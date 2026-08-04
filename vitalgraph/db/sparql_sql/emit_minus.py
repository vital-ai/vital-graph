"""Handler for KIND_MINUS."""

from __future__ import annotations

import logging

from .ir import PlanV2
from .emit_context import EmitContext
from .var_scope import compute_scope

logger = logging.getLogger(__name__)


def _identity_expr(alias: str, sql_name: str, info, space_id: str) -> str:
    """Term identity for a shared MINUS variable.

    Uses the stored ``__uuid`` when the variable has a term identity, and
    derives one from the text/type/lang/datatype companions otherwise. Both
    forms are comparable — ``vitalgraph_term_uuid`` mirrors the Python
    ``_generate_term_uuid`` exactly — so a synthesized value on one side
    matches the same term read from the term table on the other.
    """
    from .sql_type_generation import term_identity_expr

    if info is not None and info.has_term_identity():
        return f"{alias}.{sql_name}__uuid"
    return term_identity_expr(alias, sql_name, space_id)


def emit_minus(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for MINUS (set difference).

    SPARQL MINUS removes rows from the left side where the right side
    has matching bindings for shared variables.
    """
    from .emit import emit

    left_child = plan.children[0]
    right_child = plan.children[1]

    left_ctx = ctx.child()
    right_ctx = ctx.child()

    left_sql = emit(left_child, left_ctx)
    right_sql = emit(right_child, right_ctx)

    l_alias = ctx.aliases.next("ml")
    r_alias = ctx.aliases.next("mr")

    left_scope = compute_scope(left_child)
    right_scope = compute_scope(right_child)
    left_vars = left_scope.all_visible
    right_vars = right_scope.all_visible
    shared = left_vars & right_vars
    ctx.log("minus", f"left_vars={sorted(left_vars)}, shared={sorted(shared)}")

    # SELECT all left columns — reuse left child sql_names
    from .sql_type_generation import TypeRegistry, ColumnInfo, term_identity_expr
    select_cols = []
    for v in sorted(left_vars):
        child_info = left_ctx.types.get(v)
        sn = child_info.sql_name if child_info else v
        select_cols.extend(TypeRegistry.passthrough_columns(sn, l_alias))
        lane = child_info.typed_lane if child_info else None
        tm = child_info.text_materialized if child_info else True
        # MINUS passes the left side through unchanged, so its variables keep
        # whatever term identity they had. Not propagating this made a MINUS
        # output feeding a JOIN look synthesized, so emit_join fell back to
        # comparing text columns — which are NULL when the term JOIN was
        # deferred.
        ft = child_info.from_triple if child_info else False
        ctx.types.register(ColumnInfo.simple_output(
            v, sn, typed_lane=lane, from_triple=ft, text_materialized=tm))

    if not shared:
        return f"SELECT {', '.join(select_cols)}\nFROM ({left_sql}) AS {l_alias}"

    # SPARQL MINUS semantics (§18.5):
    # Remove left row μ1 if there EXISTS right row μ2 such that:
    #   1. μ1 and μ2 are compatible (shared bound vars have equal values)
    #   2. dom(μ1) ∩ dom(μ2) ≠ ∅ (at least one shared var bound in both)
    # NULL/unbound variables don't block compatibility.
    compat_parts = []
    nonempty_parts = []
    for v in sorted(shared):
        l_info = left_ctx.types.get(v)
        r_info = right_ctx.types.get(v)
        l_sn = l_info.sql_name if l_info else v
        r_sn = r_info.sql_name if r_info else v
        # Ask whether the variable has a term identity rather than testing its
        # __uuid column for NULL. A value from VALUES/BIND carries a literal
        # NULL::uuid, so reading that column directly says "unbound" for a
        # bound value — which made the domain-intersection test below
        # unsatisfiable and turned the whole MINUS into a no-op (issue 026).
        #
        # A derived identity and a term-table UUID are interchangeable by
        # construction: vitalgraph_term_uuid mirrors _generate_term_uuid, so
        # the two sides compare correctly even when only one is derived.
        l_uuid = _identity_expr(l_alias, l_sn, l_info, ctx.space_id)
        r_uuid = _identity_expr(r_alias, r_sn, r_info, ctx.space_id)
        # Rule 2: 3-part compatibility for joins (§10.5).
        # Compatible: if either side is NULL (unbound), it's fine; otherwise must match.
        compat_parts.append(
            f"({l_uuid} IS NULL OR {r_uuid} IS NULL OR {l_uuid} = {r_uuid})")
        # Domain intersection: at least one var bound in both sides
        nonempty_parts.append(f"({l_uuid} IS NOT NULL AND {r_uuid} IS NOT NULL)")

    corr_clause = " AND ".join(compat_parts)
    domain_clause = " OR ".join(nonempty_parts)

    sql = (
        f"SELECT {', '.join(select_cols)}\n"
        f"FROM ({left_sql}) AS {l_alias}\n"
        f"WHERE NOT EXISTS (\n"
        f"  SELECT 1 FROM ({right_sql}) AS {r_alias}\n"
        f"  WHERE {corr_clause}\n"
        f"  AND ({domain_clause})\n"
        f")"
    )
    return sql
