"""
SPARQL Expression → SQL string translation.

Handles ExprVar, ExprValue, ExprFunction, and ExprAggregator nodes.
"""

from __future__ import annotations

import logging
from typing import Dict

from .jena_types import (
    URINode, LiteralNode, BNodeNode,
    ExprVar, ExprValue, ExprFunction, ExprAggregator, Expr,
)
from .jena_sql_ir import RelationPlan, SQLContext, VarSlot
from .jena_sql_helpers import _esc

logger = logging.getLogger(__name__)


# ===========================================================================
# Public API
# ===========================================================================

def expr_to_sql(expr: Expr, ctx_or_plan=None) -> str:
    """Public API: Expr → SQL string (for tests and compat)."""
    return _expr_to_sql_str(expr, ctx_or_plan)


# ===========================================================================
# Core expression translator
# ===========================================================================

def _expr_to_sql_str(expr: Expr, plan_or_ctx=None) -> str:
    """Translate a SPARQL expression to a SQL string fragment."""
    if isinstance(expr, ExprVar):
        return _resolve_var_ref(expr.var, plan_or_ctx)

    if isinstance(expr, ExprValue):
        node = expr.node
        if isinstance(node, URINode):
            return f"'{_esc(node.value)}'"
        elif isinstance(node, LiteralNode):
            if node.datatype and "integer" in node.datatype:
                return node.value
            elif node.datatype and "decimal" in node.datatype:
                return node.value
            elif node.datatype and "double" in node.datatype:
                return node.value
            elif node.datatype and "boolean" in node.datatype:
                return "TRUE" if node.value == "true" else "FALSE"
            return f"'{_esc(node.value)}'"
        return "NULL"

    if isinstance(expr, ExprFunction):
        return _func_to_sql(expr, plan_or_ctx)

    if isinstance(expr, ExprAggregator):
        return _agg_to_sql(expr, plan_or_ctx)

    return "NULL"


# ===========================================================================
# Inner-query expression translator (uses term_ref aliases)
# ===========================================================================

def _expr_to_sql_str_inner(expr: Expr, plan: RelationPlan) -> str:
    """Translate expression using inner query column names (term_ref aliases)."""
    if isinstance(expr, ExprVar):
        slot = plan.var_slots.get(expr.var)
        if slot and slot.term_ref_id:
            tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
            if tt:
                return f"{tt.alias}.term_text"
        return f"{expr.var}__text"

    if isinstance(expr, ExprFunction):
        name = (expr.name or "").lower()
        args = expr.args or []

        if name == "contains" and len(args) == 2:
            s = _expr_to_sql_str_inner(args[0], plan)
            pat = _expr_to_sql_str_inner(args[1], plan)
            return f"(POSITION({pat} IN {s}) > 0)"

        if name in _FUNC_MAP and len(args) == 2:
            l = _expr_to_sql_str_inner(args[0], plan)
            r = _expr_to_sql_str_inner(args[1], plan)
            if name in ("gt", "lt", "ge", "le", "eq", "ne"):
                l, r = _apply_typed_casts(args[0], args[1], l, r)
            return f"({l} {_FUNC_MAP[name]} {r})"

        if name == "regex" and len(args) >= 2:
            s = _expr_to_sql_str_inner(args[0], plan)
            pat = _expr_to_sql_str_inner(args[1], plan)
            if len(args) >= 3:
                flags = _expr_to_sql_str_inner(args[2], plan)
                if "'i'" in flags:
                    return f"({s} ~* {pat})"
            return f"({s} ~ {pat})"

    if isinstance(expr, ExprValue):
        return _expr_to_sql_str(expr, None)

    return _expr_to_sql_str(expr, plan)


# ===========================================================================
# Variable resolution
# ===========================================================================

def _resolve_var_ref(var_name: str, plan_or_ctx) -> str:
    """Resolve a variable name to its SQL column reference."""
    if plan_or_ctx is None:
        return var_name

    # RelationPlan
    if isinstance(plan_or_ctx, RelationPlan):
        slot = plan_or_ctx.var_slots.get(var_name)
        if slot and slot.text_col:
            return slot.text_col
        return var_name

    # SQLContext (v1 compat)
    if isinstance(plan_or_ctx, SQLContext):
        b = plan_or_ctx.bindings.get(var_name)
        if b:
            return b.text_col
        return var_name

    return var_name


def _resolve_type_ref(var_name: str, plan_or_ctx) -> str:
    """Resolve a variable to its type column."""
    if isinstance(plan_or_ctx, RelationPlan):
        slot = plan_or_ctx.var_slots.get(var_name)
        if slot and slot.type_col:
            return slot.type_col
    if isinstance(plan_or_ctx, SQLContext):
        b = plan_or_ctx.bindings.get(var_name)
        if b:
            return b.type_col
    return f"{var_name}__type"


def _resolve_lang_ref(var_name: str, plan_or_ctx) -> str:
    """Resolve a variable to its lang column (raw, no COALESCE)."""
    if isinstance(plan_or_ctx, RelationPlan):
        slot = plan_or_ctx.var_slots.get(var_name)
        if slot and slot.term_ref_id:
            tt = next((t for t in plan_or_ctx.tables if t.ref_id == slot.term_ref_id), None)
            if tt:
                return f"{tt.alias}.lang"
    if isinstance(plan_or_ctx, SQLContext):
        b = plan_or_ctx.bindings.get(var_name)
        if b:
            return f"{b.term_alias}.lang"
    return "NULL"


def _resolve_uuid_ref(var_name: str, plan_or_ctx) -> str:
    """Resolve a variable to its UUID column."""
    if isinstance(plan_or_ctx, RelationPlan):
        slot = plan_or_ctx.var_slots.get(var_name)
        if slot and slot.uuid_col:
            return slot.uuid_col
    if isinstance(plan_or_ctx, SQLContext):
        b = plan_or_ctx.bindings.get(var_name)
        if b:
            return b.uuid_col
    return f"{var_name}__uuid"


# ===========================================================================
# Binary operator map
# ===========================================================================

_FUNC_MAP = {
    "add": "+", "subtract": "-", "multiply": "*", "divide": "/",
    "eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=",
    "and": "AND", "or": "OR", "not": "NOT",
}


# ===========================================================================
# Typed literal comparison helpers
# ===========================================================================

_NUMERIC_DTYPES = {
    "http://www.w3.org/2001/XMLSchema#integer",
    "http://www.w3.org/2001/XMLSchema#int",
    "http://www.w3.org/2001/XMLSchema#long",
    "http://www.w3.org/2001/XMLSchema#short",
    "http://www.w3.org/2001/XMLSchema#decimal",
    "http://www.w3.org/2001/XMLSchema#float",
    "http://www.w3.org/2001/XMLSchema#double",
    "http://www.w3.org/2001/XMLSchema#nonNegativeInteger",
    "http://www.w3.org/2001/XMLSchema#positiveInteger",
    "http://www.w3.org/2001/XMLSchema#negativeInteger",
    "http://www.w3.org/2001/XMLSchema#nonPositiveInteger",
    "http://www.w3.org/2001/XMLSchema#unsignedInt",
    "http://www.w3.org/2001/XMLSchema#unsignedLong",
    "http://www.w3.org/2001/XMLSchema#unsignedShort",
    "http://www.w3.org/2001/XMLSchema#unsignedByte",
    "http://www.w3.org/2001/XMLSchema#byte",
}

_DATETIME_DTYPES = {
    "http://www.w3.org/2001/XMLSchema#dateTime",
}

_DATE_DTYPES = {
    "http://www.w3.org/2001/XMLSchema#date",
}


def _get_literal_datatype(expr) -> str | None:
    """Extract the XSD datatype URI from an ExprValue with a LiteralNode, or None."""
    if isinstance(expr, ExprValue) and isinstance(expr.node, LiteralNode):
        return expr.node.datatype
    return None


def _apply_typed_casts(left_expr, right_expr, left_sql: str, right_sql: str):
    """Apply CAST to variable sides of a comparison when a typed literal is present.

    Returns (left_sql, right_sql) with appropriate CASTs applied.
    """
    l_dt = _get_literal_datatype(left_expr)
    r_dt = _get_literal_datatype(right_expr)
    # Determine the effective datatype from whichever side is a typed literal
    dt = l_dt or r_dt
    if not dt:
        return left_sql, right_sql

    if dt in _NUMERIC_DTYPES:
        # CAST the non-literal side to NUMERIC
        if r_dt and not l_dt:
            left_sql = f"CAST({left_sql} AS NUMERIC)"
        elif l_dt and not r_dt:
            right_sql = f"CAST({right_sql} AS NUMERIC)"
    elif dt in _DATETIME_DTYPES:
        if r_dt and not l_dt:
            left_sql = f"CAST({left_sql} AS TIMESTAMP)"
        elif l_dt and not r_dt:
            right_sql = f"CAST({right_sql} AS TIMESTAMP)"
    elif dt in _DATE_DTYPES:
        if r_dt and not l_dt:
            left_sql = f"CAST({left_sql} AS DATE)"
        elif l_dt and not r_dt:
            right_sql = f"CAST({right_sql} AS DATE)"

    return left_sql, right_sql


# ===========================================================================
# Function translator
# ===========================================================================

def _func_to_sql(expr: ExprFunction, plan_or_ctx) -> str:
    """Translate an ExprFunction to SQL."""
    name = (expr.name or "").lower()
    args = expr.args or []

    # Binary operators
    if name in _FUNC_MAP and len(args) == 2:
        l = _expr_to_sql_str(args[0], plan_or_ctx)
        r = _expr_to_sql_str(args[1], plan_or_ctx)
        # Typed literal comparison: CAST variable side for correct ordering
        if name in ("gt", "lt", "ge", "le", "eq", "ne"):
            l, r = _apply_typed_casts(args[0], args[1], l, r)
        return f"({l} {_FUNC_MAP[name]} {r})"

    if name == "not" and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        return f"(NOT {inner})"

    if name == "bound" and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        return f"({inner} IS NOT NULL)"

    if name == "isuri" or name == "isiri":
        if len(args) == 1:
            var = _expr_to_sql_str(args[0], plan_or_ctx)
            # Check term_type = 'U'
            if isinstance(args[0], ExprVar):
                type_col = _resolve_type_ref(args[0].var, plan_or_ctx)
                return f"({type_col} = 'U')"
            return f"({var} IS NOT NULL)"

    if name == "isliteral":
        if len(args) == 1 and isinstance(args[0], ExprVar):
            type_col = _resolve_type_ref(args[0].var, plan_or_ctx)
            return f"({type_col} = 'L')"

    if name == "isblank":
        if len(args) == 1 and isinstance(args[0], ExprVar):
            type_col = _resolve_type_ref(args[0].var, plan_or_ctx)
            return f"({type_col} = 'B')"

    if name == "str":
        if len(args) == 1:
            return _expr_to_sql_str(args[0], plan_or_ctx)

    if name == "contains":
        if len(args) == 2:
            s = _expr_to_sql_str(args[0], plan_or_ctx)
            pat = _expr_to_sql_str(args[1], plan_or_ctx)
            return f"(POSITION({pat} IN {s}) > 0)"

    if name == "strstarts":
        if len(args) == 2:
            s = _expr_to_sql_str(args[0], plan_or_ctx)
            pat = _expr_to_sql_str(args[1], plan_or_ctx)
            return f"({s} LIKE {pat} || '%%')"

    if name == "strends":
        if len(args) == 2:
            s = _expr_to_sql_str(args[0], plan_or_ctx)
            pat = _expr_to_sql_str(args[1], plan_or_ctx)
            return f"({s} LIKE '%%' || {pat})"

    if name == "regex":
        if len(args) >= 2:
            s = _expr_to_sql_str(args[0], plan_or_ctx)
            pat = _expr_to_sql_str(args[1], plan_or_ctx)
            if len(args) >= 3:
                flags = _expr_to_sql_str(args[2], plan_or_ctx)
                if "'i'" in flags:
                    return f"({s} ~* {pat})"
            return f"({s} ~ {pat})"

    if name == "if":
        if len(args) == 3:
            cond = _expr_to_sql_str(args[0], plan_or_ctx)
            then = _expr_to_sql_str(args[1], plan_or_ctx)
            else_ = _expr_to_sql_str(args[2], plan_or_ctx)
            return f"(CASE WHEN {cond} THEN {then} ELSE {else_} END)"

    if name == "concat":
        parts = [_expr_to_sql_str(a, plan_or_ctx) for a in args]
        return "(" + " || ".join(parts) + ")"

    if name == "strlen":
        if len(args) == 1:
            return f"LENGTH({_expr_to_sql_str(args[0], plan_or_ctx)})"

    if name == "ucase":
        if len(args) == 1:
            return f"UPPER({_expr_to_sql_str(args[0], plan_or_ctx)})"

    if name == "lcase":
        if len(args) == 1:
            return f"LOWER({_expr_to_sql_str(args[0], plan_or_ctx)})"

    if name == "substr" or name == "substring":
        if len(args) >= 2:
            s = _expr_to_sql_str(args[0], plan_or_ctx)
            start = _expr_to_sql_str(args[1], plan_or_ctx)
            if len(args) >= 3:
                length = _expr_to_sql_str(args[2], plan_or_ctx)
                return f"SUBSTRING({s}, {start}, {length})"
            return f"SUBSTRING({s}, {start})"

    if name == "coalesce":
        parts = [_expr_to_sql_str(a, plan_or_ctx) for a in args]
        return f"COALESCE({', '.join(parts)})"

    if name == "in" and len(args) >= 2:
        val = _expr_to_sql_str(args[0], plan_or_ctx)
        opts = [_expr_to_sql_str(a, plan_or_ctx) for a in args[1:]]
        return f"({val} IN ({', '.join(opts)}))"

    if name == "notin" and len(args) >= 2:
        val = _expr_to_sql_str(args[0], plan_or_ctx)
        opts = [_expr_to_sql_str(a, plan_or_ctx) for a in args[1:]]
        return f"({val} NOT IN ({', '.join(opts)}))"

    if name == "abs" and len(args) == 1:
        return f"ABS({_expr_to_sql_str(args[0], plan_or_ctx)})"

    if name == "ceil" and len(args) == 1:
        return f"CEIL({_expr_to_sql_str(args[0], plan_or_ctx)})"

    if name == "floor" and len(args) == 1:
        return f"FLOOR({_expr_to_sql_str(args[0], plan_or_ctx)})"

    if name == "round" and len(args) == 1:
        return f"ROUND({_expr_to_sql_str(args[0], plan_or_ctx)})"

    if name == "replace":
        if len(args) >= 3:
            s = _expr_to_sql_str(args[0], plan_or_ctx)
            pat = _expr_to_sql_str(args[1], plan_or_ctx)
            rep = _expr_to_sql_str(args[2], plan_or_ctx)
            flags = _expr_to_sql_str(args[3], plan_or_ctx) if len(args) >= 4 else None
            if flags and "'i'" in flags:
                return f"REGEXP_REPLACE({s}, {pat}, {rep}, 'gi')"
            return f"REGEXP_REPLACE({s}, {pat}, {rep})"

    if name == "lang":
        if len(args) == 1 and isinstance(args[0], ExprVar):
            lang_col = _resolve_lang_ref(args[0].var, plan_or_ctx)
            return f"COALESCE({lang_col}, '')"
        return "''"

    if name == "datatype":
        if len(args) == 1 and isinstance(args[0], ExprVar):
            var_name = args[0].var
            type_col = _resolve_type_ref(var_name, plan_or_ctx)
            lang_col = _resolve_lang_ref(var_name, plan_or_ctx)
            return (
                f"(CASE"
                f" WHEN {type_col} = 'U' THEN ''"
                f" WHEN {lang_col} IS NOT NULL AND {lang_col} != '' THEN"
                f" 'http://www.w3.org/1999/02/22-rdf-syntax-ns#langString'"
                f" ELSE 'http://www.w3.org/2001/XMLSchema#string'"
                f" END)"
            )
        if len(args) == 1:
            return "'http://www.w3.org/2001/XMLSchema#string'"

    # isNumeric — check if the term text matches a numeric pattern
    if name == "isnumeric":
        if len(args) == 1:
            inner = _expr_to_sql_str(args[0], plan_or_ctx)
            return f"({inner} ~ '^[+-]?(\\d+\\.?\\d*|\\.\\d+)([eE][+-]?\\d+)?$')"

    # sameTerm — strict RDF term equality via UUID
    if name == "sameterm":
        if len(args) == 2:
            if isinstance(args[0], ExprVar) and isinstance(args[1], ExprVar):
                l_uuid = _resolve_uuid_ref(args[0].var, plan_or_ctx)
                r_uuid = _resolve_uuid_ref(args[1].var, plan_or_ctx)
                return f"({l_uuid} = {r_uuid})"
            l = _expr_to_sql_str(args[0], plan_or_ctx)
            r = _expr_to_sql_str(args[1], plan_or_ctx)
            return f"({l} = {r})"

    # UUID — returns a fresh IRI (urn:uuid:...)
    if name == "uuid" and len(args) == 0:
        return "'urn:uuid:' || gen_random_uuid()::text"

    # STRUUID — returns a plain UUID string
    if name == "struuid" and len(args) == 0:
        return "gen_random_uuid()::text"

    # MD5 (built-in)
    if name == "md5" and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        return f"md5({inner})"

    # SHA hash functions (require pgcrypto extension)
    if name in ("sha1", "sha256", "sha384", "sha512") and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        return f"encode(digest({inner}, '{name}'), 'hex')"

    # ENCODE_FOR_URI
    if name == "encode_for_uri" and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        return _encode_for_uri_sql(inner)

    # STRLANG — construct lang-tagged literal; returns the string value
    if name == "strlang" and len(args) == 2:
        return _expr_to_sql_str(args[0], plan_or_ctx)

    # STRDT — construct typed literal; returns the string value
    if name == "strdt" and len(args) == 2:
        return _expr_to_sql_str(args[0], plan_or_ctx)

    # IRI / URI constructor — returns string as-is
    if name in ("iri", "uri") and len(args) == 1:
        return _expr_to_sql_str(args[0], plan_or_ctx)

    # BNODE constructor
    if name == "bnode":
        if len(args) == 0:
            return "'_:b' || gen_random_uuid()::text"
        if len(args) == 1:
            inner = _expr_to_sql_str(args[0], plan_or_ctx)
            return f"'_:b' || md5({inner})"

    # Date/time extraction functions — CAST term_text to TIMESTAMP, then EXTRACT
    _DT_EXTRACT = {
        "year": "YEAR", "month": "MONTH", "day": "DAY",
        "hours": "HOUR", "minutes": "MINUTE", "seconds": "SECOND",
    }
    if name in _DT_EXTRACT and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        pg_field = _DT_EXTRACT[name]
        return f"EXTRACT({pg_field} FROM CAST({inner} AS TIMESTAMP))"

    if name == "tz" or name == "timezone":
        if len(args) == 1:
            inner = _expr_to_sql_str(args[0], plan_or_ctx)
            # Extract timezone string; returns '' for non-TZ values
            return (
                f"COALESCE(REGEXP_REPLACE(CAST({inner} AS TEXT), "
                f"'^.*([+-]\\d{{2}}:\\d{{2}}|Z)$', '\\1'), '')"
            )

    if name == "now" and len(args) == 0:
        return "CAST(NOW() AS TEXT)"

    logger.warning("Unsupported function: %s", name)
    return "NULL"


# ===========================================================================
# ENCODE_FOR_URI helper
# ===========================================================================

_URI_ENCODE_REPLACEMENTS = [
    ('%', '%25'),   # must be first to avoid double-encoding
    (' ', '%20'), ('!', '%21'), ('#', '%23'), ('$', '%24'),
    ('&', '%26'), ("'", '%27'), ('(', '%28'), (')', '%29'),
    ('*', '%2A'), ('+', '%2B'), (',', '%2C'), ('/', '%2F'),
    (':', '%3A'), (';', '%3B'), ('=', '%3D'), ('?', '%3F'),
    ('@', '%40'), ('[', '%5B'), (']', '%5D'),
]


def _encode_for_uri_sql(inner_sql: str) -> str:
    """Generate nested REPLACE() calls for percent-encoding per RFC 3986."""
    result = inner_sql
    for char, encoded in _URI_ENCODE_REPLACEMENTS:
        escaped_char = char.replace("'", "''")
        result = f"REPLACE({result}, '{escaped_char}', '{encoded}')"
    return result


# ===========================================================================
# Aggregate translator
# ===========================================================================

def _agg_to_sql(expr: ExprAggregator, plan_or_ctx) -> str:
    """Translate an aggregator expression to SQL."""
    name = (expr.name or "").upper()
    inner = _expr_to_sql_str(expr.expr, plan_or_ctx) if expr.expr else "*"

    if name == "COUNT":
        if expr.distinct:
            return f"COUNT(DISTINCT {inner})"
        return f"COUNT({inner})"
    elif name == "SUM":
        return f"SUM(CAST({inner} AS NUMERIC))"
    elif name == "AVG":
        return f"AVG(CAST({inner} AS NUMERIC))"
    elif name == "MIN":
        return f"MIN({inner})"
    elif name == "MAX":
        return f"MAX({inner})"
    elif name == "GROUP_CONCAT":
        sep = expr.separator or " "
        return f"STRING_AGG({inner}, '{_esc(sep)}')"
    elif name == "SAMPLE":
        return f"MIN({inner})"

    return f"{name}({inner})"
