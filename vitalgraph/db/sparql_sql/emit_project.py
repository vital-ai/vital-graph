"""Handler for KIND_PROJECT — SELECT projection."""

from __future__ import annotations

import logging

from .ir import PlanV2
from .emit_context import EmitContext

logger = logging.getLogger(__name__)


def emit_project(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a PROJECT modifier.

    Recursively emits the child, then wraps in a SELECT that projects
    only the requested variables with their companion columns.
    """
    from .emit import emit

    child_sql = emit(plan.child, ctx)

    if not plan.project_vars:
        return child_sql

    from .sql_type_generation import TypeRegistry

    p_alias = ctx.aliases.next("p")
    proj_cols = []
    name_map = {}
    for var in plan.project_vars:
        info = ctx.types.get(var)
        if info and info.sql_name:
            sn = info.sql_name
            proj_cols.extend(TypeRegistry.passthrough_columns(sn, p_alias))
        else:
            # Rule 5: NULL companions for out-of-scope variables (§10.5).
            from .sql_type_generation import ColumnInfo
            sn = ctx.types.allocate(var)
            ctx.types.register(ColumnInfo(sparql_name=var, sql_name=sn,
                                          text_col=sn))
            proj_cols.extend(TypeRegistry.null_companions(sn))
        name_map[var] = sn

    ctx.log("project", f"projecting: {name_map}")

    base = (
        f"SELECT {', '.join(proj_cols)}\n"
        f"FROM ({child_sql}) AS {p_alias}"
    )

    # Lift ORDER BY: the child may be an ORDER node whose SQL ends with
    # "ORDER BY ...".  Wrapping it in a subquery buries the ORDER BY where
    # PostgreSQL ignores it.  Re-emit the ORDER BY on the outer SELECT,
    # rewriting column references from the child alias to p_alias.
    child_plan = plan.child if plan.children else None
    # Walk through SLICE to find the ORDER node
    if child_plan and child_plan.kind == "slice" and child_plan.children:
        child_plan = child_plan.children[0]
    if child_plan and child_plan.kind == "order" and child_plan.order_conditions:
        from .emit_expressions import expr_to_sql
        ob_parts = []
        for key, direction in child_plan.order_conditions:
            if isinstance(key, str):
                info = ctx.types.get(key)
                sn = info.sql_name if info else key
                col = f"{p_alias}.{sn}"
            else:
                col = expr_to_sql(key, ctx)
                if not col:
                    continue
            suffix = " DESC" if direction == "DESC" else ""
            ob_parts.append(f"{col}{suffix}")
        if ob_parts:
            base += f"\nORDER BY {', '.join(ob_parts)}"

    return base
