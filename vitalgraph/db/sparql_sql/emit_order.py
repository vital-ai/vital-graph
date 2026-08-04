"""Handler for KIND_ORDER — ORDER BY emission."""

from __future__ import annotations

import logging

from .ir import PlanV2
from .emit_context import EmitContext

logger = logging.getLogger(__name__)


def emit_order(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for an ORDER BY modifier.

    Recursively emits the child, then wraps with ORDER BY.
    """
    from .emit import emit
    from .emit_expressions import expr_to_sql

    child_sql = emit(plan.child, ctx)

    if not plan.order_conditions:
        return child_sql

    o_alias = ctx.aliases.next("o")
    ob_parts = []
    for key, direction in plan.order_conditions:
        if isinstance(key, str):
            info = ctx.types.get(key)
            sn = info.sql_name if info else key
            col = f"{o_alias}.{sn}"
        else:
            col = _scoped_expr(key, plan, ctx)
            if not col:
                continue
        suffix = " DESC" if direction == "DESC" else ""
        ob_parts.append(f"{col}{suffix}")

    if not ob_parts:
        return child_sql

    ctx.log("order", f"ORDER BY: {', '.join(ob_parts)}")

    return (
        f"SELECT * FROM ({child_sql}) AS {o_alias}\n"
        f"ORDER BY {', '.join(ob_parts)}"
    )


def _scoped_expr(expr, plan, ctx):
    """Emit an expression with the child pattern's variables declared in scope.

    These expressions apply to whatever the child binds, so that is the scope
    an unresolvable reference should be judged against (issue 028).
    """
    from .emit_expressions import expr_to_sql
    from .var_scope import compute_scope

    child = plan.child if getattr(plan, "child", None) is not None else None
    in_scope = compute_scope(child).all_visible if child is not None else None
    with ctx.expression_scope(in_scope):
        return expr_to_sql(expr, ctx)
