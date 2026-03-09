"""
Variable Scope Model — tracks which SPARQL variables are visible at each
point in the plan tree.

SPARQL has specific scoping rules that differ from SQL:
  - BIND/EXTEND introduces a variable that's visible to subsequent patterns
  - GROUP BY restricts visibility to grouped vars + aggregates
  - UNION: a variable is in-scope if it's in any branch (but may be NULL)
  - EXISTS: outer variables are correlated but inner-only vars are not visible
  - OPTIONAL/LEFT JOIN: right-side vars are in-scope but may be NULL

VarScope computes variable visibility by walking the PlanV2 tree bottom-up,
mirroring Jena's VarFinder algebra walker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Set

from ..jena_sparql.jena_types import ExprVar, ExprFunction, ExprAggregator, GroupVar

from .ir import (
    PlanV2,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS,
    KIND_TABLE, KIND_NULL, KIND_PATH,
    KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE,
    KIND_ORDER, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
    MODIFIER_KINDS,
)


# ---------------------------------------------------------------------------
# VarScope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VarScope:
    """The set of variables visible at a point in the plan tree.

    Attributes:
        defined: Variables that are definitely bound (from BGP, BIND, etc.)
        maybe: Variables that may or may not be bound (from OPTIONAL, UNION)
        all_visible: defined | maybe — everything the emitter can reference
    """
    defined: FrozenSet[str] = field(default_factory=frozenset)
    maybe: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def all_visible(self) -> FrozenSet[str]:
        return self.defined | self.maybe

    def with_defined(self, *vars: str) -> VarScope:
        """Add variables to the defined set."""
        return VarScope(
            defined=self.defined | frozenset(vars),
            maybe=self.maybe - frozenset(vars),
        )

    def with_maybe(self, *vars: str) -> VarScope:
        """Add variables to the maybe set."""
        return VarScope(
            defined=self.defined,
            maybe=self.maybe | frozenset(vars),
        )

    def restrict_to(self, vars: Set[str]) -> VarScope:
        """Restrict scope to only the given variables (for PROJECT)."""
        return VarScope(
            defined=self.defined & frozenset(vars),
            maybe=self.maybe & frozenset(vars),
        )

    def merge_join(self, other: VarScope) -> VarScope:
        """Merge scopes for an inner JOIN — both sides must bind."""
        return VarScope(
            defined=self.defined | other.defined,
            maybe=self.maybe | other.maybe,
        )

    def merge_left_join(self, other: VarScope) -> VarScope:
        """Merge scopes for LEFT JOIN — right side vars become maybe."""
        right_only = other.all_visible - self.all_visible
        return VarScope(
            defined=self.defined,
            maybe=self.maybe | other.defined | other.maybe | right_only,
        )

    def merge_union(self, other: VarScope) -> VarScope:
        """Merge scopes for UNION — vars in both branches are defined,
        vars in only one branch become maybe."""
        both = self.defined & other.defined
        one_side = (
            (self.defined - other.all_visible) |
            (other.defined - self.all_visible) |
            self.maybe | other.maybe
        )
        return VarScope(defined=both, maybe=one_side)

    def merge_minus(self, other: VarScope) -> VarScope:
        """Merge scopes for MINUS — only left side vars survive."""
        return self  # MINUS doesn't introduce new variables

    def after_group(self, group_vars: Set[str],
                     agg_vars: Set[str]) -> VarScope:
        """Scope after GROUP BY — only grouped vars and aggregates visible."""
        return VarScope(
            defined=frozenset(group_vars | agg_vars),
            maybe=frozenset(),
        )


# ---------------------------------------------------------------------------
# Scope computation from PlanV2 tree
# ---------------------------------------------------------------------------

def compute_scope(plan: PlanV2) -> VarScope:
    """Compute the variable scope for a PlanV2 node.

    Walks the tree bottom-up, mirroring Jena's VarFinder rules.
    """
    kind = plan.kind

    # --- Leaf relation kinds ---

    if kind == KIND_BGP:
        return VarScope(defined=frozenset(plan.var_slots.keys()))

    if kind == KIND_TABLE:
        vars = frozenset(plan.values_vars) if plan.values_vars else frozenset()
        return VarScope(defined=vars)

    if kind == KIND_NULL:
        return VarScope()

    if kind == KIND_PATH:
        return VarScope(defined=frozenset(plan.var_slots.keys()))

    # --- Binary relation kinds ---

    if kind == KIND_JOIN:
        left_scope = compute_scope(plan.children[0])
        right_scope = compute_scope(plan.children[1])
        return left_scope.merge_join(right_scope)

    if kind == KIND_LEFT_JOIN:
        left_scope = compute_scope(plan.children[0])
        right_scope = compute_scope(plan.children[1])
        return left_scope.merge_left_join(right_scope)

    if kind == KIND_UNION:
        left_scope = compute_scope(plan.children[0])
        right_scope = compute_scope(plan.children[1])
        return left_scope.merge_union(right_scope)

    if kind == KIND_MINUS:
        left_scope = compute_scope(plan.children[0])
        right_scope = compute_scope(plan.children[1])
        return left_scope.merge_minus(right_scope)

    # --- Modifier kinds (unary) ---

    if kind == KIND_FILTER:
        return compute_scope(plan.child)

    if kind == KIND_EXTEND:
        inner = compute_scope(plan.child)
        return inner.with_defined(plan.extend_var)

    if kind == KIND_GROUP:
        inner_scope = compute_scope(plan.child)
        group_var_names: Set[str] = set()
        for gv in (plan.group_vars or []):
            if isinstance(gv, GroupVar):
                group_var_names.add(gv.var)
            elif isinstance(gv, str):
                group_var_names.add(gv)
        agg_var_names = set(plan.aggregates.keys()) if plan.aggregates else set()
        return inner_scope.after_group(group_var_names, agg_var_names)

    if kind == KIND_PROJECT:
        inner = compute_scope(plan.child)
        proj_set = set(plan.project_vars) if plan.project_vars else set()
        return inner.restrict_to(proj_set)

    if kind in (KIND_DISTINCT, KIND_REDUCED):
        return compute_scope(plan.child)

    if kind == KIND_SLICE:
        return compute_scope(plan.child)

    if kind == KIND_ORDER:
        return compute_scope(plan.child)

    # Fallback
    if plan.children:
        return compute_scope(plan.children[0])
    return VarScope()


# ---------------------------------------------------------------------------
# Expression variable extraction
# ---------------------------------------------------------------------------

def vars_in_expr(expr) -> Set[str]:
    """Collect variable names referenced in an expression tree.

    Copied from v1 jena_sql_helpers._vars_in_expr for isolation.
    """
    if isinstance(expr, ExprVar):
        return {expr.var}
    if isinstance(expr, ExprFunction):
        result: Set[str] = set()
        for a in (expr.args or []):
            result.update(vars_in_expr(a))
        return result
    if isinstance(expr, ExprAggregator):
        if expr.expr:
            return vars_in_expr(expr.expr)
    return set()


# ---------------------------------------------------------------------------
# Text-needed variable computation
# ---------------------------------------------------------------------------

def compute_text_needed_vars(plan: PlanV2) -> Set[str]:
    """Compute the set of variables that need term-table text resolution.

    Strategy: start with ALL variables from all BGP nodes (conservative).
    Then identify variables that are provably internal-only — those that
    do NOT appear in any project_vars AND are NOT referenced by any
    expression (FILTER, EXTEND, ORDER, GROUP, HAVING, LEFT JOIN ON) in
    the entire plan tree.

    Only provably internal variables can skip term JOINs.  This is safe:
    the worst case is resolving a variable we didn't need (correct but
    slightly larger SQL), never the other way around.
    """
    # Collect ALL variables from all BGP nodes
    all_bgp_vars: Set[str] = set()
    _collect_all_bgp_vars(plan, all_bgp_vars)

    if not all_bgp_vars:
        return set()

    # If there's no PROJECT node in the tree (SELECT *), every BGP variable
    # is projected to the output and needs text resolution.
    if not _has_project(plan):
        return all_bgp_vars

    # Collect variables referenced by modifiers (project, filter, etc.)
    referenced: Set[str] = set()
    _collect_referenced_vars(plan, referenced)

    # A variable is internal-only if it's in a BGP but NOT referenced
    # by any modifier in the entire plan tree
    internal_only = all_bgp_vars - referenced

    # Return all BGP vars minus the provably internal ones
    return all_bgp_vars - internal_only


def _has_project(plan: PlanV2) -> bool:
    """Return True if the root modifier chain contains a PROJECT node.

    Only walks down the modifier chain (unary nodes).  Does NOT recurse
    into relation children — a PROJECT inside a JOIN child is a subquery
    boundary, not the outer query's PROJECT.
    """
    node = plan
    while node:
        if node.kind == KIND_PROJECT:
            return True
        if node.kind not in MODIFIER_KINDS:
            return False  # Hit a relation — no PROJECT in outer chain
        if not node.children:
            return False
        node = node.children[0]
    return False


def _collect_all_bgp_vars(plan: PlanV2, result: Set[str]) -> None:
    """Collect ALL variables from all descendant BGP nodes."""
    if plan.kind == KIND_BGP and plan.var_slots:
        result.update(plan.var_slots.keys())
    for child in (plan.children or []):
        _collect_all_bgp_vars(child, result)


def _collect_referenced_vars(plan: PlanV2, refs: Set[str]) -> None:
    """Collect all variables referenced by any modifier in the plan tree."""
    kind = plan.kind

    if kind == KIND_PROJECT and plan.project_vars:
        refs.update(plan.project_vars)

    if kind == KIND_FILTER and plan.filter_exprs:
        for expr in plan.filter_exprs:
            refs.update(vars_in_expr(expr))

    if kind == KIND_EXTEND:
        if plan.extend_var:
            refs.add(plan.extend_var)
        if plan.extend_expr:
            refs.update(vars_in_expr(plan.extend_expr))

    if kind == KIND_ORDER and plan.order_conditions:
        for expr, _dir in plan.order_conditions:
            refs.update(vars_in_expr(expr))

    if kind == KIND_GROUP:
        if plan.group_vars:
            for gv in plan.group_vars:
                if isinstance(gv, GroupVar):
                    refs.add(gv.var)
                    if gv.expr:
                        refs.update(vars_in_expr(gv.expr))
                elif isinstance(gv, str):
                    refs.add(gv)
        if plan.aggregates:
            for agg_var, agg_expr in plan.aggregates.items():
                refs.add(agg_var)
                extracted = vars_in_expr(agg_expr)
                if extracted:
                    refs.update(extracted)
                elif isinstance(agg_expr, ExprAggregator) and agg_expr.expr is None:
                    # COUNT(*) / COUNT(DISTINCT *) — references ALL child vars
                    child_scope = compute_scope(plan.children[0]) if plan.children else VarScope()
                    refs.update(child_scope.all_visible)
        if plan.having_exprs:
            for expr in plan.having_exprs:
                refs.update(vars_in_expr(expr))

    if kind == KIND_LEFT_JOIN and plan.left_join_exprs:
        for expr in plan.left_join_exprs:
            refs.update(vars_in_expr(expr))

    # DISTINCT/REDUCED: need text for variables visible from the child,
    # not ALL descendant BGP vars.  DISTINCT sits above PROJECT, so only
    # the projected columns need deduplication — internal join variables
    # have already been eliminated.
    if kind in (KIND_DISTINCT, KIND_REDUCED) and plan.children:
        child_scope = compute_scope(plan.children[0])
        refs.update(child_scope.all_visible)

    # UNION/MINUS: the parent modifiers already indicate which variables
    # need text resolution.  The UNION/MINUS nodes themselves don't add
    # any text requirements beyond what flows upward.

    # Recurse into children
    for child in (plan.children or []):
        _collect_referenced_vars(child, refs)
