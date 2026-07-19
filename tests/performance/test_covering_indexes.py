"""P1 / Tier 1 gate: graph-scoped predicate scans are Index-Only via the
(context_uuid, predicate_uuid) INCLUDE(subject, object) covering index.

Runs against a pre-loaded realistic KG space (the nurture lead dataset) with a
selective graph-scoped predicate. On realistic data the planner serves the scan
from the covering index as an **Index Only Scan with 0 heap fetches** across the
whole selectivity range. (The earlier synthetic fixture had only ~50%-selectivity
predicates, where PG18's cost model prefers a bitmap heap scan — a poor
demonstration, not a covering-index failure.)

Skips if no such space is loaded (see the `require_space` pattern in conftest).
The covering index and a VACUUM (for the visibility map that index-only needs)
are ensured idempotently on first run.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from .conftest import skip_no_pg, space_exists
from .harness import assert_plan, node_types, total_shared_buffers

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# (space_id, graph_uri, selective_predicate_uri) — pre-loaded realistic spaces,
# tried in order. hasKGEntityType is a natural, selective entity-type filter.
CANDIDATES = [
    ("space_lead_dataset_test", "urn:lead_entity_graph_dataset",
     "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"),
    ("sp_sql_lead_dataset", "urn:lead_entity_graph_dataset",
     "http://vital.ai/ontology/haley-ai-kg#hasKGEntityType"),
]
_INCLUDE = "(context_uuid, predicate_uuid) INCLUDE (subject_uuid, object_uuid)"


async def _pick_loaded(conn):
    for sp, g, p in CANDIDATES:
        if await space_exists(conn, sp):
            return sp, g, p
    return None


async def test_selective_graph_scoped_scan_is_index_only(perf_pool):
    async with perf_pool.acquire() as conn:
        pick = await _pick_loaded(conn)
        if not pick:
            pytest.skip("no realistic lead dataset loaded")
        space_id, graph_uri, pred_uri = pick

        # Ensure the covering index + a set visibility map (index-only needs it).
        # Idempotent; the index persists after the first run.
        idx = f"idx_{space_id}_quad_ctx_pred"
        await conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON {space_id}_rdf_quad {_INCLUDE}")
        await conn.execute(f"VACUUM (ANALYZE) {space_id}_rdf_quad")

        g_uuid = _generate_term_uuid(graph_uri, "U")
        p_uuid = _generate_term_uuid(pred_uri, "U")
        sql = (f"SELECT subject_uuid, object_uuid FROM {space_id}_rdf_quad "
               f"WHERE context_uuid = $1 AND predicate_uuid = $2")

        plan = await assert_plan(
            conn, sql, g_uuid, p_uuid,
            must_use_index=idx,
            index_only=True,                      # Index Only Scan + 0 heap fetches
            no_seq_scan_on=[f"{space_id}_rdf_quad"],
            no_spill=True,
        )
        matched = await conn.fetchval(
            f"SELECT count(*) FROM {space_id}_rdf_quad "
            f"WHERE context_uuid = $1 AND predicate_uuid = $2", g_uuid, p_uuid)
        print(f"\n[{space_id}] graph-scoped scan matched {matched} rows: "
              f"{node_types(plan)} buffers={total_shared_buffers(plan)}")
