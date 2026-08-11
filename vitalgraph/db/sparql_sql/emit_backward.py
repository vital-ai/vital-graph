"""Emit a negated traversal backward, as a set.

STATUS: WIRED as of `issues/059`. `emit_slice._try_candidate_driven` calls
`extract_negated_traversal` and `emit_candidate_ctes`, and `not_exists` runs
through it today — its plan contains the `cand0` CTE and answers in ~200 ms.

This header used to read "NOT WIRED", describing the two failed placements
below, and stayed that way after the third placement succeeded. It sent a reader
back to re-derive a solved problem in 2026-08 before anyone noticed the module
was live. The failure analysis below is still accurate and worth keeping; only
the status was wrong.

TWO BODY SHAPES REACH IT.

  * An EDGE CHAIN — `not_exists`. The negation tests a constrained leaf some
    hops away from the correlated variable, and the walk follows those hops.
  * ZERO HOPS with an UNBOUND OBJECT — `is_empty`, added 2026-08-10. The body is
    `?slot <valueProp> ?val`: the correlated variable IS the leaf's subject, and
    the negation only asks whether the predicate is present at all. `excl` is
    then one index range scan on (context, predicate) — "slots that hold a
    value" — and the rest of `emit_candidate_ctes` is reused unchanged, because
    the SHAPE is the same and only the seed differs.

      is_empty/Text   51,753 ms -> 328 ms,  3,302,262 buffers -> 25,351

    That number lands in the 205-337 ms band measured below for an empty answer,
    which is the point: `is_empty` returns nothing, and an empty answer is
    exactly what makes the candidate set empty and the walk free.

The KGQuery side had to change with it. `is_empty` emitted
`OPTIONAL { ?slot p ?v } FILTER(!BOUND(?v))`, which is the same question but
compiles to a LEFT JOIN with an IS NULL filter — not an `ExprExists`, so
`_foldable_exists_join` never saw it and this module was unreachable. Switching
the spelling ALONE measured >300 s, because the body then reached the forward
probe instead; the recogniser change and the spelling change only work as a
pair, and neither is a fix on its own.

Two placements were tried and measured. Both are CORRECT — a differential test
against the correlated form returned identical 300-row sets on a case
constructed to have a non-empty answer — and neither is faster.

**1. Inlined into the probe** as an `extra_cond`:

    per-probe cost   ~21  ->  ~69,928
    total estimate   6.5 billion

The subquery lands inside `SubPlan 2`, the per-anchor-row probe, and an
uncorrelated subquery nested inside a correlated one is not hoisted out of it —
PostgreSQL re-evaluates it per row.

**2. As a MATERIALIZED CTE scoped to phase 1**, with the probe testing
membership. This fixed the re-evaluation: the CTE is computed exactly once, cost
69,796. The query still times out, because the outer `Unique` is 95 million.

The reason is the part neither placement addresses: **the anchor still drives**.
Phase 1 scans 100,000 entities and probes each, and when the answer is empty
that scan exhausts no matter how cheap the probe becomes.

What is actually required
-------------------------
Phase 1 must be DRIVEN BY the walked-back set rather than filtered by it:

    FROM (walk back from the surviving leaves) AS candidates
    JOIN anchor ON anchor.subject = candidates.n

The hand-written form of that measures 205-337ms against >200s, and the reason
it wins is that when the negation excludes everything the candidate set is
EMPTY, so nothing is walked and nothing is scanned. A filter cannot reproduce
that; only choosing a different driver can.

That is a genuine alternative to `_emit_two_phase`, not a modification of it, and
it trades away the ordered-scan property two-phase relies on for O(page) — which
is only an acceptable trade when the answer is sparse. Hence the density gate in
`issues/059`.


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

    Two degenerate-looking cases are legitimate and both occur:

    * `leaf_obj is None` — the negation tests only that the predicate is PRESENT,
      whatever its value. `is_empty` is this: "the slot holds no text value at
      all", not "holds some particular value".
    * `hops == []` — the correlated variable IS the leaf's subject, so there is
      nothing to walk. Again `is_empty`: the body is `?slot <pred> ?val` and the
      outer query correlates on `?slot` directly.

    Neither weakens the set semantics. The walk still produces "the nodes the
    negation excludes"; with no hops that set is just the leaf subjects.
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
        obj = self.leaf_obj[:8] if self.leaf_obj else "*"
        return (f"Traversal(leaf=({self.leaf_pred[:8]},{obj}), "
                f"hops={len(self.hops)}, corr={self.correlated_var})")


def emit_backward_walk_cte(trav: Traversal, space_id: str, cte_name: str,
                           context_uuid: str) -> str:
    """A MATERIALIZED CTE holding the nodes the negation excludes.

    `WITH <name> AS MATERIALIZED (SELECT ... AS n ...)`, for a caller to test
    membership against. MATERIALIZED is not decoration: without it PostgreSQL 12+
    may inline the CTE back into the correlated probe that references it, which
    is precisely the arrangement measured at ~69,928 per probe against ~21.

    The walk starts at the constrained end — an index range scan on
    (predicate, object, context) — and each hop is a column predicate on
    `edge_type_uuid`, which is why `issues/060` is a prerequisite: without that
    column every hop needs a join back to a 24 GB quad table, 42s against 1.5s.
    """
    body = _walk_select(trav, space_id, context_uuid)
    return f"WITH {cte_name} AS MATERIALIZED (\n    {body}\n  )"


def _walk_select(trav: Traversal, space_id: str, context_uuid: str) -> str:
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

    if not trav.hops:
        # No hops: the correlated node IS the leaf's subject, so the excluded
        # set is just "subjects carrying this predicate". One index range scan
        # on (context, predicate) — no edges involved.
        where = [f"lf.predicate_uuid = '{trav.leaf_pred}'::uuid",
                 f"lf.context_uuid = '{context_uuid}'::uuid"]
        if trav.leaf_obj:
            where.append(f"lf.object_uuid = '{trav.leaf_obj}'::uuid")
        return (f"SELECT lf.subject_uuid AS n\n    FROM {t_quad} lf"
                f"\n    WHERE " + "\n      AND ".join(where))

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
    where = [f"lf.predicate_uuid = '{trav.leaf_pred}'::uuid",
             f"lf.context_uuid = '{context_uuid}'::uuid"]
    if trav.leaf_obj:
        where.append(f"lf.object_uuid = '{trav.leaf_obj}'::uuid")
    parts.append("WHERE " + " AND ".join(where))

    return "\n    ".join(parts)


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
        # No edges is not automatically unrecognisable: the correlated node can
        # BE the constrained subject, with nothing to walk. `is_empty` is that —
        # `?slot <valueProp> ?val`, correlating on ?slot.
        return _extract_value_absence(plan, aliases)

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


class Level:
    """One hop of the positive traversal, anchor-side first.

    `edge_type` is the hop; `dest_pred`/`dest_obj` are the type constraint on the
    node it lands on, which the backward walk has to re-apply — dropping it would
    admit nodes the forward form never reached.
    """

    def __init__(self, edge_type, dest_pred, dest_obj):
        self.edge_type = edge_type
        self.dest_pred = dest_pred
        self.dest_obj = dest_obj


def extract_positive_chain(plan, aliases):
    """The anchor -> ... -> node chain a BGP walks, anchor-side first.

    Returns None unless the BGP is a single chain of typed edge hops, each
    landing on a node with a type constraint. That is the shape the candidate
    driven form can invert; anything else is refused rather than approximated,
    because a backward walk that drops a constraint returns rows the forward form
    would not.
    """
    tables = getattr(plan, "tables", None) or []
    edges = [t for t in tables if getattr(t, "kind", None) == "edge"]
    if not edges:
        return None

    consts = _const_map(aliases)
    pred_of, obj_of, ctx_of = {}, {}, {}
    type_via, dest_typed, follows = {}, {}, {}

    for _owner, sql in (getattr(plan, "tagged_constraints", None) or []):
        m = re.search(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            pred_of[m.group(1)] = consts.get(m.group(2))
        m = re.search(r"(\w+)\.object_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            obj_of[m.group(1)] = consts.get(m.group(2))
        m = re.search(r"(\w+)\.context_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            ctx_of[m.group(1)] = consts.get(m.group(2))
        m = re.search(r"(\w+)\.edge_uuid\s*=\s*(\w+)\.subject_uuid", sql)
        if m:
            type_via[m.group(1)] = m.group(2)
        m = re.search(r"(\w+)\.subject_uuid\s*=\s*(\w+)\.dest_node_uuid", sql)
        if m:
            dest_typed[m.group(2)] = m.group(1)
        m = re.search(r"(\w+)\.source_node_uuid\s*=\s*(\w+)\.dest_node_uuid", sql)
        if m:
            follows[m.group(1)] = m.group(2)

    by_alias = {e.alias: e for e in edges}
    # The anchor-side hop is the one that follows nothing.
    roots = [e.alias for e in edges if e.alias not in follows]
    if len(roots) != 1:
        return None
    order, cur, seen = [], roots[0], set()
    nxt = {v: k for k, v in follows.items()}
    while cur and cur not in seen:
        seen.add(cur)
        order.append(cur)
        cur = nxt.get(cur)
    if len(order) != len(edges):
        return None

    levels = []
    for alias in order:
        tv = type_via.get(alias)
        etype = obj_of.get(tv) if tv else None
        dq = dest_typed.get(alias)
        if not etype or not dq:
            return None
        dp, do = pred_of.get(dq), obj_of.get(dq)
        if not dp or not do:
            return None
        levels.append(Level(str(etype), str(dp), str(do)))

    contexts = {v for v in ctx_of.values() if v}
    if len(contexts) != 1:
        return None
    return levels, str(next(iter(contexts)))


def _extract_value_absence(plan, aliases) -> Optional[Traversal]:
    """A zero-hop negation: `?x <pred> ?anything`, correlating on `?x`.

    The body `issues/072` needs. `is_empty` asks whether a slot holds a value at
    all, so the negated pattern binds a constant PREDICATE and leaves the object
    a variable, and the outer query correlates on the subject directly. There is
    no edge to walk back along, which is why the edge-chain recogniser above
    declines it — and why it then fell back to a forward probe costing 53 s
    where the set form costs a single index range scan.

    Deliberately strict, because everything this returns is emitted as different
    SQL for the same question:

    * exactly ONE quad table, so there is nothing else in the body whose meaning
      would be dropped by reducing it to a set of subjects. TERM tables are
      allowed alongside it: they are text/type resolution joins on the quad's
      own columns, present because the body binds a value variable, and they
      cannot change whether a matching triple EXISTS. Every constraint is still
      required to reference the quad alias, so a term table carrying a real
      filter would be rejected;
    * a constant predicate — without one the excluded set is "every subject",
      which is never what the caller meant;
    * the correlated variable bound to that table's `subject_uuid`.

    An object constant is ALLOWED but not required. With one this recognises
    `?x <pred> <value>` too, which is `not_has`'s body shape. That does not
    hijack `not_has`: the density gate in `_try_candidate_driven` declines it,
    because its negation excludes a few hundred of ~100,000 and the forward
    probe stops sooner. Correctness does not depend on that gate — both forms
    answer the same question — only the choice of the faster one does.
    """
    tables = getattr(plan, "tables", None) or []
    quads = [t for t in tables if getattr(t, "kind", None) == "quad"]
    others = [t for t in tables if getattr(t, "kind", None) not in ("quad", "term")]
    if len(quads) != 1 or others:
        return None
    alias = quads[0].alias

    # Nothing may constrain anything but the quad. A term table is only ever a
    # resolution join here, and if one ever carries a filter this rejects it
    # rather than silently dropping the filter's meaning.
    for _owner, sql in (getattr(plan, "tagged_constraints", None) or []):
        refs = set(re.findall(r"\b(\w+)\.\w+_uuid\b", sql))
        if refs - {alias}:
            return None

    consts = _const_map(aliases)
    pred = obj = ctx_uuid = None
    for _owner, sql in (getattr(plan, "tagged_constraints", None) or []):
        m = re.search(rf"{re.escape(alias)}\.predicate_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            pred = consts.get(m.group(1))
        m = re.search(rf"{re.escape(alias)}\.object_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            obj = consts.get(m.group(1))
        m = re.search(rf"{re.escape(alias)}\.context_uuid\s*=\s*__CONST_(\w+)__", sql)
        if m:
            ctx_uuid = consts.get(m.group(1))
    if not pred:
        return None

    corr = None
    for var, slot in (getattr(plan, "var_slots", None) or {}).items():
        for ref_id, col in (getattr(slot, "positions", None) or []):
            if ref_id == alias and col == "subject_uuid":
                corr = var
    if corr is None:
        return None

    return Traversal(str(pred), str(obj) if obj else None, [], corr,
                     str(ctx_uuid) if ctx_uuid else None)


def emit_candidate_ctes(trav: Traversal, levels, space_id: str,
                        context_uuid: str, name) -> tuple:
    """CTEs computing the anchor-side nodes that satisfy path-AND-negation.

    Returns `(with_clause, candidates_cte_name)`.

    Walks from the constrained end back to the anchor, re-applying each level's
    type constraint on the way. Dropping those would admit nodes the forward form
    never reached, which is the difference between an optimisation and a
    different query.

    Every CTE is MATERIALIZED. Without it PostgreSQL 12+ may inline them back
    into the outer query and rebuild the walk per anchor row, which is exactly
    the arrangement measured at ~69,928 per probe.

    The reason this wins where a filter cannot: when the negation excludes
    everything, `surviving` is EMPTY and every later CTE is empty, so no hop is
    walked and the anchor is never scanned. A filter still has to visit each
    anchor row to discover that none qualify.
    """
    t_quad = f"{space_id}_rdf_quad"
    t_edge = f"{space_id}_edge"
    ctx = context_uuid
    parts = []

    excl = name("excl")
    parts.append(
        f"{excl} AS MATERIALIZED (\n    {_walk_select(trav, space_id, ctx)}\n  )")

    deepest = levels[-1]
    surv = name("surv")
    parts.append(
        f"{surv} AS MATERIALIZED (\n"
        f"    SELECT q.subject_uuid AS n FROM {t_quad} q\n"
        f"    WHERE q.predicate_uuid = '{deepest.dest_pred}'::uuid\n"
        f"      AND q.object_uuid = '{deepest.dest_obj}'::uuid\n"
        f"      AND q.context_uuid = '{ctx}'::uuid\n"
        f"    EXCEPT SELECT n FROM {excl}\n  )")

    prev = surv
    # Walk back level by level, applying the type of the node each hop lands on.
    for i in range(len(levels) - 1, 0, -1):
        hop = levels[i].edge_type
        landing = levels[i - 1]
        step = name("bw")
        parts.append(
            f"{step} AS MATERIALIZED (\n"
            f"    SELECT DISTINCT e.source_node_uuid AS n FROM {prev} p\n"
            f"    JOIN {t_edge} e ON e.dest_node_uuid = p.n\n"
            f"      AND e.edge_type_uuid = '{hop}'::uuid\n"
            f"      AND e.context_uuid = '{ctx}'::uuid\n"
            f"    WHERE EXISTS (SELECT 1 FROM {t_quad} tq\n"
            f"      WHERE tq.subject_uuid = e.source_node_uuid\n"
            f"        AND tq.predicate_uuid = '{landing.dest_pred}'::uuid\n"
            f"        AND tq.object_uuid = '{landing.dest_obj}'::uuid\n"
            f"        AND tq.context_uuid = '{ctx}'::uuid)\n  )")
        prev = step

    cands = name("cand")
    parts.append(
        f"{cands} AS MATERIALIZED (\n"
        f"    SELECT DISTINCT e.source_node_uuid AS n FROM {prev} p\n"
        f"    JOIN {t_edge} e ON e.dest_node_uuid = p.n\n"
        f"      AND e.edge_type_uuid = '{levels[0].edge_type}'::uuid\n"
        f"      AND e.context_uuid = '{ctx}'::uuid\n  )")

    return "WITH " + ",\n  ".join(parts), cands
