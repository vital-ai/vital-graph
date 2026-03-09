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

    return (
        f"SELECT {', '.join(proj_cols)}\n"
        f"FROM ({child_sql}) AS {p_alias}"
    )
