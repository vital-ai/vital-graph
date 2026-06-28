"""
SPARQL Expression → SQL string translation.

Handles ExprVar, ExprValue, ExprFunction, and ExprAggregator nodes.
"""

from __future__ import annotations

import logging
from typing import Dict

from .jena_sparql.jena_types import (
    URINode, LiteralNode, BNodeNode,
    ExprVar, ExprValue, ExprFunction, ExprAggregator, Expr,
)
from .jena_sql_ir import RelationPlan, SQLContext, VarSlot
from .jena_sql_helpers import _esc

logger = logging.getLogger(__name__)


# ===========================================================================
# SPARQL regex → PostgreSQL regex translation
# ===========================================================================

def _parse_sparql_flags(flags_sql: str | None) -> str:
    """Extract raw SPARQL flag characters from a SQL-quoted string like "'ism'"."""
    if not flags_sql:
        return ""
    # Strip surrounding quotes
    stripped = flags_sql.strip().strip("'").strip('"')
    return stripped


def sparql_regex_to_pg(subject_sql: str, pattern_sql: str,
                       flags_sql: str | None = None) -> str:
    """Translate SPARQL REGEX(?s, ?pat, flags) to a PostgreSQL ~ expression.

    SPARQL (XPath/XQuery) flags:
        i  – case-insensitive
        s  – dotAll (. matches \\n)
        m  – multiline (^ $ match line boundaries)
        x  – extended (free-spacing / comments)

    PostgreSQL mapping:
        i  → use ~* operator instead of ~
        s  → embed (?s) prefix inside the pattern
        m  → embed (?n) prefix (PG uses 'n' for newline-sensitive, 's' for single-line)
        x  → embed (?x) prefix inside the pattern

    Note: PostgreSQL ARE already supports \\d, \\w, \\s, non-greedy
    quantifiers (*?, +?), and most XPath regex features natively.
    """
    raw_flags = _parse_sparql_flags(flags_sql)

    # Choose operator
    case_insensitive = "i" in raw_flags
    op = "~*" if case_insensitive else "~"

    # Build embedded flag prefix for non-'i' flags
    pg_embedded = ""
    if "s" in raw_flags:
        # PG: (?s) makes . match \\n (single-line / dotAll mode)
        pg_embedded += "s"
    if "m" in raw_flags:
        # PG: (?n) is newline-sensitive matching where ^ $ match at line boundaries
        # In PostgreSQL ARE, (?m) doesn't exist; (?n) is the equivalent
        pg_embedded += "n"
    if "x" in raw_flags:
        # PG: (?x) enables extended (free-spacing) mode
        pg_embedded += "x"

    if pg_embedded:
        # Inject (?flags) prefix into the pattern.
        # Pattern is a SQL string like 'abc' — we prepend inside the quotes.
        if pattern_sql.startswith("'") and pattern_sql.endswith("'"):
            inner = pattern_sql[1:-1]
            pattern_sql = f"'(?{pg_embedded}){inner}'"
        else:
            # Dynamic pattern (column ref or expression) — use concat
            pattern_sql = f"('(?{pg_embedded})' || {pattern_sql})"

    return f"({subject_sql} {op} {pattern_sql})"


def sparql_replace_flags_to_pg(flags_sql: str | None) -> str:
    """Translate SPARQL REPLACE flags to PostgreSQL REGEXP_REPLACE flags parameter.

    SPARQL REPLACE uses the same flag set as REGEX.
    PostgreSQL REGEXP_REPLACE(source, pattern, replacement, flags):
        'g'  – global (replace all occurrences; SPARQL always replaces all)
        'i'  – case-insensitive
        'n'  – newline-sensitive (^ $ match at line boundaries = SPARQL 'm')
        's'  – single-line (. matches \\n = SPARQL 's')
        'x'  – extended

    Note: SPARQL REPLACE always replaces ALL occurrences (like 'g' in PG).
    """
    raw_flags = _parse_sparql_flags(flags_sql)
    pg_flags = "g"  # SPARQL always does global replace
    if "i" in raw_flags:
        pg_flags += "i"
    if "s" in raw_flags:
        pg_flags += "s"  # PG 's' = dotAll (same as SPARQL)
    if "m" in raw_flags:
        pg_flags += "n"  # PG 'n' = newline-sensitive = SPARQL 'm'
    if "x" in raw_flags:
        pg_flags += "x"
    return pg_flags


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
            if name == "divide":
                return f"({l} / NULLIF({r}, 0))"
            return f"({l} {_FUNC_MAP[name]} {r})"

        if name == "regex" and len(args) >= 2:
            s = _expr_to_sql_str_inner(args[0], plan)
            pat = _expr_to_sql_str_inner(args[1], plan)
            flags = _expr_to_sql_str_inner(args[2], plan) if len(args) >= 3 else None
            return sparql_regex_to_pg(s, pat, flags)

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
        # No slot and not a BIND/EXTEND variable → truly unbound → NULL
        if slot is None:
            extend_exprs = getattr(plan_or_ctx, 'extend_exprs', None) or {}
            if var_name not in extend_exprs:
                return "NULL"
        return var_name

    # SQLContext (v1 compat)
    if isinstance(plan_or_ctx, SQLContext):
        b = plan_or_ctx.bindings.get(var_name)
        if b:
            return b.text_col
        return var_name

    return var_name


def _resolve_num_ref(var_name: str, plan_or_ctx) -> str:
    """Resolve a variable to its pre-cast NUMERIC column (term_num or __num).

    The term JOIN subquery includes term_num = CASE WHEN datatype IN (numeric_types)
    THEN CAST(term_text AS NUMERIC) END, so t_alias.term_num is a real column.
    The inner SELECT projects it as var__num, and the outer query references sub.var__num.

    For non-BGP paths (no term JOINs), falls back to an inline safe cast.
    """
    text_col = None
    if isinstance(plan_or_ctx, RelationPlan):
        slot = plan_or_ctx.var_slots.get(var_name)
        if slot and slot.text_col:
            text_col = slot.text_col
    elif isinstance(plan_or_ctx, SQLContext):
        b = plan_or_ctx.bindings.get(var_name)
        if b and b.text_col:
            text_col = b.text_col

    if text_col:
        # Inner BGP path: t_alias.term_text -> t_alias.term_num
        if ".term_text" in text_col:
            return text_col.replace(".term_text", ".term_num")
        # Outer BGP path: var__text -> var__num
        if "__text" in text_col:
            return text_col.replace("__text", "__num")

    # Non-BGP fallback: direct CAST (errors match SPARQL error semantics)
    text_ref = text_col or f"{var_name}"
    return f"CAST(({text_ref}) AS NUMERIC)"


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

_NUMERIC_DATATYPES_V1 = [
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
]

_NUMERIC_DT_SQL_LIST = ", ".join(f"'{dt}'" for dt in _NUMERIC_DATATYPES_V1)


def _safe_numeric_cast(sql_expr: str, datatype_col: str = None) -> str:
    """Wrap a text→NUMERIC cast to return NULL on non-numeric input.

    SPARQL arithmetic on non-numeric values produces an error (unbound).
    Uses the term table's datatype column when available to classify the value.
    Falls back to regex check if no datatype column is provided.
    """
    # Already numeric — __num columns are pre-cast at retrieval time
    if "__num" in sql_expr:
        return sql_expr
    if not datatype_col:
        # Derive datatype column from the text column pattern
        if "__text" in sql_expr:
            datatype_col = sql_expr.replace("__text", "__datatype")
        elif ".term_text" in sql_expr:
            datatype_col = sql_expr.replace(".term_text", ".datatype_id")

    if datatype_col:
        if "datatype_id" in datatype_col:
            from .jena_sql_emit import _dt_ids_for_uris
            id_list = _dt_ids_for_uris(_NUMERIC_DATATYPES_V1)
        else:
            id_list = _NUMERIC_DT_SQL_LIST
        return (
            f"(CASE WHEN {datatype_col} IN ({id_list}) "
            f"THEN CAST(({sql_expr}) AS NUMERIC) END)"
        )
    # Fallback: no datatype column available (non-BGP path).
    # Use a simple numeric check that sqlglot can parse (avoid ~ regex operator).
    # translate() strips all numeric chars; if empty, the string is all-numeric.
    return (
        f"(CASE WHEN LENGTH(TRANSLATE(({sql_expr}), '0123456789.-+eE', '')) = 0 "
        f"AND LENGTH(({sql_expr})) > 0 "
        f"THEN CAST(({sql_expr}) AS NUMERIC) END)"
    )


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
        # Use pre-cast __num column for the variable side
        if r_dt and not l_dt:
            if "__num" in left_sql:
                pass  # already numeric from pre-cast
            elif "__text" in left_sql:
                left_sql = left_sql.replace("__text", "__num")
            elif ".term_text" in left_sql:
                left_sql = left_sql.replace(".term_text", ".term_num")
            else:
                left_sql = f"CAST({left_sql} AS NUMERIC)"
        elif l_dt and not r_dt:
            if "__num" in right_sql:
                pass  # already numeric from pre-cast
            elif "__text" in right_sql:
                right_sql = right_sql.replace("__text", "__num")
            elif ".term_text" in right_sql:
                right_sql = right_sql.replace(".term_text", ".term_num")
            else:
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
        if name in ("add", "subtract", "multiply", "divide"):
            # Arithmetic: resolve variables to pre-cast __num columns
            from .jena_sparql.jena_types import ExprVar as _EV, ExprValue as _EVa
            def _arith_arg(a):
                if isinstance(a, _EV):
                    return _resolve_num_ref(a.var, plan_or_ctx)
                elif isinstance(a, _EVa):
                    return _expr_to_sql_str(a, plan_or_ctx)
                else:
                    # Non-variable (e.g. str(?x)): result may be text,
                    # Safe cast: returns NULL for non-numeric strings
                    # (matches SPARQL error propagation semantics)
                    inner = _expr_to_sql_str(a, plan_or_ctx)
                    return (f"CASE WHEN ({inner}) ~ '^-?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?$'"
                            f" THEN CAST(({inner}) AS NUMERIC) ELSE NULL END")
            l = _arith_arg(args[0])
            r = _arith_arg(args[1])
        elif name in ("gt", "lt", "ge", "le", "eq", "ne"):
            l = _expr_to_sql_str(args[0], plan_or_ctx)
            r = _expr_to_sql_str(args[1], plan_or_ctx)
            l, r = _apply_typed_casts(args[0], args[1], l, r)
        else:
            l = _expr_to_sql_str(args[0], plan_or_ctx)
            r = _expr_to_sql_str(args[1], plan_or_ctx)
        if name == "divide":
            return f"({l} / NULLIF({r}, 0))"
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
            flags = _expr_to_sql_str(args[2], plan_or_ctx) if len(args) >= 3 else None
            return sparql_regex_to_pg(s, pat, flags)

    if name == "if":
        if len(args) == 3:
            cond = _expr_to_sql_str(args[0], plan_or_ctx)
            then = _expr_to_sql_str(args[1], plan_or_ctx)
            else_ = _expr_to_sql_str(args[2], plan_or_ctx)
            # Cast condition to boolean — SPARQL IF uses effective boolean value
            # which allows non-boolean expressions; PostgreSQL CASE requires boolean
            return f"(CASE WHEN CAST(({cond}) AS BOOLEAN) THEN {then} ELSE {else_} END)"

    if name == "concat":
        if not args:
            return "''"
        parts = [_expr_to_sql_str(a, plan_or_ctx) for a in args]
        return "(" + " || ".join(parts) + ")"

    # STRDT(lexical, datatype) — returns the lexical form as a typed literal
    # The actual datatype annotation is handled at the result mapping level
    if name == "strdt" and len(args) >= 2:
        return _expr_to_sql_str(args[0], plan_or_ctx)

    # STRLANG(lexical, lang) — returns the lexical form as a lang-tagged literal
    if name == "strlang" and len(args) >= 2:
        return _expr_to_sql_str(args[0], plan_or_ctx)

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
        if not args:
            return "NULL"
        parts = [f"CAST({_expr_to_sql_str(a, plan_or_ctx)} AS TEXT)" for a in args]
        return f"COALESCE({', '.join(parts)})"

    if name == "in" and len(args) >= 2:
        val = _expr_to_sql_str(args[0], plan_or_ctx)
        opts = [_expr_to_sql_str(a, plan_or_ctx) for a in args[1:]]
        return f"({val} IN ({', '.join(opts)}))"

    if name == "notin" and len(args) >= 2:
        val = _expr_to_sql_str(args[0], plan_or_ctx)
        opts = [_expr_to_sql_str(a, plan_or_ctx) for a in args[1:]]
        return f"({val} NOT IN ({', '.join(opts)}))"

    # ABS / CEIL / FLOOR / ROUND — resolve to pre-cast __num column
    if name in ("abs", "ceil", "floor", "round") and len(args) == 1:
        from .jena_sparql.jena_types import ExprVar as _EV
        if isinstance(args[0], _EV):
            arg_sql = _resolve_num_ref(args[0].var, plan_or_ctx)
        else:
            arg_sql = _expr_to_sql_str(args[0], plan_or_ctx)
        return f"{name.upper()}({arg_sql})"

    if name == "replace":
        if len(args) >= 3:
            s = _expr_to_sql_str(args[0], plan_or_ctx)
            pat = _expr_to_sql_str(args[1], plan_or_ctx)
            rep = _expr_to_sql_str(args[2], plan_or_ctx)
            flags_sql = _expr_to_sql_str(args[3], plan_or_ctx) if len(args) >= 4 else None
            pg_flags = sparql_replace_flags_to_pg(flags_sql)
            return f"REGEXP_REPLACE({s}, {pat}, {rep}, '{pg_flags}')"

    if name == "lang":
        if len(args) == 1 and isinstance(args[0], ExprVar):
            lang_col = _resolve_lang_ref(args[0].var, plan_or_ctx)
            return f"COALESCE({lang_col}, '')"

    if name == "langmatches":
        if len(args) == 2:
            lang_expr = _expr_to_sql_str(args[0], plan_or_ctx)
            pattern = _expr_to_sql_str(args[1], plan_or_ctx)
            # LANGMATCHES(lang, '*') → lang IS NOT NULL AND lang != ''
            # LANGMATCHES(lang, 'en') → lang ILIKE 'en' OR lang ILIKE 'en-%'
            return (
                f"(CASE WHEN {pattern} = '*' "
                f"THEN ({lang_expr} IS NOT NULL AND {lang_expr} != '') "
                f"ELSE (LOWER({lang_expr}) = LOWER({pattern}) "
                f"OR LOWER({lang_expr}) LIKE LOWER({pattern}) || '-%') END)"
            )
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

    if name == "tz" and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        # TZ() returns the timezone string (e.g. 'Z', '-08:00') or '' if none
        return (
            f"(CASE WHEN CAST({inner} AS TEXT) ~ '([+-]\\d{{2}}:\\d{{2}}|Z)$' "
            f"THEN REGEXP_REPLACE(CAST({inner} AS TEXT), "
            f"'^.*([+-]\\d{{2}}:\\d{{2}}|Z)$', '\\1') "
            f"ELSE '' END)"
        )

    if name == "timezone" and len(args) == 1:
        inner = _expr_to_sql_str(args[0], plan_or_ctx)
        # TIMEZONE() returns an xsd:dayTimeDuration like 'PT0S' for Z, '-PT8H' for -08:00
        # For no timezone, it's an error (unbound) — return NULL
        return (
            f"(CASE "
            f"WHEN CAST({inner} AS TEXT) ~ 'Z$' THEN 'PT0S' "
            f"WHEN CAST({inner} AS TEXT) ~ '[+-]\\d{{2}}:\\d{{2}}$' THEN "
            f"REGEXP_REPLACE(CAST({inner} AS TEXT), "
            f"'^.*([+-])(\\d{{2}}):(\\d{{2}})$', "
            f"'\\1PT\\2H\\3M') "
            f"ELSE NULL END)"
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
