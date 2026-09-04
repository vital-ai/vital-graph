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

THE CRITERION REQUIREMENT IS CORRECT — re-measured 2026-08-14 on an isolated host

It was added because an unfiltered depth-3 walk on `wordnet_frames` measured
865 ms flat against 2,044 ms hop-wise. A re-measurement on the busy development
machine appeared to REVERSE that, and this docstring said so for part of a day.

Re-run on the isolated test cluster (`vg-test`, same 16 GB buffer pool as the
host, nothing else on it), interleaved, 9 repetitions, on `graph_synth_100k`
depth 3 from a hub start — a different fixture from the original:

    flat                       1,555 ms   stdev 200
    path-wise (gate bypassed)  2,514 ms   stdev 234      0.62x — 1.6x SLOWER
    dedup (what ships now)       105 ms   stdev  20     14.7x FASTER

**The original finding holds.** Path-wise emission really is ~1.6x slower for an
unfiltered walk, on two independent fixtures, and the gate that refuses it is
right. What did not hold was the contradicting measurement: it was taken on a
machine that had spent a day loading and benchmarking 19M-quad fixtures, where
the flat plan's median swung between 822 ms and 3,158 ms. Isolation, not
repetition, was what the comparison needed.

Note the scope this gate now has. `emit_dedup_chain` handles the unfiltered case
far better than either arm above and is deliberately NOT gated, so the gate only
decides what happens when dedup declines. It is still worth having — that is
exactly when the walk is path-wise and fans out — but it is no longer the thing
standing between a user and a slow query.

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

from .declines import Rule
from .traversal_chain import TraversalChain

logger = logging.getLogger(__name__)

# `semijoin` is stage 2d.1, which loads the range/text/IN statistics this reads.
# Declaring it is not bookkeeping: placed BEFORE that stage, this gate saw no
# number on any query and reported "selectivity unknown" every time. The
# declaration is what makes moving the call a build failure instead of a silent
# regression to the uninformed answer.
SHAPE = Rule("traversal_shape", stage="traversal_decision",
             reads=("collect", "pred_stats", "semijoin"))

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

    # Which end to drive from: "head", "tail", or None when there is no basis
    # to choose. Separate from `hop_wise` because they answer different
    # questions — whether to walk hop by hop, and which way to walk.
    #
    # Only "head" is emittable today: `emit_hop_wise` declines a tail-driven
    # walk as not implemented. A "tail" decision therefore falls back to the
    # flat plan and is RECORDED as a decline, which is the point — the gap
    # shows up in the declines report instead of being invisible.
    direction: Optional[str] = None

    def __repr__(self):
        d = f", drive from {self.direction}" if self.direction else ""
        return f"Decision({'hop-wise' if self.hop_wise else 'as-is'}: {self.reason}{d})"


def _end_sizes(chain, pair_rows, pair_bounds=None):
    """How many rows each end admits, when that is knowable.

    A PINNED end admits one row by definition. A CONSTRAINED end admits whatever
    `rdf_stats` says its (predicate, object) pair holds. An OPEN end is unknown
    and returns None — and unknown is not "large", so it must never be compared
    as if it were.

    A CONSTRAINED END MISSING FROM rdf_stats IS NOT UNKNOWN ANY MORE, and this
    is the point of `pair_bounds` (`issues/153`). `recompute_stats_tables` keeps
    each predicate's LARGEST pairs, so a pair that is absent is smaller than
    every pair stored for its predicate — an upper bound, not a mystery.

    That matters because it is the common shape, not a corner: one end
    constrained to a rare value and the other to a common one. The rare end is
    exactly the one the cap drops, so without a bound this returned None for it
    and `choose_direction` drove from the HUGE end — the opposite of the point
    of the table. `issues/090` measured 9.2x for driving from the smaller end.

    An upper bound is sound to compare directly: if bound < other, the true size
    is also < other and the choice is right. If bound >= other the comparison is
    inconclusive and picking the other end is the conservative outcome, which is
    what falls out anyway.
    """
    def size(pinned, constraint):
        if pinned:
            return 1
        if constraint and pair_rows:
            # Two producers key these differently — `_load_quad_stats` uses UUID
            # objects, `_load_missing_pair_stats` selects `::text` and so uses
            # strings. A lookup that knows only one of them silently misses, and
            # a missing price reads as "unknown end", which is exactly how this
            # gate fails closed and does nothing.
            got = (pair_rows.get(constraint)
                   or pair_rows.get((str(constraint[0]), str(constraint[1]))))
            if got is not None:
                return got
        if constraint and pair_bounds:
            # Absent. Fall back to what absence implies for THIS predicate.
            b = (pair_bounds.get(constraint[0])
                 if constraint[0] in pair_bounds
                 else pair_bounds.get(str(constraint[0])))
            if b is not None:
                return b
        return None
    return (size(chain.pinned_head, chain.head_constraint),
            size(chain.pinned_tail, chain.tail_constraint))


def choose_direction(chain, pair_rows=None, pair_bounds=None) -> Optional[str]:
    """Which end to drive from — the smaller one, when both are known.

    issues/090, re-measured 2026-08-16 on a 5.1M-quad space:

        entity end open (2,863 entities, 5,726 slots of the type)
            anchor-driven   2,452,092 buffers   537.1 ms
            end-driven        338,252 buffers    58.4 ms     9.2x

        entity pinned to ONE uri
            anchor-driven           542 buffers   0.2 ms
            end-driven              601 buffers   1.0 ms     4.2x the other way

    So the direction cannot be a convention; it follows the smaller end. Both
    counts come from statistics already loaded — a pinned end is 1 by
    definition, a constrained end is one `rdf_stats` lookup.

    ONE KNOWABLE END IS STILL USED -- this used to say the opposite ("returns
    None when only one end is knowable"), which contradicted both the code and
    `test_one_knowable_end_is_used`. The usual one-known case is a PINNED end,
    which is 1 row by definition and unbeatable, so declining there would give
    up the whole issues/090 win to avoid a comparison that is not in doubt.

    THE CASE THAT IS IN DOUBT is one end priced and the other absent from
    `rdf_stats`, where this drives from the priced end because the other has no
    number. Since the recompute, absence is no longer uninformative -- but what
    it means depends on the PREDICATE, not on the pair:

      * predicate not cut (the common case: 13 of 15, 18 of 19, 19 of 23 on the
        spaces measured) -- every pair with count >= 2 is stored, so an absent
        pair holds exactly ONE row. The best driving set available, and this
        currently passes it over.
      * predicate cut by `keep_top_n` -- the cap keeps a predicate's LARGEST
        pairs, so an absent pair is <= every stored pair for that predicate.

    Both are UPPER bounds: absence cannot hide a huge end.

    Both are comparable, and both are recoverable from the loaded table without
    a schema change. Not done here: it is a plan change and issues/090's numbers
    swing 9.2x one way and 4.2x the other, so it wants measurement. See
    `issues/153`, which also records that an earlier reading of this had the
    direction backwards.
    """
    head, tail = _end_sizes(chain, pair_rows, pair_bounds)
    if head is not None and tail is not None:
        return "head" if head <= tail else "tail"
    if head is not None:
        return "head"
    if tail is not None:
        return "tail"
    return None


def decide(chain: Optional[TraversalChain],
           criterion_rows: Optional[int] = None,
           predicate_rows: Optional[int] = None,
           pair_rows: Optional[dict] = None,
           pair_bounds: Optional[dict] = None) -> Decision:
    """Choose an evaluation shape for one chain.

    `criterion_rows` / `predicate_rows` come from the value histograms
    (`sync_value_stats.estimate_range` and `rdf_pred_stats`): how many rows the
    per-hop criterion admits, out of how many the predicate has.

    Both are optional and neither gates the decision — they are reported so a
    choice can be diagnosed. See the module docstring for why a selectivity
    threshold here was wrong.
    """
    if chain is None or chain.depth == 0:
        SHAPE.decline("no chain", depth=getattr(chain, "depth", None))
        return Decision(False, "no chain")

    if chain.depth < MIN_DEPTH:
        SHAPE.decline("chain is too shallow",
                      depth=chain.depth, min_depth=MIN_DEPTH)
        return Decision(False, f"depth {chain.depth} < {MIN_DEPTH}", chain)

    # Without a pinned end there is no small driving set, so every hop would
    # materialise the whole relation. Untested, and the one shape with an
    # obvious mechanism for being worse — so it declines.
    direction = choose_direction(chain, pair_rows, pair_bounds)
    if direction is None:
        SHAPE.decline("neither end pinned or constrained, so there is no small "
                      "driving set and every hop would materialise the whole "
                      "relation", depth=chain.depth)
        return Decision(False, "neither end pinned or constrained, "
                               "no driving set", chain)

    # A CONSTRAINED end now counts. It admits a set rather than a row, so it is
    # a driving set when that set is the smaller of the two — which is what
    # `choose_direction` decides from statistics rather than by convention
    # (issues/090: 9.2x choosing right, 4.2x choosing wrong).
    #
    # Emission has not caught up: `emit_hop_wise` serves a head-driven walk
    # only and declines a tail-driven one, with its own recorded reason. That
    # decline stays THERE rather than being duplicated here, because the two
    # answer different questions — this module decides what is BEST, the
    # emitter decides what it can BUILD. Folding "not implemented" into the
    # strategy would make the decision unable to express the thing issues/090
    # needs it to express: that the tail is the better end.

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
        SHAPE.decline("pinned, but no MEASURED criterion — an unfiltered walk "
                      "fans out and hop-wise is a nested-loop strategy",
                      depth=chain.depth, criterion_rows=criterion_rows,
                      predicate_rows=predicate_rows)
        return Decision(False, f"depth {chain.depth}, pinned but no measured "
                               f"criterion — an unfiltered walk fans out", chain)

    # Selectivity is REPORTED, not thresholded. A gate on HOW selective was
    # tried and was wrong (see the correction above); `category IN` admits 56%
    # of its predicate and still measured 7.1x faster at depth 3.
    sel = f", criterion admits {criterion_rows / predicate_rows:.0%}"

    return Decision(
        True,
        f"depth {chain.depth}, driving from {direction}{sel}",
        chain, direction=direction)


def decide_for_plan(chains, criterion_rows=None, predicate_rows=None,
                    pair_rows=None, pair_bounds=None) -> Decision:
    """Decide for the deepest chain in a plan, and log it.

    The deepest is the one that matters: cost compounds per hop, and a plan
    holding a 3-hop chain beside a 1-hop chain is dominated by the former.
    """
    if not chains:
        SHAPE.decline("the plan holds no traversal chain")
        return Decision(False, "no chain")
    decision = decide(chains[0], criterion_rows, predicate_rows, pair_rows,
                      pair_bounds)
    logger.info("traversal decision: %s", decision)
    return decision
