"""Handler for KIND_UNION."""

from __future__ import annotations

import logging

from .ir import PlanV2
from .emit_context import EmitContext
from .var_scope import compute_scope

logger = logging.getLogger(__name__)


def emit_union(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a UNION.

    Each branch is emitted independently. Missing variables in a branch
    are padded with NULL to produce uniform column sets.
    """
    from .emit import emit

    left_child = plan.children[0]
    right_child = plan.children[1]

    left_ctx = ctx.child()
    right_ctx = ctx.child()

    left_sql = emit(left_child, left_ctx)
    right_sql = emit(right_child, right_ctx)

    # Compute variable sets
    left_scope = compute_scope(left_child)
    right_scope = compute_scope(right_child)
    left_vars = left_scope.all_visible
    right_vars = right_scope.all_visible
    all_vars = sorted(left_vars | right_vars)

    from .sql_type_generation import TypeRegistry, ColumnInfo

    # Allocate new output sql_names for the combined result
    out_names = {}  # sparql_var → output sql_name
    for v in all_vars:
        out_names[v] = ctx.types.allocate(v)

    ctx.log("union", f"left_vars={sorted(left_vars)}, right_vars={sorted(right_vars)}, "
            f"output: {out_names}")

    # Build padded SELECT for each branch — remap child sql_names to output names
    def _padded_select(branch_sql, branch_ctx, branch_vars, alias):
        cols = []
        for v in all_vars:
            out_sn = out_names[v]
            if v in branch_vars:
                child_info = branch_ctx.types.get(v)
                child_sn = child_info.sql_name if child_info else v
                cols.extend(TypeRegistry.remap_columns(child_sn, out_sn, alias))
            else:
                cols.extend(TypeRegistry.null_companions(out_sn))
        return f"SELECT {', '.join(cols)} FROM ({branch_sql}) AS {alias}"

    l_alias = ctx.aliases.next("ul")
    r_alias = ctx.aliases.next("ur")

    padded_left = _padded_select(left_sql, left_ctx, left_vars, l_alias)
    padded_right = _padded_select(right_sql, right_ctx, right_vars, r_alias)

    union_sql = f"{padded_left}\nUNION ALL\n{padded_right}"

    # Wrap in outer SELECT so columns are accessible by name
    u_alias = ctx.aliases.next("u")
    outer_cols = []
    for v in all_vars:
        outer_cols.extend(TypeRegistry.passthrough_columns(out_names[v], u_alias))

    # Register output variables with opaque sql_names
    for v in all_vars:
        l_info = left_ctx.types.get(v)
        r_info = right_ctx.types.get(v)
        l_lane = l_info.typed_lane if l_info else None
        r_lane = r_info.typed_lane if r_info else None
        lane = l_lane if l_lane and l_lane == r_lane else None
        ctx.types.register(ColumnInfo.simple_output(v, out_names[v], typed_lane=lane))

    sql = (
        f"SELECT {', '.join(outer_cols)}\n"
        f"FROM ({union_sql}) AS {u_alias}"
    )
    return sql
