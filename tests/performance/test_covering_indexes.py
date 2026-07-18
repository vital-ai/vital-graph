"""P1 / Tier 1 gate: graph-scoped predicate scans are Index-Only via the
(context_uuid, predicate_uuid) INCLUDE(...) covering index.

Proves the covering index turns a graph-scoped predicate scan into an
**Index Only Scan with 0 heap fetches** — no random reads into the (huge, at
scale) heap. This is the one covering index that pays off; the subject-scoped
case is already served index-only by the 5-column PK (measured), so it was not
added.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from test_scripts.data.generate_scale_data import load_scale_space, HASNAME
from .conftest import skip_no_pg
from .harness import assert_plan, node_types, total_shared_buffers

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "perf_cov"
GRAPH = "urn:perf"


async def test_graph_scoped_predicate_scan_is_index_only(perf_pool):
    # 100K entities: enough that the planner prefers the covering index (index-
    # only) over a seq scan for a graph-scoped predicate scan.
    await load_scale_space(perf_pool, SPACE, 100_000, graph_uri=GRAPH, drop_first=True)
    try:
        g_uuid = _generate_term_uuid(GRAPH, "U")
        p_uuid = _generate_term_uuid(HASNAME, "U")   # every entity has one

        sql = (f"SELECT subject_uuid, object_uuid FROM {SPACE}_rdf_quad "
               f"WHERE context_uuid = $1 AND predicate_uuid = $2")
        async with perf_pool.acquire() as conn:
            plan = await assert_plan(
                conn, sql, g_uuid, p_uuid,
                must_use_index=f"idx_{SPACE}_quad_ctx_pred",
                index_only=True,                     # Index Only Scan + 0 heap fetches
                no_seq_scan_on=[f"{SPACE}_rdf_quad"],
                no_spill=True,
            )
            print(f"\npredicate-scan: {node_types(plan)} buffers={total_shared_buffers(plan)}")
    finally:
        async with perf_pool.acquire() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, SPACE)
            except Exception:
                pass
