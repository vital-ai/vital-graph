"""L2 gate for nested-frame traversal (frame_entity_integrity_plan.md §7).

Arbitrary-depth frame nesting (`frame Edge_hasKGFrame* ...`) compiles to a
recursive CTE whose per-hop lookup is a single edge-table probe. For that to
stay cheap at any depth/scale, each hop must be an **Index Only Scan** on the
edge composite indexes, in BOTH directions:
  - parent→child  (source_node_uuid = ?)  → idx_{space}_edge_src_dst
  - child→parent  (dest_node_uuid   = ?)  → idx_{space}_edge_dst_src

This test guards against an edge-index or edge-completeness regression turning a
hop into a Seq Scan (which would make deep frame paths blow up).
"""

from __future__ import annotations

import uuid as _uuid

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from .conftest import skip_no_pg
from .harness import assert_plan, node_types

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "perf_edgehop"
_NS = _uuid.UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")


async def _seed_edges(pool, n_sources=1000, fanout=10):
    """Create the space and COPY n_sources*fanout edge rows (frame->frame style)."""
    g = _uuid.uuid5(_NS, "ctx")
    rows = []
    for s in range(n_sources):
        src = _uuid.uuid5(_NS, f"src:{s}")
        for d in range(fanout):
            dst = _uuid.uuid5(_NS, f"dst:{s}:{d}")
            rows.append((_uuid.uuid5(_NS, f"e:{s}:{d}"), src, dst, g))
    async with pool.acquire() as conn:
        try:
            await SparqlSQLSchema.drop_space(conn, SPACE)
        except Exception:
            pass
        await SparqlSQLSchema.create_space(conn, SPACE)
        t = SparqlSQLSchema.get_table_names(SPACE)
        await conn.copy_records_to_table(
            t["edge"].split(".")[-1], records=rows,
            columns=["edge_uuid", "source_node_uuid", "dest_node_uuid", "context_uuid"])
        await conn.execute(f"VACUUM (ANALYZE) {t['edge']}")   # set visibility map
    return _uuid.uuid5(_NS, "src:0"), _uuid.uuid5(_NS, "dst:0:0")


async def test_edge_hops_are_index_only_both_directions(perf_pool):
    src, dst = await _seed_edges(perf_pool)
    try:
        async with perf_pool.acquire() as conn:
            # The invariant is the plan shape: an Index Only Scan on the covering
            # edge index, no Seq Scan, both directions.  Runtime heap fetches
            # depend on the visibility map (VACUUM vs the suite's xmin horizon),
            # so they're not asserted here — that's require_zero_heap_fetches=False.
            # parent -> child hop
            p1 = await assert_plan(
                conn,
                f"SELECT dest_node_uuid FROM {SPACE}_edge WHERE source_node_uuid = $1", src,
                must_use_index=f"idx_{SPACE}_edge_src_dst",
                index_only=True, require_zero_heap_fetches=False,
                no_seq_scan_on=[f"{SPACE}_edge"], no_spill=True)
            # child -> parent hop
            p2 = await assert_plan(
                conn,
                f"SELECT source_node_uuid FROM {SPACE}_edge WHERE dest_node_uuid = $1", dst,
                must_use_index=f"idx_{SPACE}_edge_dst_src",
                index_only=True, require_zero_heap_fetches=False,
                no_seq_scan_on=[f"{SPACE}_edge"], no_spill=True)
            print(f"\nedge hops: fwd={node_types(p1)} rev={node_types(p2)}")
    finally:
        async with perf_pool.acquire() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, SPACE)
            except Exception:
                pass
