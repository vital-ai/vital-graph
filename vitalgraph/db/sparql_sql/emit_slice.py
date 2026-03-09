"""Handler for KIND_SLICE — LIMIT/OFFSET emission."""

from __future__ import annotations

from .ir import PlanV2, KIND_DISTINCT, KIND_REDUCED, KIND_PROJECT, KIND_ORDER
from .emit_context import EmitContext


def _find_buried_order(plan: PlanV2, depth: int = 0) -> list:
    """Walk child chain (DISTINCT→PROJECT→ORDER) to find ORDER conditions.

    Jena's algebra nests order inside project inside distinct, but SPARQL
    evaluation order is project → distinct → order → limit.  When SLICE
    wraps DISTINCT, we must re-apply ORDER BY after the DISTINCT.
    """
    if depth > 4:
        return []
    if plan.kind == KIND_ORDER and plan.order_conditions:
        return list(plan.order_conditions)
    if plan.kind in (KIND_DISTINCT, KIND_REDUCED, KIND_PROJECT):
        if plan.children:
            return _find_buried_order(plan.children[0], depth + 1)
    return []


def emit_slice(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a SLICE modifier (LIMIT/OFFSET)."""
    from .emit import emit
    from .emit_expressions import expr_to_sql

    child_sql = emit(plan.child, ctx)

    # Re-apply ORDER BY when it's buried inside DISTINCT
    # (SPARQL: order after distinct, Jena algebra: order inside distinct)
    reorder_parts = []
    if plan.child and plan.child.kind in (KIND_DISTINCT, KIND_REDUCED):
        buried = _find_buried_order(plan.child)
        if buried:
            s_alias = ctx.aliases.next("s")
            ob_parts = []
            for key, direction in buried:
                if isinstance(key, str):
                    info = ctx.types.get(key)
                    sn = info.sql_name if info else key
                    col = f"{s_alias}.{sn}"
                else:
                    col = expr_to_sql(key, ctx)
                    if not col:
                        continue
                suffix = " DESC" if direction == "DESC" else ""
                ob_parts.append(f"{col}{suffix}")
            if ob_parts:
                reorder_parts = [
                    f"SELECT * FROM ({child_sql}) AS {s_alias}",
                    f"ORDER BY {', '.join(ob_parts)}",
                ]

    if reorder_parts:
        parts = reorder_parts
    else:
        parts = [child_sql]

    if plan.limit >= 0:
        parts.append(f"LIMIT {plan.limit}")
    if plan.offset > 0:
        parts.append(f"OFFSET {plan.offset}")

    if len(parts) == 1:
        return child_sql

    ctx.log("slice", f"LIMIT={plan.limit}, OFFSET={plan.offset}")

    return "\n".join(parts)
