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


def _foldable_exists_join(node, depth: int = 0):
    """`(filter_node, join_node, exists_expr)` for a foldable negation, else None.

    The shape KGQuery produces for `not_exists` / `not_has` / `not_has_any`:

        filter [ExprExists(NOT EXISTS)]
          join
            bgp   <- anchor
            bgp   <- the frame path the EXISTS correlates into

    `mark_semijoins` never marks that join, and it is right not to. The body
    references a variable the RIGHT bgp binds — `?frame_0_0`, meaning "does
    *this* frame have such a slot" — and per SPARQL 1.1 §8.1.1 the body is
    evaluated with the current solution mapping substituted. Dropping the right
    side would drop that binding and change the question being asked.

    So the fold has to go the other way: the EXISTS moves INSIDE the probe,
    where the variable it needs is in scope. This function only recognises the
    shape; the precondition that makes the move sound — every variable the body
    shares with the outer query must be bound by the right bgp — is checked at
    the point of use, where both bgps are known.
    """
    from .ir import KIND_FILTER, KIND_JOIN
    from ..jena_sparql.jena_types import ExprExists

    if node is None or depth > 6:
        return None
    if (node.kind == KIND_FILTER and node.filter_exprs
            and len(node.filter_exprs) == 1
            and isinstance(node.filter_exprs[0], ExprExists)
            and node.children):
        child = node.children[0]
        if child.kind == KIND_JOIN and len(child.children or []) == 2:
            return (node, child, node.filter_exprs[0])
    for c in (node.children or []):
        found = _foldable_exists_join(c, depth + 1)
        if found is not None:
            return found
    return None


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

    if plan.limit < 0:
        return None
    # Either a marked semi-join, or the negation shape: a FILTER whose whole
    # expression is a correlated EXISTS sitting on a two-child JOIN. The latter
    # is never marked, and correctly so — see _foldable_exists_join.
    exists_join = None
    if not _has_semijoin(plan.child):
        exists_join = _foldable_exists_join(plan.child)
        if exists_join is None:
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

    if exists_join is not None:
        exists_filter, sj, exists_expr = exists_join
    else:
        exists_filter, exists_expr = None, None
        sj = find_semijoin(plan.child)
    if sj is None or len(sj.children or []) != 2:
        return None
    left_bgp = find_bgp(sj.children[0])
    right_bgp = find_bgp(sj.children[1])
    if left_bgp is None or right_bgp is None:
        return None

    # The probe walks the right bgp FORWARD, once per anchor row, so a traversal
    # that amplifies makes the per-row cost the amplification factor. Recorded
    # fan-out is the only thing that knows: PostgreSQL underestimates these
    # joins by 305x and 4,761x (issues/059), and the reorder heuristic scores
    # leaf selectivity with no notion of what a join multiplies by.
    #
    # An UNRECOGNISED traversal means no opinion, NOT decline. That looks like
    # the opposite of choose_direction's "unmeasured is unsafe", and is the same
    # principle applied to a different question: conservative means "do not move
    # away from the known-good state". There, the known-good state is not
    # rewriting; here, it is the rewrite that currently answers not_has and
    # not_has_any in 47-163ms and whose bodies this recogniser deliberately does
    # not parse.
    try:
        from .sync_edge_fanout import extract_traversal, assess_traversal
        fanout = getattr(ctx.aliases, "edge_fanout", None) or {}
        if fanout:
            hops = extract_traversal(right_bgp, ctx.aliases)
            if hops:
                verdict = assess_traversal(fanout, hops, "forward")
                if not verdict["safe"]:
                    ctx.log("slice", f"two-phase declined: probe traversal "
                                     f"amplifies forward — {verdict['reason']}")
                    return None
    except Exception:
        pass        # a statistic must never be able to fail a query

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
        if filt is exists_filter:
            continue        # folded into the probe below, not pushed
        push_filters(filt, ctx.space_id, ctx)
        if filt.filter_exprs:
            ctx.log("slice", "two-phase declined: filter not pushed into probe")
            return None

    # Fold a correlated EXISTS into the probe, where the variable it correlates
    # on is in scope.
    extra_conds = None
    if exists_expr is not None:
        from .var_scope import compute_scope
        from .emit_expressions import expr_to_sql_exists_with_overrides

        # SOUNDNESS: every variable the body shares with the outer query must be
        # bound by the right bgp. If it referenced something bound only by the
        # anchor, moving the condition inside the probe would re-scope it — the
        # body would correlate to the wrong row, or to nothing at all.
        #
        # Derived from the PLAN, never from ctx.types: at this point two-phase
        # has emitted only the anchor, so ctx.types does not yet carry the
        # query's variables. Reading it here returned an empty set, which made
        # this check pass vacuously, produced no overrides, and emitted an
        # UNCORRELATED `NOT EXISTS (...)` — "does any slot anywhere have this
        # value", always true, so every entity was excluded and the query
        # returned 0 rows instead of 1,508. Caught by test_comparator_coverage.
        body_vars = set(compute_scope(exists_expr.prepared_plan).all_visible
                        if exists_expr.prepared_plan is not None else ())
        right_vars = set((right_bgp.var_slots or {}).keys())
        left_vars = set((left_bgp.var_slots or {}).keys())
        correlated = body_vars & (right_vars | left_vars)
        outside = correlated - right_vars
        if not body_vars or outside:
            ctx.log("slice", "two-phase declined: EXISTS correlates outside "
                             f"the probe ({sorted(outside)})")
            return None

        overrides = {}
        for var in correlated:
            slot = (right_bgp.var_slots or {}).get(var)
            if slot and slot.positions:
                q_alias, uuid_col = slot.positions[0]
                overrides[var] = f"{q_alias}.{uuid_col}"
        # Every correlated variable must have produced a column. A missing one
        # means an uncorrelated subquery, which is silently wrong rather than an
        # error, so refuse instead.
        if set(overrides) != correlated:
            ctx.log("slice", "two-phase declined: no probe column for "
                             f"{sorted(correlated - set(overrides))}")
            return None
        cond = expr_to_sql_exists_with_overrides(exists_expr, ctx, overrides)
        if not cond:
            ctx.log("slice", "two-phase declined: EXISTS body did not emit")
            return None
        extra_conds = [cond]

    probe = emit_bgp_exists(right_bgp, ctx, (key, col_ref),
                            extra_conds=extra_conds)
    if probe is None:
        return None

    info = ctx.types.get(key)
    sn = info.sql_name if info and info.sql_name else key

    p_alias = ctx.aliases.next("pg")
    t_alias = f"t_{sn}"
    suffix = " DESC" if direction == "DESC" else ""

    # ---- candidate-driven alternative -------------------------------------
    # For a negation whose answer is SPARSE, driving from the walked-back set
    # beats probing from the anchor: when the negation excludes everything the
    # candidate set is empty, so no hop is walked and the anchor is never
    # scanned. Two earlier placements kept the anchor driving and did not help —
    # inlining the set into the probe (per-probe ~21 -> ~69,928) and hanging it
    # off a CTE the probe filtered against (outer Unique still 95 million).
    #
    # Gated on DENSITY, because the trade is real: this gives up the ordered
    # early-terminating scan, so it costs work proportional to the ANSWER —
    # 22-27s when the negation excludes nothing, against a probe that stops
    # after 25 rows.
    if exists_expr is not None and exists_expr.negated:
        cand_sql = _try_candidate_driven(
            plan, ctx, left_bgp, right_bgp, exists_expr, key, col_ref,
            from_sql, where_conds, sn, t_alias)
        if cand_sql is not None:
            return cand_sql


    # DISTINCT, and it must stay (issues/046). EXISTS does not multiply the
    # anchor's rows, but it does not deduplicate them either, and the anchor was
    # never one row per entity: rdf_quad can hold the same (s,p,o,c) more than
    # once, differing by quad_uuid/dataset. Measured on a production copy, 82
    # subjects carried the anchor quad more than once and the page came back
    # with 34,659 rows for 34,423 entities — the right set, the wrong
    # multiplicity, which a subset check cannot see.
    #
    # DISTINCT ON, not DISTINCT, and the difference is the whole ballgame.
    # Plain `SELECT DISTINCT x ... ORDER BY x` lets the planner satisfy the
    # dedup with a HashAggregate and sort afterwards — a blocking node, so every
    # candidate is probed before LIMIT sees anything. Measured: HashAggregate
    # over 35,987 rows, 81-122s. `DISTINCT ON` has only one implementation,
    # Unique over sorted input, so the planner must keep the index-ordered scan
    # and LIMIT still stops early — 52 probes instead of 35,987.
    conds = list(where_conds) + [f"EXISTS (\n{probe}\n)"]
    page = (f"SELECT DISTINCT ON ({col_ref}) {col_ref} AS {sn}__uuid\n"
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
    # This shape is only O(page) while the planner drives it from an ordered,
    # early-terminating scan. Above a data-dependent LIMIT (measured 19, 52 and
    # 174 on three datasets) it switches to a blocking Sort and probes every
    # candidate. Tell the executor, which fences the statement (issues/047).
    ctx.needs_ordered_scan = True
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


def _try_candidate_driven(plan, ctx, left_bgp, right_bgp, exists_expr,
                          key, col_ref, from_sql, where_conds, sn, t_alias):
    """Phase 1 driven by the walked-back candidate set, or None to decline.

    The alternative to probing from the anchor. See emit_backward for why a
    filter cannot reproduce it: an empty candidate set costs nothing, whereas a
    filter still visits every anchor row to discover that none qualify.

    Declines on anything it does not fully recognise. This path returns
    different SQL for the same question, so an approximation here is a wrong
    answer rather than a slow one.
    """
    from .sql_type_generation import TypeRegistry
    from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES
    from .emit_backward import (extract_negated_traversal,
                                extract_positive_chain, emit_candidate_ctes)

    if exists_expr.prepared_plan is None:
        return None
    trav = extract_negated_traversal(exists_expr.prepared_plan,
                                     exists_expr.prepared_aliases)
    if trav is None:
        return None
    chain = extract_positive_chain(right_bgp, ctx.aliases)
    if chain is None:
        return None
    levels, ctx_uuid = chain
    if not levels:
        return None

    # DENSITY gate. The negation must exclude most of the population, or the
    # answer is dense and the forward probe — which stops after one page — wins.
    # The selectivity is already in rdf_stats; an unknown one declines, because
    # guessing favourably is how a rewrite ships looking correct and behaves
    # badly on the shapes nobody profiled.
    stats = getattr(ctx.aliases, "quad_stats", None) or {}
    extra = getattr(ctx.aliases, "extra_quad_stats", None) or {}
    deepest = levels[-1]
    excluded_n = stats.get((trav.leaf_pred, trav.leaf_obj)) or \
        extra.get((trav.leaf_pred, trav.leaf_obj))
    population_n = stats.get((deepest.dest_pred, deepest.dest_obj)) or \
        extra.get((deepest.dest_pred, deepest.dest_obj))
    if not excluded_n or not population_n:
        ctx.log("slice", "candidate-driven declined: negation selectivity "
                         "unknown")
        return None
    if excluded_n < 0.5 * population_n:
        ctx.log("slice", f"candidate-driven declined: negation excludes only "
                         f"{excluded_n}/{population_n} — answer is dense, the "
                         f"probe stops sooner")
        return None

    with_clause, cands = emit_candidate_ctes(
        trav, levels, ctx.space_id, str(ctx_uuid), ctx.aliases.next)

    # `candidates` goes in the FROM so it DRIVES; the anchor becomes a lookup.
    # That is the entire difference from the two placements that did not work.
    c_alias = ctx.aliases.next("cd")
    anchor_from = from_sql.strip()
    if not anchor_from.upper().startswith("FROM "):
        return None
    anchor_tables = anchor_from[5:]
    conds = list(where_conds) + [f"{col_ref} = {c_alias}.n"]

    page = (f"{with_clause}\n"
            f"SELECT DISTINCT ON ({c_alias}.n) {c_alias}.n AS {sn}__uuid\n"
            f"FROM {cands} AS {c_alias}, {anchor_tables}\n"
            f"WHERE {' AND '.join(conds)}\n"
            f"ORDER BY {c_alias}.n\n"
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
    # No ordered-scan fence here: this shape does not depend on an early
    # terminating index scan, it depends on the candidate set being small.
    ctx.log("slice", f"candidate-driven: {len(levels)} level(s) walked back, "
                     f"negation excludes {excluded_n}/{population_n}")
    return (f"SELECT {', '.join(cols)}\n"
            f"FROM ({page}) AS {r_alias}\n"
            f"JOIN {ctx.space_id}_term AS {t_alias} "
            f"ON {r_alias}.{sn}__uuid = {t_alias}.term_uuid")
