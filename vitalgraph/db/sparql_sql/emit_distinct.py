"""Handler for KIND_DISTINCT and KIND_REDUCED.

Includes a push-down optimisation: when text_needed_vars is active and
the child chain is a simple modifier stack above a BGP, DISTINCT is
applied at the UUID level *before* term JOINs.  This can reduce the
working set by orders of magnitude (e.g. 7M rows → 14 for low-
cardinality columns like predicate_uuid).
"""

from __future__ import annotations

import logging

from .ir import (
    PlanV2,
    KIND_BGP, KIND_TABLE, KIND_NULL, KIND_PATH,
    KIND_PROJECT, KIND_ORDER, KIND_SLICE, KIND_REDUCED,
    KIND_FILTER, KIND_EXTEND, KIND_GROUP,
)
from .emit_context import EmitContext

logger = logging.getLogger(__name__)


def emit_distinct(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for DISTINCT/REDUCED modifier.

    When possible, pushes DISTINCT below term JOINs so deduplication
    operates on compact UUID columns rather than resolved text.
    """
    from .emit import emit

    if _can_pushdown(plan, ctx):
        return _emit_pushdown(plan, ctx)

    child_sql = emit(plan.child, ctx)

    d_alias = ctx.aliases.next("d")
    return (
        f"SELECT DISTINCT * FROM ({child_sql}) AS {d_alias}"
    )


# ---------------------------------------------------------------------------
# Push-down helpers
# ---------------------------------------------------------------------------

_SAFE_MODIFIER_KINDS = frozenset({KIND_PROJECT, KIND_ORDER, KIND_SLICE, KIND_REDUCED})
_LEAF_KINDS = frozenset({KIND_BGP, KIND_TABLE, KIND_NULL, KIND_PATH})


def _can_pushdown(plan: PlanV2, ctx: EmitContext) -> bool:
    """Return True if DISTINCT can safely be pushed below term JOINs.

    Conditions:
      - text_needed_vars optimisation is active (not None) and non-empty
      - The child chain contains only safe modifiers (project, order,
        slice) ending at a leaf (bgp, table, null, path).
      - No FILTER, EXTEND, GROUP, JOIN, LEFT_JOIN, UNION, MINUS —
        these may reference resolved text columns in the child tree.
    """
    text_needed = ctx.text_needed_vars
    if text_needed is None or not text_needed:
        return False

    node = plan.child
    while node:
        if node.kind in _LEAF_KINDS:
            return True
        if node.kind not in _SAFE_MODIFIER_KINDS:
            return False
        if not node.children:
            return False
        node = node.children[0]
    return False


def _output_vars(node: PlanV2, ctx: EmitContext) -> list:
    """Determine the ordered list of variables in the child chain's output.

    If a PROJECT node exists, only its project_vars survive.
    Otherwise, all registered variables are in the output.
    """
    cur = node
    while cur:
        if cur.kind == KIND_PROJECT and cur.project_vars:
            return list(cur.project_vars)
        if cur.kind in _LEAF_KINDS:
            break
        if not cur.children:
            break
        cur = cur.children[0]
    # No PROJECT — all registered vars are output (SELECT *)
    return sorted(ctx.types.all_vars())


def _emit_pushdown(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit DISTINCT with term JOINs deferred past deduplication.

    Strategy: emit the child with no term JOINs, then apply DISTINCT
    over **only the UUID columns** (not the full companion set).  This
    gives PG a compact hash/sort key it can serve from an index scan.
    After deduplication, resolve text via term JOINs on the small
    result set.
    """
    from .emit import emit
    from .sql_type_generation import TypeRegistry
    from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES

    # Phase 1: find output vars (from PROJECT) before emitting anything,
    # then emit the leaf node directly — bypassing ORDER/PROJECT layers
    # that would create nested subqueries preventing PG parallel scans.
    output_vars = _output_vars(plan.child, ctx)

    leaf = plan.child
    while leaf.kind in _SAFE_MODIFIER_KINDS and leaf.children:
        leaf = leaf.children[0]

    original_text_needed = ctx.text_needed_vars
    ctx.text_needed_vars = set()
    child_sql = emit(leaf, ctx)
    ctx.text_needed_vars = original_text_needed

    vars_to_resolve = []  # (sparql_var, sql_name) — need term JOINs
    other_vars = []        # (sparql_var, sql_name) — UUID passthrough only
    for var in output_vars:
        info = ctx.types.get(var)
        if not info or not info.sql_name:
            continue
        sn = info.sql_name
        if var in original_text_needed and info.from_triple:
            vars_to_resolve.append((var, sn))
        else:
            other_vars.append((var, sn))

    if not vars_to_resolve:
        # Nothing to resolve — fall back to plain DISTINCT
        d_alias = ctx.aliases.next("d")
        return f"SELECT DISTINCT * FROM ({child_sql}) AS {d_alias}"

    # Phase 3: compact DISTINCT on UUID columns only
    d_alias = ctx.aliases.next("d")
    all_output = vars_to_resolve + other_vars
    uuid_cols = [f"{d_alias}.{sn}__uuid AS {sn}__uuid"
                 for _var, sn in all_output]
    distinct_sql = (
        f"SELECT DISTINCT {', '.join(uuid_cols)}\n"
        f"FROM ({child_sql}) AS {d_alias}"
    )

    # Phase 4: wrap with term JOINs + null companions
    r_alias = ctx.aliases.next("r")
    select_cols = []
    joins = []

    for _var, sn in vars_to_resolve:
        t_alias = f"t_{sn}"
        joins.append(
            f"JOIN {ctx.term_table} AS {t_alias} "
            f"ON {r_alias}.{sn}__uuid = {t_alias}.term_uuid"
        )
        select_cols.extend(TypeRegistry.term_table_columns(
            sn, t_alias, r_alias, "",
            dt_case_sql=ctx.dt_case_expr(t_alias),
            numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
            boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
            datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES),
        ))

    # Non-text vars: UUID passthrough + null companions
    for _var, sn in other_vars:
        null_cols = TypeRegistry.null_companions(sn)
        # Replace the NULL::uuid placeholder with actual UUID passthrough
        for i, c in enumerate(null_cols):
            if c.endswith(f" AS {sn}__uuid"):
                null_cols[i] = f"{r_alias}.{sn}__uuid AS {sn}__uuid"
                break
        select_cols.extend(null_cols)

    n_deferred = len(vars_to_resolve)
    logger.debug("DISTINCT push-down: %d term JOINs deferred past DISTINCT "
                 "(%d UUID cols)", n_deferred, len(all_output))

    sql_parts = [f"SELECT {', '.join(select_cols)}"]
    sql_parts.append(f"FROM ({distinct_sql}) AS {r_alias}")
    sql_parts.extend(joins)

    return "\n".join(sql_parts)
