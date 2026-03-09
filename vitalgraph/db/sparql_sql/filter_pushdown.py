"""FILTER push-down — converts text filters on SPARQL variables to
quad-level UUID semi-join constraints in the child BGP.

Detects patterns like CONTAINS(?var, "literal") in a FILTER node and
converts them to:
    q.object_uuid IN (SELECT term_uuid FROM term WHERE term_text ILIKE '%literal%')

This pushes text matching to the term table FIRST, then uses the resulting
UUIDs to drive quad-level joins — leveraging the GIN trigram index and
dramatically reducing intermediate row counts.

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

from .ir import PlanV2, KIND_BGP, KIND_FILTER, KIND_EXTEND
from .collect import _esc

logger = logging.getLogger(__name__)


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


def push_text_filters(plan: PlanV2, space_id: str) -> None:
    """Push text-based FILTER expressions down into the descendant BGP.

    Modifies the plan in-place:
    - Adds semi-join constraints to the descendant BGP's tagged_constraints
    - Removes consumed filter expressions from plan.filter_exprs

    Handles FILTER → BGP and FILTER → EXTEND → BGP (UNION + BIND pattern).
    """
    if plan.kind != KIND_FILTER or not plan.filter_exprs:
        return

    # Walk through EXTEND/FILTER children to find the BGP
    child_bgp = _find_descendant_bgp(plan)
    if child_bgp is None:
        return
    term_table = f"{space_id}_term"
    quad_aliases = {t.alias for t in child_bgp.tables
                    if t.kind in ("quad", "edge", "frame_entity")}

    extra_constraints: List[Tuple[str, str]] = []
    remaining: List = []

    for expr in plan.filter_exprs:
        constraint = _try_text_filter(expr, child_bgp, term_table, quad_aliases)
        if constraint:
            extra_constraints.append(constraint)
        else:
            remaining.append(expr)

    if extra_constraints:
        child_bgp.tagged_constraints.extend(extra_constraints)
        child_bgp.constraints.extend(sql for _, sql in extra_constraints)
        plan.filter_exprs = remaining if remaining else None
        logger.debug("Pushed %d text filter(s) into BGP", len(extra_constraints))


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
    if name == "contains":
        term_cond = f"term_text LIKE '%{escaped}%'"
    elif name == "strstarts":
        term_cond = f"term_text LIKE '{escaped}%'"
    elif name == "strends":
        term_cond = f"term_text LIKE '%{escaped}'"
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
