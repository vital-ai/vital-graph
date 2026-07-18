"""L2 gate: extended statistics fix the predicate/object correlation underestimate.

Root cause of the high-cardinality slot-value 60s timeouts
(high_cardinality_slot_value_query_plan.md): Postgres assumes
predicate_uuid ⟂ object_uuid and multiplies selectivities, so a
(slot-predicate, value) leaf that actually matches tens of thousands of rows is
estimated at ~tens — the planner then seeds an 8-way join there and picks all
nested loops -> timeout.

This test builds a correlated dataset (a value that only ever appears as the
object of one predicate) and asserts the planner's estimate is:
  - ACCURATE with the extended stats the schema now creates (within a small factor)
  - badly UNDER-estimated without them (proving the stats are what fix it)
"""

from __future__ import annotations

import uuid as _uuid

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from .conftest import skip_no_pg
from .harness import explain_json, estimated_rows, actual_rows

pytestmark = [pytest.mark.performance, pytest.mark.slow, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "perf_corr"
_NS = _uuid.UUID("6ba7b815-9dad-11d1-80b4-00c04fd430c8")
N_FILLER = 1_000_000
M_CORR = 20_000        # the correlated (slot-predicate, value) rows


def _u(s: str):
    return _uuid.uuid5(_NS, s)


async def _load_correlated(pool):
    """COPY a big table where one (predicate, object) pair is 100% correlated."""
    g = _u("ctx")
    p_slot, p_filler, o_val = _u("pred:slot"), _u("pred:filler"), _u("obj:val")
    quads = []
    for i in range(N_FILLER):                       # filler: varied predicate/object
        quads.append((_u(f"s:{i}"), p_filler, _u(f"o:{i % 1000}"), g, _u(f"qf:{i}")))
    for j in range(M_CORR):                         # correlated: p_slot only ever -> o_val
        quads.append((_u(f"cs:{j}"), p_slot, o_val, g, _u(f"qc:{j}")))
    async with pool.acquire() as conn:
        try:
            await SparqlSQLSchema.drop_space(conn, SPACE)
        except Exception:
            pass
        await SparqlSQLSchema.create_space(conn, SPACE)   # creates the extended stats DDL
        t = SparqlSQLSchema.get_table_names(SPACE)
        await conn.copy_records_to_table(
            t["rdf_quad"].split(".")[-1], records=quads,
            columns=["subject_uuid", "predicate_uuid", "object_uuid",
                     "context_uuid", "quad_uuid"])
        await conn.execute(f"VACUUM (ANALYZE) {t['rdf_quad']}")
    return p_slot, o_val


async def test_extended_stats_fix_correlation_estimate(perf_pool):
    p_slot, o_val = await _load_correlated(perf_pool)
    sql = f"SELECT 1 FROM {SPACE}_rdf_quad WHERE predicate_uuid = $1 AND object_uuid = $2"
    try:
        async with perf_pool.acquire() as conn:
            # WITH extended stats (created by the schema DDL).
            plan = await explain_json(conn, sql, p_slot, o_val)
            est_with, act = estimated_rows(plan), actual_rows(plan)

            # Remove them and re-ANALYZE → the independence-assumption underestimate.
            await conn.execute(f"DROP STATISTICS IF EXISTS stat_{SPACE}_quad_po")
            await conn.execute(f"ANALYZE {SPACE}_rdf_quad")
            plan2 = await explain_json(conn, sql, p_slot, o_val)
            est_without = estimated_rows(plan2)

            print(f"\ncorrelated leaf: actual={act} est_with_stats={est_with} "
                  f"est_without={est_without} "
                  f"(under-est {act / max(est_without,1):.0f}x without)")

            # With stats: estimate within ~4x of actual (correlation captured).
            assert 0.25 * act <= est_with <= 4 * act, (
                f"extended stats did not correct the estimate: est={est_with} actual={act}")
            # Without stats: badly under-estimated (this is the bug the stats fix).
            assert est_without <= act / 10, (
                f"expected a large underestimate without stats; got est={est_without} actual={act}")
    finally:
        async with perf_pool.acquire() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, SPACE)
            except Exception:
                pass
