"""Handler for KIND_PATH — Property path emission.

Produces SQL using WITH RECURSIVE CTEs for property path patterns.
The CTE always produces (start_uuid, end_uuid, ctx_uuid) triples —
ctx_uuid is a standard column carried through every path variant, not
a conditional add-on.  This treats context_uuid the same as
subject_uuid / object_uuid.

When inside ``GRAPH ?g``, the ``same_graph`` flag enforces that all
steps in a sequence / recursion share the same ctx_uuid, and the outer
SELECT binds ``?g`` via a term-table JOIN — identical to how subject
and object variables are bound.

Supports: PathLink, PathInverse, PathSeq, PathAlt, PathOneOrMore,
PathZeroOrMore, PathZeroOrOne, PathNegPropSet.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from ..jena_sparql.jena_types import (
    VarNode, URINode,
    PathLink, PathInverse, PathSeq, PathAlt,
    PathOneOrMore, PathZeroOrMore, PathZeroOrOne,
    PathNegPropSet, PathExpr,
)
from .ir import PlanV2
from .emit_context import EmitContext
from .collect import _esc

logger = logging.getLogger(__name__)

MAX_PATH_DEPTH = 100  # cycle prevention for recursive CTEs
_cte_counter = 0

def _next_cte_name(prefix: str) -> str:
    """Generate a unique CTE name to avoid collisions in nested paths."""
    global _cte_counter
    _cte_counter += 1
    return f"{prefix}_{_cte_counter}"


def _merge_ctes(inner_cte: str, new_body: str) -> str:
    """Merge an inner CTE prefix with a new recursive CTE body.

    If inner_cte is empty, wraps new_body in WITH RECURSIVE.
    If inner_cte exists, strips its WITH RECURSIVE prefix and combines
    both CTE definitions into a single WITH RECURSIVE block.
    """
    if not inner_cte:
        return f"WITH RECURSIVE {new_body}"
    inner_body = inner_cte
    if inner_body.startswith("WITH RECURSIVE "):
        inner_body = inner_body[len("WITH RECURSIVE "):]
    return f"WITH RECURSIVE {inner_body},\n{new_body}"


def emit_path(plan: PlanV2, ctx: EmitContext) -> str:
    """Emit a property path pattern as SQL using WITH RECURSIVE CTEs."""
    meta = plan.path_meta
    if meta is None:
        raise ValueError("path plan has no path_meta")

    path_expr = meta["path"]
    subject = meta["subject"]
    obj = meta["object"]
    quad_table = meta["quad_table"]
    term_table = meta["term_table"]
    graph_uri = meta.get("graph_uri")
    cte_alias = meta["cte_alias"]
    graph_var = meta.get("graph_var")

    from .collect import GRAPH_VAR_SCOPE

    # ── Build graph_clause (WHERE filter on every leaf quad scan) ──
    graph_clauses = []

    # 1. Lock — always applied (scoping / security)
    if ctx.aliases.graph_lock_uri:
        graph_clauses.append(
            f"q.context_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(ctx.aliases.graph_lock_uri)}' AND term_type = 'U' LIMIT 1)"
        )

    # 2. GRAPH <uri> — explicit named graph constraint
    if graph_uri and graph_uri != GRAPH_VAR_SCOPE:
        graph_clauses.append(
            f"q.context_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(graph_uri)}' AND term_type = 'U' LIMIT 1)"
        )

    # 3. Default graph — only when NOT inside a GRAPH clause
    if ctx.aliases.default_graph and graph_uri is None:
        graph_clauses.append(
            f"q.context_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(ctx.aliases.default_graph)}' AND term_type = 'U' LIMIT 1)"
        )

    # Rule 3: IS DISTINCT FROM for negative comparisons (§10.5).
    # GRAPH ?g — exclude default graph (named graphs only).
    # Use IS DISTINCT FROM (not !=) so NULL from a missing default graph
    # term is treated as "no exclusion" rather than filtering all rows.
    if ctx.aliases.default_graph and graph_uri == GRAPH_VAR_SCOPE:
        graph_clauses.append(
            f"q.context_uuid IS DISTINCT FROM (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(ctx.aliases.default_graph)}' AND term_type = 'U' LIMIT 1)"
        )

    graph_clause = ""
    if graph_clauses:
        graph_clause = " AND " + " AND ".join(graph_clauses)

    # same_graph: enforce cross-step ctx_uuid consistency inside GRAPH scopes
    same_graph = graph_uri is not None  # True for GRAPH <uri> and GRAPH ?g

    # ── Generate path CTE — always (start_uuid, end_uuid, ctx_uuid) ──
    cte_parts, path_select = _path_to_sql(
        path_expr, quad_table, term_table, graph_clause, cte_alias,
        same_graph=same_graph,
    )

    # ── Subject / object constraints ──
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

    # ── Outer SELECT: bind variables via term-table JOINs ──
    # Same pattern for subject, object, AND graph variable.
    from .sql_type_generation import ColumnInfo

    from .emit_bgp import _NUMERIC_DATATYPES, _BOOLEAN_DT, _DATETIME_DATATYPES
    _NUM_RE = r"'^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$'"
    _DT_RE = r"'^\d{4}-'"

    select_cols = []
    term_joins = []

    # Bind subject, object, and graph variable uniformly
    bindings = [(subject, "start_uuid"), (obj, "end_uuid")]
    if graph_var:
        bindings.append((VarNode(name=graph_var), "ctx_uuid"))

    for node, uuid_col in bindings:
        if isinstance(node, VarNode):
            sn = ctx.types.allocate(node.name)
            t_alias = f"t_{sn}"
            term_joins.append(
                f"JOIN {term_table} AS {t_alias} "
                f"ON {cte_alias}.{uuid_col} = {t_alias}.term_uuid"
            )
            select_cols.append(f"{t_alias}.term_text AS {sn}")
            select_cols.append(f"{t_alias}.term_type AS {sn}__type")
            select_cols.append(f"{cte_alias}.{uuid_col} AS {sn}__uuid")
            select_cols.append(f"{t_alias}.lang AS {sn}__lang")
            _dt_case = ctx.dt_case_expr(t_alias)
            _num_ids = ctx.dt_ids_for_uris(_NUMERIC_DATATYPES)
            _bool_id = ctx.dt_ids_for_uris([_BOOLEAN_DT])
            _dt_ids = ctx.dt_ids_for_uris(_DATETIME_DATATYPES)
            select_cols.append(f"({_dt_case}) AS {sn}__datatype")
            select_cols.append(
                f"CASE WHEN {t_alias}.datatype_id IN ({_num_ids})"
                f" AND {t_alias}.term_text ~ {_NUM_RE}"
                f" THEN CAST({t_alias}.term_text AS NUMERIC) END AS {sn}__num"
            )
            select_cols.append(
                f"CASE WHEN {t_alias}.datatype_id = {_bool_id}"
                f" AND {t_alias}.term_text IN ('true','false','1','0')"
                f" THEN ({t_alias}.term_text = 'true') END AS {sn}__bool"
            )
            select_cols.append(
                f"CASE WHEN {t_alias}.datatype_id IN ({_dt_ids})"
                f" AND {t_alias}.term_text ~ {_DT_RE}"
                f" THEN CAST({t_alias}.term_text AS TIMESTAMP) END AS {sn}__dt"
            )
            info = ColumnInfo.simple_output(node.name, sn, from_triple=True)
            ctx.types._columns[node.name] = info

    if not select_cols:
        select_cols = ["1"]

    # ── Assemble ──
    parts = []
    if cte_parts:
        parts.append(cte_parts)
    parts.append(f"SELECT {', '.join(select_cols)}")
    parts.append(f"FROM ({path_select}) AS {cte_alias}")
    parts.extend(term_joins)
    if where_clause:
        parts.append(where_clause)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# _path_to_sql — converts PathExpr tree to SQL
#
# Always produces (start_uuid, end_uuid, ctx_uuid).
# ctx_uuid = q.context_uuid at the leaf level, propagated through every
# combinator.  When same_graph is True, sequence JOINs and recursive
# steps enforce lp.ctx_uuid = rp.ctx_uuid so the entire path resolves
# within a single named graph.
# ---------------------------------------------------------------------------

def _path_to_sql(path: PathExpr, quad_table: str, term_table: str,
                 graph_clause: str, cte_alias: str,
                 same_graph: bool = False) -> Tuple[str, str]:
    """Convert a PathExpr to SQL.

    Returns (cte_prefix, select_sql) where cte_prefix is a WITH RECURSIVE
    clause (or empty string) and select_sql is a SELECT producing
    (start_uuid, end_uuid, ctx_uuid).

    When same_graph is True, multi-step paths (PathSeq, recursive) enforce
    that all steps share the same ctx_uuid.
    """

    # Simple link: single quad scan
    if isinstance(path, PathLink):
        pred_filter = (
            f"predicate_uuid = (SELECT term_uuid FROM {term_table} "
            f"WHERE term_text = '{_esc(path.uri)}' AND term_type = 'U' LIMIT 1)"
        )
        sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid, "
            f"q.context_uuid AS ctx_uuid "
            f"FROM {quad_table} q "
            f"WHERE {pred_filter}{graph_clause}"
        )
        return "", sql

    # Inverse: swap start/end, keep ctx_uuid
    if isinstance(path, PathInverse):
        cte, inner_sql = _path_to_sql(path.sub, quad_table, term_table,
                                       graph_clause, cte_alias, same_graph)
        sql = (
            f"SELECT inv.end_uuid AS start_uuid, inv.start_uuid AS end_uuid, "
            f"inv.ctx_uuid "
            f"FROM ({inner_sql}) AS inv"
        )
        return cte, sql

    # Alternative: UNION (both branches carry ctx_uuid)
    if isinstance(path, PathAlt):
        cte_l, sql_l = _path_to_sql(path.left, quad_table, term_table,
                                     graph_clause, cte_alias + "_l", same_graph)
        cte_r, sql_r = _path_to_sql(path.right, quad_table, term_table,
                                     graph_clause, cte_alias + "_r", same_graph)
        cte = ""
        if cte_l or cte_r:
            parts = [p for p in [cte_l, cte_r] if p]
            cte = "\n".join(parts)
        sql = f"({sql_l}) UNION ({sql_r})"
        return cte, sql

    # Sequence: JOIN on end→start; enforce same ctx_uuid when same_graph
    if isinstance(path, PathSeq):
        cte_l, sql_l = _path_to_sql(path.left, quad_table, term_table,
                                     graph_clause, cte_alias + "_l", same_graph)
        cte_r, sql_r = _path_to_sql(path.right, quad_table, term_table,
                                     graph_clause, cte_alias + "_r", same_graph)
        cte = ""
        if cte_l or cte_r:
            parts = [p for p in [cte_l, cte_r] if p]
            cte = "\n".join(parts)
        ctx_constraint = " AND lp.ctx_uuid = rp.ctx_uuid" if same_graph else ""
        sql = (
            f"SELECT lp.start_uuid, rp.end_uuid, lp.ctx_uuid "
            f"FROM ({sql_l}) AS lp "
            f"JOIN ({sql_r}) AS rp ON lp.end_uuid = rp.start_uuid{ctx_constraint}"
        )
        return cte, sql

    # One or more (+): WITH RECURSIVE
    if isinstance(path, PathOneOrMore):
        inner_cte, base_sql = _path_to_sql(path.sub, quad_table, term_table,
                                            graph_clause, cte_alias + "_base", same_graph)
        rec_name = _next_cte_name(f"{cte_alias}_rec")
        ctx_rec_constraint = " AND r.ctx_uuid = step.ctx_uuid" if same_graph else ""
        rec_body = (
            f"{rec_name}(start_uuid, end_uuid, depth, ctx_uuid) AS (\n"
            f"  SELECT start_uuid, end_uuid, 1, ctx_uuid FROM ({base_sql}) AS _base\n"
            f"  UNION\n"
            f"  SELECT r.start_uuid, step.end_uuid, r.depth + 1, r.ctx_uuid\n"
            f"  FROM {rec_name} r\n"
            f"  JOIN ({base_sql}) AS step ON r.end_uuid = step.start_uuid{ctx_rec_constraint}\n"
            f"  WHERE r.depth < {MAX_PATH_DEPTH}\n"
            f")"
        )
        cte = _merge_ctes(inner_cte, rec_body)
        sql = f"SELECT DISTINCT start_uuid, end_uuid, ctx_uuid FROM {rec_name}"
        return cte, sql

    # Zero or more (*): WITH RECURSIVE + identity base case
    if isinstance(path, PathZeroOrMore):
        inner_cte, base_sql = _path_to_sql(path.sub, quad_table, term_table,
                                            graph_clause, cte_alias + "_base", same_graph)
        rec_name = _next_cte_name(f"{cte_alias}_rec")
        # Identity: every node connected to itself (within its graph)
        identity_sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.subject_uuid AS end_uuid, "
            f"0, q.context_uuid AS ctx_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''} "
            f"UNION SELECT q.object_uuid, q.object_uuid, "
            f"0, q.context_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''}"
        )
        ctx_rec_constraint = " AND r.ctx_uuid = step.ctx_uuid" if same_graph else ""
        rec_body = (
            f"{rec_name}(start_uuid, end_uuid, depth, ctx_uuid) AS (\n"
            f"  ({identity_sql})\n"
            f"  UNION\n"
            f"  SELECT r.start_uuid, step.end_uuid, r.depth + 1, r.ctx_uuid\n"
            f"  FROM {rec_name} r\n"
            f"  JOIN ({base_sql}) AS step ON r.end_uuid = step.start_uuid{ctx_rec_constraint}\n"
            f"  WHERE r.depth < {MAX_PATH_DEPTH}\n"
            f")"
        )
        cte = _merge_ctes(inner_cte, rec_body)
        sql = f"SELECT DISTINCT start_uuid, end_uuid, ctx_uuid FROM {rec_name}"
        return cte, sql

    # Zero or one (?): identity UNION one step
    if isinstance(path, PathZeroOrOne):
        _, base_sql = _path_to_sql(path.sub, quad_table, term_table,
                                    graph_clause, cte_alias + "_base", same_graph)
        identity_sql = (
            f"SELECT q.subject_uuid AS start_uuid, q.subject_uuid AS end_uuid, "
            f"q.context_uuid AS ctx_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''} "
            f"UNION SELECT q.object_uuid, q.object_uuid, q.context_uuid "
            f"FROM {quad_table} q{' WHERE TRUE' + graph_clause if graph_clause else ''}"
        )
        sql = f"({identity_sql}) UNION ({base_sql})"
        return "", sql

    # Negated property set: all predicates EXCEPT the listed ones
    # ^uri entries are inverse: exclude on object→subject direction
    if isinstance(path, PathNegPropSet):
        fwd_uris = [u for u in path.uris if not u.startswith("^")]
        inv_uris = [u[1:] for u in path.uris if u.startswith("^")]

        parts = []
        if fwd_uris or not inv_uris:
            if fwd_uris:
                excl = " AND ".join(
                    f"q.predicate_uuid != (SELECT term_uuid FROM {term_table} "
                    f"WHERE term_text = '{_esc(u)}' AND term_type = 'U' LIMIT 1)"
                    for u in fwd_uris
                )
                parts.append(
                    f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid, "
                    f"q.context_uuid AS ctx_uuid "
                    f"FROM {quad_table} q WHERE {excl}{graph_clause}"
                )
            else:
                parts.append(
                    f"SELECT q.subject_uuid AS start_uuid, q.object_uuid AS end_uuid, "
                    f"q.context_uuid AS ctx_uuid "
                    f"FROM {quad_table} q"
                    + (f" WHERE TRUE{graph_clause}" if graph_clause else "")
                )
        if inv_uris:
            excl = " AND ".join(
                f"q.predicate_uuid != (SELECT term_uuid FROM {term_table} "
                f"WHERE term_text = '{_esc(u)}' AND term_type = 'U' LIMIT 1)"
                for u in inv_uris
            )
            parts.append(
                f"SELECT q.object_uuid AS start_uuid, q.subject_uuid AS end_uuid, "
                f"q.context_uuid AS ctx_uuid "
                f"FROM {quad_table} q WHERE {excl}{graph_clause}"
            )

        sql = " UNION ".join(f"({p})" for p in parts) if len(parts) > 1 else parts[0]
        return "", sql

    # Fallback
    logger.warning("Unsupported path type: %s", type(path).__name__)
    return "", "SELECT NULL AS start_uuid, NULL AS end_uuid, NULL AS ctx_uuid WHERE FALSE"
