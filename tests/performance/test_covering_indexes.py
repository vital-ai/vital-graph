"""P1 / Tier 1 gate: graph-scoped reads are Index-Only via the covering indexes.

Proves the new (context_uuid, subject_uuid) INCLUDE (...) covering index turns a
graph-scoped lookup into an **Index Only Scan with 0 heap fetches** — no random
reads into the (huge, at scale) heap. This is the highest-value read change and
its plan-shape holds at any size.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from test_scripts.data.generate_scale_data import load_scale_space
from .conftest import skip_no_pg
from .harness import assert_plan, node_types

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "perf_cov"
GRAPH = "urn:perf"


async def test_subject_scoped_read_is_index_only(perf_pool):
    # 20K entities: plenty for the planner to prefer the index on an equality
    # lookup; small enough to load fast. load_scale_space VACUUMs so index-only
    # scans have their visibility map set.
    await load_scale_space(perf_pool, SPACE, 20_000, graph_uri=GRAPH, drop_first=True)
    try:
        g_uuid = _generate_term_uuid(GRAPH, "U")
        s_uuid = _generate_term_uuid("urn:perf:e:000000000", "U")  # one entity

        # Graph-scoped subject lookup — all of one entity's props. With
        # (context_uuid, subject_uuid) INCLUDE (predicate_uuid, object_uuid) this
        # is served entirely from the index (no heap).
        sql = (f"SELECT predicate_uuid, object_uuid FROM {SPACE}_rdf_quad "
               f"WHERE context_uuid = $1 AND subject_uuid = $2")
        async with perf_pool.acquire() as conn:
            plan = await assert_plan(
                conn, sql, g_uuid, s_uuid,
                must_use_index=f"idx_{SPACE}_quad_ctx_subj",
                index_only=True,                 # Index Only Scan + 0 heap fetches
                no_seq_scan_on=[f"{SPACE}_rdf_quad"],
                max_shared_buffers=200,
                max_actual_rows_bound=50,
                no_spill=True,
            )
            print(f"\nsubject-scoped read node types: {node_types(plan)}")
    finally:
        async with perf_pool.acquire() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, SPACE)
            except Exception:
                pass
