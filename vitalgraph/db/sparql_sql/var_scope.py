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

from ..jena_sparql.jena_types import (
    ExprVar, ExprFunction, ExprAggregator, ExprExists, GroupVar,
)

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

def _vars_in_algebra(op, _seen=None) -> Set[str]:
    """Collect every variable named anywhere in an algebra (Op) subtree.

    Deliberately coarse — it walks dataclass fields generically rather than
    switching on Op type, so a new Op kind cannot silently go uninspected. Used
    for EXISTS/NOT EXISTS, where the nested pattern is an Op rather than a
    PlanV2 and callers only need "is this variable mentioned in there".
    """
    from ..jena_sparql.jena_types import VarNode

    result: Set[str] = set()
    if op is None:
        return result
    # Guard against shared/cyclic references in the algebra tree
    if _seen is None:
        _seen = set()
    if id(op) in _seen:
        return result
    _seen.add(id(op))

    if isinstance(op, VarNode):
        return {op.name}
    if isinstance(op, (ExprVar, ExprFunction, ExprAggregator)):
        return vars_in_expr(op)
    if isinstance(op, str):
        return result
    if isinstance(op, dict):
        for v in op.values():
            result.update(_vars_in_algebra(v, _seen))
        return result
    if isinstance(op, (list, tuple, set, frozenset)):
        for item in op:
            result.update(_vars_in_algebra(item, _seen))
        return result
    if hasattr(op, "__dataclass_fields__"):
        for fname in op.__dataclass_fields__:
            result.update(_vars_in_algebra(getattr(op, fname, None), _seen))
    return result


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
    if isinstance(expr, ExprExists):
        # An outer variable may be referenced ONLY from inside the EXISTS
        # pattern (typically from a FILTER there). Missing it here makes
        # compute_text_needed_vars treat the variable as internal-only, so the
        # outer BGP emits NULL for its text column and the correlation compares
        # against NULL — EXISTS never matches (issue 027).
        return _vars_in_algebra(expr.graph_pattern)
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


def all_named_vars(plan: PlanV2) -> Set[str]:
    """Every variable named anywhere in the plan tree.

    Deliberately broader than ``compute_scope(plan).all_visible``, which is
    only what is *visible* at the root. A variable can be named in the query
    yet invisible there — referenced solely from a FILTER inside an EXISTS, or
    bound in a sibling scope — and those are exactly the cases where a
    reference fails to resolve during emission.

    Used to populate ``EmitContext.query_all_vars``, which gates the
    unresolved-variable diagnostic in ``emit_expressions._var_to_sql``. Gating
    that on scope-visibility meant the diagnostic stayed silent for precisely
    the variables most likely to go missing (issues 027, 028), so this is the
    set the diagnostic needs.

    Diagnostics only — nothing branches on this, so over-inclusion is safe.
    """
    result: Set[str] = set()
    _collect_all_bgp_vars(plan, result)
    _collect_referenced_vars(plan, result)
    _collect_values_vars(plan, result)
    result.update(compute_scope(plan).all_visible)
    return result


def _collect_values_vars(plan: PlanV2, result: Set[str]) -> None:
    """Collect VALUES (inline data) variables from the whole tree."""
    if plan.kind == KIND_TABLE and plan.values_vars:
        result.update(plan.values_vars)
    for child in (plan.children or []):
        _collect_values_vars(child, result)


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


def _counts_a_bare_var(agg_expr) -> bool:
    """True for ``COUNT(?v)`` / ``COUNT(DISTINCT ?v)`` over a plain variable.

    These are the aggregates that emit a UUID column rather than text, so the
    counted variable needs no term JOIN. Everything else — COUNT of a compound
    expression, COUNT(*), and every non-COUNT aggregate (MIN/MAX/SUM/AVG/
    GROUP_CONCAT/SAMPLE) — reads a value column and is excluded.
    """
    if not isinstance(agg_expr, ExprAggregator):
        return False
    if (agg_expr.name or "COUNT").upper() != "COUNT":
        return False
    return isinstance(agg_expr.expr, ExprVar)


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
                if _counts_a_bare_var(agg_expr):
                    # COUNT(?v) / COUNT(DISTINCT ?v) aggregates the UUID column
                    # (emit_group._qualify_agg_inner), which is non-null exactly
                    # when the variable is bound — so the term JOIN resolving
                    # ?v's TEXT is pure cost. Counting the frames of a 1.1M-frame
                    # graph resolved 1.1M URIs it never looked at: 2,180 ms
                    # against 579 ms once the JOIN is dropped.
                    #
                    # Only a BARE variable qualifies. COUNT(expr) may evaluate
                    # text, and COUNT(*) / COUNT(DISTINCT *) is handled below —
                    # it builds a ROW() over the child's columns and needs them.
                    # A variable used elsewhere too still gets its text from that
                    # other reference; this only declines to add one.
                    continue
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

    # VALUES (KIND_TABLE): variables bound by inline VALUES participate in
    # JOIN conditions that compare text values.  Mark them as referenced so
    # any BGP sibling that shares the variable resolves its text column
    # (otherwise the text is NULL and the equality join always fails).
    if kind == KIND_TABLE and plan.values_vars:
        refs.update(plan.values_vars)

    # Recurse into children
    for child in (plan.children or []):
        _collect_referenced_vars(child, refs)
