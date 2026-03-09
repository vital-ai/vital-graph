"""
Pass 3: EMIT — Walk the resolved RelationPlan tree and produce SQL strings.

Handles BGP (with optimized inner/outer split), JOIN, LEFT JOIN, UNION,
MINUS, TABLE (VALUES), and modifier application via sqlglot.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

import sqlglot

from .jena_sparql.jena_types import (
    URINode, LiteralNode, VarNode,
    ExprVar, ExprValue, ExprFunction, Expr,
    PathExpr, PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne, PathNegPropSet,
)
from .jena_sql_ir import RelationPlan, PG_DIALECT
from .jena_sql_helpers import _esc, _vars_in_expr
from .jena_sql_expressions import _expr_to_sql_str, _expr_to_sql_str_inner

logger = logging.getLogger(__name__)


def _infer_extend_type(expr) -> str:
    """Infer the RDF type annotation for an EXTEND expression result.

    Returns a SQL expression for the __type column:
      'U' for IRI/URI constructors
      'B' for BNODE constructors
      'L' for literals (arithmetic, string functions, etc.)
    """
    from .jena_sparql.jena_types import ExprFunction as EF, ExprVar as EV
    if isinstance(expr, EF):
        fname = (expr.name or "").lower()
        if fname in ("iri", "uri"):
            return "'U'"
        if fname == "bnode":
            return "'B'"
        if fname == "struuid":
            return "'L'"
        if fname == "uuid":
            return "'U'"
    # Default: literal (arithmetic, string functions, math, etc.)
    return "'L'"


# String functions that preserve the input's lang tag and datatype
_LANG_PRESERVING_FUNCS = {
    "lcase", "ucase", "substr", "replace", "strafter", "strbefore",
}

# Numeric functions whose result is xsd:integer
_INTEGER_RESULT_FUNCS = {"ceil", "floor", "round"}

# Numeric functions whose result is xsd:decimal (or inherits input type)
_DECIMAL_RESULT_FUNCS = {"abs"}

XSD = "http://www.w3.org/2001/XMLSchema#"


def _infer_extend_datatype(expr, lang_refs: dict, type_refs: dict,
                           datatype_refs: dict = None) -> str:
    """Infer the __datatype SQL expression for an EXTEND result.

    Returns a SQL expression string or 'NULL'.
    """
    from .jena_sparql.jena_types import ExprFunction as EF, ExprVar as EV, ExprValue as _EVa2, LiteralNode as _LN2
    # Handle literal constants (e.g. BIND(4 AS ?z) → xsd:integer)
    if isinstance(expr, _EVa2) and hasattr(expr, 'node') and isinstance(expr.node, _LN2):
        if expr.node.datatype:
            return f"'{expr.node.datatype}'"
        return "NULL"
    if not isinstance(expr, EF):
        return "NULL"
    fname = (expr.name or "").lower()
    args = expr.args or []
    dt_refs = datatype_refs or {}

    # Arithmetic / math functions: propagate input datatype when possible
    if fname == "divide":
        # Division always produces xsd:decimal per SPARQL spec
        return f"'{XSD}decimal'"
    if fname in ("add", "subtract", "multiply"):
        # Try to propagate from first arg
        if args and isinstance(args[0], EV) and args[0].var in dt_refs:
            return dt_refs[args[0].var]
        return f"'{XSD}integer'"

    if fname in _INTEGER_RESULT_FUNCS:
        # CEIL/FLOOR/ROUND preserve input datatype per SPARQL spec
        if args and isinstance(args[0], EV) and args[0].var in dt_refs:
            return dt_refs[args[0].var]
        return f"'{XSD}integer'"

    if fname in _DECIMAL_RESULT_FUNCS:
        # ABS preserves input datatype
        if args and isinstance(args[0], EV) and args[0].var in dt_refs:
            return dt_refs[args[0].var]
        return f"'{XSD}decimal'"

    # String functions preserve the input's datatype/lang
    if fname in _LANG_PRESERVING_FUNCS and args:
        src = args[0]
        if isinstance(src, EV):
            lang_ref = lang_refs.get(src.var)
            dt_ref = dt_refs.get(src.var)
            if lang_ref and dt_ref:
                # If input has lang → rdf:langString; if has explicit datatype → that; else NULL
                return (
                    f"CASE WHEN {lang_ref} IS NOT NULL AND {lang_ref} != '' "
                    f"THEN 'http://www.w3.org/1999/02/22-rdf-syntax-ns#langString' "
                    f"WHEN {dt_ref} IS NOT NULL AND {dt_ref} != '' "
                    f"THEN {dt_ref} "
                    f"ELSE NULL END"
                )
            elif lang_ref:
                return (
                    f"CASE WHEN {lang_ref} IS NOT NULL AND {lang_ref} != '' "
                    f"THEN 'http://www.w3.org/1999/02/22-rdf-syntax-ns#langString' "
                    f"ELSE NULL END"
                )
        return "NULL"

    # str() always returns xsd:string
    if fname == "str":
        return f"'{XSD}string'"

    # STRLEN returns xsd:integer (it's a count)
    if fname == "strlen":
        return f"'{XSD}integer'"

    # Date/time extraction → xsd:integer
    if fname in ("year", "month", "day", "hours", "minutes"):
        return f"'{XSD}integer'"

    # SECONDS → xsd:decimal per SPARQL spec
    if fname == "seconds":
        return f"'{XSD}decimal'"

    # ENCODE_FOR_URI → xsd:string
    if fname == "encode_for_uri":
        return f"'{XSD}string'"

    # IF(cond, then, else) — infer datatype from branches
    if fname == "if" and len(args) >= 3:
        from .jena_sparql.jena_types import ExprValue as EVa, LiteralNode as LN
        # Check then/else branches for constant literal datatypes
        for branch in (args[1], args[2]):
            if isinstance(branch, EVa) and hasattr(branch, 'node') and isinstance(branch.node, LN):
                if branch.node.datatype:
                    return f"'{branch.node.datatype}'"
        return "NULL"

    # COALESCE: build SQL COALESCE over possible datatypes from each arg
    if fname == "coalesce" and args:
        from .jena_sparql.jena_types import ExprValue as _EVa, ExprFunction as _EF2, LiteralNode as _LN
        dt_parts = []
        for a in args:
            if isinstance(a, EV) and a.var in dt_refs:
                dt_parts.append(dt_refs[a.var])
            elif isinstance(a, _EVa) and hasattr(a, 'node') and isinstance(a.node, _LN):
                if a.node.datatype:
                    dt_parts.append(f"'{a.node.datatype}'")
            elif isinstance(a, _EF2):
                # Recurse for nested expressions (e.g. ?o/?x → decimal)
                sub_dt = _infer_extend_datatype(a, lang_refs, type_refs, datatype_refs=datatype_refs)
                if sub_dt != "NULL":
                    dt_parts.append(sub_dt)
        if len(dt_parts) == 1:
            return dt_parts[0]
        if dt_parts:
            return f"COALESCE({', '.join(dt_parts)})"
        return f"'{XSD}integer'"

    # CONCAT → no datatype annotation (plain literal)
    # SPARQL spec: result type depends on input types; safest is no annotation
    if fname == "concat":
        return "NULL"

    # STRDT explicitly sets the datatype (2nd arg is the datatype URI)
    if fname == "strdt" and len(args) >= 2:
        from .jena_sparql.jena_types import ExprValue as EVa
        if isinstance(args[1], EVa) and hasattr(args[1], 'node') and args[1].node:
            return f"'{args[1].node.value}'"

    # STRLANG → rdf:langString
    if fname == "strlang":
        return "'http://www.w3.org/1999/02/22-rdf-syntax-ns#langString'"

    # TIMEZONE → xsd:dayTimeDuration
    if fname == "timezone":
        return f"'{XSD}dayTimeDuration'"

    # TZ → plain literal (no datatype)
    if fname == "tz":
        return "NULL"

    # datatype() returns a URI, not a literal
    if fname in ("iri", "uri", "bnode", "struuid", "datatype"):
        return "NULL"

    return "NULL"


def _infer_extend_lang(expr, lang_refs: dict) -> str:
    """Infer the __lang SQL expression for an EXTEND result.

    Returns a SQL expression string or 'NULL'.
    """
    from .jena_sparql.jena_types import ExprFunction as EF, ExprVar as EV
    if not isinstance(expr, EF):
        return "NULL"
    fname = (expr.name or "").lower()
    args = expr.args or []

    # Lang-preserving string functions propagate the input's lang tag
    if fname in _LANG_PRESERVING_FUNCS and args:
        src = args[0]
        if isinstance(src, EV) and src.var in lang_refs:
            return lang_refs[src.var]
        return "NULL"

    # STRLANG explicitly sets the lang tag (2nd arg)
    if fname == "strlang" and len(args) >= 2:
        from .jena_sparql.jena_types import ExprValue as EVa
        if isinstance(args[1], EVa) and hasattr(args[1], 'node') and args[1].node:
            return f"'{args[1].node.value}'"

    return "NULL"


def _q(name: str) -> str:
    """Return a SQL-safe alias for a SPARQL variable name.

    Previously this quoted mixed-case names, but that caused inconsistencies
    in UNION padding and column references (some quoted, some not).
    Now returns the bare name — PostgreSQL lowercases it consistently,
    and _apply_var_map renames everything to opaque v0/v1/... at the end.
    """
    return name


# Module-level stats holder — set by generate_sql before calling emit().
# Maps (pred_uuid_str, obj_uuid_str) → row_count for selectivity scoring.
_quad_stats: Dict[tuple, int] = {}
_pred_stats: Dict[str, int] = {}


def set_quad_stats(quad_stats: Dict[tuple, int], pred_stats: Dict[str, int]):
    """Set predicate cardinality stats for the current emit pass."""
    global _quad_stats, _pred_stats
    _quad_stats = quad_stats
    _pred_stats = pred_stats


# Module-level datatype cache — set by generate_sql before calling emit().
# Maps datatype_id (int) → datatype_uri (str), loaded from {space}_datatype.
_datatype_cache: Dict[int, str] = {}
_dt_uri_to_id: Dict[str, int] = {}


def set_datatype_cache(cache: Dict[int, str]):
    """Set the datatype_id → URI cache for the current emit pass."""
    global _datatype_cache, _dt_uri_to_id
    _datatype_cache = cache
    _dt_uri_to_id = {uri: did for did, uri in cache.items()}


def _dt_ids_for_uris(uris) -> str:
    """Resolve a list of datatype URIs to a comma-separated ID list.

    Used to replace URI-based IN lists with numeric datatype_id comparisons.
    Returns 'NULL' if none resolve (makes IN clause always false).
    """
    ids = [str(_dt_uri_to_id[u]) for u in uris if u in _dt_uri_to_id]
    return ", ".join(ids) if ids else "NULL"


# ===========================================================================
# Join reordering
# ===========================================================================

_UUID_RE = re.compile(
    r"'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'::uuid")


def _reorder_joins(quad_tables, tagged_constraints):
    """Reorder quad tables so every JOIN references an already-placed table.

    SPARQL triple patterns may produce disconnected "islands" (e.g. slot
    properties listed before the edge that connects them to the frame).
    This creates cartesian products that are catastrophically slow.

    The algorithm:
    1. Parse each tagged constraint to find which *other* aliases it references.
    2. Pick the best chain root: prefer text-filter (ILIKE) tables as the
       most selective anchor.  Falls back to quad_tables[0].
    3. Greedy placement (dependency graph traversal): repeatedly pick the
       remaining table with the most constraints connecting it to
       already-placed tables.  When connectivity scores are tied, use
       predicate cardinality stats from the MV as a tiebreaker (prefer
       lower cardinality = more selective).
    4. Assign each constraint to the ON clause of the *last-placed* alias
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

    # --- Pre-compute per-table cardinality and fingerprint ---
    # Cardinality: estimated row count from stats MV (for selectivity tiebreaker).
    # Fingerprint: deterministic sort key from constraint content (pred UUID,
    # obj UUID, co-ref columns) — makes ordering independent of alias naming
    # so that identical triple patterns produce the same chain regardless of
    # SPARQL source order.
    _INF = float('inf')
    cardinality = {}   # alias → estimated row_count
    fingerprint = {}   # alias → deterministic sort key (str)

    for alias in all_aliases:
        pred_uuid = obj_uuid = None
        coref_cols = []   # columns co-referenced with other tables
        self_parts = []   # constant constraint fragments
        for owner, sql, refs in parsed:
            if owner != alias:
                continue
            if f"{alias}.predicate_uuid = " in sql:
                m = _UUID_RE.search(sql)
                if m:
                    pred_uuid = m.group(1)
                    self_parts.append(f"p={pred_uuid}")
            elif f"{alias}.object_uuid = " in sql and not refs:
                m = _UUID_RE.search(sql)
                if m:
                    obj_uuid = m.group(1)
                    self_parts.append(f"o={obj_uuid}")
            if refs:
                # Extract the column name pattern (e.g. "subject_uuid", "object_uuid")
                for col in ("subject_uuid", "object_uuid"):
                    if f"{alias}.{col}" in sql:
                        coref_cols.append(col)

        # Build deterministic fingerprint from constraint content
        fingerprint[alias] = "|".join(sorted(self_parts) + sorted(coref_cols))

        # Look up cardinality from stats
        if _quad_stats or _pred_stats:
            if pred_uuid and obj_uuid:
                card = _quad_stats.get((pred_uuid, obj_uuid))
                if card is not None:
                    cardinality[alias] = card
                    continue
            if pred_uuid:
                card = _pred_stats.get(pred_uuid)
                if card is not None:
                    cardinality[alias] = card

    # --- Pick chain root ---
    # Best anchor: the entity table co-referenced with the text-filter
    # (ILIKE) table.  The ILIKE table itself (name lookup) isn't a good
    # root — but its co-referenced entity table + the ILIKE table joined
    # immediately after forms a highly selective anchor cluster.
    # Falls back to quad_tables[0] if no ILIKE found.
    first = quad_tables[0]
    ilike_alias = None
    for owner, sql, refs in parsed:
        if not refs and ("ILIKE" in sql or "ilike" in sql):
            ilike_alias = owner
            break

    if ilike_alias and ilike_alias in alias_to_table:
        # Find the table co-referenced with the ILIKE table via subject_uuid.
        # That's the entity table (?a rdf:type ...) that shares the subject.
        subj_ref = f"{ilike_alias}.subject_uuid"
        for owner, sql, refs in parsed:
            if subj_ref in sql and refs:
                for ref_alias in refs:
                    if ref_alias in alias_to_table and ref_alias != ilike_alias:
                        first = alias_to_table[ref_alias]
                        logger.debug("Chain root: %s (co-ref of ILIKE anchor %s)",
                                     ref_alias, ilike_alias)
                        break
                if first.alias != quad_tables[0].alias:
                    break

    placed_order = [first]
    placed_set = {first.alias}
    remaining = [t.alias for t in quad_tables if t.alias != first.alias]

    # --- Greedy placement (dependency graph traversal) ---
    while remaining:
        best_alias = None
        best_score = (-1, _INF, "")  # (connectivity, -cardinality, fingerprint)

        for alias in remaining:
            conn = 0
            for owner, sql, refs in parsed:
                involved = {owner} | refs
                if alias in involved:
                    others = involved - {alias}
                    if others and others <= placed_set:
                        conn += 1

            card = cardinality.get(alias, _INF)
            fp = fingerprint.get(alias, "")
            # Primary: connectivity (higher = better).
            # Tiebreaker 1: cardinality (lower = better → more selective first).
            # Tiebreaker 2: fingerprint (deterministic, alias-independent).
            score = (conn, -card, fp)
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
# Semi-join pushdown for filter-only quad tables
# ===========================================================================

def _apply_semijoin_pushdown(ordered, on_map, first_conds, plan):
    """Convert filter-only quad tables into IN subquery conditions.

    DISABLED: This optimization can harm mid-chain filters (e.g. the Hyponym
    edge-type constraint in 7b went from 423ms to 18s).  It will be
    re-enabled once statistics-guided join reordering is in place, which
    can determine *when* a semi-join pushdown is actually beneficial
    based on actual predicate cardinality data.

    The idea: a quad table with subject=co-reference, predicate=constant,
    object=constant can be replaced by an IN subquery on the binding table.
    This helps endpoint filters (late in the chain) but hurts mid-chain
    filters that PG was already using effectively as index conditions.
    """
    # TODO: re-enable with selectivity-guided heuristic
    return ordered, on_map, first_conds


# ===========================================================================
# CTE staging for large BGPs
# ===========================================================================

_CTE_STAGE_THRESHOLD = 999  # disabled: eager CTE materialization hurts multi-hop traversals


def _build_staged_inner(ordered, on_map, first_conds, plan):
    """Split a large join chain into MATERIALIZED CTE stages.

    Each stage has ≤ CHUNK_SIZE tables so PG can do exhaustive planning
    per stage.  Bridge variables (shared between stages) are passed through
    as named columns.

    Returns (cte_prefix, final_stage, col_remap) or None if not needed.
        cte_prefix:  "WITH _s0 AS MATERIALIZED (...), ..." SQL string
        final_stage: alias of last CTE (e.g. "_s3")
        col_remap:   {"alias.col" → "final.col_name"} for outer refs
    """
    if len(ordered) <= _CTE_STAGE_THRESHOLD:
        return None

    _CHUNK_SIZE = 10

    # 1. Split into chunks
    chunks = []
    cur = []
    for t in ordered:
        cur.append(t)
        if len(cur) >= _CHUNK_SIZE:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    if len(chunks) <= 1:
        return None

    # 2. Map alias → chunk index
    alias_chunk = {}
    for ci, chunk in enumerate(chunks):
        for t in chunk:
            alias_chunk[t.alias] = ci

    # 3. Find cross-chunk column references that need to be bridged.
    # Scan every ON condition; if it references an alias in an earlier
    # chunk, that column must be exposed by the earlier CTE.
    _COLS = ("subject_uuid", "object_uuid", "edge_uuid",
             "source_node_uuid", "dest_node_uuid",
             "predicate_uuid", "context_uuid")

    bridge_set = set()  # (alias, col) that must be exposed
    for alias, conds in on_map.items():
        ci = alias_chunk[alias]
        for cond in conds:
            for other in alias_chunk:
                if alias_chunk[other] >= ci:
                    continue
                for col in _COLS:
                    if f"{other}.{col}" in cond:
                        bridge_set.add((other, col))

    # 4. Map (alias, col) → CTE column name.
    # Prefer variable names when available for readability.
    pos_to_var = {}
    for var, slot in plan.var_slots.items():
        for a, c in slot.positions:
            if a in alias_chunk:
                pos_to_var.setdefault((a, c), var)

    col_name_map = {}  # (alias, col) → cte_col_name
    _br_n = 0
    # Name bridge columns
    for a, c in sorted(bridge_set):
        var = pos_to_var.get((a, c))
        if var:
            col_name_map[(a, c)] = f"{var}__uuid"
        else:
            col_name_map[(a, c)] = f"_br{_br_n}"
            _br_n += 1
    # Name all var-position columns (needed by outer query)
    for (a, c), var in pos_to_var.items():
        if (a, c) not in col_name_map:
            col_name_map[(a, c)] = f"{var}__uuid"

    # 5. Generate each CTE stage
    cte_sqls = []
    exposed = {}  # accumulated col_name → True

    for ci, chunk in enumerate(chunks):
        sname = f"_s{ci}"
        chunk_aliases = {t.alias for t in chunk}

        # --- SELECT columns ---
        select_cols = []
        new_exposed = {}

        # Pass-through from previous stage
        if ci > 0:
            prev = f"_s{ci - 1}"
            for cn in sorted(exposed):
                select_cols.append(f"{prev}.{cn}")
                new_exposed[cn] = True

        # New columns from this chunk
        for (a, c), cn in sorted(col_name_map.items(), key=lambda x: x[1]):
            if a in chunk_aliases and cn not in new_exposed:
                select_cols.append(f"{a}.{c} AS {cn}")
                new_exposed[cn] = True

        if not select_cols:
            select_cols = ["1"]

        # --- FROM / JOIN ---
        from_parts = []
        where_parts = []

        if ci == 0:
            from_parts.append(f"FROM {chunk[0].table_name} AS {chunk[0].alias}")
            for t in chunk[1:]:
                conds = on_map.get(t.alias, [])
                if conds:
                    from_parts.append(
                        f"JOIN {t.table_name} AS {t.alias} ON "
                        + " AND ".join(conds))
                else:
                    from_parts.append(
                        f"JOIN {t.table_name} AS {t.alias} ON TRUE")
            where_parts = list(first_conds) if first_conds else []
        else:
            prev = f"_s{ci - 1}"
            from_parts.append(f"FROM {prev}")
            for t in chunk:
                conds = on_map.get(t.alias, [])
                rewritten = [_rewrite_cte_refs(c, alias_chunk, ci,
                                               col_name_map) for c in conds]
                if rewritten:
                    from_parts.append(
                        f"JOIN {t.table_name} AS {t.alias} ON "
                        + " AND ".join(rewritten))
                else:
                    from_parts.append(
                        f"CROSS JOIN {t.table_name} AS {t.alias}")

        sql = f"SELECT {', '.join(select_cols)}\n" + "\n".join(from_parts)
        if where_parts:
            sql += "\nWHERE " + " AND ".join(where_parts)

        cte_sqls.append(f"{sname} AS (\n{sql}\n)")
        exposed = new_exposed

    # 6. Assemble
    cte_prefix = "WITH\n" + ",\n".join(cte_sqls)
    final = f"_s{len(chunks) - 1}"

    # 7. Column remap for outer references
    col_remap = {}
    for (a, c), cn in col_name_map.items():
        col_remap[f"{a}.{c}"] = f"{final}.{cn}"

    return cte_prefix, final, col_remap


def _rewrite_cte_refs(cond, alias_chunk, current_ci, col_name_map):
    """Rewrite a constraint: replace earlier-chunk alias.col with CTE refs."""
    result = cond
    for (alias, col), cname in col_name_map.items():
        aci = alias_chunk.get(alias)
        if aci is not None and aci < current_ci:
            old_ref = f"{alias}.{col}"
            if old_ref in result:
                # Reference the immediately previous stage (pass-through
                # guarantees all earlier columns are available there)
                prev = f"_s{current_ci - 1}"
                result = result.replace(old_ref, f"{prev}.{cname}")
    return result


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

    quad_aliases = {t.alias for t in plan.tables if t.kind in ("quad", "edge_mv", "frame_entity_mv")}
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
        raw_flags = ""
        if flags_arg and isinstance(flags_arg, ExprValue):
            if isinstance(flags_arg.node, LiteralNode):
                raw_flags = flags_arg.node.value or ""
        op = "~*" if "i" in raw_flags else "~"
        # Embed non-'i' flags as (?flags) prefix in pattern
        pg_embedded = ""
        if "s" in raw_flags:
            pg_embedded += "s"
        if "m" in raw_flags:
            pg_embedded += "n"
        if "x" in raw_flags:
            pg_embedded += "x"
        pat = f"(?{pg_embedded}){escaped}" if pg_embedded else escaped
        term_cond = f"term_text {op} '{pat}'"
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
    # Simple table (VALUES) without modifiers — return directly
    if plan.kind == "table" and not (
        plan.filter_exprs or plan.having_exprs or plan.extend_exprs or plan.group_by
        or plan.aggregates or plan.select_vars is not None
        or plan.distinct or plan.order_by or plan.limit >= 0 or plan.offset > 0
    ):
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
    elif plan.kind == "table":
        base_sql = _emit_table(plan)
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

    # --- Build EXTEND and aggregate maps first (before FILTER) ---
    agg_sql_map: Dict[str, str] = {}
    _nb_agg_info: Dict[str, tuple] = {}  # agg_var -> (agg_name, input_var)
    if plan.aggregates:
        from .jena_sparql.jena_types import ExprAggregator as _EAgg, ExprVar as _EVRef
        for var, expr in plan.aggregates.items():
            sql_expr = _expr_to_sql_str(expr, plan)
            if sql_expr:
                agg_sql_map[var] = sql_expr
            if isinstance(expr, _EAgg):
                aname = (expr.name or "").upper()
                ivar = expr.expr.var if isinstance(expr.expr, _EVRef) else None
                _nb_agg_info[var] = (aname, ivar)

    extend_sql_map: Dict[str, str] = {}
    if plan.extend_exprs:
        for var, expr in plan.extend_exprs.items():
            if isinstance(expr, ExprVar) and expr.var in agg_sql_map:
                extend_sql_map[var] = agg_sql_map[expr.var]
            else:
                sql_expr = _expr_to_sql_str(expr, plan)
                if sql_expr:
                    # Cast raw numeric literals to TEXT so they're
                    # compatible with term_text columns in FILTERs/JOINs
                    if isinstance(expr, ExprValue) and hasattr(expr, 'node'):
                        from .jena_sparql.jena_types import LiteralNode as _LN
                        if isinstance(expr.node, _LN) and expr.node.datatype:
                            dt = expr.node.datatype
                            if any(t in dt for t in ("integer", "decimal", "double", "float", "byte", "short", "long", "int")):
                                sql_expr = f"CAST({sql_expr} AS TEXT)"
                    extend_sql_map[var] = sql_expr

    # --- Column scoping fix: if FILTER references EXTEND vars, wrap in subquery ---
    # SPARQL evaluation order: EXTEND produces columns BEFORE FILTER sees them.
    # In SQL, WHERE cannot reference SELECT aliases from the same level.
    # Solution: materialize EXTEND columns in a subquery, apply FILTER on outer.
    extend_vars = set(extend_sql_map.keys())
    filter_refs = set()
    if plan.filter_exprs:
        for expr in plan.filter_exprs:
            filter_refs.update(_vars_in_expr(expr))
    # Also check if later EXTENDs reference earlier ones (chained EXTEND)
    # and if the outer EXTEND expressions reference extend vars
    outer_extend_refs = set()
    if plan.extend_exprs and plan.select_vars:
        for var in plan.select_vars:
            if var in extend_sql_map and var not in plan.extend_exprs:
                continue
            if var in extend_sql_map:
                ext_expr = plan.extend_exprs.get(var)
                if ext_expr:
                    outer_extend_refs.update(_vars_in_expr(ext_expr))

    needs_extend_subquery = bool(extend_vars and (
        (filter_refs & extend_vars) or (outer_extend_refs & extend_vars)
    ))

    if needs_extend_subquery:
        # Partition extends: "inner" = referenced by FILTER (materialize in subquery),
        # "outer" = depend on inner extends (compute in outer SELECT).
        inner_extend_vars = extend_vars & (filter_refs | outer_extend_refs)
        # Also include any extend vars that inner extends depend on
        for var in list(inner_extend_vars):
            ext_expr = plan.extend_exprs.get(var) if plan.extend_exprs else None
            if ext_expr:
                deps = _vars_in_expr(ext_expr) & extend_vars
                inner_extend_vars.update(deps)
        outer_extend_vars = extend_vars - inner_extend_vars

        # Build inner SELECT with base columns + inner EXTEND columns materialized
        inner_cols = ["*"]
        for var in inner_extend_vars:
            sql_expr = extend_sql_map[var]
            inner_cols.append(f"{sql_expr} AS {_q(var)}")
            ext_expr = plan.extend_exprs.get(var) if plan.extend_exprs else None
            inferred_type = _infer_extend_type(ext_expr)
            inner_cols.append(f"{inferred_type} AS {var}__type")

        inner_sql = f"SELECT {', '.join(inner_cols)} FROM ({base_sql}) AS _base"
        wrapped_sql = f"SELECT * FROM ({inner_sql}) AS _ext"
        parsed = sqlglot.parse_one(wrapped_sql, dialect=PG_DIALECT)

        # Rewrite inner extends to reference materialized column names
        for var in inner_extend_vars:
            extend_sql_map[var] = _q(var)
        # Outer extends keep their original SQL expressions but vars they
        # reference are now materialized columns, so re-resolve them
        for var in outer_extend_vars:
            ext_expr = plan.extend_exprs.get(var) if plan.extend_exprs else None
            if ext_expr:
                sql_expr = _expr_to_sql_str(ext_expr, plan)
                if sql_expr:
                    # Replace inner extend var references with column names
                    for ivar in inner_extend_vars:
                        slot = plan.var_slots.get(ivar)
                        if slot and slot.text_col:
                            sql_expr = sql_expr.replace(slot.text_col, _q(ivar))
                    extend_sql_map[var] = sql_expr
    else:
        parsed = sqlglot.parse_one(base_sql, dialect=PG_DIALECT)

    # --- Apply FILTER ---
    if plan.filter_exprs:
        from .jena_sparql.jena_types import ExprExists as _EE
        for expr in plan.filter_exprs:
            if isinstance(expr, _EE):
                exists_sql = _emit_exists_subquery(expr, plan, space_id)
                if exists_sql:
                    parsed = parsed.where(exists_sql, dialect=PG_DIALECT)
            else:
                if needs_extend_subquery:
                    # Resolve var refs to materialized column names
                    sql_expr = _expr_to_sql_str(expr, plan)
                    if sql_expr:
                        # Replace extend var text_col refs with column names
                        for var in extend_vars:
                            slot = plan.var_slots.get(var)
                            if slot and slot.text_col:
                                sql_expr = sql_expr.replace(slot.text_col, _q(var))
                        parsed = parsed.where(sql_expr, dialect=PG_DIALECT)
                else:
                    sql_expr = _expr_to_sql_str(expr, plan)
                    if sql_expr:
                        parsed = parsed.where(sql_expr, dialect=PG_DIALECT)

    if plan.group_by:
        for gv in plan.group_by:
            slot = plan.var_slots.get(gv)
            if slot and slot.text_col:
                parsed = parsed.group_by(slot.text_col, dialect=PG_DIALECT)
            else:
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

    # --- Apply SELECT projection ---
    # Collect existing column aliases/expressions from the parsed SQL
    # so we can carry over companion columns for slot variables.
    _existing_aliases: Dict[str, str] = {}
    for _ex in parsed.expressions:
        if hasattr(_ex, "alias") and _ex.alias:
            _existing_aliases[_ex.alias] = _ex.sql(dialect=PG_DIALECT)

    # Build references for extend type inference from existing aliases
    _outer_lang_refs: Dict[str, str] = {}
    _outer_type_refs: Dict[str, str] = {}
    _outer_dt_refs: Dict[str, str] = {}
    for v in (plan.var_slots or {}):
        if f"{v}__lang" in _existing_aliases:
            _outer_lang_refs[v] = f"{v}__lang"
        if f"{v}__type" in _existing_aliases:
            _outer_type_refs[v] = f"{v}__type"
        if f"{v}__datatype" in _existing_aliases:
            _outer_dt_refs[v] = f"{v}__datatype"

    if plan.select_vars is not None:
        proj_cols = []
        _companion_gb_cols = []  # companion cols to add to GROUP BY
        for var in plan.select_vars:
            if var in extend_sql_map:
                proj_cols.append(f"{extend_sql_map[var]} AS {_q(var)}")
                # Add companion columns for extend variables.
                # With GROUP BY, companions are stripped from base SQL and need re-projection.
                # Without GROUP BY, we still need __type for non-literal extends (BNODE, IRI, UUID).
                ext_expr = plan.extend_exprs.get(var) if plan.extend_exprs else None
                needs_companions = False
                if ext_expr:
                    inferred_type = _infer_extend_type(ext_expr)
                    inferred_dt_check = _infer_extend_datatype(
                        ext_expr, _outer_lang_refs, _outer_type_refs,
                        datatype_refs=_outer_dt_refs)
                    needs_companions = (plan.group_by
                                        or inferred_type != "'L'"
                                        or inferred_dt_check != "NULL")
                if ext_expr and needs_companions:
                    if isinstance(ext_expr, ExprVar) and ext_expr.var in _nb_agg_info:
                        # Extend aliases an aggregate — infer companions from agg info
                        _an2, _iv2 = _nb_agg_info[ext_expr.var]
                        proj_cols.append(f"NULL AS {var}__uuid")
                        proj_cols.append(f"'L' AS {var}__type")
                        proj_cols.append(f"NULL AS {var}__lang")
                        if _an2 == "COUNT":
                            proj_cols.append(f"'{XSD}integer' AS {var}__datatype")
                        elif _an2 == "AVG":
                            proj_cols.append(f"'{XSD}decimal' AS {var}__datatype")
                        elif _iv2 and f"{_iv2}__datatype" in _existing_aliases:
                            _dt_src = _existing_aliases[f"{_iv2}__datatype"].split(" AS ")[0].strip()
                            proj_cols.append(f"MIN({_dt_src}) AS {var}__datatype")
                        else:
                            proj_cols.append(f"NULL AS {var}__datatype")
                    elif isinstance(ext_expr, ExprVar):
                        # Simple variable alias — carry over source companions
                        src = ext_expr.var
                        for sfx in ("__uuid", "__type", "__lang", "__datatype"):
                            src_alias = src + sfx
                            if src_alias in _existing_aliases:
                                _src_expr = _existing_aliases[src_alias].split(" AS ")[0].strip()
                                proj_cols.append(f"{_src_expr} AS {var}{sfx}")
                            else:
                                proj_cols.append(f"NULL AS {var}{sfx}")
                    else:
                        inferred_dt = _infer_extend_datatype(
                            ext_expr, _outer_lang_refs, _outer_type_refs,
                            datatype_refs=_outer_dt_refs)
                        inferred_lang = _infer_extend_lang(ext_expr, _outer_lang_refs)
                        proj_cols.append(f"NULL AS {var}__uuid")
                        proj_cols.append(f"{inferred_type} AS {var}__type")
                        proj_cols.append(f"{inferred_lang} AS {var}__lang")
                        proj_cols.append(f"{inferred_dt} AS {var}__datatype")
            elif var in agg_sql_map:
                proj_cols.append(f"{agg_sql_map[var]} AS {_q(var)}")
                # Add companion columns for aggregate results
                proj_cols.append(f"NULL AS {var}__uuid")
                proj_cols.append(f"'L' AS {var}__type")
                proj_cols.append(f"NULL AS {var}__lang")
                # Infer datatype from aggregate type
                _ai = _nb_agg_info.get(var)
                if _ai:
                    _an, _iv = _ai
                    if _an == "COUNT":
                        proj_cols.append(f"'{XSD}integer' AS {var}__datatype")
                    elif _an == "AVG":
                        proj_cols.append(f"'{XSD}decimal' AS {var}__datatype")
                    elif _iv and f"{_iv}__datatype" in _existing_aliases:
                        _dt_src = _existing_aliases[f"{_iv}__datatype"].split(" AS ")[0].strip()
                        proj_cols.append(f"{_dt_src} AS {var}__datatype")
                    else:
                        proj_cols.append(f"NULL AS {var}__datatype")
                else:
                    proj_cols.append(f"NULL AS {var}__datatype")
            else:
                slot = plan.var_slots.get(var)
                if slot and slot.text_col:
                    proj_cols.append(f"{slot.text_col} AS {_q(var)}")
                else:
                    proj_cols.append(f"NULL AS {_q(var)}")
                # Carry over companion columns from the original SQL
                for sfx in ("__type", "__uuid", "__lang", "__datatype"):
                    comp_alias = var + sfx
                    if comp_alias in _existing_aliases:
                        # Use the existing expression (preserves correct table refs)
                        proj_cols.append(f"{_existing_aliases[comp_alias]}")
                        if plan.group_by and var in plan.group_by:
                            # Extract the source expression (before AS alias)
                            _src = _existing_aliases[comp_alias].split(" AS ")[0].strip()
                            _companion_gb_cols.append(_src)
        if proj_cols:
            new_exprs = [sqlglot.parse_one(p, dialect=PG_DIALECT) for p in proj_cols]
            parsed = parsed.select(*new_exprs, append=False)
        # Add companion columns to GROUP BY
        for comp_col in _companion_gb_cols:
            parsed = parsed.group_by(comp_col, dialect=PG_DIALECT)
    else:
        for var, sql_expr in agg_sql_map.items():
            parsed = parsed.select(f"{sql_expr} AS {_q(var)}", append=True)
        for var, sql_expr in extend_sql_map.items():
            parsed = parsed.select(f"{sql_expr} AS {_q(var)}", append=True)

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
    if plan.extend_exprs:
        proj_vars |= set(plan.extend_exprs.keys())
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

    # Collect vars referenced by non-COUNT aggregates — they need term_text
    # (SUM/AVG need CAST(term_text AS NUMERIC), MIN/MAX/GROUP_CONCAT need term_text)
    if plan.aggregates:
        from .jena_sparql.jena_types import ExprAggregator as _EA, ExprVar as _EV
        for _agg_var, _agg_expr in plan.aggregates.items():
            if isinstance(_agg_expr, _EA) and (_agg_expr.name or "").upper() != "COUNT":
                if isinstance(_agg_expr.expr, _EV):
                    _ref_var = _agg_expr.expr.var
                    if _ref_var in plan.var_slots:
                        inner_text_vars.add(_ref_var)

    # Build aggregate/extend maps
    agg_sql_map: Dict[str, str] = {}
    if plan.aggregates:
        for var, expr in plan.aggregates.items():
            sql_expr = _agg_expr_to_inner_sql(expr, plan, inner_text_vars)
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
    quad_tables = [t for t in plan.tables if t.kind in ("quad", "edge_mv", "frame_entity_mv")]
    # Include vars referenced by aggregates that need term_text (already in inner_text_vars)
    agg_ref_vars = inner_text_vars & set(plan.var_slots.keys())
    all_needed = proj_vars | order_vars | filter_vars | extend_ref_vars | agg_ref_vars
    sub_alias = "sub"

    # Reorder joins and apply semi-join pushdown BEFORE building inner_cols,
    # because pushdown may update VarSlot positions (removing filter-only
    # quad tables and rewriting variable bindings to their co-reference targets).
    _ordered = _on_map = _first_conds = None
    if quad_tables and plan.tagged_constraints:
        _ordered, _on_map, _first_conds = _reorder_joins(quad_tables, plan.tagged_constraints)
        _ordered, _on_map, _first_conds = _apply_semijoin_pushdown(
            _ordered, _on_map, _first_conds, plan)

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
    # Vars that are only consumed by aggregates (not projected/filtered directly)
    # — their term JOINs are needed but raw columns must NOT be in SELECT
    # when GROUP BY is active (PostgreSQL would require them in GROUP BY)
    agg_only_vars = agg_ref_vars - (proj_vars | order_vars | filter_vars | extend_ref_vars)

    for var, slot in plan.var_slots.items():
        if var not in all_needed:
            continue
        # Skip raw column projection for aggregate-only vars when GROUP BY is present
        if plan.group_by and var in agg_only_vars:
            pass  # term JOIN still added below for the aggregate expression
        elif slot.positions:
            q_alias, uuid_col_name = slot.positions[0]
            inner_cols.append(f"{q_alias}.{uuid_col_name} AS {var}__uuid")

        # Include term JOIN in inner only if needed for ORDER BY or FILTER
        # Use pre-filtered subquery to give PG accurate cardinality → hash join
        if var in inner_text_vars and slot.term_ref_id:
            tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
            if tt:
                # Pre-filter term table to only UUIDs present in the source column.
                # Prefer narrower tables: frame_entity_mv < edge_mv < rdf_quad
                _kind_rank = {"frame_entity_mv": 0, "edge_mv": 1, "quad": 2}
                best_pos = slot.positions[0]
                best_rank = 99
                for pos_alias, pos_col in slot.positions:
                    pos_tbl = next((t for t in plan.tables if t.alias == pos_alias), None)
                    rank = _kind_rank.get(pos_tbl.kind, 99) if pos_tbl else 99
                    if rank < best_rank:
                        best_rank = rank
                        best_pos = (pos_alias, pos_col)
                q_alias, uuid_col_name = best_pos
                quad_tbl = next((t for t in plan.tables if t.alias == q_alias), None)
                quad_tbl_name = quad_tbl.table_name if quad_tbl else f"{space_id}_rdf_quad"
                from .jena_sql_expressions import _NUMERIC_DATATYPES_V1
                _num_ids = _dt_ids_for_uris(_NUMERIC_DATATYPES_V1)
                inner_term_joins.append(
                    f"JOIN (SELECT term_uuid, term_text, term_type, lang, datatype_id, "
                    f"CASE WHEN datatype_id IN ({_num_ids}) "
                    f"THEN CAST(term_text AS NUMERIC) END AS term_num "
                    f"FROM {tt.table_name} "
                    f"WHERE term_uuid IN ("
                    f"SELECT DISTINCT {uuid_col_name} FROM {quad_tbl_name}"
                    f")) AS {tt.alias} "
                    f"ON {tt.join_col} = {tt.alias}.term_uuid"
                )
                # Only project text/type/lang/datatype/num columns if the var is not agg-only
                if not (plan.group_by and var in agg_only_vars):
                    inner_cols.append(f"{tt.alias}.term_text AS {var}__text")
                    inner_cols.append(f"{tt.alias}.term_type AS {var}__type")
                    inner_cols.append(f"{tt.alias}.lang AS {var}__lang")
                    inner_cols.append(f"{tt.alias}.datatype_id AS {var}__datatype")
                    inner_cols.append(f"{tt.alias}.term_num AS {var}__num")

    if not inner_cols:
        inner_cols = ["1"]

    # --- CTE staging for large join chains ---
    staged = None
    if _ordered is not None:
        staged = _build_staged_inner(_ordered, _on_map, _first_conds, plan)

    if staged is not None:
        cte_prefix, final_stage, col_remap = staged
        logger.debug("CTE staging: %d stages for %d tables",
                     cte_prefix.count("AS MATERIALIZED"), len(_ordered))

        # Remap inner_cols: replace "alias.col" refs with CTE column refs
        remapped_cols = []
        for ic in inner_cols:
            rc = ic
            for old_ref, new_ref in col_remap.items():
                rc = rc.replace(old_ref, new_ref)
            remapped_cols.append(rc)
        inner_cols = remapped_cols

        # Remap inner_term_joins
        remapped_tj = []
        for tj in inner_term_joins:
            rt = tj
            for old_ref, new_ref in col_remap.items():
                rt = rt.replace(old_ref, new_ref)
            remapped_tj.append(rt)
        inner_term_joins = remapped_tj

    inner_parts = []
    if plan.distinct:
        inner_parts.append(f"SELECT DISTINCT {', '.join(inner_cols)}")
    else:
        inner_parts.append(f"SELECT {', '.join(inner_cols)}")

    # Emit FROM / JOIN using pre-computed ordered tables
    if staged is not None:
        # CTE-staged: just reference the final stage
        inner_parts.insert(0, cte_prefix)
        inner_parts.append(f"FROM {final_stage}")
        inner_parts.extend(inner_term_joins)
        first_conds = []  # already in stage 0's WHERE
    elif _ordered is not None:
        ordered, on_map, first_conds = _ordered, _on_map, _first_conds

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
        inner_parts.extend(inner_term_joins)
    elif quad_tables:
        inner_parts.append(f"FROM {quad_tables[0].table_name} AS {quad_tables[0].alias}")
        for qt in quad_tables[1:]:
            inner_parts.append(f"JOIN {qt.table_name} AS {qt.alias} ON TRUE")
        first_conds = list(plan.constraints) if plan.constraints else []
        inner_parts.extend(inner_term_joins)
    else:
        first_conds = list(plan.constraints) if plan.constraints else []
        inner_parts.extend(inner_term_joins)

    if first_conds:
        inner_parts.append("WHERE " + " AND ".join(first_conds))

    # FILTER conditions — split into inner (BGP vars only) and deferred (EXTEND vars)
    deferred_filter_exprs = []
    if plan.filter_exprs:
        from .jena_sparql.jena_types import ExprExists as _EE
        extend_var_names = set(plan.extend_exprs.keys()) if plan.extend_exprs else set()
        filter_parts = []
        for expr in plan.filter_exprs:
            if isinstance(expr, _EE):
                exists_sql = _emit_exists_subquery(expr, plan, space_id)
                if exists_sql:
                    filter_parts.append(exists_sql)
            else:
                # Check if this filter references any EXTEND vars
                refs = _vars_in_expr(expr)
                if refs & extend_var_names:
                    # Defer to outer query where EXTEND columns are available
                    deferred_filter_exprs.append(expr)
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
        # Build mapping: var_name -> outer SQL column reference for text/type/lang/uuid/num
        outer_text_refs: Dict[str, str] = {}
        outer_type_refs: Dict[str, str] = {}
        outer_lang_refs: Dict[str, str] = {}
        outer_uuid_refs: Dict[str, str] = {}
        outer_num_refs: Dict[str, str] = {}
        outer_datatype_refs: Dict[str, str] = {}
        for var in plan.var_slots:
            if var in inner_text_vars:
                outer_text_refs[var] = f"{sub_alias}.{var}__text"
                outer_type_refs[var] = f"{sub_alias}.{var}__type"
                outer_lang_refs[var] = f"{sub_alias}.{var}__lang"
                outer_datatype_refs[var] = f"{sub_alias}.{var}__datatype"
                outer_uuid_refs[var] = f"{sub_alias}.{var}__uuid"
                outer_num_refs[var] = f"{sub_alias}.{var}__num"
            else:
                outer_text_refs[var] = f"t_{var}.term_text"
                outer_type_refs[var] = f"t_{var}.term_type"
                outer_lang_refs[var] = f"t_{var}.lang"
                outer_datatype_refs[var] = f"t_{var}.datatype_id"
                outer_uuid_refs[var] = f"{sub_alias}.{var}__uuid"
                from .jena_sql_expressions import _NUMERIC_DATATYPES_V1
                outer_num_refs[var] = (
                    f"CASE WHEN t_{var}.datatype_id IN ({_dt_ids_for_uris(_NUMERIC_DATATYPES_V1)}) "
                    f"THEN CAST(t_{var}.term_text AS NUMERIC) END"
                )
        for ext_var, ext_expr in plan.extend_exprs.items():
            if ext_var not in extend_sql_map:
                sql_expr = _resolve_extend_for_outer(
                    ext_expr, plan, outer_text_refs,
                    outer_lang_refs=outer_lang_refs,
                    outer_type_refs=outer_type_refs,
                    outer_uuid_refs=outer_uuid_refs,
                    outer_num_refs=outer_num_refs,
                    outer_datatype_refs=outer_datatype_refs,
                )
                if sql_expr:
                    extend_sql_map[ext_var] = sql_expr

    # --- Build OUTER query: JOIN term for text resolution ---
    outer_cols = []
    outer_joins = []

    # Build a map of aggregate var → (agg_name, input_var) for datatype inference
    _agg_info: Dict[str, tuple] = {}  # agg_var -> (agg_name, input_var_name)
    if plan.aggregates:
        from .jena_sparql.jena_types import ExprAggregator as _EA2, ExprVar as _EV2
        for agg_var, agg_expr in plan.aggregates.items():
            if isinstance(agg_expr, _EA2):
                agg_name = (agg_expr.name or "").upper()
                input_var = agg_expr.expr.var if isinstance(agg_expr.expr, _EV2) else None
                _agg_info[agg_var] = (agg_name, input_var)
    # Also map extend vars that alias aggregates
    _ext_to_agg: Dict[str, str] = {}  # extend_var -> agg_var
    if plan.extend_exprs:
        for ext_var, ext_expr in plan.extend_exprs.items():
            if isinstance(ext_expr, ExprVar) and ext_expr.var in _agg_info:
                _ext_to_agg[ext_var] = ext_expr.var

    # Collect datatype refs for aggregate input vars from inner subquery
    # Only available when the var is projected (not agg-only in GROUP BY)
    _inner_dt_refs: Dict[str, str] = {}
    agg_only = agg_ref_vars - (proj_vars | order_vars | filter_vars | extend_ref_vars) if plan.group_by else set()
    for var in plan.var_slots:
        if var in inner_text_vars and var not in agg_only:
            _inner_dt_refs[var] = f"{sub_alias}.{var}__datatype"

    def _agg_datatype_sql(agg_var: str) -> str:
        """Infer __datatype for an aggregate result."""
        info = _agg_info.get(agg_var)
        if not info:
            return "NULL"
        agg_name, input_var = info
        if agg_name == "COUNT":
            return f"'{XSD}integer'"
        if agg_name == "AVG":
            return f"'{XSD}decimal'"
        # SUM/MIN/MAX: propagate input datatype if available in outer query
        if input_var:
            dt_ref = _inner_dt_refs.get(input_var)
            if dt_ref:
                return dt_ref
        # SUM is always numeric; MIN/MAX on term_num are also numeric
        if agg_name == "SUM":
            return f"'{XSD}integer'"
        if agg_name in ("MIN", "MAX", "SAMPLE"):
            return f"'{XSD}decimal'"
        return "NULL"

    select_list = plan.select_vars or sorted(proj_vars)
    for var in select_list:
        if var in inner_extend_aliases:
            outer_cols.append(f"{inner_extend_aliases[var]} AS {_q(var)}")
            # Add companion columns for aggregate-backed extends
            agg_var = _ext_to_agg.get(var)
            if agg_var:
                outer_cols.append(f"'L' AS {var}__type")
                outer_cols.append(f"{_agg_datatype_sql(agg_var)} AS {var}__datatype")
            continue
        if var in inner_agg_aliases:
            outer_cols.append(f"{inner_agg_aliases[var]} AS {_q(var)}")
            outer_cols.append(f"'L' AS {var}__type")
            outer_cols.append(f"{_agg_datatype_sql(var)} AS {var}__datatype")
            continue
        if var in extend_sql_map:
            outer_cols.append(f"{extend_sql_map[var]} AS {_q(var)}")
            # Emit companion columns: __uuid, __type, __datatype, __lang
            ext_expr = plan.extend_exprs.get(var) if plan.extend_exprs else None
            if ext_expr and isinstance(ext_expr, ExprVar) and ext_expr.var in plan.var_slots:
                # Simple alias (e.g. ?avg = ?.0) — pass through source metadata
                src = ext_expr.var
                if src in inner_text_vars:
                    outer_cols.append(f"{sub_alias}.{src}__uuid AS {var}__uuid")
                    outer_cols.append(f"{sub_alias}.{src}__type AS {var}__type")
                    outer_cols.append(f"{sub_alias}.{src}__lang AS {var}__lang")
                    outer_cols.append(f"{sub_alias}.{src}__datatype AS {var}__datatype")
                else:
                    outer_cols.append(f"{sub_alias}.{src}__uuid AS {var}__uuid")
                    outer_cols.append(f"t_{src}.term_type AS {var}__type")
                    outer_cols.append(f"t_{src}.lang AS {var}__lang")
                    outer_cols.append(f"t_{src}.datatype_id AS {var}__datatype")
            else:
                # Computed expression — infer metadata from expression type
                inferred_type = _infer_extend_type(ext_expr)
                inferred_dt = _infer_extend_datatype(
                    ext_expr, outer_lang_refs, outer_type_refs,
                    datatype_refs=outer_datatype_refs)
                inferred_lang = _infer_extend_lang(ext_expr, outer_lang_refs)
                outer_cols.append(f"NULL AS {var}__uuid")
                outer_cols.append(f"{inferred_type} AS {var}__type")
                outer_cols.append(f"{inferred_lang} AS {var}__lang")
                outer_cols.append(f"{inferred_dt} AS {var}__datatype")
            continue
        if var in agg_sql_map:
            outer_cols.append(f"{agg_sql_map[var]} AS {_q(var)}")
            continue
        slot = plan.var_slots.get(var)
        if not slot:
            outer_cols.append(f"NULL AS {_q(var)}")
            outer_cols.append(f"NULL AS {var}__uuid")
            outer_cols.append(f"NULL AS {var}__type")
            continue

        if var in inner_text_vars:
            # Text already resolved in inner query
            outer_cols.append(f"{sub_alias}.{var}__text AS {_q(var)}")
            outer_cols.append(f"{sub_alias}.{var}__type AS {var}__type")
            outer_cols.append(f"{sub_alias}.{var}__lang AS {var}__lang")
            outer_cols.append(f"{sub_alias}.{var}__datatype AS {var}__datatype")
        else:
            # Need outer term JOIN for text + type
            t_alias = f"t_{var}"
            outer_joins.append(
                f"JOIN {term_table} AS {t_alias} "
                f"ON {sub_alias}.{var}__uuid = {t_alias}.term_uuid"
            )
            outer_cols.append(f"{t_alias}.term_text AS {_q(var)}")
            outer_cols.append(f"{t_alias}.term_type AS {var}__type")
            outer_cols.append(f"{t_alias}.lang AS {var}__lang")
            outer_cols.append(f"{t_alias}.datatype_id AS {var}__datatype")
        # Always include UUID from inner subquery
        outer_cols.append(f"{sub_alias}.{var}__uuid AS {var}__uuid")

    if not outer_cols:
        outer_cols = ["1"]

    outer_parts = [f"SELECT {', '.join(outer_cols)}"]
    outer_parts.append(f"FROM ({inner_sql}) AS {sub_alias}")
    outer_parts.extend(outer_joins)

    # Apply deferred filters (those referencing EXTEND vars) on the outer query
    if deferred_filter_exprs and plan.extend_exprs:
        # Add extend expressions to outer refs so deferred filters can inline them
        deferred_text_refs = dict(outer_text_refs)
        deferred_type_refs = dict(outer_type_refs)
        deferred_lang_refs = dict(outer_lang_refs)
        deferred_uuid_refs = dict(outer_uuid_refs)
        for ext_var, ext_sql in extend_sql_map.items():
            deferred_text_refs[ext_var] = ext_sql
            ext_expr = plan.extend_exprs.get(ext_var)
            inferred_type = _infer_extend_type(ext_expr)
            deferred_type_refs[ext_var] = inferred_type

        deferred_num_refs = dict(outer_num_refs)
        deferred_datatype_refs = dict(outer_datatype_refs)
        deferred_where_parts = []
        for expr in deferred_filter_exprs:
            sql_expr = _resolve_extend_for_outer(
                expr, plan, deferred_text_refs,
                outer_lang_refs=deferred_lang_refs,
                outer_type_refs=deferred_type_refs,
                outer_uuid_refs=deferred_uuid_refs,
                outer_num_refs=deferred_num_refs,
                outer_datatype_refs=deferred_datatype_refs,
            )
            if sql_expr:
                deferred_where_parts.append(sql_expr)
        if deferred_where_parts:
            outer_parts.append("WHERE " + " AND ".join(deferred_where_parts))

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

    quad_tables = [t for t in plan.tables if t.kind in ("quad", "edge_mv", "frame_entity_mv")]

    # Collect vars referenced by non-COUNT aggregates — they need term JOINs
    from .jena_sparql.jena_types import ExprAggregator as _EA, ExprVar as _EV
    agg_term_vars = set()
    if plan.aggregates:
        for _av, _ae in plan.aggregates.items():
            if isinstance(_ae, _EA) and (_ae.name or "").upper() != "COUNT":
                if isinstance(_ae.expr, _EV) and _ae.expr.var in plan.var_slots:
                    agg_term_vars.add(_ae.expr.var)

    # Build agg info: agg_var -> (agg_name, input_var, term_alias)
    _agg_info_a: Dict[str, tuple] = {}
    _ext_to_agg_a: Dict[str, str] = {}
    if plan.aggregates:
        for _av2, _ae2 in plan.aggregates.items():
            if isinstance(_ae2, _EA):
                aname = (_ae2.name or "").upper()
                ivar = _ae2.expr.var if isinstance(_ae2.expr, _EV) and _ae2.expr.var in plan.var_slots else None
                # Find the term table alias for the input var
                talias = None
                if ivar:
                    slot = plan.var_slots.get(ivar)
                    if slot and slot.term_ref_id:
                        tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
                        if tt:
                            talias = tt.alias
                _agg_info_a[_av2] = (aname, ivar, talias)
    if plan.extend_exprs:
        for _ev, _ee in plan.extend_exprs.items():
            if isinstance(_ee, _EV) and _ee.var in _agg_info_a:
                _ext_to_agg_a[_ev] = _ee.var

    def _agg_dt_sql_a(agg_var: str) -> str:
        info = _agg_info_a.get(agg_var)
        if not info:
            return "NULL"
        aname, ivar, talias = info
        if aname == "COUNT":
            return f"'{XSD}integer'"
        if aname == "AVG":
            return f"'{XSD}decimal'"
        # SUM/MIN/MAX/SAMPLE: propagate from input's datatype via sub-aggregate
        if talias:
            return f"MIN({talias}.datatype_id)"
        return "NULL"

    proj_cols = []
    for var in (plan.select_vars or []):
        if var in extend_sql_map:
            proj_cols.append(f"{extend_sql_map[var]} AS {_q(var)}")
            agg_var = _ext_to_agg_a.get(var)
            if agg_var:
                proj_cols.append(f"'L' AS {var}__type")
                proj_cols.append(f"{_agg_dt_sql_a(agg_var)} AS {var}__datatype")
        elif var in agg_sql_map:
            proj_cols.append(f"{agg_sql_map[var]} AS {_q(var)}")
            proj_cols.append(f"'L' AS {var}__type")
            proj_cols.append(f"{_agg_dt_sql_a(var)} AS {var}__datatype")
        else:
            proj_cols.append(f"NULL AS {_q(var)}")

    if not proj_cols:
        proj_cols = ["1"]

    parts = [f"SELECT {', '.join(proj_cols)}"]
    # Partition constraints into per-table ON clauses vs WHERE
    # Reorder tables so every JOIN references an already-placed table.
    if quad_tables and plan.tagged_constraints:
        ordered, on_map, where_parts = _reorder_joins(quad_tables, plan.tagged_constraints)
        ordered, on_map, where_parts = _apply_semijoin_pushdown(
            ordered, on_map, where_parts, plan)

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

    # Add term JOINs for non-COUNT aggregate vars (with term_num pre-cast)
    from .jena_sql_expressions import _NUMERIC_DATATYPES_V1
    _num_ids = _dt_ids_for_uris(_NUMERIC_DATATYPES_V1)
    for var in agg_term_vars:
        slot = plan.var_slots.get(var)
        if slot and slot.term_ref_id:
            tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
            if tt and slot.positions:
                q_alias, uuid_col = slot.positions[0]
                parts.append(
                    f"JOIN (SELECT term_uuid, term_text, term_type, lang, datatype_id, "
                    f"CASE WHEN datatype_id IN ({_num_ids}) "
                    f"THEN CAST(term_text AS NUMERIC) END AS term_num "
                    f"FROM {term_table}) AS {tt.alias} "
                    f"ON {q_alias}.{uuid_col} = {tt.alias}.term_uuid"
                )

    if plan.filter_exprs:
        from .jena_sparql.jena_types import ExprExists as _EE
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
        gb_cols = []
        for gv in plan.group_by:
            slot = plan.var_slots.get(gv)
            if slot and slot.positions:
                q_alias, uuid_col = slot.positions[0]
                gb_cols.append(f"{q_alias}.{uuid_col}")
            else:
                gb_cols.append(gv)
        parts.append("GROUP BY " + ", ".join(gb_cols))

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

    # FROM: first quad table
    quad_tables = [t for t in plan.tables if t.kind in ("quad", "edge_mv", "frame_entity_mv")]
    term_tables = [t for t in plan.tables if t.kind == "term"
                   and t.ref_id not in skip_term_refs]

    # Reorder joins and apply semi-join pushdown BEFORE building select_cols,
    # because pushdown may update VarSlot uuid_col references.
    _ordered = _on_map = _first_conds = None
    if quad_tables and plan.tagged_constraints:
        _ordered, _on_map, _first_conds = _reorder_joins(quad_tables, plan.tagged_constraints)
        _ordered, _on_map, _first_conds = _apply_semijoin_pushdown(
            _ordered, _on_map, _first_conds, plan)

    # Build named columns for active var_slots (after pushdown rewrites)
    select_cols = []
    for var, slot in active_vars.items():
        if slot.text_col:
            select_cols.append(f"{slot.text_col} AS {var}")
        if slot.uuid_col:
            select_cols.append(f"{slot.uuid_col} AS {var}__uuid")
        if slot.type_col:
            select_cols.append(f"{slot.type_col} AS {var}__type")
        # Add lang/datatype from the term table
        if slot.text_col and "." in slot.text_col:
            t_alias = slot.text_col.rsplit(".", 1)[0]
            select_cols.append(f"{t_alias}.lang AS {var}__lang")
            select_cols.append(f"{t_alias}.datatype_id AS {var}__datatype")

    if not select_cols:
        select_cols = ["1"]

    parts = [f"SELECT {', '.join(select_cols)}"]

    # Emit FROM / JOIN using pre-computed ordered tables
    if _ordered is not None:
        ordered, on_map, first_conds = _ordered, _on_map, _first_conds

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

    # Determine which vars have companion columns (from triple patterns, not BIND)
    left_child_slots = plan.children[0].var_slots if plan.children else {}
    right_child_slots = plan.children[1].var_slots if len(plan.children) > 1 else {}
    def _has_companions(v, is_left):
        slots = left_child_slots if is_left else right_child_slots
        slot = slots.get(v)
        return slot is not None and slot.term_ref_id is not None

    # SELECT columns from both sides
    all_vars = left_vars | right_vars
    select_cols = []
    for v in sorted(all_vars):
        is_left = v in left_vars
        src = l_alias if is_left else r_alias
        select_cols.append(f"{src}.{v} AS {v}")
        if _has_companions(v, is_left):
            select_cols.append(f"{src}.{v}__uuid AS {v}__uuid")
            select_cols.append(f"{src}.{v}__type AS {v}__type")
            select_cols.append(f"{src}.{v}__lang AS {v}__lang")
            select_cols.append(f"{src}.{v}__datatype AS {v}__datatype")
        else:
            select_cols.append(f"NULL AS {v}__uuid")
            # Check if this is a BIND/extend var with a known datatype
            child = plan.children[0] if is_left else plan.children[1]
            ext_expr = (child.extend_exprs or {}).get(v)
            if ext_expr:
                inferred_type = _infer_extend_type(ext_expr)
                inferred_dt = _infer_extend_datatype(ext_expr, {}, {})
                select_cols.append(f"{inferred_type} AS {v}__type")
                select_cols.append(f"NULL AS {v}__lang")
                select_cols.append(f"{inferred_dt} AS {v}__datatype")
            else:
                select_cols.append(f"'L' AS {v}__type")
                select_cols.append(f"NULL AS {v}__lang")
                select_cols.append(f"NULL AS {v}__datatype")

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
            qv = _q(v)
            if v in child_vars:
                cols.append(f"{qv}")
                cols.append(f"{v}__uuid")
                cols.append(f"{v}__type")
            else:
                cols.append(f"NULL AS {qv}")
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
    """Emit SPARQL MINUS using NOT EXISTS on common variables.

    SPARQL MINUS semantics (from Jena QueryIterMinus):
    - Compute commonVars = intersection of visible vars from left and right
    - A left row is excluded iff there exists a right row where:
      (a) at least one common variable is bound in BOTH rows, AND
      (b) all shared bound variables have compatible (equal) values
    - If commonVars is empty, MINUS never excludes anything (return left as-is)

    SQL EXCEPT is WRONG for this because it compares ALL columns including
    padded NULLs, and doesn't handle the "shared domain" check.
    """
    meta = plan._minus_meta  # type: ignore[attr-defined]
    m_alias = meta["m_alias"]
    left_vars = meta["left_vars"]
    right_vars = meta["right_vars"]

    left_sql = emit(plan.children[0], space_id)
    right_sql = emit(plan.children[1], space_id)

    common_vars = sorted(left_vars & right_vars)

    # If no common variables, MINUS never excludes — return left unchanged
    if not common_vars:
        return f"SELECT * FROM ({left_sql}) AS {m_alias}"

    # Build NOT EXISTS correlated subquery on common variables
    # For each common var, match when both are non-NULL and equal
    # The "shared domain" check: at least one common var must be bound in both
    match_clauses = []
    for v in common_vars:
        # IS NOT DISTINCT FROM handles NULL=NULL correctly, but we need
        # the SPARQL semantics: only match when both are bound (non-NULL)
        match_clauses.append(
            f"(_left.{_q(v)} IS NOT NULL AND _right.{_q(v)} IS NOT NULL "
            f"AND _left.{_q(v)} = _right.{_q(v)})"
        )

    # A right row is "compatible with shared domain" if ALL common vars
    # that are bound in both sides are equal. We use:
    # - For each common var: either both NULL, or both non-NULL and equal
    # - AND at least one common var is bound in both sides
    compat_clauses = []
    has_shared = []
    for v in common_vars:
        compat_clauses.append(
            f"(_left.{_q(v)} IS NULL OR _right.{_q(v)} IS NULL "
            f"OR _left.{_q(v)} = _right.{_q(v)})"
        )
        has_shared.append(
            f"(_left.{_q(v)} IS NOT NULL AND _right.{_q(v)} IS NOT NULL)"
        )

    where = " AND ".join(compat_clauses)
    shared_domain = " OR ".join(has_shared)

    minus_sql = (
        f"SELECT _left.* FROM ({left_sql}) AS _left "
        f"WHERE NOT EXISTS ("
        f"SELECT 1 FROM ({right_sql}) AS _right "
        f"WHERE ({shared_domain}) AND {where}"
        f")"
    )
    return f"SELECT * FROM ({minus_sql}) AS {m_alias}"


# ===========================================================================
# TABLE (VALUES) emitter
# ===========================================================================

def _emit_table(plan: RelationPlan) -> str:
    """Emit VALUES as UNION ALL of SELECT constants.

    Special case: OpTable(vars=[], rows=[{}]) from empty WHERE {}
    produces a single row with no columns — used as a base for EXTEND.
    """
    if not plan.values_rows:
        return "SELECT 1 WHERE FALSE"
    parts = []
    for row in plan.values_rows:
        cols = []
        for var in (plan.values_vars or []):
            val = row.get(var)
            if val is None:
                cols.append(f"NULL AS {_q(var)}")
            elif isinstance(val, URINode):
                cols.append(f"'{_esc(val.value)}' AS {_q(var)}")
            elif isinstance(val, LiteralNode):
                cols.append(f"'{_esc(val.value)}' AS {_q(var)}")
            else:
                cols.append(f"NULL AS {_q(var)}")
        if not cols:
            # Empty WHERE {} — just produce a single row
            parts.append("SELECT 1 AS _dummy")
        else:
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

    # Substitute inner constants — the outer generate_sql only handles
    # the outer aliases' constants, so inner EXISTS constants need their
    # own substitution (using direct term table scalar subqueries).
    from .jena_sql_helpers import substitute_constants as _subst_const
    inner_sql = _subst_const(inner_sql, inner_aliases)

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
                               outer_uuid_refs: Optional[Dict[str, str]] = None,
                               outer_num_refs: Optional[Dict[str, str]] = None,
                               outer_datatype_refs: Optional[Dict[str, str]] = None) -> str:
    """Resolve an extend expression using outer query column references.

    Instead of resolving variables to inner plan term aliases (e.g. t1.term_text),
    this substitutes them with the outer query's references (e.g. sub.date__text).
    For arithmetic operators, ExprVar args resolve to pre-cast __num columns.
    """
    from .jena_sparql.jena_types import ExprVar as EV, ExprValue as EVa, ExprFunction as EF
    from .jena_sql_expressions import _FUNC_MAP

    _recurse = lambda a: _resolve_extend_for_outer(
        a, plan, outer_text_refs,
        outer_lang_refs=outer_lang_refs, outer_type_refs=outer_type_refs,
        outer_uuid_refs=outer_uuid_refs, outer_num_refs=outer_num_refs,
        outer_datatype_refs=outer_datatype_refs,
    )

    if isinstance(expr, EV):
        if expr.var in outer_text_refs:
            return outer_text_refs[expr.var]
        return _expr_to_sql_str(expr, plan)

    if isinstance(expr, EVa):
        return _expr_to_sql_str(expr, plan)

    if isinstance(expr, EF):
        fname = (expr.name or "").lower()
        eargs = expr.args or []

        # Arithmetic: resolve ExprVar args to pre-cast __num columns directly
        if fname in ("add", "subtract", "multiply", "divide") and len(eargs) == 2:
            op = _FUNC_MAP[fname]
            num_args = []
            for a in eargs:
                if isinstance(a, EV) and (outer_num_refs or {}).get(a.var):
                    num_args.append(outer_num_refs[a.var])
                elif isinstance(a, EVa):
                    num_args.append(_expr_to_sql_str(a, plan))
                else:
                    # Non-variable arg (e.g. str(?x)) — result may be text,
                    # Safe cast: returns NULL for non-numeric strings
                    inner = _recurse(a)
                    num_args.append(
                        f"CASE WHEN CAST(({inner}) AS TEXT) ~ '^-?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?$'"
                        f" THEN CAST(({inner}) AS NUMERIC) ELSE NULL END")
            if fname == "divide":
                return f"({num_args[0]} / NULLIF({num_args[1]}, 0))"
            return f"({num_args[0]} {op} {num_args[1]})"

        # Math functions: resolve ExprVar arg to pre-cast __num column
        if fname in ("abs", "ceil", "floor", "round") and len(eargs) == 1:
            a = eargs[0]
            if isinstance(a, EV) and (outer_num_refs or {}).get(a.var):
                return f"{fname.upper()}({outer_num_refs[a.var]})"
            return f"{fname.upper()}({_recurse(a)})"

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

        # STRLANG / STRDT type guards: require simple literal input
        # (no lang tag, no non-xsd:string datatype)
        if fname in ("strlang", "strdt") and len(eargs) >= 2 and isinstance(eargs[0], EV):
            var_name = eargs[0].var
            lang_ref = (outer_lang_refs or {}).get(var_name, "NULL")
            dt_ref = (outer_datatype_refs or {}).get(var_name, "NULL")
            text_ref = (outer_text_refs or {}).get(var_name, "NULL")
            xsd_str = "http://www.w3.org/2001/XMLSchema#string"
            guard = (f"({lang_ref} IS NULL OR {lang_ref} = '')"
                     f" AND ({dt_ref} IS NULL OR {dt_ref} = '' OR {dt_ref} = '{xsd_str}')")
            return f"CASE WHEN {guard} THEN {text_ref} ELSE NULL END"

        args_sql = [_recurse(a) for a in eargs]
        # Delegate to the standard function translator with pre-resolved args
        return _func_with_resolved_args(expr, args_sql, plan)

    return _expr_to_sql_str(expr, plan)


def _func_with_resolved_args(expr, args_sql: List[str], plan_or_ctx) -> str:
    """Translate an ExprFunction using pre-resolved argument SQL strings."""
    from .jena_sparql.jena_types import ExprFunction as EF
    from .jena_sql_expressions import (
        _FUNC_MAP, _apply_typed_casts, _NUMERIC_DTYPES, _DATETIME_DTYPES, _DATE_DTYPES,
    )

    name = (expr.name or "").lower()
    args = expr.args or []

    if name in _FUNC_MAP and len(args_sql) == 2:
        l, r = args_sql
        if name in ("add", "subtract", "multiply", "divide"):
            # Arithmetic: args already resolved to __num by _resolve_extend_for_outer
            if name == "divide":
                return f"({l} / NULLIF({r}, 0))"
        elif name in ("gt", "lt", "ge", "le", "eq", "ne"):
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

    if name == "tz" and len(args_sql) == 1:
        # TZ() returns the timezone string (e.g. 'Z', '-08:00') or '' if none
        return (
            f"(CASE WHEN CAST({args_sql[0]} AS TEXT) ~ '([+-]\\d{{2}}:\\d{{2}}|Z)$' "
            f"THEN REGEXP_REPLACE(CAST({args_sql[0]} AS TEXT), "
            f"'^.*([+-]\\d{{2}}:\\d{{2}}|Z)$', '\\1') "
            f"ELSE '' END)"
        )

    if name == "timezone" and len(args_sql) == 1:
        # TIMEZONE() returns xsd:dayTimeDuration; NULL (unbound) if no TZ
        # Format: sign + 'PT' + hours(no leading zero) + 'H' + optional minutes + 'M'
        _t = f"CAST({args_sql[0]} AS TEXT)"
        _sign = f"REGEXP_REPLACE({_t}, '^.*([+-])\\d{{2}}:\\d{{2}}$', '\\1')"
        _hrs = f"CAST(REGEXP_REPLACE({_t}, '^.*[+-](\\d{{2}}):\\d{{2}}$', '\\1') AS INTEGER)"
        _mins = f"CAST(REGEXP_REPLACE({_t}, '^.*[+-]\\d{{2}}:(\\d{{2}})$', '\\1') AS INTEGER)"
        return (
            f"(CASE "
            f"WHEN {_t} ~ 'Z$' THEN 'PT0S' "
            f"WHEN {_t} ~ '[+-]\\d{{2}}:\\d{{2}}$' THEN "
            f"CONCAT({_sign}, 'PT', {_hrs}, 'H', "
            f"CASE WHEN {_mins} > 0 THEN CONCAT({_mins}, 'M') ELSE '' END) "
            f"ELSE NULL END)"
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

    # ABS / CEIL / FLOOR / ROUND — args already NUMERIC via __num pre-cast
    if name == "abs" and len(args_sql) == 1:
        return f"ABS({args_sql[0]})"
    if name == "ceil" and len(args_sql) == 1:
        return f"CEIL({args_sql[0]})"
    if name == "floor" and len(args_sql) == 1:
        return f"FLOOR({args_sql[0]})"
    if name == "round" and len(args_sql) == 1:
        return f"ROUND({args_sql[0]})"

    # STRAFTER / STRBEFORE — no native PG functions, use SUBSTRING
    if name == "strafter" and len(args_sql) == 2:
        return (
            f"CASE WHEN POSITION({args_sql[1]} IN {args_sql[0]}) > 0 "
            f"THEN SUBSTRING({args_sql[0]} FROM POSITION({args_sql[1]} IN {args_sql[0]}) + LENGTH({args_sql[1]})) "
            f"ELSE '' END"
        )
    if name == "strbefore" and len(args_sql) == 2:
        return (
            f"CASE WHEN POSITION({args_sql[1]} IN {args_sql[0]}) > 0 "
            f"THEN SUBSTRING({args_sql[0]} FROM 1 FOR POSITION({args_sql[1]} IN {args_sql[0]}) - 1) "
            f"ELSE '' END"
        )

    # SUBSTR / SUBSTRING
    if name in ("substr", "substring"):
        if len(args_sql) >= 3:
            return f"SUBSTRING({args_sql[0]}, {args_sql[1]}, {args_sql[2]})"
        if len(args_sql) >= 2:
            return f"SUBSTRING({args_sql[0]}, {args_sql[1]})"

    # REPLACE
    if name == "replace" and len(args_sql) >= 3:
        from .jena_sql_expressions import sparql_replace_flags_to_pg
        import re as _re
        flags_sql = args_sql[3] if len(args_sql) >= 4 else None
        pg_flags = sparql_replace_flags_to_pg(flags_sql)
        # SPARQL uses $N for backreferences; PostgreSQL uses \N
        rep_sql = _re.sub(r'\$(\d)', r'\\\1', args_sql[2])
        return f"REGEXP_REPLACE({args_sql[0]}, {args_sql[1]}, {rep_sql}, '{pg_flags}')"

    # STRSTARTS / STRENDS
    if name == "strstarts" and len(args_sql) == 2:
        return f"({args_sql[0]} LIKE {args_sql[1]} || '%%')"
    if name == "strends" and len(args_sql) == 2:
        return f"({args_sql[0]} LIKE '%%' || {args_sql[1]})"

    # REGEX
    if name == "regex" and len(args_sql) >= 2:
        from .jena_sql_expressions import sparql_regex_to_pg
        flags = args_sql[2] if len(args_sql) >= 3 else None
        return sparql_regex_to_pg(args_sql[0], args_sql[1], flags)

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
    from .jena_sparql.jena_types import ExprVar as EV, ExprValue as EVa, ExprFunction as EF

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
            if name == "divide":
                return f"({args_sql[0]} / NULLIF({args_sql[1]}, 0))"
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

def _agg_expr_to_inner_sql(expr, plan: RelationPlan,
                           inner_text_vars: Optional[set] = None) -> str:
    """Translate an aggregate expression for the inner query of _emit_bgp_optimized.

    For COUNT, resolves to UUID columns (always available).
    For SUM/AVG/MIN/MAX/GROUP_CONCAT, resolves to term_text columns
    (via inner term JOINs added by the caller) so values can be cast/compared.
    """
    from .jena_sparql.jena_types import ExprAggregator, ExprVar as EV
    if not isinstance(expr, ExprAggregator):
        return _expr_to_sql_str(expr, plan)

    name = (expr.name or "").upper()
    needs_text = name not in ("COUNT",)

    # Resolve inner expression
    if expr.expr is None:
        inner = "*"
    elif isinstance(expr.expr, EV):
        var_name = expr.expr.var
        slot = plan.var_slots.get(var_name)
        if needs_text and inner_text_vars and var_name in inner_text_vars:
            # Use term_text column from inner term JOIN
            if slot and slot.term_ref_id:
                tt = next((t for t in plan.tables if t.ref_id == slot.term_ref_id), None)
                if tt:
                    inner = f"{tt.alias}.term_text"
                else:
                    inner = f"{var_name}__text"
            else:
                inner = f"{var_name}__text"
        elif slot and slot.positions:
            q_alias, uuid_col = slot.positions[0]
            inner = f"{q_alias}.{uuid_col}"
        else:
            inner = _expr_to_sql_str(expr.expr, plan)
    else:
        inner = _expr_to_sql_str(expr.expr, plan)

    if name == "COUNT":
        if expr.distinct:
            return f"COALESCE(COUNT(DISTINCT {inner}), 0)"
        return f"COALESCE(COUNT({inner}), 0)"
    elif name == "SUM":
        # Use pre-cast term_num column for numeric aggregation
        if ".term_text" in inner:
            num_inner = inner.replace(".term_text", ".term_num")
        elif "__text" in inner:
            num_inner = inner.replace("__text", "__num")
        else:
            num_inner = f"CAST({inner} AS NUMERIC)"
        dist = "DISTINCT " if expr.distinct else ""
        return f"COALESCE(SUM({dist}{num_inner}), 0)"
    elif name == "AVG":
        if ".term_text" in inner:
            num_inner = inner.replace(".term_text", ".term_num")
        elif "__text" in inner:
            num_inner = inner.replace("__text", "__num")
        else:
            num_inner = f"CAST({inner} AS NUMERIC)"
        dist = "DISTINCT " if expr.distinct else ""
        return f"COALESCE(AVG({dist}{num_inner}), 0)"
    elif name in ("MIN", "MAX"):
        # Use numeric column for proper numeric comparison
        if ".term_text" in inner:
            num_inner = inner.replace(".term_text", ".term_num")
        elif "__text" in inner:
            num_inner = inner.replace("__text", "__num")
        else:
            num_inner = inner
        dist = "DISTINCT " if expr.distinct else ""
        return f"{name}({dist}{num_inner})"
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
            select_cols.append(f"{t_alias}.lang AS {node.name}__lang")
            select_cols.append(f"{t_alias}.datatype_id AS {node.name}__datatype")

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
