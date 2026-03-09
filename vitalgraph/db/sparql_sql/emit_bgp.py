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

from .ir import PlanV2, TableRef, VarSlot
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

    inner_sql = "\n".join(inner_parts)

    # --- Build OUTER query (JOIN term for text + derived columns) ---
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

        # No term table needed — just pass through UUID, null everything else
        outer_cols.extend(TypeRegistry.null_companions(sn))
        # Override the uuid column with the actual passthrough
        # null_companions uses typed nulls (NULL::uuid), so match that format
        for i, c in enumerate(outer_cols):
            if c.endswith(f" AS {sn}__uuid"):
                outer_cols[i] = f"{sub_alias}.{sn}__uuid AS {sn}__uuid"
                break

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
        ctx.types.register(ColumnInfo.simple_output(var, sn, from_triple=has_term))

    # Trace: SPARQL→SQL name allocation
    ctx.log("bgp", f"name map: {sql_names}")
    ctx.log_scope("bgp", defined=set(plan.var_slots.keys()))

    return sql
