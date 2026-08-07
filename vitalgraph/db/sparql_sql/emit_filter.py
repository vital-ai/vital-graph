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
    from .filter_pushdown import push_filters

    # Push text and numeric-range filters into the child BGP before emitting
    push_filters(plan, ctx.space_id, ctx)

    child_sql = emit(plan.child, ctx)

    if not plan.filter_exprs:
        return child_sql

    f_alias = ctx.aliases.next("f")
    where_parts = []
    # A FILTER's expressions see exactly the variables its child pattern binds
    # (SPARQL §18.2.1). Declaring that lets an unresolvable reference be told
    # apart from a legitimately unbound one — see issue 028.
    from .var_scope import compute_scope
    with ctx.expression_scope(compute_scope(plan.child).all_visible):
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
