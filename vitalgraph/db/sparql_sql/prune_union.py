"""Prune dead UNION branches whose constants did not resolve to UUIDs.

After materialize_constants(), some constant placeholders remain unresolved
(the URI does not exist in the term table). Any BGP constraint referencing
such a placeholder will match 0 rows, so the entire UNION branch is dead
and can be removed from the IR tree before SQL emission.

This eliminates unnecessary UNION ALL branches in the generated SQL,
dramatically reducing PostgreSQL planning time for queries with entity
subtype UNIONs (e.g. KGEntity | KGNewsEntity | KGProductEntity | KGWebEntity)
where only one subtype exists in the space.
"""

from __future__ import annotations

import logging
from typing import Set

from .ir import AliasGenerator, PlanV2, KIND_UNION, KIND_BGP, KIND_JOIN

logger = logging.getLogger(__name__)

_CONST_PREFIX = "__CONST_"
_CONST_SUFFIX = "__"


def _unresolved_const_names(aliases: AliasGenerator) -> Set[str]:
    """Return the set of constant column names (e.g. 'c_3') that did NOT
    resolve to a UUID during materialize_constants()."""
    unresolved = set()
    for (_text, _ttype), col_name in aliases.constants.items():
        if col_name not in aliases.resolved_constants:
            unresolved.add(col_name)
    return unresolved


def _branch_has_unresolved_constant(plan: PlanV2, dead_tokens: Set[str]) -> bool:
    """Return True if any constraint in *plan* (recursively) references
    a constant placeholder token that is in *dead_tokens*."""
    # Check constraints on this node
    for constraint in plan.constraints:
        for token in dead_tokens:
            if token in constraint:
                return True

    # Check tagged_constraints too (they mirror constraints but with table tag)
    for _tag, constraint in plan.tagged_constraints:
        for token in dead_tokens:
            if token in constraint:
                return True

    # Recurse into children
    for child in plan.children:
        if _branch_has_unresolved_constant(child, dead_tokens):
            return True

    return False


def prune_dead_union_branches(plan: PlanV2, aliases: AliasGenerator) -> PlanV2:
    """Walk the IR tree and remove UNION children whose constraints reference
    unresolved constants. Returns the (possibly modified) plan.

    If a UNION node loses one child, it is replaced by the surviving child.
    If both children are dead (should not happen in practice), the node is
    left unchanged as a safety measure.
    """
    unresolved = _unresolved_const_names(aliases)
    if not unresolved:
        return plan

    # Build the set of placeholder tokens to search for in constraints
    dead_tokens = {f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}" for col in unresolved}

    pruned_count = _prune_recursive(plan, dead_tokens)
    if pruned_count > 0:
        dead_uris = []
        for (text, _ttype), col_name in aliases.constants.items():
            if col_name in unresolved:
                # Shorten the URI for logging
                short = text.rsplit('#', 1)[-1] if '#' in text else text.rsplit('/', 1)[-1]
                dead_uris.append(short)
        logger.info("Pruned %d dead UNION branch(es) — absent types: %s",
                     pruned_count, ", ".join(sorted(dead_uris)))

    return plan


def _prune_recursive(plan: PlanV2, dead_tokens: Set[str]) -> int:
    """Recursively prune dead UNION children. Returns total branches pruned."""
    pruned = 0

    # First, recurse into all children (bottom-up so inner UNIONs are pruned first)
    for i, child in enumerate(plan.children):
        pruned += _prune_recursive(child, dead_tokens)

    # Now handle UNION nodes at this level
    if plan.kind == KIND_UNION and len(plan.children) == 2:
        left_dead = _branch_has_unresolved_constant(plan.children[0], dead_tokens)
        right_dead = _branch_has_unresolved_constant(plan.children[1], dead_tokens)

        if left_dead and not right_dead:
            # Replace this UNION with the surviving right child
            survivor = plan.children[1]
            _replace_plan_in_place(plan, survivor)
            pruned += 1
        elif right_dead and not left_dead:
            # Replace this UNION with the surviving left child
            survivor = plan.children[0]
            _replace_plan_in_place(plan, survivor)
            pruned += 1
        elif left_dead and right_dead:
            # Both dead — leave unchanged (safety: let SQL return 0 rows naturally)
            logger.warning("Both UNION branches are dead — leaving unchanged")

    return pruned


def _replace_plan_in_place(target: PlanV2, source: PlanV2) -> None:
    """Replace *target*'s fields with *source*'s fields, keeping the same
    object identity (so parent references remain valid)."""
    target.kind = source.kind
    target.tables = source.tables
    target.var_slots = source.var_slots
    target.constraints = source.constraints
    target.tagged_constraints = source.tagged_constraints
    target.children = source.children
    target.project_vars = source.project_vars
    target.limit = source.limit
    target.offset = source.offset
    target.order_conditions = source.order_conditions
    target.filter_exprs = source.filter_exprs
    target.extend_var = source.extend_var
    target.extend_expr = source.extend_expr
    target.group_vars = source.group_vars
    target.aggregates = source.aggregates
    target.having_exprs = source.having_exprs
    target.left_join_exprs = source.left_join_exprs
    target.values_vars = source.values_vars
    target.values_rows = source.values_rows
    target.path_meta = source.path_meta
    target.graph_uri = source.graph_uri
