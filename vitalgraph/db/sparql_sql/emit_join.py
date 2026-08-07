"""Handlers for KIND_JOIN and KIND_LEFT_JOIN."""

from __future__ import annotations

import logging
from typing import Set

from .ir import PlanV2, KIND_TABLE
from .emit_context import EmitContext
from .var_scope import compute_scope

logger = logging.getLogger(__name__)


def _boundness_col(alias: str, sql_name: str, info) -> str:
    """Column whose NULL-ness actually means "this variable is unbound".

    Not simply the text column: when the term JOIN is deferred the text is
    NULL for a variable that is bound, so testing it reports unbound and
    SPARQL's "unbound is compatible with anything" rule then admits rows it
    should not (issue 030).

    A variable with a term identity is tested on ``__uuid``. One without —
    a VALUES/BIND/aggregate value — is tested on its text, which is always
    materialised for exactly the reason it has no term identity: the value was
    synthesized rather than read from a term row, so there is nothing to defer.
    """
    if info is not None and info.has_term_identity():
        return f"{alias}.{sql_name}__uuid"
    return f"{alias}.{sql_name}"


def emit_join(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for an inner JOIN."""
    return _emit_join_impl(plan, ctx, is_left=False)


def emit_left_join(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a LEFT JOIN (OPTIONAL)."""
    return _emit_join_impl(plan, ctx, is_left=True)


def _emit_join_impl(plan: PlanV2, ctx: EmitContext, is_left: bool) -> str:
    """Common implementation for JOIN and LEFT JOIN."""
    from .emit import emit

    left_child = plan.children[0]
    right_child = plan.children[1]

    # Create child contexts with isolated type registries
    left_ctx = ctx.child()
    right_ctx = ctx.child()

    left_sql = emit(left_child, left_ctx)

    l_alias = ctx.aliases.next("j")
    r_alias = ctx.aliases.next("j")

    # Compute variable sets from scopes
    left_scope = compute_scope(left_child)
    right_scope = compute_scope(right_child)
    left_vars = left_scope.all_visible
    right_vars = right_scope.all_visible
    shared = left_vars & right_vars
    all_vars = left_vars | right_vars



    ctx.log("join", f"left_vars={sorted(left_vars)}, right_vars={sorted(right_vars)}, "
            f"shared={sorted(shared)}, is_left={is_left}")

    from .sql_type_generation import TypeRegistry, ColumnInfo

    # Resolve child sql_names for each variable
    def _child_sn(v, child_ctx):
        info = child_ctx.types.get(v)
        return info.sql_name if info else v

    # VALUES (KIND_TABLE) uses UNDEF → NULL; joins must be NULL-tolerant
    left_is_table = left_child.kind == KIND_TABLE
    right_is_table = right_child.kind == KIND_TABLE

    # Semi-join: emit the right side as a flat existence probe correlated on the
    # shared variable. Requires the left side emitted first, for its alias.
    exists_sql = None
    if (not is_left) and plan.hints.get('semijoin') and len(shared) == 1:
        from .emit_bgp import emit_bgp_exists, find_bgp
        v = next(iter(shared))
        l_info = left_ctx.types.get(v)
        rbgp = find_bgp(right_child)
        if rbgp is not None and l_info and l_info.has_term_identity():
            exists_sql = emit_bgp_exists(
                rbgp, right_ctx, (v, f"{l_alias}.{l_info.sql_name}__uuid"))

    if exists_sql is not None:
        semi_cols = []
        for v2 in sorted(left_vars):
            semi_cols.extend(
                TypeRegistry.passthrough_columns(_child_sn(v2, left_ctx), l_alias))
        if semi_cols:
            # Only the left side survives. Register its variables as this node's
            # output — without this an ORDER BY above cannot resolve them and
            # emits the raw SPARQL name as a column. Drop the probed side's
            # private variables for the same reason, in reverse.
            for v2 in sorted(left_vars):
                ci = left_ctx.types.get(v2)
                ctx.types.register(ColumnInfo.simple_output(
                    v2, ci.sql_name if ci else v2,
                    typed_lane=ci.typed_lane if ci else None,
                    from_triple=ci.from_triple if ci else False,
                    text_materialized=ci.text_materialized if ci else True))
            for v2 in sorted(right_vars - left_vars):
                ctx.types.drop(v2)
            ctx.log("join", f"SEMI JOIN via flat probe; dropped "
                            f"{sorted(right_vars - left_vars)}")
            return (f"SELECT {', '.join(semi_cols)}\n"
                    f"FROM ({left_sql}) AS {l_alias}\n"
                    f"WHERE EXISTS (\n{exists_sql}\n)")

    right_sql = emit(right_child, right_ctx)

    # ON clause: shared variables joined by UUID, typed lane, or text
    if shared:
        on_parts = []
        for v in sorted(shared):
            left_info = left_ctx.types.get(v)
            right_info = right_ctx.types.get(v)
            l_sn = left_info.sql_name if left_info else v
            r_sn = right_info.sql_name if right_info else v
            left_has_uuid = bool(left_info and left_info.has_term_identity())
            right_has_uuid = bool(right_info and right_info.has_term_identity())
            if left_has_uuid and right_has_uuid:
                cond = f"{l_alias}.{l_sn}__uuid = {r_alias}.{r_sn}__uuid"
            elif (left_info and right_info
                  and left_info.typed_lane and left_info.typed_lane == right_info.typed_lane):
                lane = left_info.typed_lane
                cond = f"{l_alias}.{l_sn}__{lane} = {r_alias}.{r_sn}__{lane}"
            elif (left_info and left_info.typed_lane
                  and right_info and not right_info.typed_lane and right_info.from_triple):
                lane = left_info.typed_lane
                cond = f"{l_alias}.{l_sn}__{lane} = {r_alias}.{r_sn}__{lane}"
            elif (right_info and right_info.typed_lane
                  and left_info and not left_info.typed_lane and left_info.from_triple):
                lane = right_info.typed_lane
                cond = f"{l_alias}.{l_sn}__{lane} = {r_alias}.{r_sn}__{lane}"
            else:
                cond = (
                    f"CAST({l_alias}.{l_sn} AS TEXT) = CAST({r_alias}.{r_sn} AS TEXT)"
                )
            # Rule 2: 3-part compatibility for joins (§10.5).
            # SPARQL compatible-mapping semantics: unbound (NULL) is
            # compatible with any value.  Apply to VALUES joins AND LEFT
            # JOINs so that sequential OPTIONALs sharing a variable work.
            #
            # The NULL test must use a column that actually signals boundness.
            # The text column does not when the term JOIN was deferred — it is
            # NULL for a variable that IS bound (issue 030 kind D). So prefer
            # __uuid where there is a term identity, and fall back to text
            # only for synthesized values, whose text is always materialised
            # precisely because there is no term row to defer.
            if right_is_table or left_is_table or is_left:
                l_null_col = _boundness_col(l_alias, l_sn, left_info)
                r_null_col = _boundness_col(r_alias, r_sn, right_info)
                cond = f"({l_null_col} IS NULL OR {r_null_col} IS NULL OR {cond})"
            on_parts.append(cond)
        on_clause = " AND ".join(on_parts)
        ctx.log("join", f"ON: {', '.join(on_parts[:3])}{'...' if len(on_parts) > 3 else ''}")
    else:
        on_clause = "TRUE"

    # LEFT JOIN ON expressions (OPTIONAL filter conditions)
    if is_left and plan.left_join_exprs:
        from .emit_expressions import expr_to_sql
        for expr in plan.left_join_exprs:
            sql_expr = expr_to_sql(expr, ctx)
            if sql_expr:
                on_clause += f" AND {sql_expr}"

    # Rule 4: COALESCE for shared variable projection (§10.5).
    # Prefer left's sql_name for shared vars (canonical output name).
    # For VALUES joins and LEFT JOINs, use COALESCE so right-side bindings
    # fill in NULLs from the left (SPARQL compatible-mapping semantics).
    select_cols = []
    values_shared = shared if (left_is_table or right_is_table or is_left) else set()
    for v in sorted(all_vars):
        if v in left_vars:
            sn = _child_sn(v, left_ctx)
            if v in values_shared and v in right_vars:
                r_sn = _child_sn(v, right_ctx)
                select_cols.extend(
                    TypeRegistry.coalesce_columns(sn, l_alias, r_sn, r_alias))
            else:
                select_cols.extend(TypeRegistry.passthrough_columns(sn, l_alias))
        else:
            sn = _child_sn(v, right_ctx)
            select_cols.extend(TypeRegistry.passthrough_columns(sn, r_alias))

    # Register output variables — reuse child sql_names (globally unique)
    # Propagate from_triple so downstream JOINs know the variable has a UUID.
    for v in sorted(all_vars):
        child_info = left_ctx.types.get(v) if v in left_vars else right_ctx.types.get(v)
        sn = child_info.sql_name if child_info else v
        lane = child_info.typed_lane if child_info else None
        ft = child_info.from_triple if child_info else False
        tm = child_info.text_materialized if child_info else True
        ctx.types.register(ColumnInfo.simple_output(
            v, sn, typed_lane=lane, from_triple=ft, text_materialized=tm))

    ctx.log("join", f"output map: {{{', '.join(f'?{v}→{ctx.types.get(v).sql_name}' for v in sorted(all_vars))}}}")
    ctx.log_scope("join", defined=left_vars | right_vars,
                  optional=right_vars - left_vars if is_left else None)

    join_type = "LEFT JOIN" if is_left else "JOIN"

    sql = (
        f"SELECT {', '.join(select_cols)}\n"
        f"FROM ({left_sql}) AS {l_alias}\n"
        f"{join_type} ({right_sql}) AS {r_alias}\n"
        f"ON {on_clause}"
    )
    return sql
