"""FILTER push-down — converts filters on SPARQL variables to quad-level UUID
semi-join constraints in the child BGP.

Detects patterns like CONTAINS(?var, "literal") in a FILTER node and
converts them to:
    q.object_uuid IN (SELECT term_uuid FROM term WHERE term_text ILIKE '%literal%')

This pushes text matching to the term table FIRST, then uses the resulting
UUIDs to drive quad-level joins — leveraging the GIN trigram index and
dramatically reducing intermediate row counts.

Numeric range comparators (issues/040 W2) are pushed the same way:

    FILTER(?val >= 65.0)
 -> q.object_uuid IN (SELECT term_uuid FROM term
                      WHERE CASE WHEN <numeric> THEN CAST(term_text AS NUMERIC)
                            END >= 65.0)

Without this the predicate can only be evaluated *above* the join, so every
candidate carrying that slot crosses the join and is discarded at the top. The
cost is then independent of how selective the threshold is: measured on
sp_lead_synth, `MQLRating >= 99.9` returned 16 rows and `>= 0` returned 10,000,
and both read ~458,900 buffers. Equality comparators never had this problem
because they bind the object at the leaf — which is exactly what this restores
for ranges.

The consumed filter expressions are removed from the FILTER node so they
are not applied again in the outer wrapper.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

from ..jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, LiteralNode,
)

from .ir import (PlanV2, KIND_BGP, KIND_FILTER, KIND_EXTEND, KIND_JOIN,
                 KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS)
from .collect import _esc, _like_escape

logger = logging.getLogger(__name__)


def _quad_aliases(bgp: PlanV2) -> set:
    return {t.alias for t in bgp.tables
            if t.kind in ("quad", "edge", "frame_entity")}


# Descending past these would change what the filter means: pushing into the
# right side of an OPTIONAL turns "keep the row, unbound" into "drop the row",
# and pushing into one UNION branch silently drops the other's contribution.
_UNSAFE_TO_DESCEND = frozenset({KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS})


def _find_bgp_binding(node: Optional[PlanV2], var_name: str,
                      depth: int = 0) -> Optional[PlanV2]:
    """Find the BGP that binds `var_name` to a quad column.

    Unlike `_find_descendant_bgp`, this searches *all* operands of an inner
    JOIN rather than the first child only. A constraint pushed into either
    operand of an inner join is applied above it anyway, so this preserves
    semantics; LEFT_JOIN / UNION / MINUS are refused.
    """
    if node is None or depth > 8:
        return None
    if node.kind in _UNSAFE_TO_DESCEND:
        return None
    if node.kind == KIND_BGP:
        slot = node.var_slots.get(var_name)
        if slot and slot.positions:
            ref_id, _col = slot.positions[0]
            if ref_id in _quad_aliases(node):
                return node
        return None
    if node.kind in (KIND_JOIN, KIND_FILTER, KIND_EXTEND):
        for child in (node.children or []):
            found = _find_bgp_binding(child, var_name, depth + 1)
            if found is not None:
                return found
    return None


def _find_descendant_bgp(plan: PlanV2) -> Optional[PlanV2]:
    """Walk through EXTEND/FILTER children to find a descendant BGP.

    Handles chains like FILTER → EXTEND → BGP (UNION + BIND pattern)
    and FILTER → FILTER → BGP (nested filters).
    """
    node = plan
    while node.children:
        child = node.children[0]
        if child.kind == KIND_BGP:
            return child
        if child.kind in (KIND_EXTEND, KIND_FILTER):
            node = child
            continue
        return None
    return None


def push_filters(plan: PlanV2, space_id: str, ctx=None) -> None:
    """Push text and numeric-range FILTER expressions into the descendant BGP.

    Modifies the plan in-place:
    - Adds semi-join constraints to the descendant BGP's tagged_constraints
    - Removes consumed filter expressions from plan.filter_exprs

    Handles FILTER → BGP and FILTER → EXTEND → BGP (UNION + BIND pattern).

    ``ctx`` is the EmitContext; it is required for numeric push-down because the
    numeric datatype ids are per-space and only resolvable from the loaded
    datatype cache. Without it only text filters are pushed.
    """
    if plan.kind != KIND_FILTER or not plan.filter_exprs:
        return

    term_table = f"{space_id}_term"

    # The single-chain BGP, if there is one. Text push-down still targets only
    # this, unchanged.
    child_bgp = _find_descendant_bgp(plan)

    # per-BGP accumulated constraints, so a JOIN's operands can each receive
    # the constraints that belong to them
    pushed: dict = {}
    remaining: List = []
    n_pushed = 0

    for expr in plan.filter_exprs:
        constraint = None
        target = None

        if child_bgp is not None:
            quad_aliases = _quad_aliases(child_bgp)
            constraint = _try_text_filter(expr, child_bgp, term_table,
                                          quad_aliases)
            if constraint:
                target = child_bgp

        if constraint is None and ctx is not None:
            # Numeric ranges search by *variable*, so they also reach BGPs that
            # sit under an inner JOIN — which is the usual shape for a KGQuery
            # (FILTER over JOIN over two BGPs), and one the single-chain walk
            # above cannot see at all.
            var_name = _numeric_var(expr)
            if var_name is not None:
                bgp = _find_bgp_binding(plan.children[0] if plan.children else None,
                                        var_name)
                if bgp is not None:
                    constraint = _try_numeric_filter(
                        expr, bgp, term_table, _quad_aliases(bgp), ctx)
                    if constraint:
                        target = bgp

        if constraint and target is not None:
            pushed.setdefault(id(target), (target, []))[1].append(constraint)
            n_pushed += 1
        else:
            remaining.append(expr)

    if n_pushed:
        for bgp, constraints in pushed.values():
            bgp.tagged_constraints.extend(constraints)
            bgp.constraints.extend(sql for _, sql in constraints)
        plan.filter_exprs = remaining if remaining else None
        logger.debug("Pushed %d filter(s) into %d BGP(s)",
                     n_pushed, len(pushed))


# Backwards-compatible alias — this function used to handle text filters only.
push_text_filters = push_filters


def _try_text_filter(
    expr, bgp: PlanV2, term_table: str, quad_aliases: set
) -> Optional[Tuple[str, str]]:
    """Try to convert a single text filter expression to a quad-level constraint.

    Returns (alias, sql) tuple for tagged_constraints, or None.
    """
    if not isinstance(expr, ExprFunction):
        return None

    name = (expr.name or "").lower()
    args = expr.args or []

    var_name = None
    literal_value = None
    flags_arg = None

    if name in ("contains", "strstarts", "strends") and len(args) == 2:
        if isinstance(args[0], ExprVar) and isinstance(args[1], ExprValue):
            if isinstance(args[1].node, LiteralNode):
                var_name = args[0].var
                literal_value = args[1].node.value
    elif name == "regex" and len(args) >= 2:
        if isinstance(args[0], ExprVar) and isinstance(args[1], ExprValue):
            if isinstance(args[1].node, LiteralNode):
                var_name = args[0].var
                literal_value = args[1].node.value
                if len(args) >= 3:
                    flags_arg = args[2]
    elif name == "eq" and len(args) == 2:
        for i, j in ((0, 1), (1, 0)):
            if isinstance(args[i], ExprVar) and isinstance(args[j], ExprValue):
                if isinstance(args[j].node, LiteralNode):
                    var_name = args[i].var
                    literal_value = args[j].node.value
                    break

    if var_name is None or literal_value is None:
        return None

    # Find the variable's quad column binding
    slot = bgp.var_slots.get(var_name)
    if not slot or not slot.positions:
        return None

    # Use the first position — (ref_id, col_name) e.g. ("q1", "object_uuid")
    ref_id, col_name = slot.positions[0]

    # Must be a quad/MV table alias (not a term table)
    if ref_id not in quad_aliases:
        return None

    uuid_col = f"{ref_id}.{col_name}"

    # Build the term table condition
    escaped = _esc(literal_value)
    # For the LIKE-based operators the needle must also have its LIKE
    # metacharacters (\ % _) escaped, else CONTAINS(?x, "50%") over-matches.
    # Escaping keeps the GIN trigram index usable (pg_trgm honors '\').
    like_esc = _esc(_like_escape(literal_value))
    if name == "contains":
        term_cond = f"term_text LIKE '%{like_esc}%'"
    elif name == "strstarts":
        term_cond = f"term_text LIKE '{like_esc}%'"
    elif name == "strends":
        term_cond = f"term_text LIKE '%{like_esc}'"
    elif name == "regex":
        raw_flags = ""
        if flags_arg and isinstance(flags_arg, ExprValue):
            if isinstance(flags_arg.node, LiteralNode):
                raw_flags = flags_arg.node.value or ""
        op = "~*" if "i" in raw_flags else "~"
        pg_embedded = ""
        if "s" in raw_flags:
            pg_embedded += "s"
        if "m" in raw_flags:
            pg_embedded += "n"
        if "x" in raw_flags:
            pg_embedded += "x"
        pat = f"(?{pg_embedded}){escaped}" if pg_embedded else escaped
        term_cond = f"term_text {op} '{pat}'"
    elif name == "eq":
        term_cond = f"term_text = '{escaped}'"
    else:
        return None

    constraint_sql = (
        f"{uuid_col} IN "
        f"(SELECT term_uuid FROM {term_table} WHERE {term_cond})"
    )
    logger.debug("Text filter pushdown: %s(%s, '%s') → %s",
                 name, var_name, literal_value, constraint_sql[:80])
    return (ref_id, constraint_sql)


# ---------------------------------------------------------------------------
# Numeric range push-down (issues/040 W2)
# ---------------------------------------------------------------------------

# Jena renders comparison operators under several names depending on how the
# expression was written; map each to its SQL operator and to the operator that
# means the same thing when the variable is the *right* operand
# (`65 <= ?v` is `?v >= 65`).
_NUMERIC_OPS = {
    "lt": "<", "lessthan": "<",
    "le": "<=", "lessequal": "<=", "lessthanorequal": "<=",
    "gt": ">", "greaterthan": ">",
    "ge": ">=", "greaterequal": ">=", "greaterthanorequal": ">=",
}
_FLIPPED = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}


def _numeric_literal(expr) -> Optional[str]:
    """Return the SQL numeric literal for an ExprValue, or None.

    Rendered from the parsed float so the emitted SQL cannot carry anything
    from the query text into the statement.
    """
    if not isinstance(expr, ExprValue) or not isinstance(expr.node, LiteralNode):
        return None
    try:
        return repr(float(expr.node.value))
    except (TypeError, ValueError):
        return None


def _try_numeric_filter(
    expr, bgp: PlanV2, term_table: str, quad_aliases: set, ctx
) -> Optional[Tuple[str, str]]:
    """Convert `?var <op> <number>` into a term-table semi-join constraint.

    Returns (alias, sql) for tagged_constraints, or None if the expression is
    not a numeric comparison against a quad-bound variable.
    """
    if not isinstance(expr, ExprFunction):
        return None

    op = _NUMERIC_OPS.get((expr.name or "").lower())
    if op is None:
        return None

    args = expr.args or []
    if len(args) != 2:
        return None

    left, right = args
    if isinstance(left, ExprVar):
        var_name, literal = left.var, _numeric_literal(right)
    elif isinstance(right, ExprVar):
        # Variable on the right: `65 <= ?v` means `?v >= 65`.
        var_name, literal = right.var, _numeric_literal(left)
        op = _FLIPPED[op]
    else:
        return None

    if literal is None:
        return None

    slot = bgp.var_slots.get(var_name)
    if not slot or not slot.positions:
        return None
    ref_id, col_name = slot.positions[0]
    if ref_id not in quad_aliases:
        return None

    # Must reproduce the __num projection exactly (sql_type_generation), or the
    # push-down and the column it replaces would disagree about which literals
    # count as numeric. CASE rather than `AND` because PostgreSQL does not
    # guarantee AND evaluation order, and an unguarded CAST over the term table
    # raises on the first URI it meets.
    from .sql_type_generation import numeric_term_expr
    from .emit_bgp import _NUMERIC_DATATYPES

    num_ids = ctx.dt_ids_for_uris(_NUMERIC_DATATYPES)
    if num_ids == "NULL":
        return None      # no numeric datatypes in this space — nothing to match

    num_expr = numeric_term_expr(num_ids)

    constraint_sql = (
        f"{ref_id}.{col_name} IN "
        f"(SELECT term_uuid FROM {term_table} WHERE {num_expr} {op} {literal})"
    )
    logger.debug("Numeric filter pushdown: %s %s %s -> %s",
                 var_name, op, literal, constraint_sql[:80])
    return (ref_id, constraint_sql)


def _numeric_var(expr) -> Optional[str]:
    """Variable name of a `?var <op> number` comparison, or None."""
    if not isinstance(expr, ExprFunction):
        return None
    if (expr.name or "").lower() not in _NUMERIC_OPS:
        return None
    args = expr.args or []
    if len(args) != 2:
        return None
    left, right = args
    if isinstance(left, ExprVar) and _numeric_literal(right) is not None:
        return left.var
    if isinstance(right, ExprVar) and _numeric_literal(left) is not None:
        return right.var
    return None
