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

    # An order this layer SYNTHESIZED for stable paging (`collect._collect_slice`,
    # `issues/075`) is ordered by the variable's UUID, not its text. Any stable
    # order satisfies it, and uuid is the one the paging emitters can produce
    # from an index without resolving text for the whole match set.
    #
    # This is what makes the paths agree. Ordering by text here while
    # `_emit_two_phase` ordered by uuid gave two total orders for one query, so
    # a pagination sequence crossing them skipped and repeated rows
    # (`issues/078`). A user's own ORDER BY has no such hint and is emitted on
    # the text column, as written.
    stable = bool((plan.hints or {}).get("stable_paging"))

    o_alias = ctx.aliases.next("o")
    ob_parts = []
    for key, direction in plan.order_conditions:
        if isinstance(key, str):
            info = ctx.types.get(key)
            sn = info.sql_name if info else key
            if stable:
                col = f"{o_alias}.{sn}__uuid"
            elif info is not None and info.typed_lane:
                # A computed variable on the numeric or boolean lane — ORDER BY
                # over a COUNT, for instance. `sn` is not a text column there
                # and PostgreSQL raises "collations are not supported by type
                # numeric" rather than ignoring the clause. Caught by DAWG
                # aggregates/COUNT 8b.
                col = f"{o_alias}.{sn}"
            else:
                # Pinned, not inherited: SPARQL orders strings by code point and
                # PostgreSQL orders by the cluster's collation. Only the text
                # column takes it — the stable-paging branch orders by uuid,
                # where COLLATE is a type error rather than a no-op.
                from .collation import collate
                col = collate(f"{o_alias}.{sn}")
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
