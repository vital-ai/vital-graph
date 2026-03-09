"""Handler for KIND_GROUP — GROUP BY + aggregate emission.

Includes a push-down optimisation: when group-key variables need text
resolution, the term JOINs for those keys are deferred past the GROUP BY
so PG groups on compact UUID columns rather than resolved text.
"""

from __future__ import annotations

import logging
from typing import Optional, Set

from ..jena_sparql.jena_types import ExprVar, ExprAggregator, GroupVar

from .ir import (
    PlanV2,
    KIND_BGP, KIND_TABLE, KIND_NULL, KIND_PATH,
    KIND_PROJECT, KIND_ORDER, KIND_SLICE, KIND_REDUCED,
)
from .emit_context import EmitContext
from .sql_type_generation import infer_expr_type

logger = logging.getLogger(__name__)

# Kinds that are safe to have between GROUP and a leaf node
_SAFE_MODIFIER_KINDS = frozenset({KIND_PROJECT, KIND_ORDER, KIND_SLICE, KIND_REDUCED})
_LEAF_KINDS = frozenset({KIND_BGP, KIND_TABLE, KIND_NULL, KIND_PATH})


def emit_group(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a GROUP BY modifier with aggregates.

    When possible, defers term JOINs for group-key variables past the
    GROUP BY so PG aggregates on compact UUID columns.
    """
    pushdown_vars = _pushdown_candidates(plan, ctx)
    if pushdown_vars:
        return _emit_group_pushdown(plan, ctx, pushdown_vars)
    # COUNT-only with no group keys: defer ALL term JOINs.
    # e.g. SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o } — no text needed.
    if _all_count_no_keys(plan, ctx):
        original = ctx.text_needed_vars
        ctx.text_needed_vars = set()
        result = _emit_group_impl(plan, ctx)
        ctx.text_needed_vars = original
        return result
    return _emit_group_impl(plan, ctx)


def _emit_group_impl(plan: PlanV2, ctx: EmitContext) -> str:
    """Core GROUP BY emission (original logic)."""
    from .emit import emit
    from .emit_expressions import expr_to_sql

    child_sql = emit(plan.child, ctx)
    g_alias = ctx.aliases.next("g")

    # Trace group keys and aggregates
    gk_names = [gv.var if isinstance(gv, GroupVar) else str(gv)
                for gv in (plan.group_vars or [])]
    agg_names = list((plan.aggregates or {}).keys())
    ctx.log("group", f"keys={gk_names}, aggregates={agg_names}")

    # GROUP BY columns
    from .sql_type_generation import TypeRegistry, COMPANION_SUFFIXES
    gb_cols = []
    gb_select = []
    for gv in (plan.group_vars or []):
        var = gv.var if isinstance(gv, GroupVar) else str(gv)
        has_expr = isinstance(gv, GroupVar) and gv.expr is not None

        if has_expr:
            # Expression-based group key: GROUP BY (EXPR AS ?var)
            expr_sql = expr_to_sql(gv.expr, ctx)
            if not expr_sql:
                expr_sql = "NULL"
            gb_cols.append(expr_sql)
            # Allocate opaque name and register ColumnInfo so downstream
            # handlers (ORDER, PROJECT) can find this variable.
            sn = ctx.types.allocate(var)
            typed = infer_expr_type(gv.expr, ctx.types)
            gb_select.extend(typed.produce_companions(sn, expr_sql))
            ctx.types.register_extend(var, typed, sn)
            # If the expression has companion overrides (e.g. COALESCE
            # with dynamic type/datatype), add them to GROUP BY too.
            if typed._companion_overrides:
                for suffix in COMPANION_SUFFIXES:
                    if suffix in typed._companion_overrides:
                        gb_cols.append(typed._companion_overrides[suffix])
        else:
            # Simple variable group key: passthrough from child
            child_info = ctx.types.get(var)
            if child_info and child_info.sql_name:
                sn = child_info.sql_name
                gb_cols.append(f"{g_alias}.{sn}")
                gb_select.extend(TypeRegistry.passthrough_columns(sn, g_alias))
                # Companions must be in GROUP BY too
                for suffix in COMPANION_SUFFIXES:
                    gb_cols.append(f"{g_alias}.{sn}{suffix}")
            else:
                # Rule 5: NULL companions for out-of-scope variables (§10.5).
                # Still add to gb_cols so GROUP BY collapses rows properly.
                from .sql_type_generation import ColumnInfo
                sn = ctx.types.allocate(var)
                info = ColumnInfo(sparql_name=var, sql_name=sn, text_col=sn)
                info._is_null_placeholder = True
                ctx.types.register(info)
                gb_cols.append("CAST(NULL AS text)")
                gb_select.extend(TypeRegistry.null_companions(sn))

    # Collect child variable sql_names for COUNT(DISTINCT *) handling.
    # Use UUID column for triple-sourced vars: robust when term JOINs
    # are deferred (text would be NULL), and UUID is 1:1 with text.
    child_sql_names = []
    for v in ctx.types.all_vars():
        info = ctx.types.get(v)
        if info and info.sql_name:
            if info.from_triple:
                child_sql_names.append(f"{info.sql_name}__uuid")
            else:
                child_sql_names.append(info.sql_name)

    # Aggregate expressions
    agg_select = []
    for agg_var, agg_expr in (plan.aggregates or {}).items():
        if isinstance(agg_expr, ExprAggregator):
            agg_sql = _aggregate_to_sql(agg_expr, g_alias, ctx,
                                         child_sql_names=child_sql_names)
            # Allocate opaque SQL name for the aggregate result
            agg_sn = ctx.types.allocate(agg_var)
            agg_select.append(f"{agg_sql} AS {agg_sn}")

            # Register aggregate in TypeRegistry with opaque SQL name
            agg_name = (agg_expr.name or "").upper()
            input_var = None
            if isinstance(agg_expr.expr, ExprVar):
                input_var = agg_expr.expr.var

            # SAMPLE: also aggregate companion columns so type metadata
            # is preserved through GROUP BY.  SAMPLE → MAX, so we use
            # MAX on every companion from the input variable.
            if agg_name == "SAMPLE" and input_var:
                inp_info = ctx.types.get(input_var)
                if inp_info and inp_info.sql_name:
                    isrc = inp_info.sql_name
                    _SAMPLE_SKIP = {"__uuid", "__bool", "__dt"}
                    for suffix in COMPANION_SUFFIXES:
                        if suffix in _SAMPLE_SKIP:
                            _null = {"__uuid": "NULL",
                                     "__bool": "NULL::boolean",
                                     "__dt": "NULL::timestamp"}[suffix]
                            agg_select.append(f"{_null} AS {agg_sn}{suffix}")
                            continue
                        src_col = f"{g_alias}.{isrc}{suffix}"
                        agg_select.append(f"MAX({src_col}) AS {agg_sn}{suffix}")

            info = ctx.types.register_aggregate(agg_var, agg_name,
                                                 agg_sn, input_var)

            # For SAMPLE, override companions to reference aggregated cols
            if agg_name == "SAMPLE" and input_var:
                inp_info = ctx.types.get(input_var)
                if inp_info and inp_info.sql_name:
                    info.type_col = f"{agg_sn}__type"
                    info.dt_col = f"{agg_sn}__datatype"
                    info.lang_col = f"{agg_sn}__lang"
                    info.num_col = f"{agg_sn}__num"
                    info._has_agg_companions = True
                    info._sql_has_companions = True

            ctx.log("group", f"aggregate ?{agg_var} → {agg_sn} = "
                    f"{agg_name}({input_var}), lane={info.typed_lane}")

    all_select = gb_select + agg_select
    if not all_select:
        all_select = ["1 AS _dummy"]

    parts = [f"SELECT {', '.join(all_select)}"]
    parts.append(f"FROM ({child_sql}) AS {g_alias}")

    if gb_cols:
        parts.append(f"GROUP BY {', '.join(gb_cols)}")

    # HAVING (if present on the group node)
    if plan.having_exprs:
        having_parts = []
        for expr in plan.having_exprs:
            sql_expr = expr_to_sql(expr, ctx)
            if sql_expr:
                having_parts.append(sql_expr)
        if having_parts:
            parts.append(f"HAVING {' AND '.join(having_parts)}")

    return "\n".join(parts)


def _aggregate_to_sql(expr: ExprAggregator, src_alias: str,
                       ctx: EmitContext, *,
                       child_sql_names: list = None) -> str:
    """Convert an ExprAggregator to a SQL aggregate expression.

    After the child SQL is wrapped as (child_sql) AS src_alias, all column
    references must go through ``src_alias.sql_name`` (text) or
    ``src_alias.sql_name__num`` (numeric).  The stale ``info.text_col`` /
    ``info.num_col`` from earlier handlers are NOT valid here.
    """
    from .emit_expressions import expr_to_sql

    agg_name = (expr.name or "COUNT").upper()
    distinct_prefix = "DISTINCT " if expr.distinct else ""

    # PostgreSQL has no SAMPLE(); use MAX() as a deterministic stand-in.
    if agg_name == "SAMPLE":
        agg_name = "MAX"

    if agg_name == "COUNT" and expr.expr is None:
        if expr.distinct and child_sql_names:
            # COUNT(DISTINCT *) — PostgreSQL doesn't support DISTINCT *.
            # Use COUNT(DISTINCT ROW(col1, col2, ...)) instead.
            row_cols = ', '.join(f"{src_alias}.{sn}" for sn in child_sql_names)
            return f"COUNT(DISTINCT ROW({row_cols}))"
        return "COUNT(*)"

    if expr.expr is not None:
        # Resolve the inner expression — but for simple variable references,
        # override with properly-qualified src_alias.sql_name references.
        inner_sql = _qualify_agg_inner(expr.expr, expr, src_alias, ctx)
        if inner_sql is None:
            inner_sql = expr_to_sql(expr.expr, ctx)
        if inner_sql:
            if agg_name == "GROUP_CONCAT":
                sep = expr.separator or ' '
                return f"string_agg({distinct_prefix}{inner_sql}, '{_esc_agg(sep)}')"

            # SPARQL aggregate error semantics (§18.5):
            # If ANY value in the group raises a type error, the whole
            # aggregate is an error (NULL/unbound).  For simple variable
            # references, detect this via COUNT(*) != COUNT(num_col).
            if agg_name in ("AVG", "SUM", "MIN", "MAX") and isinstance(expr.expr, ExprVar):
                error_guard = (f"CASE WHEN COUNT(*) != COUNT({inner_sql}) "
                               f"THEN NULL ELSE ")
                if agg_name == "AVG":
                    # AVG of empty group = 0 (SPARQL spec §18.5.1.5)
                    return (f"CASE WHEN COUNT(*) = 0 THEN 0 "
                            f"WHEN COUNT(*) != COUNT({inner_sql}) THEN NULL "
                            f"ELSE AVG({distinct_prefix}{inner_sql}) END")
                return (f"{error_guard}"
                        f"{agg_name}({distinct_prefix}{inner_sql}) END")

            # For numeric aggregates with complex expressions (IF, COALESCE),
            # wrap in CAST to NUMERIC to avoid CASE branch type mismatches.
            # The expression itself guards against errors.
            if agg_name == "AVG" and not isinstance(expr.expr, ExprVar):
                inner_sql = f"CAST({inner_sql} AS NUMERIC)"
                return f"COALESCE(AVG({distinct_prefix}{inner_sql}), 0)"
            if agg_name == "SUM" and not isinstance(expr.expr, ExprVar):
                inner_sql = f"CAST({inner_sql} AS NUMERIC)"
            return f"{agg_name}({distinct_prefix}{inner_sql})"

    if agg_name == "GROUP_CONCAT":
        return f"string_agg({distinct_prefix}*, ' ')"
    return f"{agg_name}({distinct_prefix}*)"


def _qualify_agg_inner(inner_expr, agg_expr: ExprAggregator,
                        src_alias: str, ctx: EmitContext) -> Optional[str]:
    """Qualify a simple variable reference for use inside an aggregate.

    Returns a properly-qualified SQL expression using src_alias, or None
    if the expression isn't a simple variable (falls back to expr_to_sql).
    """
    if not isinstance(inner_expr, ExprVar):
        return None

    var = inner_expr.var
    info = ctx.types.get(var)
    if not info or not info.sql_name:
        return None

    # Rule 1: NULL = unbound (§10.5). Variables not in BGP are NULL.
    if getattr(info, '_is_null_placeholder', False):
        return "NULL"

    agg_name = (agg_expr.name or "").upper()

    if agg_name in ("SUM", "AVG"):
        # Always use the numeric companion column
        if info.num_col:
            return f"{src_alias}.{info.sql_name}__num"
        return f"CAST({src_alias}.{info.sql_name} AS NUMERIC)"

    if agg_name in ("MIN", "MAX"):
        # Use numeric column if available, else text
        if info.num_col:
            return f"{src_alias}.{info.sql_name}__num"
        return f"{src_alias}.{info.sql_name}"

    if agg_name == "GROUP_CONCAT":
        # Text value
        return f"{src_alias}.{info.sql_name}"

    if agg_name == "COUNT":
        # Use UUID column for triple-sourced vars: UUID is non-null iff
        # the variable is bound, same as text.  This is robust when term
        # JOINs are deferred past GROUP BY (text column would be NULL).
        if info.from_triple:
            return f"{src_alias}.{info.sql_name}__uuid"
        return f"{src_alias}.{info.sql_name}"

    # Default: text column
    return f"{src_alias}.{info.sql_name}"


def _esc_agg(s: str) -> str:
    """Escape a string for use in SQL aggregate separator."""
    return s.replace("'", "''")


def _all_count_no_keys(plan: PlanV2, ctx: EmitContext) -> bool:
    """True when there are no group keys and every aggregate is COUNT.

    In this case no variable's text is needed — COUNT uses UUID columns
    and COUNT(*) references no column at all.  Deferring all term JOINs
    lets PG do a simple parallel index-only count.

    Only safe when the child chain is simple modifiers ending at a leaf
    (no FILTER, EXTEND, JOIN, subquery that may reference text).
    """
    if ctx.text_needed_vars is None:
        return False
    # Must have no group keys
    if plan.group_vars:
        return False
    # Every aggregate must be COUNT
    for _agg_var, agg_expr in (plan.aggregates or {}).items():
        if isinstance(agg_expr, ExprAggregator):
            agg_name = (agg_expr.name or "COUNT").upper()
            if agg_name != "COUNT":
                return False
    # Child chain must be safe modifiers + leaf
    node = plan.child
    while node:
        if node.kind in _LEAF_KINDS:
            return True
        if node.kind not in _SAFE_MODIFIER_KINDS:
            return False
        if not node.children:
            return False
        node = node.children[0]
    return False


# ---------------------------------------------------------------------------
# GROUP BY push-down helpers
# ---------------------------------------------------------------------------

def _pushdown_candidates(plan: PlanV2, ctx: EmitContext) -> Set[str]:
    """Return the set of group-key variable names whose term JOINs can be
    deferred past the GROUP BY, or empty set if push-down is not applicable.

    When ALL aggregates are COUNT (or COUNT(*)), we can defer ALL
    text-needed variables — COUNT uses UUID columns which are always
    available.  This eliminates every term JOIN from the inner scan.

    Conditions:
      - text_needed_vars optimisation is active
      - All group keys are simple variables (no expression keys)
      - All aggregates are COUNT (including COUNT(*), COUNT(DISTINCT))
      - No HAVING clause (may reference text columns)
      - Child chain is a safe modifier stack ending at a leaf
      - At least one group key is in text_needed_vars
    """
    text_needed = ctx.text_needed_vars
    if text_needed is None:
        return set()

    # Require simple group keys
    group_key_vars: Set[str] = set()
    for gv in (plan.group_vars or []):
        has_expr = isinstance(gv, GroupVar) and gv.expr is not None
        if has_expr:
            return set()  # Expression-based key — bail out
        var = gv.var if isinstance(gv, GroupVar) else str(gv)
        group_key_vars.add(var)

    candidates = group_key_vars & text_needed
    if not candidates:
        return set()

    # Only push down when ALL aggregates are COUNT — other aggregates
    # (SUM, AVG, MIN, MAX, GROUP_CONCAT) need text or numeric columns
    # that require term JOINs.
    for _agg_var, agg_expr in (plan.aggregates or {}).items():
        if isinstance(agg_expr, ExprAggregator):
            agg_name = (agg_expr.name or "COUNT").upper()
            if agg_name != "COUNT":
                return set()

    # HAVING may reference text columns — skip push-down
    if plan.having_exprs:
        return set()

    # Walk child chain: only safe modifiers + leaf.
    node = plan.child
    while node:
        if node.kind in _LEAF_KINDS:
            return candidates
        if node.kind not in _SAFE_MODIFIER_KINDS:
            return set()
        if not node.children:
            return set()
        node = node.children[0]
    return set()


def _emit_group_pushdown(plan: PlanV2, ctx: EmitContext,
                          deferred_vars: Set[str]) -> str:
    """Emit GROUP BY with ALL term JOINs deferred.

    Since all aggregates are COUNT (verified by _pushdown_candidates),
    and COUNT uses UUID columns, we can set text_needed = empty so the
    entire inner scan is UUID-only.  After GROUP BY, only the small
    number of group-key output rows need term resolution.
    """
    from .sql_type_generation import TypeRegistry
    from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES

    # Phase 1: defer ALL term JOINs (COUNT uses UUID, safe)
    original_text_needed = ctx.text_needed_vars
    ctx.text_needed_vars = set()

    # Phase 2: normal GROUP BY emission (fully UUID-only inner scan)
    group_sql = _emit_group_impl(plan, ctx)

    ctx.text_needed_vars = original_text_needed  # restore

    # Phase 3: identify which group-key vars need term resolution
    vars_to_resolve = []
    for var in sorted(deferred_vars):
        info = ctx.types.get(var)
        if info and info.from_triple and info.sql_name:
            vars_to_resolve.append((var, info.sql_name))

    if not vars_to_resolve:
        return group_sql

    # Phase 4: build outer SELECT with term JOINs for group keys
    r_alias = ctx.aliases.next("r")
    select_cols = []
    joins = []
    resolved_sns = set()

    for _var, sn in vars_to_resolve:
        t_alias = f"t_{sn}"
        joins.append(
            f"JOIN {ctx.term_table} AS {t_alias} "
            f"ON {r_alias}.{sn}__uuid = {t_alias}.term_uuid"
        )
        select_cols.extend(TypeRegistry.term_table_columns(
            sn, t_alias, r_alias, "",
            dt_case_sql=ctx.dt_case_expr(t_alias),
            numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
            boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
            datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES),
        ))
        resolved_sns.add(sn)

    # Determine which variables are in the GROUP BY output:
    # only group keys + aggregates (child-consumed vars don't survive)
    output_vars = set()
    for gv in (plan.group_vars or []):
        var = gv.var if isinstance(gv, GroupVar) else str(gv)
        output_vars.add(var)
    for agg_var in (plan.aggregates or {}):
        output_vars.add(agg_var)

    # Passthrough columns for non-deferred output vars
    for var in sorted(output_vars):
        info = ctx.types.get(var)
        if not info or not info.sql_name or info.sql_name in resolved_sns:
            continue
        if info._sql_has_companions:
            select_cols.extend(
                TypeRegistry.passthrough_columns(info.sql_name, r_alias))
        else:
            # Aggregate variables: single column, no companions
            sn = info.sql_name
            select_cols.append(f"{r_alias}.{sn} AS {sn}")

    n_deferred = len(vars_to_resolve)
    logger.debug("GROUP BY push-down: %d term JOINs deferred past GROUP BY",
                 n_deferred)

    sql_parts = [f"SELECT {', '.join(select_cols)}"]
    sql_parts.append(f"FROM ({group_sql}) AS {r_alias}")
    sql_parts.extend(joins)

    return "\n".join(sql_parts)
