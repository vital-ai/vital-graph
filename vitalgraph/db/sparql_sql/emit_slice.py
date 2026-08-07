"""Handler for KIND_SLICE — LIMIT/OFFSET emission."""

from __future__ import annotations

from typing import Optional

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


def _has_semijoin(node, depth: int = 0) -> bool:
    """Is there a semi-join anywhere below? Bounds the two-phase rewrite."""
    if node is None or depth > 6:
        return False
    if getattr(node, "hints", None) and node.hints.get("semijoin"):
        return True
    return any(_has_semijoin(c, depth + 1) for c in (getattr(node, "children", None) or []))


def _filters_between(node, stop, depth: int = 0):
    """FILTER nodes on the path from `node` down to `stop` (exclusive)."""
    from .ir import KIND_FILTER
    if node is None or node is stop or depth > 8:
        return
    if node.kind == KIND_FILTER:
        yield node
    for c in (node.children or []):
        yield from _filters_between(c, stop, depth + 1)


def _emit_two_phase(plan: PlanV2, ctx: EmitContext) -> Optional[str]:
    """Page uuids first, resolve text for the page afterwards.

    Why this exists: with the criteria as a semi-join the driving scan can emit
    rows in `subject_uuid` order, so `LIMIT` should be able to stop after a
    pageful. It cannot, because the term JOIN that resolves the projected
    variable's text sits between the ordered scan and the slice, and a join
    that does not preserve order forces the whole input to be materialised
    first. Measured: 45,926 buffers for a 25-row page — 10,000 probes, one per
    entity in the space.

    Resolving text *after* the LIMIT removes that barrier: the inner query
    touches only uuid columns, so the scan stays ordered and stops early, and
    exactly one page of term lookups follows.

    Returns None when the shape does not qualify, and the caller emits normally.
    """
    from .emit import emit
    from .sql_type_generation import TypeRegistry
    from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES

    if plan.limit < 0 or not _has_semijoin(plan.child):
        return None

    buried = _find_buried_order(plan.child)
    if len(buried) != 1:
        return None
    key, direction = buried[0]
    if not isinstance(key, str):
        return None

    # Phase 1 must be FLAT: the ORDER BY has to land on a real column of the
    # anchor's own table, so an index can supply the order and LIMIT can stop.
    # Wrapping it in a subquery — which is what emit_bgp does for every BGP —
    # puts the ordering above the scan, and PostgreSQL then computes the whole
    # match set and top-N sorts it.
    from .emit_bgp import emit_bgp_anchor, emit_bgp_exists, find_bgp, find_semijoin

    sj = find_semijoin(plan.child)
    if sj is None or len(sj.children or []) != 2:
        return None
    left_bgp = find_bgp(sj.children[0])
    right_bgp = find_bgp(sj.children[1])
    if left_bgp is None or right_bgp is None:
        return None

    anchor = emit_bgp_anchor(left_bgp, ctx, key)
    if anchor is None:
        return None
    col_ref, from_sql, where_conds = anchor

    # FILTERs between the slice and the join are normally applied by
    # emit_filter, which this path bypasses — so push them into the probe
    # explicitly. filter_pushdown turns a numeric range into a term semi-join
    # on the probed BGP, which is exactly where it needs to be evaluated.
    #
    # Then VERIFY. If any expression survives, it would have to be applied above
    # a join whose probed side no longer exposes the variable — which silently
    # returns rows that do not satisfy the criterion. That is not hypothetical:
    # dropping the variable without landing the filter produced a page
    # containing entities outside the result set. Unconsumed filter => bail out
    # and let the ordinary path handle it, slower and correct.
    from .filter_pushdown import push_filters
    for filt in _filters_between(plan.child, sj):
        push_filters(filt, ctx.space_id, ctx)
        if filt.filter_exprs:
            ctx.log("slice", "two-phase declined: filter not pushed into probe")
            return None

    probe = emit_bgp_exists(right_bgp, ctx, (key, col_ref))
    if probe is None:
        return None

    info = ctx.types.get(key)
    sn = info.sql_name if info and info.sql_name else key

    p_alias = ctx.aliases.next("pg")
    t_alias = f"t_{sn}"
    suffix = " DESC" if direction == "DESC" else ""

    conds = list(where_conds) + [f"EXISTS (\n{probe}\n)"]
    page = (f"SELECT {col_ref} AS {sn}__uuid\n"
            f"{from_sql}\n"
            f"WHERE {' AND '.join(conds)}\n"
            f"ORDER BY {col_ref}{suffix}\n"
            f"LIMIT {plan.limit}")
    if plan.offset > 0:
        page += f"\nOFFSET {plan.offset}"

    r_alias = ctx.aliases.next("r")
    cols = TypeRegistry.term_table_columns(
        sn, t_alias, r_alias, "",
        dt_case_sql=ctx.dt_case_expr(t_alias),
        numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
        boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
        datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES),
    )
    ctx.log("slice", f"two-phase page: uuid-only LIMIT {plan.limit}, "
                     f"text resolved after")
    return (f"SELECT {', '.join(cols)}\n"
            f"FROM ({page}) AS {r_alias}\n"
            f"JOIN {ctx.term_table} AS {t_alias} "
            f"ON {r_alias}.{sn}__uuid = {t_alias}.term_uuid\n"
            f"ORDER BY {r_alias}.{sn}__uuid{suffix}")


def emit_slice(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a SLICE modifier (LIMIT/OFFSET)."""
    from .emit import emit
    from .emit_expressions import expr_to_sql

    two_phase = _emit_two_phase(plan, ctx)
    if two_phase is not None:
        return two_phase

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
