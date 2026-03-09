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
            col = expr_to_sql(key, ctx)
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
