"""Handler for KIND_BGP — Basic Graph Pattern emission.

Produces the core quad-table SQL for triple patterns. Uses the v2
EmitContext for companion column management via TypeRegistry.

Strategy (matching v1's optimized path):
  Inner: quad tables + WHERE constraints → UUID columns
  Outer: JOIN term tables for text/type/lang/datatype resolution
         + derived term_num for pre-cast numeric values
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from .ir import PlanV2, TableRef, VarSlot, KIND_BGP
from .emit_context import EmitContext
from .collect import _esc, _const_subquery

logger = logging.getLogger(__name__)

# XSD numeric datatypes for the term_num derived column.
# When datatype is one of these, term_text is pre-cast to NUMERIC so
# downstream handlers (aggregates, arithmetic, comparisons) can reference
# var__num directly without ad-hoc casting.
XSD = "http://www.w3.org/2001/XMLSchema#"
_NUMERIC_DATATYPES = [
    f"{XSD}integer", f"{XSD}int", f"{XSD}long", f"{XSD}short",
    f"{XSD}decimal", f"{XSD}float", f"{XSD}double",
    f"{XSD}nonNegativeInteger", f"{XSD}positiveInteger",
    f"{XSD}negativeInteger", f"{XSD}nonPositiveInteger",
    f"{XSD}unsignedInt", f"{XSD}unsignedLong",
    f"{XSD}unsignedShort", f"{XSD}unsignedByte", f"{XSD}byte",
]
_NUMERIC_DT_SQL_LIST = ", ".join(f"'{dt}'" for dt in _NUMERIC_DATATYPES)
_BOOLEAN_DT = f"{XSD}boolean"
_DATETIME_DATATYPES = [f"{XSD}dateTime", f"{XSD}date"]


def emit_bgp(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit SQL for a Basic Graph Pattern.

    Produces an inner/outer split:
      Inner: SELECT uuid columns FROM quad tables WHERE constraints
      Outer: JOIN term tables for text/type/lang/datatype + derived term_num

    The derived ``term_num`` column pre-casts numeric literals to NUMERIC
    so downstream handlers (aggregates, arithmetic, comparisons) can
    reference ``var__num`` directly without ad-hoc casting.

    IMPORTANT: After emission, TypeRegistry entries use **output column
    names** (simple ``var``, ``var__type``, etc.) — not internal term
    table aliases — so parent handlers can safely wrap this SQL in a
    subquery and reference columns by name.
    """
    quad_tables = [t for t in plan.tables if t.kind in ("quad", "edge", "frame_entity")]

    if not plan.var_slots:
        # All-constant BGP: still need to verify the pattern exists
        if quad_tables and plan.constraints:
            parts = [f"SELECT 1 AS _dummy"]
            parts.append(f"FROM {quad_tables[0].table_name} AS {quad_tables[0].alias}")
            for qt in quad_tables[1:]:
                parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
            parts.append("WHERE " + " AND ".join(plan.constraints))
            parts.append("LIMIT 1")
            return "\n".join(parts)
        return "SELECT 1 AS _dummy"

    # Allocate opaque SQL names for each SPARQL variable
    from .sql_type_generation import TypeRegistry, ColumnInfo
    sql_names: Dict[str, str] = {}  # sparql_var → sql_name
    for var in plan.var_slots:
        sql_names[var] = ctx.types.allocate(var)

    ctx.log("bgp", f"quad tables: {[t.alias for t in quad_tables]}, "
            f"vars: {sql_names}")

    # --- Build INNER query (quad tables + constraints) ---
    # A traversal chain gets its own shape: one nested LATERAL per hop, so the
    # pinned end drives the walk instead of whichever criterion PostgreSQL
    # happened to root on. Same rows either way (see emit_traversal), so this
    # declines to None freely and the flat path below is the fallback.
    hop_wise = _try_hop_wise(plan, ctx, quad_tables, sql_names)
    if hop_wise is not None:
        inner_sql = hop_wise
    else:
        inner_sql = _emit_flat_inner(plan, ctx, quad_tables, sql_names)

    return _wrap_with_terms(plan, ctx, sql_names, inner_sql)


def _emit_flat_inner(plan: PlanV2, ctx: EmitContext, quad_tables, sql_names) -> str:
    """The original inner query: every quad table in one reordered join."""
    inner_cols: List[str] = []
    for var, slot in plan.var_slots.items():
        sn = sql_names[var]
        if slot.positions:
            q_alias, uuid_col = slot.positions[0]
            inner_cols.append(f"{q_alias}.{uuid_col} AS {sn}__uuid")

    if not inner_cols:
        inner_cols = ["1 AS _dummy"]

    inner_parts = [f"SELECT {', '.join(inner_cols)}"]

    # FROM clause — use dependency-graph reordering when tagged_constraints
    # are available, emitting explicit JOIN ... ON <conditions> instead of
    # JOIN ... ON TRUE.  This gives PG direct equi-join hints per step.
    if quad_tables and plan.tagged_constraints:
        from .reorder_bgp import reorder_joins
        ordered, on_map, first_conds = reorder_joins(
            quad_tables, plan.tagged_constraints,
            quad_stats=ctx.aliases.quad_stats,
            pred_stats=ctx.aliases.pred_stats,
            leaf_cardinality=_leaf_cardinality(plan, ctx),
        )
        # When the anchor table has a text-filter (IN SELECT term_uuid),
        # wrap it in a subquery to force PG to evaluate the filter first.
        first_t = ordered[0]
        text_conds = [c for c in first_conds if "IN (SELECT term_uuid" in c]
        other_first_conds = [c for c in first_conds if c not in text_conds]

        if text_conds:
            all_anchor_conds = text_conds + other_first_conds
            # Strip alias prefix inside subquery (alias doesn't exist yet)
            prefix = f"{first_t.alias}."
            stripped = [c.replace(prefix, "") for c in all_anchor_conds]
            inner_parts.append(
                f"FROM (SELECT * FROM {first_t.table_name}"
                f" WHERE {' AND '.join(stripped)} OFFSET 0) AS {first_t.alias}"
            )
        else:
            inner_parts.append(f"FROM {first_t.table_name} AS {first_t.alias}")
            other_first_conds = first_conds  # nothing was split off

        for qt in ordered[1:]:
            conds = on_map.get(qt.alias)
            if conds:
                inner_parts.append(
                    f"JOIN {qt.table_name} AS {qt.alias} ON "
                    + " AND ".join(conds)
                )
            else:
                inner_parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
        if not text_conds and first_conds:
            inner_parts.append("WHERE " + " AND ".join(first_conds))
    elif quad_tables:
        inner_parts.append(f"FROM {quad_tables[0].table_name} AS {quad_tables[0].alias}")
        for qt in quad_tables[1:]:
            inner_parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
        if plan.constraints:
            inner_parts.append("WHERE " + " AND ".join(plan.constraints))

    return "\n".join(inner_parts)


def _try_hop_wise(plan: PlanV2, ctx: EmitContext, quad_tables,
                  sql_names) -> Optional[str]:
    """The hop-wise inner query, when a chain was found and chosen.

    Wrapped so a failure here can never take a query down: the flat path is
    still correct, and losing the optimisation is preferable to losing the
    answer. The decision itself is made in the generator at stage 2d.2, where
    the statistics it reads are already loaded.
    """
    decision = getattr(ctx.aliases, "traversal_decision", None)
    if decision is None or not decision.hop_wise or decision.chain is None:
        return None
    try:
        from .emit_traversal import emit_hop_wise
        return emit_hop_wise(plan, decision.chain, quad_tables, sql_names)
    except Exception as exc:
        logger.warning("hop-wise emission failed, using the flat join: %s", exc)
        return None


def _wrap_with_terms(plan: PlanV2, ctx: EmitContext, sql_names,
                     inner_sql: str) -> str:
    """--- Build OUTER query (JOIN term for text + derived columns) ---"""
    from .sql_type_generation import TypeRegistry, ColumnInfo

    # Only join term tables for variables that need text resolution
    # (projected, filtered, ordered, etc.).  Internal-only variables
    # used solely for UUID-level joins get null companions — saving one
    # term table JOIN each.  text_needed_vars=None means resolve ALL
    # (safe fallback).
    sub_alias = "sub"
    outer_cols: List[str] = []
    outer_joins: List[str] = []
    text_needed = ctx.text_needed_vars  # None or set of SPARQL var names

    for var, slot in plan.var_slots.items():
        sn = sql_names[var]
        needs_text = (text_needed is None or var in text_needed)
        if needs_text and slot.term_ref_id:
            tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
            if tt:
                t_alias = f"t_{sn}"
                outer_joins.append(
                    f"JOIN {ctx.term_table} AS {t_alias} "
                    f"ON {sub_alias}.{sn}__uuid = {t_alias}.term_uuid"
                )
                outer_cols.extend(TypeRegistry.term_table_columns(
                    sn, t_alias, sub_alias, _NUMERIC_DT_SQL_LIST,
                    dt_case_sql=ctx.dt_case_expr(t_alias),
                    numeric_dt_id_list=ctx.dt_ids_for_uris(_NUMERIC_DATATYPES),
                    boolean_dt_id=ctx.dt_ids_for_uris([_BOOLEAN_DT]),
                    datetime_dt_id_list=ctx.dt_ids_for_uris(_DATETIME_DATATYPES),
                ))
                continue

        # Term JOIN deferred: the variable is bound and its __uuid is real,
        # only the text-derived companions are absent. Not null_companions(),
        # which means *unbound* and would NULL the UUID too (issue 030).
        outer_cols.extend(TypeRegistry.deferred_text_companions(sn, sub_alias))

    if not outer_cols:
        outer_cols = ["1 AS _dummy"]

    outer_parts = [f"SELECT {', '.join(outer_cols)}"]
    outer_parts.append(f"FROM ({inner_sql}) AS {sub_alias}")
    outer_parts.extend(outer_joins)

    sql = "\n".join(outer_parts)

    # --- Register variables with opaque OUTPUT column names ---
    for var, slot in plan.var_slots.items():
        sn = sql_names[var]
        has_term = slot.term_ref_id is not None and any(
            t.ref_id == slot.term_ref_id for t in plan.tables
        )
        # Whether the term JOIN was actually emitted above. The variable is
        # bound and its __uuid is real either way; only the text column
        # differs. Recorded so consumers need not consult ctx (issue 030).
        ctx.types.register(ColumnInfo.simple_output(
            var, sn, from_triple=has_term,
            text_materialized=(text_needed is None or var in text_needed),
        ))

    # Trace: SPARQL→SQL name allocation
    ctx.log("bgp", f"name map: {sql_names}")
    ctx.log_scope("bgp", defined=set(plan.var_slots.keys()))

    return sql


def _leaf_cardinality(plan, ctx) -> dict:
    """alias -> row count for each constant leaf, read from the IR.

    `plan.leaf_terms` records `(alias, column) -> (term_text, term_type)` at
    COLLECT time, when the value is known, precisely so consumers do not have to
    recover it from generated SQL. `semijoin._leaf_rows` already reads it for the
    selectivity gate, with a comment saying why: parsing the SQL couples you to
    its text and fails silently when it differs.

    `reorder_joins` predated that and still regex-parsed. It could not read the
    KGQuery shape at all — the object constant arrives in a constraint that also
    references the joined alias, which its parser skips — so no leaf ever got a
    pair count and the chain root fell through to list position (`issues/061`).

    Counts come from the same three places the gate uses, most specific first:
    the `(predicate, object)` preload, the on-demand pairs that `rdf_stats`
    pruning made necessary, then the per-predicate total.
    """
    aliases = ctx.aliases
    consts = getattr(aliases, "constants", None) or {}
    resolved = getattr(aliases, "resolved_constants", None) or {}
    quad_stats = getattr(aliases, "quad_stats", None) or {}
    extra = getattr(aliases, "extra_quad_stats", None) or {}
    pred_stats = getattr(aliases, "pred_stats", None) or {}

    def _uuid(term):
        col = consts.get(term)
        return resolved.get(col) if col else None

    by_alias: dict = {}
    for (alias, col), term in (getattr(plan, "leaf_terms", None) or {}).items():
        u = _uuid(term)
        if not u:
            continue
        if col == "predicate_uuid":
            by_alias.setdefault(alias, {})["p"] = u
        elif col == "object_uuid":
            by_alias.setdefault(alias, {})["o"] = u

    # RANGE leaves bind a predicate and NO constant object, so the pair lookup
    # above can never find them and the per-predicate fallback below reports the
    # whole predicate — millions — for a criterion that is actually served by a
    # narrow index scan on num_val / dt_val.
    #
    # Getting this wrong is not theoretical. Ranking ranges by their predicate
    # total made some other leaf the chain root, the plan stopped driving from
    # the num_val index the range push-down depends on (issues/040 W2,
    # issues/056), and SEVEN comparator cells went from 3-14 ms to 30 s
    # timeouts. `plan.range_leaves` records (alias, col) -> (operator, literal)
    # and `aliases.range_stats` counts them; both existed and neither was read.
    range_stats = getattr(aliases, "range_stats", None) or {}
    range_aliases = set()
    unmeasured_range = False
    for (alias, _col), (op, literal) in (
            getattr(plan, "range_leaves", None) or {}).items():
        range_aliases.add(alias)
        p_uuid = by_alias.get(alias, {}).get("p")
        n = range_stats.get((p_uuid, op, literal)) if p_uuid else None
        if n is None:
            unmeasured_range = True
        else:
            by_alias.setdefault(alias, {})["range_n"] = n

    out: dict = {}
    for alias, parts in by_alias.items():
        if "range_n" in parts:
            out[alias] = parts["range_n"]
            continue
        p_uuid, o_uuid = parts.get("p"), parts.get("o")
        if p_uuid and o_uuid:
            n = quad_stats.get((p_uuid, o_uuid))
            if n is None:
                n = extra.get((p_uuid, o_uuid))
            if n is not None:
                out[alias] = n
                continue
        if alias in range_aliases:
            # A range whose count is unknown. The per-predicate total would be
            # wildly wrong for it, so record nothing rather than something
            # misleading.
            continue
        if p_uuid:
            n = pred_stats.get(p_uuid)
            if n is not None:
                out[alias] = n

    # Hand the range aliases up: root choice needs to know WHICH leaves are
    # index-backed, not just how many rows they match. See reorder_joins.
    out["__range_aliases__"] = range_aliases

    if unmeasured_range:
        # One unrankable range is enough to make the whole comparison unsafe:
        # every other leaf still has a number, so the cheapest of THOSE would win
        # the root and the range would stop driving. Decline to re-root at all
        # and leave the plan exactly as it was — the conservative direction is
        # "do not move away from the known-good state".
        return {}
    return out


def emit_bgp_exists(plan: PlanV2, ctx: EmitContext,
                    correlation: tuple,
                    extra_conds: Optional[list] = None) -> Optional[str]:
    """Emit a BGP as a flat existence test for use inside EXISTS.

    `correlation` is (sparql_var, outer_sql_ref): the variable shared with the
    anchor, and the column on the outer row to bind it to.

    `extra_conds` are additional WHERE predicates evaluated INSIDE this
    subquery. They exist for criteria that correlate to a variable this BGP
    binds rather than to the anchor — a `FILTER NOT EXISTS` asking whether
    *this* frame has a slot, for instance. Such a condition cannot stay above
    the join, because the two-phase rewrite does not project the variable it
    needs; folding it in here is what lets the shape be paged at all
    (issues/057).

    Deliberately NOT `emit_bgp` with a different projection. `emit_bgp` builds
    an inner/outer split — an inner subquery over the quad tables wrapped in an
    outer one that joins the term table and projects companion columns. As the
    body of an EXISTS that wrapper is what PostgreSQL evaluates per outer row,
    and it does not collapse into index probes: measured 1.3M buffers against a
    45,945 baseline, unchanged by pushing the correlation inward or by removing
    the term JOINs. The wrapper itself is the cost.

    So this emits one flat statement — quad and edge tables joined directly,
    `SELECT 1`, no term JOINs, no projection — with the correlation as an
    ordinary constraint so `reorder_joins` can seed the chain from it rather
    than reaching it last. Join ordering still matters inside the probe: a naive
    order measured 9.7s against the set-based plan's 31ms.

    Returns None when the BGP is not a shape this can handle, in which case the
    caller falls back to a plain join.
    """
    from .reorder_bgp import reorder_joins

    quad_tables = [t for t in plan.tables
                   if t.kind in ("quad", "edge", "frame_entity")]
    if not quad_tables or not plan.var_slots:
        return None

    corr_var, corr_ref = correlation
    slot = plan.var_slots.get(corr_var)
    if not slot or not slot.positions:
        return None
    q_alias, uuid_col = slot.positions[0]
    if q_alias not in {t.alias for t in quad_tables}:
        return None

    # The correlation is a constraint like any other, which is what lets the
    # reorderer treat the correlated table as a candidate chain root.
    corr_cond = f"{q_alias}.{uuid_col} = {corr_ref}"
    tagged = list(plan.tagged_constraints) + [(q_alias, corr_cond)]

    ordered, on_map, first_conds = reorder_joins(
        quad_tables, tagged,
        quad_stats=ctx.aliases.quad_stats,
        pred_stats=ctx.aliases.pred_stats,
        leaf_cardinality=_leaf_cardinality(plan, ctx),
    )

    first_t = ordered[0]
    parts = ["SELECT 1", f"FROM {first_t.table_name} AS {first_t.alias}"]
    for qt in ordered[1:]:
        conds = on_map.get(qt.alias)
        if conds:
            parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON "
                         + " AND ".join(conds))
        else:
            parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
    where_conds = list(first_conds) + list(extra_conds or [])
    if where_conds:
        parts.append("WHERE " + " AND ".join(where_conds))
    # OFFSET 0 is an optimisation fence. Without it PostgreSQL pulls the
    # correlated subquery up into a hash semi-join: it builds the full set of
    # qualifying anchors, which both costs the whole match set and destroys the
    # anchor scan's ordering, so LIMIT cannot stop early. With it the subquery
    # stays a per-row probe and the ordered scan survives.
    parts.append("OFFSET 0")

    ctx.log("bgp", f"EXISTS probe: {len(ordered)} table(s), root "
                   f"{first_t.alias}, correlated on {corr_cond}")
    return "\n".join(parts)


def find_bgp(node: Optional[PlanV2], depth: int = 0) -> Optional[PlanV2]:
    """The single BGP under a chain of transparent modifiers, if there is one.

    Only descends where the node cannot change which rows exist — a FILTER or a
    second BGP would make the existence test mean something different.
    """
    from .ir import KIND_PROJECT, KIND_ORDER
    if node is None or depth > 4:
        return None
    if node.kind == KIND_BGP:
        return node
    if node.kind in (KIND_PROJECT, KIND_ORDER) and node.children:
        return find_bgp(node.children[0], depth + 1)
    return None


def emit_bgp_anchor(plan: PlanV2, ctx: EmitContext, var: str):
    """Emit a BGP as a flat FROM/WHERE over its quad tables, for the anchor.

    Returns (column_ref, from_where_sql) or None.

    The point is that `column_ref` is a real column of a real table, so an
    `ORDER BY` on it can be satisfied by an index and `LIMIT` can stop the scan.
    `emit_bgp` wraps every BGP in a subquery, which puts the ordering above the
    scan where no index reaches it — PostgreSQL then computes the whole match
    set and top-N sorts it, which is what a 25-row page was paying for.
    """
    from .reorder_bgp import reorder_joins

    quad_tables = [t for t in plan.tables
                   if t.kind in ("quad", "edge", "frame_entity")]
    slot = plan.var_slots.get(var)
    if not quad_tables or not slot or not slot.positions:
        return None
    q_alias, uuid_col = slot.positions[0]
    if q_alias not in {t.alias for t in quad_tables}:
        return None

    if plan.tagged_constraints:
        ordered, on_map, first_conds = reorder_joins(
            quad_tables, plan.tagged_constraints,
            quad_stats=ctx.aliases.quad_stats,
            pred_stats=ctx.aliases.pred_stats,
            leaf_cardinality=_leaf_cardinality(plan, ctx))
    else:
        ordered, on_map, first_conds = quad_tables, {}, list(plan.constraints)

    first_t = ordered[0]
    parts = [f"FROM {first_t.table_name} AS {first_t.alias}"]
    for qt in ordered[1:]:
        conds = on_map.get(qt.alias)
        parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON "
                     + (" AND ".join(conds) if conds else "TRUE"))
    where = list(first_conds)
    return (f"{q_alias}.{uuid_col}", "\n".join(parts), where)


def find_semijoin(node, depth: int = 0):
    """The nearest JOIN below that was marked as an existence test."""
    from .ir import KIND_JOIN
    if node is None or depth > 6:
        return None
    if node.kind == KIND_JOIN and getattr(node, "hints", None) \
            and node.hints.get("semijoin"):
        return node
    for c in (getattr(node, "children", None) or []):
        f = find_semijoin(c, depth + 1)
        if f is not None:
            return f
    return None
