"""
Analytics Job — periodic computation of KG analytics per space.

Runs once per day (default). Each cycle:
1. Lists all spaces
2. For each space, computes entity/frame/relation/property analytics via SQL
3. Stores results as JSONB in space_analytics table

Can also be triggered on-demand for a single space via trigger_compute().
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Well-known predicates
_VITALTYPE = 'http://vital.ai/ontology/vital-core#vitaltype'
_HAS_EDGE_SOURCE = 'http://vital.ai/ontology/vital-core#hasEdgeSource'
_HAS_EDGE_DESTINATION = 'http://vital.ai/ontology/vital-core#hasEdgeDestination'
_HAS_NAME = 'http://vital.ai/ontology/vital-core#hasName'

# Edge type URIs for relation classification
_EDGE_HAS_KG_RELATION = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation'
_EDGE_HAS_ENTITY_KG_FRAME = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame'
_EDGE_HAS_KG_SLOT = 'http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot'


def _short_name(uri: str) -> str:
    """Extract short display name from a URI."""
    if '#' in uri:
        return uri.rsplit('#', 1)[1]
    if '/' in uri:
        return uri.rsplit('/', 1)[1]
    return uri


class AnalyticsJob:
    """Computes KG analytics for all spaces periodically.

    Usage::

        job = AnalyticsJob(pool, schema)
        await job.run()          # compute for all spaces
        await job.trigger_compute(space_id)  # compute for one space
    """

    def __init__(self, pool, schema=None):
        """
        Args:
            pool: asyncpg connection pool.
            schema: Optional SparqlSQLSchema instance for table name resolution.
        """
        self._pool = pool
        self._schema = schema

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def run(self) -> Dict[str, Any]:
        """Compute analytics for all spaces. Called by ProcessScheduler."""
        results: Dict[str, Any] = {}
        try:
            spaces = await self._list_spaces()
            logger.info("AnalyticsJob: computing analytics for %d space(s)", len(spaces))
            for space_id in spaces:
                try:
                    result = await self._compute_and_store(space_id)
                    results[space_id] = result
                except Exception as e:
                    logger.error("AnalyticsJob: failed for space %s: %s", space_id, e, exc_info=True)
                    results[space_id] = {"error": str(e)}
        except Exception as e:
            logger.error("AnalyticsJob: cycle error: %s", e, exc_info=True)
        return results

    async def trigger_compute(self, space_id: str, graph_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """On-demand computation for a single space, optionally scoped to one graph."""
        return await self._compute_and_store(space_id, graph_uri=graph_uri)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    async def _compute_and_store(self, space_id: str, graph_uri: Optional[str] = None) -> Dict[str, Any]:
        """Compute all analytics for a space and store in space_analytics table.
        
        If graph_uri is provided, computes analytics scoped to quads in that graph only.
        Results are NOT stored (on-demand graph-filtered view).
        """
        start = time.monotonic()

        async with self._pool.acquire() as conn:
            # Set statement timeout to prevent runaway queries on large spaces (60s)
            await conn.execute("SET LOCAL statement_timeout = '60s'")

            # Verify space tables exist
            table_exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                f"{space_id}_rdf_quad"
            )
            if not table_exists:
                logger.warning("AnalyticsJob: space tables not found for %s, skipping", space_id)
                return {"space_id": space_id, "skipped": True}

            # Resolve graph filter to graph_id if provided
            graph_id = None
            if graph_uri:
                graph_id = await conn.fetchval(
                    "SELECT graph_id FROM graph WHERE space_id = $1 AND graph_uri = $2",
                    space_id, graph_uri
                )
                if graph_id is None:
                    return {"space_id": space_id, "error": f"Graph not found: {graph_uri}"}

            entity_analytics = await self._compute_entity_analytics(conn, space_id, graph_id)
            frame_analytics = await self._compute_frame_analytics(conn, space_id, graph_id)
            relation_analytics = await self._compute_relation_analytics(conn, space_id, graph_id)
            property_analytics = await self._compute_property_analytics(conn, space_id, graph_id)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        analytics_data = {
            "space_id": space_id,
            "entity_analytics": entity_analytics,
            "frame_analytics": frame_analytics,
            "relation_analytics": relation_analytics,
            "property_analytics": property_analytics,
        }

        # Only store if full space computation (not graph-filtered)
        if not graph_uri:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO space_analytics (space_id, computed_at, computation_time_ms, analytics_json)
                       VALUES ($1, NOW(), $2, $3::jsonb)""",
                    space_id, elapsed_ms, json.dumps(analytics_data)
                )

        logger.info("AnalyticsJob: space=%s graph=%s completed in %dms", space_id, graph_uri or 'all', elapsed_ms)
        return {"space_id": space_id, "computation_time_ms": elapsed_ms, "analytics": analytics_data}

    # ------------------------------------------------------------------
    # Entity analytics
    # ------------------------------------------------------------------

    def _graph_filter(self, graph_id: Optional[int], alias: str = 'q') -> str:
        """Return a SQL AND clause filtering by graph_id if provided."""
        if graph_id is not None:
            return f" AND {alias}.graph_id = {int(graph_id)}"
        return ""

    async def _compute_entity_analytics(self, conn, space_id: str, graph_id: Optional[int] = None) -> Dict[str, Any]:
        """Compute entity type distribution and frame relationship stats."""
        t_quad = f"{space_id}_rdf_quad"
        t_term = f"{space_id}_term"
        gf = self._graph_filter(graph_id)

        # Get type distribution for entities (vitaltype containing 'Entity')
        type_rows = await conn.fetch(f"""
            SELECT o_term.term_text AS type_uri, COUNT(DISTINCT q.subject_uuid) AS cnt
            FROM {t_quad} q
            JOIN {t_term} p_term ON q.predicate_uuid = p_term.term_uuid
            JOIN {t_term} o_term ON q.object_uuid = o_term.term_uuid
            WHERE p_term.term_text = $1
              AND o_term.term_text LIKE '%Entity%'{gf}
            GROUP BY o_term.term_text
            ORDER BY cnt DESC
            LIMIT 50
        """, _VITALTYPE)

        type_distribution = [
            {"type_uri": row["type_uri"], "type_name": _short_name(row["type_uri"]), "count": row["cnt"]}
            for row in type_rows
        ]
        total_count = sum(row["cnt"] for row in type_rows)

        # Count entities with at least one frame (via Edge_hasEntityKGFrame)
        with_frames_count = await conn.fetchval(f"""
            SELECT COUNT(DISTINCT src_term.term_text)
            FROM {t_quad} type_q
            JOIN {t_term} type_p ON type_q.predicate_uuid = type_p.term_uuid
            JOIN {t_term} type_o ON type_q.object_uuid = type_o.term_uuid
            JOIN {t_quad} src_q ON type_q.subject_uuid = src_q.subject_uuid
            JOIN {t_term} src_p ON src_q.predicate_uuid = src_p.term_uuid
            JOIN {t_term} src_term ON src_q.object_uuid = src_term.term_uuid
            WHERE type_p.term_text = $1
              AND type_o.term_text = $2
              AND src_p.term_text = $3
        """, _VITALTYPE, _EDGE_HAS_ENTITY_KG_FRAME, _HAS_EDGE_SOURCE) or 0

        orphan_count = max(0, total_count - with_frames_count)

        # Average frames per entity
        avg_frames = 0.0
        if with_frames_count > 0:
            total_frame_edges = await conn.fetchval(f"""
                SELECT COUNT(*)
                FROM {t_quad} q
                JOIN {t_term} p_term ON q.predicate_uuid = p_term.term_uuid
                JOIN {t_term} o_term ON q.object_uuid = o_term.term_uuid
                WHERE p_term.term_text = $1
                  AND o_term.term_text = $2
            """, _VITALTYPE, _EDGE_HAS_ENTITY_KG_FRAME) or 0
            avg_frames = round(total_frame_edges / max(with_frames_count, 1), 2)

        return {
            "total_count": total_count,
            "type_distribution": type_distribution,
            "with_frames_count": with_frames_count,
            "orphan_count": orphan_count,
            "avg_frames_per_entity": avg_frames,
        }

    # ------------------------------------------------------------------
    # Frame analytics
    # ------------------------------------------------------------------

    async def _compute_frame_analytics(self, conn, space_id: str, graph_id: Optional[int] = None) -> Dict[str, Any]:
        """Compute frame and slot type distributions."""
        t_quad = f"{space_id}_rdf_quad"
        t_term = f"{space_id}_term"
        gf = self._graph_filter(graph_id)

        # Frame type distribution
        frame_rows = await conn.fetch(f"""
            SELECT o_term.term_text AS type_uri, COUNT(DISTINCT q.subject_uuid) AS cnt
            FROM {t_quad} q
            JOIN {t_term} p_term ON q.predicate_uuid = p_term.term_uuid
            JOIN {t_term} o_term ON q.object_uuid = o_term.term_uuid
            WHERE p_term.term_text = $1
              AND o_term.term_text LIKE '%Frame%'
              AND o_term.term_text NOT LIKE '%Edge%'{gf}
            GROUP BY o_term.term_text
            ORDER BY cnt DESC
            LIMIT 50
        """, _VITALTYPE)

        frame_type_distribution = [
            {"type_uri": row["type_uri"], "type_name": _short_name(row["type_uri"]), "count": row["cnt"]}
            for row in frame_rows
        ]
        total_frame_count = sum(row["cnt"] for row in frame_rows)

        # Slot type distribution
        slot_rows = await conn.fetch(f"""
            SELECT o_term.term_text AS type_uri, COUNT(DISTINCT q.subject_uuid) AS cnt
            FROM {t_quad} q
            JOIN {t_term} p_term ON q.predicate_uuid = p_term.term_uuid
            JOIN {t_term} o_term ON q.object_uuid = o_term.term_uuid
            WHERE p_term.term_text = $1
              AND o_term.term_text LIKE '%Slot%'{gf}
            GROUP BY o_term.term_text
            ORDER BY cnt DESC
            LIMIT 50
        """, _VITALTYPE)

        slot_type_distribution = [
            {"type_uri": row["type_uri"], "type_name": _short_name(row["type_uri"]), "count": row["cnt"]}
            for row in slot_rows
        ]
        total_slot_count = sum(row["cnt"] for row in slot_rows)

        # Avg slots per frame
        avg_slots_per_frame = round(total_slot_count / max(total_frame_count, 1), 2)

        # Frames without slots (frames not appearing as source in Edge_hasKGSlot)
        frames_with_slots = await conn.fetchval(f"""
            SELECT COUNT(DISTINCT src_term.term_text)
            FROM {t_quad} type_q
            JOIN {t_term} type_p ON type_q.predicate_uuid = type_p.term_uuid
            JOIN {t_term} type_o ON type_q.object_uuid = type_o.term_uuid
            JOIN {t_quad} src_q ON type_q.subject_uuid = src_q.subject_uuid
            JOIN {t_term} src_p ON src_q.predicate_uuid = src_p.term_uuid
            JOIN {t_term} src_term ON src_q.object_uuid = src_term.term_uuid
            WHERE type_p.term_text = $1
              AND type_o.term_text = $2
              AND src_p.term_text = $3
        """, _VITALTYPE, _EDGE_HAS_KG_SLOT, _HAS_EDGE_SOURCE) or 0

        without_slots_count = max(0, total_frame_count - frames_with_slots)

        return {
            "total_count": total_frame_count,
            "type_distribution": frame_type_distribution,
            "total_slot_count": total_slot_count,
            "slot_type_distribution": slot_type_distribution,
            "avg_slots_per_frame": avg_slots_per_frame,
            "without_slots_count": without_slots_count,
        }

    # ------------------------------------------------------------------
    # Relation analytics
    # ------------------------------------------------------------------

    async def _compute_relation_analytics(self, conn, space_id: str, graph_id: Optional[int] = None) -> Dict[str, Any]:
        """Compute edge type distribution and classification."""
        t_quad = f"{space_id}_rdf_quad"
        t_term = f"{space_id}_term"
        gf = self._graph_filter(graph_id)

        # Edge type distribution
        edge_rows = await conn.fetch(f"""
            SELECT o_term.term_text AS type_uri, COUNT(DISTINCT q.subject_uuid) AS cnt
            FROM {t_quad} q
            JOIN {t_term} p_term ON q.predicate_uuid = p_term.term_uuid
            JOIN {t_term} o_term ON q.object_uuid = o_term.term_uuid
            WHERE p_term.term_text = $1
              AND o_term.term_text LIKE '%Edge_%'{gf}
            GROUP BY o_term.term_text
            ORDER BY cnt DESC
            LIMIT 50
        """, _VITALTYPE)

        edge_type_distribution = [
            {"type_uri": row["type_uri"], "type_name": _short_name(row["type_uri"]), "count": row["cnt"]}
            for row in edge_rows
        ]
        total_edge_count = sum(row["cnt"] for row in edge_rows)

        # Classify specific edge types
        edge_type_map = {row["type_uri"]: row["cnt"] for row in edge_rows}
        inter_entity_count = edge_type_map.get(_EDGE_HAS_KG_RELATION, 0)
        entity_frame_count = edge_type_map.get(_EDGE_HAS_ENTITY_KG_FRAME, 0)
        frame_slot_count = edge_type_map.get(_EDGE_HAS_KG_SLOT, 0)

        # Most connected entities (top 10 by total edge count from edge table)
        most_connected = []
        try:
            t_edge = f"{space_id}_edge"
            connected_rows = await conn.fetch(f"""
                SELECT term.term_text AS entity_uri, edge_count
                FROM (
                    SELECT node_uuid, COUNT(*) AS edge_count FROM (
                        SELECT source_node_uuid AS node_uuid FROM {t_edge}
                        UNION ALL
                        SELECT dest_node_uuid AS node_uuid FROM {t_edge}
                    ) all_nodes
                    GROUP BY node_uuid
                    ORDER BY edge_count DESC
                    LIMIT 10
                ) top_nodes
                JOIN {t_term} term ON top_nodes.node_uuid = term.term_uuid
                ORDER BY edge_count DESC
            """)
            for row in connected_rows:
                most_connected.append({
                    "entity_uri": row["entity_uri"],
                    "entity_name": _short_name(row["entity_uri"]),
                    "edge_count": row["edge_count"],
                })
        except Exception as e:
            logger.warning("AnalyticsJob: most_connected query failed for %s: %s", space_id, e)

        return {
            "total_edge_count": total_edge_count,
            "edge_type_distribution": edge_type_distribution,
            "inter_entity_relation_count": inter_entity_count,
            "entity_frame_edge_count": entity_frame_count,
            "frame_slot_edge_count": frame_slot_count,
            "most_connected_entities": most_connected,
        }

    # ------------------------------------------------------------------
    # Property analytics
    # ------------------------------------------------------------------

    async def _compute_property_analytics(self, conn, space_id: str, graph_id: Optional[int] = None) -> Dict[str, Any]:
        """Compute predicate usage and literal type distributions."""
        t_quad = f"{space_id}_rdf_quad"
        t_term = f"{space_id}_term"
        gf = self._graph_filter(graph_id)

        # Distinct predicate count
        distinct_pred_count = await conn.fetchval(f"""
            SELECT COUNT(DISTINCT predicate_uuid) FROM {t_quad} q WHERE 1=1{gf}
        """) or 0

        # Top 20 predicates by usage
        pred_rows = await conn.fetch(f"""
            SELECT p_term.term_text AS predicate_uri, COUNT(*) AS cnt
            FROM {t_quad} q
            JOIN {t_term} p_term ON q.predicate_uuid = p_term.term_uuid
            WHERE 1=1{gf}
            GROUP BY p_term.term_text
            ORDER BY cnt DESC
            LIMIT 20
        """)
        top_predicates = [
            {"predicate_uri": row["predicate_uri"], "short_name": _short_name(row["predicate_uri"]), "count": row["cnt"]}
            for row in pred_rows
        ]

        # Literal type distribution (datatype of object terms that are literals)
        literal_rows = await conn.fetch(f"""
            SELECT
                COALESCE(dt.datatype_uri, 'xsd:string') AS type_uri,
                COUNT(*) AS cnt
            FROM {t_term} t
            LEFT JOIN {space_id}_datatype dt ON t.datatype_id = dt.datatype_id
            WHERE t.term_type = 'L'
            GROUP BY dt.datatype_uri
            ORDER BY cnt DESC
        """)
        literal_type_distribution = [
            {"type_uri": row["type_uri"], "type_name": _short_name(row["type_uri"]), "count": row["cnt"]}
            for row in literal_rows
        ]

        return {
            "distinct_predicate_count": distinct_pred_count,
            "top_predicates": top_predicates,
            "literal_type_distribution": literal_type_distribution,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _list_spaces(self) -> List[str]:
        """List all space_ids from the space admin table."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT space_id FROM space ORDER BY space_id")
        return [row["space_id"] for row in rows]
