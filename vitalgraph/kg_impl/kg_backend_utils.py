"""
KG Backend Abstraction Layer

This module provides a unified interface for KG operations across space backends.
It abstracts backend-specific implementation details and provides a consistent API
for KG endpoint implementations.

There is ONE adapter today (`SparqlSQLBackendAdapter`). The interface is kept
because it is what the kg_impl processors are written against, not because a
second backend is expected — `issues/241`.
"""

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple, Union, cast
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

# Model imports
from ..model.kgentities_model import EntityCreateResponse, EntityUpdateResponse

# Graph retrieval utilities
from .kg_graph_retrieval_utils import GraphObjectRetriever
from ..db.connection_config import require


# ---------------------------------------------------------------------------
# Fast default-listing helpers (shared by KGEntities and the generic
# list_objects path for KGRelations / KGTypes).
#
# These bypass the SPARQL pipeline for the *plain default* listing: order by
# the internal ``subject_uuid`` (index-friendly) and resolve text only for the
# page, avoiding the ``ORDER BY ?s`` full-URI resolution that dominates cold
# renders on large spaces.  They key on whatever type predicate the caller's
# SPARQL uses (``vitaltype`` for entities, ``rdf:type`` for the generic path)
# with the exact same type-URI set, and use COUNT(DISTINCT)/SELECT DISTINCT so
# the result equals the SPARQL ``COUNT(DISTINCT ?x)`` regardless of multi-typing.
# ---------------------------------------------------------------------------

RDF_TYPE_URI = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
VITALTYPE_URI = 'http://vital.ai/ontology/vital-core#vitaltype'


def graph_is_uri(graph_id: Optional[str]) -> bool:
    """True if graph_id is an absolute IRI whose context UUID we can derive.

    Accepts ``http(s)://…`` and ``urn:…``; rejects empty and the literal
    ``"default"`` (a bare word with no scheme → ambiguous context).
    """
    return bool(graph_id) and graph_id != "default" and ":" in graph_id


def _resolve_space_impl(backend):
    """Return the SparqlSQLSpaceImpl from either the impl itself or an adapter.

    Callers pass whatever `self.backend` they hold — sometimes the space impl
    directly (KGEntities/KGFrames), sometimes a backend adapter wrapping it
    (the generic list_objects path). The direct-SQL helpers need the impl's
    `.schema` and `.db_impl`; return None for non-sparql_sql backends so the
    caller falls back to SPARQL.
    """
    if hasattr(backend, 'schema') and hasattr(backend, 'db_impl'):
        return backend
    inner = getattr(backend, 'backend', None)
    if inner is not None and hasattr(inner, 'schema') and hasattr(inner, 'db_impl'):
        return inner
    return None


async def fast_typed_subject_count(backend, space_id: str, graph_id: str,
                                   type_predicate_uri: str,
                                   type_uris) -> Optional[int]:
    """`COUNT(DISTINCT subject_uuid)` for subjects of the given type(s), or None."""
    if not graph_is_uri(graph_id):
        return None
    impl = _resolve_space_impl(backend)
    if impl is None:
        return None
    try:
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        t = impl.schema.get_table_names(space_id)
        p_uuid = _generate_term_uuid(type_predicate_uri, 'U')
        obj_uuids = [_generate_term_uuid(u, 'U') for u in type_uris]
        g_uuid = _generate_term_uuid(graph_id, 'U')
        async with impl.db_impl.connection_pool.acquire() as conn:
            n = await conn.fetchval(
                f"SELECT COUNT(DISTINCT subject_uuid) FROM {t['rdf_quad']} "
                f"WHERE predicate_uuid = $1 AND object_uuid = ANY($2::uuid[]) "
                f"AND context_uuid = $3",
                p_uuid, obj_uuids, g_uuid,
            )
        return int(n or 0)
    except Exception:
        logging.getLogger(__name__).warning(
            "fast_typed_subject_count failed, caller will fall back", exc_info=True)
        return None


async def fast_typed_subject_page(backend, space_id: str, graph_id: str,
                                  type_predicate_uri: str, type_uris,
                                  page_size: int, offset: int) -> Optional[list]:
    """Ordered (`subject_uuid`) page of subject URIs of the given type(s), or None."""
    if not graph_is_uri(graph_id):
        return None
    impl = _resolve_space_impl(backend)
    if impl is None:
        return None
    try:
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        t = impl.schema.get_table_names(space_id)
        p_uuid = _generate_term_uuid(type_predicate_uri, 'U')
        obj_uuids = [_generate_term_uuid(u, 'U') for u in type_uris]
        g_uuid = _generate_term_uuid(graph_id, 'U')
        async with impl.db_impl.connection_pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT tt.term_text AS uri "
                f"FROM (SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                f"      WHERE predicate_uuid = $1 "
                f"      AND object_uuid = ANY($2::uuid[]) "
                f"      AND context_uuid = $3 "
                f"      ORDER BY subject_uuid LIMIT $4 OFFSET $5) sub "
                f"JOIN {t['term']} tt ON tt.term_uuid = sub.subject_uuid "
                f"ORDER BY sub.subject_uuid",
                p_uuid, obj_uuids, g_uuid, page_size, offset,
            )
        return [r['uri'] for r in rows]
    except Exception:
        logging.getLogger(__name__).warning(
            "fast_typed_subject_page failed, caller will fall back", exc_info=True)
        return None


# `issues/175` class 2. Defined in the db layer, which kg_impl already
# depends on; the reverse would invert the layering.
from ..db.sparql_sql.conn_scope import write_conn as _write_conn
from ..db.sparql_sql.entity_lock import EntityLockTimeout
from ..utils.exception_detail import describe_exception


@dataclass
class BackendOperationResult:
    """Result of a backend operation."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    objects: Optional[List[GraphObject]] = None


class KGBackendInterface(ABC):
    """Abstract interface for KG backend operations."""
    
    @abstractmethod
    async def store_objects(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> BackendOperationResult:
        """Store VitalSigns objects in the backend."""
        pass
    
    @abstractmethod
    async def object_exists(self, space_id: str, graph_id: str, uri: str) -> bool:
        """Check if an object exists in the backend."""
        pass
    
    @abstractmethod
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> BackendOperationResult:
        """Delete an object from the backend."""
        pass
    
    @abstractmethod
    async def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        """Execute a SPARQL query against the backend."""
        pass
    
    @abstractmethod
    async def validate_parent_connection(self, space_id: str, graph_id: str, 
                                       parent_uri: str, child_uri: str) -> bool:
        """Validate that a parent-child relationship exists."""
        pass
    
    @abstractmethod
    async def update_quads(self, space_id: str, graph_id: str, 
                          delete_quads: List[tuple], insert_quads: List[tuple]) -> bool:
        """
        Atomically update quads by deleting old ones and inserting new ones.
        
        Implementation Strategy:
        1. Execute DELETE and INSERT within single PostgreSQL transaction
        2. PostgreSQL transaction provides atomicity guarantee

        This used to have a third step — synchronising a second store after the
        commit — which is where the second-store tri-state came from. With one
        store there is nothing to be out of sync WITH, so the operation either
        commits or it does not (`issues/241`).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier (full URI)
            delete_quads: List of (subject, predicate, object, graph) tuples to delete
            insert_quads: List of (subject, predicate, object, graph) tuples to insert
            
        Returns:
            bool: True if operation succeeded, False otherwise
        """
        pass

    @abstractmethod
    async def get_objects_by_uris(self, space_id: str, uris: List[str],
                                  graph_id: Optional[str] = None) -> List[GraphObject]:
        """Retrieve multiple objects by URI list as VitalSigns GraphObjects."""
        pass


class SparqlSQLBackendAdapter(KGBackendInterface):
    """Adapter for the pure-PostgreSQL sparql_sql backend.

    Wraps ``SparqlSQLSpaceImpl`` and exposes the ``KGBackendInterface``
    consumed by kg_impl processors (KGEntityCreateProcessor, etc.).
    """

    def __init__(self, backend_impl):
        self.backend = backend_impl
        self.logger = logging.getLogger(f"{__name__}.SparqlSQLBackendAdapter")
        self.retriever = GraphObjectRetriever(backend_impl)
        # PostgreSQL config for thread-offloaded ANALYZE (avoids event loop stalls)
        self._pg_config = getattr(backend_impl, 'postgresql_config', None)

    # ------------------------------------------------------------------
    # store_objects
    # ------------------------------------------------------------------

    async def store_objects(self, space_id: str, graph_id: str,
                            objects: List[GraphObject],
                            conn=None) -> BackendOperationResult:
        try:
            import time as _time
            from rdflib import URIRef

            _t0 = _time.monotonic()
            graph_uri = URIRef(graph_id)

            def _build_quads():
                result = []
                for obj in objects:
                    try:
                        for s, p, o in obj.to_triples():
                            result.append((s, p, o, graph_uri))
                    except Exception as e:
                        pass  # logged below via count mismatch
                return result

            quads = await asyncio.to_thread(_build_quads)

            _t1 = _time.monotonic()
            self.logger.info("⏱️  BACKEND to_triples: %.3fs (%d objects → %d quads)",
                             _t1 - _t0, len(objects), len(quads))

            inserted = await self.backend.add_rdf_quads_batch_bulk(
                space_id, quads, connection=conn)
            _t2 = _time.monotonic()
            self.logger.info("⏱️  BACKEND add_rdf_quads_batch_bulk: %.3fs (%d inserted)",
                             _t2 - _t1, inserted)

            if inserted == 0 and len(quads) > 0:
                self.logger.error(
                    "store_objects: 0 quads inserted out of %d — "
                    "likely a PostgreSQL index overflow or constraint error",
                    len(quads),
                )
                return BackendOperationResult(
                    success=False,
                    message=f"Failed to insert quads: 0 of {len(quads)} stored",
                    error=f"0 quads inserted (check server logs for index overflow errors)",
                )

            # Refresh planner statistics for the auxiliary tables after a write.
            #
            # rdf_quad and term are deliberately EXCLUDED. Measured on prod, this
            # block ran 27k+ times per space over 45 days at ~4.2s per ANALYZE of
            # rdf_quad alone, accounting for 28.7% of all database time — and
            # column statistics on a 26.8M-row table barely move when one
            # applicant's entities are appended. MaintenanceJob and autovacuum own
            # those two tables now.
            # See planning/planning_performance/prod_db_saturation_plan.md
            try:
                await self._maybe_analyze_aux_tables(space_id, since=_t2)
            except Exception as ae:
                self.logger.warning("ANALYZE after bulk insert failed (non-fatal): %s", ae)

            self.logger.info("⏱️  BACKEND store_objects total: %.3fs", _time.monotonic() - _t0)

            return BackendOperationResult(
                success=True,
                message=f"Successfully stored {len(objects)} objects ({inserted} quads)",
                data={"stored_count": len(objects), "quad_count": inserted},
            )
        except Exception as e:
            self.logger.error("store_objects failed: %s", describe_exception(e))
            return BackendOperationResult(success=False, message=str(e), error=str(e))

    # ------------------------------------------------------------------
    # Post-write ANALYZE of auxiliary tables (three-tier guard)
    # ------------------------------------------------------------------

    async def _get_analyze_lock_manager(self):
        """Lazily create the process lock manager used to serialise ANALYZE."""
        if getattr(self, '_analyze_lock_manager', None) is None:
            if not self._pg_config:
                return None
            from ..process.process_lock_manager import ProcessLockManager
            mgr = ProcessLockManager(self._pg_config)
            await mgr.connect()
            self._analyze_lock_manager = mgr
        return self._analyze_lock_manager

    async def _maybe_analyze_aux_tables(self, space_id: str, since: float) -> bool:
        """ANALYZE the auxiliary tables for *space_id*, rate-limited across processes.

        Three tiers, each covering a case the previous one cannot:

        * **Tier 0** — in-process timestamp. Avoids a catalog roundtrip on the hot
          write path.
        * **Tier 1** — ``pg_stat_user_tables.last_analyze``, which PostgreSQL keeps
          globally. This is the guard that actually holds across workers and task
          restarts; the in-process dict never did.
        * **Tier 2** — non-blocking advisory lock. ``last_analyze`` only advances
          when ANALYZE *completes*, so during a run every other process still reads
          a stale timestamp and would start its own. The lock closes that window —
          which is also the restart-stampede case, when every task comes up with an
          empty Tier 0 simultaneously.

        Returns True if ANALYZE actually ran.
        """
        import time as _time
        from ..db.sparql_sql.auto_analyze import (
            was_analyzed_recently, set_last_analyze_time, fetch_last_analyze_age,
            ANALYZE_LOCAL_GUARD_SECONDS, ANALYZE_MIN_INTERVAL,
        )
        from ..db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

        # Tier 0 — fast path, no DB roundtrip.
        if was_analyzed_recently(space_id, max_age_seconds=ANALYZE_LOCAL_GUARD_SECONDS):
            self.logger.debug("⏱️  BACKEND ANALYZE: skipped (local guard)")
            return False

        t = SparqlSQLSchema.get_table_names(space_id)
        # `frame_slot`, not `frame_entity`. The retired key was removed from
        # `get_table_names` (`issues/183`), so this raised KeyError while
        # BUILDING the list — before any ANALYZE ran. Not "the dropped table's
        # ANALYZE fails": ALL FIVE were skipped, silently, because the caller
        # logs it as non-fatal. Prod showed it as
        # `ANALYZE after bulk insert failed (non-fatal): 'frame_entity'`
        # on every bulk write.
        # `entity_slot_sort` ADDED 2026-09-11. It was the one derived table the
        # query path plans against that nothing ever analyzed — not this
        # function, and not reliably autovacuum either, because these tables are
        # populated by bulk load. Found with 3,877,000 rows and `last_analyze`
        # NULL on `sp_lead_synth_100k`, and 304,923 rows never analyzed on
        # `<space>`, where the planner consequently estimated `rows=1` for it.
        # That estimate is what `issues/096` noticed in its plans without
        # tracing it back here. Compensating for bulk load is the whole reason
        # this function exists, so excluding the biggest bulk-loaded table was
        # backwards.
        tables = [t['rdf_pred_stats'], t['rdf_stats'], t['datatype'],
                  t['edge'], t['frame_slot'], t['entity_slot_sort']]
        # Only a rate-limit proxy for "has this space been analyzed recently",
        # not a claim about size: `entity_slot_sort` outgrows `edge` on some
        # spaces (3.9M against 365k). Kept as `edge` because every space has one
        # and changing it would reset the shared clock for all of them.
        representative = t['edge']

        # Tier 1 — shared clock.
        # INTERNAL pool (`issues/231`): both the catalog probe below and the
        # ANALYZE fallback further down are deferrable maintenance, and on the
        # request pool they compete with the readers this is supposed to be
        # speeding up. Falls back to the request pool so an impl without the
        # split keeps working.
        from ..db.pool import internal_pool_for
        pool = internal_pool_for(self.backend.db_impl)
        if pool is not None:
            async with pool.acquire() as conn:
                age = await fetch_last_analyze_age(conn, representative)
            if age is not None and age < ANALYZE_MIN_INTERVAL:
                # Re-arm Tier 0 so we don't re-query the catalog on every batch
                # for the remainder of the interval.
                set_last_analyze_time(space_id)
                self.logger.debug(
                    "⏱️  BACKEND ANALYZE: skipped (shared guard, %.0fs ago)", age)
                return False

        # Tier 2 — non-blocking lock. If another process is mid-ANALYZE, skip;
        # never block, or writers queue behind maintenance.
        lock_mgr = await self._get_analyze_lock_manager()
        if lock_mgr is not None and not await lock_mgr.try_acquire("analyze", space_id):
            self.logger.debug("⏱️  BACKEND ANALYZE: skipped (another process holds the lock)")
            return False
        try:
            if self._pg_config:
                await asyncio.to_thread(self._sync_analyze_tables, tables)
            elif pool is not None:
                async with pool.acquire() as conn:
                    for tbl in tables:
                        await conn.execute(f"ANALYZE {tbl}")
            set_last_analyze_time(space_id)
            self.logger.info("⏱️  BACKEND ANALYZE (aux tables): %.3fs",
                             _time.monotonic() - since)
            return True
        finally:
            if lock_mgr is not None:
                await lock_mgr.release("analyze", space_id)

    # ------------------------------------------------------------------
    # Thread-offloaded ANALYZE helper
    # ------------------------------------------------------------------

    def _sync_analyze_tables(self, tables: List[str]) -> int:
        """Run ANALYZE on each table via a short-lived psycopg sync connection.

        Designed to be called via ``asyncio.to_thread()`` so the event loop
        is never blocked.  Mirrors MaintenanceJob._sync_run_tables().
        """
        import psycopg
        from psycopg import sql as psql

        cfg = self._pg_config
        assert cfg is not None, "_sync_analyze_tables requires _pg_config"
        conn = psycopg.connect(
            host=require(cfg, 'host'),
            port=require(cfg, 'port'),
            dbname=require(cfg, 'database'),
            user=require(cfg, 'username'),
            password=require(cfg, 'password'),
            autocommit=True,
        )
        completed = 0
        try:
            for table in tables:
                try:
                    conn.execute(psql.SQL("ANALYZE {}").format(psql.Identifier(table)))
                    completed += 1
                except Exception as e:
                    self.logger.warning("ANALYZE %s failed: %s", table, e)
        finally:
            conn.close()
        return completed

    # ------------------------------------------------------------------
    # object_exists
    # ------------------------------------------------------------------

    async def object_exists(self, space_id: str, graph_id: str, uri: str) -> bool:
        try:
            query = f"""
                SELECT ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{ <{uri}> ?p ?o . }}
                }} LIMIT 1
            """
            result = await self.backend.execute_sparql_query(space_id, query)
            bindings = result.get('results', {}).get('bindings', [])
            return len(bindings) > 0
        except Exception as e:
            self.logger.error("object_exists failed: %s", e)
            return False

    async def batch_check_uris_exist(self, space_id: str, graph_id: str,
                                      uris: List[str]) -> List[str]:
        """Return URIs that already exist as subjects in the graph (direct SQL)."""
        try:
            return await self.backend.check_subjects_exist(space_id, graph_id, uris)
        except Exception as e:
            self.logger.error("batch_check_uris_exist failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # get_object / get_entity / get_entity_graph
    # ------------------------------------------------------------------

    async def get_object(self, space_id: str, graph_id: str,
                         object_uri: str) -> BackendOperationResult:
        try:
            triples = await self.retriever.get_object_triples(
                space_id, graph_id, object_uri, include_materialized_edges=False
            )
            if not triples:
                return BackendOperationResult(success=True, message="Object not found", objects=[])
            objects = await self._triples_to_vitalsigns(triples)
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_object failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    async def get_entity(self, space_id: str, graph_id: str,
                         entity_uri: str) -> BackendOperationResult:
        return await self.get_object(space_id, graph_id, entity_uri)

    async def get_entity_graph(self, space_id: str, graph_id: str,
                               entity_uri: str) -> BackendOperationResult:
        try:
            objects = await self.retriever.get_entity_graph_as_objects(
                space_id, graph_id, entity_uri, include_materialized_edges=False
            )
            if not objects:
                return BackendOperationResult(
                    success=False, message=f"Entity graph not found: {entity_uri}", objects=[])
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_entity_graph failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    async def get_entity_by_reference_id(self, space_id: str, graph_id: str,
                                         reference_id: str) -> BackendOperationResult:
        try:
            triples = await self.retriever.get_entity_by_reference_id(
                space_id, graph_id, reference_id, include_materialized_edges=False
            )
            if not triples:
                return BackendOperationResult(success=True, message="Not found", objects=[])
            objects = await self._triples_to_vitalsigns(triples)
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_entity_by_reference_id failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    async def get_entity_graph_by_reference_id(self, space_id: str, graph_id: str,
                                               reference_id: str) -> BackendOperationResult:
        try:
            objects = await self.retriever.get_entity_graph_by_reference_id_as_objects(
                space_id, graph_id, reference_id, include_materialized_edges=False
            )
            if not objects:
                return BackendOperationResult(
                    success=False, message=f"Not found: {reference_id}", objects=[])
            return BackendOperationResult(success=True, message="OK", objects=objects)
        except Exception as e:
            self.logger.error("get_entity_graph_by_reference_id failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e), objects=[])

    # ------------------------------------------------------------------
    # delete_object
    # ------------------------------------------------------------------

    async def delete_object(self, space_id: str, graph_id: str,
                            uri: str, conn=None) -> BackendOperationResult:
        try:
            delete_query = f"""
                DELETE {{
                    GRAPH <{graph_id}> {{ <{uri}> ?p ?o . }}
                }}
                WHERE {{
                    GRAPH <{graph_id}> {{ <{uri}> ?p ?o . }}
                }}
            """
            await self.backend.execute_sparql_update(
                space_id, delete_query, conn=conn)
            return BackendOperationResult(success=True, message=f"Deleted {uri}")
        except Exception as e:
            self.logger.error("delete_object failed: %s", e)
            return BackendOperationResult(success=False, message=str(e), error=str(e))

    # ------------------------------------------------------------------
    # SPARQL execution
    # ------------------------------------------------------------------

    async def execute_sparql_query(self, space_id: str, query: str) -> Dict[str, Any]:
        return await self.backend.execute_sparql_query(space_id, query)

    async def execute_sparql_update(self, space_id: str, update_query: str):
        try:
            return await self.backend.execute_sparql_update(space_id, update_query)
        except Exception as e:
            self.logger.error("execute_sparql_update failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # fast_entity_count — direct-SQL count for the default KGEntity listing
    # ------------------------------------------------------------------

    # The four KGEntity subclass objects (must stay in sync with
    # _KGENTITY_TYPE_CLAUSE in kgentity_list_impl.py). Entities key on
    # ``vitaltype`` (one per object → the fast count is exact).
    _KGENTITY_TYPE_URIS = (
        'http://vital.ai/ontology/haley-ai-kg#KGEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGNewsEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGProductEntity',
        'http://vital.ai/ontology/haley-ai-kg#KGWebEntity',
    )

    async def fast_entity_count(self, space_id: str, graph_id: str,
                                entity_type_uri: Optional[str] = None,
                                search: Optional[str] = None,
                                prop_filters: str = "",
                                sort_by: Optional[str] = None,
                                filters: Optional[dict] = None) -> Optional[int]:
        """Exact entity count, from `entity_prop_sort` when it can serve the
        shape and from the quads for the plain default listing.

        THE COUNT MUST TRACK THE PAGE. Both run concurrently and the request
        waits for both, so a fast page beside a slow count is worth nothing.
        This declined every typed/filtered/sorted shape while
        `fast_entity_page` had already been taught to serve them: the page
        came back in 0.4 ms and the count took a `COUNT(DISTINCT)` over the
        quads, so the request took 30 s and was killed by the transaction
        timeout. Deterministic on the FIRST page of a listing; every later page
        hit the count cache and looked fine.
        """
        if search:
            logger.info(
                "fast_entity_count DECLINE(%s): search is set; text lives in the "
                "FTS index, not entity_prop_sort", space_id)
            return None
        # `sort_by` is NOT a routing condition here, where it is for the page.
        # A sort changes the ORDER of a result set, never its SIZE, so a bare
        # sort is the plain count and belongs to `fast_typed_subject_count`.
        # Routing it into the prop-sort branch made a sort-only listing decline
        # its count and fall to SPARQL for a number the plain path already had.
        if entity_type_uri or prop_filters:
            impl = _resolve_space_impl(self.backend)
            if impl is None or not graph_is_uri(graph_id):
                logger.info(
                    "fast_entity_count DECLINE(%s): impl_resolved=%s graph_is_uri=%s",
                    space_id, impl is not None, graph_is_uri(graph_id))
                return None
            from ..db.sparql_sql.fast_prop_sort import fast_entity_prop_count
            return await fast_entity_prop_count(
                impl, space_id, graph_id, entity_type_uri=entity_type_uri,
                filters=filters, sort_by=sort_by)
        return await fast_typed_subject_count(
            self.backend, space_id, graph_id, VITALTYPE_URI, self._KGENTITY_TYPE_URIS)

    async def fast_entity_page(self, space_id: str, graph_id: str,
                               page_size: int, offset: int,
                               entity_type_uri: Optional[str] = None,
                               search: Optional[str] = None,
                               prop_filters: str = "",
                               sort_by: Optional[str] = None,
                               filters: Optional[dict] = None,
                               sort_order: str = "asc") -> Optional[List[str]]:
        """Ordered page of entity URIs, or ``None`` → SPARQL fallback.

        Two fast paths now, and they cover different shapes:

        * the PLAIN default listing, ordered by `subject_uuid`, from the quads
        * a SORTED or FILTERED listing, from `{space}_entity_prop_sort`

        SEARCH still declines. Text lives in `{space}_fts_{index}` and composing
        it with this table is a join whose driving side depends on how selective
        the search is — measured, not guessed, per
        `planning_ui/kg_search_filter_sort_fts_plan.md`. `issues/172` is what
        guessing costs.
        """
        # THESE TWO DECLINES WERE SILENT, and that cost a second production
        # diagnosis. `fast_entity_prop_page` logs its own reasons at INFO, but
        # both returns below happen BEFORE it is called — so a listing that
        # declined here produced no line at all, and the absence of a
        # `prop_sort DECLINE` was read as "the fast path is not declining".
        # An unexplained decline is indistinguishable from an absent one.
        if search:
            logger.info(
                "fast_entity_page DECLINE(%s): search is set and text lives in "
                "the FTS index, not entity_prop_sort; composing them is not yet "
                "measured. NOTE: a UI that only enables sorting once a search "
                "narrows the set makes this the COMMON path, not a rare one.",
                space_id)
            return None
        if entity_type_uri or prop_filters or sort_by:
            impl = _resolve_space_impl(self.backend)
            if impl is None or not graph_is_uri(graph_id):
                logger.info(
                    "fast_entity_page DECLINE(%s): impl_resolved=%s graph_is_uri=%s "
                    "— the space impl could not be resolved from %s, or the graph "
                    "is not a URI", space_id, impl is not None,
                    graph_is_uri(graph_id), type(self.backend).__name__)
                return None
            from ..db.sparql_sql.fast_prop_sort import fast_entity_prop_page
            return await fast_entity_prop_page(
                impl, space_id, graph_id, page_size, offset,
                entity_type_uri=entity_type_uri, filters=filters,
                sort_by=sort_by, sort_order=sort_order)
        return await fast_typed_subject_page(
            self.backend, space_id, graph_id, VITALTYPE_URI,
            self._KGENTITY_TYPE_URIS, page_size, offset)

    # ------------------------------------------------------------------
    # validate_parent_connection
    # ------------------------------------------------------------------

    async def validate_parent_connection(self, space_id: str, graph_id: str,
                                         parent_uri: str, child_uri: str) -> bool:
        try:
            query = f"""
                SELECT ?edge WHERE {{
                    GRAPH <{graph_id}> {{
                        ?edge <http://vital.ai/ontology/vital-core#edgeSource> <{parent_uri}> .
                        ?edge <http://vital.ai/ontology/vital-core#edgeDestination> <{child_uri}> .
                    }}
                }} LIMIT 1
            """
            result = await self.backend.execute_sparql_query(space_id, query)
            bindings = result.get('results', {}).get('bindings', [])
            return len(bindings) > 0
        except Exception as e:
            self.logger.error("validate_parent_connection failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # update_quads
    # ------------------------------------------------------------------

    async def update_quads(self, space_id: str, graph_id: str,
                           delete_quads: List[tuple],
                           insert_quads: List[tuple]) -> bool:
        try:
            # This transaction syncs the stats tables TWICE — once down for the
            # removes, once up for the inserts — and the two calls lock their
            # own key ranges in sorted order without being sorted against each
            # other. So a remove of {C} plus an insert of {B} takes C then B,
            # while a concurrent update doing the reverse takes B then C: a
            # cycle that per-batch ordering cannot see (issues/115).
            #
            # The bulk paths retry themselves, but only when they own the
            # transaction. Here the transaction is ours, so the retry is too.
            async def _do_update(conn):
                # Both halves hand their stats deltas back instead of applying
                # them inline, so the hot predicate rows are locked once, at the
                # end, rather than from the first remove through the last
                # insert. Measured on this shape: 98.4% of the transaction spent
                # holding them, against 7.7% for a plain insert (issues/115).
                sink: list = []
                if delete_quads:
                    await self.backend.remove_rdf_quads_batch_bulk(
                        space_id, delete_quads, connection=conn, stats_sink=sink)
                if insert_quads:
                    await self.backend.add_rdf_quads_batch_bulk(
                        space_id, insert_quads, connection=conn, stats_sink=sink)

            from vitalgraph.db.sparql_sql.deadlock_retry import with_deadlock_retry
            await with_deadlock_retry(
                self.backend.db_impl.connection_pool, _do_update,
                what=f"update_quads({space_id}, {graph_id})")
            return True
        except Exception as e:
            self.logger.error("update_quads failed: %s", describe_exception(e))
            return False

    def _lock_timeout_failed(self, where: str, exc: EntityLockTimeout,
                             subjects: int) -> bool:
        """Log a lock timeout NAMING THE ENTITY, and report the write as failed.

        Reported from production (`issues/253`): "a failure cannot be traced to a
        lead, so nothing can be reconciled." PostgreSQL says `canceling statement
        due to lock timeout`, which identifies the STATEMENT — and every write to
        every lead issues the same one. The lock key is the only thing that says
        which entity was being written, so it belongs on the error line.
        """
        self.logger.error(
            "%s LOCK TIMEOUT after %.3fs waiting on entity %s (key %d); "
            "%d subject(s) NOT written",
            where, exc.waited_s, exc.uri, exc.key, subjects)
        return False

    async def upsert_objects_atomic(self, space_id: str, graph_id: str,
                                    entity_uris: List[str],
                                    objects: List[GraphObject],
                                    conn=None) -> bool:
        """Replace one or more entity graphs in ONE locked transaction.

        `issues/173`. UPSERT used to be `delete_object` then `store_objects`,
        two independent operations with nothing holding them together. A client
        that timed out and retried while the first request was still in flight
        got: A sees nothing committed and starts storing; B also sees nothing
        committed, so skips the delete, and stores too. Both landed.

        Only the server-stamped timestamps showed the damage, which is why it
        went unnoticed for two months: every client-supplied property carries
        the same value on each attempt, so the quad primary key dedupes the
        retry silently. The timestamps come from `datetime.now()` per request,
        so each attempt wrote a distinct row that no constraint could collapse.

        The lock is taken FIRST, before anything is read, so the existence check
        the caller made outside this transaction cannot be acted on by two
        writers at once. Everything else happens exactly as
        `update_entity_graph` does it, per entity.
        """
        import time as _time
        from ..db.sparql_sql.entity_lock import lock_entities
        from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
        from ..db.sparql_sql.sync_frame_slot_table import sync_frame_slot_before_delete
        from ..db.sparql_sql.sync_edge_table import sync_edge_table_before_delete
        from ..db.sparql_sql.sync_entity_slot_sort import (
            sync_entity_slot_sort_before_delete)
        from ..db.sparql_sql.sync_entity_prop_sort import (
            sync_entity_prop_sort_after_change)
        from ..db.sparql_sql.sync_frame_prop_sort import (
            sync_frame_prop_sort_after_change)
        from rdflib import URIRef

        try:
            _t0 = _time.monotonic()
            t = self.backend.schema.get_table_names(space_id)
            g_uuid = _generate_term_uuid(graph_id, 'U')
            p_uuid = _generate_term_uuid(
                'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI', 'U')
            graph_uri = URIRef(graph_id)

            def _build_quads():
                out = []
                for obj in objects:
                    try:
                        for sub, pred, o in obj.to_triples():
                            out.append((sub, pred, o, graph_uri))
                    except Exception:
                        pass
                return out

            quads = await asyncio.to_thread(_build_quads)

            async with _write_conn(self.backend.db_impl.connection_pool, conn) as conn:
                async with conn.transaction():
                    # Sorted inside `lock_entities`, so a multi-entity upsert
                    # cannot deadlock against one taking the same entities in a
                    # different order.
                    await lock_entities(conn, entity_uris)

                    for entity_uri in entity_uris:
                        e_uuid = _generate_term_uuid(entity_uri, 'U')
                        rows = await conn.fetch(
                            f"SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                            f"WHERE predicate_uuid = $1 AND object_uuid = $2 "
                            f"  AND context_uuid = $3",
                            p_uuid, e_uuid, g_uuid)
                        subject_uuids = [r['subject_uuid'] for r in rows]
                        if not subject_uuids:
                            continue
                        # The auxiliary tables are derived from the quads, so
                        # they have to be told before the rows go, not after.
                        await sync_frame_slot_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await sync_edge_table_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        # `entity_slot_sort` BEFORE the delete for the same
                        # reason (`issues/194`): its rows are reached through
                        # the edge table this delete invalidates, and a stale
                        # row makes a sort order by a value that is gone.
                        await sync_entity_slot_sort_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await conn.execute(
                            f"DELETE FROM {t['rdf_quad']} "
                            f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                            subject_uuids, g_uuid)
                        # AND THE PROP TABLES AFTER IT. A delete there is a
                        # RECOMPUTE: they store the MIN of a multi-valued
                        # property, so removing the lexically first of three
                        # values must move the MIN to the next survivor while
                        # the row itself survives. Re-deriving before the
                        # delete would restore the value being removed.
                        await sync_entity_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await sync_frame_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)

                    if quads:
                        await self.backend.add_rdf_quads_batch_bulk(
                            space_id, quads, connection=conn)

            self.logger.info(
                "\u23f1\ufe0f  upsert_objects_atomic: %.3fs (%d entit(y/ies), %d quads)",
                _time.monotonic() - _t0, len(entity_uris), len(quads))
            return True
        except EntityLockTimeout as e:
            return self._lock_timeout_failed("upsert_objects_atomic", e, len(entity_uris))
        except Exception as e:
            self.logger.error("upsert_objects_atomic failed: %s", describe_exception(e))
            return False

    async def update_entity_graph(self, space_id: str, graph_id: str,
                                   entity_uri: str,
                                   insert_quads: List[tuple],
                                     conn=None) -> bool:
        """Atomically replace an entity graph: subject-level delete + insert.

        Uses direct SQL to find all subjects belonging to the entity graph
        (via hasKGGraphURI) and deletes all their quads, then inserts the
        new quads — all within a single transaction.  This avoids the SPARQL
        pipeline's datatype-propagation issues that cause quad-level deletes
        to miss rows.
        """
        import time as _time
        try:
            _t0 = _time.monotonic()
            schema = self.backend.schema
            t = schema.get_table_names(space_id)
            from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
            g_uuid = _generate_term_uuid(graph_id, 'U')
            HAS_KG_GRAPH_URI = 'http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI'
            p_uuid = _generate_term_uuid(HAS_KG_GRAPH_URI, 'U')
            entity_uuid = _generate_term_uuid(entity_uri, 'U')

            async with _write_conn(self.backend.db_impl.connection_pool, conn) as conn:
                async with conn.transaction():
                    # Step 0: SERIALIZE ON THE ENTITY (`issues/173`).
                    #
                    # This transaction was already atomic; it was not exclusive.
                    # Two concurrent writers both run Step 1, both find the same
                    # subjects (or both find none, for an entity that does not
                    # exist yet), and both insert. Atomicity alone does not stop
                    # that — neither transaction does anything invalid on its
                    # own. The lock releases when this transaction ends.
                    from ..db.sparql_sql.entity_lock import lock_entities
                    await lock_entities(conn, [entity_uri])

                    # Step 1: Find all subjects in the entity graph
                    rows = await conn.fetch(
                        f"SELECT DISTINCT subject_uuid FROM {t['rdf_quad']} "
                        f"WHERE predicate_uuid = $1 AND object_uuid = $2 AND context_uuid = $3",
                        p_uuid, entity_uuid, g_uuid,
                    )
                    subject_uuids = [r['subject_uuid'] for r in rows]
                    if not subject_uuids:
                        self.logger.warning("update_entity_graph: no subjects found for %s", entity_uri)
                        # Still insert the new quads (entity may not have kGGraphURI on itself)
                    else:
                        # Step 2: Sync auxiliary tables before delete
                        from ..db.sparql_sql.sync_frame_slot_table import sync_frame_slot_before_delete
                        await sync_frame_slot_before_delete(conn, space_id, subject_uuids, context_uuid=g_uuid)
                        from ..db.sparql_sql.sync_edge_table import sync_edge_table_before_delete
                        await sync_edge_table_before_delete(conn, space_id, subject_uuids, context_uuid=g_uuid)
                        # THE SORT TABLES TOO (`issues/194`). The insert side is
                        # already covered: `add_rdf_quads_batch_bulk` maintains
                        # all five derived tables. What was missing is the
                        # DELETE side, and it fails differently for each:
                        #
                        #   `entity_slot_sort` keeps rows pointing at quads that
                        #   no longer exist, so a sort orders by a value that is
                        #   gone. Dropped BEFORE the delete, like edge and
                        #   frame_slot, because the rows are identified through
                        #   the edge table the delete is about to invalidate.
                        #
                        #   The two prop tables hold the MIN of a multi-valued
                        #   property, so a delete is a RECOMPUTE, not a row
                        #   drop — removing the lexically first of three values
                        #   must move the stored MIN to the next survivor while
                        #   the ROW SURVIVES. That cannot run before the delete
                        #   (the doomed value is still there to be re-derived),
                        #   so it runs after, below.
                        from ..db.sparql_sql.sync_entity_slot_sort import (
                            sync_entity_slot_sort_before_delete)
                        await sync_entity_slot_sort_before_delete(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)

                        # Step 3: Delete all quads for those subjects
                        result = await conn.execute(
                            f"DELETE FROM {t['rdf_quad']} "
                            f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                            subject_uuids, g_uuid,
                        )
                        deleted = int(result.split()[-1]) if result else 0
                        self.logger.info("update_entity_graph: deleted %d quads for %d subjects",
                                         deleted, len(subject_uuids))

                    # Step 4: Insert new quads in the same transaction
                    if insert_quads:
                        await self.backend.add_rdf_quads_batch_bulk(
                            space_id, insert_quads, connection=conn)

                    # AND THE PROP TABLES, AFTER the delete (`issues/194`).
                    # A delete here is a recompute against the survivors: for a
                    # subject that is gone entirely this empties its rows, and
                    # for one that lost a single value of several it moves the
                    # stored MIN. Running it before the delete would re-derive
                    # the value being removed.
                    if subject_uuids:
                        from ..db.sparql_sql.sync_entity_prop_sort import (
                            sync_entity_prop_sort_after_change)
                        from ..db.sparql_sql.sync_frame_prop_sort import (
                            sync_frame_prop_sort_after_change)
                        await sync_entity_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)
                        await sync_frame_prop_sort_after_change(
                            conn, space_id, subject_uuids, context_uuid=g_uuid)

            _t1 = _time.monotonic()
            self.logger.info("⏱️  update_entity_graph: %.3fs", _t1 - _t0)
            return True
        except EntityLockTimeout as e:
            return self._lock_timeout_failed("update_entity_graph", e, 1)
        except Exception as e:
            self.logger.error("update_entity_graph failed: %s", describe_exception(e))
            return False

    async def update_entity_subject_only(self, space_id: str, graph_id: str,
                                          entity_uri: str,
                                          insert_quads: List[tuple]) -> bool:
        """Atomically replace only the entity's own quads (subject = entity_uri).

        Unlike update_entity_graph which deletes ALL subjects with hasKGGraphURI,
        this only deletes quads where the subject IS the entity itself, preserving
        all frames, slots, and edges in the entity graph.

        No edge / frame_slot / entity_slot_sort sync is needed: the entity subject
        carries no edge-source/dest properties and is not a frame, so no row in
        those tables can describe it.

        `entity_prop_sort` IS needed, and this docstring said otherwise until
        2026-09-12 (`issues/194`). That table indexes properties hanging STRAIGHT
        OFF THE ENTITY — which is exactly the set of quads this method deletes.
        The reasoning that exempts the other three stops one step short of it:
        being neither an edge nor a frame says nothing about the entity's own
        properties. Left unsynced, a filter on a removed value still matched it.
        `frame_prop_sort` stays exempt, for the stated reason — an entity is not
        a frame.
        """
        import time as _time
        try:
            _t0 = _time.monotonic()
            schema = self.backend.schema
            t = schema.get_table_names(space_id)
            from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
            g_uuid = _generate_term_uuid(graph_id, 'U')
            entity_uuid = _generate_term_uuid(entity_uri, 'U')

            async with self.backend.db_impl.connection_pool.acquire() as conn:
                async with conn.transaction():
                    # Delete only entity's own quads
                    result = await conn.execute(
                        f"DELETE FROM {t['rdf_quad']} "
                        f"WHERE subject_uuid = $1 AND context_uuid = $2",
                        entity_uuid, g_uuid,
                    )
                    deleted = int(result.split()[-1]) if result else 0
                    self.logger.info("update_entity_subject_only: deleted %d quads for %s",
                                     deleted, entity_uri)

                    # Insert new entity quads
                    if insert_quads:
                        await self.backend.add_rdf_quads_batch_bulk(
                            space_id, insert_quads, connection=conn)

                    # AFTER the write, not before: a delete here is a RECOMPUTE
                    # against the surviving values, so re-deriving first would
                    # restore the value being removed. One call covers both the
                    # delete and the insert, which is why this table has a
                    # single `after_change` where the slot table needs two.
                    from ..db.sparql_sql.sync_entity_prop_sort import (
                        sync_entity_prop_sort_after_change)
                    await sync_entity_prop_sort_after_change(
                        conn, space_id, [entity_uuid], context_uuid=g_uuid)

            _t1 = _time.monotonic()
            self.logger.info("⏱️  update_entity_subject_only: %.3fs", _t1 - _t0)
            return True
        except Exception as e:
            self.logger.error("update_entity_subject_only failed: %s", e)
            return False

    async def update_subjects_graph(self, space_id: str, graph_id: str,
                                     subject_uris: List[str],
                                     insert_quads: List[tuple],
                                     lock_uris: Optional[List[str]] = None,
                                     conn=None) -> bool:
        """Atomically replace quads for a list of subject URIs.

        Subject-level delete + insert in a single transaction.  Avoids the
        fragile quad-level UUID matching in ``remove_rdf_quads_batch_bulk``.
        Used by frame create/update paths where the subject URIs are known.

        ``lock_uris`` SERIALISES ON THE GROUPING, not on the subjects being
        written (`issues/174`). This transaction was already atomic; it was not
        exclusive, which is the same gap `update_entity_graph` had. The key must
        be what OWNS these subjects — the entity for an entity-scoped frame, the
        frame itself for a standalone one — because entity upsert and
        entity-graph delete hold the entity key, and advisory locks only exclude
        writers that share a key. Locking the frame subjects instead would
        contend with nobody while looking correct.

        Do NOT derive the key from `hasKGFormType`: a frame whose form type is
        unset defaults to Assertion while still being entity-scoped, and on the
        production space that is roughly 275,000 of 482,000 frames. The caller
        knows which grouping it is writing; that is where the decision belongs.
        """
        import time as _time
        try:
            if not subject_uris and not insert_quads:
                return True
            _t0 = _time.monotonic()
            schema = self.backend.schema
            t = schema.get_table_names(space_id)
            from ..db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

            g_uuid = _generate_term_uuid(graph_id, 'U')
            s_uuids = [_generate_term_uuid(uri, 'U') for uri in subject_uris]

            async with _write_conn(self.backend.db_impl.connection_pool, conn) as conn:
                async with conn.transaction():
                    if lock_uris:
                        from ..db.sparql_sql.entity_lock import lock_entities
                        await lock_entities(conn, lock_uris)
                    if s_uuids:
                        # Sync auxiliary tables before delete.
                        #
                        # TIMED INDIVIDUALLY because the aggregate was
                        # misleading: `FRAME_CREATE step2` is 7.52s mean / 22.8s
                        # max on production for FOURTEEN subjects, of which the
                        # insert is ~0.3s, and the caller's log attributed the
                        # whole thing to "update_subjects_graph" with no way to
                        # tell which of these four statements owned it. Each one
                        # scans for the affected quads before the DELETE, so any
                        # of them could. Sub-millisecond to emit, and it runs on
                        # the path that starves the connection pool.
                        _s0 = _time.monotonic()
                        from ..db.sparql_sql.sync_frame_slot_table import sync_frame_slot_before_delete
                        await sync_frame_slot_before_delete(conn, space_id, s_uuids, context_uuid=g_uuid)
                        _s1 = _time.monotonic()
                        from ..db.sparql_sql.sync_edge_table import sync_edge_table_before_delete
                        await sync_edge_table_before_delete(conn, space_id, s_uuids, context_uuid=g_uuid)
                        _s2 = _time.monotonic()
                        from ..db.sparql_sql.sync_entity_slot_sort import (
                            sync_entity_slot_sort_before_delete)
                        from ..db.sparql_sql.sync_entity_prop_sort import (
                            sync_entity_prop_sort_after_change)
                        from ..db.sparql_sql.sync_frame_prop_sort import (
                            sync_frame_prop_sort_after_change)
                        # `entity_slot_sort` BEFORE the delete (`issues/194`):
                        # its rows are reached through the edge table the delete
                        # invalidates, so afterwards they cannot be found — and
                        # a stale row makes a sort order by a value that is
                        # gone. Timed like its siblings above, for the same
                        # reason: any of these scans can own the latency.
                        await sync_entity_slot_sort_before_delete(
                            conn, space_id, s_uuids, context_uuid=g_uuid)
                        _s3 = _time.monotonic()

                        # Delete all quads for these subjects in this graph
                        result = await conn.execute(
                            f"DELETE FROM {t['rdf_quad']} "
                            f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                            s_uuids, g_uuid,
                        )
                        _s4 = _time.monotonic()
                        # AND THE PROP TABLES AFTER IT, because a delete there
                        # is a RECOMPUTE against the survivors rather than a row
                        # drop: they store the MIN of a multi-valued property,
                        # and for a subject deleted outright this empties its
                        # rows. Before the delete it would re-derive the value
                        # being removed.
                        await sync_entity_prop_sort_after_change(
                            conn, space_id, s_uuids, context_uuid=g_uuid)
                        await sync_frame_prop_sort_after_change(
                            conn, space_id, s_uuids, context_uuid=g_uuid)
                        deleted = int(result.split()[-1]) if result else 0
                        self.logger.info(
                            "⏱️  update_subjects_graph presync: frame_entity=%.3fs "
                            "edge=%.3fs stats=%.3fs delete=%.3fs "
                            "(%d subjects, %d quads deleted)",
                            _s1 - _s0, _s2 - _s1, _s3 - _s2, _s4 - _s3,
                            len(s_uuids), deleted)

                    # Insert new quads
                    if insert_quads:
                        await self.backend.add_rdf_quads_batch_bulk(
                            space_id, insert_quads, connection=conn)

            _t1 = _time.monotonic()
            self.logger.info("⏱️  update_subjects_graph: %.3fs (%d subjects)",
                             _t1 - _t0, len(subject_uris))
            return True
        except EntityLockTimeout as e:
            return self._lock_timeout_failed(
                "update_subjects_graph", e, len(subject_uris))
        except Exception as e:
            self.logger.error("update_subjects_graph failed: %s", describe_exception(e))
            return False

    async def delete_entity_graph_direct(self, space_id: str, graph_id: str,
                                          entity_uri: str) -> int:
        """Delete entire entity graph via direct SQL (no SPARQL pipeline)."""
        try:
            return await self.backend.delete_entity_graph_bulk(
                space_id, graph_id, entity_uri)
        except Exception as e:
            self.logger.error("delete_entity_graph_direct failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # remove_rdf_quads_batch
    # ------------------------------------------------------------------

    async def remove_rdf_quads_batch(self, space_id: str, quads: List[tuple]) -> int:
        try:
            return await self.backend.remove_rdf_quads_batch(space_id, quads)
        except Exception as e:
            self.logger.error("remove_rdf_quads_batch failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # get_objects_by_uris
    # ------------------------------------------------------------------

    async def get_objects_by_uris(self, space_id: str, uris: List[str],
                                  graph_id: Optional[str] = None) -> List[GraphObject]:
        """Retrieve multiple objects by URI list as VitalSigns GraphObjects."""
        return await self.backend.db_objects.get_objects_by_uris(space_id, uris, graph_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _triples_to_vitalsigns(self, triples: List[tuple]) -> List[GraphObject]:
        try:
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            if not triples:
                return []
            vs = VitalSigns()
            objects = await asyncio.to_thread(vs.from_triples_list, (t for t in triples))
            return cast(List[GraphObject], objects)
        except Exception as e:
            self.logger.error("_triples_to_vitalsigns failed: %s", e)
            return []


def create_backend_adapter(backend_impl) -> KGBackendInterface:
    """Return the `KGBackendInterface` adapter for a space backend.

    Dispatches on the backend's TYPE, not on a substring of its class name.
    `issues/241`: the name-substring form defaulted to the RETIRED backend's
    adapter, so an unrecognised backend was silently adapted as a store it had
    nothing to do with — and a rename of `SparqlSQLSpaceImpl` would have been
    enough to trigger it, with no import error and no failing test to say so.

    Unknown backends RAISE. There is one adapter and guessing is what the old
    default did; a caller that reaches here with something else needs to know,
    not to be handed the only adapter that happens to exist.
    """
    from ..db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    # IDEMPOTENT. Several callers take a `backend` parameter that is ALREADY an
    # adapter and hand it straight back in — `_get_specific_frame_graphs` is one.
    # The old name-substring dispatch matched `SparqlSQLBackendAdapter` too and
    # silently wrapped an adapter in an adapter, which happened to work because
    # the adapter delegates through `self.backend`. Rejecting it instead broke
    # those callers (`issues/243`), so this returns it unchanged: correct for
    # them, and strictly better than the double wrap it replaces.
    if isinstance(backend_impl, KGBackendInterface):
        return backend_impl

    if isinstance(backend_impl, SparqlSQLSpaceImpl):
        return SparqlSQLBackendAdapter(backend_impl)

    raise TypeError(
        f"No KG backend adapter for {type(backend_impl).__name__}. "
        f"Supported: SparqlSQLSpaceImpl, or an already-built adapter.")
