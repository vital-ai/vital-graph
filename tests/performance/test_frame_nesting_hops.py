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


async def _seed_edges(pool, space_manager, n_sources=1000, fanout=10):
    """Create the space and COPY n_sources*fanout edge rows (frame->frame style).

    Through the SPACE MANAGER, so the space gets its registry row as well as its
    tables. Calling `SparqlSQLSchema.create_space` directly left a table group
    with no row in `space` — which is what every reconciliation reports as
    orphaned debris, and what `cleanup_orphan_space_tables --apply` drops once it
    is empty. This benchmark never inserts a quad, so it was permanently empty
    and permanently eligible.
    """
    g = _uuid.uuid5(_NS, "ctx")
    rows = []
    for s in range(n_sources):
        src = _uuid.uuid5(_NS, f"src:{s}")
        for d in range(fanout):
            dst = _uuid.uuid5(_NS, f"dst:{s}:{d}")
            rows.append((_uuid.uuid5(_NS, f"e:{s}:{d}"), src, dst, g))
    await space_manager.delete_space_with_tables(SPACE)
    ok = await space_manager.create_space_with_tables(SPACE, SPACE)
    assert ok, f"space manager failed to create {SPACE}"
    async with pool.acquire() as conn:
        t = SparqlSQLSchema.get_table_names(SPACE)
        await conn.copy_records_to_table(
            t["edge"].split(".")[-1], records=rows,
            columns=["edge_uuid", "source_node_uuid", "dest_node_uuid", "context_uuid"])
        await conn.execute(f"VACUUM (ANALYZE) {t['edge']}")   # set visibility map

        # DID the VACUUM actually set it? It cannot mark a page all-visible
        # while an older snapshot is open anywhere in the cluster, and this
        # suite shares a database with the app container's background jobs.
        # Without the map an Index Only Scan is unavailable and the planner
        # takes a Bitmap Heap Scan — the assertion below then fails with
        # "expected an Index Only Scan", which reads as a query-shape
        # regression and is nothing of the sort.
        #
        # Confirmed rather than guessed: holding one idle-in-transaction
        # snapshot in another session makes this test fail every time, and it
        # passes every time without one. It had been recorded as "flaky" twice
        # on the strength of passing when re-run alone.
        allvisible = await conn.fetchval(
            "SELECT relallvisible FROM pg_class WHERE relname = $1",
            t["edge"].split(".")[-1])
    if not allvisible:
        pytest.skip(
            "the visibility map could not be set — another session holds an "
            "older snapshot, so an Index Only Scan is unavailable and this "
            "test would be measuring that rather than the index")
    return _uuid.uuid5(_NS, "src:0"), _uuid.uuid5(_NS, "dst:0:0")


@pytest.mark.bench("query.frame_nesting.edge_hops_index_only")
async def test_edge_hops_are_index_only_both_directions(
        perf_pool, perf_space_manager, perf_record):
    src, dst = await _seed_edges(perf_pool, perf_space_manager)
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
            perf_record(plan=p1, dataset="synthetic:edges",
                        notes="forward hop (source→dest)")
            print(f"\nedge hops: fwd={node_types(p1)} rev={node_types(p2)}")
    finally:
        # Through the manager too, so the registry row goes with the tables.
        # `SparqlSQLSchema.drop_space` removes only the tables, which would leave
        # a `space` row pointing at nothing — the mirror-image residue of what
        # creating outside the manager left.
        try:
            await perf_space_manager.delete_space_with_tables(SPACE)
        except Exception:
            pass
