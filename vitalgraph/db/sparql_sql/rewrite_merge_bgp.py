"""Merge `Join(BGP, BGP)` into one BGP so join order is chosen across both.

Two BGPs joined on a shared variable mean exactly what one BGP containing all
their triples means — SPARQL's BGP matching is defined on the whole pattern, and
an inner join of two patterns is the join of their solution mappings. What the
split costs is not correctness but the ORDER: each BGP is emitted as its own
subquery with its own `reorder_joins` decision, so neither can be driven by a
selective leaf living in the other.

On the reference CONSTRUCT of `issues/178` that is the whole defect. The
traversal BGP orders itself from `q4` — every `KGFrame` — and enters
`{space}_frame_slot` by `frame_uuid`, producing 285,348 rows for a 425-row
answer. The anchor BGP, holding the trigram-filtered text leaf that matches 61
entities in 3 ms, joins from OUTSIDE and so cannot drive anything. Merged, the
text leaf is simply one of the candidate anchors, `reorder_joins` already
prefers it, and `frame_slot` is entered on `entity_uuid`:

    generated, split BGPs   3,081.7 ms   5,722,185 buffers   285,348 loops
    merged                      8.5 ms      15,268 buffers       425 loops

362x, same 425 rows, verified identical as a multiset against the generator's
own output.

This is deliberately NOT a CTE. Anchoring the arm in a `MATERIALIZED` CTE, in a
`NOT MATERIALIZED` one, and in a plain inline subquery all measured at 15,268
buffers — the fence is worth nothing. What matters is only that the two sets of
tables reach one ordering decision together.
"""

from __future__ import annotations

import logging
from typing import Optional

from .ir import (PlanV2, VarSlot, KIND_BGP, KIND_JOIN, KIND_EXTEND,
                 KIND_FILTER)

logger = logging.getLogger(__name__)


def _merge_two(left: PlanV2, right: PlanV2) -> Optional[PlanV2]:
    shared = set(left.var_slots) & set(right.var_slots)
    if not shared:
        # No shared variable is a cross product; one BGP or two makes no
        # difference to the order, and merging would only lose a boundary.
        return None

    merged = PlanV2(kind=KIND_BGP)

    for var, slot in left.var_slots.items():
        merged.var_slots[var] = VarSlot(name=var,
                                        positions=list(slot.positions or []),
                                        term_ref_id=slot.term_ref_id)
    # A shared variable may carry a term table on BOTH sides. Keeping both
    # would emit two term JOINs for one variable under two aliases, and the
    # second is dead weight the planner still has to execute.
    drop_term_aliases = set()
    for var, slot in right.var_slots.items():
        existing = merged.var_slots.get(var)
        if existing is None:
            merged.var_slots[var] = VarSlot(name=var,
                                            positions=list(slot.positions or []),
                                            term_ref_id=slot.term_ref_id)
            continue
        existing.positions.extend(slot.positions or [])
        if existing.term_ref_id is None:
            existing.term_ref_id = slot.term_ref_id
        elif slot.term_ref_id is not None and slot.term_ref_id != existing.term_ref_id:
            drop_term_aliases.add(slot.term_ref_id)

    seen = set()
    for table in list(left.tables) + list(right.tables):
        if table.ref_id in drop_term_aliases or table.alias in seen:
            continue
        seen.add(table.alias)
        merged.tables.append(table)

    merged.constraints = list(left.constraints) + list(right.constraints)
    merged.tagged_constraints = (list(left.tagged_constraints)
                                 + list(right.tagged_constraints))
    merged.leaf_terms = {**left.leaf_terms, **right.leaf_terms}
    merged.range_leaves = {**left.range_leaves, **right.range_leaves}

    # The equality the JOIN's ON clause used to carry. It has to become a
    # tagged constraint or the merged BGP is a cross product — the rows would
    # be wrong, not merely slow.
    for var in sorted(shared):
        lpos = left.var_slots[var].positions or []
        rpos = right.var_slots[var].positions or []
        if not lpos or not rpos:
            return None
        l_alias, l_col = lpos[0]
        r_alias, r_col = rpos[0]
        merged.tagged_constraints.append(
            (r_alias, f"{r_alias}.{r_col} = {l_alias}.{l_col}"))

    return merged


def _peel_extends(node: PlanV2, other: PlanV2):
    """Strip a chain of FILTER/EXTEND nodes, returning (inner, chain).

    A UNION branch of the `issues/178` shape arrives as
    `Filter(Extend(BGP))` — the FILTER is the residual text predicate and the
    EXTEND is `BIND(?x AS ?y)`. Peeling only EXTEND made this rewrite decline
    on the query it was written for, silently, while distribution above it
    fired and duplicated the pattern: all of the cost, none of the benefit.

    Both lift above an inner join. A FILTER reading only this side's variables
    commutes — `filter(A) JOIN B` and `filter(A JOIN B)` select the same rows —
    and nothing selective is deferred by doing so, because `filter_pushdown`
    has already pushed the trigram predicate down into the leaf as
    `object_uuid IN (SELECT term_uuid ...)`. BIND only ADDS a variable.

    Declines — `(None, [])` — when an EXTEND binds a variable the OTHER side
    also binds. Lifting it would then change which rows match, rather than
    merely where the value is computed.
    """
    chain = []
    cur = node
    while cur is not None and cur.kind in (KIND_EXTEND, KIND_FILTER):
        if (cur.kind == KIND_EXTEND and cur.extend_var
                and cur.extend_var in (other.var_slots or {})):
            return None, []
        chain.append(cur)
        cur = cur.children[0] if cur.children else None
    return cur, chain


def merge_bgp_joins(plan: PlanV2, aliases=None) -> PlanV2:
    """Rewrite every `Join(BGP, BGP)` below `plan` into a single BGP."""
    if plan is None:
        return plan
    from .plan_decisions import recorder_for
    _rec = recorder_for(aliases) if aliases is not None else None
    plan.children = [merge_bgp_joins(c, aliases) for c in (plan.children or [])]

    if plan.kind != KIND_JOIN or len(plan.children or []) != 2:
        return plan
    # A join marked as an existence test is emitted as `EXISTS (...)`; its two
    # sides are not one pattern and merging them would turn a semi-join into a
    # product.
    if (plan.hints or {}).get('semijoin'):
        if _rec: _rec.declined("merge_bgp", "join is marked as a semi-join")
        return plan
    left, right = plan.children
    # A UNION branch carrying `BIND(?x AS ?y)` reaches here as
    # `Extend(BGP)`, not `BGP` — which is how this rewrite first declined on
    # the very query it was written for, silently, while distribution above it
    # fired. BIND only ADDS a variable: it does not constrain matching, so the
    # chain lifts above the merged pattern unchanged.
    left_core, left_chain = _peel_extends(left, right)
    right_core, right_chain = _peel_extends(right, left)
    if left_core is None or right_core is None:
        if _rec: _rec.declined(
            "merge_bgp", "an EXTEND binds a variable the other side also binds")
        return plan
    if left_core.kind != KIND_BGP or right_core.kind != KIND_BGP:
        # THE decline that cost two rounds in `issues/178`: a UNION branch
        # arrives as `Filter(Extend(BGP))`, and requiring bare BGPs rejected
        # the query this was written for while distribution above it fired.
        if _rec: _rec.declined(
            "merge_bgp", "children are not both BGPs after peeling",
            left=left_core.kind, right=right_core.kind)
        return plan

    merged = _merge_two(left_core, right_core)
    _merged_tables = len(merged.tables) if merged is not None else 0
    if merged is None:
        if _rec: _rec.declined("merge_bgp", "no shared variable, or a shared "
                                            "variable had no position")
        return plan
    for node in reversed(left_chain + right_chain):
        node.children = [merged]
        merged = node
    # `_merged_tables`, not `len(merged.tables)`: by here `merged` may be the
    # outermost re-wrapped FILTER/EXTEND, whose `.tables` is empty. Reporting
    # that read "merged two BGPs into one: 0 tables" until the decision record
    # made it visible.
    logger.info("merged two BGPs into one: %d tables, order now chosen across "
                "both", _merged_tables)
    if _rec: _rec.fired("merge_bgp", "one ordering decision across both",
                        tables=_merged_tables)
    return merged
