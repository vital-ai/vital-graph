"""Decide whether a traversal chain should be evaluated hop by hop.

Step 2 of `planning_performance/traversal_chain_plan.md`. `traversal_chain`
finds the chain; this says what to do about it. Still INERT — it returns a
decision and a reason, and nothing emits differently yet.

WHAT THE CHOICE IS WORTH, on graph_synth_10k after the equality push-down,
three start entities, identical answers throughout:

    criterion         depth   generated    hop-wise
    score >= 50           1     26.8 ms     0.2 ms    134x
    score >= 50           2    132.6 ms     0.9 ms    145x
    score >= 50           3    170.0 ms     1.8 ms     97x
    category IN (a,b)     3     88.4 ms     1.4 ms     65x
    occurred >= mid       3     62.8 ms     1.7 ms     37x
    category IN (a,b)     2      1.9 ms     0.7 ms      3x
    occurred >= mid       2      2.3 ms     0.9 ms      3x

Hop-wise is better in every case measured, and by more as depth grows.

A CORRECTION, because the first version of this file said otherwise. It recorded
`category IN` at depth 2 as 200x WORSE hop-wise and built a narrow selectivity
gate to exclude it. That measurement was wrong, and wrong because of the
BENCHMARK rather than the shape: the hand-written comparison filtered on
`term_text IN ('alpha','beta')` while the generated SQL resolves those values to
term UUIDs. Filtering by text makes the planner enumerate the value side —
38,368 quads scanned to answer a question about 11 — which is the exact failure
`_in_as_constants` documents at 11,679 ms against 37 ms. With the constants
resolved, the same query is 0.2 ms.

So selectivity is NOT a gate here. It stays in the reason string because it is
worth seeing, and because ranking two chains may want it later, but nothing is
declined for being insufficiently selective.

THE CRITERION REQUIREMENT IS UNDER REVIEW — 2026-08-14

It was added because an unfiltered depth-3 walk on `wordnet_frames` measured
865 ms flat against 2,044 ms hop-wise. Re-measured with INTERLEAVED runs
(alternating plans, 7-9 repetitions, medians rather than min-of-2), that
reverses: 3,158 ms flat against 2,129 ms hop-wise, and the same reversal appears
on `graph_synth_100k` (2,452 against 1,918). The flat plan's median on the
wordnet query ranged 822 ms to 3,158 ms across one session with that space
untouched, while hop-wise held 1,989-2,129 ms with a quarter of the variance.

So the evidence for this gate is currently contradicted, and the gate is
DECLINING queries hop-wise would win. It stays until the comparison has been
repeated on a quiet machine across sessions — this area has produced four
measurements that reversed on closer inspection, and removing a safety gate on
the fifth would be the same mistake. See
`planning_performance/stats_table_freshness_plan.md`.

WHAT IS STILL REQUIRED

A pinned end, and a MEASURED criterion.

Without a pinned end there is no small driving set and each hop would
materialise the whole relation. Without a criterion the walk fans out unchecked,
and that is not a hypothetical: an unfiltered depth-3 walk on `wordnet_frames`
measured 865 ms flat against 2,044 ms hop-wise. Hop-wise is a nested-loop
strategy and it loses when the intermediate sets grow.

The criterion must be MEASURED, not selective. Those are different gates, and
the difference is the whole correction above.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .traversal_chain import TraversalChain

logger = logging.getLogger(__name__)

# Kept for reporting and for whatever ranking comes later. NOT a gate: see the
# correction in the module docstring for why a threshold here was wrong.
SELECTIVE_FRACTION = 0.25

# Depth 1 QUALIFIES. The reasoning that excluded it — "one hop is already the
# plan a sane optimiser picks" — was wrong, and measurably so: a depth-1 walk
# with one criterion is 26.8 ms as generated and 0.2 ms hop-wise, because the
# planner drives from the criterion (50 terms -> 6,847 quads -> 4,660 frames)
# and applies the PINNED ENTITY last, as a probe. The win is not from sequencing
# several hops; it is from making the pinned constant drive, which a single hop
# needs just as much.
MIN_DEPTH = 1


@dataclass
class Decision:
    """What to do, and why — the reason is the point.

    Every wrong turn here has been a pass that silently declined. A decision
    that records why it went the way it did can be checked against a query
    someone is complaining about, which a bare boolean cannot.
    """
    hop_wise: bool
    reason: str
    chain: Optional[TraversalChain] = None

    def __repr__(self):
        return f"Decision({'hop-wise' if self.hop_wise else 'as-is'}: {self.reason})"


def decide(chain: Optional[TraversalChain],
           criterion_rows: Optional[int] = None,
           predicate_rows: Optional[int] = None) -> Decision:
    """Choose an evaluation shape for one chain.

    `criterion_rows` / `predicate_rows` come from the value histograms
    (`sync_value_stats.estimate_range` and `rdf_pred_stats`): how many rows the
    per-hop criterion admits, out of how many the predicate has.

    Both are optional and neither gates the decision — they are reported so a
    choice can be diagnosed. See the module docstring for why a selectivity
    threshold here was wrong.
    """
    if chain is None or chain.depth == 0:
        return Decision(False, "no chain")

    if chain.depth < MIN_DEPTH:
        return Decision(False, f"depth {chain.depth} < {MIN_DEPTH}", chain)

    # Without a pinned end there is no small driving set, so every hop would
    # materialise the whole relation. Untested, and the one shape with an
    # obvious mechanism for being worse — so it declines.
    if not (chain.pinned_head or chain.pinned_tail):
        return Decision(False, "neither end pinned, no driving set", chain)

    # A MEASURED criterion is required. Not a selective one — see below.
    #
    # This reverses the previous behaviour, on a measurement rather than an
    # argument. Emitting hop-wise for every pinned chain regressed the one
    # unfiltered deep walk in the corpus: `wordnet_frames`, depth 3, no
    # criterion, 865 ms flat against 2,044 ms hop-wise. Hop-wise is a
    # nested-loop strategy; it pays when each hop's input stays small and loses
    # when the walk fans out unchecked, and 3,108 results through a start entity
    # of out-degree 671 is the losing shape.
    #
    # Measured across both fixtures, the split is exact:
    #
    #     criterion measured    1.8x - 234x faster, 6 of 6 cases
    #     no criterion          1.0x parity on 4 synthetic cases, and the
    #                           single 2.4x REGRESSION above
    #
    # The earlier "unknown does not decline" rule was justified by two of three
    # criterion families being unmeasurable (`issues/090`). Ranges, IN, equality
    # and booleans have since been wired in, so "unknown" now much more often
    # means "there is no criterion" — which is exactly the losing shape.
    if criterion_rows is None or not predicate_rows:
        return Decision(False, f"depth {chain.depth}, pinned but no measured "
                               f"criterion — an unfiltered walk fans out", chain)

    # Selectivity is REPORTED, not thresholded. A gate on HOW selective was
    # tried and was wrong (see the correction above); `category IN` admits 56%
    # of its predicate and still measured 7.1x faster at depth 3.
    sel = f", criterion admits {criterion_rows / predicate_rows:.0%}"

    return Decision(
        True,
        f"depth {chain.depth}, pinned "
        f"{'head' if chain.pinned_head else 'tail'}{sel}", chain)


def decide_for_plan(chains, criterion_rows=None, predicate_rows=None) -> Decision:
    """Decide for the deepest chain in a plan, and log it.

    The deepest is the one that matters: cost compounds per hop, and a plan
    holding a 3-hop chain beside a 1-hop chain is dominated by the former.
    """
    if not chains:
        return Decision(False, "no chain")
    decision = decide(chains[0], criterion_rows, predicate_rows)
    logger.info("traversal decision: %s", decision)
    return decision
