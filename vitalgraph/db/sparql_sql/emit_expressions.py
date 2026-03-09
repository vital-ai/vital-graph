"""
v2 Expression-to-SQL converter.

Converts sidecar AST Expr nodes to SQL expression strings. This is a
copy-then-revise of the v1 jena_sql_expressions.py, adapted to work
with EmitContext and TypeRegistry instead of RelationPlan.

Initially a thin wrapper that handles the core expression types. Will be
expanded to cover all ~40 SPARQL functions as Phase 6 progresses.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, ExprAggregator, ExprExists,
    URINode, LiteralNode, BNodeNode, VarNode,
    SortCondition,
)

from .emit_context import EmitContext
from .collect import _esc

logger = logging.getLogger(__name__)

# XSD namespace
XSD = "http://www.w3.org/2001/XMLSchema#"

# Numeric datatypes for CAST
_NUMERIC_DATATYPES = frozenset({
    f"{XSD}integer", f"{XSD}decimal", f"{XSD}double", f"{XSD}float",
    f"{XSD}int", f"{XSD}long", f"{XSD}short", f"{XSD}byte",
    f"{XSD}nonNegativeInteger", f"{XSD}positiveInteger",
    f"{XSD}nonPositiveInteger", f"{XSD}negativeInteger",
    f"{XSD}unsignedInt", f"{XSD}unsignedLong", f"{XSD}unsignedShort",
    f"{XSD}unsignedByte",
})


def expr_to_sql(expr, ctx: EmitContext) -> Optional[str]:
    """Convert a sidecar AST Expr to a SQL expression string.

    Args:
        expr: An Expr node from the sidecar AST.
        ctx: The EmitContext for variable resolution.

    Returns:
        SQL expression string, or None if the expression can't be converted.
    """
    if expr is None:
        return None

    if isinstance(expr, ExprVar):
        return _var_to_sql(expr, ctx)

    if isinstance(expr, ExprValue):
        return _value_to_sql(expr)

    if isinstance(expr, ExprFunction):
        return _function_to_sql(expr, ctx)

    if isinstance(expr, ExprAggregator):
        return _aggregator_to_sql(expr, ctx)

    if isinstance(expr, ExprExists):
        return _exists_to_sql(expr, ctx)

    if isinstance(expr, SortCondition):
        inner = expr_to_sql(expr.expr, ctx)
        if inner:
            return f"{inner} {'DESC' if expr.direction == 'DESC' else 'ASC'}"
        return None

    logger.warning("Unknown expression type: %s", type(expr).__name__)
    return None


def _var_to_sql(expr: ExprVar, ctx: EmitContext) -> Optional[str]:
    """Convert a variable reference to its SQL column name."""
    info = ctx.types.get(expr.var)
    if info and info.text_col:
        return info.text_col
    # Rule 1: NULL = unbound (§10.5). Variable not in registry.
    return "NULL"


def _value_to_sql(expr: ExprValue) -> Optional[str]:
    """Convert a constant value to a SQL literal."""
    node = expr.node
    if node is None:
        return "NULL"

    if isinstance(node, URINode):
        return f"'{_esc(node.value)}'"

    if isinstance(node, LiteralNode):
        val = node.value
        dt = node.datatype or ""

        # Boolean
        if dt == f"{XSD}boolean":
            return "TRUE" if val.lower() in ("true", "1") else "FALSE"

        # Numeric types — emit as bare numbers
        if dt in _NUMERIC_DATATYPES:
            try:
                if "." in val or "e" in val.lower():
                    return str(float(val))
                return str(int(val))
            except ValueError:
                pass

        # String / other — emit as quoted literal
        return f"'{_esc(val)}'"

    if isinstance(node, BNodeNode):
        return f"'_:{_esc(node.label)}'"

    return "NULL"


def _is_numeric_expr(expr, ctx: EmitContext) -> bool:
    """Check if an expression is known to be numeric at compile time.

    BGP variables all have num_col (a CASE WHEN that returns NULL for
    non-numeric values), but that doesn't mean the variable IS numeric —
    it could be a URI.  Only trust typed_lane='num' which is set for
    computed variables (BIND, aggregates) known to produce numbers.
    """
    if isinstance(expr, ExprValue) and expr.node and isinstance(expr.node, LiteralNode):
        return expr.node.datatype in _NUMERIC_DATATYPES
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if info and info.typed_lane == "num":
            return True
    if isinstance(expr, ExprFunction):
        fname = (expr.name or "").lower()
        if fname in ("add", "subtract", "multiply", "divide", "unaryminus",
                      "abs", "ceil", "floor", "round", "strlen", "rand",
                      "year", "month", "day", "hours", "minutes", "seconds"):
            return True
        if expr.function_iri and expr.function_iri in _XSD_CAST_MAP:
            sql_type = _XSD_CAST_MAP[expr.function_iri]
            if sql_type not in ("TEXT", "BOOLEAN"):
                return True
        # Recurse: COALESCE/IF is numeric if any argument is numeric
        if fname in ("coalesce", "if") and expr.args:
            return any(_is_numeric_expr(a, ctx) for a in expr.args)
    return False


def _cmp_pair(left, right, ctx: EmitContext):
    """Return (left_sql, right_sql) using numeric columns when appropriate.

    If either side is numeric, both sides are converted to their numeric
    SQL representations to avoid text=integer type mismatches.
    """
    left_num = _is_numeric_expr(left, ctx)
    right_num = _is_numeric_expr(right, ctx)

    if left_num or right_num:
        a = _numeric_arg(left, ctx)
        b = _numeric_arg(right, ctx)
        return a, b
    else:
        a = expr_to_sql(left, ctx)
        b = expr_to_sql(right, ctx)
        return a, b


_XSD_CAST_MAP = {
    f"{XSD}integer": "INTEGER",
    f"{XSD}int": "INTEGER",
    f"{XSD}long": "BIGINT",
    f"{XSD}short": "SMALLINT",
    f"{XSD}byte": "SMALLINT",
    f"{XSD}decimal": "NUMERIC",
    f"{XSD}double": "DOUBLE PRECISION",
    f"{XSD}float": "REAL",
    f"{XSD}boolean": "BOOLEAN",
    f"{XSD}string": "TEXT",
    f"{XSD}dateTime": "TIMESTAMP",
    f"{XSD}date": "DATE",
    f"{XSD}nonNegativeInteger": "INTEGER",
    f"{XSD}positiveInteger": "INTEGER",
    f"{XSD}nonPositiveInteger": "INTEGER",
    f"{XSD}negativeInteger": "INTEGER",
    f"{XSD}unsignedInt": "INTEGER",
    f"{XSD}unsignedLong": "BIGINT",
    f"{XSD}unsignedShort": "SMALLINT",
    f"{XSD}unsignedByte": "SMALLINT",
}


def _function_to_sql(expr: ExprFunction, ctx: EmitContext) -> Optional[str]:
    """Convert a function call to SQL."""
    fname = (expr.name or "").lower()
    args = expr.args or []

    # --- XSD cast functions (xsd:integer(?x), xsd:double(?x), etc.) ---
    if expr.function_iri and expr.function_iri in _XSD_CAST_MAP:
        sql_type = _XSD_CAST_MAP[expr.function_iri]
        if args:
            num_col = None
            text_col = None
            bool_col = None
            if isinstance(args[0], ExprVar):
                info = ctx.types.get(args[0].var)
                if info:
                    num_col = info.num_col
                    text_col = info.text_col
                    # bool_col: SQL boolean from __bool companion
                    if info.sql_name:
                        bool_col = f"{info.sql_name}__bool"
            if text_col is None:
                text_col = expr_to_sql(args[0], ctx)
            if text_col:
                # XSD lexical form regexes per type
                _INT_RE = "'^[-+]?[0-9]+$'"
                _DEC_RE = "'^[-+]?[0-9]*\\.?[0-9]+$'"
                _FLOAT_RE = ("'^[-+]?(\\d+\\.?\\d*|\\.\\d+)"
                             "([eE][-+]?\\d+)?$'")
                # Boolean cast: accept string true/false/0/1 AND numeric 0/nonzero
                if sql_type == "BOOLEAN":
                    parts = "CASE "
                    if num_col:
                        parts += (f"WHEN {num_col} IS NOT NULL "
                                  f"THEN ({num_col} != 0) ")
                    parts += (f"WHEN LOWER({text_col}) IN ('true','1') THEN TRUE "
                              f"WHEN LOWER({text_col}) IN ('false','0') THEN FALSE "
                              f"ELSE NULL END")
                    return parts
                # Integer types: typed bool→0/1, typed num→TRUNC,
                # plain string only if strict integer format
                if sql_type in ("INTEGER", "BIGINT", "SMALLINT"):
                    bool_branch = ""
                    if bool_col:
                        bool_branch = (f"WHEN {bool_col} IS NOT NULL "
                                       f"THEN CAST(({bool_col})::int AS {sql_type}) ")
                    num_branch = ""
                    if num_col:
                        num_branch = (f"WHEN {num_col} IS NOT NULL "
                                      f"THEN CAST(TRUNC({num_col}) AS {sql_type}) ")
                    return (f"CASE "
                            f"{bool_branch}"
                            f"{num_branch}"
                            f"WHEN {text_col} ~ {_INT_RE} "
                            f"THEN CAST({text_col} AS {sql_type}) "
                            f"ELSE NULL END")
                # Decimal: typed bool→0/1, typed num passthrough,
                # plain string must match decimal format (no sci notation)
                if sql_type == "NUMERIC":
                    bool_branch = ""
                    if bool_col:
                        bool_branch = (f"WHEN {bool_col} IS NOT NULL "
                                       f"THEN CAST(({bool_col})::int AS {sql_type}) ")
                    if num_col:
                        return (f"COALESCE({num_col}, "
                                f"CASE {bool_branch}"
                                f"WHEN {text_col} ~ {_DEC_RE} "
                                f"THEN CAST({text_col} AS {sql_type}) "
                                f"ELSE NULL END)")
                    return (f"CASE {bool_branch}"
                            f"WHEN {text_col} ~ {_DEC_RE} "
                            f"THEN CAST({text_col} AS {sql_type}) "
                            f"ELSE NULL END")
                # Float/double: typed bool→0/1, typed num passthrough,
                # plain string accepts full numeric+sci format
                if sql_type in ("DOUBLE PRECISION", "REAL"):
                    bool_branch = ""
                    if bool_col:
                        bool_branch = (f"WHEN {bool_col} IS NOT NULL "
                                       f"THEN CAST(({bool_col})::int AS {sql_type}) ")
                    if num_col:
                        return (f"COALESCE(CAST({num_col} AS {sql_type}), "
                                f"CASE {bool_branch}"
                                f"WHEN {text_col} ~ {_FLOAT_RE} "
                                f"THEN CAST({text_col} AS {sql_type}) "
                                f"ELSE NULL END)")
                    return (f"CASE {bool_branch}"
                            f"WHEN {text_col} ~ {_FLOAT_RE} "
                            f"THEN CAST({text_col} AS {sql_type}) "
                            f"ELSE NULL END")
                # xsd:string: canonical value forms
                if sql_type == "TEXT":
                    parts = "CASE "
                    if bool_col:
                        parts += (f"WHEN {bool_col} IS NOT NULL "
                                  f"THEN CASE WHEN {bool_col} "
                                  f"THEN 'true' ELSE 'false' END ")
                    if num_col:
                        parts += (f"WHEN {num_col} IS NOT NULL "
                                  f"THEN CASE WHEN {num_col} = TRUNC({num_col}) "
                                  f"THEN CAST(CAST({num_col} AS BIGINT) AS TEXT) "
                                  f"ELSE CAST({num_col} AS TEXT) END ")
                    parts += f"ELSE CAST({text_col} AS TEXT) END"
                    return parts
                # Other types: plain cast
                return f"CAST({text_col} AS {sql_type})"
        return None

    # --- Comparison operators ---
    # Use numeric columns when either side is numeric to avoid text=integer errors
    if fname in ("eq", "numericequal") and len(args) == 2:
        a, b = _cmp_pair(args[0], args[1], ctx)
        if a and b:
            return f"({a} = {b})"

    if fname in ("ne", "numericnotequal") and len(args) == 2:
        a, b = _cmp_pair(args[0], args[1], ctx)
        if a and b:
            return f"({a} != {b})"

    if fname in ("lt", "numericlessthan") and len(args) == 2:
        a, b = _cmp_pair(args[0], args[1], ctx)
        if a and b:
            return f"({a} < {b})"

    if fname in ("gt", "numericgreaterthan") and len(args) == 2:
        a, b = _cmp_pair(args[0], args[1], ctx)
        if a and b:
            return f"({a} > {b})"

    if fname in ("le",) and len(args) == 2:
        a, b = _cmp_pair(args[0], args[1], ctx)
        if a and b:
            return f"({a} <= {b})"

    if fname in ("ge",) and len(args) == 2:
        a, b = _cmp_pair(args[0], args[1], ctx)
        if a and b:
            return f"({a} >= {b})"

    # --- Logical operators ---
    if fname == "and" and len(args) == 2:
        a, b = expr_to_sql(args[0], ctx), expr_to_sql(args[1], ctx)
        if a and b:
            return f"({a} AND {b})"

    if fname == "or" and len(args) == 2:
        a, b = expr_to_sql(args[0], ctx), expr_to_sql(args[1], ctx)
        if a and b:
            return f"({a} OR {b})"

    if fname in ("not", "unarynot") and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return f"NOT ({a})"

    # --- Arithmetic ---
    if fname == "add" and len(args) == 2:
        # SPARQL + is strictly numeric. Non-numeric operands → error (NULL).
        a, b = _numeric_arg(args[0], ctx), _numeric_arg(args[1], ctx)
        if a and b:
            return f"({a} + {b})"

    if fname == "subtract" and len(args) == 2:
        a, b = _numeric_arg(args[0], ctx), _numeric_arg(args[1], ctx)
        if a and b:
            return f"({a} - {b})"

    if fname == "multiply" and len(args) == 2:
        a, b = _numeric_arg(args[0], ctx), _numeric_arg(args[1], ctx)
        if a and b:
            return f"({a} * {b})"

    if fname == "divide" and len(args) == 2:
        a, b = _numeric_arg(args[0], ctx), _numeric_arg(args[1], ctx)
        if a and b:
            return f"({a}::NUMERIC / NULLIF({b}::NUMERIC, 0))"

    if fname == "unaryminus" and len(args) == 1:
        a = _numeric_arg(args[0], ctx)
        if a:
            return f"(-{a})"

    # --- String functions ---
    if fname == "str" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return f"CAST({a} AS TEXT)"

    if fname == "strlen" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(args[0], ctx, f"LENGTH({a})")

    if fname == "ucase" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(args[0], ctx, f"UPPER({a})")

    if fname == "lcase" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(args[0], ctx, f"LOWER({a})")

    if fname == "contains" and len(args) == 2:
        a, b = expr_to_sql(args[0], ctx), expr_to_sql(args[1], ctx)
        if a and b:
            result = f"(POSITION({b} IN {a}) > 0)"
            return _require_literal(args[0], ctx, result)

    if fname == "strstarts" and len(args) == 2:
        a, b = expr_to_sql(args[0], ctx), expr_to_sql(args[1], ctx)
        if a and b:
            result = f"(LEFT({a}, LENGTH({b})) = {b})"
            return _require_literal(args[0], ctx, result)

    if fname == "strends" and len(args) == 2:
        a, b = expr_to_sql(args[0], ctx), expr_to_sql(args[1], ctx)
        if a and b:
            result = f"(RIGHT({a}, LENGTH({b})) = {b})"
            return _require_literal(args[0], ctx, result)

    if fname == "concat":
        if not args:
            return "''"
        parts = [expr_to_sql(a, ctx) for a in args]
        if all(parts):
            # Guard: reject non-string typed literal arguments (e.g. numeric).
            # xsd:string and rdf:langString are OK.
            _XSD_STR = f"{XSD}string"
            _RDF_LS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
            guards = []
            for arg_expr in args:
                if isinstance(arg_expr, ExprVar):
                    info = ctx.types.get(arg_expr.var)
                    if info and info.dt_col:
                        guards.append(
                            f"({info.dt_col} IS NOT NULL "
                            f"AND {info.dt_col} != '' "
                            f"AND {info.dt_col} != '{_XSD_STR}' "
                            f"AND {info.dt_col} != '{_RDF_LS}')")
            sql = f"CONCAT({', '.join(parts)})"
            if guards:
                sql = f"CASE WHEN {' OR '.join(guards)} THEN NULL ELSE {sql} END"
            return sql

    if fname == "substr":
        if len(args) >= 2:
            s = expr_to_sql(args[0], ctx)
            start = expr_to_sql(args[1], ctx)
            if s and start:
                if len(args) >= 3:
                    length = expr_to_sql(args[2], ctx)
                    if length:
                        result = f"SUBSTRING({s} FROM {start} FOR {length})"
                        return _require_literal(args[0], ctx, result)
                return _require_literal(
                    args[0], ctx, f"SUBSTRING({s} FROM {start})")

    if fname == "replace" and len(args) >= 3:
        s = expr_to_sql(args[0], ctx)
        pat = expr_to_sql(args[1], ctx)
        rep = expr_to_sql(args[2], ctx)
        if s and pat and rep:
            # Convert SPARQL $N backreferences to PostgreSQL \N format
            rep = f"REPLACE({rep}, '$1', '\\1')"
            rep = f"REPLACE({rep}, '$2', '\\2')"
            rep = f"REPLACE({rep}, '$3', '\\3')"
            flags = "'g'"
            if len(args) >= 4:
                f_sql = expr_to_sql(args[3], ctx)
                if f_sql:
                    # Merge SPARQL flags with global 'g'
                    raw = f_sql.strip("'")
                    flags = f"'g{raw}'"
            result = f"regexp_replace({s}, {pat}, {rep}, {flags})"
            return _typed_literal_guard(args[0], ctx, result)

    if fname == "encode_for_uri" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            # Percent-encode each character: unreserved chars stay as-is,
            # others get their UTF-8 bytes encoded as %XX.
            # Works correctly for all Unicode including non-BMP (emojis).
            result = (f"(SELECT string_agg("
                    f"CASE WHEN c ~ '[A-Za-z0-9_.~-]' THEN c "
                    f"ELSE UPPER(regexp_replace("
                    f"encode(convert_to(c, 'UTF8'), 'hex'), "
                    f"'(..)', '%' || '\\1', 'g')) "
                    f"END, '' ORDER BY ordinality) "
                    f"FROM regexp_split_to_table({a}, '') "
                    f"WITH ORDINALITY AS t(c, ordinality))")
            return _require_literal(args[0], ctx, result)

    if fname in ("strbefore", "strafter") and len(args) == 2:
        a = expr_to_sql(args[0], ctx)
        b = expr_to_sql(args[1], ctx)
        if a and b:
            if fname == "strbefore":
                result = (f"CASE WHEN POSITION({b} IN {a}) > 0 "
                          f"THEN LEFT({a}, POSITION({b} IN {a}) - 1) "
                          f"WHEN {b} = '' THEN '' "
                          f"ELSE '' END")
            else:  # strafter
                result = (f"CASE WHEN POSITION({b} IN {a}) > 0 "
                          f"THEN SUBSTRING({a} FROM POSITION({b} IN {a}) + LENGTH({b})) "
                          f"WHEN {b} = '' THEN {a} "
                          f"ELSE '' END")

            # Lang compatibility guard: if pattern has a lang tag,
            # arg1 must have the same lang tag, otherwise error (NULL).
            pat_lang = _get_literal_lang(args[1])
            if pat_lang:
                if isinstance(args[0], ExprVar):
                    info = ctx.types.get(args[0].var)
                    if info and info.lang_col:
                        result = (f"CASE WHEN {info.lang_col} IS NULL "
                                  f"OR LOWER({info.lang_col}) != "
                                  f"'{pat_lang.lower()}' "
                                  f"THEN NULL ELSE {result} END")
                    else:
                        # No lang column info — plain literal can't match
                        # a lang-tagged pattern
                        result = "NULL"

            return _typed_literal_guard(args[0], ctx, result,
                                        allow_xsd_string=True)

    # --- Type testing ---
    if fname == "bound" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return f"({a} IS NOT NULL)"

    if fname in ("isiri", "isuri") and len(args) == 1:
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.type_col:
                return f"({info.type_col} = 'U')"
        return "FALSE"

    if fname == "isblank" and len(args) == 1:
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.type_col:
                return f"({info.type_col} = 'B')"
        return "FALSE"

    if fname == "isliteral" and len(args) == 1:
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.type_col:
                return f"({info.type_col} = 'L')"
        return "FALSE"

    if fname == "isnumeric" and len(args) == 1:
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.num_col:
                return f"({info.num_col} IS NOT NULL)"
        return "FALSE"

    # --- REGEX ---
    if fname == "regex" and len(args) >= 2:
        s = expr_to_sql(args[0], ctx)
        pat = expr_to_sql(args[1], ctx)
        if s and pat:
            if len(args) >= 3:
                flags = expr_to_sql(args[2], ctx)
                if flags and "'i'" in flags.lower():
                    return f"({s} ~* {pat})"
            return f"({s} ~ {pat})"

    # --- Accessors ---
    if fname == "lang" and len(args) == 1:
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.lang_col:
                return f"COALESCE({info.lang_col}, '')"
        return "''"

    if fname == "datatype" and len(args) == 1:
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.dt_col:
                return info.dt_col
        # Handle constant literals: datatype(10) → xsd:integer
        if isinstance(args[0], ExprValue) and isinstance(args[0].node, LiteralNode):
            dt = args[0].node.datatype
            if dt:
                return f"'{dt.replace(chr(39), chr(39)+chr(39))}'"
        return "NULL"

    if fname == "langmatches" and len(args) == 2:
        a = expr_to_sql(args[0], ctx)
        b = expr_to_sql(args[1], ctx)
        if a and b:
            if b == "'*'":
                return f"({a} IS NOT NULL AND {a} != '')"
            return f"(LOWER({a}) = LOWER({b}))"

    # --- Conditional ---
    if fname == "if" and len(args) == 3:
        cond = expr_to_sql(args[0], ctx)
        then_num = _is_numeric_expr(args[1], ctx)
        else_num = _is_numeric_expr(args[2], ctx)
        # When branches have mixed types, promote both to numeric
        # to avoid PostgreSQL "CASE types X and Y cannot be matched".
        if then_num or else_num:
            then_val = _numeric_arg(args[1], ctx)
            else_val = _numeric_arg(args[2], ctx)
        else:
            then_val = expr_to_sql(args[1], ctx)
            else_val = expr_to_sql(args[2], ctx)
        if cond and then_val and else_val:
            # Numeric conditions (e.g. 1/0) need special handling:
            # - NULL (error) → propagate as NULL (SPARQL error semantics)
            # - != 0 → true, = 0 → false
            if _is_numeric_expr(args[0], ctx):
                return (f"CASE WHEN ({cond}) IS NULL THEN NULL "
                        f"WHEN ({cond}) != 0 THEN {then_val} "
                        f"ELSE {else_val} END")
            # Rule 6: type guards for error propagation (§10.5).
            # SPARQL §17.4.1: IF(error, t, e) → error.
            return (f"CASE WHEN ({cond}) IS NULL THEN NULL "
                    f"WHEN ({cond}) THEN {then_val} "
                    f"ELSE {else_val} END")

    if fname == "coalesce":
        if not args:
            return "NULL"
        parts = [expr_to_sql(a, ctx) for a in args]
        valid = [p for p in parts if p]
        if valid:
            # Cast all to TEXT if mixing text variables with numeric literals
            has_text = any(isinstance(a, ExprVar) and not _is_numeric_expr(a, ctx)
                          for a in args)
            has_num = any(_is_numeric_expr(a, ctx) or
                         (isinstance(a, ExprValue) and hasattr(a, 'node') and
                          isinstance(a.node, LiteralNode) and
                          a.node.datatype in _NUMERIC_DATATYPES)
                         for a in args)
            if has_text and has_num:
                valid = [f"CAST({p} AS TEXT)" for p in valid]
            return f"COALESCE({', '.join(valid)})"

    # --- Constructors ---
    if fname in ("iri", "uri") and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a and ctx.base_uri:
            # Resolve relative IRI against base URI
            # If the value doesn't look like an absolute URI, prepend base
            return (f"CASE WHEN {a} ~ '^[a-zA-Z][a-zA-Z0-9+.-]*:' "
                    f"THEN {a} "
                    f"ELSE CONCAT('{ctx.base_uri}', {a}) END")
        return a

    if fname == "bnode" and len(args) <= 1:
        if args:
            a = expr_to_sql(args[0], ctx)
            return f"CONCAT('_:', {a})" if a else "'_:b0'"
        return "'_:b0'"

    if fname == "strdt" and len(args) == 2:
        a = expr_to_sql(args[0], ctx)
        if a and isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info:
                # STRDT requires simple literal — error if input has lang tag,
                # non-string datatype, or is not a literal (URI, bnode).
                # RDF 1.1: xsd:string IS a simple literal, so allow it.
                _XSD_STR = "http://www.w3.org/2001/XMLSchema#string"
                guards = []
                if info.type_col:
                    guards.append(f"{info.type_col} != 'L'")
                if info.lang_col:
                    guards.append(f"({info.lang_col} IS NOT NULL AND {info.lang_col} != '')")
                if info.dt_col:
                    guards.append(f"({info.dt_col} IS NOT NULL AND {info.dt_col} != '' "
                                  f"AND {info.dt_col} != '{_XSD_STR}')")
                if guards:
                    cond = " OR ".join(guards)
                    return f"CASE WHEN {cond} THEN NULL ELSE {a} END"
        return a

    if fname == "strlang" and len(args) == 2:
        a = expr_to_sql(args[0], ctx)
        if a and isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info:
                # STRLANG requires simple literal — error if input has lang tag,
                # non-string datatype, or is not a literal.
                # RDF 1.1: xsd:string IS a simple literal, so allow it.
                _XSD_STR = "http://www.w3.org/2001/XMLSchema#string"
                guards = []
                if info.type_col:
                    guards.append(f"{info.type_col} != 'L'")
                if info.lang_col:
                    guards.append(f"({info.lang_col} IS NOT NULL AND {info.lang_col} != '')")
                if info.dt_col:
                    guards.append(f"({info.dt_col} IS NOT NULL AND {info.dt_col} != '' "
                                  f"AND {info.dt_col} != '{_XSD_STR}')")
                if guards:
                    cond = " OR ".join(guards)
                    return f"CASE WHEN {cond} THEN NULL ELSE {a} END"
        return a

    # --- Math ---
    if fname == "abs" and len(args) == 1:
        a = _numeric_arg(args[0], ctx)
        if a:
            return f"ABS({a})"

    if fname == "ceil" and len(args) == 1:
        a = _numeric_arg(args[0], ctx)
        if a:
            return f"CEIL({a})"

    if fname == "floor" and len(args) == 1:
        a = _numeric_arg(args[0], ctx)
        if a:
            return f"FLOOR({a})"

    if fname == "round" and len(args) == 1:
        a = _numeric_arg(args[0], ctx)
        if a:
            return f"ROUND({a})"

    # --- Hash functions ---
    if fname == "md5" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(args[0], ctx, f"MD5({a})")

    if fname == "sha1" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(
                args[0], ctx, f"ENCODE(DIGEST({a}, 'sha1'), 'hex')")

    if fname == "sha256" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(
                args[0], ctx, f"ENCODE(DIGEST({a}, 'sha256'), 'hex')")

    if fname == "sha384" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(
                args[0], ctx, f"ENCODE(DIGEST({a}, 'sha384'), 'hex')")

    if fname == "sha512" and len(args) == 1:
        a = expr_to_sql(args[0], ctx)
        if a:
            return _require_literal(
                args[0], ctx, f"ENCODE(DIGEST({a}, 'sha512'), 'hex')")

    # --- DateTime extraction ---
    if fname in ("year", "month", "day", "hours", "minutes", "seconds"):
        if len(args) == 1:
            # Use the __dt companion column if available
            dt_sql = None
            if isinstance(args[0], ExprVar):
                info = ctx.types.get(args[0].var)
                if info:
                    # Find dt companion
                    sn = info.sql_name
                    dt_sql = f"{sn}__dt" if sn else None
            if dt_sql is None:
                dt_sql = expr_to_sql(args[0], ctx)
            if dt_sql:
                pg_field = {
                    "year": "YEAR", "month": "MONTH", "day": "DAY",
                    "hours": "HOUR", "minutes": "MINUTE",
                    "seconds": "SECOND",
                }[fname]
                return f"EXTRACT({pg_field} FROM {dt_sql})"

    # --- Timezone ---
    if fname == "tz" and len(args) == 1:
        # Extract timezone suffix from datetime text (Z, -08:00, etc.)
        a = expr_to_sql(args[0], ctx)
        if a:
            return (f"CASE WHEN {a} ~ 'Z$' THEN 'Z' "
                    f"WHEN {a} ~ '[+-]\\d{{2}}:\\d{{2}}$' "
                    f"THEN SUBSTRING({a} FROM '[+-]\\d{{2}}:\\d{{2}}$') "
                    f"ELSE '' END")

    if fname == "timezone" and len(args) == 1:
        # Convert timezone to xsd:dayTimeDuration
        a = expr_to_sql(args[0], ctx)
        if a:
            return (f"CASE WHEN {a} ~ 'Z$' THEN 'PT0S' "
                    f"WHEN {a} ~ '[+-]\\d{{2}}:\\d{{2}}$' THEN "
                    f"CONCAT("
                    f"CASE WHEN SUBSTRING({a} FROM '[+-]') = '-' THEN '-' ELSE '' END,"
                    f"'PT',"
                    f"ABS(CAST(SUBSTRING(SUBSTRING({a} FROM '[+-]\\d{{2}}:\\d{{2}}$') FROM 2 FOR 2) AS INTEGER))::TEXT,"
                    f"'H',"
                    f"CASE WHEN CAST(SUBSTRING(SUBSTRING({a} FROM '[+-]\\d{{2}}:\\d{{2}}$') FROM 5 FOR 2) AS INTEGER) != 0 "
                    f"THEN CONCAT(CAST(SUBSTRING(SUBSTRING({a} FROM '[+-]\\d{{2}}:\\d{{2}}$') FROM 5 FOR 2) AS INTEGER)::TEXT, 'M') "
                    f"ELSE '' END) "
                    f"ELSE NULL END")

    # --- UUID ---
    if fname == "uuid" and len(args) == 0:
        return "CONCAT('urn:uuid:', GEN_RANDOM_UUID()::TEXT)"

    if fname == "struuid" and len(args) == 0:
        return "GEN_RANDOM_UUID()::TEXT"

    # --- SAMETERM ---
    if fname == "sameterm" and len(args) == 2:
        if isinstance(args[0], ExprVar) and isinstance(args[1], ExprVar):
            info_a = ctx.types.get(args[0].var)
            info_b = ctx.types.get(args[1].var)
            if info_a and info_b and info_a.uuid_col and info_b.uuid_col:
                return f"({info_a.uuid_col} = {info_b.uuid_col})"
        a = expr_to_sql(args[0], ctx)
        b = expr_to_sql(args[1], ctx)
        if a and b:
            return f"({a} = {b})"

    # --- IN / NOT IN ---
    # First arg is the value, rest are list items.
    # SQL IN/NOT IN handles NULL (error) items correctly per SPARQL semantics.
    if fname == "in" and len(args) >= 1:
        val = expr_to_sql(args[0], ctx)
        if val:
            if len(args) == 1:
                return "FALSE"  # Empty list → always false
            items = [expr_to_sql(a, ctx) for a in args[1:]]
            if all(items):
                return f"({val} IN ({', '.join(items)}))"

    if fname == "notin" and len(args) >= 1:
        val = expr_to_sql(args[0], ctx)
        if val:
            if len(args) == 1:
                return "TRUE"  # Empty list → always true
            items = [expr_to_sql(a, ctx) for a in args[1:]]
            if all(items):
                return f"({val} NOT IN ({', '.join(items)}))"

    # --- NOW() ---
    if fname == "now" and len(args) == 0:
        return ("TO_CHAR(NOW() AT TIME ZONE 'UTC', "
                "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')")

    # --- RAND() ---
    if fname == "rand" and len(args) == 0:
        return "RANDOM()::DOUBLE PRECISION"

    logger.debug("Unhandled function: %s (args=%d)", fname, len(args))
    return None


def _aggregator_to_sql(expr: ExprAggregator, ctx: EmitContext) -> Optional[str]:
    """Convert an aggregator expression to SQL (for use inside HAVING etc.)."""
    agg_name = (expr.name or "COUNT").upper()
    distinct_prefix = "DISTINCT " if expr.distinct else ""

    # PostgreSQL has no SAMPLE(); use MAX() as a deterministic stand-in.
    if agg_name == "SAMPLE":
        agg_name = "MAX"

    if agg_name == "COUNT" and expr.expr is None:
        return "COUNT(*)"

    if expr.expr:
        inner = expr_to_sql(expr.expr, ctx)
        if inner:
            return f"{agg_name}({distinct_prefix}{inner})"

    return f"{agg_name}({distinct_prefix}*)"


def _exists_to_sql(expr: ExprExists, ctx: EmitContext) -> Optional[str]:
    """Emit EXISTS / NOT EXISTS as a correlated SQL subquery.

    Runs the inner graph pattern through collect → emit with a child context,
    finds shared variables, and builds UUID-based correlation conditions.
    """
    from .collect import collect
    from .emit import emit
    from .ir import AliasGenerator
    from .var_scope import compute_scope

    gp = expr.graph_pattern
    if gp is None:
        return None

    # Build a fresh alias generator with a prefix to avoid collisions
    inner_aliases = AliasGenerator(alias_prefix="ex_")

    # Collect the inner graph pattern into a PlanV2
    inner_plan = collect(gp, ctx.space_id, inner_aliases,
                         graph_uri=ctx.graph_lock_uri)

    # Create a child EmitContext for the inner subquery
    from .sql_type_generation import TypeRegistry
    inner_types = TypeRegistry(aliases=inner_aliases)
    inner_ctx = EmitContext(
        space_id=ctx.space_id,
        aliases=inner_aliases,
        types=inner_types,
        graph_lock_uri=ctx.graph_lock_uri,
        base_uri=ctx.base_uri,
        trace_enabled=False,
    )

    # Emit the inner graph pattern
    inner_sql = emit(inner_plan, inner_ctx)

    # Substitute inner constants with direct term table lookups
    # (inner aliases' constants are NOT in the outer CTE)
    term_table = f"{ctx.space_id}_term"
    for (text, ttype), col_name in inner_aliases.constants.items():
        token = f"__CONST_{col_name}__"
        replacement = (
            f"(SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}' LIMIT 1)"
        )
        inner_sql = inner_sql.replace(token, replacement)

    # Find shared variables between outer and inner scopes
    outer_vars = set(ctx.types.all_vars())
    inner_scope = compute_scope(inner_plan)
    inner_vars = inner_scope.all_visible
    shared = outer_vars & inner_vars

    # Build correlation conditions on UUID columns
    ex_alias = ctx.aliases.next("_ex")
    corr_parts = []
    for var in sorted(shared):
        o_info = ctx.types.get(var)
        i_info = inner_ctx.types.get(var)
        if o_info and i_info and o_info.sql_name and i_info.sql_name:
            o_uuid = f"{o_info.sql_name}__uuid"
            i_uuid = f"{i_info.sql_name}__uuid"
            corr_parts.append(f"{o_uuid} = {ex_alias}.{i_uuid}")

    if corr_parts:
        corr_where = " AND ".join(corr_parts)
        subquery = f"SELECT 1 FROM ({inner_sql}) AS {ex_alias} WHERE {corr_where}"
    else:
        subquery = f"SELECT 1 FROM ({inner_sql}) AS {ex_alias}"

    prefix = "NOT EXISTS" if expr.negated else "EXISTS"
    return f"{prefix} ({subquery})"


def _typed_literal_guard(expr, ctx: EmitContext, sql: str,
                         allow_xsd_string: bool = False) -> str:
    """Rule 6: type guards for error propagation (§10.5).

    Wrap SQL in a guard that returns NULL for typed literals.
    SPARQL string functions require simple literals or lang-tagged literals.
    Typed literals should produce an error (NULL).
    If allow_xsd_string is True, xsd:string is treated as a simple literal
    (RDF 1.1 semantics) and allowed through.
    """
    _XSD_STR = f"{XSD}string"
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if info and info.dt_col:
            if allow_xsd_string:
                return (f"CASE WHEN {info.dt_col} IS NOT NULL "
                        f"AND {info.dt_col} != '' "
                        f"AND {info.dt_col} != '{_XSD_STR}' "
                        f"THEN NULL ELSE {sql} END")
            return (f"CASE WHEN {info.dt_col} IS NOT NULL "
                    f"AND {info.dt_col} != '' THEN NULL ELSE {sql} END")
    return sql


def _require_literal(expr, ctx: EmitContext, sql: str) -> str:
    """Rule 6: type guards for error propagation (§10.5).

    Return NULL if the expression resolves to a non-literal (URI, bnode).
    SPARQL string/hash functions require literal arguments (§17.2).
    Non-literal inputs produce a type error, mapped to NULL.
    """
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if info and info.type_col:
            return (f"CASE WHEN {info.type_col} = 'L' "
                    f"THEN {sql} ELSE NULL END")
    return sql


def _get_literal_lang(expr) -> Optional[str]:
    """Extract the language tag from a literal expression, or None."""
    if isinstance(expr, ExprValue) and hasattr(expr, 'node'):
        if isinstance(expr.node, LiteralNode) and expr.node.lang:
            return expr.node.lang
    return None


def _numeric_arg(expr, ctx: EmitContext) -> Optional[str]:
    """Convert an expression to a numeric SQL expression.

    If the expression resolves to a text column, wraps with CAST to NUMERIC.
    For expressions that are statically non-numeric (e.g. STR()), returns NULL
    to produce correct SPARQL error semantics.
    """
    sql = expr_to_sql(expr, ctx)
    if sql is None:
        return None

    # If it's a variable with a numeric column, use that
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if info and info.num_col:
            return info.num_col

    # If it's already a number literal, return as-is
    if isinstance(expr, ExprValue) and expr.node:
        if isinstance(expr.node, LiteralNode) and expr.node.datatype in _NUMERIC_DATATYPES:
            return sql

    # Wrap text columns with CAST
    if isinstance(expr, ExprVar):
        return f"CAST({sql} AS NUMERIC)"

    # For function calls that produce non-numeric results (STR, CONCAT, etc.),
    # return NULL to trigger SPARQL error semantics in arithmetic ops.
    if isinstance(expr, ExprFunction):
        fname = (expr.name or "").lower()
        if not _is_numeric_expr(expr, ctx):
            return "NULL::numeric"

    return sql
