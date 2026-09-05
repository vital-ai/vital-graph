"""A FILTERING equality is a measured criterion; a structural constant is not.

`issues/160`. `criterion_rows` came only from `range_stats` (ops >,>=,<,<=),
`in_stats` and `text_stats`. An equality is none of those — it is a CONSTANT in
the BGP, priced by `rdf_stats` as a (predicate, object) pair and by
`absence_bounds` when the cap dropped it. So an equality-only query reported
"no measured criterion" and declined to the as-is fan-out, which is the entire
production Nurture shape.

THE FIRST ATTEMPT AT THIS REGRESSED AND WAS REVERTED, and the reason is the
point of this file. It fed EVERY chain constraint into the contest, including
constants under TYPE predicates — `hasKGSlotType`, `hasKGFrameType`,
`vitaltype` — which appear on every query of this shape and filter nothing. One
won at "2% selectivity" and drove a nested loop:

    campaign head        13.9 s  ->  TIMEOUT
    SFLeadId present      4 ms   ->  TIMEOUT     (a 1-in-1,150,000 equality)
    SFLeadId ABSENT     400 ms   ->  19 ms

Rarity was never the discriminator — the most selective shape in the set
regressed worst. WHICH constant drives the walk is.
"""

from __future__ import annotations

from vitalgraph.db.sparql_sql.generator import (
    _equality_criterion, _slot_value_predicate_uuids)
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid

HALEY = "http://vital.ai/ontology/haley-ai-kg#"

P_TEXT = _generate_term_uuid(f"{HALEY}hasTextSlotValue", "U")
P_URI = _generate_term_uuid(f"{HALEY}hasUriSlotValue", "U")
P_SLOT_TYPE = _generate_term_uuid(f"{HALEY}hasKGSlotType", "U")
P_FRAME_TYPE = _generate_term_uuid(f"{HALEY}hasKGFrameType", "U")
P_VITALTYPE = _generate_term_uuid(
    "http://vital.ai/ontology/vital-core#vitaltype", "U")

O_HEAD, O_ABSENT, O_TYPE = "o_head", "o_absent", "o_type"
PRED_STATS = {P_URI: 100_000, P_TEXT: 1_150_000,
              P_SLOT_TYPE: 3_044_865, P_FRAME_TYPE: 74_684,
              P_VITALTYPE: 3_044_860}


class _Chain:
    def __init__(self, head_c=None, tail_c=None):
        self.head_constraint, self.tail_constraint = head_c, tail_c


def test_a_stored_value_equality_is_a_measured_criterion():
    crit, pred = _equality_criterion(
        [_Chain(head_c=(P_URI, O_HEAD))], {(P_URI, O_HEAD): 78_871}, {},
        PRED_STATS, set(), None, None)
    assert (crit, pred) == (78_871, 100_000)


def test_an_absent_value_is_priced_from_its_predicate_bound():
    """Absence is an upper bound, not a mystery — `issues/153` supplies it."""
    crit, pred = _equality_criterion(
        [_Chain(head_c=(P_TEXT, O_ABSENT))], {}, {P_TEXT: 1},
        PRED_STATS, set(), None, None)
    assert (crit, pred) == (1, 1_150_000)


def test_a_STRUCTURAL_constant_is_refused():
    """The regression, as a test.

    `hasKGSlotType = <SFLeadId>` is on every query of this shape and selects
    nothing. Priced, it reports ~2% and wins the contest against a genuinely
    narrow value.
    """
    for p in (P_SLOT_TYPE, P_FRAME_TYPE, P_VITALTYPE):
        crit, pred = _equality_criterion(
            [_Chain(head_c=(p, O_TYPE))], {(p, O_TYPE): 74_684}, {},
            PRED_STATS, set(), None, None)
        assert (crit, pred) == (None, None), f"{p} was admitted as a criterion"


def test_a_structural_constant_cannot_displace_a_value_one():
    """Both on the same chain — exactly the production shape.

    The value equality admits 1 in 1,150,000; the slot-type constant ~2.5%. The
    first attempt let the structural one win here.
    """
    ch = _Chain(head_c=(P_TEXT, O_ABSENT), tail_c=(P_SLOT_TYPE, O_TYPE))
    crit, pred = _equality_criterion(
        [ch], {(P_SLOT_TYPE, O_TYPE): 74_684}, {P_TEXT: 1},
        PRED_STATS, set(), None, None)
    assert (crit, pred) == (1, 1_150_000), (
        "the structural constant displaced the value criterion — this is the "
        "reverted regression")


def test_the_narrower_of_an_equality_and_a_range_wins():
    crit, pred = _equality_criterion(
        [_Chain(head_c=(P_TEXT, O_ABSENT))], {}, {P_TEXT: 1},
        PRED_STATS, set(), 8_000, 100_000)
    assert (crit, pred) == (1, 1_150_000)


def test_a_wider_equality_does_not_displace_a_narrower_range():
    crit, pred = _equality_criterion(
        [_Chain(head_c=(P_URI, O_HEAD))], {(P_URI, O_HEAD): 78_871}, {},
        PRED_STATS, set(), 10, 1_150_000)
    assert (crit, pred) == (10, 1_150_000)


def test_a_saturated_pair_is_not_treated_as_a_measurement():
    """A capped count is a LOWER bound; using it OVERSTATES selectivity."""
    crit, pred = _equality_criterion(
        [_Chain(head_c=(P_URI, O_HEAD))], {(P_URI, O_HEAD): 10_000}, {},
        PRED_STATS, {(P_URI, O_HEAD)}, None, None)
    assert (crit, pred) == (None, None)


def test_every_slot_value_predicate_is_recognised():
    """23 value predicates, each keyed both as UUID and as str.

    Two producers key stats differently (`_load_quad_stats` uses UUID objects,
    `_load_missing_pair_stats` selects ::text), and a miss here reads as "not a
    criterion" — silently restoring the old decline.
    """
    u = _slot_value_predicate_uuids()
    assert P_TEXT in u and P_URI in u
    assert str(P_TEXT) in u and str(P_URI) in u
    assert P_SLOT_TYPE not in u and str(P_SLOT_TYPE) not in u
