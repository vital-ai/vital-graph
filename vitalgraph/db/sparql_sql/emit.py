"""
v2 Emitter — slim recursive dispatcher that routes PlanV2 nodes to handlers.

Each plan kind has its own handler module. The dispatcher:
1. Looks up the handler for plan.kind
2. Calls handler(plan, ctx) → SQL string
3. The handler recursively calls emit() for its children

This replaces v1's monolithic 2900-line emit() function with composable,
testable handler modules.
"""

from __future__ import annotations

import logging
from typing import Dict, Callable

from .ir import (
    PlanV2,
    KIND_BGP, KIND_JOIN, KIND_LEFT_JOIN, KIND_UNION, KIND_MINUS,
    KIND_TABLE, KIND_NULL, KIND_PATH,
    KIND_PROJECT, KIND_DISTINCT, KIND_REDUCED, KIND_SLICE,
    KIND_ORDER, KIND_FILTER, KIND_EXTEND, KIND_GROUP,
)
from .emit_context import EmitContext

logger = logging.getLogger(__name__)

# Handler type: (plan, ctx) → SQL string
Handler = Callable[[PlanV2, EmitContext], str]

# Handler registry — populated by _register_handlers() at module load
_HANDLERS: Dict[str, Handler] = {}


def emit(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit a PlanV2 node as a PostgreSQL SQL string.

    Dispatches to the appropriate handler based on plan.kind.
    Each handler recursively calls emit() for its children.
    """
    handler = _HANDLERS.get(plan.kind)
    if handler is None:
        raise NotImplementedError(
            f"No v2 emit handler for plan kind: {plan.kind!r}"
        )

    # Rich dispatch log per §8.3
    n_children = len(plan.children) if plan.children else 0
    modifiers = []
    if plan.filter_exprs:
        modifiers.append("filter")
    if plan.extend_var:
        modifiers.append(f"extend({plan.extend_var})")
    if plan.project_vars:
        modifiers.append(f"project({len(plan.project_vars)})")
    if plan.order_conditions:
        modifiers.append("order")
    if plan.limit >= 0:
        modifiers.append(f"limit({plan.limit})")
    mod_str = f", modifiers: {modifiers}" if modifiers else ""
    if ctx.trace_enabled:
        ctx.trace.log_step(ctx.depth, "dispatch", plan.kind,
                           f"{plan.kind} (children={n_children}{mod_str})")

    sql = handler(plan, ctx)

    # Log resulting SQL and column map
    ctx.log_sql(plan.kind, sql)
    ctx.log_column_map(plan.kind)
    return sql


def _register_handlers():
    """Register all handler modules. Called once at module load."""
    from .emit_bgp import emit_bgp
    from .emit_join import emit_join, emit_left_join
    from .emit_union import emit_union
    from .emit_minus import emit_minus
    from .emit_table import emit_table
    from .emit_null import emit_null
    from .emit_filter import emit_filter
    from .emit_extend import emit_extend
    from .emit_group import emit_group
    from .emit_project import emit_project
    from .emit_order import emit_order
    from .emit_slice import emit_slice
    from .emit_distinct import emit_distinct
    from .emit_path import emit_path

    _HANDLERS[KIND_BGP] = emit_bgp
    _HANDLERS[KIND_JOIN] = emit_join
    _HANDLERS[KIND_LEFT_JOIN] = emit_left_join
    _HANDLERS[KIND_UNION] = emit_union
    _HANDLERS[KIND_MINUS] = emit_minus
    _HANDLERS[KIND_TABLE] = emit_table
    _HANDLERS[KIND_NULL] = emit_null
    _HANDLERS[KIND_FILTER] = emit_filter
    _HANDLERS[KIND_EXTEND] = emit_extend
    _HANDLERS[KIND_GROUP] = emit_group
    _HANDLERS[KIND_PROJECT] = emit_project
    _HANDLERS[KIND_ORDER] = emit_order
    _HANDLERS[KIND_SLICE] = emit_slice
    _HANDLERS[KIND_DISTINCT] = emit_distinct
    _HANDLERS[KIND_PATH] = emit_path
    _HANDLERS[KIND_REDUCED] = emit_distinct  # REDUCED = same as DISTINCT for SQL


_register_handlers()
