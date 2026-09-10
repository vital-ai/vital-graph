"""Distribute a JOIN over a UNION so each branch gets an INDEXABLE join.

`Join(Union(A, B), C)` is emitted today as one join whose condition must hold
for solutions from EITHER branch. The branches bind different variables, so the
condition is null-tolerant:

    ON (j0.v8__uuid IS NULL OR j0.v8__uuid = j1.v15__uuid)
   AND (j0.v10__uuid IS NULL OR j0.v10__uuid = j1.v13__uuid)

That is CORRECT — SPARQL says an unbound variable is compatible with anything —
and it is unindexable. PostgreSQL cannot drive `C` from the branch's bindings,
so it computes `C` in full and filters afterwards.

`issues/183` measured what that costs on the reference happy-frame CONSTRUCT.
The text filter already anchors its own branch correctly (`reorder_bgp` picks
the ILIKE leaf as chain root and `emit_bgp` fences it with `OFFSET 0`), so each
branch yields 61 entities cheaply — and then the entity set DIES at the join,
because a null-tolerant predicate cannot carry it into the traversal:

    driving from the matched entities (hand-written)        307 buffers
    the generated null-tolerant join                  5,151,495 buffers

Distributing fixes both halves at once:

    Union(Join(A, C), Join(B, C))

Each arm's condition is a plain equality on the variables that arm actually
binds, so it is indexable and drives from the small side. And every variable of
`C` is bound in every arm, which removes the second defect `issues/180`
records — 212 of 425 rows returning NULL for `?sourceSlotEntity` because the
projection took the union side of a null-tolerant join.

WHY IT IS SOUND. Join distributes over union in the SPARQL algebra exactly as
in relational algebra: a solution of `Join(Union(A,B), C)` comes from a
compatible pair with a member of A or of B, which is the definition of the
union of the two joins. `C` is evaluated twice, which is the cost — and it is
paid against a driving set that is now small, which is the point.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Optional, Set

from .ir import PlanV2, KIND_BGP, KIND_JOIN, KIND_UNION
from .var_scope import compute_scope

logger = logging.getLogger(__name__)

_ALIAS_RE = re.compile(r"\b([a-z][a-z0-9_]*)\.([a-z_]+)\b")


def _aliases_of(plan: PlanV2, out: Set[str]) -> Set[str]:
    for t in (plan.tables or []):
        out.add(t.alias)
    for c in (plan.children or []):
        _aliases_of(c, out)
    return out


def _clone_subtree(plan: PlanV2, aliases):
    """Deep-copy `plan`, renaming every table alias to a fresh one.

    The rename has to reach three places, and missing any one produces SQL that
    references an alias that is not in scope:

      * `TableRef.alias` / `.ref_id`,
      * `var_slots[...].positions`, which are `(ref_id, column)` pairs,
      * the CONSTRAINT STRINGS, where aliases appear as `q5.subject_uuid`.
    """
    clone = copy.deepcopy(plan)
    mapping = {a: aliases.next("du") for a in sorted(_aliases_of(clone, set()))}

    def rename_sql(sql: str) -> str:
        return _ALIAS_RE.sub(
            lambda m: (f"{mapping[m.group(1)]}.{m.group(2)}"
                       if m.group(1) in mapping else m.group(0)), sql)

    def walk(p: PlanV2) -> None:
        for t in (p.tables or []):
            if t.alias in mapping:
                t.ref_id = t.alias = mapping[t.alias]
            if getattr(t, "join_col", None):
                t.join_col = rename_sql(t.join_col)
        for slot in (p.var_slots or {}).values():
            slot.positions = [(mapping.get(r, r), c) for r, c in slot.positions]
        if p.tagged_constraints:
            p.tagged_constraints = [(mapping.get(o, o), rename_sql(s))
                                    for o, s in p.tagged_constraints]
        if p.constraints:
            p.constraints = [rename_sql(s) for s in p.constraints]
        # ALSO alias-keyed, and missing them is what made the cloned arm return
        # ZERO rows: `leaf_terms` and `range_leaves` are keyed by
        # `(alias, column)`, so a clone that renames only the tables and the
        # constraint strings leaves every lookup pointing at the ORIGINAL arm's
        # aliases. Everything that reads them — the traversal gate, the
        # slot-type constants, the range anchor — then answers for the wrong
        # subtree.
        for attr in ("leaf_terms", "range_leaves"):
            m = getattr(p, attr, None)
            if m:
                setattr(p, attr, {(mapping.get(a, a), c): v
                                  for (a, c), v in m.items()})
        for c in (p.children or []):
            walk(c)

    walk(clone)
    return clone, mapping


def _rename_sql_with(sql: str, mapping) -> str:
    return _ALIAS_RE.sub(
        lambda m: (f"{mapping[m.group(1)]}.{m.group(2)}"
                   if m.group(1) in mapping else m.group(0)), sql)


def _renamed_node(node: PlanV2, mapping) -> PlanV2:
    """Rename `C`'s aliases where the JOIN node itself refers to them."""
    n = copy.copy(node)
    n.tagged_constraints = [(mapping.get(o, o), _rename_sql_with(s, mapping))
                            for o, s in (node.tagged_constraints or [])]
    n.constraints = [_rename_sql_with(s, mapping)
                     for s in (node.constraints or [])]
    if node.var_slots:
        n.var_slots = {}
        for k, v in node.var_slots.items():
            v2 = copy.copy(v)
            v2.positions = [(mapping.get(r, r), c) for r, c in (v.positions or [])]
            n.var_slots[k] = v2
    for attr in ("leaf_terms", "range_leaves"):
        m = getattr(node, attr, None)
        if m:
            setattr(n, attr, {(mapping.get(a, a), c): val
                              for (a, c), val in m.items()})
    return n


def _branches_bind_differently(union: PlanV2) -> bool:
    """Do the branches bind different variables?

    If they bind the same set, the join condition is already a plain equality
    and distributing would duplicate `C` for nothing.
    """
    if len(union.children or []) < 2:
        return False
    scopes = [compute_scope(c).all_visible for c in union.children]
    return any(s != scopes[0] for s in scopes[1:])


def distribute_join_over_union(plan: PlanV2, aliases) -> PlanV2:
    """Rewrite `Join(Union(...), C)` to `Union(Join(branch, C), ...)`."""
    if plan is None:
        return plan
    plan.children = [distribute_join_over_union(c, aliases)
                     for c in (plan.children or [])]

    if plan.kind != KIND_JOIN or len(plan.children or []) != 2:
        return plan

    left, right = plan.children
    for union, other, union_first in ((left, right, True), (right, left, False)):
        if union.kind != KIND_UNION or len(union.children or []) < 2:
            continue
        if not _branches_bind_differently(union):
            continue
        # `other` is duplicated once per branch, so keep this to the shape the
        # measurement covers: a single BGP. A large subtree copied per branch is
        # a different trade and has not been priced.
        if other.kind != KIND_BGP:
            continue

        arms = []
        for i, branch in enumerate(union.children):
            # Copy the ORIGINAL join node rather than building a bare one: it
            # carries the var_slots and constraints that describe how the union
            # side connects to `C`, and a fresh node drops them.
            j = copy.copy(plan)
            # A DEEP COPY, but the aliases are NOT renamed.
            #
            # Renaming was the first attempt and it produced an arm that
            # matched nothing: the aliases appear in var_slots, in the
            # constraint strings, in `leaf_terms`, in `range_leaves`, and in
            # the parent join node, and every one that is missed leaves part of
            # the arm pointing at the other arm's tables.
            #
            # It is also unnecessary. A SQL alias only has to be unique within
            # one SELECT scope, and the arms are separate SELECTs under
            # UNION ALL — so both may use `q5`. The copy exists purely so the
            # later in-place rewrites cannot mutate one arm through the other.
            side = other if i == 0 else copy.deepcopy(other)
            j.children = [branch, side] if union_first else [side, branch]
            arms.append(j)
        out = PlanV2(kind=KIND_UNION)
        out.children = arms
        logger.info("distributed a join over a %d-branch union: each arm now "
                    "joins on the variables that branch binds", len(arms))
        return out
    return plan
