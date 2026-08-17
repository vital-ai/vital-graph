#!/usr/bin/env python
"""Generate a synthetic TRAVERSAL fixture: mixed nodes, mixed edges, real criteria.

The existing pair of fixtures each cover one thing and neither covers traversal:

    wordnet_frames    connection frames, but the ONLY criterion expressible is
                      the traversal type — every slot is a KGEntitySlot and
                      there is not one literal value in the space
    lead_synth        literal slots and rich comparators, but the frames are
                      ATTRIBUTE frames: entity -> frame -> literal. There is
                      nothing to traverse; no frame connects two entities

So the shape a graph store exists for — follow edges between entities, several
hops, keeping only the hops that satisfy a criterion — has no fixture at all.
Measurements on wordnet can only vary the traversal TYPE, which is why
`issues/048` has numbers for type-filtered walks and none for value-filtered
ones.

This fixture is both at once: entities connected BY frames carrying criteria of
every comparator-relevant datatype, plus KG relations as a second, structurally
different traversal, at 10k and 100k like the other pair.

WHAT IT CONTAINS

  entities        several kinds, so a query can select a subset by type
  connection      entity -> frame -> 2 slots -> 2 entities. The traversal edge,
    frames        and where the criteria live
  KG relations    entity -> entity directly, via Edge_hasKGRelation. The other
                  traversal shape, deliberately NOT frame-mediated, so a query
                  crossing both is possible and so the two can be compared
  nested frames   frame -> frame via Edge_hasKGFrame, to depth 8. The third
                  shape, and the one nothing had: a criterion living one level
                  BELOW the frame that connects two entities, plus chains
                  deeper than any plausible cap so a truncating property
                  path is caught rather than assumed absent
  criteria        on every connection frame and every relation:
                    integer   score       uniform [0, 100)
                    double    weight      uniform [0, 1)
                    dateTime  occurred    uniform over a 3-year window
                    string    label       one of 50, for equality and CONTAINS
                    category  category    one of 8, weighted — the IN / VALUES case
                    boolean   active      Bernoulli(0.5)

GROUND TRUTH IS COMPUTED, NOT ASSUMED

The manifest records what the generator actually produced, not what the
distributions imply: criterion counts are tallied while writing, and the
traversal answers are produced by walking the finished graph in Python.

That matters more here than in a value-only fixture. A traversal assertion is
"from this entity, at depth 3, following only hops with score >= 50, you reach
exactly these". Nobody can eyeball whether that is right, and a query that
silently returns a subset looks like a correct answer — which is precisely the
failure this fixture exists to catch. So the expected sets are derived from the
same edge list the N-Triples are written from, by a BFS that shares no code with
the SQL pipeline under test.

TOPOLOGY, and why it is not a lattice

Successors are drawn per entity from a seeded RNG rather than by a stride rule.
A modular rule (i -> i+1, i+k) makes depth-N reachability trivially predictable
and, worse, correlates position with criteria, so a filtered walk degenerates
into a contiguous scan and measures the wrong thing. Random successors with a
fixed fan-out keep the reachable set small and irregular, which is what a real
knowledge graph looks like.

Cycles are permitted. Real graphs have them, a traversal that mishandles one
loops or double-counts, and the BFS records the correct answer either way.

USAGE

    python scripts/generate_graph_dataset.py --entities 10000 \\
        --out internal_data/graph_synth_10k

    python scripts/convert_nt_to_csv.py internal_data/graph_synth_10k/*.nt \\
        --out test_data/graph_synth_10k.csv --graph urn:sp_graph_synth_10k \\
        --dataset graph_synth

    python scripts/load_wordnet_csv.py --space sp_graph_synth_10k \\
        --quads-csv test_data/graph_synth_10k.csv \\
        --terms-csv test_data/graph_synth_10k_terms.csv

Output is N-Triples shards for the same reason as the lead generator: the
.nt -> slim CSV -> COPY path exists and is validated, and duplicating the
uuid5/datatype-id logic here would be a second place for it to drift.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD = "http://www.w3.org/2001/XMLSchema#"

BASE = "urn:graphsyn"

SRC_ROLE = "urn:hasSourceEntity"
DST_ROLE = "urn:hasDestinationEntity"

# Entity kinds. A traversal query can restrict endpoints by kind, which is a
# different axis from the criteria on the edges themselves.
ENTITY_KINDS = ["Person", "Organization", "Product", "Topic", "Place"]

# A RARE entity kind, on a small fraction of entities (issues/090).
#
# The traversal gate chooses which end of a chain to drive from by comparing how
# many rows each end admits, and the ends of a chain are ENTITIES. The five kinds
# above are drawn uniformly, so every kind-constrained end is ~20% of the entity
# set and no end is meaningfully smaller than another. `--rare-entity-fraction`
# adds a sixth kind at a few percent, which is what makes one end genuinely
# small and the direction choice observable.
#
# The skew has to sit on the ENTITY, not on the slot: a rare SLOT TYPE was tried
# first and does not chain. `hasKGSlotType` is how a hop is recognised as a
# source/destination pair in the first place, so a third value there produces
# hops of a different kind, which the chain builder reports as "no multi-hop
# chain found (2 single hops)" and the whole rewrite declines.
RARE_KIND = "Rare"

# Frame types — the wordnet-style criterion, kept so the two fixtures ask the
# same question in the same way.
FRAME_TYPES = ["Mentions", "WorksWith", "DerivedFrom", "LocatedIn"]

# Relation types for the non-frame traversal.
RELATION_TYPES = ["Knows", "Owns", "Supersedes"]

# ---------------------------------------------------------------------------
# NESTED FRAMES — frame -> frame via Edge_hasKGFrame
# ---------------------------------------------------------------------------
#
# The third shape, and the one no fixture had. `traversal_chain_plan.md` GAP 4:
# frames nest via `Edge_hasKGFrame`, arbitrary depth is served by SPARQL
# property paths through a recursive CTE, and
# none of the chain detection, hop-wise emission or dedup has ever been tested
# against a nested-frame walk. Checked before building this: zero
# `Edge_hasKGFrame` terms in any loaded space, and `test_frame_nesting_hops.py`
# seeds raw edge-table rows with no quads and no SPARQL, so it exercises the
# index and nothing above it.
#
# It is how the product actually models compound facts — a LeadStatusFrame
# carrying a LeadStatusQualificationFrame beneath it — so a criterion routinely
# lives one level BELOW the frame that connects two entities.
NESTED_FRAME_TYPES = ["Qualification", "Provenance", "Confidence", "Revision"]

# Fraction of connection frames that carry a child frame at all. Under 1, so a
# query can still tell a nested frame from a plain one — but not far under, and
# the first value tried was too far.
#
# At 0.15 the derived criterion "this frame has a descendant with score >= 50"
# came out at 2.9% per hop, and a depth-3 walk under it was EMPTY from all 13
# sample starts. That is the failure this generator's own docstring names: a
# fixture whose expected answers are mostly `[]` cannot distinguish a working
# traversal from one that returns nothing. Raised until the densest nested
# criterion survives to depth 3 — see `nesting.walk_density` in the manifest,
# which reports what was actually achieved rather than what this implies.
NEST_P = 0.35

# Probability a nested frame itself carries a child. Geometric, so chain length
# has a tail rather than a fixed depth.
NEST_DECAY = 0.5

# THE CAP MUST BE EXERCISED, AND A PROBABILITY IS NOT A GUARANTEE.
#
# The question GAP 4 asks is whether a recursive path silently truncates
# real nesting, and a truncated walk returns FEWER rows — which reads as a
# correct answer. A geometric draw at NEST_DECAY gives depth >= 6 about 3% of
# the time, so on an unlucky seed the fixture would contain nothing past the cap
# and the test would pass by not asking. So a fixed number of chains are forced
# to exactly DEEP_CHAIN_DEPTH, which is deliberately GREATER than the cap.
DEEP_CHAIN_COUNT = 40
DEEP_CHAIN_DEPTH = 8

# The IN / VALUES case: skewed on purpose. A uniform categorical makes every
# `IN (...)` roughly the same size, which hides whether selectivity is being
# used at all.
CATEGORIES = [
    ("alpha", 32), ("beta", 24), ("gamma", 16), ("delta", 12),
    ("epsilon", 8), ("zeta", 4), ("eta", 3), ("theta", 1),
]

LABELS = [f"label-{i:02d}" for i in range(50)]

# A MULTI-VALUED criterion: an edge carries one to several tags. Everything else
# here is single-valued, which makes a whole class of question untestable —
# `rdf_stats` counts QUADS, so on a multi-valued predicate a subject with two
# matching values is counted twice and an `IN` sum exceeds the number of
# matching SUBJECTS. With every predicate single-valued the two are identical
# and the difference cannot be observed.
TAGS = ["urgent", "review", "archived", "external", "draft", "verified"]
TAG_COUNT_WEIGHTS = [(1, 55), (2, 30), (3, 12), (4, 3)]

DATE_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
DATE_DAYS = 3 * 365

# Thresholds the manifest reports actual counts for, so a bench can sweep
# selectivity and assert against a number rather than an observation.
SCORE_THRESHOLDS = [0, 25, 50, 75, 90, 99]
WEIGHT_THRESHOLDS = [0.0, 0.25, 0.5, 0.75, 0.9, 0.99]

# Depths the traversal ground truth is computed for. 3 is where the join count
# and the cost both start to matter (issues/048).
TRAVERSAL_DEPTHS = [1, 2, 3]

# How many start entities to record answers for. Enough that a bench can pick
# one with a non-trivial reachable set; few enough to keep the manifest small.
N_SAMPLE_STARTS = 12


def _uri(*parts) -> str:
    return f"{BASE}:" + ":".join(str(p) for p in parts)


def _t(s: str, p: str, o: str) -> str:
    return f"<{s}> <{p}> <{o}> .\n"


def _lit(s: str, p: str, value, dtype: str) -> str:
    v = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'<{s}> <{p}> "{v}"^^<{dtype}> .\n'


def _weighted(rng: random.Random, pairs):
    total = sum(w for _v, w in pairs)
    r = rng.uniform(0, total)
    upto = 0.0
    for v, w in pairs:
        upto += w
        if r <= upto:
            return v
    return pairs[-1][0]


class Criteria:
    """The criterion values carried by one edge, whatever kind of edge it is.

    Held as an object rather than emitted inline so the same values feed BOTH
    the N-Triples and the ground-truth walk. Generating them twice from the same
    seed would work until someone changed the draw order in one place only.
    """

    __slots__ = ("score", "weight", "occurred", "label", "category", "active",
                 "tags")

    def __init__(self, rng: random.Random):
        # Values are SKEWED, deliberately. Uniform values make a planner's job
        # trivially easy: every histogram bucket is the same height, so any
        # selectivity estimate is right and no misestimation can be reproduced.
        # Real attributes are not uniform, and issues/072 and the nurture-slot
        # timeouts were both planner misestimates on skewed data.

        # score: log-normal, the usual shape for a rating or a count — most
        # values low, a long thin tail. Clipped to [0, 100) to stay comparable
        # with the lead fixture's rating range.
        self.score = min(99, int(rng.lognormvariate(2.9, 0.8)))

        # weight: Beta(2, 5) — bounded, unimodal, mass toward zero. The shape a
        # normalised confidence or affinity actually has.
        self.weight = round(rng.betavariate(2.0, 5.0), 6)

        # occurred: recency-biased rather than flat. Knowledge graphs accrete,
        # so recent edges outnumber old ones; an exponential over the window
        # gives that without a hard cutoff. Business hours and weekdays are
        # modelled too, because a date range that lands on a weekend boundary
        # behaves differently from one that does not, and flat timestamps hide
        # it entirely.
        age_days = min(DATE_DAYS - 1, int(rng.expovariate(1.0 / (DATE_DAYS / 3))))
        when = DATE_START + timedelta(days=DATE_DAYS - 1 - age_days)
        if when.weekday() >= 5 and rng.random() < 0.8:
            when -= timedelta(days=2)          # most activity on weekdays
        hour = min(23, max(0, int(rng.gauss(13, 3))))   # clustered in the day
        self.occurred = when.replace(
            hour=hour, minute=rng.randrange(60), second=rng.randrange(60))

        # label: Zipf over the label set. String equality on a heavy-tailed
        # column is where an index either helps enormously or not at all.
        self.label = LABELS[min(len(LABELS) - 1,
                                int(rng.paretovariate(1.2)) - 1)]
        self.category = _weighted(rng, CATEGORIES)

        # A flag that is mostly false. p=0.5 is the one value that makes a
        # boolean useless as a filter.
        self.active = rng.random() < 0.2

        # One to four tags, skewed toward one. Distinct values per edge, so the
        # quad count and the subject count genuinely differ.
        n_tags = _weighted(rng, TAG_COUNT_WEIGHTS)
        self.tags = sorted(rng.sample(TAGS, n_tags))

    def triples(self, subject: str) -> str:
        return (
            _lit(subject, f"{HALEY}hasScore", self.score, f"{XSD}integer")
            + _lit(subject, f"{HALEY}hasWeight", self.weight, f"{XSD}double")
            + _lit(subject, f"{HALEY}hasOccurredAt",
                   self.occurred.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                   f"{XSD}dateTime")
            + _lit(subject, f"{HALEY}hasLabel", self.label, f"{XSD}string")
            + _lit(subject, f"{HALEY}hasCategory", self.category, f"{XSD}string")
            + _lit(subject, f"{HALEY}hasActive",
                   "true" if self.active else "false", f"{XSD}boolean")
            + "".join(_t(subject, f"{HALEY}hasTag", f"{BASE}:tag:{tag}")
                      for tag in self.tags)
        )


def _draw_out_degree(rng: random.Random, mean_fanout: int, cap: int = 200) -> int:
    """Out-degree per entity, heavy-tailed rather than constant.

    A fixed fan-out gives every entity the same cost profile, so a traversal
    bench measures one shape repeatedly. Real entities differ by orders of
    magnitude — most connect to a handful of things, a few connect to thousands
    — and the expensive queries are the ones that touch the few.

    `cap` SCALES with the dataset, which the in-degree `hub_cap` already did and
    this did not. A fixed 200 makes the biggest hub a smaller and smaller share
    of the graph as the fixture grows: measured at 100k entities it reached 107
    distinct neighbours, 0.107% of the graph, where `wordnet_frames`' largest
    hub reaches 671 of 109,734 — 0.611%, nearly 6x hubbier in the terms that
    matter. The consequence was that no synthetic fixture, at any size, could
    reproduce the fan-out shape where hop-wise traversal measured 2.4x SLOWER,
    so the gate protecting against it could only ever be calibrated on wordnet.
    """
    d = int(rng.paretovariate(1.6) * mean_fanout / 2)
    return max(1, min(d, cap))


def build_topology(n_entities: int, fanout: int = 4,
                   relation_fanout: int = 2, seed: int = 0,
                   local_p: float = 0.55, alpha: float = 1.05,
                   ring: int = 3):
    """Choose every edge before writing anything, with a realistic shape.

    The edge lists are the single source of truth: the N-Triples are rendered
    from them and the expected traversal answers are walked over them.

    WHY NOT UNIFORM RANDOM TARGETS
    ------------------------------
    Uniform targets give an Erdos-Renyi graph — Poisson degrees, no hubs,
    clustering near zero — which is the least knowledge-graph-like structure
    available and flatters everything measured on it:

      * no hubs means no worst case, and traversal cost is dominated by whether
        the walk passes through a high-degree node;
      * no clustering means no redundant paths, so the deduplication a real
        traversal must do never arises;
      * degrees concentrate at the mean, making cardinality estimation easy and
        hiding exactly the misestimation behind issues/072 and the nurture-slot
        timeouts.

    THE TWO TERMS
    -------------
    LOCAL (probability `local_p`) — a neighbour within `ring` on the index ring.
      This is the Watts-Strogatz lattice term and it produces CLUSTERING: a
      node's neighbours are themselves likely connected, giving triangles. The
      radius is small on purpose; a wide one spreads local edges too thin to
      close any.

    POWER-LAW (otherwise) — a target drawn from a pool built by a CONFIGURATION
      MODEL: each node is assigned a desired in-degree from a Pareto draw and
      appears in the pool that many times. This produces HUBS and a heavy in-
      degree tail by construction.

      Preferential attachment was tried first and rejected: with every node
      seeded once into the sampling pool, the uniform seed dominates and the
      tail never forms — measured max in-degree 27 where the configuration
      model gives 207 on the same size.

    Together, measured at 2,000 entities: in-degree max 207 against a median of
    4, Gini 0.50, clustering 0.106 — about 50x the random-graph baseline for
    this density — and a mean path of 3.6 hops. High clustering with short
    paths is the small-world signature.

    Self-loops are rejected; duplicate edges are not. Two entities related by
    more than one frame is normal in a knowledge graph, and a traversal that
    double-counts them is a defect this fixture should be able to expose.
    """
    rng = random.Random(seed)

    frame_edges = []      # (src_idx, dst_idx, Criteria, frame_type)
    relation_edges = []   # (src_idx, dst_idx, Criteria, relation_type)

    # A hub may hold up to ~2% of all IN-EDGES. Uncapped, a Pareto draw at this
    # alpha occasionally has one node absorb most of the graph, which is not
    # realistic and makes the fixture's cost profile depend on a single unlucky
    # draw.
    #
    # The share is of edges, not of nodes: capping at a fraction of n_entities
    # truncates the tail at small sizes — at 2,000 entities that produced a max
    # in-degree of 36 where the uncapped draw gives 207 — so the fixture stopped
    # having hubs exactly where they are cheapest to test.
    hub_cap = max(20, int(n_entities * fanout * 0.02))
    in_target = [max(1, min(int(rng.paretovariate(alpha)), hub_cap))
                 for _ in range(n_entities)]
    pool = [i for i, d in enumerate(in_target) for _ in range(d)]
    rng.shuffle(pool)
    cursor = 0

    def pick_target(src: int) -> int:
        nonlocal cursor
        for _ in range(8):
            if rng.random() < local_p:
                offset = rng.randrange(1, ring + 1) * rng.choice((1, -1))
                dst = (src + offset) % n_entities
            else:
                if cursor >= len(pool):
                    rng.shuffle(pool)
                    cursor = 0
                dst = pool[cursor]
                cursor += 1
            if dst != src:
                return dst
        return (src + 1) % n_entities

    # Roughly `wordnet_frames`' hub share once duplicate edges collapse: the
    # draw is of EDGES and a hub's targets repeat, so ~1.2% of entities as a raw
    # cap lands near 0.6% as distinct neighbours. Floored at 200 so small
    # fixtures keep the tail they already had.
    out_cap = max(200, int(n_entities * 0.012))

    for i in range(n_entities):
        for _ in range(_draw_out_degree(rng, fanout, out_cap)):
            frame_edges.append(
                (i, pick_target(i), Criteria(rng), rng.choice(FRAME_TYPES)))
        for _ in range(_draw_out_degree(rng, relation_fanout, out_cap)):
            relation_edges.append(
                (i, pick_target(i), Criteria(rng), rng.choice(RELATION_TYPES)))

    return frame_edges, relation_edges


def build_nesting(n_frames: int, seed: int = 0):
    """Attach child frames beneath connection frames, forming a forest.

    Returns a list of nested frames, each a tuple:

        (nested_idx, parent_kind, parent_idx, depth, Criteria, frame_type)

    where `parent_kind` is "frame" for a connection frame (`frame_edges[idx]`)
    or "nested" for another nested frame (`nested[idx]`), and `depth` is 1 for a
    direct child. The list is in creation order, and a parent always precedes
    its children, so a single forward pass can render or walk it.

    The first DEEP_CHAIN_COUNT connection frames get a straight chain of exactly
    DEEP_CHAIN_DEPTH — see the constant for why that is forced rather than
    drawn. Everything after that nests geometrically.
    """
    rng = random.Random(seed + 7)
    nested = []

    def add(parent_kind, parent_idx, depth):
        idx = len(nested)
        nested.append((idx, parent_kind, parent_idx, depth, Criteria(rng),
                       rng.choice(NESTED_FRAME_TYPES)))
        return idx

    n_deep = min(DEEP_CHAIN_COUNT, n_frames)
    for fi in range(n_deep):
        parent_kind, parent_idx = "frame", fi
        for depth in range(1, DEEP_CHAIN_DEPTH + 1):
            parent_idx = add(parent_kind, parent_idx, depth)
            parent_kind = "nested"

    for fi in range(n_deep, n_frames):
        if rng.random() >= NEST_P:
            continue
        parent_kind, parent_idx, depth = "frame", fi, 1
        while True:
            parent_idx = add(parent_kind, parent_idx, depth)
            parent_kind = "nested"
            depth += 1
            if rng.random() >= NEST_DECAY:
                break

    return nested


def _nested_matching_set(nested, predicate=None, max_depth=1):
    """Connection frames with a descendant at depth <= `max_depth` satisfying `predicate`.

    `predicate(Criteria) -> bool`, or None for "has any descendant at all".

    `max_depth` DEFAULTS TO 1, AND THAT DEFAULT IS THE WHOLE POINT.
    ------------------------------------------------------------
    The ground truth has to ask the same question the query asks. The nested
    criterion templates in `graph_fixtures.NESTED_CRITERIA` descend exactly one
    `Edge_hasKGFrame` hop, so a frame whose only matching descendant is a
    GRANDCHILD is not matched by them.

    Computing this at any depth is what the first version did, and it produced a
    ground truth 11,536 frames wide against a query that matches 9,065 — so a
    correct engine returned 3 entities where the manifest said 4, on one case in
    twelve. Read as a test failure that is "the traversal silently drops rows",
    which is the most alarming defect this fixture can report and was entirely
    the fixture's own. Deriving the expected answer from a DIFFERENT definition
    than the query uses is the same drift the fixture exists to catch, one level
    up.

    A transitive walk needs `max_depth=None` AND a query using a property path.
    That combination is not currently usable: the `+` path over
    `^hasEdgeSource/hasEdgeDestination` did not complete within 60 s on the 10k
    fixture for a root with 8 descendants.
    """
    parent_of = {idx: (pk, pi) for idx, pk, pi, _d, _c, _ft in nested}
    out = set()
    for idx, _pk, _pi, depth, crit, _ft in nested:
        if max_depth is not None and depth > max_depth:
            continue
        if predicate is not None and not predicate(crit):
            continue
        pk, pi = parent_of[idx]
        while pk == "nested":            # climb to the connection frame
            pk, pi = parent_of[pi]
        out.add(pi)
    return out


# The nested criteria the manifest records walks for, densest first. A test
# picks by what it needs: the dense ones survive to depth 3, `score >= 50` is
# a depth-1/2 case by construction and the manifest says so.
NESTED_WALKS = {
    "frame_traversal_has_nested": None,
    "frame_traversal_nested_category_in_alpha_beta":
        lambda c: c.category in ("alpha", "beta"),
    "frame_traversal_nested_score_gte_50": lambda c: c.score >= 50,
}


def nesting_ground_truth(nested, frame_edges):
    """What a nested-frame query must return, walked from the same list.

    Two questions, because GAP 4 asks two:

      * **The property path.** `?f <Edge_hasKGFrame>* ?child` over a root whose
        subtree is deeper than 5. `deep_roots` records, per
        connection frame with a chain past the cap, the descendants at each
        depth — so a truncating walk is caught by a count, not by inspection.
      * **The nested criterion.** Which connection frames have a DESCENDANT
        carrying `score >= 50`. That is the traversal question the product
        actually asks, and it is the one where a criterion sits below the frame
        that joins two entities.
    """
    children = {}
    for idx, pkind, pidx, _depth, _crit, _ft in nested:
        children.setdefault((pkind, pidx), []).append(idx)

    by_depth_hist = {}
    for _idx, _pk, _pi, depth, _c, _ft in nested:
        by_depth_hist[depth] = by_depth_hist.get(depth, 0) + 1

    def descendants_by_depth(root_frame_idx):
        """{relative depth: [nested idx]} beneath one connection frame."""
        out, frontier, d = {}, children.get(("frame", root_frame_idx), []), 1
        while frontier:
            out[str(d)] = sorted(frontier)
            nxt = []
            for n in frontier:
                nxt += children.get(("nested", n), [])
            frontier, d = nxt, d + 1
        return out

    deep_roots = {}
    for fi in range(min(DEEP_CHAIN_COUNT, len(frame_edges))):
        d = descendants_by_depth(fi)
        if len(d) > 5:                    # deep enough to expose truncation
            deep_roots[str(fi)] = d

    # Walked over the same list the N-Triples are rendered from, not inferred
    # from NEST_P, and through the SAME function the traversal walks use.
    matching = {k: _nested_matching_set(nested, p)
                for k, p in NESTED_WALKS.items()}

    return {
        "n_nested_frames": len(nested),
        "max_depth": max(by_depth_hist) if by_depth_hist else 0,
        "depth_histogram": {str(k): v for k, v in sorted(by_depth_hist.items())},
        "max_path_depth_note": (
            "emit_path.py caps recursive property paths at MAX_PATH_DEPTH "
            "(100). deep_roots hold chains of DEEP_CHAIN_DEPTH, so a walk that "
            "truncates for any reason returns strictly fewer descendants than "
            "recorded here."),
        "deep_roots": deep_roots,
        # Per-hop selectivity of each nested criterion, as a fraction of all
        # connection frames. Reported because it is what decides how deep the
        # matching walk stays non-empty, and because the first version of this
        # fixture shipped one at 2.9% whose depth-3 answers were all `[]`.
        "walk_density": {
            k: {"frames": len(v),
                "fraction": round(len(v) / max(len(frame_edges), 1), 4)}
            for k, v in matching.items()
        },
    }


def graph_stats(edges, n_entities: int, rng: random.Random) -> dict:
    """Degree distribution, clustering and path length — the evidence that the
    generated graph has the shape it claims.

    Recorded in the manifest so a bench can say "this walk started at a hub"
    rather than discovering it as an unexplained outlier, and so a change to the
    generator that flattens the distribution is visible rather than silent.

    Clustering and path length are SAMPLED. Both are O(n * d^2) or worse exactly,
    which at 100k would dominate generation; the manifest records the sample
    size so the number is not mistaken for exact.
    """
    out_deg = [0] * n_entities
    in_deg = [0] * n_entities
    undirected = {}
    for src, dst, _c, _k in edges:
        out_deg[src] += 1
        in_deg[dst] += 1
        undirected.setdefault(src, set()).add(dst)
        undirected.setdefault(dst, set()).add(src)

    def summary(degs):
        s = sorted(degs)
        n = len(s)
        total = sum(s) or 1
        # Gini: 0 = every node identical, 1 = one node has everything. The
        # single number that says whether hubs exist.
        cum = 0
        for idx, v in enumerate(s, 1):
            cum += idx * v
        gini = (2 * cum) / (n * total) - (n + 1) / n
        return {
            "max": s[-1], "mean": round(total / n, 2),
            "p50": s[n // 2], "p90": s[int(n * 0.9)], "p99": s[int(n * 0.99)],
            "gini": round(gini, 3),
        }

    sample = rng.sample(range(n_entities), min(500, n_entities))
    clustering = []
    for node in sample:
        nb = undirected.get(node, set())
        if len(nb) < 2:
            continue
        nb_list = list(nb)
        links = sum(1 for a_i, a in enumerate(nb_list)
                    for b in nb_list[a_i + 1:]
                    if b in undirected.get(a, ()))
        possible = len(nb_list) * (len(nb_list) - 1) / 2
        clustering.append(links / possible if possible else 0.0)

    # Average shortest path, sampled, on the undirected view. Short paths beside
    # high clustering is the small-world signature.
    hops = []
    for src in rng.sample(range(n_entities), min(30, n_entities)):
        seen = {src: 0}
        q = deque([src])
        while q and len(seen) < 3000:
            cur = q.popleft()
            if seen[cur] >= 6:
                continue
            for nxt in undirected.get(cur, ()):
                if nxt not in seen:
                    seen[nxt] = seen[cur] + 1
                    q.append(nxt)
        if len(seen) > 1:
            hops.append(sum(seen.values()) / (len(seen) - 1))

    top = sorted(range(n_entities), key=lambda i: in_deg[i], reverse=True)[:10]
    return {
        "in_degree": summary(in_deg),
        "out_degree": summary(out_deg),
        "clustering_coefficient": round(sum(clustering) / len(clustering), 4)
                                  if clustering else 0.0,
        "clustering_sample": len(clustering),
        "mean_path_length_sampled": round(sum(hops) / len(hops), 2) if hops else None,
        "path_sample": len(hops),
        "top_in_degree": [{"entity": i, "in_degree": in_deg[i]} for i in top],
        "isolated_in": sum(1 for d in in_deg if d == 0),
    }


def _adjacency(edges, predicate=None):
    adj = {}
    for src, dst, crit, kind in edges:
        if predicate and not predicate(crit, kind):
            continue
        adj.setdefault(src, set()).add(dst)
    return adj


def _adjacency_by_index(edges, keep_indexes):
    """Adjacency keeping only edges whose POSITION is in `keep_indexes`.

    The nested-criterion walk cannot be expressed as a predicate over an edge's
    own criteria — what qualifies it is a value on a frame BENEATH it — so the
    filter is by identity rather than by value.
    """
    adj = {}
    for i, (src, dst, _crit, _kind) in enumerate(edges):
        if i in keep_indexes:
            adj.setdefault(src, set()).add(dst)
    return adj


def _reachable(adj, start: int, depth: int) -> set:
    """Entities EXACTLY `depth` hops away, following `adj`.

    Exactly, not at-most: a traversal query with N hops written out returns the
    far end of an N-hop path, and a walk that quietly admits shorter paths is a
    real defect this fixture should catch rather than encode.
    """
    frontier = {start}
    for _ in range(depth):
        nxt = set()
        for node in frontier:
            nxt |= adj.get(node, set())
        frontier = nxt
        if not frontier:
            break
    return frontier


def compute_ground_truth(frame_edges, relation_edges, n_entities, seed,
                         nested_matching=None):
    """Walk the finished edge lists and record the answers a query must give."""
    rng = random.Random(seed + 1)

    frame_adj = _adjacency(frame_edges)
    rel_adj = _adjacency(relation_edges)
    # One filtered view per criterion family, so a bench can assert a FILTERED
    # traversal rather than only an open one.
    frame_adj_score50 = _adjacency(
        frame_edges, lambda c, _k: c.score >= 50)
    frame_adj_cat_ab = _adjacency(
        frame_edges, lambda c, _k: c.category in ("alpha", "beta"))
    frame_adj_type0 = _adjacency(
        frame_edges, lambda _c, k: k == FRAME_TYPES[0])
    frame_adj_recent = _adjacency(
        frame_edges,
        lambda c, _k: c.occurred >= DATE_START + timedelta(days=DATE_DAYS // 2))
    # The nested cases: keep a hop only when the connecting frame has a CHILD
    # frame satisfying the criterion. Structurally different from every filter
    # above — the criterion is one Edge_hasKGFrame BELOW the traversal edge — so
    # a rewrite that quietly drops the nested hop still satisfies all the others.
    nested_matching = nested_matching or {}
    nested_adj = {k: _adjacency_by_index(frame_edges, v)
                  for k, v in nested_matching.items()}

    # Sample starts are CHOSEN, not drawn uniformly. With a filter admitting
    # roughly half the hops, a uniformly-drawn start usually has an empty
    # reachable set by depth 3, and a fixture whose expected answers are mostly
    # `[]` cannot distinguish a working traversal from one that returns nothing
    # — the exact failure this is built to catch.
    #
    # So: prefer starts that still reach something at the deepest depth UNDER
    # THE MOST SELECTIVE filter, and fall back to any start if too few qualify.
    # The bias is toward the interesting corner of the graph, not toward any
    # particular answer, and the recorded answers are still whatever the walk
    # produced.
    deepest = max(TRAVERSAL_DEPTHS)

    # Span the DEGREE DISTRIBUTION, not just reachability. On a scale-free graph
    # the cost of a walk is dominated by whether it passes through a hub, so a
    # sample drawn without regard to degree measures the typical case and never
    # the expensive one.
    #
    # OUT-degree is seeded first, and that is the correction. This used to seed
    # by IN-degree alone, which is the wrong end for the query these fixtures
    # exist to measure: a forward walk pinned at its head fans out by the START
    # entity's OUT-degree, and the highest in-degree entity has no particular
    # out-degree at all. The consequence was measurable — every open traversal
    # on graph_synth reached 4, 16 and 64 entities at depths 1-3, so the fixture
    # could not reproduce the fan-out shape that made hop-wise emission 2.4x
    # SLOWER on wordnet, and the gate protecting against it rested on one
    # dataset.
    #
    # In-degree is still seeded, because a tail-pinned walk is the mirror case
    # and will want it once reverse traversal is implemented.
    out_deg, in_deg = {}, {}
    for s, d, _c, _k in frame_edges:
        out_deg[s] = out_deg.get(s, 0) + 1
        in_deg[d] = in_deg.get(d, 0) + 1
    by_out = sorted(range(n_entities), key=lambda i: out_deg.get(i, 0),
                    reverse=True)
    by_in = sorted(range(n_entities), key=lambda i: in_deg.get(i, 0),
                   reverse=True)
    seeded = [by_out[0], by_out[1], by_out[len(by_out) // 2], by_out[-1],
              by_in[0]]
    seeded = list(dict.fromkeys(seeded))       # de-dupe, keep order

    candidates = list(range(n_entities))
    rng.shuffle(candidates)
    candidates = seeded + [c for c in candidates if c not in seeded]
    useful, plain = [], []
    # A start must keep the NESTED walk alive too, not only the flat one. The
    # two select different corners of the graph — nesting is a property of the
    # frame, reachability a property of the entity — and picking on the flat
    # criterion alone left the densest nested walk empty at depth 3 from every
    # start, which is a fixture that cannot fail.
    dense_nested = nested_adj.get("frame_traversal_nested_category_in_alpha_beta")
    for c in candidates:
        if len(useful) >= N_SAMPLE_STARTS and len(plain) >= 2:
            break
        if _reachable(frame_adj_score50, c, deepest) and (
                dense_nested is None or _reachable(dense_nested, c, deepest)):
            if len(useful) < N_SAMPLE_STARTS - 2:
                useful.append(c)
        elif len(plain) < 2:
            plain.append(c)          # keep a couple of dead ends on purpose
    starts = sorted(set(seeded + useful + plain))
    if len(starts) < min(N_SAMPLE_STARTS, n_entities):
        extra = [c for c in candidates if c not in starts]
        starts = sorted(set(starts + extra[:N_SAMPLE_STARTS - len(starts)]))

    def walk(adj):
        return {
            str(s): {str(d): sorted(_reachable(adj, s, d))
                     for d in TRAVERSAL_DEPTHS}
            for s in starts
        }

    return {
        "sample_starts": starts,
        "frame_traversal": walk(frame_adj),
        "frame_traversal_score_gte_50": walk(frame_adj_score50),
        "frame_traversal_category_in_alpha_beta": walk(frame_adj_cat_ab),
        "frame_traversal_type_is_" + FRAME_TYPES[0]: walk(frame_adj_type0),
        "frame_traversal_occurred_second_half": walk(frame_adj_recent),
        "relation_traversal": walk(rel_adj),
        **{k: walk(adj) for k, adj in nested_adj.items()},
    }


def tally(edges):
    """Actual counts, tallied from what was generated."""
    n = len(edges)
    out = {
        "count": n,
        "score_gte": {str(t): sum(1 for _s, _d, c, _k in edges if c.score >= t)
                      for t in SCORE_THRESHOLDS},
        "weight_gte": {str(t): sum(1 for _s, _d, c, _k in edges if c.weight >= t)
                       for t in WEIGHT_THRESHOLDS},
        "active_true": sum(1 for _s, _d, c, _k in edges if c.active),
        "category_eq": {},
        "label_eq": {},
        "kind_eq": {},
        "occurred_second_half": sum(
            1 for _s, _d, c, _k in edges
            if c.occurred >= DATE_START + timedelta(days=DATE_DAYS // 2)),
    }
    for name, _w in CATEGORIES:
        out["category_eq"][name] = sum(
            1 for _s, _d, c, _k in edges if c.category == name)
    for lb in LABELS[:5]:
        out["label_eq"][lb] = sum(1 for _s, _d, c, _k in edges if c.label == lb)

    # The multi-valued one, counted BOTH ways on purpose. `rdf_stats` answers
    # in quads; a query asking "which frames" wants subjects. A test comparing
    # an estimate against the wrong one of these would look correct.
    out["tag_quads"] = {}
    out["tag_subjects"] = {}
    for tag in TAGS:
        out["tag_quads"][tag] = sum(1 for _s, _d, c, _k in edges if tag in c.tags)
        out["tag_subjects"][tag] = out["tag_quads"][tag]   # one edge = one subject
    # An IN over two tags: a subject carrying BOTH is one subject and two quads.
    pair = (TAGS[0], TAGS[1])
    out["tag_in_pair"] = {
        "tags": list(pair),
        "quads": sum(len([g for g in pair if g in c.tags])
                     for _s, _d, c, _k in edges),
        "subjects": sum(1 for _s, _d, c, _k in edges
                        if any(g in c.tags for g in pair)),
    }
    out["avg_tags_per_edge"] = round(
        sum(len(c.tags) for _s, _d, c, _k in edges) / max(len(edges), 1), 2)
    for _s, _d, _c, k in edges:
        out["kind_eq"][k] = out["kind_eq"].get(k, 0) + 1
    return out


def _is_rare(index: int, fraction: float) -> bool:
    """Deterministic membership of the rare minority.

    Index arithmetic rather than a random draw, so the set is derivable from the
    manifest without replaying the generator's rng state — a test that has to
    reproduce the generator's stream to know what it built is a test that will
    drift away from its fixture.
    """
    if fraction <= 0:
        return False
    every = max(1, int(round(1.0 / fraction)))
    return index % every == 0


def generate(out_dir: Path, n_entities: int, fanout: int, relation_fanout: int,
             seed: int, shard_entities: int,
             rare_entity_fraction: float = 0.0) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("graph_syn_*.nt"):
        old.unlink()

    t0 = time.time()
    frame_edges, relation_edges = build_topology(
        n_entities, fanout, relation_fanout, seed)
    nested = build_nesting(len(frame_edges), seed)

    rng = random.Random(seed + 2)
    entity_kind = [rng.choice(ENTITY_KINDS) for _ in range(n_entities)]
    # The rare minority, chosen by INDEX rather than by an rng draw so the set is
    # derivable from the manifest alone. A test that has to replay the
    # generator's rng stream to know which entities it built is a test that
    # drifts away from its fixture the first time anything above it draws.
    n_rare_entities = 0
    if rare_entity_fraction > 0:
        for i in range(n_entities):
            if _is_rare(i, rare_entity_fraction):
                entity_kind[i] = RARE_KIND
                n_rare_entities += 1

    n_triples = 0
    shard_idx = 0
    fh = None

    def ent(i):
        return _uri("entity", i)

    try:
        for i in range(n_entities):
            if i % shard_entities == 0:
                if fh:
                    fh.close()
                shard_idx += 1
                fh = open(out_dir / f"graph_syn_{shard_idx:04d}.nt", "w",
                          encoding="utf-8")

            e = ent(i)
            kind = entity_kind[i]
            buf = [
                _t(e, RDF_TYPE, f"{HALEY}KGEntity"),
                _t(e, f"{VITAL}vitaltype", f"{HALEY}KGEntity"),
                _t(e, f"{VITAL}URIProp", e),
                _t(e, f"{HALEY}hasKGEntityType", f"{BASE}:kind:{kind}"),
                _lit(e, f"{VITAL}hasName", f"entity {i} ({kind})", f"{XSD}string"),
                _lit(e, f"{HALEY}hasKGraphDescription",
                     f"synthetic {kind} number {i}", f"{XSD}string"),
            ]
            fh.write("".join(buf))
            n_triples += len(buf)

        # Connection frames: the frame-mediated traversal edge.
        for fi, (src, dst, crit, ftype) in enumerate(frame_edges):
            if fh is None:
                break
            frame = _uri("frame", fi)
            s_slot, d_slot = _uri("slot", fi, "s"), _uri("slot", fi, "d")
            s_edge, d_edge = _uri("edge", fi, "s"), _uri("edge", fi, "d")
            buf = [
                _t(frame, RDF_TYPE, f"{HALEY}KGFrame"),
                _t(frame, f"{VITAL}vitaltype", f"{HALEY}KGFrame"),
                _t(frame, f"{VITAL}URIProp", frame),
                _t(frame, f"{HALEY}hasKGFrameType", f"{BASE}:frametype:{ftype}"),
                _lit(frame, f"{HALEY}hasKGFrameTypeDescription", ftype, f"{XSD}string"),
                crit.triples(frame),
            ]
            for slot, edge, role, target in (
                    (s_slot, s_edge, SRC_ROLE, ent(src)),
                    (d_slot, d_edge, DST_ROLE, ent(dst))):
                buf += [
                    _t(slot, RDF_TYPE, f"{HALEY}KGEntitySlot"),
                    _t(slot, f"{VITAL}vitaltype", f"{HALEY}KGEntitySlot"),
                    _t(slot, f"{VITAL}URIProp", slot),
                    _t(slot, f"{HALEY}hasKGSlotType", role),
                    _t(slot, f"{HALEY}hasEntitySlotValue", target),
                    _t(edge, RDF_TYPE, f"{HALEY}Edge_hasKGSlot"),
                    _t(edge, f"{VITAL}vitaltype", f"{HALEY}Edge_hasKGSlot"),
                    _t(edge, f"{VITAL}URIProp", edge),
                    _t(edge, f"{VITAL}hasEdgeSource", frame),
                    _t(edge, f"{VITAL}hasEdgeDestination", slot),
                ]
            block = "".join(buf)
            fh.write(block)
            n_triples += block.count("\n")

        # Nested frames: frame -> frame via Edge_hasKGFrame.
        #
        # A child is an ordinary KGFrame — same type, same criteria predicates —
        # so nothing distinguishes it structurally except what points AT it.
        # That is the shape the product uses and it is what makes the criterion
        # reachable only by descending one more edge.
        for (ni, pkind, pidx, _depth, crit, ftype) in nested:
            if fh is None:
                break
            child = _uri("nframe", ni)
            parent = (_uri("frame", pidx) if pkind == "frame"
                      else _uri("nframe", pidx))
            nedge = _uri("nedge", ni)
            buf = [
                _t(child, RDF_TYPE, f"{HALEY}KGFrame"),
                _t(child, f"{VITAL}vitaltype", f"{HALEY}KGFrame"),
                _t(child, f"{VITAL}URIProp", child),
                _t(child, f"{HALEY}hasKGFrameType", f"{BASE}:frametype:{ftype}"),
                _lit(child, f"{HALEY}hasKGFrameTypeDescription", ftype,
                     f"{XSD}string"),
                crit.triples(child),
                _t(nedge, RDF_TYPE, f"{HALEY}Edge_hasKGFrame"),
                _t(nedge, f"{VITAL}vitaltype", f"{HALEY}Edge_hasKGFrame"),
                _t(nedge, f"{VITAL}URIProp", nedge),
                _t(nedge, f"{VITAL}hasEdgeSource", parent),
                _t(nedge, f"{VITAL}hasEdgeDestination", child),
            ]
            block = "".join(buf)
            fh.write(block)
            n_triples += block.count("\n")

        # KG relations: entity -> entity directly, no frame in between.
        for ri, (src, dst, crit, rtype) in enumerate(relation_edges):
            rel = _uri("relation", ri)
            buf = [
                _t(rel, RDF_TYPE, f"{HALEY}Edge_hasKGRelation"),
                _t(rel, f"{VITAL}vitaltype", f"{HALEY}Edge_hasKGRelation"),
                _t(rel, f"{VITAL}URIProp", rel),
                _t(rel, f"{HALEY}hasKGRelationType", f"{BASE}:reltype:{rtype}"),
                _lit(rel, f"{HALEY}hasKGRelationTypeDescription", rtype, f"{XSD}string"),
                _t(rel, f"{VITAL}hasEdgeSource", ent(src)),
                _t(rel, f"{VITAL}hasEdgeDestination", ent(dst)),
                crit.triples(rel),
            ]
            block = "".join(buf)
            fh.write(block)
            n_triples += block.count("\n")
    finally:
        if fh:
            fh.close()

    nesting = nesting_ground_truth(nested, frame_edges)
    nested_matching = {k: _nested_matching_set(nested, p)
                       for k, p in NESTED_WALKS.items()}

    manifest = {
        "n_entities": n_entities,
        "n_frames": len(frame_edges),
        "n_nested_frames": len(nested),
        "n_relations": len(relation_edges),
        "n_triples": n_triples,
        # The skew that makes the traversal direction choice observable
        # (issues/090). `n_rare_entities` against n_entities is the ratio the
        # gate compares, so a test asserts against the fixture's own description
        # of itself rather than against a number someone typed.
        "rare_entity_fraction": rare_entity_fraction,
        "rare_entity_kind": (f"{BASE}:kind:{RARE_KIND}"
                             if rare_entity_fraction > 0 else None),
        "n_rare_entities": n_rare_entities,
        "triples_per_entity": round(n_triples / max(n_entities, 1), 1),
        "seed": seed,
        "fanout": fanout,
        "relation_fanout": relation_fanout,
        "entity_kinds": ENTITY_KINDS,
        "frame_types": FRAME_TYPES,
        "relation_types": RELATION_TYPES,
        "categories": [c for c, _w in CATEGORIES],
        "criteria_predicates": {
            "score": f"{HALEY}hasScore (xsd:integer, uniform [0,100))",
            "weight": f"{HALEY}hasWeight (xsd:double, uniform [0,1))",
            "occurred": f"{HALEY}hasOccurredAt (xsd:dateTime, 3-year window)",
            "label": f"{HALEY}hasLabel (xsd:string, 50 values)",
            "category": f"{HALEY}hasCategory (xsd:string, 8 weighted values)",
            "active": f"{HALEY}hasActive (xsd:boolean, p=0.2)",
            "tag": f"{HALEY}hasTag (uri, MULTI-VALUED, 1-4 of 6)",
        },
        "actual_matches": {
            "frames": tally(frame_edges),
            "relations": tally(relation_edges),
        },
        "graph_shape": {
            "model": "preferential attachment (hubs) + local ring (clustering)",
            "frames": graph_stats(frame_edges, n_entities, random.Random(seed + 3)),
            "relations": graph_stats(relation_edges, n_entities,
                                     random.Random(seed + 4)),
        },
        "value_distributions": {
            "score": "lognormal(mu=2.9, sigma=0.8), clipped to [0,100)",
            "weight": "Beta(2,5)",
            "occurred": "exponential recency bias, weekday- and hour-clustered",
            "label": "Pareto(1.2) over 50 labels",
            "category": "weighted, 32:24:16:12:8:4:3:1",
            "active": "Bernoulli(0.2)",
        },
        "nesting": nesting,
        "traversal": compute_ground_truth(
            frame_edges, relation_edges, n_entities, seed,
            nested_matching=nested_matching),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    dt = time.time() - t0
    print(f"✅ {n_entities:,} entities, {len(frame_edges):,} frames, "
          f"{len(nested):,} nested frames, {len(relation_edges):,} relations")
    print(f"   nesting: max depth {nesting['max_depth']}, "
          f"{len(nesting['deep_roots'])} chain(s) deeper than 5")
    print("   nested walks: " + ", ".join(
        f"{k.replace('frame_traversal_', '')}->{v['fraction']:.0%}"
        for k, v in nesting["walk_density"].items()))
    print(f"   {n_triples:,} triples ({manifest['triples_per_entity']} per entity) "
          f"in {shard_idx} shard(s), {dt:.1f}s")
    print(f"📄 manifest: {out_dir / 'manifest.json'}")
    gs = manifest["graph_shape"]["frames"]
    print(f"   in-degree: max={gs['in_degree']['max']} p99={gs['in_degree']['p99']} "
          f"p50={gs['in_degree']['p50']} gini={gs['in_degree']['gini']}")
    print(f"   out-degree: max={gs['out_degree']['max']} "
          f"mean={gs['out_degree']['mean']} gini={gs['out_degree']['gini']}")
    print(f"   clustering={gs['clustering_coefficient']} "
          f"mean_path={gs['mean_path_length_sampled']} (small-world: both)")
    print("   score >= : " + ", ".join(
        f"{k}->{v:,}" for k, v in manifest["actual_matches"]["frames"]["score_gte"].items()))
    print("   category : " + ", ".join(
        f"{k}->{v:,}" for k, v in manifest["actual_matches"]["frames"]["category_eq"].items()))
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entities", type=int, default=10000)
    ap.add_argument("--fanout", type=int, default=4,
                    help="connection frames out of each entity. 4 keeps a "
                         "FILTERED walk alive to depth 3: at ~50%% selectivity "
                         "a fan-out of 2 collapses to nothing by depth 2")
    ap.add_argument("--relation-fanout", type=int, default=2,
                    help="KG relations out of each entity")
    ap.add_argument("--seed", type=int, default=20260814)
    ap.add_argument("--shard-entities", type=int, default=5000)
    ap.add_argument("--rare-entity-fraction", type=float, default=0.0,
                    help="fraction of entities given a RARE sixth kind "
                         "(issues/090). 0 disables it, leaving emitted triples "
                         "byte for byte identical to the existing fixtures "
                         "(the manifest gains three descriptive keys). ~0.02 "
                         "gives a kind-constrained chain end far smaller than "
                         "any of the five uniform kinds, which is what makes "
                         "the traversal direction choice observable.")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    generate(Path(args.out), args.entities, args.fanout,
             args.relation_fanout, args.seed, args.shard_entities,
             rare_entity_fraction=args.rare_entity_fraction)
    return 0


if __name__ == "__main__":
    sys.exit(main())
