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

# Module-level shared compile cache (space-independent, sidecar compilation
# depends only on SPARQL structure, not on which space is queried).
_compile_cache = SparqlCompileCache(maxsize=512)

# Deterministic UUID namespace (same as fuseki_postgresql for compatibility)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

def _generate_term_uuid(
    term_text: str, term_type: str,
    lang: Optional[str] = None, datatype_id: Optional[int] = None,
) -> uuid.UUID:
    """Deterministic UUID v5 for an RDF term — matches fuseki_postgresql."""
    parts = [term_text, term_type]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))


class _SparqlSQLGraphsAdapter:
    """Lightweight adapter so endpoint code can call ``db_space_impl.graphs.list_graphs()``
    and ``db_space_impl.graphs.get_graph()`` exactly like the fuseki_postgresql backend."""

    def __init__(self, space_impl: 'SparqlSQLSpaceImpl'):
        self._impl = space_impl

    async def list_graphs(self, space_id: str) -> List[Dict[str, Any]]:
        rows = await self._impl.list_graphs(space_id)
        # Normalise to the dict shape the endpoint expects
        graphs = []
        for r in rows:
            graphs.append({
                'graph_uri': r.get('graph_uri'),
                'graph_name': r.get('graph_name'),
                'triple_count': 0,
                'created_time': r.get('created_time'),
                'updated_time': None,
            })
        return graphs

    async def get_graph(self, space_id: str, graph_uri: str) -> Optional[Dict[str, Any]]:
        rows = await self._impl.db_impl.execute_query(
            "SELECT graph_uri, graph_name, created_time FROM graph "
            "WHERE space_id = $1 AND graph_uri = $2",
            [space_id, graph_uri],
        )
        if not rows:
            return None
        r = rows[0]
        return {
            'graph_uri': r.get('graph_uri'),
            'graph_name': r.get('graph_name'),
            'triple_count': 0,
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
            async with self._impl.db_impl.connection_pool.acquire() as conn:
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
        pool = self._impl.db_impl.connection_pool
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

    async def remove_quads_by_subject_uris(self, space_id: str,
                                           subject_uris: list,
                                           graph_id: str = None,
                                           transaction=None) -> int:
        """Remove all quads for the given subject URIs."""
        if not subject_uris:
            return 0
        if graph_id is None:
            graph_id = "main"
        t = self._impl.schema.get_table_names(space_id)
        removed = 0
        async with self._impl.db_impl.connection_pool.acquire() as conn:
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
        async with self.db_impl.connection_pool.acquire() as conn:
            yield conn

    # ==================================================================
    # Space lifecycle
    # ==================================================================

    async def create_space_storage(self, space_id: str) -> bool:
        try:
            async with self.db_impl.connection_pool.acquire() as conn:
                await SparqlSQLSchema.create_space(conn, space_id)
            return True
        except Exception as e:
            logger.error("create_space_storage(%s) failed: %s", space_id, e)
            return False

    async def delete_space_storage(self, space_id: str) -> bool:
        try:
            async with self.db_impl.connection_pool.acquire() as conn:
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
            async with self.db_impl.connection_pool.acquire() as conn:
                return await SparqlSQLSchema.space_tables_exist(conn, space_id)
        except Exception as e:
            logger.error("space_exists(%s) failed: %s", space_id, e)
            return False

    async def list_spaces(self) -> List[Dict[str, Any]]:
        """List all spaces from PostgreSQL admin tables."""
        try:
            results = await self.db_impl.execute_query(
                "SELECT * FROM space ORDER BY space_id"
            )
            return results
        except Exception as e:
            logger.error("list_spaces failed: %s", e)
            return []

    async def get_space_info(self, space_id: str) -> Dict[str, Any]:
        try:
            t = self.schema.get_table_names(space_id)
            async with self.db_impl.connection_pool.acquire() as conn:
                quad_count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {t['rdf_quad']}"
                )
                term_count = await conn.fetchval(
                    f"SELECT COUNT(*) FROM {t['term']}"
                )
            # Graph records
            graph_rows = await self.db_impl.execute_query(
                "SELECT graph_uri, graph_name FROM graph WHERE space_id = $1",
                [space_id],
            )
            return {
                'space_id': space_id,
                'backend_type': 'sparql_sql',
                'quad_count': quad_count,
                'term_count': term_count,
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
            await self.db_impl.execute_query(
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
        self, space_id: str, quads: List[Tuple[Any, ...]],
    ) -> None:
        """Auto-register every graph URI found in *quads* that is not yet
        in the ``graph`` table.  This replicates the side-effect that the
        fuseki_postgresql backend has: inserting data into a graph URI
        implicitly creates the graph record."""
        graph_uris = self._extract_graph_uris_from_quads(quads)
        if not graph_uris:
            return
        try:
            existing = await self.db_impl.execute_query(
                "SELECT graph_uri FROM graph WHERE space_id = $1",
                [space_id],
            )
            existing_set = {r['graph_uri'] for r in existing} if existing else set()
            for uri in graph_uris:
                if uri not in existing_set:
                    graph_name = uri.rsplit('/', 1)[-1]
                    await self.db_impl.execute_query(
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
            await self.db_impl.execute_query(
                """INSERT INTO graph (space_id, graph_uri, graph_name, created_time)
                   VALUES ($1, $2, $3, $4)""",
                [space_id, graph_uri, graph_name, datetime.now()],
            )
            return True
        except Exception as e:
            logger.error("create_graph(%s, %s) failed: %s", space_id, graph_uri, e)
            return False

    async def drop_graph(self, space_id: str, graph_uri: str) -> bool:
        try:
            # Remove quads for this graph
            t = self.schema.get_table_names(space_id)
            async with self.db_impl.connection_pool.acquire() as conn:
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
            await self.db_impl.execute_query(
                "DELETE FROM graph WHERE space_id = $1 AND graph_uri = $2",
                [space_id, graph_uri],
            )
            return True
        except Exception as e:
            logger.error("drop_graph(%s, %s) failed: %s", space_id, graph_uri, e)
            return False

    async def list_graphs(self, space_id: str) -> List[Dict[str, Any]]:
        try:
            return await self.db_impl.execute_query(
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
            async with self.db_impl.connection_pool.acquire() as conn:
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
            async with self.db_impl.connection_pool.acquire() as conn:
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
            async with self.db_impl.connection_pool.acquire() as conn:
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
            async with self.db_impl.connection_pool.acquire() as conn:
                await conn.execute(
                    f"DELETE FROM {t['rdf_quad']} "
                    f"WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                    f"AND object_uuid = $3 AND context_uuid = $4",
                    s_uuid, p_uuid, o_uuid, g_uuid,
                )
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
            async with self.db_impl.connection_pool.acquire() as conn:
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

    async def get_rdf_quad_count(self, space_id: str,
                                  graph_uri: Optional[str] = None) -> int:
        try:
            t = self.schema.get_table_names(space_id)
            async with self.db_impl.connection_pool.acquire() as conn:
                if graph_uri:
                    g_uuid = _generate_term_uuid(graph_uri, 'U')
                    return await conn.fetchval(
                        f"SELECT COUNT(*) FROM {t['rdf_quad']} "
                        f"WHERE context_uuid = $1", g_uuid,
                    )
                return await conn.fetchval(
                    f"SELECT COUNT(*) FROM {t['rdf_quad']}"
                )
        except Exception as e:
            logger.error("get_rdf_quad_count(%s) failed: %s", space_id, e)
            return 0

    async def add_rdf_quads_batch(self, space_id: str,
                                   quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]],
                                   auto_commit: bool = True,
                                   verify_count: bool = False,
                                   connection=None) -> int:
        try:
            await self._ensure_graphs_registered(space_id, quads)
            t = self.schema.get_table_names(space_id)
            inserted = 0

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
                    if 'INSERT' in result:
                        inserted += 1

            if connection:
                await _do(connection)
            else:
                async with self.db_impl.connection_pool.acquire() as conn:
                    await _do(conn)

            return inserted
        except Exception as e:
            logger.error("add_rdf_quads_batch(%s) failed: %s", space_id, e)
            return 0

    async def add_rdf_quads_batch_bulk(self, space_id: str,
                                       quads: List[Tuple[Identifier, Identifier, Identifier, Identifier]],
                                       connection=None) -> int:
        """Batched insert: resolve all datatypes, bulk-insert terms, bulk-insert quads.

        All work happens inside a single transaction.  Uses ``executemany``
        so asyncpg pipelines the parameter sets and PostgreSQL batches the
        WAL writes — reducing ~13 k round-trips to 3.
        """
        if not quads:
            return 0

        try:
            await self._ensure_graphs_registered(space_id, quads)

            import time as _time
            _t0 = _time.monotonic()

            t = self.schema.get_table_names(space_id)

            # ------------------------------------------------------------------
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

                # Bulk insert terms
                term_args = list(seen_terms.values())
                await conn.executemany(
                    f"INSERT INTO {t['term']} "
                    f"(term_uuid, term_text, term_type, lang, datatype_id) "
                    f"VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING",
                    term_args,
                )
                _t3 = _time.monotonic()

                # Bulk insert quads
                await conn.executemany(
                    f"INSERT INTO {t['rdf_quad']} "
                    f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
                    f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
                    quad_rows,
                )
                _t4 = _time.monotonic()

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

                # Sync stats tables
                from .sync_stats_tables import sync_stats_after_insert
                await sync_stats_after_insert(conn, space_id, quad_rows)
                _t6 = _time.monotonic()

                logger.info(
                    "⏱️  BULK insert: dt_resolve=%.3fs  classify=%.3fs  "
                    "terms_insert=%.3fs (%d unique)  quads_insert=%.3fs (%d)  "
                    "edge_sync=%.3fs (%d)  fe_sync=%.3fs (%d)  "
                    "stats_sync=%.3fs  total=%.3fs",
                    _t1 - _t0, _t2 - _t1, _t3 - _t2, len(term_args),
                    _t4 - _t3, len(quad_rows),
                    _t5 - _t4, edge_inserted,
                    _t5b - _t5, fe_inserted,
                    _t6 - _t5b, _t6 - _t0,
                )
                return len(quad_rows)

            if connection:
                count = await _do_bulk(connection)
            else:
                async with self.db_impl.connection_pool.acquire() as conn:
                    async with conn.transaction():
                        count = await _do_bulk(conn)

            # Track row changes for auto-ANALYZE (outside transaction)
            from .auto_analyze import record_changes, maybe_analyze
            record_changes(space_id, count)
            async with self.db_impl.connection_pool.acquire() as conn:
                await maybe_analyze(conn, space_id)
            return count

        except Exception as e:
            logger.error("add_rdf_quads_batch_bulk(%s) failed: %s", space_id, e)
            return 0

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

            async with self.db_impl.connection_pool.acquire() as conn:
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

            async with self.db_impl.connection_pool.acquire() as conn:
                async with conn.transaction():
                    # Step 1: Find all subject UUIDs with hasKGGraphURI = entity_uri
                    subject_rows = await conn.fetch(
                        f"SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                        f"WHERE predicate_uuid = $1 AND object_uuid = $2 AND context_uuid = $3",
                        p_uuid, entity_uuid, g_uuid,
                    )
                    subject_uuids = [row['subject_uuid'] for row in subject_rows]

                    if not subject_uuids:
                        logger.warning("delete_entity_graph_bulk: no subjects found for %s", entity_uri)
                        return 0

                    # Step 2: Sync frame_entity table — remove before edge rows
                    from .sync_frame_entity_table import sync_frame_entity_before_delete
                    await sync_frame_entity_before_delete(
                        conn, space_id, subject_uuids, context_uuid=g_uuid)

                    # Step 2b: Sync edge table — remove edge rows before quads
                    from .sync_edge_table import sync_edge_table_before_delete
                    edge_deleted = await sync_edge_table_before_delete(
                        conn, space_id, subject_uuids, context_uuid=g_uuid)

                    # Step 2c: Sync stats — decrement before quads are deleted
                    from .sync_stats_tables import sync_stats_for_deleted_subjects
                    await sync_stats_for_deleted_subjects(
                        conn, space_id, subject_uuids, context_uuid=g_uuid)

                    # Step 3: Delete all quads for those subjects in one statement
                    result = await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} "
                        f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                        subject_uuids, g_uuid,
                    )
                    deleted = int(result.split()[-1]) if result else 0

            _t1 = _time.monotonic()
            logger.info(
                "⏱️  BULK delete_entity_graph: %.3fs (%d subjects, %d quads, %d edges deleted)",
                _t1 - _t0, len(subject_uuids), deleted, edge_deleted,
            )

            # Track row changes for auto-ANALYZE (outside transaction)
            from .auto_analyze import record_changes, maybe_analyze
            record_changes(space_id, deleted)
            async with self.db_impl.connection_pool.acquire() as conn:
                await maybe_analyze(conn, space_id)
            return deleted
        except Exception as e:
            logger.error("delete_entity_graph_bulk(%s, %s) failed: %s", space_id, entity_uri, e)
            return 0

    async def remove_rdf_quads_batch_bulk(self, space_id: str,
                                           quads: List[tuple],
                                           connection=None) -> int:
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

                # Sync edge table — remove edge rows before quads
                from .sync_edge_table import sync_edge_table_before_delete
                edge_deleted = await sync_edge_table_before_delete(
                    conn, space_id, unique_subjects)

                # Sync stats — decrement before quads are deleted
                from .sync_stats_tables import sync_stats_after_delete
                await sync_stats_after_delete(conn, space_id, delete_rows)

                await conn.executemany(
                    f"DELETE FROM {t['rdf_quad']} "
                    f"WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                    f"AND object_uuid = $3 AND context_uuid = $4",
                    delete_rows,
                )
                _t1 = _time.monotonic()
                logger.info("⏱️  BULK remove_quads: %.3fs (%d quads, %d edges)",
                            _t1 - _t0, len(delete_rows), edge_deleted)
                return len(delete_rows)

            if connection:
                count = await _do_bulk(connection)
            else:
                async with self.db_impl.connection_pool.acquire() as conn:
                    async with conn.transaction():
                        count = await _do_bulk(conn)

            # Track row changes for auto-ANALYZE (outside transaction)
            from .auto_analyze import record_changes, maybe_analyze
            record_changes(space_id, count)
            async with self.db_impl.connection_pool.acquire() as conn:
                await maybe_analyze(conn, space_id)
            return count
        except Exception as e:
            logger.error("remove_rdf_quads_batch_bulk(%s) failed: %s", space_id, e)
            return 0

    async def remove_rdf_quads_batch(self, space_id: str,
                                      quads: List[tuple]) -> int:
        try:
            t = self.schema.get_table_names(space_id)
            removed = 0
            async with self.db_impl.connection_pool.acquire() as conn:
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

                    result = await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} "
                        f"WHERE subject_uuid = $1 AND predicate_uuid = $2 "
                        f"AND object_uuid = $3 AND context_uuid = $4",
                        s_uuid, p_uuid, o_uuid, g_uuid,
                    )
                    if 'DELETE 1' in result:
                        removed += 1
            return removed
        except Exception as e:
            logger.error("remove_rdf_quads_batch(%s) failed: %s", space_id, e)
            return 0

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

        async with self.db_impl.connection_pool.acquire() as conn:
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
            async with self.db_impl.connection_pool.acquire() as conn:
                t_acquired = _time.monotonic()
                gen = await generate_sql(cr, space_id, conn=conn)
                sql = gen.sql
                var_map = gen.var_map or {}
                t_gen = _time.monotonic()

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

            acquire_ms = (t_acquired - t_pre_acquire) * 1000
            logger.info(
                "SPARQL pipeline [%s]: acquire=%.0fms sidecar=%.0fms gen=%.0fms exec=%.0fms "
                "rows→dict=%.0fms bindings=%.0fms total=%.0fms "
                "(%d rows, %d joins, %d chars SQL)",
                space_id,
                acquire_ms,
                (t_sidecar - t0) * 1000,
                (t_gen - t_acquired) * 1000,
                (t_exec - t_gen) * 1000,
                (t_convert_rows - t_exec) * 1000,
                (t_bindings - t_convert_rows) * 1000,
                (t_bindings - t0) * 1000,
                len(rows),
                join_count,
                sql_len,
            )
            logger.debug("Generated SQL [%s]:\n%s", space_id, sql)

            return {
                'results': {'bindings': bindings},
                'success': True,
                'sql': sql,
            }

        except Exception as e:
            logger.error("execute_sparql_query(%s) failed: %s", space_id, e)
            return {'results': {'bindings': []}, 'success': False, 'error': str(e)}

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
                entry: Dict[str, Any] = {
                    'type': type_map.get(term_type, 'literal'),
                    'value': str(val),
                }

                lang = row.get(f'{sql_name}__lang')
                if lang:
                    entry['xml:lang'] = lang

                datatype = row.get(f'{sql_name}__datatype')
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

            async with self.db_impl.connection_pool.acquire() as conn:
                gen = await generate_sql(cr, space_id, conn=conn)
                sql = gen.sql
                if sql:
                    await conn.execute(sql)

            return True

        except Exception as e:
            logger.error("execute_sparql_update(%s) failed: %s", space_id, e)
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
        return self._signal_manager

    def set_signal_manager(self, signal_manager):
        self._signal_manager = signal_manager

    # ==================================================================
    # Bulk load optimization
    # ==================================================================

    async def drop_indexes_for_bulk_load(self, space_id: str) -> bool:
        try:
            async with self.db_impl.connection_pool.acquire() as conn:
                for stmt in self.schema.drop_space_indexes_sql(space_id):
                    await conn.execute(stmt)
            return True
        except Exception as e:
            logger.error("drop_indexes_for_bulk_load(%s) failed: %s", space_id, e)
            return False

    async def recreate_indexes_after_bulk_load(self, space_id: str,
                                                concurrent: bool = True) -> bool:
        try:
            async with self.db_impl.connection_pool.acquire() as conn:
                for stmt in self.schema.create_space_indexes_sql(space_id):
                    if concurrent:
                        stmt = stmt.replace(
                            'CREATE INDEX', 'CREATE INDEX CONCURRENTLY'
                        )
                    await conn.execute(stmt)
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
        return await conn.fetchval(
            f"INSERT INTO {tables['datatype']} (datatype_uri) "
            f"VALUES ($1) ON CONFLICT (datatype_uri) "
            f"DO UPDATE SET datatype_uri = EXCLUDED.datatype_uri "
            f"RETURNING datatype_id",
            datatype_uri,
        )

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
