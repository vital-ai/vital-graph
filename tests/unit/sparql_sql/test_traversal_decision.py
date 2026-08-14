"""Choosing hop-wise evaluation must be safe before it is clever.

Measured on graph_synth_10k, identical answers, three start entities:

    criterion         depth   generated    hop-wise
    score >= 50           2    132.6 ms     0.9 ms    145x
    score >= 50           3    170.0 ms     1.8 ms     97x
    category IN (a,b)     3     88.4 ms     1.4 ms     65x
    occurred >= mid       3     62.8 ms     1.7 ms     37x
    category IN (a,b)     2      1.9 ms     0.7 ms      3x
    occurred >= mid       2      2.3 ms     0.9 ms      3x

What remains to assert are the two requirements with a MECHANISM behind them: a
pinned end, which makes the first hop's input small, and a measured criterion,
which keeps every later hop's input small. Without the second, an unfiltered
depth-3 walk on `wordnet_frames` measured 865 ms flat against 2,044 ms hop-wise
— hop-wise is a nested-loop strategy and fan-out is what defeats it. An earlier version of these tests asserted that a
`category IN` criterion must be DECLINED, on a measurement of 320.9 ms that came
from the benchmark filtering on `term_text` where the generated SQL resolves
term UUIDs. That is 0.7 ms once corrected. Tests written around a wrong number
lock the wrong behaviour in, which is why the numbers above are stated here.
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
        """The measured 97x case: depth 3, pinned head, criterion ~15%."""
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


class TestTheGate:
    """What is required, and what is only reported."""

    def test_a_barely_selective_criterion_is_still_chosen(self):
        """~56% of rows, and hop-wise measured 3x better at depth 2 and 65x at
        depth 3. This asserted the opposite when the benchmark was wrong."""
        d = decide(_chain(2), criterion_rows=38_368, predicate_rows=68_704)
        assert d.hop_wise is True
        assert "56%" in d.reason

    def test_an_unpinned_chain_declines(self):
        """No pinned end means no small driving set, so every hop would
        materialise the whole relation. Untested, and the one shape with an
        obvious mechanism for being worse."""
        d = decide(_chain(3, head=False, tail=False),
                   criterion_rows=10, predicate_rows=47_488)
        assert d.hop_wise is False
        assert "pinned" in d.reason

    def test_an_unfiltered_walk_declines(self):
        """The regression that put this gate back. `wordnet_frames`, depth 3,
        no criterion: 865 ms flat against 2,044 ms hop-wise, 3,108 results from
        a start of out-degree 671. Hop-wise is a nested-loop walk and it loses
        when the intermediate sets grow unchecked."""
        d = decide(_chain(3), criterion_rows=None, predicate_rows=47_488)
        assert d.hop_wise is False
        assert "no measured criterion" in d.reason

    def test_a_single_hop_is_CHOSEN(self):
        """This asserted the opposite, on the reasoning that one hop has nothing
        to sequence. Measured: a depth-1 walk with one criterion is 26.8 ms as
        generated and 0.2 ms hop-wise, because the planner drives from the
        criterion and probes the pinned entity LAST. The win comes from making
        the pin drive, which a single hop needs just as much."""
        d = decide(_chain(1), criterion_rows=10, predicate_rows=47_488)
        assert d.hop_wise is True

    def test_a_zero_predicate_total_does_not_divide(self):
        """Guards the division. A criterion count with nothing to divide by is
        not a selectivity, so it is treated as unmeasured rather than as a
        number — the conservative direction now that unmeasured declines."""
        d = decide(_chain(3), criterion_rows=5, predicate_rows=0)
        assert d.hop_wise is False

    def test_a_zero_length_chain_declines(self):
        assert decide(None).hop_wise is False
        assert decide(TraversalChain()).hop_wise is False


class TestSelectivityIsReportedNotRequired:
    """It was a gate, on a measurement that turned out to be a benchmark
    artefact. Kept visible because a choice should be diagnosable."""

    def test_both_selective_and_unselective_are_chosen(self):
        score = decide(_chain(3), 6_936, 47_488)       # ~15%
        category = decide(_chain(3), 38_368, 68_704)   # ~56%
        assert score.hop_wise and category.hop_wise

    def test_the_fraction_appears_in_the_reason(self):
        assert "15%" in decide(_chain(3), 6_936, 47_488).reason


class TestReporting:

    def test_the_reason_is_always_populated(self):
        for d in (decide(None),
                  decide(_chain(1), 1, 10),
                  decide(_chain(3, head=False), 1, 10),
                  decide(_chain(3), None, 10),
                  decide(_chain(3), 5, 0),
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
