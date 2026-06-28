"""
Shared helper utilities for the Jena SQL generator pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .jena_sparql.jena_types import (
    URINode, LiteralNode, BNodeNode, VarNode, RDFNode,
    ExprVar, ExprFunction, ExprAggregator, ExprExists,
)

logger = logging.getLogger(__name__)


def _esc(s: str) -> str:
    """Escape single quotes for SQL string literals."""
    if s is None:
        return ""
    return s.replace("'", "''")


def _node_text(node: RDFNode) -> str:
    """Extract the text value from an RDF node."""
    if isinstance(node, URINode):
        return node.value
    elif isinstance(node, LiteralNode):
        return node.value
    elif isinstance(node, BNodeNode):
        return f"_:{node.label}"
    elif isinstance(node, VarNode):
        return f"?{node.name}"
    return ""


def _node_type(node: RDFNode) -> str:
    """Get the term_type character for an RDF node."""
    if isinstance(node, URINode):
        return "U"
    elif isinstance(node, LiteralNode):
        return "L"
    elif isinstance(node, BNodeNode):
        return "B"
    return "U"


# Placeholder prefix/suffix for constant tokens embedded during collect.
# After materialize, these are replaced with literal 'uuid'::uuid values.
_CONST_PREFIX = "__CONST_"
_CONST_SUFFIX = "__"

CTE_CONST_ALIAS = "_const"


def _const_subquery(term_text: str, term_type: str, aliases) -> str:
    """Register a constant term and return a placeholder token.

    During collect, constants are embedded as placeholder tokens like
    ``__CONST_c_0__``.  After the materialize phase resolves UUIDs,
    :func:`substitute_constants` replaces them with ``'uuid'::uuid``
    literals.

    Args:
        term_text: The term text value (URI string or literal value).
        term_type: 'U' for URI, 'L' for literal, 'B' for blank node.
        aliases: AliasGenerator with constants registry.

    Returns:
        Placeholder token like: __CONST_c_0__
    """
    col = aliases.register_constant(term_text, term_type)
    return f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}"


def materialize_constants(
    aliases,
    term_table: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
) -> None:
    """Batch-resolve all registered constants to UUIDs via one DB query.

    Populates ``aliases.resolved_constants`` mapping col_name -> uuid string.
    This must be called after collect and before emit so that
    :func:`substitute_constants` can replace placeholder tokens with
    literal UUID values.
    """
    if not aliases.constants:
        return

    from . import db  # local import to avoid circular dependency

    pairs = list(aliases.constants.keys())  # [(term_text, term_type), ...]
    if len(pairs) == 1:
        text, ttype = pairs[0]
        sql = (
            f"SELECT term_text, term_type, term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}' LIMIT 1"
        )
    else:
        values = ", ".join(
            f"('{_esc(text)}', '{ttype}')" for text, ttype in pairs
        )
        sql = (
            f"SELECT term_text, term_type, term_uuid FROM {term_table} "
            f"WHERE (term_text, term_type) IN ({values})"
        )

    rows = db.execute_query(sql, conn_params=conn_params, conn=conn)
    text_map = {(r["term_text"], r["term_type"]): str(r["term_uuid"]) for r in rows}

    for (text, ttype), col_name in aliases.constants.items():
        uuid_str = text_map.get((text, ttype))
        if uuid_str:
            aliases.resolved_constants[col_name] = uuid_str
        else:
            logger.warning(
                "Constant not found in term table: text=%r type=%r", text, ttype
            )

    logger.debug(
        "Materialized %d/%d constants",
        len(aliases.resolved_constants), len(aliases.constants),
    )


def substitute_constants(sql: str, aliases) -> str:
    """Replace placeholder tokens with literal UUID values.

    If a constant was resolved by :func:`materialize_constants`, its
    placeholder ``__CONST_c_0__`` is replaced with ``'uuid'::uuid``.
    If not resolved (missing from DB), falls back to a scalar subquery
    against the term table.
    """
    if not aliases.constants:
        return sql

    for (text, ttype), col_name in aliases.constants.items():
        token = f"{_CONST_PREFIX}{col_name}{_CONST_SUFFIX}"
        uuid_str = aliases.resolved_constants.get(col_name)
        if uuid_str:
            replacement = f"'{uuid_str}'::uuid"
        else:
            # Fallback: inline scalar subquery (slower but correct)
            replacement = (
                f"(SELECT term_uuid FROM {CTE_CONST_ALIAS} "
                f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}')"
            )
        sql = sql.replace(token, replacement)

    return sql


def build_constants_cte(aliases, term_table: str) -> str:
    """Build a WITH _const AS (...) fallback CTE for unresolved constants.

    Returns empty string if all constants were resolved by materialize,
    or if no constants were registered.
    """
    if not aliases.constants:
        return ""
    # If all constants were resolved, no CTE needed
    if len(aliases.resolved_constants) == len(aliases.constants):
        return ""
    # Build CTE only for unresolved constants
    pairs = [
        (text, ttype) for (text, ttype), col_name in aliases.constants.items()
        if col_name not in aliases.resolved_constants
    ]
    if not pairs:
        return ""
    if len(pairs) == 1:
        text, ttype = pairs[0]
        where = f"term_text = '{_esc(text)}' AND term_type = '{ttype}'"
    else:
        values = ", ".join(
            f"('{_esc(text)}', '{ttype}')" for text, ttype in pairs
        )
        where = f"(term_text, term_type) IN ({values})"
    return (
        f"WITH {CTE_CONST_ALIAS} AS (\n"
        f"  SELECT term_text, term_type, term_uuid FROM {term_table}\n"
        f"  WHERE {where}\n"
        f")\n"
    )


def _vars_in_expr(expr) -> set:
    """Collect variable names referenced in an expression tree."""
    if isinstance(expr, ExprVar):
        return {expr.var}
    if isinstance(expr, ExprFunction):
        result = set()
        for a in (expr.args or []):
            result.update(_vars_in_expr(a))
        return result
    if isinstance(expr, ExprAggregator):
        if expr.expr:
            return _vars_in_expr(expr.expr)
    if isinstance(expr, ExprExists):
        # EXISTS/NOT EXISTS is a correlated subquery — it doesn't add vars to outer scope
        return set()
    return set()
