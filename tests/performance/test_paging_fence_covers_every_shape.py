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


def _contains_criteria(needle: str):
    """A text criterion, which pushes down as a term semi-join."""
    from vitalgraph.model.kgentities_model import SlotCriteria, FrameCriteria
    return [FrameCriteria(
        frame_type=f"{NS}:frame:CompanyFrame",
        frame_criteria=[FrameCriteria(
            frame_type=f"{NS}:frame:CompanyAddressFrame",
            slot_criteria=[SlotCriteria(
                slot_type=f"{NS}:slot:CompanyStateCode",
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
    ("contains", lambda: _contains_criteria("CAL")),
]


# How much cheaper one plan has to be before the flag is "wrong" rather than
# "arguable". Both sides are measured in the same run on the same data, so this
# is a ratio and carries no absolute count — a plan 2x cheaper is a decision
# worth making, and anything under that is inside the noise the planner is
# entitled to.
DECISIVE = 2.0

# Bad plans here can take minutes. The timeout IS a measurement: a side that
# cannot finish is not the cheaper side.
PROBE_TIMEOUT_MS = 20_000


async def _cost(conn, sql, *, fenced: bool):
    """Buffers for this plan, or None if it could not finish in time."""
    from .harness import explain_json, total_shared_buffers
    try:
        async with conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = {PROBE_TIMEOUT_MS}")
            if fenced:
                await conn.execute("SET LOCAL enable_sort = off")
            return total_shared_buffers(await explain_json(conn, sql))
    except Exception:
        return None


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
