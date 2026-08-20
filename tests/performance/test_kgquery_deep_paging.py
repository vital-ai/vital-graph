"""What a page costs at DEPTH — the dimension no benchmark varied.

FIXED 2026-08-12. The curve this file was written to record is now flat:

    offset      0      51 ms
    offset    250     277 ms      was    673 ms
    offset  1,000     291 ms      was  2,958 ms
    offset  5,000     310 ms      was 16,271 ms       52x

Two earlier attempts were fast and returned WRONG PAGES, because the deep page
ordered by entity uuid while page 1 ordered by URI text — two total orders, so
pages neither partitioned the result nor covered it. What made this land was
fixing the cause rather than the symptom (`issues/075`): the KGQuery builder
stopped emitting a default `ORDER BY ?entity` for callers who asked for no sort,
and the SQL layer now imposes a MARKED paging order instead. Every path answers
a marked order with uuid, so they agree; a real `ORDER BY` is answered as
written.

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

from .harness import explain_json
from .lead_fixtures import SYNTH, require_usable
from .test_kgquery_growth_curve import (
    KGENTITY, PAGE_SIZE, SIDECAR_URL, skip_no_pg,
)

FIXTURES = SYNTH

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

# Page 1 against page 41, now ~6x — and that ratio is page 1 being FAST (51 ms
# on an ordered scan that stops after 25 rows), not page 41 being slow.
#
# 20 sits above it with room for a noisy laptop, and far below the ~57x an
# O(offset) regression produces. This threshold has been wrong in both
# directions before: 400 was too loose to catch anything once flat, and 50 was
# set to gate a fix that turned out to return incorrect pages.
DEEP_RATIO_ALARM = 20

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
    # The fence travels WITH the SQL, because it is a property of the shape the
    # generator chose, not of the benchmark. See _warm_ms.
    return gen.sql, gen.needs_ordered_scan


async def _warm_ms(conn, sql, needs_ordered_scan=True):
    """Median of 3 warm runs, fencing ONLY when the generator asked for it.

    `SET LOCAL enable_sort = off` is not a benchmark setting, it is what the
    executor applies when `needs_ordered_scan` is set (`issues/047`) — a fence
    for the two-phase shape, whose O(page) property depends on the planner not
    falling back to a blocking sort.

    Applying it unconditionally measures a query the server would never run.
    The deep-page shape REQUIRES a sort: fenced, its `Unique` nodes have to take
    their order from indexes and the plan collapses into nested loops — 75,610 ms
    for a page that costs 277 ms unfenced. That number was nearly reported as a
    code regression.
    """
    async def once():
        async with conn.transaction():
            if needs_ordered_scan:
                await conn.execute("SET LOCAL enable_sort = off")
            t0 = time.perf_counter()
            rows = await conn.fetch(sql)
            return (time.perf_counter() - t0) * 1000.0, len(rows)

    await once()
    runs = [await once() for _ in range(3)]
    return sorted(t for t, _ in runs)[1], runs[-1][1]


@pytest.mark.bench("query.kgquery.deep_paging.curve")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
# SLOW BENCH. 20s+, nearly all of it building or scanning data rather than
# the plan being measured — the whole suite records only ~16s of
# execution_ms across 111 benches, so the cost here is setup, not signal.
# Excluded from `check.sh perf`; REQUIRED for a promotable baseline,
# because a partial run promotes holes (issues/081).
@pytest.mark.slow_bench
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
        sql, fence = await _sql_at(perf_conn, fx, off)
        ms, rows = await _warm_ms(perf_conn, sql, fence)
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
        sql, fence = await _sql_at(perf_conn, fx, off)
        t, rows = await _warm_ms(perf_conn, sql, fence)
        if rows == PAGE_SIZE:            # full pages only, see above
            ms.append(t); offs.append(off)
    if len(ms) < 2:
        pytest.skip(f"{fx.label}: match set too small for a depth curve")

    OFFSETS_USED = offs

    # The bench had a `perf_record` parameter and never called it, so it sat in
    # the baseline as `unrecorded` — passing forever without ever flagging a
    # regression. The assertion is a RATIO, so record that: `min_ratio` below 1
    # is the non-monotonic curve this exists to catch, and the deepest page's
    # plan carries the shared_buffers that thresholds.toml actually gates.
    ratios = [ms[i] / ms[i - 1] for i in range(1, len(ms)) if ms[i - 1] > 0]
    sql_deep, fence_deep = await _sql_at(perf_conn, fx, offs[-1])
    async with perf_conn.transaction():
        if fence_deep:
            await perf_conn.execute("SET LOCAL enable_sort = off")
        plan = await explain_json(perf_conn, sql_deep)
    perf_record(plan=plan, dataset=fx.space,
                metrics={"min_ratio": round(min(ratios), 3) if ratios else None,
                         "offsets_measured": len(offs),
                         "deepest_offset": offs[-1]},
                notes="cost must not drop with depth (issues/080)")

    for i in range(1, len(ms)):
        assert ms[i] >= ms[i - 1] * 0.5, (
            f"offset {OFFSETS_USED[i]} ({ms[i]:.0f}ms) is much cheaper than "
            f"offset {OFFSETS_USED[i-1]} ({ms[i-1]:.0f}ms) — the plan changed "
            f"with depth, "
            f"which is a plan-stability finding worth investigating, not a win")
