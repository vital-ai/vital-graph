"""
Pre-emit optimization pass for vector, text, and geo functions.

Walks the PlanV2 tree top-down and annotates nodes with hints that the
emit phase uses to generate more efficient SQL.  Runs between collect
and emit in the generator pipeline.

Detected patterns and their hints:

1. **Vector/Text/Hybrid top-K** (SLICE → ORDER → … → EXTEND with vg:*)
   Hint on EXTEND: ``hints['vg_top_k'] = {'limit': N, 'direction': 'DESC'}``
   → emit uses index-driving subqueries (HNSW for vector, GIN for text)
     instead of a correlated subquery per row.

2. **Filter threshold pushdown** (FILTER(?score > T) after BIND vg:…)
   Hint on EXTEND: ``hints['vg_threshold'] = 0.7``
   → emit adds ``WHERE 1 - (embedding <=> ...) > T`` inside the subquery.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from ..jena_sparql.jena_types import ExprFunction, ExprVar, ExprValue, LiteralNode

from .ir import (
    PlanV2,
    KIND_SLICE, KIND_ORDER, KIND_PROJECT, KIND_EXTEND,
    KIND_DISTINCT, KIND_REDUCED, KIND_FILTER,
)
from .declines import Rule
from .vg_functions import (
    VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY,
    is_vg_function, is_vg_vector_function, is_vg_text_function,
    is_vg_trigram_function,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def vg_optimize(plan: PlanV2) -> PlanV2:
    """Run all vg: optimization passes on the plan tree.

    Returns the (possibly annotated) plan.  The plan tree is mutated
    in-place (hints dict is populated) rather than copied.
    """
    _annotate_vector_top_k(plan)
    _annotate_filter_threshold(plan)
    return plan


# ---------------------------------------------------------------------------
# Pattern 1: Vector/Text/Hybrid top-K
#
# Detects:
#   SLICE(limit=N)
#     ORDER(DESC ?score)          -- or nested through PROJECT/DISTINCT
#       (PROJECT)?
#         EXTEND(?score = vg:vectorSimilarity/vectorNearby/textSearch/hybridSearch)
#
# Annotates the EXTEND node with:
#   hints['vg_top_k'] = {'limit': N, 'direction': 'DESC'}
# ---------------------------------------------------------------------------

# Declared so the refusal is REPORTABLE rather than only logged: "why is this
# query not using the vector fast path" is asked about one query, by someone holding
# that query and not the log level it ran under (`declines.py`).
VECTOR_TOP_K = Rule("vector_top_k", stage="vg_optimize")


def _annotate_vector_top_k(plan: PlanV2) -> None:
    """Detect SLICE→ORDER→…→EXTEND(vg:vector*/text*/hybrid*) and annotate."""
    if plan.kind != KIND_SLICE or plan.limit <= 0:
        return

    # Find ORDER BY node — may be the direct child, or buried under DISTINCT/PROJECT
    order_node, score_var, direction = _find_order_on_score(plan.child)
    if order_node is None or score_var is None:
        return

    # Find EXTEND node defining the score variable
    extend_node = _find_extend_for_var(order_node, score_var)
    if extend_node is None:
        return

    # Verify the extend expression is a vg: vector or text/hybrid function
    if not isinstance(extend_node.extend_expr, ExprFunction):
        return
    if not (is_vg_vector_function(extend_node.extend_expr)
            or is_vg_text_function(extend_node.extend_expr)
            or is_vg_trigram_function(extend_node.extend_expr)):
        return

    # REFUSE when a restriction sits between the ORDER and the EXTEND.
    #
    # `issues/220`. The top-K rewrite emits a driving subquery that takes the K
    # nearest vectors and INNER JOINs them to the pattern, restricted to the
    # subjects in the EXTEND's CHILD. Its comment promises those K "are guaranteed
    # to survive the downstream INNER JOIN" — and that holds only if the child
    # carries every restriction. A FILTER placed ABOVE the extend is not in the
    # child, so the K are chosen from a SUPERSET and the join discards them.
    #
    # Measured: a document query reported total_count=66 and returned ZERO. The
    # child yielded 209 subjects (every segment plus the parent copies) instead of
    # the 66 that survive, and all five top-K rows were segment types the outer
    # FILTER excludes. Restricted to the 66, the same top-K returned 5 rows.
    #
    # The score threshold is the ONE filter that is safe here, because it is pushed
    # INTO the driving subquery by `_annotate_filter_threshold`. Any other filter
    # means the rewrite cannot keep its promise, so it declines and the correlated
    # form serves the query — which scores per row and therefore applies the outer
    # filters first. Slower for this shape, correct for every shape.
    blocking = _restriction_between(plan.child, extend_node, score_var)
    if blocking is not None:
        VECTOR_TOP_K.decline(
            "a FILTER above the EXTEND is not in the driving subquery's child, "
            "so the top-K rows are not guaranteed to survive the join",
            score_var=score_var, blocking=blocking)
        logger.info(
            "vg_optimize: top-K DECLINED for ?%s — %s between ORDER and EXTEND "
            "is not visible to the driving subquery (issues/220)",
            score_var, blocking,
        )
        return

    # Annotate the EXTEND node
    extend_node.hints['vg_top_k'] = {
        'limit': plan.limit,
        'direction': direction,
    }
    logger.info(
        "vg_optimize: top-K detected: ?%s ORDER BY %s LIMIT %d",
        score_var, direction, plan.limit,
    )


def _find_order_on_score(
    node: Optional[PlanV2], depth: int = 0,
) -> Tuple[Optional[PlanV2], Optional[str], str]:
    """Walk through PROJECT/DISTINCT to find an ORDER node on a single var.

    Returns (order_node, var_name, direction) or (None, None, "") if not found.
    """
    if node is None or depth > 3:
        return None, None, ""

    if node.kind == KIND_ORDER and node.order_conditions:
        # Check if ordering on a single variable
        if len(node.order_conditions) == 1:
            key, direction = node.order_conditions[0]
            if isinstance(key, str):
                return node, key, direction
            if isinstance(key, ExprVar):
                return node, key.var, direction
        return None, None, ""

    # Walk through transparent wrappers
    if node.kind in (KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED) and node.children:
        return _find_order_on_score(node.children[0], depth + 1)

    return None, None, ""


def _find_extend_for_var(
    node: Optional[PlanV2], var_name: str, depth: int = 0,
) -> Optional[PlanV2]:
    """Walk down from ORDER node to find the EXTEND that defines var_name.

    Walks through ORDER → PROJECT → EXTEND chain (max depth 5).
    """
    if node is None or depth > 5:
        return None

    if node.kind == KIND_EXTEND and node.extend_var == var_name:
        return node

    # Walk through modifier chain
    if node.children:
        return _find_extend_for_var(node.children[0], var_name, depth + 1)

    return None


def _restriction_between(
    top: Optional[PlanV2], extend_node: PlanV2, score_var: str,
    depth: int = 0,
) -> Optional[str]:
    """Name of the first restricting node between `top` and `extend_node`, if any.

    `issues/220`. Walks the same chain `_find_extend_for_var` walks and reports a
    node that removes rows the driving subquery's child would have kept. Only the
    score threshold is exempt: `_annotate_filter_threshold` pushes that one INTO the
    subquery, so it is applied on the vector side rather than above the join.

    Returns None when the path is clear, which is the only case where the top-K
    rewrite can promise that its K rows survive.
    """
    node = top
    while node is not None and depth <= 6:
        if node is extend_node:
            return None
        if node.kind == KIND_FILTER:
            for expr in (node.filter_exprs or []):
                # A threshold on the score variable is pushed into the subquery.
                if _extract_threshold(expr, score_var) is None:
                    return "FILTER"
        if not node.children:
            return None
        node = node.children[0]
        depth += 1
    return None


# ---------------------------------------------------------------------------
# Pattern 2: Filter threshold pushdown
#
# Detects:
#   FILTER(?score > T)   or   FILTER(?score >= T)
#     EXTEND(?score = vg:vectorSimilarity/vectorNearby)
#
# Annotates the EXTEND node with:
#   hints['vg_threshold'] = T (float)
# ---------------------------------------------------------------------------

def _annotate_filter_threshold(plan: PlanV2) -> None:
    """Recursively walk the tree looking for FILTER→EXTEND patterns."""
    # Process this node
    if plan.kind == KIND_FILTER and plan.filter_exprs:
        _check_filter_extend_threshold(plan)

    # Recurse into children
    for child in plan.children:
        _annotate_filter_threshold(child)


def _check_filter_extend_threshold(filter_node: PlanV2) -> None:
    """Check if a FILTER node contains a threshold on a vg: EXTEND variable."""
    if not filter_node.children:
        return

    # The child should be (or contain) an EXTEND with a vg: function
    extend_node = _find_vg_extend(filter_node.children[0])
    if extend_node is None:
        return

    score_var = extend_node.extend_var

    # Check filter expressions for ?score > T or ?score >= T
    for expr in (filter_node.filter_exprs or []):
        threshold = _extract_threshold(expr, score_var)
        if threshold is not None:
            extend_node.hints['vg_threshold'] = threshold
            logger.info(
                "vg_optimize: threshold pushdown: ?%s > %s",
                score_var, threshold,
            )
            return


def _find_vg_extend(
    node: Optional[PlanV2], depth: int = 0,
) -> Optional[PlanV2]:
    """Find an EXTEND node with a vg: vector or text/hybrid function expression."""
    if node is None or depth > 3:
        return None
    if node.kind == KIND_EXTEND:
        if isinstance(node.extend_expr, ExprFunction) and (
            is_vg_vector_function(node.extend_expr)
            or is_vg_text_function(node.extend_expr)
            or is_vg_trigram_function(node.extend_expr)
        ):
            return node
    if node.children:
        return _find_vg_extend(node.children[0], depth + 1)
    return None


def _extract_threshold(expr, score_var: Optional[str]) -> Optional[float]:
    """Extract threshold from an expression like ?score > 0.7.

    Returns the float threshold value, or None if the pattern doesn't match.
    Handles both > and >= operators.
    """
    if not isinstance(expr, ExprFunction):
        return None

    fname = (expr.name or "").lower()
    if fname not in ("gt", "ge", "greaterthan", "greaterequal"):
        return None

    args = expr.args or []
    if len(args) != 2:
        return None

    # Pattern: ?score > literal
    left, right = args[0], args[1]
    if isinstance(left, ExprVar) and left.var == score_var:
        return _literal_float(right)

    # Pattern: literal < ?score  (inverted)
    if isinstance(right, ExprVar) and right.var == score_var:
        if fname in ("gt", "greaterthan"):
            # literal > ?score → ?score < literal (wrong direction, skip)
            return None
        return _literal_float(left)

    return None


def _literal_float(expr) -> Optional[float]:
    """Extract a float value from an ExprValue literal."""
    if not isinstance(expr, ExprValue):
        return None
    if expr.node and isinstance(expr.node, LiteralNode):
        try:
            return float(expr.node.value)
        except (ValueError, TypeError):
            return None
    return None
