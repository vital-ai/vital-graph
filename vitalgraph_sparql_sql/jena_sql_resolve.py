"""
Pass 2: RESOLVE — Assign concrete aliases, column names, and ON clauses.

Walks the RelationPlan tree produced by Pass 1 and resolves all VarSlot
columns so that Pass 3 (emit) can render final SQL.
"""

from __future__ import annotations

from typing import List

from .jena_sql_ir import AliasGenerator, RelationPlan, VarSlot


def resolve(plan: RelationPlan, space_id: str, aliases: AliasGenerator) -> RelationPlan:
    """Resolve a plan tree: assign final aliases, column names, ON clauses."""
    if plan.kind == "bgp":
        _resolve_bgp(plan)
        return plan
    elif plan.kind == "null":
        return plan
    elif plan.kind == "table":
        return plan
    elif plan.kind == "path":
        return plan
    elif plan.kind in ("join", "left_join"):
        return _resolve_join(plan, space_id, aliases)
    elif plan.kind == "union":
        return _resolve_union(plan, space_id, aliases)
    elif plan.kind == "minus":
        return _resolve_minus(plan, space_id, aliases)
    else:
        # Modifiers (filter, project, etc.) just resolve their single child
        if plan.children:
            plan.children = [resolve(c, space_id, aliases) for c in plan.children]
            # Inherit var_slots from child if this plan has none
            if not plan.var_slots and plan.children:
                plan.var_slots = dict(plan.children[0].var_slots)
        else:
            _resolve_bgp(plan)
        return plan


def _resolve_bgp(plan: RelationPlan):
    """Resolve VarSlot columns for a flat BGP plan."""
    for var, slot in plan.var_slots.items():
        if slot.term_ref_id:
            slot.uuid_col = f"{slot.positions[0][0]}.{slot.positions[0][1]}"
            slot.text_col = f"{slot.term_ref_id}.term_text"
            slot.type_col = f"{slot.term_ref_id}.term_type"


def _resolve_join(plan: RelationPlan, space_id: str, aliases: AliasGenerator) -> RelationPlan:
    """Resolve JOIN / LEFT JOIN: each child becomes a subquery."""
    left = resolve(plan.children[0], space_id, aliases)
    right = resolve(plan.children[1], space_id, aliases)

    l_alias = aliases.next("j")
    r_alias = aliases.next("j")

    left_vars = set(_plan_vars(left))
    right_vars = set(_plan_vars(right))
    shared = left_vars & right_vars
    all_vars = left_vars | right_vars

    # Build new var_slots referencing the subquery aliases
    new_slots = {}
    for v in all_vars:
        src = l_alias if v in left_vars else r_alias
        slot = VarSlot(name=v)
        slot.uuid_col = f"{src}.{v}__uuid"
        slot.text_col = f"{src}.{v}"
        slot.type_col = f"{src}.{v}__type"
        slot.partial = (plan.kind == "left_join" and v not in left_vars)
        new_slots[v] = slot

    plan.children = [left, right]
    plan.var_slots = new_slots
    # Store join metadata for emit
    plan._join_meta = {  # type: ignore[attr-defined]
        "l_alias": l_alias,
        "r_alias": r_alias,
        "shared": shared,
        "left_vars": left_vars,
        "right_vars": right_vars,
    }
    return plan


def _resolve_union(plan: RelationPlan, space_id: str, aliases: AliasGenerator) -> RelationPlan:
    """Resolve UNION: each child subquery, padded with NULL for missing vars."""
    left = resolve(plan.children[0], space_id, aliases)
    right = resolve(plan.children[1], space_id, aliases)

    left_vars = set(_plan_vars(left))
    right_vars = set(_plan_vars(right))
    all_vars = sorted(left_vars | right_vars)

    u_alias = aliases.next("u")

    new_slots = {}
    for v in all_vars:
        slot = VarSlot(name=v)
        slot.uuid_col = f"{u_alias}.{v}__uuid"
        slot.text_col = f"{u_alias}.{v}"
        slot.type_col = f"{u_alias}.{v}__type"
        new_slots[v] = slot

    plan.children = [left, right]
    plan.var_slots = new_slots
    plan._union_meta = {  # type: ignore[attr-defined]
        "u_alias": u_alias,
        "all_vars": all_vars,
        "left_vars": left_vars,
        "right_vars": right_vars,
    }
    return plan


def _resolve_minus(plan: RelationPlan, space_id: str, aliases: AliasGenerator) -> RelationPlan:
    """Resolve MINUS (EXCEPT)."""
    left = resolve(plan.children[0], space_id, aliases)
    right = resolve(plan.children[1], space_id, aliases)

    left_vars = set(_plan_vars(left))
    right_vars = set(_plan_vars(right))
    # SPARQL MINUS output has same variables as left side only
    out_vars = sorted(left_vars)

    m_alias = aliases.next("m")
    new_slots = {}
    for v in out_vars:
        slot = VarSlot(name=v)
        slot.text_col = f"{m_alias}.{v}"
        slot.uuid_col = f"{m_alias}.{v}"
        slot.type_col = f"{m_alias}.{v}"
        new_slots[v] = slot

    plan.children = [left, right]
    plan.var_slots = new_slots
    plan._minus_meta = {  # type: ignore[attr-defined]
        "m_alias": m_alias,
        "left_vars": left_vars,
        "right_vars": right_vars,
    }
    return plan


def _plan_vars(plan: RelationPlan) -> List[str]:
    """Get all variable names a plan exposes."""
    if plan.select_vars is not None:
        return list(plan.select_vars)
    vars = list(plan.var_slots.keys())
    if plan.extend_exprs:
        for v in plan.extend_exprs:
            if v not in vars:
                vars.append(v)
    return vars
