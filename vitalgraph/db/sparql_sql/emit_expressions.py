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
import re
from typing import Optional

from ..jena_sparql.jena_types import (
    ExprVar, ExprValue, ExprFunction, ExprAggregator, ExprExists,
    URINode, LiteralNode, BNodeNode, VarNode,
    SortCondition,
)

from .emit_context import EmitContext
from .collect import _esc
from .vg_functions import (
    VG_ALL_FUNCTIONS as _VG_ALL_FUNCTIONS,
    VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY,
    VG_TEXT_SEARCH, VG_HYBRID_SEARCH,
    VG_MULTI_VECTOR_SIMILARITY, VG_MULTI_VECTOR_NEARBY,
    VG_MULTI_VECTOR_FUNCTIONS,
    VG_GEO_DISTANCE, VG_WITHIN_RADIUS, VG_WITHIN_BOUNDS, VG_WITHIN_POLYGON,
    VG_FUZZY_MATCH, VG_TRIGRAM_SIMILARITY,
    vector_similarity_sql, geo_distance_sql, within_radius_sql,
    within_bounds_sql, within_polygon_sql,
    multi_vector_similarity_sql,
    text_search_sql, hybrid_search_sql, fuzzy_match_sql,
    trigram_similarity_sql,
)

logger = logging.getLogger(__name__)


def _like_escape_sql(expr: str) -> str:
    """Wrap a SQL string expression so LIKE metacharacters (\\ % _) are escaped
    at runtime, making it safe as the needle of a ``LIKE '%'||needle||'%'``
    pattern (the raw-string counterpart is collect._like_escape).

    Without this, CONTAINS(?x, ?y) where ?y = "50%" would treat the % as a
    wildcard.  A constant needle is folded by PostgreSQL (trigram index still
    used); pg_trgm honors the '\\' LIKE-escape, so escaped % _ become literal
    trigram content.  Backslash is replaced first.
    """
    e = f"REPLACE({expr}, '\\', '\\\\')"
    e = f"REPLACE({e}, '%', '\\%')"
    e = f"REPLACE({e}, '_', '\\_')"
    return e

# XSD namespace
XSD = "http://www.w3.org/2001/XMLSchema#"
# RDF 1.1: a language-tagged literal's datatype. Not stored — a tagged
# literal carries `lang` and a NULL datatype — so it is derived, not read.
RDF_LANGSTRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"

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


class UnresolvedVariableError(ValueError):
    """An expression referenced a variable that could not be resolved.

    Raised by ``generator.generate_sql`` after emission, when strict mode is on
    and any unresolved reference was recorded. Production keeps the permissive
    NULL behaviour, because for a *legitimately* unbound variable NULL is the
    specified result (issue 028).
    """


# SQL emitted for a variable that could not be resolved.
#
# The *value* stays NULL — that is the SPARQL-specified result when the
# variable is legitimately unbound (§10.5), and since the emitter cannot tell
# that case from a translation gap it must not emit anything else.
#
# What changes is that the NULL is now self-identifying. Generated SQL is
# logged (sparql_sql_space_impl.py, "Generated SQL [%s]"), so it outlives the
# EmitContext: someone debugging a wrong-result report from a log has the SQL
# and nothing else. A bare NULL there is indistinguishable from the many
# legitimate NULL companion columns, which is a large part of why issues 023
# and 027 went unnoticed. The comment is inert to Postgres and greppable.
_UNRESOLVED_VAR_MARKER = "vg:unresolved-var"

# Kept for callers that just want the value.
UNRESOLVED_VAR_SQL = "NULL"


def unresolved_var_sql(var: str) -> str:
    """SQL for an unresolvable variable: NULL, annotated with which one."""
    return f"NULL /* {_UNRESOLVED_VAR_MARKER} ?{var} */"


def _var_to_sql(expr: ExprVar, ctx: EmitContext) -> Optional[str]:
    """Convert a variable reference to its SQL column name.

    Returns ``UNRESOLVED_VAR_SQL`` for a variable that cannot be resolved in
    the current context, and records the fact on the context.

    The NULL is correct for a legitimately unbound variable and wrong for a
    translation gap, and the two are indistinguishable *here* — so this does
    not decide. It marks. ``generator.generate_sql`` inspects
    ``ctx.unresolved_vars`` after emission and decides there. This mirrors
    ``ColumnInfo.is_unbound``, which likewise marks a
    deliberate NULL instead of emitting a bare one. See issue 028.
    """
    info = ctx.types.get(expr.var)
    if info and info.text_col:
        # The variable resolves — but if its term JOIN was deferred, the text
        # column is NULL at runtime and any comparison using it silently
        # returns nothing. compute_text_needed_vars only defers a variable that
        # is "NOT referenced by any expression", so an expression reaching one
        # here means the reference collector missed this reference.
        #
        # That is issue 027's *second* half, which scope analysis cannot see:
        # nothing is unresolved, so 028's check never fires. Recorded through
        # the same channel because the consequence is identical — a constraint
        # that silently stops constraining.
        if info.text_materialized is False:
            ctx.add_unresolved_var(expr.var, in_scope=True,
                                   reason="text-not-materialised")
            ctx.log("expr", f"?{expr.var} referenced but text not materialised")
        return info.text_col
    # Rule 1: NULL = unbound (§10.5). Variable not in registry.
    if ctx.query_all_vars and expr.var in ctx.query_all_vars:
        # Was this variable in scope here per SPARQL's rules? If it was, the
        # translator should have resolved it and failing to is a bug; if it
        # was not, NULL is the specified result. This is the discrimination
        # issue 028 was blocked on, and it is only answerable positionally —
        # ctx.expr_scope is declared by whichever handler is emitting.
        #
        # expr_scope is None when no handler declared one; treat that as "not
        # in scope" so an undeclared site cannot manufacture false positives.
        in_scope = bool(
            (ctx.expr_scope and expr.var in ctx.expr_scope)
            or expr.var in ctx.correlated_scope
        )
        ctx.add_unresolved_var(expr.var, in_scope=in_scope)
        # Also record it in the processing trace, where every other emitter
        # logs its decisions — a trace dump then shows *where* in the plan this
        # happened, which the flat context list cannot convey.
        ctx.log("expr", f"unresolved variable ?{expr.var} → NULL")
        logger.warning(
            "Variable ?%s is named in the query but is not resolvable in the "
            "current emit context (depth=%d), so it compiles to NULL — any "
            "comparison using it is NULL, which silently weakens the enclosing "
            "FILTER/constraint rather than failing. Known causes: a pattern "
            "that references a variable bound only in a sibling scope "
            "evaluated independently (each UNION branch, per SPARQL 1.1 "
            "§18.2), or a variable the reference-collector did not mark as "
            "needed so its term-table join was skipped. If this is a UNION, "
            "move the source pattern into the branch; otherwise treat it as a "
            "translation gap and check the results before trusting them.",
            expr.var, ctx.depth)
        return unresolved_var_sql(expr.var)
    return UNRESOLVED_VAR_SQL


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


def _strdt_target(expr) -> Optional[str]:
    """The datatype URI `STRDT`/`STRLANG` is constructing, or None.

    Only a URI written in the query is knowable here. A datatype arriving
    through a variable is a runtime value, and the lane a constructed literal
    takes has to be decided at emit time — so that case keeps the lexical
    result rather than guessing.
    """
    if isinstance(expr, ExprValue) and isinstance(expr.node, URINode):
        return expr.node.value
    return None


# A lexical form CAST can safely read as a number. `STRDT("abc", xsd:integer)`
# is a type error, i.e. unbound — and an unguarded CAST would raise instead,
# taking the whole query with it.
_NUMERIC_LEX_RE = r"^[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?$"


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
        # vg: vector/geo/text/fuzzy functions that return numeric values
        if expr.function_iri and expr.function_iri in (
            VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY, VG_GEO_DISTANCE,
            VG_TEXT_SEARCH, VG_HYBRID_SEARCH, VG_FUZZY_MATCH,
            VG_TRIGRAM_SIMILARITY,
        ):
            return True
        # Recurse: COALESCE/IF is numeric if any argument is numeric
        # A constructed literal is numeric when the datatype it is being GIVEN
        # is numeric — not when its lexical form happens to parse. Keying on
        # the text would make `STRDT("1", xsd:string)` a number, which is the
        # lexical-vs-value trap behind `issues/121`.
        if fname == "strdt" and len(expr.args or []) == 2:
            target = _strdt_target(expr.args[1])
            return bool(target and target in _NUMERIC_DATATYPES)
        if fname in ("coalesce", "if") and expr.args:
            return any(_is_numeric_expr(a, ctx) for a in expr.args)
    return False



def _is_boolean_expr(expr, ctx: EmitContext) -> bool:
    """Is this expression known to be boolean at compile time?

    Mirrors _is_numeric_expr. As there, a BGP variable's bool_col existing does
    not make the variable boolean — it is a CASE that yields NULL for
    non-boolean terms — so only typed_lane='bool' is trusted for variables.
    """
    if isinstance(expr, ExprValue) and expr.node and isinstance(expr.node, LiteralNode):
        return expr.node.datatype == f"{XSD}boolean"
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if info and info.typed_lane == "bool":
            return True
    if isinstance(expr, ExprFunction):
        if expr.function_iri and _XSD_CAST_MAP.get(expr.function_iri) == "BOOLEAN":
            return True
    return False


def _boolean_arg(expr, ctx: EmitContext) -> Optional[str]:
    """Convert an expression to a boolean SQL expression, or None.

    Returning None lets the caller fall back rather than emit something
    untypeable — the failure this exists to prevent.
    """
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if info and getattr(info, "bool_col", None):
            return info.bool_col
    sql = expr_to_sql(expr, ctx)
    if sql is None:
        return None
    if isinstance(expr, ExprValue) and expr.node and isinstance(expr.node, LiteralNode):
        if expr.node.datatype == f"{XSD}boolean":
            return sql
    return f"CAST({sql} AS BOOLEAN)"


def _is_text_operand(expr, ctx: EmitContext) -> bool:
    """True only when this operand is certainly a text column or string literal.

    Conservative on purpose. `COLLATE` on a non-text expression is a PostgreSQL
    ERROR, not a no-op, so a wrong answer here turns a working query into a
    failing one — strictly worse than the locale-ordering defect it is meant to
    fix. `_cmp_pair`'s fallthrough lane carries more than strings: `STRLEN(?x)`
    is not caught by `_is_numeric_expr` in every form, and collating an integer
    would raise.

    So this admits exactly two shapes — a plain or xsd:string literal, and a
    variable resolving to its text column with no typed lane claiming otherwise.
    Anything else is left uncollated, which is the pre-existing behaviour.
    """
    if isinstance(expr, ExprValue) and isinstance(expr.node, LiteralNode):
        dt = expr.node.datatype or ""
        return dt in ("", f"{XSD}string")
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        return bool(info and info.text_col and not info.typed_lane)
    return False


def _dt_sql(expr, ctx: EmitContext) -> Optional[str]:
    """SQL yielding this operand's datatype IRI, or None if it has no lane.

    A variable carries `dt_col` (`sql_type_generation.ColumnInfo`); a literal
    written in the query knows its own datatype statically.
    """
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if not info or not info.dt_col:
            return None
        # A LANGUAGE-TAGGED literal stores a NULL datatype, exactly like a
        # plain one, but its datatype is `rdf:langString` — not `xsd:string`.
        # Coalescing both to xsd:string made `"xyz"@en`, `"xyz"@EN`, `"xyz"`
        # and `"xyz"^^xsd:string` mutually equal: twelve cross-pairs where four
        # are correct (DAWG `open-eq-07`). `datatype()` already derived this
        # correctly in §4.3; the guard did not.
        if info.dt_col != "NULL" and info.lang_col:
            return (f"(CASE WHEN {info.dt_col} IS NOT NULL THEN {info.dt_col} "
                    f"WHEN {info.lang_col} IS NOT NULL AND {info.lang_col} != '' "
                    f"THEN '{RDF_LANGSTRING}' ELSE '{XSD}string' END)")
        # The literal string "NULL" is not a column — it is what the emitters
        # use when a var's datatype is not tracked at all (see
        # `emit_context.py:569`, which tests for the same sentinel). That is
        # UNKNOWN, not "no datatype": COALESCEing it to xsd:string would assert
        # a datatype we never established and could exclude rows that match.
        # Return None so the caller declines to guard and keeps prior
        # behaviour, which is over-permissive rather than wrong-and-narrower.
        if info.dt_col == "NULL":
            return None
        return info.dt_col
    if isinstance(expr, ExprValue) and isinstance(expr.node, LiteralNode):
        # RDF 1.1: a plain literal IS an xsd:string, so an absent datatype is
        # xsd:string rather than "no datatype" — which is what makes
        # `"x" = "x"^^xsd:string` TRUE.
        dt = expr.node.datatype or f"{XSD}string"
        return f"'{_esc(dt)}'"
    return None


def _in_one_value_space(left, right, ctx: EmitContext) -> bool:
    """True when SPARQL compares these two BY VALUE regardless of datatype.

    These are the cases that are correct today and must not acquire a datatype
    guard: two numerics compare across integer/decimal/double
    (`"1"^^xsd:integer = 1.0` is TRUE), booleans were settled in `issues/049`,
    datetimes have their own lane, and a plain literal is an `xsd:string` in
    RDF 1.1 so the string lane is one space too.
    """
    if _is_numeric_expr(left, ctx) or _is_numeric_expr(right, ctx):
        return True
    if _is_boolean_expr(left, ctx) or _is_boolean_expr(right, ctx):
        return True
    # NOT `_is_text_operand`. That answers "is COLLATE safe here", and it says
    # True for a VARIABLE resolving to its text column — which is exactly the
    # case that needs the guard, because the row behind that variable may hold
    # any datatype. Using it here suppressed the guard for `?v = "x"`, so the
    # expression-path fix passed every test that compared two literals written
    # in the query while stored data stayed wrong.
    #
    # Only two STATICALLY known string literals are provably one value.
    if _is_static_string_literal(left) and _is_static_string_literal(right):
        return True
    return False


def _is_static_string_literal(expr) -> bool:
    """A literal written in the query whose datatype is absent or xsd:string."""
    return (isinstance(expr, ExprValue) and isinstance(expr.node, LiteralNode)
            and (expr.node.datatype or "") in ("", f"{XSD}string"))


def _datatype_guard(left, right, ctx: EmitContext) -> Optional[str]:
    """SQL requiring the two operands' datatypes to agree, or None.

    `issues/121`: comparison falls back to `term_text`, so a datatype we do not
    model collapses into the string lane and `"x"^^<urn:myType> = "x"` answers
    TRUE where SPARQL says FALSE.

    None when the two are in one value space — that is where today's correct
    behaviour lives, and a guard there would break it, which is `issues/049` in
    reverse.

    NOT DISTINCT FROM rather than `=`: a datatype column is NULL for a term
    with no datatype, and NULL = NULL is unknown, which would silently exclude
    rows instead of matching them.
    """
    if _in_one_value_space(left, right, ctx):
        return None
    ldt, rdt = _dt_sql(left, ctx), _dt_sql(right, ctx)
    if ldt is None or rdt is None:
        return None
    # COALESCE to xsd:string on both sides. A plain literal stores
    # `datatype_id` NULL while an explicit `"x"^^xsd:string` stores the id, and
    # RDF 1.1 makes those ONE value — so comparing the raw columns would put
    # them in different classes and drop the plain rows. Normalising is what
    # keeps `"x" = "x"^^xsd:string` TRUE.
    _S = f"'{XSD}string'"
    return (f"(COALESCE({ldt}, {_S}) IS NOT DISTINCT FROM COALESCE({rdt}, {_S}))")


# Datatypes whose VALUES we can compare. SPARQL 1.1 §17.3 routes `=` to a
# value comparison for these; anything else falls through to RDFterm-equal
# (§17.4.1.7), which "produces a type error if the arguments are both literal
# but are not the same RDF term". FALSE is reserved for the case where they are
# NOT both literal — a URI against a literal is well-defined and unequal.
_COMPARABLE_DATATYPES = _NUMERIC_DATATYPES | frozenset({
    f"{XSD}string", f"{XSD}boolean", f"{XSD}dateTime", f"{XSD}date",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
})
# `rdf:langString` BELONGS here. "Comparable" means we can DETERMINE the
# answer, not that a value comparison exists: a language-tagged literal is
# perfectly well known, and term identity over (text, tag) is decidable. Only
# an UNRECOGNISED datatype leaves us unable to say. Dropping langString made
# `"xyz"@en != "xyz"` an error where DAWG `open-eq-08` requires TRUE, and
# over-excluded 34 of 64 pairs.


def _lang_sql(expr, ctx: EmitContext) -> Optional[str]:
    """SQL yielding this operand's language tag, or None if it has no lane."""
    if isinstance(expr, ExprVar):
        info = ctx.types.get(expr.var)
        if info and info.lang_col and info.lang_col != "NULL":
            return info.lang_col
        return None
    if isinstance(expr, ExprValue) and isinstance(expr.node, LiteralNode):
        return f"'{(getattr(expr.node, 'lang', None) or '')}'"
    return None


def _comparable_sql(expr, ctx: EmitContext) -> Optional[str]:
    """When this operand's VALUE can be compared: "TRUE", "FALSE", or SQL.

    A plain literal is an `xsd:string` in RDF 1.1, so a NULL datatype counts.
    A URI or blank node is not a literal at all, so RDFterm-equal gives a
    definite answer for it — those count too, and only a LITERAL carrying an
    unrecognised datatype is the error case.
    """
    if isinstance(expr, ExprValue) and isinstance(expr.node, LiteralNode):
        dt = expr.node.datatype or f"{XSD}string"
        return "TRUE" if dt in _COMPARABLE_DATATYPES else "FALSE"
    if isinstance(expr, ExprVar):
        # Through `_dt_sql`, NOT `info.dt_col` directly. `_dt_sql` is what
        # `_datatype_guard` uses, so this engages exactly where the guard
        # already does — and the guard is known to be in scope there. Reading
        # the column info directly reached contexts the guard never enters and
        # emitted `v2__datatype` where only `f0.v3__datatype` exists, which
        # took out `aggregates/SAMPLE` and `bind/bind11`.
        dt = _dt_sql(expr, ctx)
        if dt is None:
            return None
        info = ctx.types.get(expr.var)
        known = ", ".join(f"'{d}'" for d in sorted(_COMPARABLE_DATATYPES))
        # A non-literal is not "both literal", so RDFterm-equal answers
        # definitely for it — only a literal with an unrecognised datatype is
        # the error case.
        non_literal = (f"{info.type_col} != 'L' OR "
                       if info and info.type_col else "")
        return f"({non_literal}{dt} IS NULL OR {dt} IN ({known}))"
    return None


def _term_type_guard(left, right, ctx: EmitContext) -> Optional[str]:
    """SQL requiring both operands to be the same KIND of RDF term.

    A literal, a URI and a blank node are never the same term, whatever their
    text. We compared `term_text` alone, so the blank node `_:xyz` — whose
    LABEL is "xyz" — came out equal to the literal `"xyz"`, and the datatype
    guard waved it through because a blank node has a NULL datatype and so
    derives `xsd:string`. Four spurious pairs in DAWG `open-eq-07`.

    None when either side has no type lane, which leaves the caller as it was.
    """
    cols = []
    for e in (left, right):
        if isinstance(e, ExprVar):
            info = ctx.types.get(e.var)
            if not info or not info.type_col or info.type_col == "NULL":
                return None
            cols.append(info.type_col)
        elif isinstance(e, ExprValue):
            node = e.node
            t = ("L" if isinstance(node, LiteralNode)
                 else "B" if isinstance(node, BNodeNode) else "U")
            cols.append(f"'{t}'")
        else:
            return None
    return f"({cols[0]} = {cols[1]})"


def _both_literal_sql(left, right, ctx: EmitContext) -> Optional[str]:
    """SQL true when BOTH operands are literals, or None if unknowable."""
    parts = []
    for e in (left, right):
        if isinstance(e, ExprVar):
            info = ctx.types.get(e.var)
            if not info or not info.type_col or info.type_col == "NULL":
                return None
            parts.append(f"{info.type_col} = 'L'")
        elif isinstance(e, ExprValue):
            if not isinstance(e.node, LiteralNode):
                return "FALSE"
            parts.append("TRUE")
        else:
            return None
    return f"({' AND '.join(parts)})"


def _term_error_cmp(left, right, op: str, ctx: EmitContext,
                    normal: str) -> Optional[str]:
    """`=`/`!=` where a value comparison is not available is a TYPE ERROR.

    §17.4.1.7 exactly: same term -> TRUE, both literal and not the same term ->
    ERROR. `?v != "a"^^t:type1` must return NOTHING over data typed
    `t:type1` — the identical term is unequal-false, every other term of that
    type is incomparable — and we returned seven of eight rows by comparing
    text (DAWG `open-eq-06`).

    A literal with an unrecognised datatype cannot also carry a language tag,
    so "same term" here is lexical form plus datatype agreement.
    """
    # A pair already in ONE value space needs nothing: the numeric and boolean
    # lanes yield NULL for a term outside them, which is what a type error
    # does in a FILTER anyway. Skipping here also keeps this in step with
    # `_datatype_guard`, whose first act is the same test — engaging where it
    # declines is what emitted an out-of-scope `v2__datatype` for
    # `?sample = 1.0` and broke `aggregates/SAMPLE`.
    if _in_one_value_space(left, right, ctx):
        return None
    ca, cb = _comparable_sql(left, ctx), _comparable_sql(right, ctx)
    if ca is None or cb is None:
        return None
    if ca == "TRUE" and cb == "TRUE":
        return None
    a, b = expr_to_sql(left, ctx), expr_to_sql(right, ctx)
    if not a or not b:
        return None
    guard = _datatype_guard(left, right, ctx)
    same = f"({a} = {b})" if guard is None else f"(({a} = {b}) AND {guard})"
    # Two language-tagged literals are the same term only if the TAGS match,
    # and BCP 47 tags are case-insensitive — `"xyz"@en` and `"xyz"@EN` ARE the
    # same term, while `"xyz"@en` and `"xyz"@fr` are not.
    la, lb = _lang_sql(left, ctx), _lang_sql(right, ctx)
    if la and lb:
        same = (f"({same} AND LOWER(COALESCE({la}, '')) = "
                f"LOWER(COALESCE({lb}, '')))")
    _tg = _term_type_guard(left, right, ctx)
    if _tg:
        same = f"({same} AND {_tg})"
    ident = "TRUE" if op == "=" else "FALSE"
    # "if the arguments are BOTH LITERAL but are not the same RDF term" — the
    # error needs BOTH to be literals. An unrecognised datatype against a URI
    # or a blank node is still a definite answer, because RDFterm-equal
    # returns FALSE whenever the two are not both literal. Requiring only
    # `ca AND cb` excluded the unknown-typed literal against the blank node and
    # the URI: four pairs, and the difference between 38 and 42 in DAWG
    # `open-eq-08`.
    both_lit = _both_literal_sql(left, right, ctx)
    determinate = f"({ca} AND {cb})" if both_lit is None else \
                  f"(({ca} AND {cb}) OR NOT {both_lit})"
    return (f"(CASE WHEN {determinate} THEN {normal} "
            f"WHEN {same} THEN {ident} ELSE NULL END)")


def _var_var_cmp(left, right, op: str, ctx: EmitContext) -> Optional[str]:
    """Compare two VARIABLES by value, choosing the lane at RUN TIME.

    `issues/127`. Every other comparison here picks a lane at emit time,
    because one side is written in the query and its datatype is known. Two
    variables have no compile-time type, so `_is_numeric_expr` refuses to
    trust a BGP variable's `num_col` — correctly, since the variable could
    hold a URI. But refusing the numeric lane does not make the comparison
    safe, it makes it LEXICAL: `"1"^^integer = "01"^^integer` answered false,
    and so did the three spellings of one double in `data-builtin-1.ttl`.

    `num_col` is already a `CASE` yielding NULL for anything non-numeric, so
    "both sides are numeric" is a runtime test that costs nothing to ask.
    Where it holds, compare numerically; otherwise fall through to the text
    lane exactly as before, datatype guard included.

    A plain `"1"` is NOT caught by the numeric branch — `num_col` requires a
    numeric `datatype_id` — so a string that merely looks like a number keeps
    comparing as a string, which is the distinction `issues/121` is about.
    """
    li, ri = ctx.types.get(left.var), ctx.types.get(right.var)
    if not (li and ri and li.num_col and ri.num_col):
        return None
    if li.num_col == "NULL" or ri.num_col == "NULL":
        return None
    a, b = expr_to_sql(left, ctx), expr_to_sql(right, ctx)
    if not (a and b):
        return None

    from .collation import collate
    text = f"({collate(a)} {op} {b})"
    guard = _datatype_guard(left, right, ctx)
    if guard is not None:
        text = (f"(({collate(a)} != {b}) OR NOT {guard})" if op == "!="
                else f"({text} AND {guard})")
    return (f"(CASE WHEN {li.num_col} IS NOT NULL AND {ri.num_col} IS NOT NULL "
            f"THEN ({li.num_col} {op} {ri.num_col}) ELSE {text} END)")


def _cmp_sql(left, right, op: str, ctx: EmitContext) -> Optional[str]:
    """A comparison, with a datatype guard when the operands need one.

    `=` and `!=` are NOT mirror images here. Appending `AND <guard>` is right
    for `=` and backwards for `!=`: two literals sharing a lexical form and
    differing in datatype are different terms, so they must compare UNEQUAL,
    and `(values differ) AND (datatypes agree)` makes that FALSE.

    Ordering comparators compose like `=`. SPARQL calls an incomparable
    ordering a type error, which in a FILTER excludes the row, and excluding is
    what the guard produces. See
    `planning_sparql_features/datatypes_and_language_tags.md` §4b.
    """
    # Two variables: no compile-time type, so the lane is chosen per row.
    if (isinstance(left, ExprVar) and isinstance(right, ExprVar)
            and not _is_numeric_expr(left, ctx)
            and not _is_numeric_expr(right, ctx)
            and not _is_boolean_expr(left, ctx)
            and not _is_boolean_expr(right, ctx)):
        _vv = _var_var_cmp(left, right, op, ctx)
    else:
        _vv = None

    # NOT an early return: the var-var lane must also reach the type-error rule.
    if _vv:
        normal = _vv
    else:
        a, b = _cmp_pair(left, right, ctx)
        if not a or not b:
            return None
        guard = _datatype_guard(left, right, ctx)
        if guard is None:
            normal = f"({a} {op} {b})"
        elif op == "!=":
            normal = f"(({a} != {b}) OR NOT {guard})"
        else:
            normal = f"(({a} {op} {b}) AND {guard})"

    # Only `=`/`!=` map to RDFterm-equal. Ordering is a different rule, with
    # its own cross-type ordering, so the term-type guard is applied here only.
    if op in ("=", "!="):
        # Gate on the DATATYPE GUARD engaging. That is the condition already
        # proven to be in scope wherever comparisons are emitted; the term-type
        # and language columns live beside the datatype column, so if it
        # declines they are unavailable too. Reading them regardless emitted
        # `v2__lang` for `?sample = 1.0`, where only `f0.v3__*` exists, and
        # broke `aggregates/SAMPLE` — the SECOND time this session that reading
        # ColumnInfo directly reached a context the guard never enters.
        #
        # Declining costs nothing here: a pair in one value space is compared
        # numerically, where a term of another type or with a language tag
        # yields NULL anyway.
        _guards = []
        if _datatype_guard(left, right, ctx) is None:
            return normal
        _tg = _term_type_guard(left, right, ctx)
        if _tg:
            _guards.append(_tg)
        # The language TAG is part of term identity, so it belongs in the
        # comparison and not only in the same-term branch: `"xyz"@en` and
        # `"xyz"@fr` are different terms. BCP 47 tags are case-insensitive,
        # which is what keeps `@en` and `@EN` one term.
        _la, _lb = _lang_sql(left, ctx), _lang_sql(right, ctx)
        if _la and _lb:
            _guards.append(f"(LOWER(COALESCE({_la}, '')) = "
                           f"LOWER(COALESCE({_lb}, '')))")
        if _guards:
            _g = " AND ".join(_guards)
            normal = (f"({normal} AND {_g})" if op == "="
                      else f"({normal} OR NOT ({_g}))")
        _te = _term_error_cmp(left, right, op, ctx, normal)
        if _te:
            return _te
    return normal


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

    # Booleans need the same treatment as numerics, for the same reason. A
    # variable's default lane is term_text, so comparing it to a boolean
    # literal emitted `v8 != TRUE` — `operator does not exist: text <> boolean`,
    # a query that cannot run at all. `eq` on a boolean slot escaped this only
    # because the builder turns equality into a triple pattern (term identity,
    # no lane involved) rather than a FILTER; every other comparator produces a
    # FILTER and hit it. Found by the shape matrix, which was the first thing to
    # exercise `ne`.
    if _is_boolean_expr(left, ctx) or _is_boolean_expr(right, ctx):
        a = _boolean_arg(left, ctx)
        b = _boolean_arg(right, ctx)
        if a and b:
            return a, b

    a, b = expr_to_sql(left, ctx), expr_to_sql(right, ctx)
    # The text lane. SPARQL compares strings by code point (§15.1 ordering,
    # via fn:compare); PostgreSQL uses the cluster's collation, so `?a < ?b`
    # admits different rows on a locale-collated deployment. Pinned only when
    # BOTH sides are provably text — see _is_text_operand.
    if a and b and _is_text_operand(left, ctx) and _is_text_operand(right, ctx):
        from .collation import collate
        return collate(a), b
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

    # --- VitalGraph custom functions (vg:vectorSimilarity, vg:geoDistance, etc.) ---
    if expr.function_iri and expr.function_iri in _VG_ALL_FUNCTIONS:
        return _vg_function_to_sql(expr, ctx)

    # --- Comparison operators ---
    # Use numeric columns when either side is numeric to avoid text=integer errors
    if fname in ("eq", "numericequal") and len(args) == 2:
        _sql = _cmp_sql(args[0], args[1], "=", ctx)
        if _sql:
            return _sql

    if fname in ("ne", "numericnotequal") and len(args) == 2:
        _sql = _cmp_sql(args[0], args[1], "!=", ctx)
        if _sql:
            return _sql

    if fname in ("lt", "numericlessthan") and len(args) == 2:
        _sql = _cmp_sql(args[0], args[1], "<", ctx)
        if _sql:
            return _sql

    if fname in ("gt", "numericgreaterthan") and len(args) == 2:
        _sql = _cmp_sql(args[0], args[1], ">", ctx)
        if _sql:
            return _sql

    if fname in ("le",) and len(args) == 2:
        _sql = _cmp_sql(args[0], args[1], "<=", ctx)
        if _sql:
            return _sql

    if fname in ("ge",) and len(args) == 2:
        _sql = _cmp_sql(args[0], args[1], ">=", ctx)
        if _sql:
            return _sql

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
        # Detect CONTAINS(LCASE(x), LCASE(y)) → x ILIKE '%' || y || '%'
        # This pattern leverages the GIN trigram index for fast substring search.
        # We intentionally skip _require_literal here: the CASE WHEN type='L'
        # wrapper prevents PostgreSQL from using the trigram index, causing
        # 8+ second cold-start queries due to sequential scans.
        # Non-literal terms (URIs/bnodes) won't match typical search strings.
        arg0, arg1 = args[0], args[1]
        if (isinstance(arg0, ExprFunction) and (arg0.name or "").lower() == "lcase"
                and isinstance(arg1, ExprFunction) and (arg1.name or "").lower() == "lcase"
                and arg0.args and arg1.args):
            a = expr_to_sql(arg0.args[0], ctx)
            b = expr_to_sql(arg1.args[0], ctx)
            if a and b:
                return f"({a} ILIKE '%%' || {_like_escape_sql(b)} || '%%')"
        # Plain CONTAINS(x, y) → x LIKE '%' || y || '%' (case-sensitive, still uses trgm)
        a, b = expr_to_sql(arg0, ctx), expr_to_sql(arg1, ctx)
        if a and b:
            return f"({a} LIKE '%%' || {_like_escape_sql(b)} || '%%')"

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
            # SPARQL $N backreferences -> PostgreSQL \N. This stopped at $3,
            # so a pattern with four or more capture groups left `$4` in the
            # output as a literal. Nine covers the single-digit range, which is
            # all either dialect addresses without extra syntax.
            for n in range(1, 10):
                rep = f"REPLACE({rep}, '${n}', '\\{n}')"

            # Flags. The SPARQL string was previously concatenated onto `g` and
            # handed to PostgreSQL as-is, which meant `s`/`m` were passed with
            # PostgreSQL's meaning rather than XPath's, and the default emitted
            # nothing at all — dot-matches-newline, which is not the SPARQL
            # default. Same mapping as REGEX now; see regex_flags.
            raw_flags = ""
            if len(args) >= 4:
                a3 = args[3]
                if isinstance(a3, ExprValue) and isinstance(a3.node, LiteralNode):
                    raw_flags = a3.node.value or ""
            from .regex_flags import apply_to_pattern, is_case_insensitive
            pat = apply_to_pattern(pat, raw_flags)
            # `g` is not a SPARQL flag: REPLACE replaces every occurrence by
            # definition (§17.4.3.15), so it is always requested.
            flags = "'gi'" if is_case_insensitive(raw_flags) else "'g'"
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
            from .regex_flags import apply_to_pattern, is_case_insensitive

            # SPARQL flags are a STRING LITERAL argument; read the value rather
            # than substring-matching the emitted SQL, which is how `'i'` used
            # to be detected and would also have matched a flags string that
            # merely contained the letter inside something else.
            raw_flags = ""
            if len(args) >= 3:
                a2 = args[2]
                if isinstance(a2, ExprValue) and isinstance(a2.node, LiteralNode):
                    raw_flags = a2.node.value or ""

            # Every flag but `i` becomes an embedded option on the pattern. This
            # used to handle ONLY `i` and drop `s`, `m`, `x`, `q` silently — and,
            # worse, emitted no option at all by default, which is not the SPARQL
            # default: XPath's `.` does not match a newline and PostgreSQL's does.
            # See regex_flags for the 2x2 and the measurements.
            op = "~*" if is_case_insensitive(raw_flags) else "~"

            # A LITERAL pattern is translated: XPath's `\p{L}` and `\i` have no
            # POSIX equivalent, and PostgreSQL rejects them outright. A runtime
            # pattern (a column) cannot be inspected, so it keeps the
            # options-only path and the same rejection as before.
            a1 = args[1]
            if isinstance(a1, ExprValue) and isinstance(a1.node, LiteralNode):
                from .regex_flags import apply_to_literal
                body, needs_ctype = apply_to_literal(a1.node.value or "",
                                                     raw_flags)
                pat_sql = f"'{_esc(body)}'"
                if needs_ctype:
                    # POSIX classes are ASCII-only under this database's `C`
                    # ctype, so a translated pattern needs a Unicode-aware
                    # collation on the OPERAND or it silently under-matches.
                    # Applied only when a class was translated, so ordinary
                    # patterns keep their existing plans.
                    from .regex_classes import CLASSIFY_COLLATION
                    s = f"({s} COLLATE {CLASSIFY_COLLATION})"
                return f"({s} {op} {pat_sql})"
            return f"({s} {op} {apply_to_pattern(pat, raw_flags)})"

    # --- Accessors ---
    if fname == "lang" and len(args) == 1:
        # `lang()` of a NON-LITERAL is a type error, i.e. unbound — not "".
        # Returning "" made a URI look like an untagged literal, so it leaked
        # into every lang test: `FILTER(lang(?v) = '')` returned it,
        # `FILTER(lang(?v) != '@NotALangTag@')` returned it, and
        # `FILTER(! langMatches(lang(?v), "*"))` returned it. Three DAWG cases,
        # one cause — found the day `sparql10/expr-builtin` first ran
        # (`issues/125`). Same gate `datatype()` needs, for the same reason.
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.lang_col:
                if info.type_col:
                    return (f"CASE WHEN {info.type_col} = 'L' "
                            f"THEN COALESCE({info.lang_col}, '') END")
                return f"COALESCE({info.lang_col}, '')"
        if isinstance(args[0], ExprValue):
            node = args[0].node
            if isinstance(node, LiteralNode):
                return f"'{(getattr(node, 'lang', None) or '')}'"
            return "NULL"          # URI or blank node: type error
        return "''"

    if fname == "datatype" and len(args) == 1:
        # RDF 1.1 abolished the untyped literal, so EVERY literal has a
        # datatype: a plain one is `xsd:string`, a tagged one is
        # `rdf:langString`. Neither is stored — both are a NULL `datatype_id`
        # — so both have to be derived here. Returning the column raw meant
        # `FILTER(datatype(?x) = xsd:string)` dropped exactly the rows it
        # should keep (§4.3).
        if isinstance(args[0], ExprVar):
            info = ctx.types.get(args[0].var)
            if info and info.dt_col:
                # "NULL" is the sentinel for a datatype the emitters never
                # tracked (see `_dt_sql`). UNKNOWN is not "no datatype", and
                # answering xsd:string there would invent one.
                if info.dt_col == "NULL":
                    return "NULL"
                # A non-literal has NO datatype — that is a type error, i.e.
                # unbound. Without the term-type test the COALESCE below would
                # claim every URI and blank node is an xsd:string, which is
                # worse than the bug being fixed. No type column, no coalesce.
                if not info.type_col:
                    return info.dt_col
                if info.lang_col:
                    absent = (f"CASE WHEN {info.lang_col} IS NOT NULL "
                              f"AND {info.lang_col} != '' "
                              f"THEN '{RDF_LANGSTRING}' ELSE '{XSD}string' END")
                else:
                    absent = f"'{XSD}string'"
                return (f"CASE WHEN {info.type_col} = 'L' "
                        f"THEN COALESCE({info.dt_col}, {absent}) ELSE NULL END")
        # A constructed literal knows its datatype statically — reporting it
        # unbound would leave `STRDT` indistinguishable from a plain string
        # even after the value fix above.
        if isinstance(args[0], ExprFunction):
            _inner = (args[0].name or "").lower()
            _iargs = args[0].args or []
            if _inner == "strdt" and len(_iargs) == 2:
                _t = _strdt_target(_iargs[1])
                if _t:
                    return f"'{_t.replace(chr(39), chr(39)+chr(39))}'"
        # Constant literals. `datatype(10)` was already right; a plain literal
        # fell through to NULL because the datatype is absent rather than
        # falsy-but-present — and Jena canonicalises `"a"^^xsd:string` to a
        # plain literal, so an explicitly typed string arrived here the same
        # way and got the same wrong answer.
        if isinstance(args[0], ExprValue) and isinstance(args[0].node, LiteralNode):
            node = args[0].node
            dt = node.datatype
            if dt:
                return f"'{dt.replace(chr(39), chr(39)+chr(39))}'"
            if getattr(node, "lang", None):
                return f"'{RDF_LANGSTRING}'"
            return f"'{XSD}string'"
        return "NULL"

    if fname == "langmatches" and len(args) == 2:
        a = expr_to_sql(args[0], ctx)
        b = expr_to_sql(args[1], ctx)
        if a and b:
            if b == "'*'":
                # NULL is a type error from `lang()` on a non-literal, and it
                # has to PROPAGATE. `a IS NOT NULL AND ...` converts it to
                # FALSE, which is invisible in a positive filter and wrong
                # under negation: `FILTER(! langMatches(lang(?v), "*"))` then
                # returns the URI, because `!FALSE` is TRUE while `!error` is
                # still an error. DAWG `LangMatches-4` (`issues/125`).
                return (f"CASE WHEN {a} IS NULL THEN NULL "
                        f"ELSE ({a} != '') END")
            # RFC 4647 basic filtering, which SPARQL 1.1 defines langMatches in
            # terms of: the range matches when it EQUALS the tag, or is a
            # prefix of it ENDING AT A SUBTAG BOUNDARY. This was equality
            # alone, so `langMatches(lang(?x), "en")` — the standard way to ask
            # for "English, any region" — returned nothing for en-US, en-GB,
            # en-AU (`issues/120`).
            #
            # The boundary is the whole difficulty. Comparing `LEFT(a, n+1)`
            # against `b || '-'` requires the separator, so `en` matches
            # `en-US` but NOT `enm`, which is Middle English — a different
            # language a plain prefix test would wrongly return.
            #
            # `LEFT(...) = ...` rather than LIKE, matching `strstarts` above:
            # the range can arrive through a variable, and LIKE would read a
            # `%` or `_` in it as a metacharacter.
            _basic = (f"LOWER({a}) = LOWER({b}) OR "
                      f"LEFT(LOWER({a}), LENGTH({b}) + 1) = LOWER({b}) || '-'")
            # A range written in the query is known now, and the arm above
            # already caught `"*"`, so it cannot be the wildcard. One arriving
            # through a VARIABLE can be, and only at runtime — testing for it
            # is the difference between `langMatches(?t, ?r)` with ?r = "*"
            # answering TRUE and answering FALSE, which it did.
            #
            # Gated on the range being dynamic so the ordinary
            # `langMatches(lang(?v), "en")` keeps the plain predicate instead
            # of paying for a CASE that can never take its first branch.
            if isinstance(args[1], ExprValue) and isinstance(args[1].node,
                                                             LiteralNode):
                return f"({_basic})"
            return (f"(CASE WHEN {b} = '*' "
                    f"THEN ({a} IS NOT NULL AND {a} != '') "
                    f"ELSE ({_basic}) END)")

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
        # SPARQL 1.1 §17.4.2.2. BNODE() must return a DISTINCT blank node for
        # each solution it is invoked in; BNODE(literal) must return the same
        # node for the same simple-literal argument within one execution.
        #
        # This returned the constant '_:b0' for both forms, so every solution
        # collapsed onto one node — and under DISTINCT, rows the spec calls
        # distinct deduplicated down to one (issues/067).
        #
        # BARE LABEL, no `_:`. The prefix belongs to the serializers, which
        # re-add it; emitting it here put it in the JSON result value where the
        # spec wants "b0", and would double it on export.
        if args:
            a = expr_to_sql(args[0], ctx)
            # Same argument -> same node WITHIN one execution; different across
            # executions. Both halves of §17.4.2.2's one-argument rule.
            #
            # The salt is computed at RUNTIME rather than baked into the SQL,
            # which is what makes this work with SparqlCompileCache: the cache
            # reuses generated SQL across executions, so any constant salt would
            # be reused with it and two separate queries using BNODE("x") would
            # agree — the thing the spec forbids.
            #
            #   statement_timestamp()  the start of the CURRENT statement. STABLE
            #                          within it, so every row and every repeat
            #                          of BNODE("x") in one execution sees the
            #                          same value; different for the next
            #                          statement, so executions do not collide.
            #   pg_backend_pid()       two concurrent backends cannot land on one
            #                          microsecond and share a node.
            #
            # Not clock_timestamp(), which advances DURING a statement and would
            # give a different node per row — that is the no-arg form's rule,
            # not this one.
            salt = "pg_backend_pid()::text || statement_timestamp()::text"
            return (f"('b' || md5({a} || {salt}))" if a
                    else f"('b' || md5({salt}))")
        # Fresh per row. gen_random_uuid() is VOLATILE, so PostgreSQL evaluates
        # it once per row rather than folding it to a constant — which is the
        # whole point.
        return "('b' || replace(gen_random_uuid()::text, '-', ''))"

    if fname == "strdt" and len(args) == 2:
        a = expr_to_sql(args[0], ctx)
        if not a:
            return None
        lex = a
        if isinstance(args[0], ExprVar):
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
                    lex = f"CASE WHEN {cond} THEN NULL ELSE {a} END"
        # Give the constructed literal the VALUE its datatype implies (§4.4).
        # This returned the lexical form and dropped the datatype, so
        # `STRDT("1", xsd:integer) + 1` was NULL — nothing downstream could
        # tell the result from the string "1", which makes the standard way to
        # type a computed value close to useless.
        #
        # `_is_numeric_expr` decides whether arithmetic takes the numeric lane,
        # and it now recognises the same shape. Both halves are needed: a
        # numeric result the lane chooser cannot see is still unusable, and a
        # lane chooser pointed at a text operand is worse.
        target = _strdt_target(args[1])
        if target and target in _NUMERIC_DATATYPES:
            # A STATIC lexical form has to be decided here, not in SQL.
            # PostgreSQL constant-folds `CAST('abc' AS NUMERIC)` at PLAN time,
            # so the runtime CASE below never gets to guard it and the whole
            # query dies with `invalid input syntax for type numeric`. A
            # compile-time fold cannot be defended by a runtime test.
            if isinstance(args[0], ExprValue) and isinstance(args[0].node,
                                                             LiteralNode):
                raw = args[0].node.value or ""
                if not re.match(_NUMERIC_LEX_RE, raw.strip()):
                    return "NULL"          # type error -> unbound
                return f"CAST('{_esc(raw.strip())}' AS NUMERIC)"
            # A column is not folded, so the guard holds at run time.
            return (f"CASE WHEN ({lex}) ~ '{_NUMERIC_LEX_RE}' "
                    f"THEN CAST({lex} AS NUMERIC) END")
        return lex

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


def expr_to_sql_exists_with_overrides(expr: ExprExists, ctx: EmitContext,
                                      overrides: dict) -> Optional[str]:
    """Public entry for emitting an EXISTS correlated to explicit SQL columns.

    Used by emit_slice._emit_two_phase to fold a negation into the probe. Kept
    as a named function rather than exposing the private one, so the contract —
    the caller supplies the outer column for every correlated variable — is
    stated somewhere.
    """
    return _exists_to_sql(expr, ctx, outer_uuid_overrides=overrides)


def _exists_to_sql(expr: ExprExists, ctx: EmitContext,
                   outer_uuid_overrides: Optional[dict] = None) -> Optional[str]:
    """Emit EXISTS / NOT EXISTS as a correlated SQL subquery.

    Runs the inner graph pattern through collect → emit with a child context,
    finds shared variables, and builds UUID-based correlation conditions.

    `outer_uuid_overrides` maps a SPARQL variable to the SQL expression that
    holds its uuid in the ENCLOSING scope. Normally the correlation is written
    against `<sql_name>__uuid`, an unqualified column of the surrounding
    projection. Inside the two-phase probe there is no such projection — the
    probe is deliberately flat, `SELECT 1` over raw quad tables, because the
    inner/outer wrapper is what stops PostgreSQL collapsing it into index probes
    (see emit_bgp.emit_bgp_exists). There the correlation has to name a raw
    column such as `q7.subject_uuid`, which is what this supplies.
    """
    from .collect import collect
    from .emit import emit
    from .ir import AliasGenerator
    from .var_scope import compute_scope

    gp = expr.graph_pattern
    if gp is None:
        return None

    # Prefer the plan prepared by generator.prepare_exists_subplans: it has been
    # through constant materialization and the edge-table rewrite, which cannot
    # be done here because emit is synchronous and those need I/O. Collecting
    # inline is the fallback for callers that skipped preparation (no
    # connection, or a body preparation declined) — correct, just slow.
    if expr.prepared_plan is not None and expr.prepared_aliases is not None:
        inner_plan = expr.prepared_plan
        inner_aliases = expr.prepared_aliases
    else:
        inner_aliases = AliasGenerator(alias_prefix="ex_")
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
    # Propagate the query-wide variable set so an unresolvable reference inside
    # the subquery still produces the _var_to_sql diagnostic instead of a
    # silent NULL.
    inner_ctx.query_all_vars = ctx.query_all_vars
    # An EXISTS body projects `SELECT 1`, so nothing in it needs term TEXT unless
    # a filter inside the body compares on it. Without this the body resolved
    # term_text/term_type/lang/datatype for every variable it binds, inside an
    # anti-join that discards all of them (issues/088).
    #
    # Computed rather than emptied: a body carrying `FILTER(STRSTARTS(?x, "a"))`
    # does need ?x's text, and blanking the set would emit a comparison against a
    # column that was never resolved.
    #
    # It has to happen HERE. `prepare_exists_subplans` builds the body at stage
    # 2a.3 and `compute_text_needed_vars` runs at 2c, so the prepared body never
    # sees the outer pass — the ordering is deliberate for other reasons and this
    # is the place both are in scope.
    try:
        from .var_scope import compute_text_needed_vars
        inner_ctx.text_needed_vars = compute_text_needed_vars(
            inner_plan, projection_discarded=True)
    except Exception:
        # Unknown shape: leave it None and resolve text as before. Slow, correct.
        inner_ctx.text_needed_vars = None
    # Everything emitted below here sits inside a correlated subquery, so filter
    # push-down must not add an uncorrelated one — see the field's own comment.
    inner_ctx.in_correlated_subquery = True
    # Share the unresolved-variable record with the parent. This context is
    # built directly rather than via ctx.child(), so it does not inherit the
    # list — without this, a translation gap inside an EXISTS body is recorded
    # onto a context nobody reads, which is exactly how issue 027 stayed
    # invisible.
    inner_ctx._unresolved_vars = ctx._unresolved_vars

    outer_vars = set(ctx.types.all_vars())
    inner_scope = compute_scope(inner_plan)
    inner_vars = inner_scope.all_visible

    # Per SPARQL 1.1 §8.1.1 the EXISTS pattern is evaluated with the current
    # solution mapping substituted in.  A variable the inner pattern does not
    # bind itself — typically one referenced only from an inner FILTER — must
    # therefore resolve to the OUTER row's column, which is what makes this a
    # genuinely correlated subquery.
    #
    # Without this the variable is absent from inner_ctx, _var_to_sql emits the
    # literal NULL, the inner comparison is NULL for every row and the subquery
    # returns nothing: EXISTS always false, NOT EXISTS always true, silently
    # (issue 027).
    #
    # Safe against shadowing: inner column names carry the "ex_" alias prefix
    # (AliasGenerator.next_var), so a bare outer name like `v0` can never
    # collide with an inner one and resolves to the enclosing query.
    for var in outer_vars - inner_vars:
        o_info = ctx.types.get(var)
        if o_info and o_info.sql_name:
            inner_ctx.types.register(o_info)

    # §8.1.1: the pattern is evaluated with the outer solution
    # substituted, so outer variables are in scope throughout it — even
    # inside a nested FILTER that declares its own pattern's scope.
    inner_ctx.correlated_scope = frozenset(outer_vars)
    inner_sql = emit(inner_plan, inner_ctx)

    # Substitute inner constants with direct term table lookups
    # (inner aliases' constants are NOT in the outer CTE)
    # Prefer a materialized uuid literal; fall back to the lookup subquery only
    # for constants nobody resolved.
    #
    # This used to emit the subquery unconditionally. Each one is a correlated
    # lookup evaluated inside the probe, and a KGQuery frame path carries seven
    # of them — measured at 245ms apiece against a term table with no term_text
    # index, and still a per-probe InitPlan with one. The outer query never paid
    # this because substitute_constants resolves its tokens to literals; the
    # body was simply never given the same treatment (issues/057).
    term_table = f"{ctx.space_id}_term"
    for (text, ttype), col_name in inner_aliases.constants.items():
        token = f"__CONST_{col_name}__"
        uuid_str = inner_aliases.resolved_constants.get(col_name)
        if uuid_str:
            replacement = f"'{uuid_str}'::uuid"
        else:
            replacement = (
                f"(SELECT term_uuid FROM {term_table} "
                f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}' LIMIT 1)"
            )
        inner_sql = inner_sql.replace(token, replacement)

    # Variables the inner pattern binds itself correlate through an explicit
    # predicate below; the filter-only ones were bound to outer columns above.
    # An overridden variable counts as shared even when the enclosing context's
    # type registry does not carry it — inside the two-phase probe the caller
    # knows the column and ctx may not.
    shared = (outer_vars | set(outer_uuid_overrides or {})) & inner_vars

    # Build correlation conditions on UUID columns
    ex_alias = ctx.aliases.next("_ex")
    corr_parts = []
    overrides = outer_uuid_overrides or {}
    for var in sorted(shared):
        o_info = ctx.types.get(var)
        i_info = inner_ctx.types.get(var)
        if not (i_info and i_info.sql_name):
            continue
        i_uuid = f"{ex_alias}.{i_info.sql_name}__uuid"
        if var in overrides:
            corr_parts.append(f"{overrides[var]} = {i_uuid}")
        elif o_info and o_info.sql_name:
            corr_parts.append(f"{o_info.sql_name}__uuid = {i_uuid}")

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


# ---------------------------------------------------------------------------
# VitalGraph custom function dispatcher
# ---------------------------------------------------------------------------

def _vg_function_to_sql(expr: ExprFunction, ctx: EmitContext) -> Optional[str]:
    """Convert a vg: custom function to SQL.

    Delegates to the appropriate SQL generation function in vg_functions.py.
    For vector functions that need server-side vectorization, records a
    VectorRequest on ctx so the orchestrator can inject the embedding.
    """
    iri = expr.function_iri

    if iri in (VG_VECTOR_SIMILARITY, VG_VECTOR_NEARBY):
        sql, vec_request = vector_similarity_sql(expr, ctx)
        if vec_request is not None:
            ctx.add_vector_request(vec_request)
        return sql

    if iri in VG_MULTI_VECTOR_FUNCTIONS:
        sql, vec_requests = multi_vector_similarity_sql(expr, ctx)
        for vr in vec_requests:
            ctx.add_vector_request(vr)
        return sql

    if iri == VG_TEXT_SEARCH:
        return text_search_sql(expr, ctx)

    if iri == VG_HYBRID_SEARCH:
        sql, vec_request = hybrid_search_sql(expr, ctx)
        if vec_request is not None:
            ctx.add_vector_request(vec_request)
        return sql

    if iri == VG_GEO_DISTANCE:
        return geo_distance_sql(expr, ctx)

    if iri == VG_WITHIN_RADIUS:
        return within_radius_sql(expr, ctx)

    if iri == VG_WITHIN_BOUNDS:
        return within_bounds_sql(expr, ctx)

    if iri == VG_WITHIN_POLYGON:
        return within_polygon_sql(expr, ctx)

    if iri == VG_FUZZY_MATCH:
        sql, fuzzy_request = fuzzy_match_sql(expr, ctx)
        if fuzzy_request is not None:
            ctx.add_fuzzy_request(fuzzy_request)
        return sql

    if iri == VG_TRIGRAM_SIMILARITY:
        return trigram_similarity_sql(expr, ctx)

    logger.warning("Unhandled vg: function IRI: %s", iri)
    return None
