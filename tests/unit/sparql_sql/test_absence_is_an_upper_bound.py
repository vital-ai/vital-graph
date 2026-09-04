"""An end missing from rdf_stats is SMALL, and the planner must drive from it.

`issues/153`. `recompute_stats_tables` keeps each predicate's LARGEST pairs, so
a pair that is not stored is smaller than every pair that is. That makes absence
an upper bound rather than a mystery — and acting on it is what makes the
descending order deliver the thing the table exists for.

WHY THIS IS THE COMMON SHAPE, not a corner. A query constrains one end to a rare
value (a lead id, a campaign id) and the other to a common one (a type). The
rare end is exactly the pair the cap drops. Before this, that end priced as None
and `choose_direction` drove from the only end it could price — the huge one.
`issues/090` measured 9.2x for driving from the smaller end.

The bound is sound to compare directly. If bound < other, the true size is also
< other and the choice is right. If bound >= other the comparison is
inconclusive and the other end wins, which is the conservative outcome.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sync_stats_tables import (
    STATS_MIN_ROW_COUNT, absence_bounds)
from vitalgraph.db.sparql_sql.traversal_decision import (
    _end_sizes, choose_direction)


class _Chain:
    """Just the fields `_end_sizes` reads."""

    def __init__(self, head_c=None, tail_c=None, pinned_head=False,
                 pinned_tail=False, depth=3):
        self.head_constraint, self.tail_constraint = head_c, tail_c
        self.pinned_head, self.pinned_tail = pinned_head, pinned_tail
        self.depth = depth


# P_BIG was CUT: it holds more pairs than any other predicate, so its stored
# rows are its biggest and the smallest of them (50) bounds anything absent.
# P_SMALL was NOT cut: everything it has is stored, so an absent pair is a
# singleton.
STORED = {("P_BIG", "a"): 500_000, ("P_BIG", "b"): 900, ("P_BIG", "c"): 50,
          ("P_SMALL", "x"): 9}


class TestAbsenceBounds:

    def test_a_cut_predicate_is_bounded_by_its_smallest_stored_pair(self):
        assert absence_bounds(STORED)["P_BIG"] == 50

    def test_an_uncut_predicate_means_the_pair_is_a_singleton(self):
        assert absence_bounds(STORED)["P_SMALL"] == STATS_MIN_ROW_COUNT - 1 == 1

    def test_a_predicate_with_nothing_stored_gets_no_bound(self):
        """Saying nothing is the point: absence of the PREDICATE is not
        absence of a pair, and inventing a bound there would be a guess."""
        assert "P_OTHER" not in absence_bounds(STORED)

    def test_no_stats_at_all_yields_no_bounds(self):
        assert absence_bounds({}) == {} and absence_bounds(None) == {}


class TestTheRareEndWins:

    def test_an_absent_end_is_priced_and_beats_a_huge_priced_end(self):
        """The shape that started this: rare end absent, common end enormous."""
        bounds = absence_bounds(STORED)
        chain = _Chain(head_c=("P_SMALL", "missing"), tail_c=("P_BIG", "a"))

        head, tail = _end_sizes(chain, STORED, bounds)
        assert (head, tail) == (1, 500_000), (head, tail)
        assert choose_direction(chain, STORED, bounds) == "head"

    def test_without_the_bound_it_drives_from_the_huge_end(self):
        """Pins WHY the bound is needed, by showing the behaviour without it.

        Not a hypothetical: this is what shipped once the recompute started
        keeping each predicate's largest pairs, and it is the reason the
        descending order alone was not enough.
        """
        chain = _Chain(head_c=("P_SMALL", "missing"), tail_c=("P_BIG", "a"))
        assert _end_sizes(chain, STORED, None) == (None, 500_000)
        assert choose_direction(chain, STORED, None) == "tail"

    def test_a_stored_pair_still_uses_its_exact_count(self):
        """The bound is a fallback, never an override."""
        chain = _Chain(head_c=("P_BIG", "b"), tail_c=("P_BIG", "a"))
        assert _end_sizes(chain, STORED, absence_bounds(STORED)) == (900, 500_000)

    def test_a_pinned_end_still_wins_over_a_bounded_one(self):
        """Pinned is 1 by definition and exact; a bound of 1 is not better."""
        bounds = absence_bounds(STORED)
        chain = _Chain(pinned_head=True, tail_c=("P_BIG", "missing"))
        assert _end_sizes(chain, STORED, bounds) == (1, 50)
        assert choose_direction(chain, STORED, bounds) == "head"

    def test_an_inconclusive_bound_does_not_flip_the_choice(self):
        """bound >= other must NOT be read as "smaller".

        P_BIG's absent pairs are only bounded by 50, so against a priced end of
        9 the comparison says nothing and the priced end wins. Treating a loose
        upper bound as a measurement is how a bound becomes a guess.
        """
        bounds = absence_bounds(STORED)
        chain = _Chain(head_c=("P_BIG", "missing"), tail_c=("P_SMALL", "x"))
        assert _end_sizes(chain, STORED, bounds) == (50, 9)
        assert choose_direction(chain, STORED, bounds) == "tail"

    def test_an_open_end_is_still_unknown(self):
        """A bound applies to a CONSTRAINED end. An open end has no pair at
        all, so there is nothing to bound and it must stay None."""
        bounds = absence_bounds(STORED)
        assert _end_sizes(_Chain(tail_c=("P_BIG", "a")), STORED, bounds) \
            == (None, 500_000)


class TestAPredicateWithNoStoredPairAtAll:
    """The case that matters most, and the one the first version missed.

    A high-cardinality id predicate — one object per subject — has NO pair
    reaching STATS_MIN_ROW_COUNT, so it is absent from rdf_stats entirely rather
    than merely missing one pair. Measured on `sp_lead_synth_10k`: the widest
    predicate has none of its own pairs stored.

    That is exactly what a query constrains when it looks up one lead or one
    campaign, so reading it as "no information" leaves the end the query most
    wants to drive from unpriced — which is the whole defect. `pred_stats` holds
    every predicate, so it supplies these.
    """

    PRED_STATS = {"P_BIG": 900_000, "P_SMALL": 40, "P_IDS": 500_000}

    def test_a_predicate_absent_from_rdf_stats_is_bounded_at_one(self):
        b = absence_bounds(STORED, self.PRED_STATS)
        assert b["P_IDS"] == STATS_MIN_ROW_COUNT - 1 == 1, (
            "a predicate with no stored pair holds only singletons — fairness "
            "seats rank 1 of every predicate, so absence here is not starvation")

    def test_it_beats_a_huge_priced_end(self):
        b = absence_bounds(STORED, self.PRED_STATS)
        chain = _Chain(head_c=("P_IDS", "one-specific-id"), tail_c=("P_BIG", "a"))
        assert _end_sizes(chain, STORED, b) == (1, 500_000)
        assert choose_direction(chain, STORED, b) == "head"

    def test_without_pred_stats_the_predicate_stays_unpriced(self):
        """Pins why pred_stats is passed — this is the regression it fixes."""
        chain = _Chain(head_c=("P_IDS", "one-specific-id"), tail_c=("P_BIG", "a"))
        assert _end_sizes(chain, STORED, absence_bounds(STORED)) \
            == (None, 500_000)

    def test_a_depth_one_cut_infers_nothing(self):
        """If the cap ran out while seating rank 1, absence CAN hide anything.

        Fairness only guarantees every predicate a row when the budget reaches
        depth 2. At depth 1 a predicate with a huge pair may have been starved,
        so no bound is sound and none is given.
        """
        shallow = {("P_BIG", "a"): 500_000, ("P_SMALL", "x"): 9}
        assert "P_IDS" not in absence_bounds(shallow, self.PRED_STATS)


class TestTheCutBoundaryIsDMinusOne:
    """A predicate holding D-1 pairs may still have been cut.

    `ORDER BY rn ASC LIMIT n` is bounded by a ROW COUNT, not a rank, so it
    truncates partway through rank D: of the predicates that had a rank-D pair,
    some got it and some did not. The latter hold D-1 rows AND have pairs that
    were dropped.

    Testing `n >= D` called those "not cut" and gave them a bound of 1 while
    their absent pairs held 2. Measured on `sp_graph_forms_20k`: 15,096 absent
    pairs exceeded the bound they were given. A bound that is too SMALL is the
    one direction that must never happen — it tells the planner an end is tiny
    when it is not, which is how the wrong end gets driven.

    The unit fixtures above pass under BOTH rules, which is why this needed a
    loaded space to surface and why it gets its own case here.
    """

    # P_DEEP got 3 pairs, P_EDGE got 2. D = 3, so P_EDGE sits at D-1 and may
    # have lost its rank-3 pair to the truncation.
    STORED = {("P_DEEP", "a"): 900, ("P_DEEP", "b"): 800, ("P_DEEP", "c"): 700,
              ("P_EDGE", "x"): 500, ("P_EDGE", "y"): 400,
              ("P_SHALLOW", "z"): 300}

    def test_a_predicate_at_d_minus_one_is_treated_as_cut(self):
        b = absence_bounds(self.STORED)
        assert b["P_EDGE"] == 400, (
            "a predicate holding D-1 pairs was called fully covered and bounded "
            "at 1; the LIMIT truncates mid-rank, so it may have lost its rank-D "
            "pair and anything absent could be as large as its smallest stored")

    def test_a_predicate_well_below_the_depth_is_still_fully_covered(self):
        """The inference has to keep working, or every bound collapses to
        `min stored` and the useful case (absence means 1) is lost.

        Fairness seats rank k for every predicate before rank k+1 for any, so a
        predicate with fewer than D-1 rows ran out of PAIRS, not of budget.
        """
        b = absence_bounds(self.STORED)
        assert b["P_SHALLOW"] == STATS_MIN_ROW_COUNT - 1 == 1

    def test_the_bound_is_never_smaller_than_a_real_absent_pair(self):
        """The property the loaded-space validator checks, in miniature.

        P_EDGE's dropped rank-3 pair is <= 400 by construction (DESC keeps the
        biggest), so a bound of 400 holds and a bound of 1 does not.
        """
        b = absence_bounds(self.STORED)
        dropped_rank_3 = 350          # <= min(stored for P_EDGE), by ordering
        assert dropped_rank_3 <= b["P_EDGE"], (
            f"bound {b['P_EDGE']} is smaller than a pair that really was cut")

