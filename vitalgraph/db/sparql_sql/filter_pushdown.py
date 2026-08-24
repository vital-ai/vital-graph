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
    ExprVar, ExprValue, ExprFunction, LiteralNode, URINode,
)

from .ir import (PlanV2, KIND_BGP, KIND_FILTER, KIND_EXTEND, KIND_JOIN,
                 KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS)
from .collect import _esc, _like_escape
from .declines import Rule
from .text_needle import (UnindexableTextSearch, bgp_is_unbounded, is_servable,
                          unbounded_scan_error)

# A text search the trigram index cannot serve is not pushed. `push_filters` is
# the stage; the rule reads only the lexical form and the BGP's other
# constraints, both available then.
TEXT_PUSH = Rule("text_push", stage="push_filters", reads=("collect",))

logger = logging.getLogger(__name__)


def _quad_aliases(bgp: PlanV2) -> set:
    return {t.alias for t in bgp.tables
            if t.kind in ("quad", "edge", "frame_entity")}


def _term_set(ctx, term_table: str, cond: str) -> str:
    """The set of term uuids matching `cond`, as a subquery to be used with IN.

    Deliberately INLINE, and deliberately not a MATERIALIZED CTE.

    `issues/070` observed that this subquery is uncorrelated yet lands inside
    the correlated two-phase probe, which PostgreSQL re-executes per candidate,
    and proposed hoisting it into a CTE so the term set is computed once. That
    was implemented and measured, and it is WORSE:

        contains/Text    1,284 ms -> 53,098 ms   (41x)
        ne/Text            228 ms ->  1,692 ms   (7.4x)
        has_any/Text    12,684 ms -> 20,603 ms

    The reasoning behind the CTE was wrong in a way worth keeping. "Evaluated
    once" is only cheaper than "evaluated per row" when the per-row evaluation
    cannot early-terminate. Under two-phase paging it can: the probe tests ~25
    candidates and stops, and each test is an index lookup that never builds the
    whole term set. Materialising computes EVERY matching term eagerly —
    hundreds of thousands of rows for a broad predicate like
    `term_text ILIKE '%ca%'` — before the page is even started. The `LIMIT` is
    what makes the inline form cheap, and a CTE is exactly the barrier that
    throws it away.

    A CTE could still pay off where the term set is small AND the candidate
    count is large. Nothing in the sweep is that shape, so it is not worth the
    machinery until something is.
    """
    return f"(SELECT term_uuid FROM {term_table} WHERE {cond})"


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

    # Every push-down here emits an UNCORRELATED `IN (SELECT term_uuid FROM
    # term WHERE ...)`. PostgreSQL does not hoist one of those out of a
    # correlated subquery, so inside an EXISTS body it re-executes per outer
    # row — pushing `?v IN (...)` into a NOT EXISTS body cost 190x on
    # not_has_any/Choice (56 ms -> 10.6 s). Nothing is lost by declining:
    # generator.prepare_exists_subplans has already materialised these bodies'
    # constants to uuids, which is the better constraint anyway.
    in_correlated = bool(getattr(ctx, "in_correlated_subquery", False))

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

        if child_bgp is not None and not in_correlated:
            quad_aliases = _quad_aliases(child_bgp)
            constraint = _try_text_filter(expr, child_bgp, term_table,
                                          quad_aliases, ctx)
            if constraint:
                target = child_bgp

        if constraint is None and ctx is not None:
            # Numeric ranges search by *variable*, so they also reach BGPs that
            # sit under an inner JOIN — which is the usual shape for a KGQuery
            # (FILTER over JOIN over two BGPs), and one the single-chain walk
            # above cannot see at all.
            root = plan.children[0] if plan.children else None
            # `!=`, `IN`, and the text searches all reach BGPs under an inner
            # JOIN for the same reason numeric ranges do, and are looked up by
            # variable. Text search is here as well as above because the
            # single-chain walk misses the KGQuery shape entirely, which is why
            # `contains` was never pushed despite having an emitter.
            #
            # Not inside a correlated EXISTS body: these all emit an
            # UNCORRELATED `IN (SELECT term_uuid ...)`, which PostgreSQL will
            # not hoist out of a correlated subquery and so re-runs per outer
            # row. Pushing `?v IN (...)` into a NOT EXISTS body cost 190x on
            # not_has_any/Choice before this guard existed.
            by_var = ()
            if not in_correlated:
                by_var = ((_equality_var, _try_equality_filter),
                          (_inequality_var, _try_inequality_filter),
                          (_in_var, _try_in_filter),
                          (_text_search_var, _try_text_search))
            for find_var, try_push in by_var:
                if constraint is not None:
                    break
                v = find_var(expr)
                if v is None:
                    continue
                b = _find_bgp_binding(root, v)
                if b is not None:
                    constraint = try_push(expr, b, term_table,
                                          _quad_aliases(b), ctx)
                    if constraint:
                        target = b
            var_name = (_numeric_var(expr)
                        if constraint is None and not in_correlated else None)
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


def _plain_string_datatype_guard(ctx) -> str:
    """SQL restricting a term to the plain/`xsd:string` value space, or "".

    RDF 1.1 makes a plain literal and an `xsd:string` literal the same value,
    so both pass; every other datatype sharing the lexical form is a DIFFERENT
    term and must not.

    The id is resolved from THIS SPACE via `ctx.dt_ids_for_uris`, rather than
    positionally from `STANDARD_DATATYPES` the way `numeric_datatype_ids` and
    its siblings do. That form assumes every space seeded those 40 in order. Measured 2026-08-23 across 164 per-space datatype tables: 161 hold
    `xsd:string` at id 1, and three do not hold it at all. One of those,
    `sp_geo_test`, has `vital-core#geoLocation` at id 1 — so the positional
    form would have pinned this guard to geoLocation and called it a string.

    A space with no `xsd:string` row yields `NULL` here, making the IN arm
    always false. That is correct rather than degraded: no term in such a space
    can carry that datatype, so only the plain literals (NULL) should match.

    "" when there is no context to resolve against — the caller's condition is
    then left as it was, which is over-permissive rather than wrong-and-
    narrower. Reached only by the shape-only helpers, which discard the SQL.
    """
    if ctx is None:
        return ""
    ids = ctx.dt_ids_for_uris([f"{_XSD}string"])
    return f" AND (datatype_id IS NULL OR datatype_id IN ({ids}))"


def _try_text_filter(
    expr, bgp: PlanV2, term_table: str, quad_aliases: set, ctx=None
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
    literal_node = None
    flags_arg = None
    ci = False

    ops = _text_search_operands(expr)
    if ops is not None:
        var_name, _, literal_value, ci, flags_arg = ops
    elif name == "eq" and len(args) == 2:
        for i, j in ((0, 1), (1, 0)):
            if isinstance(args[i], ExprVar) and isinstance(args[j], ExprValue):
                if isinstance(args[j].node, LiteralNode):
                    var_name = args[i].var
                    literal_value = args[j].node.value
                    literal_node = args[j].node
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

    # Can the trigram index require a trigram for this needle? If not, pushing
    # it emits `?v IN (SELECT term_uuid FROM term WHERE term_text ILIKE
    # '%XQ%')`, which reads every term in the space no matter how selective the
    # rest of the query is — the opposite of what a push-down is for. Declining
    # leaves the same FILTER above the join, over rows the query already
    # produced: identical answers, bounded by the result set. See `text_needle`.
    if name in _TEXT_SEARCH_OPS and not is_servable(name, literal_value):
        # ...unless nothing else bounds the BGP, in which case "above the join"
        # is the whole graph and declining trades a term scan for something
        # worse. That case is refused rather than silently made slower.
        if bgp_is_unbounded(bgp):
            term_rows = getattr(getattr(ctx, "aliases", None), "term_rows", None)
            msg = unbounded_scan_error(name, literal_value, var_name, term_rows)
            if msg:
                raise UnindexableTextSearch(msg)
        logger.debug("Text filter NOT pushed (unservable): %s(%s, '%s')",
                     name, var_name, literal_value)
        return TEXT_PUSH.decline("needle yields no requirable trigram, so a "
                                 "push-down would scan every term",
                                 op=name, needle=literal_value, var=var_name)

    # Build the term table condition
    escaped = _esc(literal_value)
    # For the LIKE-based operators the needle must also have its LIKE
    # metacharacters (\ % _) escaped, else CONTAINS(?x, "50%") over-matches.
    # Escaping keeps the GIN trigram index usable (pg_trgm honors '\').
    like_esc = _esc(_like_escape(literal_value))
    # ILIKE when both operands were case-folded. That is not an approximation of
    # the folded comparison, it is the SAME rewrite `emit_expressions` already
    # applies to CONTAINS(LCASE(x), LCASE(y)) above the join — so pushing it
    # changes only where the predicate is evaluated, never what it answers.
    like = "ILIKE" if ci else "LIKE"
    if name == "contains":
        # Unconditionally `term_text`: an unservable needle never reaches here,
        # so there is no longer a case that wants the index disabled.
        term_cond = f"term_text {like} '%{like_esc}%'"
    elif name == "strstarts":
        term_cond = f"term_text {like} '{like_esc}%'"
    elif name == "strends":
        term_cond = f"term_text {like} '%{like_esc}'"
    elif name == "regex":
        from .regex_flags import pg_embedded_options, is_case_insensitive

        raw_flags = ""
        if flags_arg and isinstance(flags_arg, ExprValue):
            if isinstance(flags_arg.node, LiteralNode):
                raw_flags = flags_arg.node.value or ""
        # SHARED with emit_expressions. These two were the only REGEX emitters
        # and they disagreed: this one mapped s/m/x, that one handled only `i`.
        # Which runs is decided by whether the filter was PUSHABLE — a
        # performance heuristic — so the same query returned different rows
        # depending on an optimisation, and stopped reproducing as soon as
        # anyone simplified it. Both now ask for the same semantics.
        #
        # This also fixes two bugs of its own: no option at all was emitted for
        # the default (SPARQL wants `p`, PostgreSQL defaults to dot-matches-
        # newline), and `s`+`m` together emitted the contradictory `sn` instead
        # of `w`.
        op = "~*" if is_case_insensitive(raw_flags) else "~"
        # Same translation as emit_expressions, for the same reason the flag
        # mapping is shared: which emitter runs is a performance decision and
        # must not change semantics.
        from .regex_classes import CLASSIFY_COLLATION, translate_classes
        body, needs_ctype = translate_classes(escaped)
        pat = f"(?{pg_embedded_options(raw_flags)}){body}"
        col = (f"(term_text COLLATE {CLASSIFY_COLLATION})" if needs_ctype
               else "term_text")
        term_cond = f"{col} {op} '{pat}'"
    elif name == "eq":
        # Defer to `_ne_equality_cond`, the ONE place that knows how to turn a
        # literal into a term-level equality: `num_val` for numerics so
        # `"5.0"^^double` matches `5^^integer`, `dt_val` for dateTimes so one
        # instant matches however it is written, both boolean spellings, and
        # plain/`xsd:string` with the datatype guard `issues/121` needed.
        #
        # This arm used to build its own `term_text = '...'`. Lexical, and for
        # a dateTime simply wrong: rdflib normalises `...Z` to `...+00:00` on
        # the way in, so `?v = "...Z"^^xsd:dateTime` matched NOTHING — not even
        # the term holding that exact instant — and two timestamps denoting one
        # moment compared unequal whenever their text differed.
        #
        # The shape is the same either way; the caller wraps this in
        # `uuid IN (SELECT term_uuid ... WHERE <cond>)`, which is exactly what
        # `_ne_equality_cond` is written to fill. Declining when it declines
        # keeps the two in step, which the note below `_TEXT_SEARCH_OPS` is
        # about.
        if literal_node is None:
            return None
        term_cond = _ne_equality_cond(literal_node, ctx)
        if term_cond is None:
            return None
    else:
        return None

    constraint_sql = f"{uuid_col} IN {_term_set(ctx, term_table, term_cond)}"
    logger.debug("Text filter pushdown: %s(%s, '%s') → %s",
                 name, var_name, literal_value, constraint_sql[:80])
    return (ref_id, constraint_sql)


# Text-search operators whose push-down is a pure function of the lexical form,
# so pushing them means the same thing as evaluating them above the join. `eq`
# is deliberately NOT here even though `_try_text_filter` handles it: it pushes
# as `term_text = '5'`, which misses `"5.0"^^xsd:double` — the same lexical-vs-
# value trap that made uuid inequality unsound in issues/058. Widening the gate
# to cover `eq` would turn that latent bug into a reachable one.
# Which needles the index can actually serve, and what happens to the ones it
# cannot, is stated once in `text_needle` — including why the answer is no longer
# `(term_text || '')`, the no-op concatenation that used to sit here.
_TEXT_SEARCH_OPS = ("contains", "strstarts", "strends", "regex")
_FOLD_FNS = ("lcase", "ucase")


def _unwrap_fold(node):
    """(inner, fold_name) if node is LCASE(x) / UCASE(x), else (node, None)."""
    if (isinstance(node, ExprFunction)
            and (node.name or "").lower() in _FOLD_FNS
            and len(node.args or []) == 1):
        return node.args[0], (node.name or "").lower()
    return node, None


def _text_search_operands(expr):
    """(var, op, literal, case_insensitive, flags) for a pushable text search.

    The gate in `semijoin` and the emitter must accept EXACTLY the same
    expressions — see issues/054 and issues/058 for what happens when the two
    ends drift. This states the shape once; `_try_text_filter` re-derives the
    rest from the BGP, and `_emit_two_phase` verifies consumption before it
    relies on the variable being gone.
    """
    if not isinstance(expr, ExprFunction):
        return None
    name = (expr.name or "").lower()
    args = expr.args or []
    if name in ("contains", "strstarts", "strends"):
        if len(args) != 2:
            return None
    elif name == "regex":
        if len(args) < 2:
            return None
    else:
        return None

    # KGQuery emits CONTAINS(LCASE(?v), LCASE("x")), so the raw shape never
    # matched and `contains` was never pushed at all — the gate was only half
    # the reason it was slow.
    a0, f0 = _unwrap_fold(args[0])
    a1, f1 = _unwrap_fold(args[1])
    # Both sides must be folded by the SAME function. LCASE(?v) against an
    # unfolded needle is case-SENSITIVE against a lowercased haystack, which
    # ILIKE would over-match; that asymmetry is a wrong answer, not a slow one.
    if f0 != f1:
        return None
    ci = f0 is not None
    if name == "regex" and ci:
        # regex carries its own case-insensitivity in flags; folding on top has
        # no established rewrite here, so leave it above the join.
        return None
    if not isinstance(a0, ExprVar) or not isinstance(a1, ExprValue):
        return None
    if not isinstance(a1.node, LiteralNode):
        return None
    flags = args[2] if (name == "regex" and len(args) >= 3) else None
    return a0.var, name, a1.node.value, ci, flags


def _text_search_var(expr) -> Optional[str]:
    """Variable of a pushable text-search FILTER, or None.

    SERVABILITY IS PART OF PUSHABILITY. `semijoin` reads this to decide a
    variable's term JOIN can be skipped, on the grounds that the filter will
    consume it. An unservable needle is declined by `_try_text_filter`, so the
    FILTER stays above the join and needs its value materialised after all —
    saying "pushable" here skips the join and the query then fails to generate:

        Variable(s) lost their value while in scope: ?val_0_0_0

    That is the drift this function exists to prevent, and the docstring on
    `_text_search_operands` names it: "the gate in `semijoin` and the emitter
    must accept EXACTLY the same expressions ... this states the shape once".
    The servability rule was added to the emitter (`issues/070`) and not here,
    so the two ends disagreed for exactly the needles it declines.

    It shipped green because every bench that would have caught it —
    `test_comparator_coverage`, 26 cases, whose `contains` needle is the
    two-character "CA" — was SKIPPING on a fixture nobody had loaded.
    """
    ops = _text_search_operands(expr)
    if not ops:
        return None
    var, name, literal, _ci, _flags = ops
    if name in _TEXT_SEARCH_OPS and literal is not None:
        from .text_needle import is_servable
        if not is_servable(name, literal):
            return None
    return var


def _try_text_search(expr, bgp, term_table: str, quad_aliases: set, ctx):
    """`_try_text_filter` under the by-variable dispatch signature."""
    return _try_text_filter(expr, bgp, term_table, quad_aliases, ctx)


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

_XSD = "http://www.w3.org/2001/XMLSchema#"
_DATETIME_DTS = (f"{_XSD}dateTime", f"{_XSD}date")
# A trailing `Z` or a `±HH:MM` offset — the two ways XSD spells a timezone.
# Kept as a pair: the Python form classifies the literal at emit time, the SQL
# form classifies the stored term at run time, and they must agree.
_TZ_RE = re.compile(r"(Z|[+-]\d{2}:\d{2})$")
_TZ_SQL_RE = r"(Z|[+-][0-9]{2}:[0-9]{2})$"

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?"
    r"(?:[+-]\d{2}:\d{2}|Z)?$")


def _datetime_literal(node) -> Optional[str]:
    """Lexical form of an xsd:dateTime / xsd:date literal, or None.

    Returned as text and handed to vitalgraph_iso_to_utc rather than parsed
    here, so the comparison value goes through exactly the same normalisation
    as the stored column. Parsing it in Python would introduce a second
    interpretation of ISO-8601 that could disagree with the first.

    The pattern is also the injection guard: anything not matching is refused
    rather than quoted into SQL.
    """
    if not isinstance(node, ExprValue) or not isinstance(node.node, LiteralNode):
        return None
    if node.node.datatype not in _DATETIME_DTS:
        return None
    value = (node.node.value or "").strip()
    if not _ISO_RE.match(value):
        return None
    return value


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
    is_dt = False
    if isinstance(left, ExprVar):
        var_name, literal = left.var, _numeric_literal(right)
        if literal is None:
            literal = _datetime_literal(right)
            is_dt = literal is not None
    elif isinstance(right, ExprVar):
        # Variable on the right: `65 <= ?v` means `?v >= 65`.
        var_name, literal = right.var, _numeric_literal(left)
        if literal is None:
            literal = _datetime_literal(left)
            is_dt = literal is not None
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

    # The generated column, not the equivalent expression. PostgreSQL does not
    # use statistics for an indexed expression here — it estimated 3,489,209
    # rows against 99 actual, the 1/3 default — and then hashed the whole entity
    # population rather than driving from the selective leaf. An ordinary column
    # estimates accurately (160 against 99) and the plan follows.
    # See sparql_sql_schema.numeric_term_column.
    from .sparql_sql_schema import NUMERIC_TERM_COLUMN, DATETIME_TERM_COLUMN
    if is_dt:
        # The datetime column, for the same reason as the numeric one, and the
        # comparison value is normalised through the same parser so both sides
        # mean the same instant. Comparing against a raw TIMESTAMP literal
        # would work only while every stored value carries the same offset.
        col_expr = DATETIME_TERM_COLUMN
        value_sql = f"vitalgraph_iso_to_utc('{literal}')"
    else:
        col_expr = NUMERIC_TERM_COLUMN
        value_sql = str(literal)
    num_expr = col_expr

    # No OFFSET 0 fence here. One was needed while the predicate was an
    # expression, to stop the planner folding the subquery into the join and
    # mis-costing it. With the generated column the estimate is accurate, so
    # the planner can be left to choose — and letting it choose is better,
    # since a fence also blocks legitimate optimisations.
    constraint_sql = (
        f"{ref_id}.{col_name} IN "
        f"{_term_set(ctx, term_table, f'{num_expr} {op} {value_sql}')}"
    )
    # Record structurally so the selectivity gate can estimate this leaf.
    bgp.range_leaves[(ref_id, col_name)] = (op, literal)

    # ADDITIONALLY narrow the slot itself against `entity_slot_sort`, when this
    # range is a KGQuery slot criterion. The term semi-join above is correct and
    # leaves the planner nothing selective to drive from — half the query becomes
    # one Hash Join and a fifth a sequential scan of the whole edge table. The
    # derived table answers the same question with an Index Only Scan in 2 ms.
    # Adds a constraint the surrounding chain already implies; see
    # `slot_sort_range` for why it anchors on the slot and not the entity.
    if ctx is not None:
        from .slot_sort_range import slot_range_constraint
        extra = slot_range_constraint(bgp, ctx.aliases, ctx.space_id,
                                      var_name, op, literal, value_sql)
        if extra and extra not in bgp.tagged_constraints:
            bgp.tagged_constraints.append(extra)

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
    # Datetimes count too: this gate decides whether _try_numeric_filter is
    # reached at all, so leaving it numeric-only meant the datetime branch
    # there was unreachable and dt_val never appeared in a query.
    def _comparable(node):
        return (_numeric_literal(node) is not None
                or _datetime_literal(node) is not None)

    if isinstance(left, ExprVar) and _comparable(right):
        return left.var
    if isinstance(right, ExprVar) and _comparable(left):
        return right.var
    return None


# `!=` gets its own path because the obvious rewrite is wrong. Comparing
# `object_uuid <> <uuid of the literal>` is only sound where the lexical form IS
# the value: `"5.0"^^xsd:double != 5` is FALSE in SPARQL and the two terms have
# different uuids, so uuid inequality answers TRUE (issues/058).
#
# The sound form negates the EQUALITY SET instead — "not one of the terms equal
# to this value" — computed with the same typed columns the range push-down
# uses, so numeric equality is numeric:
#
#     ?v != 5        ->  object_uuid NOT IN (SELECT term_uuid ... WHERE num_val = 5)
#     ?v != "CA"     ->  object_uuid NOT IN (SELECT term_uuid ... WHERE term_text = 'CA')
#
# The equality set is tiny — one value — where the inequality set is the whole


# `!=` gets its own path because the obvious rewrite is wrong. Comparing
# `object_uuid <> <uuid of the literal>` is only sound where the lexical form IS
# the value: `"5.0"^^xsd:double != 5` is FALSE in SPARQL while the two terms have
# different uuids, so uuid inequality answers TRUE (issues/058).
#
# The sound form negates the EQUALITY SET — "not one of the terms equal to this
# value" — computed with the same typed columns the range push-down uses, so
# numeric equality is numeric:
#
#     ?v != 5      ->  object_uuid NOT IN (SELECT term_uuid ... WHERE num_val = 5)
#     ?v != "CA"   ->  object_uuid NOT IN (SELECT term_uuid ... WHERE term_text = 'CA')
#
# The equality set is one value, where the inequality set is the whole term
# table — which is also why this form is usable at all.
_NE_OPS = {"ne", "notequals", "not_equals", "!="}


def _ne_equality_cond(value_node, ctx=None) -> Optional[str]:
    """Term-table condition matching values EQUAL to this literal, or None.

    The single source of truth for which inequalities are pushable. Both the
    emitter and `semijoin`'s gate go through it, because they must accept
    exactly the same expressions: the gate drops the variable from `needed` on
    the promise that the filter will be pushed, and if the push then declines,
    the variable is gone and its value compiles to NULL. Not hypothetical — a
    first version matched only the SHAPE and the boolean case raised
    UnresolvedVariableError immediately (issues 023, 027).

    Dispatch is on the DATATYPE, never on whether the lexical form happens to
    parse. An earlier version asked `_numeric_literal` first, which only tries
    `float(value)` and ignores the datatype entirely, so two unrelated things
    took the numeric branch and both were wrong:

        "5"                 a plain literal, i.e. an xsd:string in RDF 1.1,
                            pushed `num_val = 5` — which excludes the INTEGER 5
                            and fails to exclude the string "5", wrong in both
                            directions
        "1"^^xsd:boolean    pushed `num_val = 1`, conflating true with 1^^integer

    Neither is reachable from KGQuery, which types its literals, but both are
    reachable from SPARQL a caller writes.
    """
    from .sparql_sql_schema import NUMERIC_TERM_COLUMN, DATETIME_TERM_COLUMN
    from .emit_bgp import _NUMERIC_DATATYPES

    if isinstance(value_node, URINode):
        return f"term_text = '{_esc(value_node.value)}' AND term_type = 'U'"
    if not isinstance(value_node, LiteralNode):
        return None

    raw = value_node.value or ""
    dt = value_node.datatype or ""

    if dt == f"{_XSD}boolean":
        # `"true"` and `"1"` are ONE value in XSD, as are `"false"` and `"0"`,
        # so matching a single spelling would leave the other wrongly included —
        # which is why this used to decline and `ne`/Boolean stayed on the
        # blocking-sort path with a 60s timeout.
        #
        # It needs no typed column, unlike num_val and dt_val. A boolean's value
        # set has exactly two members, so the equality set is just both
        # spellings of one of them, and the term table's HASH index on term_text
        # answers that with two probes. The datatype guard is what stops the
        # plain string "true" and the integer 1 matching.
        lex = {"true": "'true','1'", "1": "'true','1'",
               "false": "'false','0'", "0": "'false','0'"}.get(raw.strip().lower())
        if lex is None:
            return None            # not a valid boolean lexical form
        # Resolved from THIS SPACE, not positionally — `issues/126`. The id
        # used to come from `boolean_datatype_ids()`, which enumerates
        # STANDARD_DATATYPES and assumes every space seeded those 40 in order.
        # Three of 164 real spaces did not; `sp_geo_test` has
        # `vital-core#geoLocation` at id 1, so that form pinned "boolean" to
        # geoLocation — simultaneously admitting the wrong terms and excluding
        # the right ones.
        #
        # No context means this call is the semijoin GATE
        # (`_inequality_var`/`_in_var`), which reads `ops[0]` and discards this
        # SQL. It must still return non-None: the gate and the push-down have
        # to recognise exactly the same expressions, and a gate that declined
        # here while `_try_inequality_filter` accepted would mark a join whose
        # filter then fails to push — `issues/054`, where `gt` became uniquely
        # slow. So drop the guard rather than the row.
        _bool_guard = (f" AND datatype_id IN "
                       f"({ctx.dt_ids_for_uris([f'{_XSD}boolean'])})"
                       if ctx is not None else "")
        return f"term_text IN ({lex}){_bool_guard}"

    if dt in _NUMERIC_DATATYPES:
        num = _numeric_literal(ExprValue(node=value_node))
        if num is None:
            return None            # numeric datatype, unparseable value
        # Numeric equality, so "5.0"^^double and 5^^integer both match and are
        # both correctly excluded — which uuid inequality gets wrong.
        return f"{NUMERIC_TERM_COLUMN} = {num}"

    if dt in _DATETIME_DTS and _ISO_RE.match(raw.strip()):
        # By VALUE, so one instant matches however it is written — `...Z`,
        # `...+00:00` and `2019-12-31T23:00:00-01:00` are the same moment.
        #
        # Plus a timezone-agreement guard, because `vitalgraph_iso_to_utc`
        # reads an untimezoned value AS IF it were UTC. XSD says a timezoned
        # and an untimezoned dateTime are INCOMPARABLE — the answer depends on
        # the offset nobody supplied — so without this, normalising would
        # declare them equal, which is a wrong answer rather than a missing
        # one. Requiring the two to agree makes an incomparable pair simply not
        # match, which is what a FILTER does with a type error anyway and what
        # `datatypes_and_language_tags.md` §4.6 records as the deliberate,
        # practical choice.
        _lit = raw.strip()
        _lit_tz = "true" if _TZ_RE.search(_lit) else "false"
        return (f"{DATETIME_TERM_COLUMN} = "
                f"vitalgraph_iso_to_utc('{_esc(_lit)}') "
                f"AND (term_text ~ '{_TZ_SQL_RE}') IS {_lit_tz}")

    if dt in ("", f"{_XSD}string"):
        # A plain literal and an xsd:string literal are one value in RDF 1.1, so
        # both must match — but ONLY those two.
        #
        # This used to match on `term_text` and `term_type` alone, described as
        # "without pinning the datatype id". That treats plain and xsd:string
        # as one value correctly, and every OTHER datatype sharing the lexical
        # form as the same value incorrectly. Stored, the three are distinct
        # terms:
        #
        #     "x"                  datatype_id NULL
        #     "x"^^xsd:string      datatype_id 1
        #     "x"^^<urn:custom>    datatype_id 41
        #
        # so `FILTER(?v = "x")` over data holding the third returned it —
        # `issues/121` on the pushdown side, and invisible to a test that only
        # compares literals written in the query.
        return (f"term_text = '{_esc(raw)}' AND term_type = 'L'"
                + _plain_string_datatype_guard(ctx))

    # Anything else — a language-tagged literal, an unrecognised datatype —
    # decline rather than answer approximately. A wrong answer here is a row
    # silently included or dropped, not a slow query.
    return None


def _ne_operands(expr, ctx=None):
    """(var_name, value_node) for a PUSHABLE `?var != <literal>`, else None."""
    if not isinstance(expr, ExprFunction):
        return None
    if (expr.name or "").lower() not in _NE_OPS:
        return None
    args = expr.args or []
    if len(args) != 2:
        return None
    if isinstance(args[0], ExprVar) and isinstance(args[1], ExprValue):
        var, node = args[0].var, args[1].node
    elif isinstance(args[1], ExprVar) and isinstance(args[0], ExprValue):
        var, node = args[1].var, args[0].node
    else:
        return None
    if _ne_equality_cond(node, ctx) is None:
        return None
    return var, node


def _inequality_var(expr) -> Optional[str]:
    """Variable of a pushable `?var != <literal>`, or None.

    Defers to `_ne_operands` so the gate and the emitter cannot drift apart.
    """
    ops = _ne_operands(expr)
    return ops[0] if ops else None


def _comparable_term_cond(ctx) -> Optional[str]:
    """Terms whose VALUE can be compared, as a term-table condition.

    RDFterm-equal (SPARQL §17.4.1.7) makes a comparison between two literals
    that are not the same RDF term a TYPE ERROR unless their datatype is one
    whose values we can compare. A non-literal is not "both literal", so term
    identity answers definitely for it and it stays. A plain literal has a NULL
    datatype and IS an xsd:string in RDF 1.1, so it stays too.

    None when there is no context to resolve ids against, which leaves the
    caller's condition exactly as it was.
    """
    if ctx is None:
        return None
    from .emit_bgp import _NUMERIC_DATATYPES
    uris = list(_NUMERIC_DATATYPES) + [
        f"{_XSD}string", f"{_XSD}boolean", f"{_XSD}dateTime", f"{_XSD}date",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString",
    ]
    ids = ctx.dt_ids_for_uris(uris)
    return (f"term_type != 'L' OR datatype_id IS NULL "
            f"OR datatype_id IN ({ids})")


def _try_inequality_filter(expr, bgp, term_table: str, quad_aliases: set, ctx):
    """Convert `?var != <literal>` into a NOT IN over the equality set.

    Returns (alias, sql) or None. Declines on anything whose equality semantics
    this cannot express exactly — a wrong answer here is a row silently included
    or dropped, not a slow query.
    """
    ops = _ne_operands(expr)
    if ops is None:
        return None
    var_name, value_node = ops

    slot = bgp.var_slots.get(var_name)
    if not slot or not slot.positions:
        return None
    ref_id, col_name = slot.positions[0]
    if ref_id not in quad_aliases:
        return None

    eq_cond = _ne_equality_cond(value_node, ctx)
    if eq_cond is None:
        return None

    # `NOT IN (things equal to it)` is not the whole of `!=`. A term whose
    # datatype we cannot compare by VALUE is neither equal nor unequal to the
    # literal — it is a TYPE ERROR, which a FILTER drops. `NOT IN` KEEPS those
    # rows, so `?v != 1` over data carrying an unrecognised datatype returned
    # six rows where two are correct (DAWG `open-eq-04`).
    #
    # The expression path learned this rule in 4fae676 and this did not, which
    # is why that commit fixed `open-eq-06` and left `open-eq-04` failing: `!=`
    # on a variable goes through the push-down. Same split as `issues/121`, in
    # the same two files.
    cmp_ok = _comparable_term_cond(ctx)
    tail = ""
    if cmp_ok:
        tail = f" AND {ref_id}.{col_name} IN {_term_set(ctx, term_table, cmp_ok)}"
    return (ref_id, f"{ref_id}.{col_name} NOT IN "
                    f"{_term_set(ctx, term_table, eq_cond)}{tail}")


# `?v IN (a, b, c)` is a disjunction of equalities, so it is the same problem as
# `!=` with the negation dropped and the union widened — `_ne_equality_cond` is
# reused verbatim, which is what makes this sound for the numeric and datetime
# slot classes and declining for booleans, exactly as it is for `ne`.
_IN_OPS = {"in": "IN", "notin": "NOT IN"}


def _in_operands(expr, ctx=None):
    """(var, sql_op, [conds], [value nodes]) for a pushable `?var IN (...)`."""
    if not isinstance(expr, ExprFunction):
        return None
    sql_op = _IN_OPS.get((expr.name or "").lower())
    if sql_op is None:
        return None
    args = expr.args or []
    # One arg is the empty list, which means a constant FALSE/TRUE rather than a
    # value test; leave that for the general emitter.
    if len(args) < 2 or not isinstance(args[0], ExprVar):
        return None
    conds, nodes = [], []
    for item in args[1:]:
        if not isinstance(item, ExprValue):
            return None
        cond = _ne_equality_cond(item.node, ctx)
        if cond is None:
            return None
        conds.append(f"({cond})")
        nodes.append(item.node)
    return args[0].var, sql_op, conds, nodes


def _in_var(expr) -> Optional[str]:
    """Variable of a pushable `?var IN (...)` / `NOT IN (...)`, or None."""
    ops = _in_operands(expr)
    return ops[0] if ops else None


def _literal_term_key(node):
    """(term_text, term_type) when this value is exactly ONE term, else None.

    Only for values whose lexical form IS the value, so value-equality and
    term-equality coincide: URIs, and plain / xsd:string literals (one value in
    RDF 1.1). A typed numeric is not one term — `5`, `5.0` and `05` are three
    terms and one value, which is the whole reason `_ne_equality_cond` compares
    `num_val` instead of text.
    """
    if isinstance(node, URINode):
        return (node.value, "U")
    if not isinstance(node, LiteralNode):
        return None
    if (node.datatype or "") in ("", f"{_XSD}string") and not getattr(node, "lang", None):
        return (node.value or "", "L")
    return None


def _in_as_constants(conds_nodes, ctx) -> Optional[str]:
    """`IN (uuid, uuid)` over resolved constants, or None if not expressible.

    Worth the trouble because the difference is not marginal. As a subquery the
    leaf has no constant object, so the planner cannot drive the two-phase probe
    from the correlated candidate — it instead enumerates every slot holding the
    value and walks the edges back. Measured on has_any/Text: for each of 194
    candidates it scanned 8,660 slots and did 1,680,086 edge lookups.

        IN (SELECT term_uuid FROM term WHERE term_text = 'CA')   11,679 ms
        IN ('44a04397-...'::uuid)                                    37 ms

    Registering the constants here means they are resolved by the SECOND
    materialization pass in `generate_sql`, which exists for this — push-down
    runs during emit, long after the first pass. If one does not resolve,
    `substitute_constants` falls back to a scalar subquery over the `_const`
    CTE, which is correct (a missing term matches nothing) and still small.
    """
    aliases = getattr(ctx, "aliases", None)
    if aliases is None or not hasattr(aliases, "register_constant"):
        return None
    keys = [_literal_term_key(n) for n in conds_nodes]
    if not keys or any(k is None for k in keys):
        return None
    from .collect import _CONST_PREFIX, _CONST_SUFFIX
    toks = []
    for text, ttype in keys:
        col = aliases.register_constant(text, ttype)
        toks.append(f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}")
    return ", ".join(toks)


# ---------------------------------------------------------------------------
# Equality against a single term: FILTER(?var = <uri>)
# ---------------------------------------------------------------------------

def _equality_operands(expr):
    """(var_name, value_node) for `?var = <term>` in either order, else None."""
    # The mapper names it "eq", not "=". Checking for the symbol matched
    # nothing and the handler silently never fired.
    if not isinstance(expr, ExprFunction) or (expr.name or "").lower() != "eq":
        return None
    args = list(expr.args or [])
    if len(args) != 2:
        return None
    if isinstance(args[0], ExprVar) and isinstance(args[1], ExprValue):
        return args[0].var, args[1].node
    if isinstance(args[1], ExprVar) and isinstance(args[0], ExprValue):
        return args[1].var, args[0].node
    return None


def _equality_var(expr) -> Optional[str]:
    ops = _equality_operands(expr)
    return ops[0] if ops else None


def _try_equality_filter(expr, bgp, term_table: str, quad_aliases: set, ctx):
    """Push `FILTER(?var = <uri>)` down to a UUID equality on the leaf.

    Without this the comparison stays at the OUTERMOST level and runs against
    the variable's resolved TEXT, so the whole query is computed and then
    filtered. On a 3-hop traversal pinned by `FILTER(?e0 = <entity>)` the
    generated SQL contained the entity's uuid zero times and its URI once — in a
    trailing `WHERE (v1 = 'urn:graphsyn:entity:1256')`. Every entity in the
    graph was walked three hops, every uuid resolved to text, and then all but
    one starting point discarded.

    Pushing it makes the leaf carry a constant, which is what lets the planner
    drive from it. Same reasoning as `_in_as_constants`, and the same mechanism:
    the constant is registered so the second materialization pass resolves it,
    and an unresolved one degrades to a scalar subquery over `_const` — correct,
    because a URI absent from the term table matches nothing.

    Only single-term values qualify (`_literal_term_key`): a typed numeric is
    several terms and one value, so term equality is not value equality and
    `_try_numeric_filter` owns that case.
    """
    ops = _equality_operands(expr)
    if ops is None:
        return None
    var_name, value_node = ops

    key = _literal_term_key(value_node)
    if key is None:
        return None

    slot = bgp.var_slots.get(var_name)
    if not slot or not slot.positions:
        return None
    ref_id, col_name = slot.positions[0]
    if ref_id not in quad_aliases:
        return None

    aliases = getattr(ctx, "aliases", None)
    if aliases is None or not hasattr(aliases, "register_constant"):
        return None
    from .collect import _CONST_PREFIX, _CONST_SUFFIX
    text, ttype = key
    col = aliases.register_constant(text, ttype)
    token = f"{_CONST_PREFIX}{col}{_CONST_SUFFIX}"
    return (ref_id, f"{ref_id}.{col_name} = {token}")


def _try_in_filter(expr, bgp, term_table: str, quad_aliases: set, ctx):
    """Convert `?var IN (...)` into a semi-join over the union of equality sets.

    Returns (alias, sql) or None.
    """
    # ctx, because `conds` is emitted below and its datatype guard resolves
    # ids against THIS space. `_in_var` may keep the default: it takes ops[0]
    # and discards the SQL.
    ops = _in_operands(expr, ctx)
    if ops is None:
        return None
    var_name, sql_op, conds, nodes = ops

    slot = bgp.var_slots.get(var_name)
    if not slot or not slot.positions:
        return None
    ref_id, col_name = slot.positions[0]
    if ref_id not in quad_aliases:
        return None

    # Prefer resolved uuid constants: they give the leaf a constant object, which
    # is what lets the planner drive the probe from the correlated candidate
    # instead of enumerating the value side. 11,679 ms -> 37 ms on has_any/Text.
    consts = _in_as_constants(nodes, ctx)
    if consts is not None:
        return (ref_id, f"{ref_id}.{col_name} {sql_op} ({consts})")

    return (ref_id, f"{ref_id}.{col_name} {sql_op} "
                    f"{_term_set(ctx, term_table, ' OR '.join(conds))}")
