"""What a page costs at DEPTH — the dimension no benchmark varied.

A record of the collapse. `078` is REOPENED: the fix that flattened this curve
was reverted on 2026-08-12 because it returned INCORRECT PAGES — it sliced the
match set by entity uuid while the query's own `ORDER BY ?entity` orders by URI
text, so consecutive pages came from two different total orders and rows were
both skipped and repeated (`issues/083`). The numbers below are the reverted-to
behaviour and are what this file measures again.

`issues/078`. Every performance test in this repo pages at `offset=0`; the only
offset literal anywhere in `tests/performance/` was zero. So the whole two-phase
paging effort — `040`, `047`, `053`, `059`-`061` — was validated on page 1, and
nothing was ever asserted about page 2 onward. It does not hold there.

Measured on `sp_lead_synth_100k` with a 16 GB buffer pool (the pool matters
enormously here — see `issues/081`; on the 1 GB pool page 41 timed out):

    page      offset    two-phase ordered scan
       1           0        52 ms
       2          25       128 ms
       3          50       226 ms
       5         100       343 ms
      11         250       673 ms
      41       1,000     2,958 ms
     201       5,000    16,271 ms

The shape is O(offset), because `OFFSET` defeats the early termination the plan
is built around: the scan must produce and discard N rows, each paying the
criteria probe. A materialise shape is flat at ~310 ms for the same query at any
depth, which is the fix `078` proposes.

WHAT THIS FILE IS FOR. It records the curve so a fix can be shown to flatten it,
and so the collapse cannot return unnoticed. The assertions deliberately pin the
SHAPE — that cost grows with offset, and by how much at worst — rather than
laptop timings, which move with the buffer pool by more than 25x.
"""

from __future__ import annotations

import time

import pytest

from .lead_fixtures import SYNTH, require_usable
from .test_kgquery_growth_curve import (
    KGENTITY, PAGE_SIZE, SIDECAR_URL, skip_no_pg,
)

FIXTURES = SYNTH

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# Page 1 against page 41. This gates the COLLAPSE, not a fix — the fix was
# reverted (see the header), so the O(offset) shape is present and expected, and
# the measured ratio is ~57x.
#
# It was briefly tightened to 50 to lock in the fix. That was wrong twice over:
# the fix returned incorrect pages, and a threshold below the CURRENT measured
# value is a permanently red test rather than a regression gate. 400 leaves room
# above the ~57x for a noisy laptop and a cold pool, while still catching a real
# worsening of the shape.
DEEP_RATIO_ALARM = 400

OFFSETS = [0, 250, 1000]


async def _sql_at(conn, fx, offset):
    from .test_kgquery_generated_sql_plans import _to_builder_frame
    from scripts.perf_shape_matrix import build_criteria
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    crit = build_criteria(
        comparator="eq",
        slot_class="http://vital.ai/ontology/haley-ai-kg#KGTextSlot")
    ec = EntityQueryCriteria(
        entity_type=KGENTITY, entity_uris=None,
        frame_criteria=[_to_builder_frame(f) for f in crit],
        use_edge_pattern=True)
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        ec, fx.graph, PAGE_SIZE, offset)
    client = AsyncSidecarClient(SIDECAR_URL)
    try:
        raw = await client.compile(sparql)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    if not cr.ok:
        pytest.fail(f"paging SPARQL failed to compile at offset {offset}: {cr.error}")
    gen = await generate_sql(cr, fx.space, conn=conn)
    if not gen.ok:
        pytest.fail(f"paging SQL failed to generate at offset {offset}: {gen.error}")
    return gen.sql


async def _warm_ms(conn, sql):
    async def once():
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_sort = off")
            t0 = time.perf_counter()
            rows = await conn.fetch(sql)
            return (time.perf_counter() - t0) * 1000.0, len(rows)

    await once()
    runs = [await once() for _ in range(3)]
    return sorted(t for t, _ in runs)[1], runs[-1][1]


@pytest.mark.bench("query.kgquery.deep_paging.curve")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_page_cost_across_offsets(perf_conn, perf_record, fx):
    """The curve itself. A flat one means a fix landed; a steep one is issues/078."""
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    # An offset past the end of the match set returns 0 rows — that is the
    # FIXTURE being smaller than the offset, not a defect. The 10k fixture has
    # ~900 matches for this criterion, so offset 1000 is off the end of it.
    # Those points still cost real work (the scan must skip) but they are not
    # comparable to a full page, so they are excluded from the ratio.
    timings, full = {}, {}
    for off in OFFSETS:
        sql = await _sql_at(perf_conn, fx, off)
        ms, rows = await _warm_ms(perf_conn, sql)
        timings[off] = ms
        assert rows in (0, PAGE_SIZE), (
            f"offset {off} returned {rows} rows — a page should be full or "
            f"empty, never partial-and-not-at-the-end")
        if rows == PAGE_SIZE:
            full[off] = ms

    if len(full) < 2:
        pytest.skip(f"{fx.label}: match set too small for a depth curve "
                    f"(full pages only at offsets {sorted(full)})")
    deepest = max(full)
    ratio = full[deepest] / full[0] if full.get(0) else 0.0
    perf_record(kind="sql", dataset=fx.space,
                metrics={f"page_ms_offset_{o}": round(timings[o], 1)
                         for o in OFFSETS} | {"deep_ratio": round(ratio, 1)},
                notes="cost across offsets — issues/078; flat means fixed")

    assert ratio < DEEP_RATIO_ALARM, (
        f"page at offset {deepest} is {ratio:.0f}x page 1 "
        f"({full[deepest]:.0f}ms vs {full[0]:.0f}ms) — the O(offset) "
        f"collapse in issues/078 has worsened. NOTE: this is extremely sensitive "
        f"to shared_buffers; check the server configuration before treating it "
        f"as a code regression (issues/081).")


@pytest.mark.bench("query.kgquery.deep_paging.monotonic")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_deeper_pages_are_never_cheaper(perf_conn, perf_record, fx):
    """Cost must not DROP with depth — that means the plan changed underneath.

    Worth pinning because it is what a partial fix looks like: `issues/080`
    measured a sorted page getting FASTER with depth (13.5s -> 5.6s -> 2.7s),
    which was the planner abandoning a nested loop it should never have chosen.
    A non-monotonic curve is a signal about the plan, not a win.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    ms, offs = [], []
    for off in OFFSETS:
        sql = await _sql_at(perf_conn, fx, off)
        t, rows = await _warm_ms(perf_conn, sql)
        if rows == PAGE_SIZE:            # full pages only, see above
            ms.append(t); offs.append(off)
    if len(ms) < 2:
        pytest.skip(f"{fx.label}: match set too small for a depth curve")

    OFFSETS_USED = offs
    for i in range(1, len(ms)):
        assert ms[i] >= ms[i - 1] * 0.5, (
            f"offset {OFFSETS_USED[i]} ({ms[i]:.0f}ms) is much cheaper than "
            f"offset {OFFSETS_USED[i-1]} ({ms[i-1]:.0f}ms) — the plan changed "
            f"with depth, "
            f"which is a plan-stability finding worth investigating, not a win")
