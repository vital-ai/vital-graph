"""What aggregates cost, and specifically what `MIN`/`MAX` cost extra.

`scaling_implementation_plan.md` carried this as the last unmeasured risk:

> **`MIN`/`MAX` sort-per-group (P1):** a known regression traded for correctness
> (`issues/029`), not an oversight. It is unmeasured — no suite has large enough
> groups — so it is sequenced as *measure, then decide*, not *optimise now*. The
> risk is that it is discovered in production rather than by the P1 gate ...
> Watch for `external merge` in `Sort Method`, which is where a constant factor
> becomes a cliff.

`MIN`/`MAX` cannot use PostgreSQL's aggregate: SPARQL §15.1 orders blank nodes
< IRIs < literals with numerics compared numerically, so `emit_group` builds
`(array_agg(col ORDER BY sparql_order_key))[1]` — a real sort per group.
Everything else (`COUNT`, `SUM`, `AVG`) aggregates without ordering.

MEASURED 2026-08-12 on `sp_lead_synth_100k`, 400,000 integer values:

    shape                     MIN     MAX     AVG     SUM   COUNT   MIN/AVG
    1 group x 400,000        736     733     374     375      33      2.0x
    4 groups x ~100,000    2,198   1,987   1,293   1,221     584      1.7x
    400,000 groups x 1     2,385      —    2,569       —   4,318      0.9x

**The answer is that it does not need fixing.** The overhead is a bounded ~2x,
it shrinks as groups get smaller (at one row per group there is nothing to sort
and `MIN` is no slower than `AVG`), and the cliff the plan warned about is not
there:

    work_mem   Sort Method        MIN
    64MB       quicksort          876 ms
    16MB       quicksort          877 ms
    4MB        external merge     897 ms      <- spills, and costs nothing
    1MB        external merge     800 ms

Spilling to disk is within noise of sorting in memory for this shape, so
`external merge` is not the cliff it was expected to be. That is the finding
worth keeping: the risk was real to worry about and is not real in practice.

WHAT THIS FILE GATES. Not the absolute timings, which move with the machine and
the buffer pool. It gates the RATIO of `MIN` to `AVG` over identical data —
that ratio is the sort-per-group cost, it is the thing `issues/029` traded for
correctness, and a regression in `sparql_order_key` or a lost index would show
up there while every absolute number stayed plausible.
"""

from __future__ import annotations

import time

import pytest

from .lead_fixtures import SYNTH, require_usable
from .test_kgquery_growth_curve import SIDECAR_URL, skip_no_pg

FIXTURES = SYNTH

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

KG = "http://vital.ai/ontology/haley-ai-kg#"
INT_VALUE = f"<{KG}hasIntegerSlotValue>"
DBL_VALUE = f"<{KG}hasDoubleSlotValue>"
SLOT_TYPE = f"<{KG}hasKGSlotType>"

# MIN/MAX pay a sort per group that COUNT/SUM/AVG do not. Measured at 1.7-2.0x
# on the shapes that can show it. 6 is far above that and far below the order of
# magnitude a genuine regression would produce — a lost `__num` companion, say,
# which would push the ordering onto text comparison for every row.
SORT_PER_GROUP_ALARM = 6.0


async def _agg_sql(conn, space, graph, agg, group_by=False, prop=INT_VALUE):
    """Compile and generate one aggregate query the same way the server does."""
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    if group_by:
        sparql = (f"SELECT ?t ({agg}(?v) AS ?a) WHERE {{ GRAPH <{graph}> {{ "
                  f"?s {SLOT_TYPE} ?t . ?s {prop} ?v }} }} GROUP BY ?t")
    else:
        sparql = (f"SELECT ({agg}(?v) AS ?a) WHERE {{ GRAPH <{graph}> {{ "
                  f"?s {prop} ?v }} }}")

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
        pytest.fail(f"{agg} failed to compile: {cr.error}")
    gen = await generate_sql(cr, space, conn=conn)
    if not gen.ok:
        pytest.fail(f"{agg} failed to generate SQL: {gen.error}")
    return gen.sql


async def _warm_ms(conn, sql):
    """Median of 3 warm runs. No fence: an aggregate REQUIRES its sort.

    `enable_sort = off` is the executor's fence for the two-phase paging shape
    (`issues/047`), and applying it here would measure a plan the server never
    chooses — the same trap that read 75,610 ms against 277 ms on a deep page.
    """
    async def once():
        t0 = time.perf_counter()
        rows = await conn.fetch(sql)
        return (time.perf_counter() - t0) * 1000.0, len(rows)

    await once()
    runs = [await once() for _ in range(3)]
    return sorted(t for t, _ in runs)[1], runs[-1][1]


@pytest.mark.bench("query.aggregate.sort_per_group")
@pytest.mark.parametrize("group_by", [False, True], ids=["one_group", "by_type"])
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_min_max_sort_per_group_stays_bounded(
        perf_conn, perf_record, fx, group_by):
    """`MIN` against `AVG` over identical data — the ratio IS the sort cost.

    Both shapes are measured because they stress it differently: one group of
    400,000 rows is the largest single sort, and four groups of ~100,000 is the
    shape where per-group work is repeated. The many-tiny-groups case is not
    gated — with one row per group there is nothing to sort, and `MIN` measured
    FASTER than `AVG` there, so a ratio assertion would be meaningless.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    timings = {}
    for agg in ("MIN", "MAX", "AVG", "SUM", "COUNT"):
        sql = await _agg_sql(perf_conn, fx.space, fx.graph, agg, group_by)
        ms, rows = await _warm_ms(perf_conn, sql)
        timings[agg] = ms
        if rows == 0:
            pytest.skip(f"{fx.label}: no numeric slot values to aggregate")

    ratio = timings["MIN"] / timings["AVG"] if timings["AVG"] else 0.0
    perf_record(kind="sql", dataset=fx.space,
                metrics={f"agg_{k.lower()}_ms": round(v, 1)
                         for k, v in timings.items()} | {"min_over_avg": round(ratio, 2)},
                notes=f"aggregate cost, group_by={group_by} — issues/029 "
                      f"sort-per-group")

    assert ratio < SORT_PER_GROUP_ALARM, (
        f"MIN is {ratio:.1f}x AVG over the same data "
        f"({timings['MIN']:.0f}ms vs {timings['AVG']:.0f}ms) — the sort per "
        f"group that issues/029 traded for SPARQL 15.1 ordering has got much "
        f"more expensive. Check that the `__num` companion is still being used "
        f"for the ordering key; without it every comparison falls back to text.")


@pytest.mark.bench("query.aggregate.spill")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_min_survives_spilling_to_disk(perf_conn, perf_record, fx):
    """The cliff the plan warned about: `external merge` instead of `quicksort`.

    Measured at the LARGEST work_mem that actually spills, found by stepping
    down — 4MB reaches it on 100k, 1MB on 10k. It costs nothing detectable
    (897 ms against 876 ms in memory), so the constant factor does NOT become a
    cliff, which is the specific thing the scaling plan flagged and could not
    evaluate.

    Gated loosely and on the RATIO to the in-memory run, because the point is
    "spilling is not catastrophic", not a particular millisecond count.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    sql = await _agg_sql(perf_conn, fx.space, fx.graph, "MIN")

    async def at_work_mem(setting):
        async with perf_conn.transaction():
            await perf_conn.execute(f"SET LOCAL work_mem = '{setting}'")
            await perf_conn.fetch(sql)
            t0 = time.perf_counter()
            await perf_conn.fetch(sql)
            ms = (time.perf_counter() - t0) * 1000.0
            plan = await perf_conn.fetch(
                "EXPLAIN (ANALYZE, FORMAT JSON) " + sql)
        import json
        methods = []

        def walk(n):
            if n.get("Sort Method"):
                methods.append(n["Sort Method"])
            for c in n.get("Plans", []):
                walk(c)
        walk(json.loads(plan[0][0])[0]["Plan"])
        return ms, methods

    mem_ms, mem_methods = await at_work_mem("64MB")

    # FIND the spill rather than assuming a setting reaches it. A fixed 4MB
    # spills on 100k and does NOT on 10k — measured, `quicksort` at 4MB and
    # `external merge` at 1MB — so the 10k case skipped with "too little data to
    # test the cliff", which was not true: the data was fine, the threshold was
    # too generous. A bench that cannot falsify its claim on half its fixtures is
    # a hole that reads as coverage.
    disk_ms = disk_methods = None
    for setting in ("4MB", "1MB", "256kB", "64kB"):
        ms, methods = await at_work_mem(setting)
        if any("external" in m for m in methods):
            disk_ms, disk_methods, spill_at = ms, methods, setting
            break
    if disk_ms is None:
        pytest.skip(f"{fx.label}: the sort did not spill even at 64kB "
                    f"(PostgreSQL's minimum work_mem), so this fixture genuinely "
                    f"cannot reach the cliff")

    perf_record(kind="sql", dataset=fx.space,
                metrics={"min_in_memory_ms": round(mem_ms, 1),
                         "min_spilled_ms": round(disk_ms, 1),
                         "spill_ratio": round(disk_ms / mem_ms, 2) if mem_ms else 0},
                notes=f"MIN with and without a work_mem spill at {spill_at} "
                      f"— issues/029")

    assert disk_ms < mem_ms * 10, (
        f"spilling to disk cost {disk_ms / mem_ms:.1f}x the in-memory sort "
        f"({disk_ms:.0f}ms vs {mem_ms:.0f}ms). The scaling plan flagged "
        f"`external merge` as where MIN/MAX's constant factor could become a "
        f"cliff; it was measured at ~1.0x, so this is a real change.")


# Datatype matters, because the sort key differs. Numeric terms compare through
# the `__num` companion; text compares lexicographically over longer values.
# Measured on 100k, one group:
#
#     type       rows        MIN     AVG     SUM   COUNT   MIN/AVG
#     Integer   400,000      825     365     371      31     2.26x
#     Double    437,000    1,273     417     413      58     3.05x
#     Currency  155,000      384     233     214      43     1.65x
#     Text    1,050,000    2,487     323*    153*     96        n/a
#
#     * AVG/SUM over text return UNBOUND, not a value — see the test below.
NUMERIC_PROPS = [("Integer", INT_VALUE), ("Double", DBL_VALUE),
                 ("Currency", f"<{KG}hasCurrencySlotValue>")]


@pytest.mark.bench("query.aggregate.by_datatype")
@pytest.mark.parametrize("type_name,prop", NUMERIC_PROPS,
                         ids=[n for n, _ in NUMERIC_PROPS])
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
async def test_sort_per_group_across_numeric_datatypes(
        perf_conn, perf_record, fx, type_name, prop):
    """The sort-per-group cost is not uniform across datatypes.

    Doubles cost most (3.05x against AVG, vs 2.26x for integers), which is the
    reason to measure each rather than generalise from one: they are the widest
    numeric terms here and the ordering key does the most work. Currency is
    cheapest at 1.65x, and it also has the fewest rows.

    All three stay far below the alarm, so this is coverage rather than a
    finding — but a change that pushed ordering onto text comparison would show
    up here first, on the widest type.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    timings = {}
    for agg in ("MIN", "AVG"):
        sql = await _agg_sql(perf_conn, fx.space, fx.graph, agg, prop=prop)
        ms, rows = await _warm_ms(perf_conn, sql)
        timings[agg] = ms
    ratio = timings["MIN"] / timings["AVG"] if timings["AVG"] else 0.0

    perf_record(kind="sql", dataset=fx.space,
                metrics={f"agg_{type_name.lower()}_min_ms": round(timings["MIN"], 1),
                         f"agg_{type_name.lower()}_avg_ms": round(timings["AVG"], 1),
                         f"agg_{type_name.lower()}_ratio": round(ratio, 2)},
                notes=f"MIN vs AVG on {type_name} — issues/029 sort-per-group")

    assert ratio < SORT_PER_GROUP_ALARM, (
        f"{type_name}: MIN is {ratio:.1f}x AVG "
        f"({timings['MIN']:.0f}ms vs {timings['AVG']:.0f}ms)")


@pytest.mark.parametrize("fx", FIXTURES[-1:], ids=[FIXTURES[-1].label])
async def test_avg_over_non_numeric_returns_unbound_and_does_not_crash(
        perf_conn, fx):
    """`AVG` over text must return UNBOUND, not abort the query.

    This is `issues/029`'s other half and the one with teeth: `AVG`/`SUM` used
    to raise `invalid input syntax for type numeric` and kill the WHOLE query,
    not just the aggregate. A regression would not be slow, it would be a
    500 on a query that touches one non-numeric value.

    Kept here rather than in a correctness suite because it is the same code
    path the timings above exercise, and because the fixture large enough to
    make the timings meaningful is the one that also has 1.05M text values.
    """
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    text_prop = f"<{KG}hasTextSlotValue>"
    for agg in ("AVG", "SUM"):
        sql = await _agg_sql(perf_conn, fx.space, fx.graph, agg, prop=text_prop)
        rows = await perf_conn.fetch(sql)          # must not raise
        assert rows, f"{agg} over text returned no row at all"
        value = list(rows[0].values())[0]
        assert value is None, (
            f"{agg} over non-numeric text returned {value!r}; SPARQL makes this "
            f"a type error, which in an aggregate means an unbound result")

    # MIN over text is well-defined (lexicographic) and must still work.
    sql = await _agg_sql(perf_conn, fx.space, fx.graph, "MIN", prop=text_prop)
    rows = await perf_conn.fetch(sql)
    assert rows and list(rows[0].values())[0] is not None, (
        "MIN over text should return the lexicographically smallest term")
