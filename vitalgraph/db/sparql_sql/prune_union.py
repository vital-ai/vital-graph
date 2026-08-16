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

from .ir import (AliasGenerator, PlanV2, KIND_UNION, KIND_BGP, KIND_JOIN,
                 KIND_LEFT_JOIN, KIND_MINUS, KIND_GROUP, KIND_FILTER,
                 KIND_PROJECT, KIND_SLICE, KIND_ORDER, KIND_DISTINCT,
                 KIND_REDUCED, KIND_EXTEND)

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
    """Replace *target*'s fields with *source*'s, keeping object identity so
    parent references remain valid.

    Copies every dataclass field rather than enumerating them by hand. The
    hand-written version silently dropped any field added to the IR later:
    `leaf_terms` was lost exactly that way, and the symptom surfaced several
    layers off as a selectivity gate that could not read cardinality, with no
    error raised anywhere. A generic copy cannot go stale.
    """
    from dataclasses import fields
    for f in fields(source):
        if f.name == "kind" or not f.name.startswith("_"):
            setattr(target, f.name, getattr(source, f.name))
    target.path_meta = source.path_meta
    target.graph_uri = source.graph_uri


# ---------------------------------------------------------------------------
# Provably-empty queries (issues/073)
# ---------------------------------------------------------------------------

# Descending through these preserves "empty child => empty result".
#
# NOT in this set, and each for its own reason:
#   KIND_UNION      a sibling branch may still match
#   KIND_MINUS      subtracting nothing leaves the left side intact
#   KIND_LEFT_JOIN  handled specially — only the LEFT child is required; an
#                   OPTIONAL that matches nothing still yields its outer row
#   KIND_GROUP      an aggregate over zero rows still produces a row
#                   (`SELECT COUNT(*)` is 0, not empty), so emptiness does not
#                   propagate upward through it
_EMPTY_PROPAGATES = frozenset({
    KIND_JOIN, KIND_BGP, KIND_FILTER, KIND_PROJECT, KIND_SLICE, KIND_ORDER,
    KIND_DISTINCT, KIND_REDUCED, KIND_EXTEND,
})


def query_is_provably_empty(plan: PlanV2, aliases: AliasGenerator) -> bool:
    """True when a constant that does not exist in the term table is REQUIRED.

    An equality against a term that was never stored matches nothing, so the
    whole query matches nothing — and that can be known before running it.

    Without this the plan does the opposite of short-circuiting. The constant
    compiles to a scalar subquery over an empty `_const` CTE, so the comparison
    is NULL for every row; the planner cannot see that it is constant-false, and
    under the ordered-scan fence it walks the entire ordering index proving it.
    Measured on `eq`/DateTime at 100k: 40 s+ for an empty answer, against 0 ms
    for the same query shape when the constant resolves.

    That makes "search for a value that is not there" the WORST case, when it
    should be the cheapest — and searching for an absent value is not exotic, it
    is what a typo or an over-narrow filter produces.
    """
    unresolved = _unresolved_const_names(aliases)
    if not unresolved:
        return False
    dead = {f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}" for col in unresolved}
    return _required_subtree_is_dead(plan, dead)


# Comparisons where an ABSENT term means "this constraint does nothing", rather
# than "this constraint can never hold". Everything is DISTINCT FROM a missing
# term, so the row survives.
#
# `collect.py` emits exactly this for `GRAPH ?g`, and says why: SPARQL's GRAPH ?g
# ranges over the named graphs, so the default graph is EXCLUDED, and
# `IS DISTINCT FROM` is chosen over `!=` precisely so a missing default-graph
# term reads as "no exclusion" instead of filtering every row.
_NO_OP_WHEN_ABSENT = ("IS DISTINCT FROM",)


def _dead_constant_is_required(constraint: str, tok: str) -> bool:
    """Whether this constraint genuinely cannot hold without `tok`.

    The distinction the caller needs, and the one this function exists for:

        col = <missing>                  can never hold  -> required
        col IS DISTINCT FROM <missing>   always holds    -> NOT required

    Treating the second as required is a silent wrong answer, not a slow one:
    the query is rewritten to `LIMIT 0` and returns nothing, with no error.
    """
    idx = 0
    while True:
        i = constraint.find(tok, idx)
        if i == -1:
            return False
        before = constraint[:i].rstrip()
        # Look for a no-op operator immediately to the left, allowing for the
        # opening parenthesis of the scalar subquery the constant compiles to.
        head = before[:-1].rstrip() if before.endswith("(") else before
        if not any(head.upper().endswith(op) for op in _NO_OP_WHEN_ABSENT):
            return True
        idx = i + len(tok)


def _node_owns_dead_constant(plan: PlanV2, dead: Set[str]) -> bool:
    """Dead constant REQUIRED by THIS node's own constraints (not its children's).

    "Required" is load-bearing. An earlier version asked only whether a dead
    constant appeared anywhere in the constraint text, which made
    `IS DISTINCT FROM <missing>` look fatal when it is the opposite — every row
    satisfies it. Any query with a `GRAPH ?g` and a `default_graph` whose URI is
    not in the term table (an empty default graph is enough) was declared
    provably empty and rewritten to `LIMIT 0`.
    """
    for constraint in plan.constraints:
        if any(tok in constraint and _dead_constant_is_required(constraint, tok)
               for tok in dead):
            return True
    for _tag, constraint in plan.tagged_constraints:
        if any(tok in constraint and _dead_constant_is_required(constraint, tok)
               for tok in dead):
            return True
    return False


def _required_subtree_is_dead(plan: PlanV2, dead: Set[str], depth: int = 0) -> bool:
    if plan is None or depth > 24:
        return False
    if _node_owns_dead_constant(plan, dead):
        return True
    if plan.kind == KIND_LEFT_JOIN:
        # Only the left side is required; a dead OPTIONAL just never matches.
        kids = plan.children or []
        return bool(kids) and _required_subtree_is_dead(kids[0], dead, depth + 1)
    if plan.kind not in _EMPTY_PROPAGATES:
        return False
    return any(_required_subtree_is_dead(c, dead, depth + 1)
               for c in (plan.children or []))


# ---------------------------------------------------------------------------
# Tautological NOT EXISTS
# ---------------------------------------------------------------------------

def fold_dead_not_exists(plan: PlanV2, depth: int = 0) -> int:
    """Drop every ``FILTER NOT EXISTS`` whose body can never match.

    An EXISTS body that REQUIRES a term absent from the term table matches
    nothing for any outer row, so ``NOT EXISTS`` over it is a tautology and the
    filter is pure cost. Left in, it is expensive cost: the absent constant
    compiles to a scalar subquery over an empty `_const` CTE, so every
    comparison is NULL and the planner cannot fold it — it builds the correlated
    anti-join and evaluates it per candidate row.

    Measured on the frames list of a 1.1M-frame graph, where the "Assertion"
    tab asks for frames having NEITHER `hasKGFormType` NOR `hasFrameGraphURI`
    and neither predicate exists in that space at all:

        anchor + re-anchor                          0.4 ms
        anchor + re-anchor + 2 dead NOT EXISTS  4,506.1 ms

    Returns the number of filter expressions removed.

    Only a TOP-LEVEL conjunct is folded — an `ExprExists` that IS one of
    `filter_exprs`. One buried inside a larger boolean (`FILTER(?x || NOT
    EXISTS {...})`) would need the expression tree rewritten to TRUE and is
    left alone; it is correct, merely unoptimised.

    A non-negated `EXISTS` over a dead body is constant-FALSE, which makes the
    whole enclosing pattern empty. That is a larger rewrite than dropping a
    conjunct and is deliberately NOT done here; `query_is_provably_empty`
    covers the outer-constant form of the same idea.
    """
    from vitalgraph.db.jena_sparql.jena_types import ExprExists

    if plan is None or depth > 24:
        return 0

    removed = 0
    if plan.kind == KIND_FILTER and plan.filter_exprs:
        keep = []
        for expr in plan.filter_exprs:
            if (isinstance(expr, ExprExists) and expr.negated
                    and _exists_body_is_dead(expr)):
                removed += 1
                continue
            keep.append(expr)
        if removed:
            plan.filter_exprs = keep
            logger.debug("folded %d tautological NOT EXISTS", removed)
            if not keep and plan.children:
                # Nothing left to filter on: become the child, so the node does
                # not linger as an identity wrapper the emitters must carry.
                _replace_plan_in_place(plan, plan.children[0])

    for child in (plan.children or []):
        removed += fold_dead_not_exists(child, depth + 1)
    return removed


def _exists_body_is_dead(expr) -> bool:
    """True when this EXISTS body requires a constant that is not in the term
    table.

    Reads the body's OWN AliasGenerator: `prepare_exists_subplans` gives each
    body its own, because its constants are its own. Using the outer one here
    would compare column names from different namespaces and could call a live
    body dead — the one error this must never make.

    Returns False when the body was never prepared, which is the pre-existing
    fallback path (emit collects it inline) and carries no resolution info.
    """
    sub = getattr(expr, "prepared_plan", None)
    sub_aliases = getattr(expr, "prepared_aliases", None)
    if sub is None or sub_aliases is None:
        return False
    unresolved = _unresolved_const_names(sub_aliases)
    if not unresolved:
        return False
    dead = {f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}" for col in unresolved}
    return _required_subtree_is_dead(sub, dead)
