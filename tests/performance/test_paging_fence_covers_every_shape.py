"""Every paging shape is either fenced or does not need fencing.

`issues/114`, and the defect `issues/111` actually was.

A KGQuery page is O(page) only while PostgreSQL drives it from an ordered scan
that stops at the LIMIT. Above a data-dependent row count it switches to a
blocking Sort. `execute_sparql_query` removes that alternative with
`SET LOCAL enable_sort = off`, but ONLY when the generator sets
`needs_ordered_scan`.

WHY A PROPERTY AND NOT A THRESHOLD. The page size at which a shape flips is a
cost-model crossover, not a property of this system — measured at 12, 19, 52 and
161-180 across datasets and dates. A bench that binary-searches for it measures
PostgreSQL's arithmetic against one data distribution and reports a different
number whenever the data moves.

WHAT THIS ASSERTS, AND THE VERSION OF IT THAT WAS WRONG. The first attempt
asserted that a plan containing a Sort must be fenced — "flag False and a Sort
present" as the bug. It fired on 24 shapes, and measuring them disproved it:

    shape       flag    unfenced   fenced     fencing would be
    eq-rare     False     35,409   435,228    12x WORSE
    range-mid   False     51,182   312,248     6x WORSE
    eq-common   True      54,561    54,561    identical

For those shapes the sort-based plan IS the right one and `False` is the correct
judgement. A Sort is not a defect; forcing `enable_sort = off` on a shape that
needs one is the 273x regression this repository already warns about.

So the checkable property is not "is there a Sort" but "does the flag AGREE with
which plan is actually cheaper":

    fenced materially cheaper   -> the flag must be True   (or the fence is lost)
    unfenced materially cheaper -> the flag must be False  (or we force a bad plan)

That is a yes/no question per shape, it needs no threshold, and it is what
`issues/111` violated: `needs_ordered_scan=False` while the unfenced plan sorted
100,000 candidates to return 1,017 rows.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_pg
from .lead_fixtures import SYNTH, require_usable
from .test_kgquery_growth_curve import (
    KGENTITY, SPECIFIC_ENTITY_TYPE, TEXT_SLOT, DOUBLE_SLOT, NS,
    _criteria_to_gen, _eq_criteria, _range_criteria, EQ_STATES,
)

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

FIXTURES = SYNTH

# The page sizes that matter: what callers actually ask for, and a larger page
# where the crossover is likelier. Not a search — two fixed points.
PAGE_SIZES = [25, 100]


# THE NEEDLE HAS TO BE BOTH MATCHABLE AND SERVABLE, and the original slot could
# not give both at once (issues/117).
#
# This probed `CompanyStateCode`, which holds two-letter codes — CA x9,220,
# TX x7,337, FL x6,528 — with the needle "CAL". Nothing matched, the LIMIT
# never filled, and both arms walked all 100,000 entities: 31.1M buffers,
# ~105 s, a comparison between two exhaustive scans that says nothing about
# fencing. ("California" is in the fixture on a DIFFERENT slot, which is what
# made the needle look plausible.)
#
# Simply matching is not enough either. On a two-letter slot every matching
# needle is at most two characters, and `MIN_TRIGRAM_NEEDLE = 3` — the index
# deliberately does not serve 1- and 2-grams — so "CA" measures the unservable
# path: 1,276,968 buffers against 138,369 for a servable needle that matches
# nothing.
#
# `CompanyName` gives both. Values average 21 characters ("AMF FREIGHT LLC",
# "Alternative Home Care LLC"), it hangs off `CompanyIdentityFrame` under the
# same `CompanyFrame` parent the address slot used, and "LLC" is three
# characters — servable — matching 41 distinct values.
TEXT_FRAME = "CompanyIdentityFrame"
TEXT_SLOT_TYPE = "CompanyName"
MATCHING_NEEDLE = "LLC"
# Deliberately absent AND servable, so the empty-result test below measures an
# empty result rather than an unservable needle. Kept distinct from
# MATCHING_NEEDLE so neither can be "fixed" into the other by accident.
ABSENT_NEEDLE = "ZZQQXX"


def _contains_criteria(needle: str):
    """A text criterion, which pushes down as a term semi-join."""
    from vitalgraph.model.kgentities_model import SlotCriteria, FrameCriteria
    return [FrameCriteria(
        frame_type=f"{NS}:frame:CompanyFrame",
        frame_criteria=[FrameCriteria(
            frame_type=f"{NS}:frame:{TEXT_FRAME}",
            slot_criteria=[SlotCriteria(
                slot_type=f"{NS}:slot:{TEXT_SLOT_TYPE}",
                slot_class_uri=TEXT_SLOT, value=needle,
                comparator="contains")])])]


# (id, criteria factory). Deliberately spans the selectivity gate: a tight range
# is where issues/111 was, a loose one is where the same shape behaves.
SHAPES = [
    ("eq-common", lambda: _eq_criteria(EQ_STATES[0])),
    ("eq-rare", lambda: _eq_criteria(EQ_STATES[-1])),
    ("range-tight", lambda: _range_criteria(99.9)),
    ("range-mid", lambda: _range_criteria(99)),
    ("range-loose", lambda: _range_criteria(65)),
    ("contains", lambda: _contains_criteria(MATCHING_NEEDLE)),
]
# The empty-result case is NOT in this matrix. It is exhaustive by
# construction — nothing matches, so the LIMIT never short-circuits and both
# arms run the walk to completion — which makes it a degenerate fence
# comparison and an expensive one: on the 100k fixture each side is ~105 s and
# 31M buffers, so four more cells would add roughly 17 minutes to warm plans
# that must then time out anyway. It gets one bounded test at the bottom of
# this file instead, on the small fixture, asserting the property that
# actually matters.


# How much cheaper one plan has to be before the flag is "wrong" rather than
# "arguable". Both sides are measured in the same run on the same data, so this
# is a ratio and carries no absolute count — a plan 2x cheaper is a decision
# worth making, and anything under that is inside the noise the planner is
# entitled to.
DECISIVE = 2.0

# Bad plans here can take minutes. The timeout IS a measurement: a side that
# cannot finish is not the cheaper side.
PROBE_TIMEOUT_MS = 20_000
# The warm-up may legitimately take longer than the probe it is preparing —
# it is the run that pays for the cache misses. Bounded so a genuinely
# pathological shape still gives up rather than hanging the suite.
WARM_TIMEOUT_MS = 120_000


async def _cost(conn, sql, *, fenced: bool, warm: bool = False):
    """Buffers for this plan, or None if it could not finish in time.

    `warm=True` discards the result: it exists to pull this plan's working set
    into the buffer pool before anything is timed.
    """
    from .harness import explain_json, total_shared_buffers
    try:
        async with conn.transaction():
            await conn.execute(
                f"SET LOCAL statement_timeout = "
                f"{WARM_TIMEOUT_MS if warm else PROBE_TIMEOUT_MS}")
            if fenced:
                await conn.execute("SET LOCAL enable_sort = off")
            return total_shared_buffers(await explain_json(conn, sql))
    except Exception:
        return None


async def _warm(conn, sql):
    """Run both plans once, untimed, so the timeout measures the PLAN.

    Without this the first probe pays to pull a 22 GB fixture's working set
    into a 16 GB pool, and the timeout reports the buffer pool instead. It is
    not a small effect: `range-tight/specific` measured 7.1x on a single cold
    probe and 1.3x warm, alternating, median of three — and it exceeded the
    20 s limit cold while finishing in about 5 s warm, so the shape was
    reported as "neither plan finished" and skipped entirely (issues/117).
    """
    for fenced in (False, True):
        await _cost(conn, sql, fenced=fenced, warm=True)


@pytest.mark.ingest_bench   # two ANALYZEd plans per shape; not an edit-loop bench
@pytest.mark.bench("query.kgquery.paging_fence_coverage")
@pytest.mark.parametrize("fx", FIXTURES, ids=[f.label for f in FIXTURES])
@pytest.mark.parametrize("entity_type", [
    pytest.param(KGENTITY, id="generic"),
    pytest.param(SPECIFIC_ENTITY_TYPE, id="specific"),
])
@pytest.mark.parametrize("shape_id,make", SHAPES, ids=[s[0] for s in SHAPES])
@pytest.mark.parametrize("page_size", PAGE_SIZES, ids=[f"p{n}" for n in PAGE_SIZES])
async def test_a_flippable_shape_is_always_fenced(
        perf_conn, fx, entity_type, shape_id, make, page_size):
    """`needs_ordered_scan` must be set for any shape whose plan would flip."""
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    gen = await _criteria_to_gen(perf_conn, make(), fx,
                                 entity_type=entity_type, page_size=page_size)
    if not gen.ok:
        # A refused generation is a different finding and has its own tests; it
        # is not an unfenced flip. Reported rather than silently passed.
        pytest.skip(f"generation refused, nothing to fence: {str(gen.error)[:120]}")

    flag = bool(getattr(gen, "needs_ordered_scan", False))
    await _warm(perf_conn, gen.sql)
    unfenced = await _cost(perf_conn, gen.sql, fenced=False)
    fenced = await _cost(perf_conn, gen.sql, fenced=True)

    if unfenced is None and fenced is None:
        pytest.skip("neither plan finished within the probe timeout")

    where = (f"[{fx.label}] {shape_id} / {entity_type.rsplit(':', 1)[-1]} / "
             f"page {page_size}")

    # A side that could not finish is not the cheaper side.
    if fenced is None:
        assert not flag, (
            f"{where}: `needs_ordered_scan` is set, but the FENCED plan did not "
            f"finish in {PROBE_TIMEOUT_MS}ms while the unfenced one took "
            f"{unfenced:,} buffers. The fence is being applied to a shape that "
            f"needs a sort — the 273x shape this repository warns about.")
        return
    if unfenced is None:
        assert flag, (
            f"{where}: the UNFENCED plan did not finish in {PROBE_TIMEOUT_MS}ms "
            f"and `needs_ordered_scan` is NOT set, so that is the plan served.")
        return

    if fenced * DECISIVE < unfenced:
        assert flag, (
            f"{where}: fencing is {unfenced / max(fenced, 1):.1f}x cheaper "
            f"({fenced:,} against {unfenced:,} buffers) and "
            f"`needs_ordered_scan` is NOT set, so the cheap plan is never "
            f"chosen. This is issues/111's shape: the flag disagreeing with "
            f"which plan is actually better. Fix it in `emit_slice`, not here.")
    elif unfenced * DECISIVE < fenced:
        assert not flag, (
            f"{where}: fencing is {fenced / max(unfenced, 1):.1f}x MORE "
            f"expensive ({fenced:,} against {unfenced:,} buffers) and "
            f"`needs_ordered_scan` IS set, so the executor forces the worse "
            f"plan. Forcing `enable_sort = off` on a shape that needs a sort is "
            f"the 273x regression this repository already documents.")


@pytest.mark.ingest_bench
@pytest.mark.asyncio(loop_scope="session")
async def test_the_three_text_needle_regimes_stay_ordered(perf_conn):
    """Match, empty, and unservable cost strictly more in that order.

    This started as "an empty result costs the whole walk" and that was assumed
    rather than measured. It is false: a SERVABLE needle matching nothing is
    answered from the index and is cheap. What costs is unservability.

    Three regimes, and the ordering between them is the property (issues/117,
    and `MIN_TRIGRAM_NEEDLE` from issues/070):

      servable + matches      cheapest — the LIMIT short-circuits
      servable + no match     more     — nothing to short-circuit on
      UNSERVABLE (< 3 chars)  most     — the index cannot help, so it scans

    Measured on the 10k fixture when written: 6,528 / 138,357 / 1,276,968
    buffers. The gates are the ORDER, not those numbers, which move with the
    fixture.

    The two-character needle is deliberate. `MIN_TRIGRAM_NEEDLE = 3` is a
    decision not to optimise 1- and 2-grams, and this pins its cost so the
    decision stays visible — the original version of this bench probed a
    two-letter slot, where every matching needle is unservable by construction,
    and measured that path while believing it measured fencing.
    """
    fx = [f for f in FIXTURES if f.label == "10k"][0]
    reason = await require_usable(perf_conn, fx)
    if reason:
        pytest.skip(reason)

    from .harness import explain_json, total_shared_buffers

    UNSERVABLE_NEEDLE = "CA"          # 2 chars: below MIN_TRIGRAM_NEEDLE
    regimes = (("matches", MATCHING_NEEDLE), ("empty", ABSENT_NEEDLE),
               ("unservable", UNSERVABLE_NEEDLE))
    cost, rows = {}, {}
    for label, needle in regimes:
        gen = await _criteria_to_gen(perf_conn, _contains_criteria(needle), fx,
                                     entity_type=KGENTITY, page_size=25)
        if not gen.ok:
            pytest.skip(f"generation refused for {label}: {str(gen.error)[:100]}")
        await _warm(perf_conn, gen.sql)
        doc = await explain_json(perf_conn, gen.sql)
        cost[label] = total_shared_buffers(doc)
        rows[label] = doc["Plan"].get("Actual Rows")

    assert rows["matches"] > 0, (
        f"{MATCHING_NEEDLE!r} matched nothing — the 'matches' regime is not "
        f"a match, so this test compares three empty walks")
    assert rows["empty"] == 0, (
        f"{ABSENT_NEEDLE!r} matched {rows['empty']} rows — it is not absent, "
        f"so the 'empty' regime is measuring nothing")

    assert cost["matches"] < cost["empty"], (
        f"a matching needle ({cost['matches']:,}) did not cost less than an "
        f"empty one ({cost['empty']:,}) — the LIMIT is not short-circuiting")
    assert cost["empty"] < cost["unservable"], (
        f"an empty SERVABLE needle ({cost['empty']:,}) cost as much as an "
        f"UNSERVABLE one ({cost['unservable']:,}) — the text index has stopped "
        f"answering the empty case, so it is scanning either way")
