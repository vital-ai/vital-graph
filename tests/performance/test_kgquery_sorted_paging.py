"""What an explicit sort costs — the path no benchmark has ever executed.

`issues/080`. Decision D1's uuid paging order applies only when NO sort is
requested, and `_emit_two_phase` declines the moment the order key is a sort
variable. So every performance test in this repo — the comparator sweep, the
growth curves, the paging benches, the plan assertions — measures the UNSORTED
path. `grep` finds no `sort_criteria` and no `ORDER BY` across
`tests/performance/`.

The UI's query builder offers sorting as a first-class control, so this is not
an exotic shape. Measured on `sp_lead_synth_100k`, 25-row page, warm:

    no sort                                46 ms
    sort by entity property (hasName)  18,579 ms      404x

WHERE THE TIME GOES, because the obvious answer is wrong. It is not that
ordering requires knowing the value. The plan is eight nested loops above the
match set, each estimated `rows=1` against 9,220 actual, resolving term text for
EVERY projected column of EVERY match — ~74,000 random lookups into a 10.4M-row
term table. The sort does not cost that, it EXPOSES it: unsorted, two-phase
pages 25 uuids and only 25 rows ever reach those joins.

    enable_nestloop=off + enable_material=off   17,589 -> 10,425 ms   only 1.7x
    resolving ONE column (the sort key) for the
      9,220-row match set, ORDER BY, LIMIT 25                33 ms

The fix is this codebase's own two-phase pattern extended to sorts: order on
(uuid, sort_key) alone, take the page, resolve the full projection for 25. Not
yet built — it changes the paging core.

AND IT IS SCALE-DEPENDENT, which is the other half of why it hid. Running this
bench across both fixtures:

    10k    unsorted     27 ms   sorted      69 ms      3x
    100k   unsorted     72 ms   sorted  14,618 ms    203x

At 10k a sort looks like a rounding error. The collapse only appears once the
match set is large enough for the per-match term resolution to dominate — so a
bench that runs only on the small fixture would report this healthy forever.
Both fixtures are parametrised here deliberately; the RATIO between them is the
signal, not either number alone.

THIS FILE IS THE GATE FOR THAT WORK. It records what the sorted path costs today
so the change can be shown to move it, and so the ratio cannot silently regress
again. The assertions are deliberately loose: they pin the SHAPE (a sort is
bounded, and is not catastrophically worse than the same query unsorted), not a
laptop timing.
"""

from __future__ import annotations

import time

import pytest

from .lead_fixtures import SYNTH, require_usable
from .test_kgquery_growth_curve import skip_no_pg
from .test_kgquery_growth_curve import (
    KGENTITY, PAGE_SIZE, SIDECAR_URL, _criteria_to_sql,
)

# The synthetic lead fixtures, same set the growth curves use.
FIXTURES = SYNTH

# Session loop scope, like the other perf modules: `perf_conn` is
# session-scoped and a per-function loop detaches it.
pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

NAME_PROP = "http://vital.ai/ontology/vital-core#hasName"

# A sorted page that costs more than this against its own unsorted twin is not a
# tuning difference, it is the O(matches) collapse this file exists to track.
# Set well above the 404x observed so it gates the pathology, not the noise.
SORT_RATIO_ALARM = 1000


async def _sorted_sql(conn, frame_criteria, fx, sorts):
    """`_criteria_to_sql`, but with sort_criteria attached."""
    from .test_kgquery_generated_sql_plans import _to_builder_frame
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria as BuilderEntityQueryCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    ec = BuilderEntityQueryCriteria(
        entity_type=KGENTITY, entity_uris=None,
        frame_criteria=[_to_builder_frame(f) for f in frame_criteria],
        sort_criteria=sorts, use_edge_pattern=True)
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        ec, fx.graph, PAGE_SIZE, 0)

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
        pytest.fail(f"sorted KGQuery failed to compile: {cr.error}\n\n{sparql}")
    gen = await generate_sql(cr, fx.space, conn=conn)
    if not gen.ok:
        pytest.fail(f"sorted KGQuery failed to generate: {gen.error}")
    return gen.sql


async def _warm_ms(conn, sql) -> float:
    """Median of 3 warm runs, honouring the executor's ordered-scan fence."""
    async def once():
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_sort = off")
            t0 = time.perf_counter()
            rows = await conn.fetch(sql)
            return (time.perf_counter() - t0) * 1000.0, len(rows)

    await once()                                  # warm the cache
    runs = [await once() for _ in range(3)]
    return sorted(t for t, _ in runs)[1], runs[-1][1]


def _eq_criteria():
    """One equality criterion — the cheapest shape, so the sort dominates."""
    from scripts.perf_shape_matrix import build_criteria
    return build_criteria(comparator="eq",
                          slot_class="http://vital.ai/ontology/haley-ai-kg#KGTextSlot")


@pytest.mark.bench("query.kgquery.sorted_paging.entity_property")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_entity_property_sort_against_its_unsorted_twin(
        perf_conn, perf_record, fx):
    """The same query, sorted and unsorted. The RATIO is the measurement.

    Absolute timings move with the machine; the ratio is the thing that
    describes the plan, and it is what a fix has to move.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    from vitalgraph.sparql.kg_query_builder import SortCriteria

    criteria = _eq_criteria()
    unsorted_sql = await _criteria_to_sql(perf_conn, criteria, fx)
    sorted_sql = await _sorted_sql(
        perf_conn, criteria, fx,
        [SortCriteria(sort_type="entity_property", property_uri=NAME_PROP)])

    unsorted_ms, unsorted_rows = await _warm_ms(perf_conn, unsorted_sql)
    sorted_ms, sorted_rows = await _warm_ms(perf_conn, sorted_sql)
    ratio = sorted_ms / unsorted_ms if unsorted_ms else 0.0

    perf_record(kind="sql", dataset=fx.space,
                metrics={"unsorted_ms": round(unsorted_ms, 1),
                         "sorted_ms": round(sorted_ms, 1),
                         "sort_ratio": round(ratio, 1)},
                notes="entity_property sort vs the same query unsorted "
                      "(issues/080)")

    print(f"\n  [{fx.label}] unsorted={unsorted_ms:,.0f}ms  "
          f"sorted={sorted_ms:,.0f}ms  ratio={ratio:.0f}x")

    assert sorted_rows == unsorted_rows == PAGE_SIZE, (
        f"a sort must not change how many rows a page returns: "
        f"{sorted_rows} sorted vs {unsorted_rows} unsorted")
    assert ratio < SORT_RATIO_ALARM, (
        f"sorted page is {ratio:.0f}x its unsorted twin ({sorted_ms:.0f}ms vs "
        f"{unsorted_ms:.0f}ms) — the O(matches) collapse in issues/080 has got "
        f"worse, not better")


@pytest.mark.bench("query.kgquery.sorted_paging.page_shape")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_a_sorted_page_is_actually_ordered(perf_conn, perf_record, fx):
    """Correctness alongside cost: whatever it costs, it must be sorted.

    Worth pinning here because the fix changes WHERE the ordering is applied —
    from above the full projection to inside a narrow phase 1 — and an ordering
    bug there would look like a performance win.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    from vitalgraph.sparql.kg_query_builder import SortCriteria

    sql = await _sorted_sql(
        perf_conn, _eq_criteria(), fx,
        [SortCriteria(sort_type="entity_property", property_uri=NAME_PROP)])
    async with perf_conn.transaction():
        await perf_conn.execute("SET LOCAL enable_sort = off")
        rows = await perf_conn.fetch(sql)

    names = [r[k] for r in rows for k in r.keys()
             if k.endswith("v8") or k == "name"]
    if not names:
        pytest.skip("could not identify the sort column in the projection")
    ordered = [n for n in names if n is not None]
    assert ordered == sorted(ordered), "the sorted page came back out of order"
