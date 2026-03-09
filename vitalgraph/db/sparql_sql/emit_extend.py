"""Handler for KIND_EXTEND — BIND expression emission."""

from __future__ import annotations

import logging
from typing import Optional

from ..jena_sparql.jena_types import ExprFunction, ExprVar, ExprValue, LiteralNode

from .ir import PlanV2
from .emit_context import EmitContext
from .sql_type_generation import infer_expr_type

logger = logging.getLogger(__name__)


def _patch_strafter_strbefore_companions(
    plan: PlanV2, ctx: EmitContext, typed
) -> None:
    """Make STRAFTER/STRBEFORE lang/datatype companions conditional.

    When the pattern is found, preserve the input's lang/datatype.
    When not found, clear them (return plain literal).
    """
    from .emit_expressions import expr_to_sql

    expr = plan.extend_expr
    if not isinstance(expr, ExprFunction):
        return
    fname = (expr.name or "").lower()
    if fname not in ("strafter", "strbefore") or len(expr.args) < 2:
        return

    arg0 = expr.args[0]
    if not isinstance(arg0, ExprVar):
        return
    arg0_info = ctx.types.get(arg0.var)
    if not arg0_info:
        return

    pat_sql = expr_to_sql(expr.args[1], ctx)
    str_sql = expr_to_sql(arg0, ctx)
    if not pat_sql or not str_sql:
        return

    found_cond = f"(POSITION({pat_sql} IN {str_sql}) > 0 OR {pat_sql} = '')"

    lang_src = arg0_info.lang_col or "NULL"
    typed.lang = (f"CASE WHEN {found_cond} THEN {lang_src} ELSE NULL END")
    typed.lang_is_sql = True

    dt_src = arg0_info.dt_col or "NULL"
    typed.datatype = (f"CASE WHEN {found_cond} THEN {dt_src} ELSE NULL END")
    typed.datatype_is_sql = True


def _patch_concat_companions(
    plan: PlanV2, ctx: EmitContext, typed
) -> None:
    """Make CONCAT lang companion conditional.

    SPARQL CONCAT: if all args have the same non-empty lang tag,
    the result has that lang. Otherwise, the result is a plain literal.
    """
    expr = plan.extend_expr
    if not isinstance(expr, ExprFunction):
        return
    fname = (expr.name or "").lower()
    if fname != "concat":
        return

    # Collect lang column references for variable args
    lang_cols = []
    for arg in expr.args:
        if isinstance(arg, ExprVar):
            info = ctx.types.get(arg.var)
            if info and info.lang_col:
                lang_cols.append(info.lang_col)
            else:
                # Arg without lang info → result is always plain
                typed.lang = None
                typed.lang_is_sql = False
                return
        elif isinstance(arg, ExprValue) and hasattr(arg, 'node'):
            if isinstance(arg.node, LiteralNode) and arg.node.lang:
                lang_cols.append(f"'{arg.node.lang}'")
            else:
                # Plain literal constant → result is always plain
                typed.lang = None
                typed.lang_is_sql = False
                return

    if len(lang_cols) < 2:
        return

    # All args are variables/literals with lang info.
    # Result has lang only if all args have the SAME non-empty lang tag.
    first = lang_cols[0]
    same_checks = []
    for lc in lang_cols[1:]:
        same_checks.append(f"LOWER({lc}) = LOWER({first})")
    all_non_null = " AND ".join(
        f"{lc} IS NOT NULL AND {lc} != ''" for lc in lang_cols
    )
    all_same = " AND ".join(same_checks)
    typed.lang = (f"CASE WHEN {all_non_null} AND {all_same} "
                  f"THEN {first} ELSE NULL END")
    typed.lang_is_sql = True


def emit_extend(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for an EXTEND (BIND) modifier.

    Recursively emits the child, then adds the bound variable as a
    computed column in a wrapping SELECT.
    """
    from .emit import emit
    from .emit_expressions import expr_to_sql

    child_sql = emit(plan.child, ctx)

    if not plan.extend_var or plan.extend_expr is None:
        return child_sql

    e_alias = ctx.aliases.next("e")
    var = plan.extend_var
    sql_expr = expr_to_sql(plan.extend_expr, ctx)
    if not sql_expr:
        sql_expr = "NULL"

    # Infer type for companion columns
    typed = infer_expr_type(plan.extend_expr, ctx.types)

    # Post-process companions for functions with conditional type metadata
    _patch_strafter_strbefore_companions(plan, ctx, typed)
    _patch_concat_companions(plan, ctx, typed)

    # Allocate opaque SQL name for the new variable
    sn = ctx.types.allocate(var)

    ctx.log("extend", f"BIND ?{var} → {sn} = {sql_expr[:80]}, "
            f"datatype={typed.datatype}, lane={typed.typed_lane}")

    # Register with opaque SQL name
    ctx.types.register_extend(var, typed, sn)

    # Produce companion columns via TypedExpr (firewall)
    # Special case: ExprVar referencing a source variable that has companion
    # columns in the child SQL (from a triple, EXTEND, or SAMPLE aggregate).
    # Pass through ALL companions so type/uuid/lang/datatype/num/bool/dt
    # are preserved.  produce_companions can't infer dynamic metadata from
    # a column reference.  Regular aggregates (COUNT, AVG, etc.) do NOT have
    # companion columns — they use produce_companions instead.
    if isinstance(plan.extend_expr, ExprVar):
        src_info = ctx.types.get(plan.extend_expr.var)
        if (src_info and src_info.sql_name and
                src_info._sql_has_companions):
            from .sql_type_generation import COMPANION_SUFFIXES
            src_sn = src_info.sql_name
            new_cols = [f"{src_sn} AS {sn}"]
            for suffix in COMPANION_SUFFIXES:
                new_cols.append(f"{src_sn}{suffix} AS {sn}{suffix}")
            return (
                f"SELECT *, {', '.join(new_cols)}\n"
                f"FROM ({child_sql}) AS {e_alias}"
            )

    new_cols = typed.produce_companions(sn, sql_expr)

    return (
        f"SELECT *, {', '.join(new_cols)}\n"
        f"FROM ({child_sql}) AS {e_alias}"
    )
