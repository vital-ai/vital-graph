"""Choosing hop-wise evaluation must be safe before it is clever.

Measured on graph_synth_10k, identical answers, three start entities:

    criterion         depth   generated    hop-wise
    score >= 50           3    187.7 ms     1.0 ms     188x better
    occurred >= mid       3     75.1 ms     2.4 ms      31x better
    category IN (a,b)     2      1.6 ms   320.9 ms     200x WORSE

Applied whenever a chain is found, this optimisation makes the third row 200x
slower. So these tests are mostly about what it must DECLINE.

The category case is not understood — not the criterion's formulation (a join to
`term` and an `IN` subquery are within 3% of each other) and not the result size
(11 rows, 254 ms). Until it is, the gate stays narrow enough to exclude it, and
these tests pin that narrowness so a later widening is a deliberate act rather
than a drift.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.traversal_chain import ChainLink, TraversalChain
from vitalgraph.db.sparql_sql.traversal_decision import (
    decide, decide_for_plan, SELECTIVE_FRACTION, MIN_DEPTH)

pytestmark = pytest.mark.unit


def _chain(depth=3, head=True, tail=False, kind="frame_entity"):
    return TraversalChain(
        links=[ChainLink(ref_id=f"femv{i}", kind=kind,
                         source_col="source_entity_uuid",
                         dest_col="dest_entity_uuid") for i in range(depth)],
        pinned_head=head, pinned_tail=tail)


class TestWhenItChoosesHopWise:

    def test_deep_pinned_and_selective(self):
        """The measured 188x case: depth 3, pinned head, criterion ~15%."""
        d = decide(_chain(3), criterion_rows=6_936, predicate_rows=47_488)
        assert d.hop_wise is True
        assert "depth 3" in d.reason and "15%" in d.reason

    def test_a_tail_pin_is_as_good_as_a_head_pin(self):
        """Either end gives a small driving set; the chain is walked from
        whichever is fixed."""
        d = decide(_chain(3, head=False, tail=True),
                   criterion_rows=100, predicate_rows=47_488)
        assert d.hop_wise is True

    def test_it_applies_to_relation_chains_too(self):
        """Both traversal shapes or it fixes half the product."""
        d = decide(_chain(3, kind="edge"), criterion_rows=100,
                   predicate_rows=47_488)
        assert d.hop_wise is True


class TestWhatItMustDecline:
    """Each of these is a measured or reasoned way to make a query slower."""

    def test_the_category_case_is_excluded(self):
        """~56% of rows. Choosing hop-wise here measured 200x SLOWER at depth 2
        and 8x slower at depth 3."""
        d = decide(_chain(2), criterion_rows=38_368, predicate_rows=68_704)
        assert d.hop_wise is False
        assert "above the" in d.reason

    def test_an_unpinned_chain_declines(self):
        """No pinned end means no small driving set, so every hop materialises
        the whole relation — the shape that lost 200x."""
        d = decide(_chain(3, head=False, tail=False),
                   criterion_rows=10, predicate_rows=47_488)
        assert d.hop_wise is False
        assert "pinned" in d.reason

    def test_a_single_hop_declines(self):
        """Nothing to sequence, and depth 1 is sub-millisecond either way."""
        d = decide(_chain(1), criterion_rows=10, predicate_rows=47_488)
        assert d.hop_wise is False
        assert str(MIN_DEPTH) in d.reason

    def test_an_unknown_estimate_declines(self):
        """`estimate_range` returns None for "unknown", never zero. Reading
        unknown as selective would pick the 200x-worse shape on exactly the
        queries nothing is known about."""
        d = decide(_chain(3), criterion_rows=None, predicate_rows=47_488)
        assert d.hop_wise is False
        assert "unknown" in d.reason

    def test_a_zero_predicate_total_declines(self):
        """Guards the division as well as the logic."""
        d = decide(_chain(3), criterion_rows=5, predicate_rows=0)
        assert d.hop_wise is False

    def test_no_chain_declines(self):
        assert decide(None).hop_wise is False
        assert decide(TraversalChain()).hop_wise is False


class TestTheThreshold:

    def test_just_inside_is_chosen(self):
        d = decide(_chain(3), criterion_rows=int(1000 * SELECTIVE_FRACTION) - 1,
                   predicate_rows=1000)
        assert d.hop_wise is True

    def test_just_outside_declines(self):
        d = decide(_chain(3), criterion_rows=int(1000 * SELECTIVE_FRACTION) + 1,
                   predicate_rows=1000)
        assert d.hop_wise is False

    def test_the_threshold_separates_the_measured_cases(self):
        """The only separation the evidence supports: score at ~15% is chosen,
        category at ~56% is not. Change SELECTIVE_FRACTION and this says whether
        the change still respects the measurements."""
        score = decide(_chain(3), 6_936, 47_488)
        category = decide(_chain(3), 38_368, 68_704)
        assert score.hop_wise and not category.hop_wise


class TestReporting:

    def test_the_reason_is_always_populated(self):
        for d in (decide(None),
                  decide(_chain(1), 1, 10),
                  decide(_chain(3, head=False), 1, 10),
                  decide(_chain(3), None, 10),
                  decide(_chain(3), 1, 10)):
            assert d.reason, "a decision with no reason cannot be diagnosed"

    def test_it_picks_the_deepest_chain(self):
        """Cost compounds per hop, so a plan holding a 3-hop chain beside a
        1-hop one is dominated by the former."""
        chains = [_chain(3), _chain(1)]
        d = decide_for_plan(chains, criterion_rows=10, predicate_rows=47_488)
        assert d.hop_wise is True
        assert d.chain.depth == 3

    def test_no_chains_is_not_an_error(self):
        assert decide_for_plan([]).hop_wise is False
