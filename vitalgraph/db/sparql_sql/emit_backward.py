"""Emit a negated traversal backward, as a set. NOT WIRED — see below.

STATUS: written, verified correct, and deliberately NOT connected, because
placing the set form where it fits made the plan WORSE. Kept because the
recogniser is the hard part and is right; what is wrong is where the condition
was put.

What was tried
--------------
The condition was emitted as an `extra_cond` on the two-phase probe, replacing
the correlated `NOT EXISTS`. That is correct — a differential test against the
correlated form returned identical 300-row sets on a case with a non-empty
answer — and it is slower:

    per-probe cost   ~21  ->  ~69,928
    total estimate   6.5 billion

because the subquery lands INSIDE `SubPlan 2`, the per-anchor-row probe, so
PostgreSQL evaluates it per row instead of once. An uncorrelated subquery nested
inside a correlated one does not get hoisted out of it.

What is actually required
-------------------------
The set has to be computed at the TOP level and drive the query, not sit inside
the probe:

    WITH excluded AS (<walk back from the constrained leaf>)
    ... anchor ... WHERE frame NOT IN (SELECT n FROM excluded)

which means replacing the anchor-and-probe structure rather than adding a
condition to it — the whole-query restructure `issues/059` describes. The
hand-written form of exactly that measures 205-337ms against a >200s timeout, so
the win is real; only this placement of it is not.


The rewrite `issues/059` asks for. The engine answers `not_exists` by scanning
every anchor row and probing forward from each; the backward form starts at the
negation's constrained end, filters there, and walks back once.

Measured on `sp_lead_synth_100k`, 25-row page:

    negation excludes everything (answer empty)     205-337 ms   vs  >200 s
    negation excludes nothing (answer 100,000)      22-27 s      vs  fast forward

Both numbers matter. The backward form does work proportional to the **answer**,
the forward probe does work proportional to finding **one page**, so this is only
a win when the answer is sparse. `not_has` and `not_has_any` already answer in
59-226 ms forward precisely because their answers are dense — firing this
unconditionally would regress the four cells `issues/057` fixed.

Correctness note that is easy to get wrong
------------------------------------------
The set difference happens at the FRAME level, not the entity level.

    WRONG:  entities-with-path  EXCEPT  entities-with-path-and-slot
    RIGHT:  frames-of-type      EXCEPT  frames-that-have-the-slot
            then walk back from what survives

An entity with two frames, one carrying the slot and one not, still satisfies
"there exists a frame with no such slot" — the entity-level difference drops it.
The frame-level form is also faster, because filtering at the constrained end
empties the intermediate set before any walking happens.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

_CORE = "http://vital.ai/ontology/vital-core#"


class Traversal:
    """A recognised negated traversal, in the terms the emitter needs.

    `leaf` is the constrained end — the (predicate, object) the negation tests
    for. `hops` are the edge types between that end and the correlated variable,
    ordered from the leaf outwards, which is the direction they will be walked.
    """

    def __init__(self, leaf_pred: str, leaf_obj: str, hops: List[str],
                 correlated_var: str, context_uuid: str):
        self.leaf_pred = leaf_pred
        self.leaf_obj = leaf_obj
        self.hops = hops
        self.correlated_var = correlated_var
        # Taken from the traversal's OWN constraints rather than from a graph
        # lock: a KGQuery uses an explicit GRAPH clause, so `graph_lock_uri` is
        # None and the context lives on each quad and edge constraint. Reading
        # it from the body also guarantees the rewritten form is scoped to the
        # same graph the original was, rather than to whatever the query as a
        # whole happened to be locked to.
        self.context_uuid = context_uuid

    def __repr__(self):
        return (f"Traversal(leaf=({self.leaf_pred[:8]},{self.leaf_obj[:8]}), "
                f"hops={len(self.hops)}, corr={self.correlated_var})")


def emit_backward_set_condition(trav: Traversal, space_id: str,
                                corr_col: str, context_uuid: str) -> str:
    """SQL for "this node is not one the negation excludes", as a SET.

    The correlated form asks, once per anchor row, "walk from this frame and see
    if a matching leaf exists". Since the body correlates on nothing but that one
    variable, it is equivalent to membership in a set that does not depend on the
    row at all:

        NOT EXISTS { frame --edge--> leaf }   ==   frame NOT IN {frames with leaf}

    which PostgreSQL builds once as a hash and probes in O(1) per row, instead of
    re-walking the traversal 100,000 times.

    `NOT IN` rather than `NOT EXISTS` deliberately: `source_node_uuid` is NOT
    NULL, so the usual NOT IN null trap does not apply, and the uncorrelated form
    is what lets the subquery be evaluated once. A correlated NOT EXISTS here
    would be pulled back into a per-row probe, which is the thing being removed.

    The walk starts at the constrained end — an index range scan on
    (predicate, object, context) — and each hop is a plain column predicate on
    `edge_type_uuid`, which is why `issues/060` is a prerequisite: without that
    column each hop needs a join back to a 24 GB quad table, measured at 42s
    against 1.5s.
    """
    t_quad = f"{space_id}_rdf_quad"
    t_edge = f"{space_id}_edge"

    parts = [
        f"SELECT e0.source_node_uuid AS n",
        f"FROM {t_quad} lf",
        f"JOIN {t_edge} e0 ON e0.dest_node_uuid = lf.subject_uuid"
        f" AND e0.edge_type_uuid = '{trav.hops[0]}'::uuid"
        f" AND e0.context_uuid = '{context_uuid}'::uuid",
    ]
    for i, hop in enumerate(trav.hops[1:], start=1):
        parts.append(
            f"JOIN {t_edge} e{i} ON e{i}.dest_node_uuid = e{i-1}.source_node_uuid"
            f" AND e{i}.edge_type_uuid = '{hop}'::uuid"
            f" AND e{i}.context_uuid = '{context_uuid}'::uuid")
    # Project the outermost hop's source, which is the node the outer query
    # correlates on.
    last = len(trav.hops) - 1
    parts[0] = f"SELECT e{last}.source_node_uuid AS n"
    parts.append(
        f"WHERE lf.predicate_uuid = '{trav.leaf_pred}'::uuid"
        f" AND lf.object_uuid = '{trav.leaf_obj}'::uuid"
        f" AND lf.context_uuid = '{context_uuid}'::uuid")

    return f"{corr_col} NOT IN (\n    " + "\n    ".join(parts) + "\n  )"


def _const_map(aliases) -> dict:
    """__CONST_x__ column name -> resolved uuid string."""
    return dict(getattr(aliases, "resolved_constants", None) or {})


def extract_negated_traversal(plan, aliases) -> Optional[Traversal]:
    """Read a NOT EXISTS body as (constrained leaf, hop chain, correlation).

    Recognises exactly one shape, and returns None for anything else — the
    conservative answer, since emitting a backward form for a body this did not
    understand would change which rows come back:

        <leaf> <pred> <obj>                     the constrained end
        <edge> vitaltype <edge type>            one or more typed hops
        <edge> hasEdgeDestination <leaf>
        <edge> hasEdgeSource <outer variable>   the correlation

    Everything is read from `tagged_constraints` rather than from the SPARQL,
    because by this point the edge-table rewrite has already replaced the
    hasEdgeSource/hasEdgeDestination quad pairs with edge-table joins, and the
    constraints are where that structure now lives.
    """
    if plan is None or getattr(plan, "kind", None) != "bgp":
        return None

    tables = getattr(plan, "tables", None) or []
    edges = [t for t in tables if getattr(t, "kind", None) == "edge"]
    if not edges:
        return None

    consts = _const_map(aliases)

    # alias -> constraints we care about
    pred_of: dict = {}
    obj_of: dict = {}
    edge_type_via: dict = {}
    dest_of: dict = {}
    src_join: dict = {}
    ctx_of: dict = {}

    for owner, sql in (getattr(plan, "tagged_constraints", None) or []):
        m = re.search(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            pred_of[m.group(1)] = consts.get(m.group(2))
        m = re.search(r"(\w+)\.object_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            obj_of[m.group(1)] = consts.get(m.group(2))
        m = re.search(r"(\w+)\.edge_uuid\s*=\s*(\w+)\.subject_uuid", sql)
        if m:
            edge_type_via[m.group(1)] = m.group(2)
        m = re.search(r"(\w+)\.subject_uuid\s*=\s*(\w+)\.dest_node_uuid", sql)
        if m:
            dest_of[m.group(2)] = m.group(1)
        m = re.search(r"(\w+)\.source_node_uuid\s*=\s*(\w+)\.dest_node_uuid", sql)
        if m:
            src_join[m.group(1)] = m.group(2)
        m = re.search(r"(\w+)\.context_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            ctx_of[m.group(1)] = consts.get(m.group(2))

    # The hop chain, ordered from the leaf outwards. With one edge this is
    # trivial; with several, each edge's source is the next edge's destination.
    ordered: List = []
    by_alias = {e.alias: e for e in edges}
    # start at the edge whose dest carries the leaf quad
    start = None
    for e in edges:
        if dest_of.get(e.alias):
            start = e
            break
    if start is None:
        return None
    cur = start
    seen = set()
    while cur is not None and cur.alias not in seen:
        seen.add(cur.alias)
        ordered.append(cur)
        nxt_alias = src_join.get(cur.alias)
        cur = by_alias.get(nxt_alias) if nxt_alias else None
    if len(ordered) != len(edges):
        return None          # not a single chain

    hops: List[str] = []
    for e in ordered:
        tv = edge_type_via.get(e.alias)
        if not tv:
            return None
        etype = obj_of.get(tv)
        if not etype:
            return None
        hops.append(etype)

    leaf_alias = dest_of.get(ordered[0].alias)
    leaf_pred = pred_of.get(leaf_alias)
    leaf_obj = obj_of.get(leaf_alias)
    if not leaf_pred or not leaf_obj:
        return None

    slots = getattr(plan, "var_slots", None) or {}
    corr = None
    for var, slot in slots.items():
        for ref_id, col in (getattr(slot, "positions", None) or []):
            if ref_id == ordered[-1].alias and col == "source_node_uuid":
                corr = var
    if corr is None:
        return None

    # The context is NOT taken from here. A prepared EXISTS body carries no
    # context constraint of its own — it inherits the graph through the
    # correlation to the outer row — so requiring one here rejected every body,
    # including the one this rewrite exists for. The caller supplies it from the
    # outer bgp, which does constrain the graph explicitly.
    contexts = {v for v in ctx_of.values() if v}
    return Traversal(str(leaf_pred), str(leaf_obj), hops, corr,
                     str(next(iter(contexts))) if contexts else None)
