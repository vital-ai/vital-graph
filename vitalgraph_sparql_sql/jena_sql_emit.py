"""
Pass 3: EMIT — Walk the resolved RelationPlan tree and produce SQL strings.

Handles BGP (with optimized inner/outer split), JOIN, LEFT JOIN, UNION,
MINUS, TABLE (VALUES), and modifier application via sqlglot.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import sqlglot

from .jena_types import (
    URINode, LiteralNode, VarNode,
    ExprVar, ExprValue, ExprFunction, Expr,
    PathExpr, PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne, PathNegPropSet,
)
from .jena_sql_ir import RelationPlan, PG_DIALECT
from .jena_sql_helpers import _esc, _vars_in_expr
from .jena_sql_expressions import _expr_to_sql_str, _expr_to_sql_str_inner

logger = logging.getLogger(__name__)


# ===========================================================================
# Join reordering
# ===========================================================================

def _reorder_joins(quad_tables, tagged_constraints):
    """Reorder quad tables so every JOIN references an already-placed table.

    SPARQL triple patterns may produce disconnected "islands" (e.g. slot
    properties listed before the edge that connects them to the frame).
    This creates cartesian products that are catastrophically slow.

    The algorithm:
    1. Parse each tagged constraint to find which *other* aliases it references.
    2. Greedy placement: repeatedly pick the remaining table that has the
       most constraints connecting it to already-placed tables.
    3. Assign each constraint to the ON clause of the *last-placed* alias
       among all aliases it involves (so all references are already in scope).

    Returns (ordered_tables, on_map, first_conds):
        ordered_tables: list of TableRef in optimised order
        on_map: dict  alias -> [sql conditions] for JOIN ON clauses
        first_conds: list of sql conditions for the first table (WHERE)
    """
    if not quad_tables:
        return quad_tables, {}, []
    if len(quad_tables) == 1:
        conds = [sql for _, sql in tagged_constraints]
        return quad_tables, {}, conds

    all_aliases = {t.alias for t in quad_tables}
    alias_to_table = {t.alias: t for t in quad_tables}

    # Parse each constraint: (owner_alias, sql, other_aliases_referenced)
    parsed = []
    for owner, sql in tagged_constraints:
        refs = {a for a in all_aliases if a != owner and f"{a}." in sql}
        parsed.append((owner, sql, refs))

    # --- Greedy placement ---
    placed_order = [quad_tables[0]]
    placed_set = {quad_tables[0].alias}
    remaining = [t.alias for t in quad_tables[1:]]

    while remaining:
        best_alias = None
        best_score = -1

        for alias in remaining:
            score = 0
            for owner, sql, refs in parsed:
                involved = {owner} | refs
                if alias in involved:
                    others = involved - {alias}
                    if others and others <= placed_set:
                        score += 1
            if score > best_score:
                best_score = score
                best_alias = alias

        if best_alias is None:
            best_alias = remaining[0]

        remaining.remove(best_alias)
        placed_order.append(alias_to_table[best_alias])
        placed_set.add(best_alias)

    # --- Assign constraints to ON clauses ---
    placement_rank = {t.alias: i for i, t in enumerate(placed_order)}
    on_map: Dict[str, List[str]] = {}

    for owner, sql, refs in parsed:
        involved = ({owner} | refs) & all_aliases
        latest = max(involved, key=lambda a: placement_rank[a])
        on_map.setdefault(latest, []).append(sql)

    first_alias = placed_order[0].alias
    first_conds = on_map.pop(first_alias, [])

    return placed_order, on_map, first_conds


# ===========================================================================
# Text filter → quad constraint pushdown
# ===========================================================================

def _extract_text_filters(plan: RelationPlan, term_table: str):
    """Convert text filters on SPARQL variables to quad-level UUID constraints.

    Detects patterns like CONTAINS(?var, "literal") and converts them to:
        q.object_uuid IN (SELECT term_uuid FROM term WHERE term_text ILIKE '%literal%')

    This pushes text matching to the term table FIRST, then uses the resulting
    UUIDs to drive quad-level joins — leveraging the GIN trigram index.

    Returns:
        extra_constraints: list of (alias, sql) for tagged_constraints
        remaining_filters: filter_exprs list with consumed filters removed
    """
    if not plan.filter_exprs:
        return [], plan.filter_exprs

    quad_aliases = {t.alias for t in plan.tables if t.kind == "quad"}
    extra = []
    remaining = []

    for expr in plan.filter_exprs:
        constraint = _try_text_filter_to_constraint(expr, plan, term_table, quad_aliases)
        if constraint:
            extra.append(constraint)
        else:
            remaining.append(expr)

    return extra, remaining or None


def _try_text_filter_to_constraint(expr, plan, term_table, quad_aliases):
    """Try to convert a single text filter to a quad-level constraint.

    Returns (alias, sql) tuple for tagged_constraints, or None.
    """
    if not isinstance(expr, ExprFunction):
        return None

    name = (expr.name or "").lower()
    args = expr.args or []

    var_name = None
    literal_value = None
    flags_arg = None

    if name in ("contains", "strstarts", "strends") and len(args) == 2:
        if isinstance(args[0], ExprVar) and isinstance(args[1], ExprValue):
            if isinstance(args[1].node, LiteralNode):
                var_name = args[0].var
                literal_value = args[1].node.value
    elif name == "regex" and len(args) >= 2:
        if isinstance(args[0], ExprVar) and isinstance(args[1], ExprValue):
            if isinstance(args[1].node, LiteralNode):
                var_name = args[0].var
                literal_value = args[1].node.value
                if len(args) >= 3:
                    flags_arg = args[2]
    elif name == "eq" and len(args) == 2:
        for i, j in ((0, 1), (1, 0)):
            if isinstance(args[i], ExprVar) and isinstance(args[j], ExprValue):
                if isinstance(args[j].node, LiteralNode):
                    var_name = args[i].var
                    literal_value = args[j].node.value
                    break

    if var_name is None or literal_value is None:
        return None

    # Find the variable's quad column binding
    slot = plan.var_slots.get(var_name)
    if not slot or not slot.uuid_col:
        return None

    # uuid_col is like "q1.object_uuid" — extract alias
    parts = slot.uuid_col.split(".")
    if len(parts) != 2:
        return None
    alias = parts[0]

    # Must be a quad table alias (not a term table or subquery alias)
    if alias not in quad_aliases:
        return None

    # Build the term table condition
    escaped = _esc(literal_value)
    if name == "contains":
        term_cond = f"term_text ILIKE '%{escaped}%'"
    elif name == "strstarts":
        term_cond = f"term_text LIKE '{escaped}%'"
    elif name == "strends":
        term_cond = f"term_text LIKE '%{escaped}'"
    elif name == "regex":
        case_insensitive = False
        if flags_arg and isinstance(flags_arg, ExprValue):
            if isinstance(flags_arg.node, LiteralNode) and "i" in flags_arg.node.value:
                case_insensitive = True
        op = "~*" if case_insensitive else "~"
        term_cond = f"term_text {op} '{escaped}'"
    elif name == "eq":
        term_cond = f"term_text = '{escaped}'"
    else:
        return None

    constraint_sql = (
        f"{slot.uuid_col} IN "
        f"(SELECT term_uuid FROM {term_table} WHERE {term_cond})"
    )
    logger.debug("Text filter pushdown: %s(%s, '%s') → %s",
                 name, var_name, literal_value, constraint_sql[:80])
    return (alias, constraint_sql)


# ===========================================================================
# Public entry point
# ===========================================================================

def emit(plan: RelationPlan, space_id: str) -> str:
    """Emit a resolved plan as a PostgreSQL SQL string."""
    if plan.kind == "null":
        return "SELECT 1 WHERE FALSE"
    if plan.kind == "table":
        return _emit_table(plan)

    # Compute which vars are actually referenced by modifiers
    needed = _needed_vars(plan)

    # ---- Optimized BGP path: inner subquery on quad, outer JOINs term ----
    if plan.kind == "bgp" and plan.var_slots:
        has_modifiers = (
            plan.filter_exprs or plan.having_exprs or plan.extend_exprs or plan.group_by
            or plan.aggregates or plan.select_vars is not None
            or plan.distinct or plan.order_by or plan.limit >= 0 or plan.offset > 0
        )
        if has_modifiers:
            return _emit_bgp_optimized(plan, space_id, needed)

    # ---- Non-BGP plans ----
    if plan.kind == "path":
        raw_path_sql = _emit_path(plan, space_id, needed)
        # Wrap in a subquery so column aliases (s, s__uuid, etc.)
        # become real columns that sqlglot can project/filter/limit
        base_sql = f"SELECT * FROM ({raw_path_sql}) AS _path"
        for var, slot in plan.var_slots.items():
            slot.text_col = var
            slot.uuid_col = f"{var}__uuid"
            slot.type_col = f"{var}__type"
    elif plan.kind == "bgp":
        base_sql = _emit_bgp(plan, space_id, needed)
    elif plan.kind in ("join", "left_join"):
        base_sql = _emit_join(plan, space_id)
    elif plan.kind == "union":
        base_sql = _emit_union(plan, space_id)
    elif plan.kind == "minus":
        base_sql = _emit_minus(plan, space_id)
    elif plan.children:
        base_sql = emit(plan.children[0], space_id)
    else:
        base_sql = _emit_bgp(plan, space_id, needed)

    # Check if any modifiers need to be applied to non-BGP plans
    has_modifiers = (
        plan.filter_exprs or plan.having_exprs or plan.extend_exprs or plan.group_by
        or plan.aggregates or plan.select_vars is not None
        or plan.distinct or plan.order_by or plan.limit >= 0 or plan.offset > 0
    )
    if not has_modifiers:
        return base_sql

    # Apply modifiers to non-BGP base SQL via sqlglot
    parsed = sqlglot.parse_one(base_sql, dialect=PG_DIALECT)

    if plan.filter_exprs:
        from .jena_types import ExprExists as _EE
        for expr in plan.filter_exprs:
            if isinstance(expr, _EE):
                exists_sql = _emit_exists_subquery(expr, plan, space_id)
                if exists_sql:
                    parsed = parsed.where(exists_sql, dialect=PG_DIALECT)
            else:
                sql_expr = _expr_to_sql_str(expr, plan)
                if sql_expr:
                    parsed = parsed.where(sql_expr, dialect=PG_DIALECT)

    if plan.group_by:
        for gv in plan.group_by:
            parsed = parsed.group_by(gv, dialect=PG_DIALECT)

    # HAVING for non-BGP path
    if plan.having_exprs and plan.aggregates:
        non_bgp_agg_map = {}
        for var, expr in plan.aggregates.items():
            sql_expr = _expr_to_sql_str(expr, plan)
            if sql_expr:
                non_bgp_agg_map[var] = sql_expr
        for expr in plan.having_exprs:
            sql_expr = _having_expr_to_sql(expr, plan, non_bgp_agg_map)
            if sql_expr:
                parsed = parsed.having(sql_expr, dialect=PG_DIALECT)

    agg_sql_map: Dict[str, str] = {}
    if plan.aggregates:
        for var, expr in plan.aggregates.items():
            sql_expr = _expr_to_sql_str(expr, plan)
            if sql_expr:
                agg_sql_map[var] = sql_expr

    extend_sql_map: Dict[str, str] = {}
    if plan.extend_exprs:
        for var, expr in plan.extend_exprs.items():
            if isinstance(expr, ExprVar) and expr.var in agg_sql_map:
                extend_sql_map[var] = agg_sql_map[expr.var]
            else:
                sql_expr = _expr_to_sql_str(expr, plan)
                if sql_expr:
                    extend_sql_map[var] = sql_expr

    if plan.select_vars is not None:
        proj_cols = []
        for var in plan.select_vars:
            if var in extend_sql_map:
                proj_cols.append(f"{extend_sql_map[var]} AS {var}")
            elif var in agg_sql_map:
                proj_cols.append(f"{agg_sql_map[var]} AS {var}")
            else:
                slot = plan.var_slots.get(var)
                if slot and slot.text_col:
                    proj_cols.append(f"{slot.text_col} AS {var}")
                else:
                    proj_cols.append(f"NULL AS {var}")
        if proj_cols:
            new_exprs = [sqlglot.parse_one(p, dialect=PG_DIALECT) for p in proj_cols]
            parsed = parsed.select(*new_exprs, append=False)
    else:
        for var, sql_expr in agg_sql_map.items():
            parsed = parsed.select(f"{sql_expr} AS \"{var}\"", append=True)
        for var, sql_expr in extend_sql_map.items():
            parsed = parsed.select(f"{sql_expr} AS {var}", append=True)

    if plan.distinct:
        parsed = parsed.distinct()

    if plan.order_by:
        for key, direction in plan.order_by:
            if isinstance(key, str):
                col = key
                slot = plan.var_slots.get(key)
                if slot and slot.text_col:
                    col = slot.text_col
            else:
                col = _expr_to_sql_str(key, plan)
            order_expr = f"{col} DESC" if direction == "DESC" else col
            parsed = parsed.order_by(order_expr, dialect=PG_DIALECT)

    if plan.limit >= 0:
        parsed = parsed.limit(plan.limit, dialect=PG_DIALECT)
    if plan.offset > 0:
        parsed = parsed.offset(plan.offset, dialect=PG_DIALECT)

    return parsed.sql(dialect=PG_DIALECT)


# ===========================================================================
# Optimized BGP emitter
# ===========================================================================

def _emit_bgp_optimized(plan: RelationPlan, space_id: str,
                         needed_vars: Optional[set] = None) -> str:
    """Optimized BGP emission: inner subquery on quad table, outer JOINs term.

    Strategy:
      Inner: quad tables + WHERE constraints + [DISTINCT on UUIDs] +
             [ORDER BY term JOIN] + [LIMIT/OFFSET]
      Outer: JOIN term tables for text resolution of projected vars.

    This ensures LIMIT/DISTINCT/ORDER BY operate on the quad table (fast)
    and term JOINs happen only on the small result set.
    """
    term_table = f"{space_id}_term"

    # Text filter pushdown: convert CONTAINS/REGEX/etc. to quad-level constraints
    extra_constraints, remaining_filters = _extract_text_filters(plan, term_table)
    if extra_constraints:
        if not plan.tagged_constraints:
            plan.tagged_constraints = []
        plan.tagged_constraints.extend(extra_constraints)
        plan.filter_exprs = remaining_filters

    # Determine projected vars and order vars
    proj_vars = set(plan.select_vars) if plan.select_vars else set(plan.var_slots.keys())
    if needed_vars:
        proj_vars = proj_vars & needed_vars
    order_vars = set()
    if plan.order_by:
        for key, _ in plan.order_by:
            if isinstance(key, str):
                order_vars.add(key)
            else:
                order_vars.update(_vars_in_expr(key))
    filter_vars = set()
    if plan.filter_exprs:
        for expr in plan.filter_exprs:
            filter_vars.update(_vars_in_expr(expr))

    # Vars that need term JOIN in the INNER query (for ORDER BY / FILTER on text)
    inner_text_vars = order_vars | filter_vars

    # Collect vars referenced by extend expressions — they also need text in inner
    extend_ref_vars = set()
    if plan.extend_exprs:
        for var, expr in plan.extend_exprs.items():
            extend_ref_vars.update(_vars_in_expr(expr))
    # Only add actual BGP vars (not aggregate internal vars like '.0')
    extend_ref_vars = extend_ref_vars & set(plan.var_slots.keys())
    inner_text_vars = inner_text_vars | extend_ref_vars

    # Build aggregate/extend maps for COUNT etc.
    # Use UUID columns (always available in inner query) for aggregate expressions
    agg_sql_map: Dict[str, str] = {}
    if plan.aggregates:
        for var, expr in plan.aggregates.items():
            sql_expr = _agg_expr_to_inner_sql(expr, plan)
            if sql_expr:
                agg_sql_map[var] = sql_expr
    extend_sql_map: Dict[str, str] = {}
    if plan.extend_exprs:
        for var, expr in plan.extend_exprs.items():
            if isinstance(expr, ExprVar) and expr.var in agg_sql_map:
                extend_sql_map[var] = agg_sql_map[expr.var]
            # Non-aggregate extends with var refs: defer to outer resolution below

    # For COUNT/aggregate-only queries, no inner/outer split needed
    if plan.aggregates and not proj_vars - set(extend_sql_map.keys()) - set(agg_sql_map.keys()):
        return _emit_bgp_aggregate(plan, space_id, agg_sql_map, extend_sql_map)

    # --- Build INNER subquery (quad table + constraints only) ---
    quad_tables = [t for t in plan.tables if t.kind == "quad"]
    all_needed = proj_vars | order_vars | filter_vars
    sub_alias = "sub"

    inner_cols = []
    inner_term_joins = []

    # Include aggregate expressions in inner query
    inner_agg_aliases = {}  # agg_var -> outer ref via sub alias
    for agg_var, agg_sql in agg_sql_map.items():
        # Sanitize: Jena uses names like '.0' which are invalid SQL identifiers
        safe_name = agg_var.replace(".", "_").replace("-", "_")
        alias = f"__agg_{safe_name}"
        inner_cols.append(f"{agg_sql} AS {alias}")
        inner_agg_aliases[agg_var] = f"{sub_alias}.{alias}"
    # Map extend vars that reference aggregates to inner aliases
    inner_extend_aliases = {}
    if plan.extend_exprs:
        for ext_var, ext_sql in extend_sql_map.items():
            ext_expr = plan.extend_exprs.get(ext_var)
            if isinstance(ext_expr, ExprVar) and ext_expr.var in inner_agg_aliases:
                inner_extend_aliases[ext_var] = inner_agg_aliases[ext_expr.var]
    for var, slot in plan.var_slots.items():
        if var not in all_needed:
            continue
        if slot.positions:
            q_alias, uuid_col_name = slot.positions[0]
            inner_cols.append(f"{q_alias}.{uuid_col_name} AS {var}__uuid")

        # Include term JOIN in inner only if needed for ORDER BY or FILTER
        # Use pre-filtered subquery to give PG accurate cardinality → hash join
        if var in inner_text_vars and slot.term_ref_id:
            tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
            if tt:
                # Pre-filter term table to only UUIDs present in the quad column
                q_alias, uuid_col_name = slot.positions[0]
                quad_tbl = next((t for t in plan.tables if t.alias == q_alias), None)
                quad_tbl_name = quad_tbl.table_name if quad_tbl else f"{space_id}_rdf_quad"
                inner_term_joins.append(
                    f"JOIN (SELECT term_uuid, term_text, term_type, lang FROM {tt.table_name} "
                    f"WHERE term_uuid IN ("
                    f"SELECT DISTINCT {uuid_col_name} FROM {quad_tbl_name}"
                    f")) AS {tt.alias} "
                    f"ON {tt.join_col} = {tt.alias}.term_uuid"
                )
                inner_cols.append(f"{tt.alias}.term_text AS {var}__text")
                inner_cols.append(f"{tt.alias}.term_type AS {var}__type")
                inner_cols.append(f"{tt.alias}.lang AS {var}__lang")

    if not inner_cols:
        inner_cols = ["1"]

    inner_parts = []
    if plan.distinct:
        inner_parts.append(f"SELECT DISTINCT {', '.join(inner_cols)}")
    else:
        inner_parts.append(f"SELECT {', '.join(inner_cols)}")

    # Partition constraints into per-table ON clauses vs residual WHERE
    # using tagged_constraints from the collect phase.
    # Reorder tables so every JOIN references an already-placed table.
    if quad_tables and plan.tagged_constraints:
        ordered, on_map, first_conds = _reorder_joins(quad_tables, plan.tagged_constraints)

        inner_parts.append(f"FROM {ordered[0].table_name} AS {ordered[0].alias}")
        for qt in ordered[1:]:
            conds = on_map.get(qt.alias)
            if conds:
                inner_parts.append(
                    f"JOIN {qt.table_name} AS {qt.alias} ON "
                    + " AND ".join(conds)
                )
            else:
                inner_parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
    elif quad_tables:
        inner_parts.append(f"FROM {quad_tables[0].table_name} AS {quad_tables[0].alias}")
        for qt in quad_tables[1:]:
            inner_parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
        first_conds = list(plan.constraints) if plan.constraints else []
    else:
        first_conds = list(plan.constraints) if plan.constraints else []

    inner_parts.extend(inner_term_joins)

    if first_conds:
        inner_parts.append("WHERE " + " AND ".join(first_conds))

    # FILTER conditions that reference text columns
    if plan.filter_exprs:
        from .jena_types import ExprExists as _EE
        filter_parts = []
        for expr in plan.filter_exprs:
            if isinstance(expr, _EE):
                exists_sql = _emit_exists_subquery(expr, plan, space_id)
                if exists_sql:
                    filter_parts.append(exists_sql)
            else:
                sql_expr = _expr_to_sql_str_inner(expr, plan)
                if sql_expr:
                    filter_parts.append(sql_expr)
        if filter_parts:
            if first_conds:
                inner_parts.append("AND " + " AND ".join(filter_parts))
            else:
                inner_parts.append("WHERE " + " AND ".join(filter_parts))

    # GROUP BY
    if plan.group_by:
        gb_cols = []
        for gv in plan.group_by:
            slot = plan.var_slots.get(gv)
            if slot and slot.positions:
                q_alias, uuid_col_name = slot.positions[0]
                gb_cols.append(f"{q_alias}.{uuid_col_name}")
                # If this var has inner term columns, add them to GROUP BY too
                if gv in inner_text_vars and slot.term_ref_id:
                    tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
                    if tt:
                        gb_cols.append(f"{tt.alias}.term_text")
                        gb_cols.append(f"{tt.alias}.term_type")
            else:
                gb_cols.append(gv)
        inner_parts.append("GROUP BY " + ", ".join(gb_cols))

    # HAVING (aggregate filter conditions)
    if plan.having_exprs:
        having_parts = []
        for expr in plan.having_exprs:
            sql_expr = _having_expr_to_sql(expr, plan, agg_sql_map)
            if sql_expr:
                having_parts.append(sql_expr)
        if having_parts:
            inner_parts.append("HAVING " + " AND ".join(having_parts))

    # ORDER BY
    if plan.order_by:
        ob_parts = []
        for key, direction in plan.order_by:
            if isinstance(key, str):
                # Check aggregate / extend-to-aggregate aliases first
                if key in agg_sql_map:
                    col = agg_sql_map[key]
                elif key in extend_sql_map:
                    col = extend_sql_map[key]
                elif key in inner_text_vars:
                    slot = plan.var_slots.get(key)
                    if slot and slot.term_ref_id:
                        tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
                        if tt:
                            col = f"{tt.alias}.term_text"
                        else:
                            col = f"{key}__text"
                    else:
                        col = f"{key}__text"
                else:
                    col = f"{key}__uuid"
            else:
                # Arbitrary expression — resolve using inner term aliases
                col = _expr_to_sql_str_inner(key, plan)
            suffix = " DESC" if direction == "DESC" else ""
            ob_parts.append(f"{col}{suffix}")
        inner_parts.append("ORDER BY " + ", ".join(ob_parts))

    # LIMIT / OFFSET
    if plan.limit >= 0:
        inner_parts.append(f"LIMIT {plan.limit}")
    if plan.offset > 0:
        inner_parts.append(f"OFFSET {plan.offset}")

    inner_sql = "\n".join(inner_parts)

    # --- Resolve deferred extend expressions using outer column references ---
    if plan.extend_exprs:
        # Build mapping: var_name -> outer SQL column reference for text/type/lang/uuid
        outer_text_refs: Dict[str, str] = {}
        outer_type_refs: Dict[str, str] = {}
        outer_lang_refs: Dict[str, str] = {}
        outer_uuid_refs: Dict[str, str] = {}
        for var in plan.var_slots:
            if var in inner_text_vars:
                outer_text_refs[var] = f"{sub_alias}.{var}__text"
                outer_type_refs[var] = f"{sub_alias}.{var}__type"
                outer_lang_refs[var] = f"{sub_alias}.{var}__lang"
                outer_uuid_refs[var] = f"{sub_alias}.{var}__uuid"
            else:
                outer_text_refs[var] = f"t_{var}.term_text"
                outer_type_refs[var] = f"t_{var}.term_type"
                outer_lang_refs[var] = f"t_{var}.lang"
                outer_uuid_refs[var] = f"{sub_alias}.{var}__uuid"
        for ext_var, ext_expr in plan.extend_exprs.items():
            if ext_var not in extend_sql_map:
                sql_expr = _resolve_extend_for_outer(
                    ext_expr, plan, outer_text_refs,
                    outer_lang_refs=outer_lang_refs,
                    outer_type_refs=outer_type_refs,
                    outer_uuid_refs=outer_uuid_refs,
                )
                if sql_expr:
                    extend_sql_map[ext_var] = sql_expr

    # --- Build OUTER query: JOIN term for text resolution ---
    outer_cols = []
    outer_joins = []

    select_list = plan.select_vars or sorted(proj_vars)
    for var in select_list:
        if var in inner_extend_aliases:
            outer_cols.append(f"{inner_extend_aliases[var]} AS {var}")
            continue
        if var in inner_agg_aliases:
            outer_cols.append(f"{inner_agg_aliases[var]} AS {var}")
            continue
        if var in extend_sql_map:
            outer_cols.append(f"{extend_sql_map[var]} AS {var}")
            continue
        if var in agg_sql_map:
            outer_cols.append(f"{agg_sql_map[var]} AS {var}")
            continue
        slot = plan.var_slots.get(var)
        if not slot:
            outer_cols.append(f"NULL AS {var}")
            outer_cols.append(f"NULL AS {var}__uuid")
            outer_cols.append(f"NULL AS {var}__type")
            continue

        if var in inner_text_vars:
            # Text already resolved in inner query
            outer_cols.append(f"{sub_alias}.{var}__text AS {var}")
            outer_cols.append(f"{sub_alias}.{var}__type AS {var}__type")
        else:
            # Need outer term JOIN for text + type
            t_alias = f"t_{var}"
            outer_joins.append(
                f"JOIN {term_table} AS {t_alias} "
                f"ON {sub_alias}.{var}__uuid = {t_alias}.term_uuid"
            )
            outer_cols.append(f"{t_alias}.term_text AS {var}")
            outer_cols.append(f"{t_alias}.term_type AS {var}__type")
        # Always include UUID from inner subquery
        outer_cols.append(f"{sub_alias}.{var}__uuid AS {var}__uuid")

    if not outer_cols:
        outer_cols = ["1"]

    outer_parts = [f"SELECT {', '.join(outer_cols)}"]
    outer_parts.append(f"FROM ({inner_sql}) AS {sub_alias}")
    outer_parts.extend(outer_joins)

    return "\n".join(outer_parts)


# ===========================================================================
# Aggregate-only BGP emitter
# ===========================================================================

def _emit_bgp_aggregate(plan: RelationPlan, space_id: str,
                         agg_sql_map: Dict[str, str],
                         extend_sql_map: Dict[str, str]) -> str:
    """Emit aggregate-only queries like COUNT(*) directly on the quad table."""
    term_table = f"{space_id}_term"

    # Text filter pushdown
    extra_constraints, remaining_filters = _extract_text_filters(plan, term_table)
    if extra_constraints:
        if not plan.tagged_constraints:
            plan.tagged_constraints = []
        plan.tagged_constraints.extend(extra_constraints)
        plan.filter_exprs = remaining_filters

    quad_tables = [t for t in plan.tables if t.kind == "quad"]

    proj_cols = []
    for var in (plan.select_vars or []):
        if var in extend_sql_map:
            proj_cols.append(f"{extend_sql_map[var]} AS {var}")
        elif var in agg_sql_map:
            proj_cols.append(f"{agg_sql_map[var]} AS {var}")
        else:
            proj_cols.append(f"NULL AS {var}")

    if not proj_cols:
        proj_cols = ["1"]

    parts = [f"SELECT {', '.join(proj_cols)}"]
    # Partition constraints into per-table ON clauses vs WHERE
    # Reorder tables so every JOIN references an already-placed table.
    if quad_tables and plan.tagged_constraints:
        ordered, on_map, where_parts = _reorder_joins(quad_tables, plan.tagged_constraints)

        parts.append(f"FROM {ordered[0].table_name} AS {ordered[0].alias}")
        for qt in ordered[1:]:
            conds = on_map.get(qt.alias)
            if conds:
                parts.append(
                    f"JOIN {qt.table_name} AS {qt.alias} ON "
                    + " AND ".join(conds)
                )
            else:
                parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
    elif quad_tables:
        parts.append(f"FROM {quad_tables[0].table_name} AS {quad_tables[0].alias}")
        for qt in quad_tables[1:]:
            parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
        where_parts = list(plan.constraints) if plan.constraints else []
    else:
        where_parts = list(plan.constraints) if plan.constraints else []

    if plan.filter_exprs:
        from .jena_types import ExprExists as _EE
        for expr in plan.filter_exprs:
            if isinstance(expr, _EE):
                exists_sql = _emit_exists_subquery(expr, plan, space_id)
                if exists_sql:
                    where_parts.append(exists_sql)
            else:
                sql_expr = _expr_to_sql_str_inner(expr, plan)
                if sql_expr:
                    where_parts.append(sql_expr)

    if where_parts:
        parts.append("WHERE " + " AND ".join(where_parts))

    if plan.group_by:
        parts.append("GROUP BY " + ", ".join(plan.group_by))

    return "\n".join(parts)


# ===========================================================================
# Flat BGP emitter (no modifiers)
# ===========================================================================

def _emit_bgp(plan: RelationPlan, space_id: str,
              needed_vars: Optional[set] = None) -> str:
    """Emit a flat BGP as SQL.

    Args:
        needed_vars: If provided, only include term JOINs and SELECT columns
            for variables in this set. This avoids expensive JOINs for variables
            that aren't projected, filtered, or ordered.
    """
    if not plan.tables:
        return "SELECT 1"

    term_table = f"{space_id}_term"

    # Text filter pushdown
    extra_constraints, remaining_filters = _extract_text_filters(plan, term_table)
    if extra_constraints:
        if not plan.tagged_constraints:
            plan.tagged_constraints = []
        plan.tagged_constraints.extend(extra_constraints)
        plan.filter_exprs = remaining_filters

    # Determine which var_slots need term resolution
    if needed_vars is not None:
        active_vars = {v: s for v, s in plan.var_slots.items() if v in needed_vars}
        # Collect term table ref_ids that we can skip
        skip_term_refs = set()
        for var, slot in plan.var_slots.items():
            if var not in needed_vars and slot.term_ref_id:
                skip_term_refs.add(slot.term_ref_id)
    else:
        active_vars = plan.var_slots
        skip_term_refs = set()

    # Build named columns for active var_slots
    select_cols = []
    for var, slot in active_vars.items():
        if slot.text_col:
            select_cols.append(f"{slot.text_col} AS {var}")
        if slot.uuid_col:
            select_cols.append(f"{slot.uuid_col} AS {var}__uuid")
        if slot.type_col:
            select_cols.append(f"{slot.type_col} AS {var}__type")

    if not select_cols:
        select_cols = ["1"]

    # FROM: first quad table
    quad_tables = [t for t in plan.tables if t.kind == "quad"]
    term_tables = [t for t in plan.tables if t.kind == "term"
                   and t.ref_id not in skip_term_refs]

    parts = [f"SELECT {', '.join(select_cols)}"]

    # Partition constraints into per-table ON clauses vs WHERE
    # Reorder tables so every JOIN references an already-placed table.
    if quad_tables and plan.tagged_constraints:
        ordered, on_map, first_conds = _reorder_joins(quad_tables, plan.tagged_constraints)

        parts.append(f"FROM {ordered[0].table_name} AS {ordered[0].alias}")
        for qt in ordered[1:]:
            conds = on_map.get(qt.alias)
            if conds:
                parts.append(
                    f"JOIN {qt.table_name} AS {qt.alias} ON "
                    + " AND ".join(conds)
                )
            else:
                parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
    elif quad_tables:
        parts.append(f"FROM {quad_tables[0].table_name} AS {quad_tables[0].alias}")
        for qt in quad_tables[1:]:
            parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
        first_conds = list(plan.constraints) if plan.constraints else []
    else:
        first_conds = list(plan.constraints) if plan.constraints else []
        if term_tables:
            parts.append(f"FROM {term_tables[0].table_name} AS {term_tables[0].alias}")
            term_tables = term_tables[1:]

    for tt in term_tables:
        parts.append(
            f"JOIN {tt.table_name} AS {tt.alias} ON {tt.join_col} = {tt.alias}.term_uuid"
        )

    if first_conds:
        parts.append("WHERE " + " AND ".join(first_conds))

    return "\n".join(parts)


# ===========================================================================
# JOIN / LEFT JOIN emitter
# ===========================================================================

def _emit_join(plan: RelationPlan, space_id: str) -> str:
    """Emit JOIN / LEFT JOIN."""
    meta = plan._join_meta  # type: ignore[attr-defined]
    l_alias = meta["l_alias"]
    r_alias = meta["r_alias"]
    shared = meta["shared"]
    left_vars = meta["left_vars"]
    right_vars = meta["right_vars"]

    # Filter pushdown: expressions referencing only left-side variables
    # can be pushed into the left child so they execute inside its subquery
    # instead of on the outer join result (dramatically faster).
    if plan.filter_exprs:
        pushed = []
        kept = []
        for expr in plan.filter_exprs:
            expr_vars = _vars_in_expr(expr)
            if expr_vars and expr_vars <= left_vars:
                pushed.append(expr)
            else:
                kept.append(expr)
        if pushed:
            left_child = plan.children[0]
            if left_child.filter_exprs is None:
                left_child.filter_exprs = []
            left_child.filter_exprs.extend(pushed)
            plan.filter_exprs = kept or None

    left_sql = emit(plan.children[0], space_id)
    right_sql = emit(plan.children[1], space_id)

    # CTE MATERIALIZED: when the left child is a bounded subquery (has LIMIT),
    # hoist it to a CTE so PG materializes the small result first and uses it
    # to drive a nested loop into the right side — dramatically faster.
    left_child = plan.children[0]
    use_cte = (
        plan.kind == "join"
        and getattr(left_child, 'limit', -1) >= 0
    )

    # ON clause: shared variables joined by UUID
    if shared:
        on_parts = [f"{l_alias}.{v}__uuid = {r_alias}.{v}__uuid" for v in shared]
        on_clause = " AND ".join(on_parts)
    else:
        on_clause = "TRUE"

    # OpLeftJoin's own expressions go in the ON clause (OPTIONAL semantics).
    # Outer FILTER expressions stay in plan.filter_exprs for WHERE clause.
    if plan.left_join_exprs and plan.kind == "left_join":
        for expr in plan.left_join_exprs:
            sql_expr = _expr_to_sql_str(expr, plan)
            if sql_expr:
                on_clause += f" AND {sql_expr}"
        plan.left_join_exprs = None  # consumed

    # SELECT columns from both sides
    all_vars = left_vars | right_vars
    select_cols = []
    for v in sorted(all_vars):
        src = l_alias if v in left_vars else r_alias
        select_cols.append(f"{src}.{v} AS {v}")
        select_cols.append(f"{src}.{v}__uuid AS {v}__uuid")
        select_cols.append(f"{src}.{v}__type AS {v}__type")

    join_type = "LEFT JOIN" if plan.kind == "left_join" else "JOIN"

    if use_cte:
        cte_name = f"_cte_{l_alias}"
        sql = (
            f"WITH {cte_name} AS MATERIALIZED (\n{left_sql}\n)\n"
            f"SELECT {', '.join(select_cols)}\n"
            f"FROM {cte_name} AS {l_alias}\n"
            f"{join_type} ({right_sql}) AS {r_alias}\n"
            f"ON {on_clause}"
        )
    else:
        sql = (
            f"SELECT {', '.join(select_cols)}\n"
            f"FROM ({left_sql}) AS {l_alias}\n"
            f"{join_type} ({right_sql}) AS {r_alias}\n"
            f"ON {on_clause}"
        )
    return sql


# ===========================================================================
# UNION emitter
# ===========================================================================

def _emit_union(plan: RelationPlan, space_id: str) -> str:
    """Emit UNION ALL."""
    meta = plan._union_meta  # type: ignore[attr-defined]
    u_alias = meta["u_alias"]
    all_vars = meta["all_vars"]
    left_vars = meta["left_vars"]
    right_vars = meta["right_vars"]

    left_sql = emit(plan.children[0], space_id)
    right_sql = emit(plan.children[1], space_id)

    # Pad each side with matching columns
    def _pad(child_sql, child_vars):
        cols = []
        for v in all_vars:
            if v in child_vars:
                cols.append(f"{v}")
                cols.append(f"{v}__uuid")
                cols.append(f"{v}__type")
            else:
                cols.append(f"NULL AS {v}")
                cols.append(f"NULL AS {v}__uuid")
                cols.append(f"NULL AS {v}__type")
        return f"SELECT {', '.join(cols)} FROM ({child_sql}) AS _pad"

    left_padded = _pad(left_sql, left_vars)
    right_padded = _pad(right_sql, right_vars)

    union_sql = f"({left_padded}) UNION ALL ({right_padded})"
    return f"SELECT * FROM ({union_sql}) AS {u_alias}"


# ===========================================================================
# MINUS (EXCEPT) emitter
# ===========================================================================

def _emit_minus(plan: RelationPlan, space_id: str) -> str:
    """Emit EXCEPT."""
    meta = plan._minus_meta  # type: ignore[attr-defined]
    m_alias = meta["m_alias"]
    all_vars = meta["all_vars"]
    left_vars = meta["left_vars"]
    right_vars = meta["right_vars"]

    left_sql = emit(plan.children[0], space_id)
    right_sql = emit(plan.children[1], space_id)

    def _pad(child_sql, child_vars):
        cols = []
        for v in all_vars:
            if v in child_vars:
                cols.append(f"{v}")
            else:
                cols.append(f"NULL AS {v}")
        return f"SELECT {', '.join(cols)} FROM ({child_sql}) AS _pad"

    left_padded = _pad(left_sql, left_vars)
    right_padded = _pad(right_sql, right_vars)

    except_sql = f"({left_padded}) EXCEPT ({right_padded})"
    return f"SELECT * FROM ({except_sql}) AS {m_alias}"


# ===========================================================================
# TABLE (VALUES) emitter
# ===========================================================================

def _emit_table(plan: RelationPlan) -> str:
    """Emit VALUES as UNION ALL of SELECT constants."""
    if not plan.values_rows:
        return "SELECT 1 WHERE FALSE"
    parts = []
    for row in plan.values_rows:
        cols = []
        for var in (plan.values_vars or []):
            val = row.get(var)
            if val is None:
                cols.append(f"NULL AS {var}")
            elif isinstance(val, URINode):
                cols.append(f"'{_esc(val.value)}' AS {var}")
            elif isinstance(val, LiteralNode):
                cols.append(f"'{_esc(val.value)}' AS {var}")
            else:
                cols.append(f"NULL AS {var}")
        parts.append(f"SELECT {', '.join(cols)}")
    return " UNION ALL ".join(parts)


# ===========================================================================
# EXISTS / NOT EXISTS subquery helper
# ===========================================================================

def _emit_exists_subquery(expr_exists, outer_plan: RelationPlan,
                           space_id: str) -> str:
    """Emit a correlated EXISTS or NOT EXISTS subquery.

    Runs the inner graph pattern through collect/resolve/emit, then
    adds correlation conditions for variables shared with the outer plan.
    """
    from .jena_sql_collect import collect as _collect
    from .jena_sql_resolve import resolve as _resolve
    from .jena_sql_ir import AliasGenerator
    from .jena_sql_helpers import CTE_CONST_ALIAS

    term_table = f"{space_id}_term"

    # Build the inner plan with a prefixed alias generator to avoid conflicts
    inner_aliases = AliasGenerator(alias_prefix="ex_")
    inner_plan = _collect(expr_exists.graph_pattern, space_id, inner_aliases)
    inner_resolved = _resolve(inner_plan, space_id, inner_aliases)

    # Find shared variables between outer and inner plans
    outer_vars = set(outer_plan.var_slots.keys())
    inner_vars = set(inner_resolved.var_slots.keys())
    shared = outer_vars & inner_vars

    # Emit inner query as a flat SQL string
    inner_sql = emit(inner_resolved, space_id)

    # Replace _const CTE references with direct term table lookups,
    # since the inner query's constants aren't in the outer CTE.
    inner_sql = inner_sql.replace(
        f"FROM {CTE_CONST_ALIAS} WHERE",
        f"FROM {term_table} WHERE"
    )

    # Build correlation: shared vars must have matching UUIDs
    corr_parts = []
    for var in sorted(shared):
        o_slot = outer_plan.var_slots.get(var)
        i_slot = inner_resolved.var_slots.get(var)
        if o_slot and o_slot.positions and i_slot and i_slot.positions:
            o_alias, o_col = o_slot.positions[0]
            corr_parts.append(f"{o_alias}.{o_col} = _ex.{var}__uuid")

    if corr_parts:
        corr_where = " AND ".join(corr_parts)
        subquery = f"SELECT 1 FROM ({inner_sql}) AS _ex WHERE {corr_where}"
    else:
        subquery = f"SELECT 1 FROM ({inner_sql}) AS _ex"

    prefix = "NOT EXISTS" if expr_exists.negated else "EXISTS"
    return f"{prefix} ({subquery})"


# ===========================================================================
# Extend expression outer-resolution helper
# ===========================================================================

def _resolve_extend_for_outer(expr, plan: RelationPlan,
                               outer_text_refs: Dict[str, str],
                               outer_lang_refs: Optional[Dict[str, str]] = None,
                               outer_type_refs: Optional[Dict[str, str]] = None,
                               outer_uuid_refs: Optional[Dict[str, str]] = None) -> str:
    """Resolve an extend expression using outer query column references.

    Instead of resolving variables to inner plan term aliases (e.g. t1.term_text),
    this substitutes them with the outer query's references (e.g. sub.date__text).
    """
    from .jena_types import ExprVar as EV, ExprValue as EVa, ExprFunction as EF

    if isinstance(expr, EV):
        if expr.var in outer_text_refs:
            return outer_text_refs[expr.var]
        return _expr_to_sql_str(expr, plan)

    if isinstance(expr, EVa):
        return _expr_to_sql_str(expr, plan)

    if isinstance(expr, EF):
        fname = (expr.name or "").lower()
        eargs = expr.args or []

        # DATATYPE() needs type + lang columns, not just text
        if fname == "datatype" and len(eargs) == 1 and isinstance(eargs[0], EV):
            var_name = eargs[0].var
            type_ref = (outer_type_refs or {}).get(var_name, "NULL")
            lang_ref = (outer_lang_refs or {}).get(var_name, "NULL")
            return (
                f"(CASE WHEN {type_ref} = 'U' THEN ''"
                f" WHEN {lang_ref} IS NOT NULL AND {lang_ref} != '' THEN"
                f" 'http://www.w3.org/1999/02/22-rdf-syntax-ns#langString'"
                f" ELSE 'http://www.w3.org/2001/XMLSchema#string' END)"
            )

        # LANG() needs lang column
        if fname == "lang" and len(eargs) == 1 and isinstance(eargs[0], EV):
            var_name = eargs[0].var
            lang_ref = (outer_lang_refs or {}).get(var_name, "NULL")
            return f"COALESCE({lang_ref}, '')"

        # sameTerm() needs UUID columns
        if fname == "sameterm" and len(eargs) == 2:
            if isinstance(eargs[0], EV) and isinstance(eargs[1], EV):
                l_uuid = (outer_uuid_refs or {}).get(eargs[0].var, f"{eargs[0].var}__uuid")
                r_uuid = (outer_uuid_refs or {}).get(eargs[1].var, f"{eargs[1].var}__uuid")
                return f"({l_uuid} = {r_uuid})"

        # isURI/isIRI/isLiteral/isBlank need type column
        if fname in ("isuri", "isiri") and len(eargs) == 1 and isinstance(eargs[0], EV):
            type_ref = (outer_type_refs or {}).get(eargs[0].var, "NULL")
            return f"({type_ref} = 'U')"
        if fname == "isliteral" and len(eargs) == 1 and isinstance(eargs[0], EV):
            type_ref = (outer_type_refs or {}).get(eargs[0].var, "NULL")
            return f"({type_ref} = 'L')"
        if fname == "isblank" and len(eargs) == 1 and isinstance(eargs[0], EV):
            type_ref = (outer_type_refs or {}).get(eargs[0].var, "NULL")
            return f"({type_ref} = 'B')"

        args_sql = [_resolve_extend_for_outer(a, plan, outer_text_refs,
                     outer_lang_refs=outer_lang_refs,
                     outer_type_refs=outer_type_refs,
                     outer_uuid_refs=outer_uuid_refs)
                     for a in eargs]
        # Delegate to the standard function translator with pre-resolved args
        return _func_with_resolved_args(expr, args_sql, plan)

    return _expr_to_sql_str(expr, plan)


def _func_with_resolved_args(expr, args_sql: List[str], plan_or_ctx) -> str:
    """Translate an ExprFunction using pre-resolved argument SQL strings."""
    from .jena_types import ExprFunction as EF
    from .jena_sql_expressions import (
        _FUNC_MAP, _apply_typed_casts, _NUMERIC_DTYPES, _DATETIME_DTYPES, _DATE_DTYPES,
    )

    name = (expr.name or "").lower()
    args = expr.args or []

    if name in _FUNC_MAP and len(args_sql) == 2:
        l, r = args_sql
        if name in ("gt", "lt", "ge", "le", "eq", "ne"):
            l, r = _apply_typed_casts(args[0], args[1], l, r)
        return f"({l} {_FUNC_MAP[name]} {r})"

    if name == "not" and len(args_sql) == 1:
        return f"(NOT {args_sql[0]})"

    # Date/time extraction
    _DT_EXTRACT = {
        "year": "YEAR", "month": "MONTH", "day": "DAY",
        "hours": "HOUR", "minutes": "MINUTE", "seconds": "SECOND",
    }
    if name in _DT_EXTRACT and len(args_sql) == 1:
        return f"EXTRACT({_DT_EXTRACT[name]} FROM CAST({args_sql[0]} AS TIMESTAMP))"

    if (name == "tz" or name == "timezone") and len(args_sql) == 1:
        return (
            f"COALESCE(REGEXP_REPLACE(CAST({args_sql[0]} AS TEXT), "
            f"'^.*([+-]\\d{{2}}:\\d{{2}}|Z)$', '\\1'), '')"
        )

    if name == "now" and len(args_sql) == 0:
        return "CAST(NOW() AS TEXT)"

    if name == "contains" and len(args_sql) == 2:
        return f"(POSITION({args_sql[1]} IN {args_sql[0]}) > 0)"

    if name == "strlen" and len(args_sql) == 1:
        return f"LENGTH({args_sql[0]})"

    if name == "ucase" and len(args_sql) == 1:
        return f"UPPER({args_sql[0]})"

    if name == "lcase" and len(args_sql) == 1:
        return f"LOWER({args_sql[0]})"

    if name == "concat":
        return "(" + " || ".join(args_sql) + ")"

    if name == "str" and len(args_sql) == 1:
        return args_sql[0]

    if name == "if" and len(args_sql) == 3:
        return f"(CASE WHEN {args_sql[0]} THEN {args_sql[1]} ELSE {args_sql[2]} END)"

    if name == "coalesce":
        return f"COALESCE({', '.join(args_sql)})"

    if name == "bound" and len(args_sql) == 1:
        return f"({args_sql[0]} IS NOT NULL)"

    # isNumeric
    if name == "isnumeric" and len(args_sql) == 1:
        return f"({args_sql[0]} ~ '^[+-]?(\\d+\\.?\\d*|\\.\\d+)([eE][+-]?\\d+)?$')"

    # UUID / STRUUID
    if name == "uuid" and len(args_sql) == 0:
        return "'urn:uuid:' || gen_random_uuid()::text"
    if name == "struuid" and len(args_sql) == 0:
        return "gen_random_uuid()::text"

    # MD5 (built-in)
    if name == "md5" and len(args_sql) == 1:
        return f"md5({args_sql[0]})"

    # SHA hash functions (pgcrypto)
    if name in ("sha1", "sha256", "sha384", "sha512") and len(args_sql) == 1:
        return f"encode(digest({args_sql[0]}, '{name}'), 'hex')"

    # ENCODE_FOR_URI
    if name == "encode_for_uri" and len(args_sql) == 1:
        from .jena_sql_expressions import _encode_for_uri_sql
        return _encode_for_uri_sql(args_sql[0])

    # STRLANG / STRDT — return string value
    if name == "strlang" and len(args_sql) == 2:
        return args_sql[0]
    if name == "strdt" and len(args_sql) == 2:
        return args_sql[0]

    # IRI / URI constructor
    if name in ("iri", "uri") and len(args_sql) == 1:
        return args_sql[0]

    # BNODE constructor
    if name == "bnode":
        if len(args_sql) == 0:
            return "'_:b' || gen_random_uuid()::text"
        if len(args_sql) == 1:
            return f"'_:b' || md5({args_sql[0]})"

    # ABS / CEIL / FLOOR / ROUND
    if name == "abs" and len(args_sql) == 1:
        return f"ABS({args_sql[0]})"
    if name == "ceil" and len(args_sql) == 1:
        return f"CEIL({args_sql[0]})"
    if name == "floor" and len(args_sql) == 1:
        return f"FLOOR({args_sql[0]})"
    if name == "round" and len(args_sql) == 1:
        return f"ROUND({args_sql[0]})"

    # SUBSTR / SUBSTRING
    if name in ("substr", "substring"):
        if len(args_sql) >= 3:
            return f"SUBSTRING({args_sql[0]}, {args_sql[1]}, {args_sql[2]})"
        if len(args_sql) >= 2:
            return f"SUBSTRING({args_sql[0]}, {args_sql[1]})"

    # REPLACE
    if name == "replace" and len(args_sql) >= 3:
        if len(args_sql) >= 4 and "'i'" in args_sql[3]:
            return f"REGEXP_REPLACE({args_sql[0]}, {args_sql[1]}, {args_sql[2]}, 'gi')"
        return f"REGEXP_REPLACE({args_sql[0]}, {args_sql[1]}, {args_sql[2]})"

    # STRSTARTS / STRENDS
    if name == "strstarts" and len(args_sql) == 2:
        return f"({args_sql[0]} LIKE {args_sql[1]} || '%%')"
    if name == "strends" and len(args_sql) == 2:
        return f"({args_sql[0]} LIKE '%%' || {args_sql[1]})"

    # REGEX
    if name == "regex" and len(args_sql) >= 2:
        if len(args_sql) >= 3 and "'i'" in args_sql[2]:
            return f"({args_sql[0]} ~* {args_sql[1]})"
        return f"({args_sql[0]} ~ {args_sql[1]})"

    # IN / NOT IN
    if name == "in" and len(args_sql) >= 2:
        return f"({args_sql[0]} IN ({', '.join(args_sql[1:])}))"
    if name == "notin" and len(args_sql) >= 2:
        return f"({args_sql[0]} NOT IN ({', '.join(args_sql[1:])}))"

    # Generic fallback
    return f"{name.upper()}({', '.join(args_sql)})"


# ===========================================================================
# HAVING expression helper
# ===========================================================================

def _having_expr_to_sql(expr, plan: RelationPlan, agg_sql_map: Dict[str, str]) -> str:
    """Translate a HAVING expression to SQL.

    Replaces aggregate variable references (e.g. '.0') with their SQL
    aggregate expressions (e.g. 'COUNT(*)') so they can appear in HAVING.
    """
    from .jena_types import ExprVar as EV, ExprValue as EVa, ExprFunction as EF

    if isinstance(expr, EV):
        if expr.var in agg_sql_map:
            return agg_sql_map[expr.var]
        # Might be an extend alias referencing an aggregate
        if plan.extend_exprs:
            ext = plan.extend_exprs.get(expr.var)
            if isinstance(ext, EV) and ext.var in agg_sql_map:
                return agg_sql_map[ext.var]
        # Fall back to regular resolution
        return _expr_to_sql_str(expr, plan)

    if isinstance(expr, EVa):
        return _expr_to_sql_str(expr, plan)

    if isinstance(expr, EF):
        args_sql = [_having_expr_to_sql(a, plan, agg_sql_map) for a in (expr.args or [])]
        name = (expr.name or "").lower()
        # Binary operators
        _OP_MAP = {
            "gt": ">", "lt": "<", "ge": ">=", "le": "<=",
            "eq": "=", "ne": "!=", "add": "+", "subtract": "-",
            "multiply": "*", "divide": "/",
        }
        if name in _OP_MAP and len(args_sql) == 2:
            return f"({args_sql[0]} {_OP_MAP[name]} {args_sql[1]})"
        if name == "and" and len(args_sql) == 2:
            return f"({args_sql[0]} AND {args_sql[1]})"
        if name == "or" and len(args_sql) == 2:
            return f"({args_sql[0]} OR {args_sql[1]})"
        if name == "not" and len(args_sql) == 1:
            return f"NOT ({args_sql[0]})"
        # Generic function fallback
        return f"{name.upper()}({', '.join(args_sql)})"

    return _expr_to_sql_str(expr, plan)


# ===========================================================================
# Aggregate inner-expression helper
# ===========================================================================

def _agg_expr_to_inner_sql(expr, plan: RelationPlan) -> str:
    """Translate an aggregate expression for the inner query of _emit_bgp_optimized.

    Resolves ExprVar references to UUID columns (q0.subject_uuid etc.)
    which are always available in the inner query, instead of text columns
    which may require a term JOIN that isn't present.
    """
    from .jena_types import ExprAggregator, ExprVar as EV
    if not isinstance(expr, ExprAggregator):
        return _expr_to_sql_str(expr, plan)

    name = (expr.name or "").upper()

    # Resolve inner expression to UUID column
    if expr.expr is None:
        inner = "*"
    elif isinstance(expr.expr, EV):
        slot = plan.var_slots.get(expr.expr.var)
        if slot and slot.positions:
            q_alias, uuid_col = slot.positions[0]
            inner = f"{q_alias}.{uuid_col}"
        else:
            inner = _expr_to_sql_str(expr.expr, plan)
    else:
        inner = _expr_to_sql_str(expr.expr, plan)

    if name == "COUNT":
        if expr.distinct:
            return f"COUNT(DISTINCT {inner})"
        return f"COUNT({inner})"
    elif name == "SUM":
        return f"SUM(CAST({inner} AS NUMERIC))"
    elif name == "AVG":
        return f"AVG(CAST({inner} AS NUMERIC))"
    elif name == "MIN":
        return f"MIN({inner})"
    elif name == "MAX":
        return f"MAX({inner})"
    elif name == "GROUP_CONCAT":
        sep = expr.separator or " "
        return f"STRING_AGG({inner}, '{_esc(sep)}')"
    elif name == "SAMPLE":
        return f"MIN({inner})"

    return f"{name}({inner})"


# ===========================================================================
# Property path emitter
# ===========================================================================

MAX_PATH_DEPTH = 100  # cycle prevention for recursive CTEs


def _emit_path(plan: RelationPlan, space_id: str,
               needed_vars: Optional[set] = None) -> str:
    """Emit a property path pattern as SQL using WITH RECURSIVE CTEs.

    The CTE produces (start_uuid, end_uuid) pairs, then we JOIN to
    the term table for text resolution of projected variables.
    """
    meta = plan._path_meta  # type: ignore[attr-defined]
    path_expr = meta["path"]
    subject = meta["subject"]
    obj = meta["object"]
    quad_table = meta["quad_table"]
    term_table = meta["term_table"]
    graph_uri = meta["graph_uri"]
    cte_alias = meta["cte_alias"]

    # Graph constraint clause (applied to every quad scan)
    graph_clause = ""
    if graph_uri:
        graph_clause = (
            f" AND q.context_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(graph_uri)}' AND term_type = 'U' LIMIT 1)"
        )

    # Generate the path SQL (may include WITH RECURSIVE)
    cte_parts, path_select = _path_to_sql(
        path_expr, quad_table, term_table, graph_clause, cte_alias
    )

    # Apply subject/object constraints
    where_parts = []
    if isinstance(subject, URINode):
        where_parts.append(
            f"{cte_alias}.start_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(subject.value)}' AND term_type = 'U' LIMIT 1)"
        )
    if isinstance(obj, URINode):
        where_parts.append(
            f"{cte_alias}.end_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(obj.value)}' AND term_type = 'U' LIMIT 1)"
        )

    where_clause = ""
    if where_parts:
        where_clause = "\nWHERE " + " AND ".join(where_parts)

    # Build SELECT with term JOINs for variable resolution
    select_cols = []
    term_joins = []

    for node, uuid_col in [(subject, "start_uuid"), (obj, "end_uuid")]:
        if isinstance(node, VarNode):
            t_alias = f"t_{node.name}"
            term_joins.append(
                f"JOIN {term_table} AS {t_alias} "
                f"ON {cte_alias}.{uuid_col} = {t_alias}.term_uuid"
            )
            select_cols.append(f"{t_alias}.term_text AS {node.name}")
            select_cols.append(f"{cte_alias}.{uuid_col} AS {node.name}__uuid")
            select_cols.append(f"{t_alias}.term_type AS {node.name}__type")

    if not select_cols:
        select_cols = ["1"]

    # Assemble final SQL
    parts = []
    if cte_parts:
        parts.append(cte_parts)
    parts.append(f"SELECT {', '.join(select_cols)}")
    parts.append(f"FROM ({path_select}) AS {cte_alias}")
    parts.extend(term_joins)
    if where_clause:
        parts.append(where_clause)

    return "\n".join(parts)


def _path_to_sql(path: PathExpr, quad_table: str, term_table: str,
                 graph_clause: str, cte_alias: str) -> tuple:
    """Convert a PathExpr to SQL.

    Returns (cte_prefix, select_sql) where cte_prefix is a WITH RECURSIVE
    clause (or empty string) and select_sql is the SELECT that produces
    (start_uuid, end_uuid) pairs.
    """

    # Simple link: just a triple pattern
    if isinstance(path, PathLink):
        pred_filter = (
            f"predicate_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(path.uri)}' AND term_type = 'U' LIMIT 1)"
        )
        sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid "
            f"FROM {quad_table} q "
            f"WHERE {pred_filter}{graph_clause}"
        )
        return "", sql

    # Inverse: swap start/end
    if isinstance(path, PathInverse):
        cte, inner_sql = _path_to_sql(path.sub, quad_table, term_table, graph_clause, cte_alias)
        sql = (
            f"SELECT inv.end_uuid AS start_uuid, inv.start_uuid AS end_uuid "
            f"FROM ({inner_sql}) AS inv"
        )
        return cte, sql

    # Alternative: UNION
    if isinstance(path, PathAlt):
        cte_l, sql_l = _path_to_sql(path.left, quad_table, term_table, graph_clause, cte_alias + "_l")
        cte_r, sql_r = _path_to_sql(path.right, quad_table, term_table, graph_clause, cte_alias + "_r")
        cte = ""
        if cte_l or cte_r:
            parts = [p for p in [cte_l, cte_r] if p]
            cte = "\n".join(parts)
        sql = f"({sql_l}) UNION ({sql_r})"
        return cte, sql

    # Sequence: JOIN
    if isinstance(path, PathSeq):
        cte_l, sql_l = _path_to_sql(path.left, quad_table, term_table, graph_clause, cte_alias + "_l")
        cte_r, sql_r = _path_to_sql(path.right, quad_table, term_table, graph_clause, cte_alias + "_r")
        cte = ""
        if cte_l or cte_r:
            parts = [p for p in [cte_l, cte_r] if p]
            cte = "\n".join(parts)
        sql = (
            f"SELECT lp.start_uuid, rp.end_uuid "
            f"FROM ({sql_l}) AS lp "
            f"JOIN ({sql_r}) AS rp ON lp.end_uuid = rp.start_uuid"
        )
        return cte, sql

    # One or more (+): WITH RECURSIVE
    if isinstance(path, PathOneOrMore):
        _, base_sql = _path_to_sql(path.sub, quad_table, term_table, graph_clause, cte_alias + "_base")
        rec_name = f"{cte_alias}_rec"
        cte = (
            f"WITH RECURSIVE {rec_name}(start_uuid, end_uuid, depth) AS (\n"
            f"  SELECT start_uuid, end_uuid, 1 FROM ({base_sql}) AS _base\n"
            f"  UNION\n"
            f"  SELECT r.start_uuid, step.end_uuid, r.depth + 1\n"
            f"  FROM {rec_name} r\n"
            f"  JOIN ({base_sql}) AS step ON r.end_uuid = step.start_uuid\n"
            f"  WHERE r.depth < {MAX_PATH_DEPTH}\n"
            f")"
        )
        sql = f"SELECT DISTINCT start_uuid, end_uuid FROM {rec_name}"
        return cte, sql

    # Zero or more (*): WITH RECURSIVE + identity base case
    if isinstance(path, PathZeroOrMore):
        _, base_sql = _path_to_sql(path.sub, quad_table, term_table, graph_clause, cte_alias + "_base")
        rec_name = f"{cte_alias}_rec"
        # Identity: every node connected to itself
        identity_sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.subject_uuid AS end_uuid, 0 "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''} "
            f"UNION SELECT q.object_uuid, q.object_uuid, 0 "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''}"
        )
        cte = (
            f"WITH RECURSIVE {rec_name}(start_uuid, end_uuid, depth) AS (\n"
            f"  ({identity_sql})\n"
            f"  UNION\n"
            f"  SELECT r.start_uuid, step.end_uuid, r.depth + 1\n"
            f"  FROM {rec_name} r\n"
            f"  JOIN ({base_sql}) AS step ON r.end_uuid = step.start_uuid\n"
            f"  WHERE r.depth < {MAX_PATH_DEPTH}\n"
            f")"
        )
        sql = f"SELECT DISTINCT start_uuid, end_uuid FROM {rec_name}"
        return cte, sql

    # Zero or one (?): identity UNION one step
    if isinstance(path, PathZeroOrOne):
        _, base_sql = _path_to_sql(path.sub, quad_table, term_table, graph_clause, cte_alias + "_base")
        identity_sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.subject_uuid AS end_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''} "
            f"UNION SELECT q.object_uuid, q.object_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''}"
        )
        sql = f"({identity_sql}) UNION ({base_sql})"
        return "", sql

    # Negated property set: all predicates EXCEPT the listed ones
    if isinstance(path, PathNegPropSet):
        if path.uris:
            exclusions = " AND ".join(
                f"q.predicate_uuid != (SELECT term_uuid FROM {term_table} "
                f"WHERE term_text = '{_esc(u)}' AND term_type = 'U' LIMIT 1)"
                for u in path.uris
            )
            sql = (
                f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid "
                f"FROM {quad_table} q "
                f"WHERE {exclusions}{graph_clause}"
            )
        else:
            sql = (
                f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid "
                f"FROM {quad_table} q"
                + (f" WHERE TRUE{graph_clause}" if graph_clause else "")
            )
        return "", sql

    # Fallback
    logger.warning("Unsupported path type: %s", type(path).__name__)
    return "", "SELECT NULL AS start_uuid, NULL AS end_uuid WHERE FALSE"


# ===========================================================================
# Helper: compute needed vars
# ===========================================================================

def _needed_vars(plan: RelationPlan) -> Optional[set]:
    """Compute which vars actually need term JOINs (text/type resolution).

    Returns None if all vars are needed (no projection), otherwise the set
    of var names that are referenced by SELECT, ORDER BY, FILTER, EXTEND,
    GROUP BY, or aggregates.
    """
    if plan.select_vars is None:
        return None  # no projection — need all vars

    needed = set()
    if plan.select_vars:
        needed.update(plan.select_vars)
    if plan.order_by:
        for key, _ in plan.order_by:
            if isinstance(key, str):
                needed.add(key)
            else:
                needed.update(_vars_in_expr(key))
    if plan.group_by:
        needed.update(plan.group_by)
    if plan.filter_exprs:
        for expr in plan.filter_exprs:
            needed.update(_vars_in_expr(expr))
    if plan.having_exprs:
        for expr in plan.having_exprs:
            needed.update(_vars_in_expr(expr))
    if plan.extend_exprs:
        for var, expr in plan.extend_exprs.items():
            needed.add(var)
            needed.update(_vars_in_expr(expr))
    if plan.aggregates:
        for var, expr in plan.aggregates.items():
            needed.add(var)
            needed.update(_vars_in_expr(expr))
    return needed
