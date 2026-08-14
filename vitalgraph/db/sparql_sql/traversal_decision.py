"""Decide whether a traversal chain should be evaluated hop by hop.

Step 2 of `planning_performance/traversal_chain_plan.md`. `traversal_chain`
finds the chain; this says what to do about it. Like that module it is INERT —
it returns a decision and a reason, and nothing emits differently yet.

WHAT THE CHOICE IS WORTH, measured on graph_synth_10k after the equality
push-down, three start entities, identical answers:

    criterion         depth   generated    hop-wise
    score >= 50           2    126.7 ms     0.7 ms     181x better
    score >= 50           3    187.7 ms     1.0 ms     188x better
    occurred >= mid       3     75.1 ms     2.4 ms      31x better
    category IN (a,b)     2      1.6 ms   320.9 ms     200x WORSE
    category IN (a,b)     3     86.5 ms   684.5 ms       8x WORSE

So this is not an optimisation to apply whenever a chain is found. Applied
blindly it would make the third row 200x slower.

WHY THE RULE IS CONSERVATIVE

Selectivity does not cleanly separate those rows: `occurred` matches ~78% of
frames and hop-wise wins 31x, while `category` matches ~56% and hop-wise loses
8x. The category case is NOT understood — it is not the criterion's formulation
(a join to `term` and an `IN` subquery measure within 3% of each other), and it
is not the result size (11 rows, 254 ms).

Building a rule on an unexplained correlation is how three plausible fixes in
this area were measured to be wrong. So the gate is deliberately narrow: choose
hop-wise only where the win is large AND explainable, and decline everywhere
else — including cases where hop-wise would in fact have won.

That trade, on the numbers above: takes the 181x and 188x, avoids the 200x
regression, and misses the 31x. A missed win costs what it already costs; a
wrong choice makes a working query 200x slower.

WHEN TO REVISIT

Explain the category case first. Until then, widening the threshold is guessing
with a bigger blast radius.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .traversal_chain import TraversalChain

logger = logging.getLogger(__name__)

# A criterion must cut to at most this fraction of the predicate's rows before
# hop-wise evaluation is worth forcing. 0.25 sits below the measured category
# case (~56%) and above the score case (~15%), which is the only separation the
# evidence actually supports.
SELECTIVE_FRACTION = 0.25

# Below this depth there is no sequence to impose: one hop driven from a pinned
# end is already the plan a sane optimiser picks, and the measurements agree
# (depth 1 is sub-millisecond either way).
MIN_DEPTH = 2


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

    A missing estimate declines. `estimate_range` returns None for "unknown",
    never zero, and treating unknown as selective would choose the shape that
    can be 200x worse on exactly the queries nothing is known about.
    """
    if chain is None or chain.depth == 0:
        return Decision(False, "no chain")

    if chain.depth < MIN_DEPTH:
        return Decision(False, f"depth {chain.depth} < {MIN_DEPTH}, nothing to sequence",
                        chain)

    # Without a pinned end there is no small driving set, so hop-wise
    # materialises the whole relation at every step — the shape that lost 200x.
    if not (chain.pinned_head or chain.pinned_tail):
        return Decision(False, "neither end pinned, no driving set", chain)

    if criterion_rows is None or not predicate_rows:
        return Decision(False, "criterion selectivity unknown", chain)

    fraction = criterion_rows / predicate_rows
    if fraction > SELECTIVE_FRACTION:
        return Decision(
            False,
            f"criterion admits {fraction:.0%} of rows, above the "
            f"{SELECTIVE_FRACTION:.0%} threshold", chain)

    return Decision(
        True,
        f"depth {chain.depth}, pinned "
        f"{'head' if chain.pinned_head else 'tail'}, criterion admits "
        f"{fraction:.0%}", chain)


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
