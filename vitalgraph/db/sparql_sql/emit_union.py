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
        # Conservative: a branch missing the variable pads with NULL, so the
        # text column only carries a value when every contributing branch
        # materialised it.
        tm = all(i.text_materialized for i in (l_info, r_info) if i)
        # Term identity propagates on exactly the same terms as text does, and
        # for the same reason: the merged column is only as good as every branch
        # feeding it. Without this a UNION's output NEVER claimed term identity
        # — `simple_output` defaults from_triple and uuid_materialized to False
        # — so `emit_join` fell through to comparing the sides as TEXT:
        #
        #     ON CAST(j0.v0 AS TEXT) = CAST(j1.v3 AS TEXT)
        #
        # even though the branches had carried real term UUIDs the whole way up.
        # That cost 1.2x on a 570,696-row join (2,172 -> 1,816 ms, same rows),
        # and it is the landmine that made withholding text for a counted
        # variable return 0: text NULL on both sides, so the join matched
        # nothing (issues/088).
        #
        # A branch that does not bind the variable contributes no ColumnInfo and
        # is skipped by `if i`; its rows carry a NULL uuid, which is genuinely
        # unbound here rather than "no term identity", so the distinction
        # `has_term_identity` exists to preserve (issues/026, 087) is intact.
        ti = all(i.has_term_identity() for i in (l_info, r_info) if i)
        # Term identity and BOUNDNESS are different claims, and `ti` is only
        # the first: the `if i` above deliberately skips a branch that does not
        # bind the variable, so `ti` says nothing about whether every row binds
        # it. `emit_join._always_bound` reads `uuid_materialized` as exactly
        # that stronger claim, and uses it to drop the compatible-mapping
        # disjuncts and recover an equijoin.
        #
        # Carrying `ti` into it alone therefore asserted always-bound for a
        # variable one branch never binds, the disjuncts went, and those rows
        # died on `NULL = x`:
        #
        #     { ?a ?p 1  { ?p a ?y } UNION { ?a ?z ?p } }
        #
        # answered with the second branch alone. `partial` records the missing
        # half. It is deliberately NOT `from_triple`: that flag also drives
        # DISTINCT, GROUP, MINUS and lane selection -- the note on
        # `uuid_materialized` in sql_type_generation says why widening it is
        # how MINUS became a silent no-op (issue 026) -- and boundness needs a
        # field that means only boundness.
        ctx.types.register(ColumnInfo.simple_output(
            v, out_names[v], typed_lane=lane, text_materialized=tm,
            uuid_materialized=ti,
            partial=(l_info is None or r_info is None)))

    sql = (
        f"SELECT {', '.join(outer_cols)}\n"
        f"FROM ({union_sql}) AS {u_alias}"
    )
    return sql
