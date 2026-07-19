"""L2 gate: extended statistics fix the predicate/object correlation underestimate.

Root cause of the high-cardinality slot-value 60s timeouts
(high_cardinality_slot_value_query_plan.md): Postgres assumes
predicate_uuid ⟂ object_uuid and multiplies selectivities, so a
(slot-predicate, value) leaf that actually matches thousands of rows is
estimated at ~tens — the planner then seeds an 8-way join there and picks all
nested loops -> timeout.

Runs against the real nurture lead dataset (a boolean slot value that only ever
appears as the object of `hasBooleanSlotValue` — the same correlation shape as
the prod `hasUriSlotValue -> nurture_lead`), and asserts the planner's estimate
is ACCURATE with the extended stats the schema creates and badly UNDER-estimated
without them. Skips if no such space is loaded.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from .conftest import skip_no_pg, space_exists
from .harness import explain_json, estimated_rows, actual_rows

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# Pre-loaded realistic spaces; hasBooleanSlotValue -> "false"/"true" is a value
# that only ever appears under that one predicate (100% correlated).
CANDIDATES = ["space_lead_dataset_test", "sp_sql_lead_dataset"]
SLOT_PRED = "http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue"


async def _pick_loaded(conn):
    for sp in CANDIDATES:
        if await space_exists(conn, sp):
            return sp
    return None


def _stats_ddl(space_id):
    stat = f"stat_{space_id}_quad_po"
    return (
        f"CREATE STATISTICS IF NOT EXISTS {stat} (mcv, ndistinct) "
        f"ON predicate_uuid, object_uuid FROM {space_id}_rdf_quad",
        f"ALTER STATISTICS {stat} SET STATISTICS 1000")


async def test_extended_stats_fix_correlation_estimate(perf_pool):
    async with perf_pool.acquire() as conn:
        space_id = await _pick_loaded(conn)
        if not space_id:
            pytest.skip("no realistic lead dataset loaded")
        stat = f"stat_{space_id}_quad_po"
        create, tune = _stats_ddl(space_id)

        p_slot = _generate_term_uuid(SLOT_PRED, "U")
        # The most common object of the slot predicate is the correlated value.
        o_val = await conn.fetchval(
            f"SELECT object_uuid FROM {space_id}_rdf_quad WHERE predicate_uuid = $1 "
            f"GROUP BY object_uuid ORDER BY count(*) DESC LIMIT 1", p_slot)
        if o_val is None:
            pytest.skip(f"{space_id} has no {SLOT_PRED} slot values")

        sql = (f"SELECT 1 FROM {space_id}_rdf_quad "
               f"WHERE predicate_uuid = $1 AND object_uuid = $2")
        try:
            # WITH extended stats.
            await conn.execute(create)
            await conn.execute(tune)
            await conn.execute(f"ANALYZE {space_id}_rdf_quad")
            plan = await explain_json(conn, sql, p_slot, o_val)
            est_with, act = estimated_rows(plan), actual_rows(plan)

            # WITHOUT them -> the independence-assumption underestimate.
            await conn.execute(f"DROP STATISTICS IF EXISTS {stat}")
            await conn.execute(f"ANALYZE {space_id}_rdf_quad")
            est_without = estimated_rows(await explain_json(conn, sql, p_slot, o_val))

            print(f"\n[{space_id}] correlated leaf: actual={act} "
                  f"est_with={est_with} est_without={est_without} "
                  f"(under-est {act / max(est_without, 1):.0f}x without)")

            assert 0.25 * act <= est_with <= 4 * act, (
                f"extended stats did not correct the estimate: est={est_with} actual={act}")
            assert est_without <= act / 10, (
                f"expected a large underestimate without stats; est={est_without} actual={act}")
        finally:
            # Restore the stats so the shared space is left improved, not degraded.
            await conn.execute(create)
            await conn.execute(tune)
            await conn.execute(f"ANALYZE {space_id}_rdf_quad")
