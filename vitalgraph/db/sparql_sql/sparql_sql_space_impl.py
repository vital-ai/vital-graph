"""
Pure-PostgreSQL space backend using the V2 SPARQL-to-SQL pipeline.

No Fuseki dependency — SPARQL queries and updates are compiled by the
Jena sidecar into an algebra, then translated to SQL and executed
directly against PostgreSQL.

Implements ``SpaceBackendInterface`` and ``SparqlBackendInterface``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from rdflib import URIRef, Literal, BNode
from rdflib.term import Identifier

from ..space_backend_interface import SpaceBackendInterface, SparqlBackendInterface
from .sparql_sql_db_impl import SparqlSQLDbImpl
from .sparql_sql_db_objects import SparqlSQLDbObjects
from .sparql_sql_schema import SparqlSQLSchema, STANDARD_DATATYPES
from .compile_cache import SparqlCompileCache
from .generator import invalidate_datatype_cache
from . import db_provider

logger = logging.getLogger(__name__)

def _lexical_form(value: Any, datatype: Optional[str]) -> str:
    """The literal's lexical form, as the caller should see it.

    Delegates to `sql_type_binding.normalize_numeric`, which is where the rule
    lives. Written inline here first and then moved: two copies of one
    formatting rule is how the regex flag mapping let a performance heuristic
    change query semantics, and the DAWG path goes through the shared function
    rather than this one — so an inline copy here would have fixed the binding
    builder nobody was measuring.
    """
    from .sql_type_binding import normalize_numeric
    if isinstance(value, float) and datatype:
        return normalize_numeric(value, datatype)
    return str(value)

# Module-level shared compile cache (space-independent, sidecar compilation
# depends only on SPARQL structure, not on which space is queried).
_compile_cache = SparqlCompileCache(maxsize=512)

# Deterministic UUID namespace (same as fuseki_postgresql for compatibility)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

# Read-path fence, enforced by PostgreSQL rather than by the client.
#
# asyncpg's `command_timeout` already cancels a slow query, but it fires from an
# event-loop callback: if the loop stalls — `utils/event_loop_monitor.py` exists
# because that is a live concern — or the worker is killed mid-query, the
# callback never runs and the query is genuinely unbounded. PostgreSQL will not
# notice a dead client on a long SELECT until it tries to return rows. A real
# `statement_timeout` is enforced by the backend regardless of client health.
# See issues/044 gap 5.
#
# Deliberately BELOW asyncpg's 60s command_timeout, which issues/044 gap 3
# records as being ordered backwards against the client's own 60s per-attempt
# budget: whoever fires first should be the server, so the client gets a real
# error to surface instead of abandoning a query that keeps running.
#
# READ PATH ONLY. It is applied where SPARQL SELECT executes, not on the pool,
# so bulk load and index rebuild — which share that pool — are untouched.
# Bounding those by a read-shaped timeout is a live risk on a large load, not a
# hypothetical one (issues/044 records COPY already being capped at 60s by
# command_timeout).
_READ_STATEMENT_TIMEOUT_MS_DEFAULT = 55_000


def _read_statement_timeout_ms() -> int:
    """Milliseconds for the read-path `statement_timeout`.

    Overridable with `VITALGRAPH_READ_STATEMENT_TIMEOUT_MS` so an operator can
    raise it for a deliberately long analytical query without a code change. A
    value of 0 disables the fence, which is what an offline job wants and what a
    served request never should.
    """
    raw = os.environ.get("VITALGRAPH_READ_STATEMENT_TIMEOUT_MS")
    if raw is None:
        return _READ_STATEMENT_TIMEOUT_MS_DEFAULT
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("VITALGRAPH_READ_STATEMENT_TIMEOUT_MS=%r is not an "
                       "integer; using %d", raw, _READ_STATEMENT_TIMEOUT_MS_DEFAULT)
        return _READ_STATEMENT_TIMEOUT_MS_DEFAULT


async def _apply_read_fence(conn) -> None:
    """Set the read-path `statement_timeout` for the current transaction.

    Must be called inside a transaction: `SET LOCAL` is scoped to it, which is
    what stops the setting leaking onto a pooled connection and silently
    fencing whatever runs on it next — including a write.

    Zero means no fence. PostgreSQL spells that `statement_timeout = 0`, which
    is also what the session already inherits, so this does nothing rather than
    emitting a statement that would be a no-op.
    """
    ms = _read_statement_timeout_ms()
    if ms > 0:
        await conn.execute(f"SET LOCAL statement_timeout = '{ms}ms'")


def _generate_term_uuid(
    term_text: str, term_type: str,
    lang: Optional[str] = None, datatype_id: Optional[int] = None,
) -> uuid.UUID:
    """Deterministic UUID v5 for an RDF term — matches fuseki_postgresql."""
    # Normalised first, so the two spellings of a blank node cannot hash to
    # two different terms however the caller spelled it (issues/065).
    from .term_normalize import normalize_term_text
    term_text = normalize_term_text(term_text, term_type)
    parts = [term_text, term_type]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))


def _concrete_subjects_from_update_ops(ops) -> set:
    """Return the set of concrete (URI) subject strings a SPARQL update touches.

    Covers the literal quads of INSERT/DELETE DATA, DELETE WHERE, and the
    (concrete parts of) INSERT/DELETE templates in MODIFY. Subjects that are
    variables (bound by a WHERE clause) are skipped — they can't be enumerated
    without executing, and are handled by the background edge self-heal.
    Used to keep {space}_edge in sync after execute_sparql_update.
    """
    from ..jena_sparql.jena_types import (
        URINode, UpdateDataInsert, UpdateDataDelete, UpdateModify, UpdateDeleteWhere,
    )
    subjects: set = set()
    for op in ops or []:
        if isinstance(op, (UpdateDataInsert, UpdateDataDelete, UpdateDeleteWhere)):
            quads = getattr(op, 'quads', [])
        elif isinstance(op, UpdateModify):
            quads = list(getattr(op, 'delete_quads', [])) + list(getattr(op, 'insert_quads', []))
        else:
            continue
        for q in quads:
            if isinstance(q.subject, URINode):
                subjects.add(q.subject.value)
    return subjects


def _has_where_bound_delete(ops) -> bool:
    """Does this update DELETE quads whose subject is a variable?

    Those subjects cannot be enumerated before executing, so the per-subject
    edge hooks cannot run for them. Everything else in an update is handled
    directly; this is the one case that needs a referential sweep afterwards.

    Detected rather than assumed, because the sweep costs an anti-join over the
    edge table and paying it on every update — including the overwhelmingly
    common all-concrete ones — would be a real per-write regression.
    """
    from ..jena_sparql.jena_types import (
        URINode, UpdateDataDelete, UpdateModify, UpdateDeleteWhere,
    )
    for op in ops or []:
        if isinstance(op, (UpdateDataDelete, UpdateDeleteWhere)):
            quads = getattr(op, 'quads', [])
        elif isinstance(op, UpdateModify):
            quads = list(getattr(op, 'delete_quads', []))
        else:
            continue
        for q in quads:
            if not isinstance(q.subject, URINode):
                return True
    return False


def _concrete_predicates_from_update_ops(ops) -> set:
    """Predicate URIs an update inserts or deletes with, where concrete.

    A SPARQL update usually binds its subject and object but names the predicate
    literally — `DELETE WHERE { ?s <p> ?o }`. So even when the affected quads
    cannot be enumerated, the set of predicates whose counts moved is known, and
    recomputing those is bounded by one predicate's rows.

    Used to keep rdf_stats true after execute_sparql_update, which otherwise
    maintains no stats at all (issues/068).
    """
    from ..jena_sparql.jena_types import (
        URINode, UpdateDataInsert, UpdateDataDelete, UpdateModify,
        UpdateDeleteWhere,
    )
    preds: set = set()
    for op in ops or []:
        if isinstance(op, (UpdateDataInsert, UpdateDataDelete, UpdateDeleteWhere)):
            quads = getattr(op, 'quads', [])
        elif isinstance(op, UpdateModify):
            quads = (list(getattr(op, 'delete_quads', []))
                     + list(getattr(op, 'insert_quads', [])))
        else:
            continue
        for q in quads:
            if isinstance(q.predicate, URINode):
                preds.add(q.predicate.value)
    return preds


def _cleared_graphs_from_update_ops(ops) -> set:
    """Graph URIs a SPARQL update empties via CLEAR or DROP.

    These forms name no subjects, so `_concrete_subjects_from_update_ops`
    returns nothing for them and the per-subject edge hooks never run — leaving
    every edge row of the dropped graph orphaned while its quads are gone
    (issues/064).

    Only a NAMED graph is returned. `CLEAR ALL` / `CLEAR DEFAULT` are
    deliberately not handled here: they are not scoped to one context, and
    guessing a context to delete by would be worse than leaving it to the
    background orphan cleanup, which is bounded and correct for any shape.
    """
    from ..jena_sparql.jena_types import UpdateClear, UpdateDrop
    graphs: set = set()
    for op in ops or []:
        if not isinstance(op, (UpdateClear, UpdateDrop)):
            continue
        g = getattr(op, 'graph', None)
        if g:
            graphs.add(g)
        else:
            target = (getattr(op, 'target', '') or '')
            # A target that is itself a URI rather than DEFAULT/NAMED/ALL.
            if target and target not in ("DEFAULT", "NAMED", "ALL"):
                graphs.add(target)
    return graphs


class _SparqlSQLGraphsAdapter:
    """Lightweight adapter so endpoint code can call ``db_space_impl.graphs.list_graphs()``
    and ``db_space_impl.graphs.get_graph()`` exactly like the fuseki_postgresql backend."""

    def __init__(self, space_impl: 'SparqlSQLSpaceImpl'):
        self._impl = space_impl

    async def list_graphs(self, space_id: str) -> List[Dict[str, Any]]:
        rows = await self._impl.list_graphs(space_id)

        # A space with exactly ONE graph can take the catalog estimate: every
        # quad in the table belongs to that graph, so the table-level
        # `reltuples` IS the graph's count. 1.7 ms against 4,591 ms, and exact
        # or near-exact on every quad table measured here.
        #
        # This is only sound because of the "exactly one" test. With two graphs
        # the table total says nothing about either of them, and there is no
        # per-context estimate in the catalog — those keep the cached exact
        # count.
        #
        # The estimate is used for DISPLAY. `list_graphs` and `get_graph` are
        # its only callers and both feed the UI; nothing verifies a load against
        # it. If that changes, the caller should ask for the exact count.
        single_graph_estimate = None
        if len(rows) == 1:
            single_graph_estimate = await self._impl.get_rdf_quad_count_estimate(space_id)

        # Normalise to the dict shape the endpoint expects
        graphs = []
        for r in rows:
            graph_uri = r.get('graph_uri')
            triple_count = 0
            if graph_uri:
                if single_graph_estimate is not None:
                    triple_count = single_graph_estimate
                else:
                    try:
                        triple_count = await self._impl.get_rdf_quad_count(space_id, graph_uri)
                    except Exception:
                        pass
            graphs.append({
                'graph_uri': graph_uri,
                'graph_name': r.get('graph_name'),
                'triple_count': triple_count,
                'created_time': r.get('created_time'),
                'updated_time': None,
            })
        return graphs

    async def get_graph(self, space_id: str, graph_uri: str) -> Optional[Dict[str, Any]]:
        rows = await self._impl._db.execute_query(
            "SELECT graph_uri, graph_name, created_time FROM graph "
            "WHERE space_id = $1 AND graph_uri = $2",
            [space_id, graph_uri],
        )
        if not rows:
            return None
        r = rows[0]
        triple_count = 0
        try:
            triple_count = await self._impl.get_rdf_quad_count(space_id, graph_uri)
        except Exception:
            pass
        return {
            'graph_uri': r.get('graph_uri'),
            'graph_name': r.get('graph_name'),
            'triple_count': triple_count,
            'created_time': r.get('created_time'),
            'updated_time': None,
        }

    async def create_graph(self, space_id: str, graph_uri: str,
                           graph_name: Optional[str] = None) -> bool:
        return await self._impl.create_graph(space_id, graph_uri, graph_name)

    async def drop_graph(self, space_id: str, graph_uri: str) -> bool:
        return await self._impl.drop_graph(space_id, graph_uri)

    async def clear_graph(self, space_id: str, graph_uri: str) -> bool:
        """Clear all quads for a graph but keep the graph record."""
        try:
            t = self._impl.schema.get_table_names(space_id)
            async with self._impl._db._pool.acquire() as conn:
                ctx_uuid = await conn.fetchval(
                    f"SELECT term_uuid FROM {t['term']} "
                    f"WHERE term_text = $1 AND term_type = 'U'",
                    graph_uri,
                )
                if ctx_uuid:
                    await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} WHERE context_uuid = $1",
                        ctx_uuid,
                    )
            # Invalidate entity graph + count cache (local, synchronous)
            try:
                from ...cache.entity_graph_cache import _entity_graph_cache
                from ...cache.count_cache import _count_cache
                _entity_graph_cache.invalidate_graph(space_id, graph_uri)
                _count_cache.invalidate_graph(space_id, graph_uri)
            except Exception:
                pass
            # Notify other instances of graph clear
            try:
                sm = self._impl._signal_manager or (
                    self._impl.db_impl.get_signal_manager() if self._impl.db_impl else None)
                if sm:
                    from vitalgraph.signal.signal_manager import SIGNAL_TYPE_UPDATED
                    await sm.notify_graphs_changed(SIGNAL_TYPE_UPDATED)
                    await sm.notify_graph_changed(graph_uri, SIGNAL_TYPE_UPDATED, space_id=space_id)
            except Exception as ne:
                logger.debug("Graph clear notify failed (non-critical): %s", ne)
            return True
        except Exception as e:
            logger.error("clear_graph(%s, %s) failed: %s", space_id, graph_uri, e)
            return False


class _SparqlSQLTransaction:
    """Async context-manager transaction wrapper for the sparql_sql backend.

    Mirrors ``FusekiPostgreSQLTransaction`` so that ``execute_with_transaction``
    in impl_utils.py works identically for both backends.
    """

    def __init__(self, connection, transaction, pool):
        self.connection = connection
        self.transaction = transaction
        self.pool = pool
        self._committed = False
        self._rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and not self._committed and not self._rolled_back:
            await self.commit()
        elif not self._rolled_back:
            await self.rollback()
        await self.pool.release(self.connection)

    async def commit(self):
        if not self._committed and not self._rolled_back:
            await self.transaction.commit()
            self._committed = True

    async def rollback(self):
        if not self._committed and not self._rolled_back:
            await self.transaction.rollback()
            self._rolled_back = True

    def get_connection(self):
        return self.connection


class _SparqlSQLCoreAdapter:
    """Provides ``create_transaction()`` so endpoint impl_utils can open
    transactions on the sparql_sql backend identically to fuseki_postgresql."""

    def __init__(self, space_impl: 'SparqlSQLSpaceImpl'):
        self._impl = space_impl

    async def create_transaction(self, space_impl=None) -> _SparqlSQLTransaction:
        pool = self._impl._db._pool
        conn = await pool.acquire()
        tr = conn.transaction()
        await tr.start()
        return _SparqlSQLTransaction(conn, tr, pool)


class _SparqlSQLDbOpsAdapter:
    """Mirrors ``FusekiPostgreSQLDbOps`` — delegates to methods already on
    ``SparqlSQLSpaceImpl`` so that ``ObjectsImpl`` (and friends) can call
    ``db_space_impl.db_ops.add_rdf_quads_batch()`` etc."""

    def __init__(self, space_impl: 'SparqlSQLSpaceImpl'):
        self._impl = space_impl

    async def add_rdf_quads_batch(self, space_id: str, quads: list,
                                  transaction=None, auto_commit: bool = True) -> int:
        if not quads:
            return 0
        conn = transaction.get_connection() if transaction else None
        return await self._impl.add_rdf_quads_batch(
            space_id, quads, connection=conn)

    async def remove_rdf_quads_batch(self, space_id: str, quads: list,
                                     transaction=None, auto_commit: bool = True) -> int:
        if not quads:
            return 0
        return await self._impl.remove_rdf_quads_batch(space_id, quads)

    async def add_rdf_quads_batch_bulk(self, space_id: str, quads: list,
                                      connection=None) -> int:
        if not quads:
            return 0
        return await self._impl.add_rdf_quads_batch_bulk(
            space_id, quads, connection=connection)

    async def remove_rdf_quads_batch_bulk(self, space_id: str, quads: list,
                                          connection=None) -> int:
        if not quads:
            return 0
        return await self._impl.remove_rdf_quads_batch_bulk(
            space_id, quads, connection=connection)

    async def remove_quads_by_subject_uris(self, space_id: str,
                                           subject_uris: list,
                                           graph_id: Optional[str] = None,
                                           transaction=None) -> int:
        """Remove all quads for the given subject URIs."""
        if not subject_uris:
            return 0
        if graph_id is None:
            graph_id = "main"
        t = self._impl.schema.get_table_names(space_id)
        removed = 0
        async with self._impl._db._pool.acquire() as conn:
            for uri in subject_uris:
                s_uuid = _generate_term_uuid(uri, 'U')
                result = await conn.execute(
                    f"DELETE FROM {t['rdf_quad']} WHERE subject_uuid = $1",
                    s_uuid,
                )
                if 'DELETE' in result:
                    removed += 1
        return removed


class SparqlSQLSpaceImpl(SpaceBackendInterface, SparqlBackendInterface):
    """
    PostgreSQL-only space backend powered by the V2 SPARQL-to-SQL pipeline.

    Lifecycle:
        impl = SparqlSQLSpaceImpl(postgresql_config, sidecar_config)
        await impl.connect()
        ...
        await impl.disconnect()
    """

    def __init__(
        self,
        postgresql_config: dict,
        sidecar_config: Optional[dict] = None,
    ):
        self.postgresql_config = postgresql_config
        self.sidecar_config = sidecar_config or {}
        self.sidecar_url: str = self.sidecar_config.get(
            'url', 'http://localhost:7070'
        )
        self.schema = SparqlSQLSchema()

        # Owned components (created on connect)
        self.db_impl: Optional[SparqlSQLDbImpl] = None
        self.connected = False
        self._signal_manager = None

        # Database objects layer (mirrors FusekiPostgreSQLDbObjects API)
        self.db_objects = SparqlSQLDbObjects(self)

        # Graph management adapter (mirrors FusekiPostgreSQLSpaceGraphs API)
        self.graphs = _SparqlSQLGraphsAdapter(self)

        # Database operations adapter (mirrors FusekiPostgreSQLDbOps API)
        self.db_ops = _SparqlSQLDbOpsAdapter(self)

        # Core adapter (provides create_transaction)
        self.core = _SparqlSQLCoreAdapter(self)

        # Shared async HTTP client for sidecar (created lazily)
        self._sidecar_client = None

        logger.info("SparqlSQLSpaceImpl initialized (sidecar=%s)", self.sidecar_url)

    @property
    def _db(self) -> SparqlSQLDbImpl:
        """Return db_impl, raising if not connected."""
        if self.db_impl is None:
            raise RuntimeError("SparqlSQLSpaceImpl not connected — call connect() first")
        return self.db_impl

    # ==================================================================
    # Connection lifecycle
    # ==================================================================

    async def connect(self) -> bool:
        """Create asyncpg pool, configure db_provider, verify admin tables."""
        try:
            self.db_impl = SparqlSQLDbImpl(self.postgresql_config)
            ok = await self.db_impl.connect()
            if not ok:
                return False

            # Configure the V2 pipeline's db_provider with our pool
            if not db_provider.is_configured():
                db_provider.configure(self.db_impl)

            self.connected = True
            logger.info("SparqlSQLSpaceImpl connected")
            return True

        except Exception as e:
            logger.error("SparqlSQLSpaceImpl connect failed: %s", e)
            return False

    async def disconnect(self) -> bool:
        """Shut down the asyncpg pool and sidecar client."""
        try:
            if self._sidecar_client:
                await self._sidecar_client.close()
                self._sidecar_client = None
            if self.db_impl:
                await self.db_impl.disconnect()
            self.connected = False
            logger.info("SparqlSQLSpaceImpl disconnected")
            return True
        except Exception as e:
            logger.error("SparqlSQLSpaceImpl disconnect error: %s", e)
            return False

    def close(self) -> None:
        """Synchronous close (for shutdown hooks)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.disconnect())
            else:
                loop.run_until_complete(self.disconnect())
        except Exception:
            pass

    def _get_sidecar_client(self):
        """Return a shared AsyncSidecarClient, creating it lazily on first use."""
        if self._sidecar_client is None:
            from ..jena_sparql.jena_sidecar_client import AsyncSidecarClient
            self._sidecar_client = AsyncSidecarClient(base_url=self.sidecar_url)
        return self._sidecar_client

    @asynccontextmanager
    async def get_db_connection(self):
        """Yield an asyncpg connection from the pool."""
        if not self.connected or not self.db_impl or not self.db_impl.connection_pool:
            raise RuntimeError("SparqlSQLSpaceImpl not connected")
        async with self._db._pool.acquire() as conn:
            yield conn

    # ==================================================================
    # Space lifecycle
    # ==================================================================

    async def create_space_storage(self, space_id: str,
                                   partition_quads: int = 0) -> bool:
        try:
            async with self._db._pool.acquire() as conn:
                await SparqlSQLSchema.create_space(conn, space_id, partition_quads)
            return True
        except Exception as e:
            logger.error("create_space_storage(%s) failed: %s", space_id, e)
            return False

    async def delete_space_storage(self, space_id: str) -> bool:
        try:
            async with self._db._pool.acquire() as conn:
                await SparqlSQLSchema.drop_space(conn, space_id)
                # Remove graph records
                await conn.execute(
                    "DELETE FROM graph WHERE space_id = $1", space_id
                )
                # Remove space metadata
                await conn.execute(
                    "DELETE FROM space WHERE space_id = $1", space_id
                )
            return True
        except Exception as e:
            logger.error("delete_space_storage(%s) failed: %s", space_id, e)
            return False

    async def space_exists(self, space_id: str) -> bool:
        try:
            async with self._db._pool.acquire() as conn:
                return await SparqlSQLSchema.space_tables_exist(conn, space_id)
        except Exception as e:
            logger.error("space_exists(%s) failed: %s", space_id, e)
            return False

    async def get_space_metadata(self, space_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single space row from the space table, or None if not found."""
        try:
            rows = await self._db.execute_query(
                "SELECT space_id, space_name, space_description, tenant, update_time "
                "FROM space WHERE space_id = $1",
                [space_id],
            )
            return rows[0] if rows else None
        except Exception as e:
            logger.error("get_space_metadata(%s) failed: %s", space_id, e)
            return None

    async def list_spaces(self) -> List[Dict[str, Any]]:
        """List all spaces from PostgreSQL admin tables."""
        try:
            results = await self._db.execute_query(
                "SELECT * FROM space ORDER BY space_id"
            )
            return results
        except Exception as e:
            logger.error("list_spaces failed: %s", e)
            return []

    async def get_space_info(self, space_id: str) -> Dict[str, Any]:
        try:
            t = self.schema.get_table_names(space_id)

            # Both are WHOLE-TABLE counts, which is exactly what the catalog
            # estimate answers. Measured on `sp_lead_synth_100k`: these two
            # exact counts were 3,624-4,397 ms on EVERY call — the space page
            # loading in ~15 s each time — against 50.5M quads and 10.4M terms.
            # `reltuples` was exact for six of eight quad tables here and 0.635%
            # out on the worst, which a space-info panel does not care about.
            #
            # Not cached, deliberately: a catalog read is already cheap, and
            # caching an estimate stacks staleness on staleness.
            quad_count = await self._table_row_estimate(t['rdf_quad'])
            term_count = await self._table_row_estimate(t['term'])
            estimated = quad_count is not None and term_count is not None

            # Fall back to exact only when the catalog has no usable number —
            # a table that has never been analysed reports -1 (PG14+).
            if quad_count is None or term_count is None:
                async with self._db._pool.acquire() as conn:
                    if quad_count is None:
                        quad_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {t['rdf_quad']}")
                    if term_count is None:
                        term_count = await conn.fetchval(
                            f"SELECT COUNT(*) FROM {t['term']}")
            # Graph records
            graph_rows = await self._db.execute_query(
                "SELECT graph_uri, graph_name FROM graph WHERE space_id = $1",
                [space_id],
            )
            return {
                'space_id': space_id,
                'backend_type': 'sparql_sql',
                'quad_count': quad_count,
                'term_count': term_count,
                'counts_estimated': estimated,
                'graphs': graph_rows,
            }
        except Exception as e:
            logger.error("get_space_info(%s) failed: %s", space_id, e)
            return {'space_id': space_id, 'error': str(e)}

    # ==================================================================
    # Space metadata
    # ==================================================================

    async def create_space_metadata(self, space_id: str, metadata: Dict[str, Any]) -> bool:
        try:
            await self._db.execute_query(
                """INSERT INTO space (space_id, space_name, space_description, tenant, update_time)
                   VALUES ($1, $2, $3, $4, NOW())
                   ON CONFLICT (space_id) DO UPDATE SET
                       space_name = EXCLUDED.space_name,
                       space_description = EXCLUDED.space_description,
                       tenant = EXCLUDED.tenant,
                       update_time = NOW()""",
                [
                    space_id,
                    metadata.get('space_name', space_id),
                    metadata.get('space_description', ''),
                    metadata.get('tenant', 'default'),
                ],
            )
            return True
        except Exception as e:
            logger.error("create_space_metadata(%s) failed: %s", space_id, e)
            return False

    async def update_space_metadata(self, space_id: str, metadata: Dict[str, Any]) -> bool:
        """Update space_name and/or space_description in the space table."""
        try:
            sets = []
            params = []
            idx = 1

            if 'space_name' in metadata:
                sets.append(f"space_name = ${idx}")
                params.append(metadata['space_name'])
                idx += 1
            if 'space_description' in metadata:
                sets.append(f"space_description = ${idx}")
                params.append(metadata['space_description'])
                idx += 1

            if not sets:
                return True  # nothing to update

            sets.append(f"update_time = NOW()")
            params.append(space_id)

            sql = f"UPDATE space SET {', '.join(sets)} WHERE space_id = ${idx}"
            await self._db.execute_query(sql, params)
            return True
        except Exception as e:
            logger.error("update_space_metadata(%s) failed: %s", space_id, e)
            return False

    # ==================================================================
    # Graph auto-registration (mirrors fuseki_postgresql DualWriteCoordinator)
    # ==================================================================

    def _extract_graph_uris_from_quads(
        self, quads: List[Tuple[Any, ...]],
    ) -> List[str]:
        """Extract unique graph URIs from quad tuples, excluding 'default'."""
        graph_uris: set = set()
        for quad in quads:
            if len(quad) >= 4:
                g = quad[3]
                g_str = str(g) if g else None
                if g_str and g_str != 'default':
                    graph_uris.add(g_str)
        return list(graph_uris)

    async def _ensure_graphs_registered(
        self, space_id: str, quads: list,
    ) -> None:
        """Auto-register every graph URI found in *quads* that is not yet
        in the ``graph`` table.  This replicates the side-effect that the
        fuseki_postgresql backend has: inserting data into a graph URI
        implicitly creates the graph record."""
        graph_uris = self._extract_graph_uris_from_quads(quads)
        if not graph_uris:
            return
        try:
            existing = await self._db.execute_query(
                "SELECT graph_uri FROM graph WHERE space_id = $1",
                [space_id],
            )
            existing_set = {r['graph_uri'] for r in existing} if existing else set()
            for uri in graph_uris:
                if uri not in existing_set:
                    graph_name = uri.rsplit('/', 1)[-1]
                    await self._db.execute_query(
                        """INSERT INTO graph (space_id, graph_uri, graph_name, created_time)
                           VALUES ($1, $2, $3, $4)
                           ON CONFLICT (space_id, graph_uri) DO NOTHING""",
                        [space_id, uri, graph_name, datetime.now()],
                    )
                    logger.debug("Auto-registered graph %s in space %s", uri, space_id)
        except Exception as e:
            logger.warning("_ensure_graphs_registered(%s) failed: %s", space_id, e)

    # ==================================================================
    # Graph management
    # ==================================================================

    async def create_graph(self, space_id: str, graph_uri: str,
                           graph_name: Optional[str] = None) -> bool:
        try:
            if graph_name is None:
                graph_name = graph_uri.rsplit('/', 1)[-1]
            await self._db.execute_query(
                """INSERT INTO graph (space_id, graph_uri, graph_name, created_time)
                   VALUES ($1, $2, $3, $4)""",
                [space_id, graph_uri, graph_name, datetime.now()],
            )
            # Notify other instances of graph creation
            try:
                sm = self._signal_manager or (self.db_impl.get_signal_manager() if self.db_impl else None)
                if sm:
                    from vitalgraph.signal.signal_manager import SIGNAL_TYPE_CREATED
                    await sm.notify_graphs_changed(SIGNAL_TYPE_CREATED)
                    await sm.notify_graph_changed(graph_uri, SIGNAL_TYPE_CREATED, space_id=space_id)
            except Exception as ne:
                logger.debug("Graph creation notify failed (non-critical): %s", ne)
            return True
        except Exception as e:
            logger.error("create_graph(%s, %s) failed: %s", space_id, graph_uri, e)
            return False

    async def drop_graph(self, space_id: str, graph_uri: str) -> bool:
        try:
            # Remove quads for this graph
            t = self.schema.get_table_names(space_id)
            async with self._db._pool.acquire() as conn:
                ctx_uuid = await conn.fetchval(
                    f"SELECT term_uuid FROM {t['term']} "
                    f"WHERE term_text = $1 AND term_type = 'U'",
                    graph_uri,
                )
                if ctx_uuid:
                    await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} WHERE context_uuid = $1",
                        ctx_uuid,
                    )
            # Remove graph record
            await self._db.execute_query(
                "DELETE FROM graph WHERE space_id = $1 AND graph_uri = $2",
                [space_id, graph_uri],
            )
            # Invalidate entity graph + count cache (local, synchronous)
            try:
                from ...cache.entity_graph_cache import _entity_graph_cache
                from ...cache.count_cache import _count_cache
                _entity_graph_cache.invalidate_graph(space_id, graph_uri)
                _count_cache.invalidate_graph(space_id, graph_uri)
            except Exception:
                pass
            # Notify other instances of graph deletion
            try:
                sm = self._signal_manager or (self.db_impl.get_signal_manager() if self.db_impl else None)
                if sm:
                    from vitalgraph.signal.signal_manager import SIGNAL_TYPE_DELETED
                    await sm.notify_graphs_changed(SIGNAL_TYPE_DELETED)
                    await sm.notify_graph_changed(graph_uri, SIGNAL_TYPE_DELETED, space_id=space_id)
            except Exception as ne:
                logger.debug("Graph deletion notify failed (non-critical): %s", ne)
            return True
        except Exception as e:
            logger.error("drop_graph(%s, %s) failed: %s", space_id, graph_uri, e)
            return False

    async def list_graphs(self, space_id: str) -> List[Dict[str, Any]]:
        try:
            return await self._db.execute_query(
                "SELECT graph_uri, graph_name, created_time FROM graph "
                "WHERE space_id = $1 ORDER BY graph_uri",
                [space_id],
            )
        except Exception as e:
            logger.error("list_graphs(%s) failed: %s", space_id, e)
            return []

    # ==================================================================
    # Term management
    # ==================================================================

    async def add_term(self, space_id: str, term_text: str, term_type: str,
                       lang: Optional[str] = None,
                       datatype_id: Optional[int] = None) -> Optional[str]:
        try:
            term_uuid = _generate_term_uuid(term_text, term_type, lang, datatype_id)
            t = self.schema.get_table_names(space_id)
            async with self._db._pool.acquire() as conn:
                await conn.execute(
                    f"INSERT INTO {t['term']} "
                    f"(term_uuid, term_text, term_type, lang, datatype_id) "
                    f"VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
                    term_uuid, term_text, term_type, lang, datatype_id,
                )
            return str(term_uuid)
        except Exception as e:
            logger.error("add_term(%s) failed: %s", space_id, e)
            return None

    async def get_term_uuid(self, space_id: str, term_text: str, term_type: str,
                            lang: Optional[str] = None,
                            datatype_id: Optional[int] = None) -> Optional[str]:
        term_uuid = _generate_term_uuid(term_text, term_type, lang, datatype_id)
        return str(term_uuid)

    async def delete_term(self, space_id: str, term_text: str, term_type: str,
                          lang: Optional[str] = None,
                          datatype_id: Optional[int] = None) -> bool:
        try:
            term_uuid = _generate_term_uuid(term_text, term_type, lang, datatype_id)
            t = self.schema.get_table_names(space_id)
            async with self._db._pool.acquire() as conn:
                await conn.execute(
                    f"DELETE FROM {t['term']} WHERE term_uuid = $1", term_uuid,
                )
            return True
        except Exception as e:
            logger.error("delete_term(%s) failed: %s", space_id, e)
            return False

    # ==================================================================
    # RDF quad operations
    # ==================================================================

    async def add_rdf_quad(self, space_id: str, quad: Union[tuple, list]) -> bool:
        try:
            await self._ensure_graphs_registered(space_id, [quad])
            s, p, o, g = quad
            t = self.schema.get_table_names(space_id)
            async with self._db._pool.acquire() as conn:
                # Atomic: term + quad + edge/frame sync run in one transaction so
                # a raise on any statement rolls back cleanly rather than leaving
                # the pooled connection in an aborted state (issue 019 hardening).
                async with conn.transaction():
                    s_uuid = await self._ensure_term(conn, t, s)
                    p_uuid = await self._ensure_term(conn, t, p)
                    o_uuid = await self._ensure_term(conn, t, o)
                    g_uuid = await self._ensure_term(conn, t, g)
                    await conn.execute(
                        f"INSERT INTO {t['rdf_quad']} "
                        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                        f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                        s_uuid, p_uuid, o_uuid, g_uuid,
                    )
                    # Keep {space}_edge in sync — this path bypasses the bulk sync,
                    # so edge quads inserted here would otherwise never reach the
                    # edge table (see edge_table_integrity_bug). Cheap + idempotent.
                    # frame_entity is derived from the edge table, so sync it after.
                    from .sync_edge_table import sync_edge_table_after_insert
                    await sync_edge_table_after_insert(conn, space_id, [s_uuid])
                    from .sync_frame_entity_table import sync_frame_entity_after_edge_insert
                    await sync_frame_entity_after_edge_insert(conn, space_id, [s_uuid])
                    # entity_slot_sort is derived from edge as well (issues/096).
                    from .sync_entity_slot_sort import sync_entity_slot_sort_after_edge_insert
                    await sync_entity_slot_sort_after_edge_insert(conn, space_id, [s_uuid])
                    # Stats too. The comment above explains why edge and
                    # frame_entity were added — "this path bypasses the bulk
                    # sync" — and stats were simply not part of that thought,
                    # so rdf_pred_stats and rdf_stats silently under-counted
                    # every quad inserted here. Same reasoning, same fix.
                    from .sync_stats_tables import sync_stats_after_insert
                    await sync_stats_after_insert(
                        conn, space_id, [(s_uuid, p_uuid, o_uuid, g_uuid)])
            self._invalidate_counts_for_quads(space_id, [quad])
            return True
        except Exception as e:
            logger.error("add_rdf_quad(%s) failed: %s", space_id, e)
            return False

    async def remove_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        try:
            t = self.schema.get_table_names(space_id)
            s_uuid = _generate_term_uuid(s, 'U')
            p_uuid = _generate_term_uuid(p, 'U')
            o_uuid = _generate_term_uuid(o, self._infer_type(o))
            g_uuid = _generate_term_uuid(g, 'U')
            async with self._db._pool.acquire() as conn:
                # Atomic, and the derived tables go first — frame_entity before
                # edge because it derives from it, and both before the quad is
                # gone because the sync helpers read it to know what to remove.
                # This path maintained nothing at all, the mirror of
                # add_rdf_quad, which syncs edge and frame_entity but not stats.
                async with conn.transaction():
                    from .sync_frame_entity_table import sync_frame_entity_before_delete
                    await sync_frame_entity_before_delete(conn, space_id, [s_uuid])
                    from .sync_entity_slot_sort import sync_entity_slot_sort_before_delete
                    await sync_entity_slot_sort_before_delete(conn, space_id, [s_uuid])
                    from .sync_edge_table import sync_edge_table_before_delete
                    await sync_edge_table_before_delete(conn, space_id, [s_uuid])
                    from .sync_stats_tables import sync_stats_after_delete
                    await sync_stats_after_delete(
                        conn, space_id, [(s_uuid, p_uuid, o_uuid, g_uuid)])
                    await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} "
                        f"WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                        f"AND object_uuid = $3 AND context_uuid = $4",
                        s_uuid, p_uuid, o_uuid, g_uuid,
                    )
            self._invalidate_counts_for_quads(space_id, [(s, p, o, g)])
            return True
        except Exception as e:
            logger.error("remove_rdf_quad(%s) failed: %s", space_id, e)
            return False

    async def get_rdf_quad(self, space_id: str, s: str, p: str, o: str, g: str) -> bool:
        try:
            t = self.schema.get_table_names(space_id)
            s_uuid = _generate_term_uuid(s, 'U')
            p_uuid = _generate_term_uuid(p, 'U')
            o_uuid = _generate_term_uuid(o, self._infer_type(o))
            g_uuid = _generate_term_uuid(g, 'U')
            async with self._db._pool.acquire() as conn:
                count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {t['rdf_quad']} "
                    f"WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                    f"AND object_uuid = $3 AND context_uuid = $4",
                    s_uuid, p_uuid, o_uuid, g_uuid,
                )
            return count > 0
        except Exception as e:
            logger.error("get_rdf_quad(%s) failed: %s", space_id, e)
            return False

    async def _table_row_estimate(self, table: str) -> Optional[int]:
        """`reltuples` for one table, or None when it cannot be trusted.

        Shared by every whole-table count. See
        `get_rdf_quad_count_estimate` for the measurements and the reasons the
        None cases exist.
        """
        try:
            async with self._db._pool.acquire() as conn:
                est = await conn.fetchval(
                    "SELECT reltuples::bigint FROM pg_class WHERE relname = $1",
                    table)
        except Exception as e:
            logger.debug("row estimate for %s failed: %s", table, e)
            return None
        if est is None or est < 0:
            return None
        return int(est)

    async def get_rdf_quad_count_estimate(self, space_id: str) -> Optional[int]:
        """Row estimate for the space's whole quad table, from the catalog.

        `pg_class.reltuples` is what the planner uses, maintained by ANALYZE,
        VACUUM and autovacuum. It is a catalog lookup: 1.7 ms against 4,591 ms
        for `COUNT(*)` over 50.5M rows — 2,700x — and on this database it was
        EXACT for six of eight quad tables, 0.0001% out on a seventh, and 0.635%
        out on the one with recent deletes.

        Returns None when there is no usable estimate, which the caller must
        treat as "do the real count":

        * PostgreSQL 14+ stores **-1** for a table that has never been analysed,
          and one table here is in that state. Returning -1 as a triple count
          would display minus one triple;
        * a table absent from `pg_class` (dropped mid-flight) has no row at all.

        Deliberately NOT cached. It is already a catalog read, and caching an
        estimate would add staleness on top of staleness.
        """
        try:
            table = self.schema.get_table_names(space_id)['rdf_quad']
        except Exception as e:
            logger.debug("get_rdf_quad_count_estimate(%s) failed: %s", space_id, e)
            return None
        return await self._table_row_estimate(table)

    async def get_rdf_quad_count(self, space_id: str,
                                  graph_uri: Optional[str] = None) -> int:
        """Exact quad count, CACHED — it is an unavoidable full count.

        `COUNT(*)` over a graph is O(the graph): measured 4,591 ms for the 50.5M
        quads of `sp_lead_synth_100k`. That is not a bad query, it is what an
        exact count costs, and no index removes it.

        It matters because this is on the DASHBOARD path. `list_graphs` calls it
        once per graph and the dashboard calls `list_graphs` once per space —
        67 of them, concurrently, which is the ~20 s page load reported from the
        UI.

        So it is cached rather than optimised. The cache already exists and its
        invalidation is already wired into every write path
        (`vitalgraphapp_impl` calls `invalidate_graph` / `invalidate_space`); it
        simply was not used here. A stale total on a dashboard is acceptable;
        the 15 minute TTL bounds it, and a write to the graph clears it at once.

        NOT cached on failure. A count that errored and cached as 0 is
        indistinguishable from a genuinely empty graph, which is the same class
        of bug as `issues/082`.
        """
        from ...cache.count_cache import _count_cache

        # Space-wide: the catalog estimate answers this directly and costs a
        # lookup. Only for the WHOLE table — there is no per-context estimate,
        # so a graph-scoped count still does the real work.
        if graph_uri is None:
            est = await self.get_rdf_quad_count_estimate(space_id)
            if est is not None:
                return est

        # Only a GRAPH-scoped count is cached, and that is deliberate.
        # Invalidation is per (space, graph): `invalidate_graph` clears keys
        # whose graph matches, so an entry stored under a synthetic
        # "whole space" graph id would survive every write and go stale until
        # the TTL. The whole-space case is answered by the catalog estimate
        # above anyway; this fall-through only runs when the table has never
        # been analysed, which is rare and correct to compute each time.
        cache_key = None
        if graph_uri is not None:
            cache_key = _count_cache.query_hash(
                f"rdf_quad_count::{space_id}::{graph_uri}")
            cached = _count_cache.get(space_id, graph_uri, cache_key)
            if cached is not None:
                return cached

        try:
            t = self.schema.get_table_names(space_id)
            async with self._db._pool.acquire() as conn:
                if graph_uri:
                    g_uuid = _generate_term_uuid(graph_uri, 'U')
                    count = await conn.fetchval(
                        f"SELECT COUNT(*) FROM {t['rdf_quad']} "
                        f"WHERE context_uuid = $1", g_uuid,
                    )
                else:
                    count = await conn.fetchval(
                        f"SELECT COUNT(*) FROM {t['rdf_quad']}"
                    )
        except Exception as e:
            logger.error("get_rdf_quad_count(%s) failed: %s", space_id, e)
            return 0

        count = int(count or 0)
        if cache_key is not None:
            _count_cache.put(space_id, graph_uri, cache_key, count)
        return count

    @staticmethod
    def _invalidate_counts_for_quads(space_id: str, quads) -> None:
        """Clear cached counts for every graph these quads touched.

        The counts behind the dashboard and the space pages are cached because
        an exact `COUNT(*)` over a graph is O(the graph). That is only sound if
        a write clears them: a stale count after an INSERT under-reports, and
        after a DELETE it reads as data that is still present.

        `clear_graph` and `drop_graph` already did this; the BATCH quad paths —
        which are how bulk load, import and the entity endpoints actually write
        — did not, so a cached count survived every ordinary write. Caught by
        `tests/integration/test_count_cache_invalidation.py`, which asserts
        against the real write path rather than calling `invalidate_graph`
        directly.

        Best effort: a cache failure must never fail a write that has already
        committed.
        """
        try:
            from ...cache.count_cache import _count_cache
            contexts = set()
            for q in quads or ():
                if len(q) >= 4 and q[3] is not None:
                    contexts.add(str(q[3]))
            for ctx in contexts:
                _count_cache.invalidate_graph(space_id, ctx)
        except Exception as e:      # pragma: no cover - defensive
            logger.debug("count cache invalidation skipped for %s: %s", space_id, e)

    async def add_rdf_quads_batch(self, space_id: str,
                                   quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]],
                                   auto_commit: bool = True,
                                   verify_count: bool = False,
                                   connection=None) -> int:
        try:
            await self._ensure_graphs_registered(space_id, quads)
            t = self.schema.get_table_names(space_id)
            inserted = 0

            subjects: set = set()
            # Rows actually inserted, for the stats sync below. Only the ones
            # that really landed: ON CONFLICT DO NOTHING means a duplicate quad
            # inserts no row, and counting it would inflate rdf_stats.
            inserted_rows: list = []

            async def _do(conn):
                nonlocal inserted
                for s, p, o, g in quads:
                    s_uuid = await self._ensure_term(conn, t, s)
                    p_uuid = await self._ensure_term(conn, t, p)
                    o_uuid = await self._ensure_term(conn, t, o)
                    g_uuid = await self._ensure_term(conn, t, g)
                    result = await conn.execute(
                        f"INSERT INTO {t['rdf_quad']} "
                        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                        f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                        s_uuid, p_uuid, o_uuid, g_uuid,
                    )
                    # asyncpg returns "INSERT <oid> <count>", so `'INSERT' in
                    # result` is true for INSERT 0 0 as well — the suppressed
                    # row counted as written. Harmless while the ON CONFLICT
                    # could never fire (nothing was ever suppressed); wrong the
                    # moment the key actually enforces (s,p,o,c), which is
                    # exactly when rdf_stats would start over-counting. Parse
                    # the count.
                    if result and result.rsplit(" ", 1)[-1].isdigit() \
                            and int(result.rsplit(" ", 1)[-1]) > 0:
                        inserted += 1
                        inserted_rows.append((s_uuid, p_uuid, o_uuid, g_uuid))
                    subjects.add(s_uuid)
                # Keep {space}_edge in sync — this path bypasses the bulk sync,
                # so edge quads inserted here would otherwise never reach the
                # edge table (see edge_table_integrity_bug). Idempotent
                # (ON CONFLICT DO NOTHING), bounded by this batch's subjects.
                # frame_entity is derived from the edge table, so sync it after.
                if subjects:
                    from .sync_edge_table import sync_edge_table_after_insert
                    await sync_edge_table_after_insert(conn, space_id, list(subjects))
                    from .sync_frame_entity_table import sync_frame_entity_after_edge_insert
                    await sync_frame_entity_after_edge_insert(conn, space_id, list(subjects))
                    from .sync_entity_slot_sort import sync_entity_slot_sort_after_edge_insert
                    await sync_entity_slot_sort_after_edge_insert(conn, space_id, list(subjects))
                # rdf_stats too. Only the BULK path synced these, so every quad
                # written through this one left the planner's cardinality
                # estimates behind — the same write-path gap as the edge table
                # (edge_table_integrity_bug), and worse, because nothing
                # self-heals stats: the maintenance job prunes them and never
                # resyncs. A stale count does not produce a wrong answer, it
                # produces a wrong PLAN, silently.
                if inserted_rows:
                    from .sync_stats_tables import sync_stats_after_insert
                    await sync_stats_after_insert(conn, space_id, inserted_rows)

            if connection:
                # Caller owns the connection/transaction — don't open a nested one.
                await _do(connection)
            else:
                # We own the connection: run the whole batch (terms + quads +
                # edge/frame sync) atomically so a raise on any statement rolls
                # back cleanly instead of poisoning the pooled connection.
                async with self._db._pool.acquire() as conn:
                    async with conn.transaction():
                        await _do(conn)

            self._invalidate_counts_for_quads(space_id, quads)
            return inserted
        except Exception as e:
            logger.error("add_rdf_quads_batch(%s) failed: %s", space_id, e)
            # RAISE, do not return 0. A count of 0 is a truthful answer to
            # "how many were written" only when nothing was ASKED for; on a
            # failure it is indistinguishable from a no-op, and every caller
            # above has to guess. issues/100 spent two days on six searches
            # that returned nothing because this returned 0 here, a caller
            # discarded it, and the API reported success. The callers already
            # have `except Exception` blocks written for this.
            raise

    async def add_rdf_quads_batch_bulk(self, space_id: str,
                                       quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]],
                                       connection=None,
                                       rebuild_indexes: Optional[bool] = None,
                                       stats_sink: Optional[list] = None) -> int:
        """Batched insert: resolve datatypes, then insert terms + quads.

        All work happens inside a single transaction.  The term/quad insert
        strategy is chosen from load context (see ``bulk_load``):

        - ``rebuild_indexes=None`` (default, auto): a large batch (>=
          ``REBUILD_MIN_QUADS``) into a currently-**empty** space drops the
          secondary indexes, COPYs, and rebuilds them once (fast initial load);
          otherwise executemany (incremental, index-live, never disrupts reads).
        - ``rebuild_indexes=True``: force the drop→COPY→rebuild path (operator
          maintenance-window load into a non-empty space — disrupts reads).
        - ``rebuild_indexes=False``: force executemany.
        """
        if not quads:
            return 0

        try:
            await self._ensure_graphs_registered(space_id, quads)

            import time as _time
            _t0 = _time.monotonic()

            t = self.schema.get_table_names(space_id)

            # ------------------------------------------------------------------
            # 0. Stamp server-managed properties on any KGEntity the batch
            #    introduces, BEFORE anything else looks at `quads`.
            #
            #    These four are server-managed, so every KGEntity acquires them
            #    eventually. Doing it here rather than in the background
            #    backfill means they ride the same COPY, the same index rebuild
            #    and the same transaction — and, critically, they are in
            #    `quad_rows` when `sync_stats_after_insert` runs below. Added
            #    afterwards by raw SQL they were not: measured on two freshly
            #    loaded fixtures, `rdf_pred_stats` held 21 of 24 predicates,
            #    missing exactly these three at 10,000 rows each, so every
            #    consumer keyed on pred_stats lost them silently.
            #
            #    It must precede the datatype scan below, or the xsd:dateTime of
            #    a creation time never reaches `dt_map` and the literal is
            #    stored untyped.
            try:
                from ...kg_impl.kg_server_properties import (
                    server_property_quads_for_import)
                from datetime import timezone as _tz
                _extra = server_property_quads_for_import(
                    quads, datetime.now(_tz.utc))
                if _extra:
                    quads = list(quads) + _extra
                    logger.debug("bulk insert: stamped %d server-property quad(s)",
                                 len(_extra))
            except Exception as exc:
                # An import that loses a server property is recoverable — the
                # backfill task still exists and will catch it. An import that
                # FAILS because of one is not.
                logger.warning("server-property stamping skipped: %s", exc)

            # 1. Collect unique datatype URIs from Literal objects
            # ------------------------------------------------------------------
            datatype_uris: set = set()
            for _s, _p, _o, _g in quads:
                for term in (_s, _p, _o, _g):
                    if isinstance(term, Literal) and term.datatype:
                        datatype_uris.add(str(term.datatype))

            # ------------------------------------------------------------------
            # 2. Resolve datatype URIs → integer IDs (one query per unique URI)
            # ------------------------------------------------------------------
            async def _resolve_all_datatypes(conn) -> Dict[str, int]:
                dt_map: Dict[str, int] = {}
                for uri in datatype_uris:
                    row = await conn.fetchrow(
                        f"SELECT datatype_id FROM {t['datatype']} WHERE datatype_uri = $1",
                        uri,
                    )
                    if row:
                        dt_map[uri] = row['datatype_id']
                    else:
                        dt_map[uri] = await conn.fetchval(
                            f"INSERT INTO {t['datatype']} (datatype_uri) "
                            f"VALUES ($1) ON CONFLICT (datatype_uri) "
                            f"DO UPDATE SET datatype_uri = EXCLUDED.datatype_uri "
                            f"RETURNING datatype_id",
                            uri,
                        )
                return dt_map

            # ------------------------------------------------------------------
            # 3. Build term rows + quad rows in Python (CPU-only, no I/O)
            # ------------------------------------------------------------------
            def _classify(term, dt_map):
                """Return (term_text, term_type, lang, datatype_id, term_uuid)."""
                term_text = str(term)
                if isinstance(term, URIRef):
                    term_type = 'U'
                elif isinstance(term, BNode):
                    term_type = 'B'
                elif isinstance(term, Literal):
                    term_type = 'L'
                else:
                    term_type = 'U'

                lang = None
                datatype_id = None
                if isinstance(term, Literal):
                    lang = term.language
                    if term.datatype:
                        datatype_id = dt_map.get(str(term.datatype))

                term_uuid = _generate_term_uuid(term_text, term_type, lang, datatype_id)
                return term_uuid, term_text, term_type, lang, datatype_id

            async def _do_bulk(conn):
                dt_map = await _resolve_all_datatypes(conn)
                _t1 = _time.monotonic()

                # Deduplicate terms by UUID
                seen_terms: Dict[uuid.UUID, tuple] = {}
                quad_rows = []

                for s, p, o, g in quads:
                    s_uuid, s_text, s_type, s_lang, s_dt = _classify(s, dt_map)
                    p_uuid, p_text, p_type, p_lang, p_dt = _classify(p, dt_map)
                    o_uuid, o_text, o_type, o_lang, o_dt = _classify(o, dt_map)
                    g_uuid, g_text, g_type, g_lang, g_dt = _classify(g, dt_map)

                    for row in (
                        (s_uuid, s_text, s_type, s_lang, s_dt),
                        (p_uuid, p_text, p_type, p_lang, p_dt),
                        (o_uuid, o_text, o_type, o_lang, o_dt),
                        (g_uuid, g_text, g_type, g_lang, g_dt),
                    ):
                        if row[0] not in seen_terms:
                            seen_terms[row[0]] = row

                    quad_rows.append((s_uuid, p_uuid, o_uuid, g_uuid))

                _t2 = _time.monotonic()

                # Insert terms + quads via the context-appropriate strategy.
                from .bulk_load import (
                    REBUILD_MIN_QUADS, insert_terms_quads_executemany,
                    bulk_load_with_index_rebuild)
                # Sorted by term_uuid: `seen_terms` is keyed in first-seen order, so
                # two batches sharing new terms inserted them in different orders and
                # could deadlock on the term PK the same way the stats tables did
                # (issues/115).
                term_args = [seen_terms[k] for k in sorted(seen_terms)]

                use_rebuild = rebuild_indexes
                quad_empty = term_empty = False
                if use_rebuild is None:  # auto: only for a large load into an empty space
                    if len(quad_rows) >= REBUILD_MIN_QUADS:
                        quad_empty = not await conn.fetchval(
                            f"SELECT EXISTS(SELECT 1 FROM {t['rdf_quad']} LIMIT 1)")
                        use_rebuild = quad_empty
                    else:
                        use_rebuild = False

                if use_rebuild:
                    # Direct-COPY terms only when the term table is also empty
                    # (else a recurring term_uuid would collide on its PK).
                    term_empty = not await conn.fetchval(
                        f"SELECT EXISTS(SELECT 1 FROM {t['term']} LIMIT 1)")
                    await bulk_load_with_index_rebuild(
                        conn, t, term_args, quad_rows,
                        self.schema.drop_space_indexes_sql(space_id),
                        self.schema.create_space_indexes_sql(space_id),
                        terms_direct=term_empty)
                    _strategy = "copy+rebuild"
                else:
                    await insert_terms_quads_executemany(
                        conn, t, term_args, quad_rows)
                    _strategy = "executemany"
                _t3 = _time.monotonic()
                _t4 = _t3  # term/quad insert is one fused strategy call

                # Sync edge table with newly inserted subjects
                from .sync_edge_table import sync_edge_table_after_insert
                unique_subjects = list({row[0] for row in quad_rows})
                edge_inserted = await sync_edge_table_after_insert(
                    conn, space_id, unique_subjects)
                _t5 = _time.monotonic()

                # Sync frame_entity table (depends on edge table)
                from .sync_frame_entity_table import sync_frame_entity_after_edge_insert
                fe_inserted = await sync_frame_entity_after_edge_insert(
                    conn, space_id, unique_subjects)
                _t5b = _time.monotonic()

                # Sync entity_slot_sort (also depends on the edge table)
                from .sync_entity_slot_sort import sync_entity_slot_sort_after_edge_insert
                await sync_entity_slot_sort_after_edge_insert(
                    conn, space_id, unique_subjects)

                # Sync stats tables
                # See the note in remove_rdf_quads_batch_bulk: a caller that
                # keeps working after this returns holds the hot rows for the
                # rest of its transaction, so it can take the deltas instead
                # and apply them once, at the end (issues/115).
                if stats_sink is None:
                    from .sync_stats_tables import sync_stats_after_insert
                    await sync_stats_after_insert(conn, space_id, quad_rows)
                else:
                    stats_sink.append(("insert", quad_rows))

                # Value histograms, for a BULK load only.
                #
                # Nothing on any write path used to build these — only an
                # explicit `resync_all`. So a space loaded through the API had
                # no histograms at all, `estimate_range` returned None for every
                # range, and the traversal criterion gate (which requires a
                # MEASURED criterion) declined every range criterion it saw. The
                # whole range-selectivity mechanism was dormant on exactly the
                # spaces that got their data through the product.
                #
                # A full rebuild is the only option — bucket BOUNDARIES move as
                # the distribution does, so there is no incremental form (see
                # `stats_table_freshness_plan.md`, candidate 4, rejected for
                # that reason). Measured: 1.3 s on 2.5M quads, 9.3 s on 19.6M.
                # Trivial next to the load it follows, and far too expensive per
                # small write.
                #
                # Hence the size gate, which splits the work between the two
                # mechanisms by what each is good at:
                #   * a BULK batch rebuilds, so the histograms are accurate;
                #   * smaller writes leave them alone, and `apply_freshness`
                #     scales for the growth or withdraws on a shape change, so
                #     they stay SAFE until the next bulk load or resync.
                if len(quad_rows) >= REBUILD_MIN_QUADS:
                    try:
                        from .sync_value_stats import resync_value_stats
                        _vs = await resync_value_stats(conn, space_id)
                        # The rebuild moves the reference every cached freshness
                        # verdict was taken against, so the verdicts have to go
                        # with it — a surviving "stale" would keep withdrawing
                        # estimates from a histogram just made correct.
                        from .generator import invalidate_stats_cache
                        invalidate_stats_cache(space_id)
                        logger.info("bulk insert: rebuilt value histograms (%s)",
                                    _vs)
                    except Exception as exc:
                        # A missing histogram degrades an estimate to an exact
                        # count. It must never fail the load that produced the
                        # data.
                        logger.warning("value histogram rebuild skipped for "
                                       "%s: %s", space_id, exc)
                _t6 = _time.monotonic()

                logger.info(
                    "⏱️  BULK insert: dt_resolve=%.3fs  classify=%.3fs  "
                    "tq_insert=%.3fs [%s] (%d terms + %d quads)  "
                    "edge_sync=%.3fs (%d)  fe_sync=%.3fs (%d)  "
                    "stats_sync=%.3fs  total=%.3fs",
                    _t1 - _t0, _t2 - _t1, _t3 - _t2, _strategy,
                    len(term_args), len(quad_rows),
                    _t5 - _t4, edge_inserted,
                    _t5b - _t5, fe_inserted,
                    _t6 - _t5b, _t6 - _t0,
                )
                return len(quad_rows)

            if connection:
                # The caller owns this transaction, so it owns the retry too.
                count = await _do_bulk(connection)
            else:
                from .deadlock_retry import with_deadlock_retry
                count = await with_deadlock_retry(
                    self._db._pool, _do_bulk,
                    what=f"add_rdf_quads_batch_bulk({space_id})")

            # Track row changes for auto-ANALYZE (outside transaction)
            from .auto_analyze import record_changes, maybe_analyze
            record_changes(space_id, count)
            self._invalidate_counts_for_quads(space_id, quads)
            async with self._db._pool.acquire() as conn:
                await maybe_analyze(conn, space_id, pg_config=self.postgresql_config)
            return count

        except Exception as e:
            logger.error("add_rdf_quads_batch_bulk(%s) failed: %s", space_id, e)
            # RAISE, do not return 0. A count of 0 is a truthful answer to
            # "how many were written" only when nothing was ASKED for; on a
            # failure it is indistinguishable from a no-op, and every caller
            # above has to guess. issues/100 spent two days on six searches
            # that returned nothing because this returned 0 here, a caller
            # discarded it, and the API reported success. The callers already
            # have `except Exception` blocks written for this.
            raise

    async def check_subjects_exist(self, space_id: str, graph_id: str,
                                    uris: List[str]) -> List[str]:
        """Return the subset of *uris* that already appear as subjects in *graph_id*.

        Uses a single SQL query with ``ANY($1)`` on an array of term UUIDs,
        avoiding the SPARQL pipeline entirely.
        """
        if not uris:
            return []
        try:
            t = self.schema.get_table_names(space_id)
            # Generate deterministic UUIDs for all candidate URIs (all are URIRefs → type 'U')
            uri_uuids = [_generate_term_uuid(uri, 'U') for uri in uris]
            # Graph context UUID
            g_uuid = _generate_term_uuid(graph_id, 'U')

            async with self._db._pool.acquire() as conn:
                rows = await conn.fetch(
                    f"SELECT DISTINCT t.term_text "
                    f"FROM {t['rdf_quad']} q "
                    f"JOIN {t['term']} t ON t.term_uuid = q.subject_uuid "
                    f"WHERE q.subject_uuid = ANY($1) AND q.context_uuid = $2",
                    uri_uuids, g_uuid,
                )
            return [row['term_text'] for row in rows]
        except Exception as e:
            logger.error("check_subjects_exist(%s) failed: %s", space_id, e)
            return []

    async def delete_entity_graph_bulk(self, space_id: str, graph_id: str,
                                       entity_uri: str) -> int:
        """Delete all quads belonging to an entity graph in one SQL operation.

        Finds all subjects whose ``hasKGGraphURI`` points to *entity_uri*,
        then deletes every quad with those subjects (within the given graph
        context) in a single ``DELETE … WHERE subject_uuid = ANY(…)`` call.
        Returns the number of deleted quads.
        """
        import time as _time
        _t0 = _time.monotonic()
        try:
            t = self.schema.get_table_names(space_id)
            g_uuid = _generate_term_uuid(graph_id, 'U')
            # Predicate UUID for hasKGGraphURI
            HAS_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI'
            p_uuid = _generate_term_uuid(HAS_KG_GRAPH_URI, 'U')
            # Object UUID for the entity URI value
            entity_uuid = _generate_term_uuid(entity_uri, 'U')

            async def _do_delete(conn):
                # Step 1: Find all subject UUIDs with hasKGGraphURI = entity_uri
                subject_rows = await conn.fetch(
                    f"SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                    f"WHERE predicate_uuid = $1 AND object_uuid = $2 AND context_uuid = $3",
                    p_uuid, entity_uuid, g_uuid,
                )
                subject_uuids = [row['subject_uuid'] for row in subject_rows]

                # THE ENTITY ITSELF, unconditionally. Membership above is a
                # snapshot of ONE mutable predicate, and the entity appears
                # in it only if it carries its own self-link — which
                # `issues/091` established entities systematically did not,
                # 619 of them across 12 spaces. Without this, deleting such
                # an entity's graph removed every member and left the root
                # behind: a typed object with nothing under it.
                if entity_uuid not in subject_uuids:
                    subject_uuids.append(entity_uuid)

                if not subject_uuids:
                    logger.warning("delete_entity_graph_bulk: no subjects found for %s", entity_uri)
                    return None

                # Step 2: Sync frame_entity table — remove before edge rows
                from .sync_frame_entity_table import sync_frame_entity_before_delete
                await sync_frame_entity_before_delete(
                    conn, space_id, subject_uuids, context_uuid=g_uuid)

                # Step 2a: entity_slot_sort, also before the edge rows go —
                # it resolves a touched slot back through the edge table.
                from .sync_entity_slot_sort import sync_entity_slot_sort_before_delete
                await sync_entity_slot_sort_before_delete(
                    conn, space_id, subject_uuids, context_uuid=g_uuid)

                # Step 2b: Sync edge table — remove edge rows before quads
                from .sync_edge_table import sync_edge_table_before_delete
                edge_deleted = await sync_edge_table_before_delete(
                    conn, space_id, subject_uuids, context_uuid=g_uuid)

                # Step 3 (fused): DELETE ... RETURNING, then decrement stats
                # from the rows actually deleted — avoids the separate
                # read-before-delete scan of the same rows (100x mitigation #10;
                # halves delete-path I/O). Edge/frame_entity sync stayed BEFORE
                # the delete (they need the quads); only stats moves after.
                from .sync_stats_tables import sync_stats_after_delete
                deleted_rows = await conn.fetch(
                    f"DELETE FROM {t['rdf_quad']} "
                    f"WHERE subject_uuid = ANY($1) AND context_uuid = $2 "
                    f"RETURNING subject_uuid, predicate_uuid, object_uuid, context_uuid",
                    subject_uuids, g_uuid,
                )
                deleted = len(deleted_rows)
                if deleted_rows:
                    quad_rows = [(r['subject_uuid'], r['predicate_uuid'],
                                  r['object_uuid'], r['context_uuid']) for r in deleted_rows]
                    await sync_stats_after_delete(conn, space_id, quad_rows)

                # VERIFY, because the membership query above cannot be
                # trusted to have seen the whole graph. It matches on a
                # single mutable predicate at one instant, so anything whose
                # grouping URI was missing, misdirected, or written after
                # this ran is not in `subject_uuids` and survives — pointing
                # at an entity that no longer exists.
                #
                # That residue is `issues/092`: 19 grouping targets across 4
                # spaces with members and no typed root, each reading as an
                # EMPTY entity graph. It went three months without an
                # explanation because nothing on the delete path ever looked
                # back to see whether the delete had finished.
                #
                # Reported, not deleted. Removing whatever still points at
                # the entity would be a second, unbounded pass over rows
                # this caller never named, and the safe half of the fix is
                # for the delete to stop being silent about it.
                orphaned = await conn.fetchval(
                    f"SELECT count(*) FROM {t['rdf_quad']} "
                    f"WHERE predicate_uuid = $1 AND object_uuid = $2 "
                    f"AND context_uuid = $3",
                    p_uuid, entity_uuid, g_uuid)
                if orphaned:
                    logger.warning(
                        "delete_entity_graph_bulk(%s, %s): %d quad(s) still "
                        "point at this entity via hasKGGraphURI after the "
                        "delete — their root is gone and they read as an "
                        "empty entity graph. See issues/092.",
                        space_id, entity_uri, orphaned)

                return subject_uuids, deleted, edge_deleted

            # Retry a deadlock victim: this transaction takes stats-table
            # locks alongside a potentially large delete, and losing it
            # discards the whole delete (issues/115).
            from .deadlock_retry import with_deadlock_retry
            _result = await with_deadlock_retry(
                self._db._pool, _do_delete,
                what=f"delete_entity_graph_bulk({space_id}, {entity_uri})")
            if _result is None:
                return 0
            subject_uuids, deleted, edge_deleted = _result

            _t1 = _time.monotonic()
            logger.info(
                "⏱️  BULK delete_entity_graph: %.3fs (%d subjects, %d quads, %d edges deleted)",
                _t1 - _t0, len(subject_uuids), deleted, edge_deleted,
            )

            # Track row changes for auto-ANALYZE (outside transaction)
            from .auto_analyze import record_changes, maybe_analyze
            record_changes(space_id, deleted)
            # This method deletes within ONE graph and has no quad list.
            try:
                from ...cache.count_cache import _count_cache
                _count_cache.invalidate_graph(space_id, str(graph_id))
            except Exception as _e:      # pragma: no cover - defensive
                logger.debug("count cache invalidation skipped: %s", _e)
            async with self._db._pool.acquire() as conn:
                await maybe_analyze(conn, space_id, pg_config=self.postgresql_config)
            return deleted
        except Exception as e:
            logger.error("delete_entity_graph_bulk(%s, %s) failed: %s", space_id, entity_uri, e)
            # RAISE, do not return 0. A count of 0 is a truthful answer to
            # "how many were written" only when nothing was ASKED for; on a
            # failure it is indistinguishable from a no-op, and every caller
            # above has to guess. issues/100 spent two days on six searches
            # that returned nothing because this returned 0 here, a caller
            # discarded it, and the API reported success. The callers already
            # have `except Exception` blocks written for this.
            raise

    async def remove_rdf_quads_batch_bulk(self, space_id: str,
                                           quads: List[tuple],
                                           connection=None,
                                           stats_sink: Optional[list] = None) -> int:
        """Batched quad deletion using executemany.

        Generates all quad UUIDs in Python, resolves datatype IDs once per
        unique datatype, then executes a single ``executemany`` DELETE.
        """
        if not quads:
            return 0
        try:
            import time as _time
            _t0 = _time.monotonic()
            t = self.schema.get_table_names(space_id)

            # Collect unique datatype URIs
            datatype_uris: set = set()
            for _s, _p, _o, _g in quads:
                if isinstance(_o, Literal) and _o.datatype:
                    datatype_uris.add(str(_o.datatype))

            async def _do_bulk(conn):
                # Resolve datatypes
                dt_map: dict = {}
                for uri in datatype_uris:
                    row = await conn.fetchrow(
                        f"SELECT datatype_id FROM {t['datatype']} WHERE datatype_uri = $1", uri)
                    if row:
                        dt_map[uri] = row['datatype_id']

                # Build UUID tuples
                delete_rows = []
                for s, p, o, g in quads:
                    s_uuid = _generate_term_uuid(str(s), 'U')
                    p_uuid = _generate_term_uuid(str(p), 'U')
                    g_uuid = _generate_term_uuid(str(g), 'U')

                    o_text = str(o)
                    if isinstance(o, URIRef):
                        o_type = 'U'
                    elif isinstance(o, BNode):
                        o_type = 'B'
                    elif isinstance(o, Literal):
                        o_type = 'L'
                    else:
                        o_type = 'U'
                    o_lang = o.language if isinstance(o, Literal) else None
                    o_dt = dt_map.get(str(o.datatype)) if isinstance(o, Literal) and o.datatype else None
                    o_uuid = _generate_term_uuid(o_text, o_type, o_lang, o_dt)

                    delete_rows.append((s_uuid, p_uuid, o_uuid, g_uuid))

                # Sync frame_entity — remove before edge rows
                from .sync_frame_entity_table import sync_frame_entity_before_delete
                unique_subjects = list({row[0] for row in delete_rows})
                await sync_frame_entity_before_delete(
                    conn, space_id, unique_subjects)

                # entity_slot_sort — also before the edge rows
                from .sync_entity_slot_sort import sync_entity_slot_sort_before_delete
                await sync_entity_slot_sort_before_delete(
                    conn, space_id, unique_subjects)

                # Sync edge table — remove edge rows before quads
                from .sync_edge_table import sync_edge_table_before_delete
                edge_deleted = await sync_edge_table_before_delete(
                    conn, space_id, unique_subjects)

                await conn.executemany(
                    f"DELETE FROM {t['rdf_quad']} "
                    f"WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                    f"AND object_uuid = $3 AND context_uuid = $4",
                    delete_rows,
                )

                # Stats LAST, and optionally not here at all. The decrement
                # needs only `delete_rows`, never the table, so its old place
                # ahead of the DELETE bought nothing and cost the whole rest of
                # the transaction: `rdf_pred_stats` holds one row per predicate,
                # `vitaltype` and `hasKGGraphURI` are on nearly every quad, and
                # the row stays locked until commit. Measured on the update_quads
                # shape — a remove followed by a full insert in one transaction —
                # the hot row was held for 98.4% of the transaction, against 7.7%
                # for a plain insert, whose sync already sat at the end
                # (issues/115).
                if stats_sink is None:
                    from .sync_stats_tables import sync_stats_after_delete
                    await sync_stats_after_delete(conn, space_id, delete_rows)
                else:
                    stats_sink.append(("delete", delete_rows))
                _t1 = _time.monotonic()
                logger.info("⏱️  BULK remove_quads: %.3fs (%d quads, %d edges)",
                            _t1 - _t0, len(delete_rows), edge_deleted)
                return len(delete_rows)

            if connection:
                # The caller owns this transaction, so it owns the retry too.
                count = await _do_bulk(connection)
            else:
                from .deadlock_retry import with_deadlock_retry
                count = await with_deadlock_retry(
                    self._db._pool, _do_bulk,
                    what=f"remove_rdf_quads_batch_bulk({space_id})")

            # Track row changes for auto-ANALYZE (outside transaction)
            from .auto_analyze import record_changes, maybe_analyze
            record_changes(space_id, count)
            self._invalidate_counts_for_quads(space_id, quads)
            async with self._db._pool.acquire() as conn:
                await maybe_analyze(conn, space_id, pg_config=self.postgresql_config)
            return count
        except Exception as e:
            logger.error("remove_rdf_quads_batch_bulk(%s) failed: %s", space_id, e)
            # RAISE, do not return 0. A count of 0 is a truthful answer to
            # "how many were written" only when nothing was ASKED for; on a
            # failure it is indistinguishable from a no-op, and every caller
            # above has to guess. issues/100 spent two days on six searches
            # that returned nothing because this returned 0 here, a caller
            # discarded it, and the API reported success. The callers already
            # have `except Exception` blocks written for this.
            raise

    async def remove_rdf_quads_batch(self, space_id: str,
                                      quads: List[tuple]) -> int:
        try:
            t = self.schema.get_table_names(space_id)
            removed = 0
            async with self._db._pool.acquire() as conn:
              # Atomic: run the multi-statement delete loop in one transaction so
              # a raise mid-loop rolls back cleanly rather than leaving the pooled
              # connection in an aborted state (issue 019 hardening).
              async with conn.transaction():
                # Resolve every quad FIRST, so the derived tables can be synced
                # before the quads they are derived from disappear.
                delete_rows = []
                for s, p, o, g in quads:
                    s_uuid = _generate_term_uuid(str(s), 'U')
                    p_uuid = _generate_term_uuid(str(p), 'U')
                    g_uuid = _generate_term_uuid(str(g), 'U')

                    # For the object, extract lang/datatype_id just like _ensure_term
                    o_text = str(o)
                    o_type = self._infer_rdflib_type(o) if hasattr(o, 'n3') else self._infer_type(o_text)
                    o_lang = None
                    o_datatype_id = None
                    if isinstance(o, Literal):
                        o_lang = o.language
                        if o.datatype:
                            o_datatype_id = await self._resolve_datatype_id(
                                conn, t, str(o.datatype))
                    o_uuid = _generate_term_uuid(o_text, o_type, o_lang, o_datatype_id)
                    delete_rows.append((s_uuid, p_uuid, o_uuid, g_uuid))

                # Maintain the derived tables. This path used to delete quads and
                # maintain NOTHING, while remove_rdf_quads_batch_bulk beside it
                # maintained all three — and this one is live product surface
                # (triples_endpoint, files_impl, objects_impl). Every delete
                # through it left an edge row whose defining quads were gone:
                # the issues/064 orphan class, on a path that pass never covered
                # because it was scoped to execute_sparql_update and CLEAR/DROP.
                #
                # ORDER MATTERS and is copied from the bulk path, not invented:
                # frame_entity is derived from edge so it goes first, edge next,
                # and both must run BEFORE the quads are deleted because the
                # sync helpers read those quads to work out what to remove.
                # Stats decrement before the delete for the same reason.
                unique_subjects = list({row[0] for row in delete_rows})
                from .sync_frame_entity_table import sync_frame_entity_before_delete
                await sync_frame_entity_before_delete(
                    conn, space_id, unique_subjects)
                from .sync_entity_slot_sort import sync_entity_slot_sort_before_delete
                await sync_entity_slot_sort_before_delete(
                    conn, space_id, unique_subjects)
                from .sync_edge_table import sync_edge_table_before_delete
                await sync_edge_table_before_delete(
                    conn, space_id, unique_subjects)
                from .sync_stats_tables import sync_stats_after_delete
                await sync_stats_after_delete(conn, space_id, delete_rows)

                for s_uuid, p_uuid, o_uuid, g_uuid in delete_rows:
                    result = await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} "
                        f"WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                        f"AND object_uuid = $3 AND context_uuid = $4",
                        s_uuid, p_uuid, o_uuid, g_uuid,
                    )
                    if 'DELETE 1' in result:
                        removed += 1
            self._invalidate_counts_for_quads(space_id, quads)
            return removed
        except Exception as e:
            logger.error("remove_rdf_quads_batch(%s) failed: %s", space_id, e)
            # RAISE, do not return 0. A count of 0 is a truthful answer to
            # "how many were written" only when nothing was ASKED for; on a
            # failure it is indistinguishable from a no-op, and every caller
            # above has to guess. issues/100 spent two days on six searches
            # that returned nothing because this returned 0 here, a caller
            # discarded it, and the API reported success. The callers already
            # have `except Exception` blocks written for this.
            raise

    async def quads(self, space_id: str, quad_pattern: tuple,
                    context: Optional[Any] = None):
        t = self.schema.get_table_names(space_id)
        s, p, o, g = quad_pattern

        where = []
        params = []
        idx = 0

        for val, col in [(s, 'subject_uuid'), (p, 'predicate_uuid'),
                         (o, 'object_uuid'), (g, 'context_uuid')]:
            if val is not None:
                idx += 1
                term_type = self._infer_rdflib_type(val) if col != 'context_uuid' else 'U'
                where.append(f"q.{col} = ${idx}")
                params.append(_generate_term_uuid(str(val), term_type))

        where_sql = " AND ".join(where) if where else "TRUE"

        sql = (
            f"SELECT ts.term_text AS s, tp.term_text AS p, "
            f"to2.term_text AS o, tg.term_text AS g "
            f"FROM {t['rdf_quad']} q "
            f"JOIN {t['term']} ts ON q.subject_uuid = ts.term_uuid "
            f"JOIN {t['term']} tp ON q.predicate_uuid = tp.term_uuid "
            f"JOIN {t['term']} to2 ON q.object_uuid = to2.term_uuid "
            f"JOIN {t['term']} tg ON q.context_uuid = tg.term_uuid "
            f"WHERE {where_sql}"
        )

        async with self._db._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            for row in rows:
                yield (row['s'], row['p'], row['o'], row['g'])

    # ==================================================================
    # Namespace management (minimal — stored as terms)
    # ==================================================================

    async def add_namespace(self, space_id: str, prefix: str,
                            namespace_uri: str) -> Optional[int]:
        return None  # Namespaces not tracked in this backend

    async def get_namespace_uri(self, space_id: str, prefix: str) -> Optional[str]:
        return None

    async def list_namespaces(self, space_id: str) -> List[Dict[str, Any]]:
        return []

    # ==================================================================
    # SPARQL execution (V2 pipeline)
    # ==================================================================

    def get_sparql_impl(self, space_id: str):
        """Return self — this backend implements SparqlBackendInterface."""
        return self

    async def execute_sparql_query(self, space_id: str, query: str,
                                    **kwargs) -> Dict[str, Any]:
        """Execute a SPARQL query via the V2 pipeline.

        Returns SPARQL JSON Results format compatible with GraphObjectRetriever:
            {
                'results': {'bindings': [
                    {'?var': {'type': 'uri'|'literal', 'value': '...', ...}, ...}
                ]},
                'ok': True
            }
        """
        try:
            import time as _time
            from ..jena_sparql.jena_ast_mapper import map_compile_response
            from .generator import generate_sql

            t0 = _time.monotonic()
            client = self._get_sidecar_client()
            raw = await _compile_cache.compile(query, client)
            t_sidecar = _time.monotonic()

            cr = map_compile_response(raw)
            if not cr.ok:
                return {'results': {'bindings': []}, 'success': False, 'error': cr.error}

            t_pre_acquire = _time.monotonic()
            async with self._db._pool.acquire() as conn:
                t_acquired = _time.monotonic()
                gen = await generate_sql(
                    cr, space_id, conn=conn,
                    multi_vector_config=kwargs.get('multi_vector_config'),
                )
                if not gen.ok:
                    # Only `cr.ok` was checked, so a REFUSED generation fell
                    # through with sql=None and the caller received an ordinary
                    # empty result set — a refusal indistinguishable from "no
                    # matches", which is strictly worse than the cost it
                    # avoided. Observed end to end: the generator logged
                    # "refused: CONTAINS(?o, 'XQ') cannot be served" while the
                    # API answered 200 with 0 bindings and no message.
                    logger.warning("SPARQL generation failed: %s", gen.error)
                    return {'results': {'bindings': []}, 'success': False,
                            'error': gen.error}
                sql = gen.sql
                var_map = gen.var_map or {}
                t_gen = _time.monotonic()

                # Resolve vector placeholders (vg:vectorSimilarity)
                if gen.vector_requests:
                    from .vg_resolve import resolve_vector_requests
                    sql = await resolve_vector_requests(
                        sql, gen.vector_requests, space_id, conn)

                # Resolve fuzzy placeholders (vg:fuzzyMatch)
                if gen.fuzzy_requests:
                    from .vg_resolve import resolve_fuzzy_requests
                    sql = await resolve_fuzzy_requests(
                        sql, gen.fuzzy_requests, space_id, conn)

                if 'ORDER BY' in query.upper() and 'MIN' in query.upper():
                    logger.info("DEBUG multi-value sort SQL:\n%s", sql)

                # ASK only needs to know whether any row matches. The generator
                # does not specialise on query_type, so without this the query
                # materialises every matching row to answer a yes/no question.
                # SPARQL forbids solution modifiers on ASK, so there is no
                # LIMIT/OFFSET/ORDER BY in the inner SQL to disturb.
                if cr.meta.query_type == 'ASK':
                    sql = f"SELECT EXISTS (SELECT 1 FROM ({sql}) _ask_sub) AS _ask_result"

                if gen.needs_ordered_scan:
                    # This plan is O(page) only while PostgreSQL drives it from
                    # an ordered scan that stops at the LIMIT. Its cost model
                    # prorates that scan's total by the LIMIT assuming matching
                    # rows are spread uniformly, which for a 96%-selective
                    # criterion is wrong by nearly the whole scan — so above a
                    # data-dependent row count it switches to a blocking Sort
                    # and probes every candidate. Measured 48s for a 100-row
                    # page against 2ms for 50, and 51-130s for a capped count.
                    #
                    # enable_sort is a discouragement, not a prohibition: if a
                    # sort is genuinely the only way to plan the query, the
                    # planner still uses one. So this cannot make the statement
                    # unplannable — it only removes the cheap-looking blocking
                    # alternative. SET LOCAL keeps it to this transaction.
                    #
                    # A GUC rather than pg_hint_plan because the hint that
                    # would fix the cause — Rows(), correcting the estimate —
                    # does not apply here: the EXISTS runs as a SubPlan filter,
                    # with no join relation to correct. See issues/047.
                    async with conn.transaction():
                        await _apply_read_fence(conn)
                        await conn.execute("SET LOCAL enable_sort = off")
                        rows = await conn.fetch(sql)
                else:
                    # Same transaction wrapper purely so `SET LOCAL` scopes to
                    # this statement and cannot leak onto the pooled connection.
                    async with conn.transaction():
                        await _apply_read_fence(conn)
                        rows = await conn.fetch(sql)
                t_exec = _time.monotonic()
                result_rows = [dict(r) for r in rows]

            t_convert_rows = _time.monotonic()

            # Convert V2 flat rows → SPARQL JSON bindings
            bindings = self._rows_to_sparql_bindings(result_rows, var_map)
            t_bindings = _time.monotonic()

            # Count JOINs in generated SQL as complexity indicator
            join_count = sql.upper().count(' JOIN ')
            sql_len = len(sql)

            # Compute once, then both log and return. These used to exist only
            # inside the log call, so the one breakdown that explains a slow
            # query was unreachable to the caller that experienced it.
            timing = {
                'acquire_ms': round((t_acquired - t_pre_acquire) * 1000, 2),
                'sidecar_ms': round((t_sidecar - t0) * 1000, 2),
                'gen_ms': round((t_gen - t_acquired) * 1000, 2),
                'exec_ms': round((t_exec - t_gen) * 1000, 2),
                'rows_to_dict_ms': round((t_convert_rows - t_exec) * 1000, 2),
                'bindings_ms': round((t_bindings - t_convert_rows) * 1000, 2),
                'total_ms': round((t_bindings - t0) * 1000, 2),
                'rows': len(rows),
                'joins': join_count,
                'sql_chars': sql_len,
            }
            logger.info(
                "SPARQL pipeline [%s]: acquire=%.0fms sidecar=%.0fms gen=%.0fms exec=%.0fms "
                "rows→dict=%.0fms bindings=%.0fms total=%.0fms "
                "(%d rows, %d joins, %d chars SQL)",
                space_id,
                timing['acquire_ms'],
                timing['sidecar_ms'],
                timing['gen_ms'],
                timing['exec_ms'],
                timing['rows_to_dict_ms'],
                timing['bindings_ms'],
                timing['total_ms'],
                timing['rows'],
                timing['joins'],
                timing['sql_chars'],
            )
            logger.debug("Generated SQL [%s]:\n%s", space_id, sql)

            result = {
                'results': {'bindings': bindings},
                'success': True,
                'sql': sql,
                'query_type': cr.meta.query_type,
                'timing': timing,
            }

            # ASK answers from the EXISTS wrapper above, not from the bindings
            # (which carry no meaningful variables once wrapped). Callers read
            # result['boolean'].
            if cr.meta.query_type == 'ASK':
                result['boolean'] = bool(result_rows[0]['_ask_result']) if result_rows else False
                result['results'] = {'bindings': []}

            # CONSTRUCT returns a graph, not the WHERE-pattern bindings. The
            # template was parsed all along and then dropped one layer short of
            # use (issue 025); instantiate it here, where the solutions are.
            elif cr.meta.query_type == 'CONSTRUCT':
                from .construct import instantiate_construct
                result['triples'] = instantiate_construct(
                    cr.meta.construct_template, bindings)
                result['results'] = {'bindings': []}

            # DESCRIBE resolves its targets from constants and from variables
            # the WHERE clause bound, then returns each target's triples.
            elif cr.meta.query_type == 'DESCRIBE':
                from .construct import describe_targets
                targets = describe_targets(cr.meta.describe_nodes, bindings)
                result['triples'] = await self._describe_triples(space_id, targets)
                result['results'] = {'bindings': []}

            return result

        except Exception as e:
            logger.error("execute_sparql_query(%s) failed: %s", space_id, e)
            return {'results': {'bindings': []}, 'success': False, 'error': str(e)}

    async def _describe_triples(self, space_id: str,
                                targets: List[str]) -> List[Dict[str, Any]]:
        """Triples describing each target URI.

        **Description strategy (SPARQL leaves this implementation-defined,
        §16.4):** every triple in the space with the target as its *subject* —
        a forward concise bounded description, without recursive blank-node
        expansion. Chosen because it is predictable and bounded; a symmetric
        or recursive CBD can return unboundedly more of the graph for a
        well-connected node.

        Runs as one VALUES-constrained SELECT rather than a query per target.
        """
        if not targets:
            return []

        # These URIs come from the query and from term rows, so they are not
        # arbitrary user text — but an IRI cannot contain these characters, so
        # anything carrying one is malformed and is dropped rather than
        # interpolated (mirrors segment_deletion._is_safe_uri).
        illegal = set('<>"{}|^`\\ \t\n\r')
        safe = [u for u in targets if u and not (illegal & set(u))]
        if len(safe) != len(targets):
            logger.warning(
                "DESCRIBE: dropped %d target(s) that cannot be safely "
                "interpolated into a query", len(targets) - len(safe))
        if not safe:
            return []

        values = " ".join(f"<{u}>" for u in safe)
        sparql = (
            f"SELECT ?s ?p ?o WHERE {{ GRAPH ?g {{ "
            f"VALUES ?s {{ {values} }} ?s ?p ?o . }} }}"
        )
        sub = await self.execute_sparql_query(space_id, sparql)
        triples: List[Dict[str, Any]] = []
        seen = set()
        for b in sub.get('results', {}).get('bindings', []):
            s, p, o = b.get('s'), b.get('p'), b.get('o')
            if not (s and p and o):
                continue
            key = (s.get('value'), p.get('value'), o.get('value'),
                   o.get('type'), o.get('xml:lang'), o.get('datatype'))
            if key in seen:
                continue
            seen.add(key)
            triples.append({'subject': s, 'predicate': p, 'object': o})
        return triples

    @staticmethod
    def _rows_to_sparql_bindings(
        rows: List[Dict[str, Any]],
        var_map: Dict[str, str],
    ) -> List[Dict[str, Dict[str, Any]]]:
        """Convert V2 pipeline result rows to SPARQL JSON bindings.

        Each V2 row has columns like ``v0``, ``v0__type``, ``v0__lang``,
        ``v0__datatype``.  ``var_map`` maps ``v0 → s`` (SPARQL name).
        Output is a list of binding dicts::

            [{'s': {'type': 'uri', 'value': 'http://...'}, ...}, ...]
        """
        # var_map: {opaque_sql_name: sparql_name}  e.g. {'v0': 's', 'v1': 'p'}
        bindings: List[Dict[str, Dict[str, Any]]] = []
        type_map = {'U': 'uri', 'L': 'literal', 'B': 'bnode', 'G': 'uri'}

        for row in rows:
            binding: Dict[str, Dict[str, Any]] = {}
            for sql_name, sparql_name in var_map.items():
                val = row.get(sql_name)
                if val is None:
                    continue

                term_type = row.get(f'{sql_name}__type', 'L')
                datatype = row.get(f'{sql_name}__datatype')
                entry: Dict[str, Any] = {
                    'type': type_map.get(term_type, 'literal'),
                    'value': _lexical_form(val, datatype),
                }

                lang = row.get(f'{sql_name}__lang')
                if lang:
                    entry['xml:lang'] = lang

                if datatype and term_type == 'L':
                    entry['datatype'] = str(datatype)

                binding[sparql_name] = entry

            bindings.append(binding)

        return bindings

    async def query_quads(self, space_id: str, sparql_query: str) -> List[Dict[str, Any]]:
        """Execute a SPARQL SELECT and return SPARQL JSON bindings.

        Compatible with FusekiPostgreSQLSpaceImpl.query_quads — the triples
        endpoint expects a list of binding dicts, e.g.
        ``[{'s': {'type': 'uri', 'value': '...'}, ...}, ...]``.
        """
        result = await self.execute_sparql_query(space_id, sparql_query)
        # A failure here returns bindings=[] with success=False. Returning that
        # empty list unqualified is what let an outage read as "no triples"
        # (`issues/082`) — the caller gets a list either way and cannot tell.
        if isinstance(result, dict) and result.get('success') is False:
            raise RuntimeError(
                f"query_quads({space_id}) failed: "
                f"{result.get('error') or 'backend reported failure'}")
        return result.get('results', {}).get('bindings', [])

    async def execute_sparql_update(self, space_id: str, update: str,
                                     **kwargs) -> bool:
        """Execute a SPARQL update via the V2 pipeline."""
        try:
            from ..jena_sparql.jena_ast_mapper import map_compile_response
            from .generator import generate_sql

            client = self._get_sidecar_client()
            raw = await _compile_cache.compile(update, client)

            cr = map_compile_response(raw)
            if not cr.ok:
                logger.error("SPARQL update compile error: %s", cr.error)
                return False

            async with self._db._pool.acquire() as conn:
                gen = await generate_sql(cr, space_id, conn=conn)
                if not gen.ok:
                    # `if sql:` treated a refused generation as nothing to do
                    # and fell through to the success return — a write that
                    # never happened, reported as one (issues/105).
                    logger.error("SPARQL update generation failed: %s", gen.error)
                    return False
                sql = gen.sql
                if sql:
                    # Atomic write: run the generated (multi-statement) update
                    # inside an explicit transaction so that if ANY statement
                    # raises (e.g. a duplicate-key under concurrency), the whole
                    # batch rolls back cleanly and the pooled connection is
                    # returned in a clean state — never left in an aborted
                    # implicit transaction that stalls conn.reset() and bleeds
                    # the pool (issue 019 defense-in-depth).
                    async with conn.transaction():
                        await conn.execute(sql)

                    # Keep {space}_edge in sync — this write path bypasses the
                    # bulk sync. For every concrete subject the update touched:
                    # add edges completed by inserts, and remove edges broken by
                    # deletes. Subjects bound only by a WHERE clause (variables)
                    # can't be enumerated here; those are covered by the
                    # background edge self-heal (MaintenanceJob._run_edge_integrity).
                    # This is best-effort: run it in its OWN transaction inside
                    # the try/except so a sync failure rolls back cleanly (leaving
                    # the committed quads intact) instead of poisoning the pooled
                    # connection. Background self-heal reconciles anything skipped.
                    try:
                        # CLEAR / DROP name no subjects, so the per-subject
                        # hooks below never fire for them and every edge row of
                        # the dropped graph is left orphaned — quads gone, edge
                        # rows answering traversals with edges to nowhere
                        # (issues/064). Handled by context instead.
                        for g_uri in _cleared_graphs_from_update_ops(cr.update_ops):
                            from .sync_edge_table import delete_edges_for_context
                            from .sync_frame_entity_table import (
                                delete_frame_entity_for_context)
                            from .sync_entity_slot_sort import (
                                delete_entity_slot_sort_for_context)
                            ctx_uuid = _generate_term_uuid(g_uri, 'U')
                            async with conn.transaction():
                                # frame_entity first: it is derived FROM the
                                # edge table, so clearing edges first would
                                # leave it unable to describe what it lost.
                                await delete_frame_entity_for_context(
                                    conn, space_id, ctx_uuid)
                                # entity_slot_sort, same reason, same order.
                                await delete_entity_slot_sort_for_context(
                                    conn, space_id, ctx_uuid)
                                await delete_edges_for_context(
                                    conn, space_id, ctx_uuid)

                        subj_uris = _concrete_subjects_from_update_ops(cr.update_ops)
                        if subj_uris:
                            from .sync_edge_table import (
                                sync_edge_table_after_insert,
                                cleanup_orphan_edges_for_subjects,
                            )
                            subj_uuids = [_generate_term_uuid(u, 'U') for u in subj_uris]
                            # frame_entity is derived from the edge table — reconcile
                            # the touched frames: drop then re-derive so a frame that
                            # gained/lost an entity slot is corrected. WHERE-bound
                            # subjects are covered by the background self-heal.
                            from .sync_frame_entity_table import (
                                sync_frame_entity_after_edge_insert,
                                sync_frame_entity_before_delete,
                            )
                            # entity_slot_sort reconciles the same way — drop
                            # then re-derive — so a slot whose VALUE was
                            # repointed gets a corrected row. Insert-only would
                            # hit ON CONFLICT DO NOTHING and keep the old value
                            # with no change in row count for a drift check to
                            # notice.
                            from .sync_entity_slot_sort import (
                                sync_entity_slot_sort_after_edge_insert,
                            )
                            async with conn.transaction():
                                await sync_edge_table_after_insert(conn, space_id, subj_uuids)
                                await cleanup_orphan_edges_for_subjects(conn, space_id, subj_uuids)
                                await sync_frame_entity_before_delete(conn, space_id, subj_uuids)
                                await sync_frame_entity_after_edge_insert(conn, space_id, subj_uuids)
                                # Deletes internally before re-deriving.
                                await sync_entity_slot_sort_after_edge_insert(
                                    conn, space_id, subj_uuids)

                        # Subjects bound by a WHERE clause could not be
                        # enumerated above, so nothing removed the edge rows
                        # their deletion orphaned. This used to be deferred to
                        # the background self-heal, which is a backfill and only
                        # ADDS — so those rows survived indefinitely, answering
                        # traversals with edges to nowhere (issues/064).
                        #
                        # Referential sweep, bounded, and only for updates that
                        # actually deferred something: the anti-join is real
                        # work and the all-concrete case is the common one.
                        # rdf_stats: execute_sparql_update maintained none at
                        # all, and nothing else repairs them — the maintenance
                        # job prunes stats and never resyncs. Recompute the
                        # predicates this update touched; bounded per predicate.
                        pred_uris = _concrete_predicates_from_update_ops(cr.update_ops)
                        if pred_uris:
                            from .sync_stats_tables import resync_stats_for_predicates
                            pred_uuids = [_generate_term_uuid(u, 'U') for u in pred_uris]
                            async with conn.transaction():
                                await resync_stats_for_predicates(
                                    conn, space_id, pred_uuids)

                        if _has_where_bound_delete(cr.update_ops):
                            from .sync_edge_table import mark_sweep_needed
                            mark_sweep_needed(space_id)

                        # WHERE-bound deletes name no subjects, so the bounded
                        # per-subject cleanup above cannot reach them. The
                        # referential sweep that does is NOT run here: it is
                        # O(edge table), measured at 181,212 ms over 4.98M rows
                        # with zero orphans, against a 60 s command_timeout — so
                        # inline it added up to 60 s to every such update and
                        # was then cancelled, meaning it never actually cleaned
                        # anything (issues/079). MaintenanceJob owns it now, on
                        # a connection that is not answering a user.
                    except Exception as ee:
                        logger.debug("edge sync after SPARQL UPDATE failed (non-critical): %s", ee)

            # Invalidate entity graph cache entries affected by this update
            try:
                from ...cache.entity_graph_cache import _entity_graph_cache
                targets = _entity_graph_cache.collect_invalidation_targets(
                    cr.update_ops, space_id,
                )
                if targets:
                    from vitalgraph.cache.count_cache import _count_cache
                    sm = self._signal_manager or (
                        self.db_impl.get_signal_manager() if self.db_impl else None)
                    _invalidated_graphs = set()
                    for graph_id, entity_uri in targets:
                        _entity_graph_cache.invalidate(space_id, graph_id, entity_uri)
                        if graph_id not in _invalidated_graphs:
                            _count_cache.invalidate_graph(space_id, graph_id)
                            _invalidated_graphs.add(graph_id)
                        if sm:
                            await sm.notify_entity_graph_changed(
                                space_id, graph_id, entity_uri)
                    logger.debug(
                        "Entity+count cache: invalidated %d entries after SPARQL UPDATE",
                        len(targets))
            except Exception as ce:
                logger.debug("Entity graph cache invalidation after SPARQL UPDATE failed (non-critical): %s", ce)

            # Detect KGDocument content changes → enqueue re-segmentation
            try:
                from ...document.segmentation_hooks import (
                    collect_segmentation_targets_from_update_ops,
                    schedule_resegmentation,
                )
                seg_targets = collect_segmentation_targets_from_update_ops(
                    cr.update_ops, space_id,
                )
                if seg_targets:
                    schedule_resegmentation(
                        db_impl=self.db_impl or self._db,
                        space_id=space_id,
                        targets=seg_targets,
                    )
                    logger.debug(
                        "Segmentation hook: detected %d document(s) after SPARQL UPDATE",
                        len(seg_targets))
            except Exception as se:
                logger.debug("Segmentation hook after SPARQL UPDATE failed (non-critical): %s", se)

            return True

        except Exception as e:
            logger.error("execute_sparql_update(%s) failed: %s", space_id, e,
                         exc_info=True)
            return False

    # ==================================================================
    # Utility
    # ==================================================================

    def get_manager_info(self) -> Dict[str, Any]:
        return {
            'backend_type': 'sparql_sql',
            'connected': self.connected,
            'pool_size': (self.db_impl.connection_pool.get_size()
                          if self.db_impl and self.db_impl.connection_pool else 0),
        }

    def get_signal_manager(self):
        return self._signal_manager or (
            self.db_impl.get_signal_manager() if self.db_impl else None)

    def set_signal_manager(self, signal_manager):
        self._signal_manager = signal_manager

    # ==================================================================
    # Bulk load optimization
    # ==================================================================

    async def drop_indexes_for_bulk_load(self, space_id: str) -> bool:
        """Drop secondary indexes ahead of a bulk load.

        CALLER CONTRACT: this leaves the space UNINDEXED and committed. Pairing
        it with `recreate_indexes_after_bulk_load` is the caller's
        responsibility, and a failure there is not automatically recoverable —
        see the note on that method.
        """
        try:
            async with self._db._pool.acquire() as conn:
                for stmt in self.schema.drop_space_indexes_sql(space_id):
                    # timeout=None: index DDL is not a query and the pool's 60s
                    # command_timeout is a QUERY fence. See recreate() below.
                    await conn.execute(stmt, timeout=None)
            return True
        except Exception as e:
            logger.error("drop_indexes_for_bulk_load(%s) failed: %s", space_id, e)
            return False

    async def recreate_indexes_after_bulk_load(self, space_id: str,
                                                concurrent: bool = True) -> bool:
        """Rebuild the secondary indexes `drop_indexes_for_bulk_load` removed.

        NO STATEMENT TIMEOUT, deliberately. The pool sets `command_timeout=60`,
        which is a fence for QUERIES; an index build is not a query and its cost
        is proportional to the table. Measured on 50,570,000 rows: 21,879 ms
        plain and 40,983 ms CONCURRENTLY — already 68% of that fence, and
        `concurrent=True` is the default, so the default path was the one about
        to cross it (`issues/079`). Under the fence the build is CANCELLED, and
        because the drops are already committed the space is left unindexed.

        A cancelled `CREATE INDEX CONCURRENTLY` also leaves an INVALID index
        behind that PostgreSQL will not use, so the failure is not even
        self-clearing.

        NOT wrapped in a transaction: `CREATE INDEX CONCURRENTLY` cannot run
        inside one. That is why the contract on `drop_indexes_for_bulk_load`
        matters — this pair is not atomic and cannot be made so while
        `concurrent` is true. `bulk_load_with_index_rebuild` is the atomic
        alternative for the non-concurrent case.
        """
        failed = []
        try:
            async with self._db._pool.acquire() as conn:
                for stmt in self.schema.create_space_indexes_sql(space_id):
                    if concurrent:
                        stmt = stmt.replace(
                            'CREATE INDEX', 'CREATE INDEX CONCURRENTLY'
                        )
                    try:
                        await conn.execute(stmt, timeout=None)
                    except Exception as one:
                        # Keep going: one index failing should not cost the rest,
                        # and the caller needs to know WHICH are missing rather
                        # than just that something went wrong.
                        failed.append((stmt, one))
            if failed:
                logger.error(
                    "recreate_indexes(%s): %d of the index builds FAILED — the "
                    "space is missing indexes and queries against it will be "
                    "slow until they are rebuilt. First failure: %s",
                    space_id, len(failed), failed[0][1])
                return False
            return True
        except Exception as e:
            logger.error("recreate_indexes(%s) failed: %s", space_id, e)
            return False

    # ==================================================================
    # Internal helpers
    # ==================================================================

    async def _ensure_term(self, conn, tables: Dict[str, str],
                           term: Identifier,
                           force_type: Optional[str] = None) -> uuid.UUID:
        """Ensure a term exists in the term table, return its UUID."""
        term_text = str(term)
        if force_type:
            term_type = force_type
        elif isinstance(term, URIRef):
            term_type = 'U'
        elif isinstance(term, BNode):
            term_type = 'B'
        elif isinstance(term, Literal):
            term_type = 'L'
        else:
            term_type = 'U'

        # One convention for what gets STORED: term_text is the bare value, so
        # a blank node is `b1` and never `_:b1`. Normalising the uuid input
        # alone would leave the two spellings sharing an id while the stored
        # text still varied by entry point (issues/065).
        from .term_normalize import normalize_term_text
        term_text = normalize_term_text(term_text, term_type)

        lang = None
        datatype_id = None
        if isinstance(term, Literal):
            lang = term.language
            if term.datatype:
                datatype_id = await self._resolve_datatype_id(
                    conn, tables, str(term.datatype)
                )

        term_uuid = _generate_term_uuid(term_text, term_type, lang, datatype_id)
        await conn.execute(
            f"INSERT INTO {tables['term']} "
            f"(term_uuid, term_text, term_type, lang, datatype_id) "
            f"VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
            term_uuid, term_text, term_type, lang, datatype_id,
        )
        return term_uuid

    async def _resolve_datatype_id(self, conn, tables: Dict[str, str],
                                    datatype_uri: str) -> Optional[int]:
        """Resolve a datatype URI to its integer ID."""
        row = await conn.fetchrow(
            f"SELECT datatype_id FROM {tables['datatype']} "
            f"WHERE datatype_uri = $1", datatype_uri,
        )
        if row:
            return row['datatype_id']
        # Insert new datatype — invalidate cache so gen picks up the new mapping
        space_id = tables['datatype'].rsplit("_datatype", 1)[0]
        invalidate_datatype_cache(space_id)
        result = await conn.fetchval(
            f"INSERT INTO {tables['datatype']} (datatype_uri) "
            f"VALUES ($1) ON CONFLICT (datatype_uri) "
            f"DO UPDATE SET datatype_uri = EXCLUDED.datatype_uri "
            f"RETURNING datatype_id",
            datatype_uri,
        )
        # Notify other instances to invalidate their datatype cache
        try:
            sm = self._signal_manager or (self.db_impl.get_signal_manager() if self.db_impl else None)
            if sm:
                await sm.notify_cache_invalidate("datatype", space_id)
        except Exception as e:
            logger.debug("Datatype cache invalidation notify failed (non-critical): %s", e)
        return result

    @staticmethod
    def _infer_type(value: str) -> str:
        """Infer term type from a raw string value."""
        if value.startswith('http://') or value.startswith('https://') or value.startswith('urn:'):
            return 'U'
        if value.startswith('_:'):
            return 'B'
        return 'L'

    @staticmethod
    def _infer_rdflib_type(term) -> str:
        """Infer term type from an rdflib Identifier."""
        if isinstance(term, URIRef):
            return 'U'
        if isinstance(term, BNode):
            return 'B'
        if isinstance(term, Literal):
            return 'L'
        return 'U'
