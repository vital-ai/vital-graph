"""Handler for KIND_EXTEND — BIND expression emission."""

from __future__ import annotations

import logging
from typing import Optional

from ..jena_sparql.jena_types import ExprFunction, ExprVar, ExprValue, LiteralNode

from .ir import PlanV2
from .emit_context import EmitContext
from .sql_type_generation import infer_expr_type

logger = logging.getLogger(__name__)


def _patch_strafter_strbefore_companions(
    plan: PlanV2, ctx: EmitContext, typed
) -> None:
    """Make STRAFTER/STRBEFORE lang/datatype companions conditional.

    When the pattern is found, preserve the input's lang/datatype.
    When not found, clear them (return plain literal).
    """
    from .emit_expressions import expr_to_sql

    expr = plan.extend_expr
    if not isinstance(expr, ExprFunction):
        return
    fname = (expr.name or "").lower()
    if fname not in ("strafter", "strbefore") or len(expr.args) < 2:
        return

    arg0 = expr.args[0]
    if not isinstance(arg0, ExprVar):
        return
    arg0_info = ctx.types.get(arg0.var)
    if not arg0_info:
        return

    pat_sql = expr_to_sql(expr.args[1], ctx)
    str_sql = expr_to_sql(arg0, ctx)
    if not pat_sql or not str_sql:
        return

    found_cond = f"(POSITION({pat_sql} IN {str_sql}) > 0 OR {pat_sql} = '')"

    lang_src = arg0_info.lang_col or "NULL"
    typed.lang = (f"CASE WHEN {found_cond} THEN {lang_src} ELSE NULL END")
    typed.lang_is_sql = True

    dt_src = arg0_info.dt_col or "NULL"
    typed.datatype = (f"CASE WHEN {found_cond} THEN {dt_src} ELSE NULL END")
    typed.datatype_is_sql = True


def _patch_concat_companions(
    plan: PlanV2, ctx: EmitContext, typed
) -> None:
    """Make CONCAT lang companion conditional.

    SPARQL CONCAT: if all args have the same non-empty lang tag,
    the result has that lang. Otherwise, the result is a plain literal.
    """
    expr = plan.extend_expr
    if not isinstance(expr, ExprFunction):
        return
    fname = (expr.name or "").lower()
    if fname != "concat":
        return

    # Collect lang column references for variable args
    lang_cols = []
    for arg in expr.args:
        if isinstance(arg, ExprVar):
            info = ctx.types.get(arg.var)
            if info and info.lang_col:
                lang_cols.append(info.lang_col)
            else:
                # Arg without lang info → result is always plain
                typed.lang = None
                typed.lang_is_sql = False
                return
        elif isinstance(arg, ExprValue) and hasattr(arg, 'node'):
            if isinstance(arg.node, LiteralNode) and arg.node.lang:
                lang_cols.append(f"'{arg.node.lang}'")
            else:
                # Plain literal constant → result is always plain
                typed.lang = None
                typed.lang_is_sql = False
                return

    if len(lang_cols) < 2:
        return

    # All args are variables/literals with lang info.
    # Result has lang only if all args have the SAME non-empty lang tag.
    first = lang_cols[0]
    same_checks = []
    for lc in lang_cols[1:]:
        same_checks.append(f"LOWER({lc}) = LOWER({first})")
    all_non_null = " AND ".join(
        f"{lc} IS NOT NULL AND {lc} != ''" for lc in lang_cols
    )
    all_same = " AND ".join(same_checks)
    typed.lang = (f"CASE WHEN {all_non_null} AND {all_same} "
                  f"THEN {first} ELSE NULL END")
    typed.lang_is_sql = True


def _try_vector_driving_extend(plan: PlanV2, ctx: EmitContext, child_sql: str) -> Optional[str]:
    """Attempt a driving top-K for this EXTEND node — vector OR text.

    With the `vg_top_k` hint, emit a JOIN against a subquery that ranks INSIDE
    the side table and returns only K rows, so the index drives: HNSW for
    vectors, GIN for text. Returns the full SQL string, or None to fall back to
    the correlated path.

    Text was added 2026-09-21. Without it `ORDER BY score LIMIT 25` scored
    every MATCH — 80,705 of them for one measured phrase — and pushed all of
    them through the outer joins and sort to return 25 rows.
    """
    top_k = plan.hints.get('vg_top_k')
    if not top_k:
        return None

    from .vg_functions import (
        vector_top_k_driving_sql, text_top_k_driving_sql,
        is_vg_vector_function, VG_TEXT_SEARCH,
    )

    expr = plan.extend_expr
    if not isinstance(expr, ExprFunction):
        return None
    # TEXT IS DELIBERATELY NOT ROUTED HERE. Tried and reverted 2026-09-21.
    #
    # A driving top-K only pays when the side table can PRODUCE rows in the
    # required order and stop — PostgreSQL's executor is demand-driven, so a
    # LIMIT above an ordered scan pulls only what it needs. pgvector's HNSW
    # supports that: `ORDER BY embedding <=> x LIMIT k` is an index-ordered
    # scan.
    #
    # GIN CANNOT. `ts_rank_cd` is computed from the heap tuple, not from the
    # index, so ranked top-N must fetch EVERY match and sort. Measured on a
    # phrase matching 80,705 of 321,276 rows, returning 25:
    #
    #     ranked top 25    Bitmap Heap Scan actual rows=80,705 -> top-N
    #                      heapsort                              1,145 ms
    #     unranked first 25  scan stops at 25                       381 ms
    #
    # So the top-K form still reads every match, and adding it on top of the
    # `push_text_search` narrowing made the query SLOWER end-to-end, not
    # faster. `text_top_k_driving_sql` is kept in `vg_functions` because the
    # shape is correct and becomes worthwhile the moment the index can order
    # by rank — RUM supports it, GIN does not.
    is_text = getattr(expr, "function_iri", None) == VG_TEXT_SEARCH
    if is_text:
        return None
    if not is_vg_vector_function(expr):
        return None

    # Resolve the entity variable's UUID column from the child context.
    # Since child_sql is already emitted, the TypeRegistry should have it.
    # If _resolve_uuid_col returns a deferred placeholder, resolve it now.
    from .vg_functions import (
        extract_vector_args, extract_text_search_args, _resolve_uuid_col)
    if is_text:
        targs = extract_text_search_args(expr)
        entity_var = targs.entity_var if targs else None
    else:
        vargs = extract_vector_args(expr)
        entity_var = vargs.entity_var if vargs else None
    if not entity_var:
        return None
    child_uuid_col = _resolve_uuid_col(entity_var, ctx)
    if child_uuid_col is None:
        return None
    # Resolve any deferred placeholder immediately (child is already emitted)
    for deferred_var, placeholder in ctx.pop_deferred_uuids():
        info = ctx.types.get(deferred_var)
        if info and info.uuid_col:
            child_uuid_col = child_uuid_col.replace(placeholder, info.uuid_col)
        else:
            logger.warning("Cannot resolve deferred UUID ?%s in vector driving path", deferred_var)
            return None

    threshold = plan.hints.get('vg_threshold')
    if is_text:
        # DESC only. The form below ranks `ORDER BY ts_rank_cd(...) DESC` —
        # "most relevant first", which is what a relevance search means. An
        # ASC top-K asks for the WORST K matches, and serving it from a form
        # hardcoded to DESC would return the wrong K without erroring.
        if (top_k.get('direction') or 'DESC').upper() != 'DESC':
            return None
        # No threshold arm: a tsvector match is boolean, and `ts_rank_cd`
        # thresholds are not comparable across queries.
        driving = text_top_k_driving_sql(
            expr, ctx, limit=top_k['limit'],
            child_sql=child_sql, child_uuid_col=child_uuid_col,
        )
    else:
        driving = vector_top_k_driving_sql(
            expr, ctx, limit=top_k['limit'], threshold=threshold,
            child_sql=child_sql, child_uuid_col=child_uuid_col,
        )
    if driving is None:
        return None

    # Record vector request if needed
    if driving.vec_request is not None:
        ctx.add_vector_request(driving.vec_request)

    # Allocate names
    var = plan.extend_var
    assert var is not None  # guaranteed by caller guard
    sn = ctx.types.allocate(var)
    e_alias = ctx.aliases.next("e")
    v_alias = ctx.aliases.next("vt")

    # Register as numeric extend (xsd:double)
    from .sql_type_generation import infer_expr_type
    typed = infer_expr_type(expr, ctx.types)
    ctx.types.register_extend(var, typed, sn)

    ctx.log("extend", f"BIND ?{var} → {sn} [VECTOR DRIVING top-K={top_k['limit']}]")

    # Emit: child JOIN (vector_subquery) ON uuid match
    # The vector subquery drives with ORDER BY + LIMIT using HNSW index
    new_cols = typed.produce_companions(sn, f"{v_alias}.{driving.score_alias}")

    return (
        f"SELECT {e_alias}.*, {', '.join(new_cols)}\n"
        f"FROM ({child_sql}) AS {e_alias}\n"
        f"JOIN ({driving.join_subquery}) AS {v_alias}\n"
        f"  ON {e_alias}.{driving.uuid_col} = {v_alias}.subject_uuid"
    )


def emit_extend(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for an EXTEND (BIND) modifier.

    Recursively emits the child, then adds the bound variable as a
    computed column in a wrapping SELECT.
    """
    from .emit import emit
    from .emit_expressions import expr_to_sql

    child_sql = emit(plan.child, ctx)

    if not plan.extend_var or plan.extend_expr is None:
        return child_sql

    # Try vector-driving top-K optimization first
    vd_sql = _try_vector_driving_extend(plan, ctx, child_sql)
    if vd_sql is not None:
        return vd_sql

    e_alias = ctx.aliases.next("e")
    var = plan.extend_var

    # Pass vg: optimizer hints to expression emitter
    saved_hints = ctx.vg_hints
    ctx.vg_hints = plan.hints if plan.hints else {}

    sql_expr = expr_to_sql(plan.extend_expr, ctx)
    if not sql_expr:
        sql_expr = "NULL"

    ctx.vg_hints = saved_hints

    # Resolve deferred UUID placeholders now that child types are populated
    for deferred_var, placeholder in ctx.pop_deferred_uuids():
        info = ctx.types.get(deferred_var)
        if info and info.uuid_col:
            sql_expr = sql_expr.replace(placeholder, info.uuid_col)
            logger.debug("Resolved deferred UUID ?%s → %s", deferred_var, info.uuid_col)
        else:
            logger.error(
                "Cannot resolve deferred UUID for ?%s after child emit — "
                "variable not bound by any triple pattern in scope",
                deferred_var,
            )

    # Infer type for companion columns
    typed = infer_expr_type(plan.extend_expr, ctx.types)

    # Post-process companions for functions with conditional type metadata
    _patch_strafter_strbefore_companions(plan, ctx, typed)
    _patch_concat_companions(plan, ctx, typed)

    # Allocate opaque SQL name for the new variable
    sn = ctx.types.allocate(var)

    ctx.log("extend", f"BIND ?{var} → {sn} = {sql_expr[:80]}, "
            f"datatype={typed.datatype}, lane={typed.typed_lane}")

    # Register with opaque SQL name
    ctx.types.register_extend(var, typed, sn)

    # Produce companion columns via TypedExpr (firewall)
    # Special case: ExprVar referencing a source variable that has companion
    # columns in the child SQL (from a triple, EXTEND, or SAMPLE aggregate).
    # Pass through ALL companions so type/uuid/lang/datatype/num/bool/dt
    # are preserved.  produce_companions can't infer dynamic metadata from
    # a column reference.  Regular aggregates (COUNT, AVG, etc.) do NOT have
    # companion columns — they use produce_companions instead.
    if isinstance(plan.extend_expr, ExprVar):
        src_info = ctx.types.get(plan.extend_expr.var)
        if (src_info and src_info.sql_name and
                src_info._sql_has_companions):
            from .sql_type_generation import COMPANION_SUFFIXES
            src_sn = src_info.sql_name
            new_cols = [f"{src_sn} AS {sn}"]
            for suffix in COMPANION_SUFFIXES:
                new_cols.append(f"{src_sn}{suffix} AS {sn}{suffix}")
            return (
                f"SELECT *, {', '.join(new_cols)}\n"
                f"FROM ({child_sql}) AS {e_alias}"
            )

    new_cols = typed.produce_companions(sn, sql_expr)

    return (
        f"SELECT *, {', '.join(new_cols)}\n"
        f"FROM ({child_sql}) AS {e_alias}"
    )
