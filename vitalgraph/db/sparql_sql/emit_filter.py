"""Handler for KIND_FILTER — wraps child SQL with WHERE clause."""

from __future__ import annotations

import logging

from .ir import PlanV2
from .emit_context import EmitContext

logger = logging.getLogger(__name__)


def emit_filter(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a FILTER modifier.

    Recursively emits the child, then wraps in a subquery with WHERE.
    Text-based filters (CONTAINS, REGEX, etc.) are pushed down into
    the child BGP as semi-join constraints before emission.
    """
    from .emit import emit
    from .emit_expressions import expr_to_sql
    from .filter_pushdown import push_text_filters

    # Push text filters into child BGP before emitting it
    push_text_filters(plan, ctx.space_id)

    child_sql = emit(plan.child, ctx)

    if not plan.filter_exprs:
        return child_sql

    f_alias = ctx.aliases.next("f")
    where_parts = []
    for expr in plan.filter_exprs:
        sql_expr = expr_to_sql(expr, ctx)
        if sql_expr:
            where_parts.append(sql_expr)

    if not where_parts:
        return child_sql

    ctx.log("filter", f"WHERE: {' AND '.join(p[:60] for p in where_parts)}")

    return (
        f"SELECT * FROM ({child_sql}) AS {f_alias}\n"
        f"WHERE {' AND '.join(where_parts)}"
    )
