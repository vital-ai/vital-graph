"""
SPARQL Update operations → SQL translation (V2 pipeline).

Self-contained module — all helpers re-implemented here.
No imports from jena_sql_helpers, jena_sql_ir, jena_sql_updates,
or any other jena_sql_*.py V1 module.

Handles INSERT DATA, DELETE DATA, DELETE/INSERT WHERE (UpdateModify),
and graph management operations (CLEAR, DROP, CREATE, COPY, MOVE, ADD).
"""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from ..jena_sparql.jena_types import (
    QuadPattern, URINode, LiteralNode, BNodeNode, VarNode, RDFNode,
    UpdateDataInsert, UpdateDataDelete, UpdateModify, UpdateDeleteWhere,
    UpdateLoad, UpdateClear, UpdateDrop, UpdateCreate, UpdateCopy,
    UpdateMove, UpdateAdd, UpdateOp,
    OpBGP, OpGraph, OpJoin, OpUnion, TriplePattern,
    CompileResult, ParsedQueryMeta,
)

logger = logging.getLogger(__name__)

# Deterministic UUID namespace — must match sparql_sql_space_impl._VITALGRAPH_NS
_VITALGRAPH_NS = _uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def _generate_term_uuid(
    term_text: str, term_type: str,
    lang: Optional[str] = None, datatype_id: Optional[int] = None,
) -> _uuid.UUID:
    """Deterministic UUID v5 for an RDF term — mirrors sparql_sql_space_impl."""
    parts = [term_text, term_type]
    if lang is not None:
        parts.append(f"lang:{lang}")
    if datatype_id is not None:
        parts.append(f"datatype:{datatype_id}")
    return _uuid.uuid5(_VITALGRAPH_NS, "\x00".join(parts))


async def _resolve_datatype_map(
    space_id: str,
    conn=None,
    conn_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Return {datatype_uri: datatype_id} for a space.

    Reuses the generator's datatype cache when possible.
    """
    from .generator import _load_datatype_cache
    id_to_uri = await _load_datatype_cache(space_id, conn_params=conn_params, conn=conn)
    return {uri: did for did, uri in id_to_uri.items()}


async def _ensure_datatype_id(
    space_id: str,
    datatype_uri: str,
    dt_map: Dict[str, int],
    conn=None,
) -> int:
    """Get or create a datatype_id for a URI.  Updates dt_map in place."""
    if datatype_uri in dt_map:
        return dt_map[datatype_uri]
    if conn is None:
        raise RuntimeError(
            f"Cannot create datatype_id for {datatype_uri} without a DB connection")
    dt_table = f"{space_id}_datatype"
    new_id = await conn.fetchval(
        f"INSERT INTO {dt_table} (datatype_uri) VALUES ($1) "
        f"ON CONFLICT (datatype_uri) DO UPDATE SET datatype_uri = EXCLUDED.datatype_uri "
        f"RETURNING datatype_id",
        datatype_uri,
    )
    dt_map[datatype_uri] = new_id
    # Invalidate generator cache so next load picks up the new entry
    from .generator import invalidate_datatype_cache
    invalidate_datatype_cache(space_id)
    return new_id


def _node_datatype_uri(node: RDFNode) -> Optional[str]:
    """Return the datatype URI for a LiteralNode, or None."""
    if isinstance(node, LiteralNode) and node.datatype:
        return node.datatype
    return None


# ===========================================================================
# Self-contained helpers (no V1 imports)
# ===========================================================================

def _strip_unavailable_graphs(algebra, named_set: Set[str]):
    """Replace OpGraph nodes referencing graphs not in named_set with empty OpBGP.

    Per SPARQL spec §3.1.2, USING without USING NAMED makes the named graph
    dataset empty. GRAPH clauses referencing absent graphs produce no results.
    """
    if algebra is None:
        return OpBGP(triples=[])

    if isinstance(algebra, OpGraph):
        # Check if graph URI is in the allowed named set
        if isinstance(algebra.graph_node, URINode):
            if algebra.graph_node.value not in named_set:
                return OpBGP(triples=[])
        # Variable graph: can't statically resolve — keep as-is
        return algebra

    # Recurse into composite ops
    if isinstance(algebra, OpJoin):
        left = _strip_unavailable_graphs(algebra.left, named_set)
        right = _strip_unavailable_graphs(algebra.right, named_set)
        return OpJoin(left=left, right=right)

    if isinstance(algebra, OpUnion):
        left = _strip_unavailable_graphs(algebra.left, named_set)
        right = _strip_unavailable_graphs(algebra.right, named_set)
        return OpUnion(left=left, right=right)

    from ..jena_sparql.jena_types import OpFilter, OpLeftJoin, OpExtend
    if isinstance(algebra, OpFilter):
        sub = _strip_unavailable_graphs(algebra.sub_op, named_set)
        return OpFilter(exprs=algebra.exprs, sub_op=sub)

    if isinstance(algebra, OpLeftJoin):
        left = _strip_unavailable_graphs(algebra.left, named_set)
        right = _strip_unavailable_graphs(algebra.right, named_set)
        return OpLeftJoin(left=left, right=right, exprs=algebra.exprs)

    if isinstance(algebra, OpExtend):
        sub = _strip_unavailable_graphs(algebra.sub_op, named_set)
        return OpExtend(var=algebra.var, expr=algebra.expr, sub_op=sub)

    # Leaf nodes (OpBGP, etc.) — return as-is
    return algebra


def _esc(s: str) -> str:
    """Escape single quotes for SQL string literals."""
    if s is None:
        return ""
    return s.replace("'", "''")


def _node_text(node: RDFNode) -> str:
    """Extract the text value from an RDF node."""
    if isinstance(node, URINode):
        return node.value
    elif isinstance(node, LiteralNode):
        return node.value
    elif isinstance(node, BNodeNode):
        return f"_:{node.label}"
    elif isinstance(node, VarNode):
        return f"?{node.name}"
    return ""


def _node_type(node: RDFNode) -> str:
    """Get the term_type character for an RDF node."""
    if isinstance(node, URINode):
        return "U"
    elif isinstance(node, LiteralNode):
        return "L"
    elif isinstance(node, BNodeNode):
        return "B"
    return "U"


def _node_lang(node: RDFNode) -> Optional[str]:
    """Extract lang tag from a node if it's a LiteralNode with lang."""
    if isinstance(node, LiteralNode) and node.lang:
        return node.lang
    return None


def _term_upsert(term_table: str, text: str, ttype: str,
                 lang: Optional[str] = None,
                 datatype_id: Optional[int] = None) -> str:
    """Generate INSERT ... WHERE NOT EXISTS for a term row.

    Uses deterministic UUID v5 (matching _generate_term_uuid) so that
    term rows created here are consistent with the main write path.
    """
    term_uuid = _generate_term_uuid(text, ttype, lang=lang, datatype_id=datatype_id)
    lang_val = f"'{_esc(lang)}'" if lang else "NULL"
    dt_val = str(datatype_id) if datatype_id is not None else "NULL"
    return (
        f"INSERT INTO {term_table} (term_uuid, term_text, term_type, lang, datatype_id) "
        f"SELECT '{term_uuid}', '{_esc(text)}', '{ttype}', {lang_val}, {dt_val} "
        f"WHERE NOT EXISTS ("
        f"SELECT 1 FROM {term_table} "
        f"WHERE term_uuid = '{term_uuid}')"
    )


def _term_uuid_subquery(term_table: str, text: str, ttype: str,
                        datatype_id: Optional[int] = None) -> str:
    """Return a UUID expression for a constant term.

    When datatype_id is known the deterministic UUID is computed
    in Python and emitted as a literal — no subquery needed.
    For URIs / blank-nodes / untyped literals the existing
    text+type lookup is used as a safe fallback.
    """
    if datatype_id is not None or ttype != 'L':
        # Deterministic — matches the main write-path UUID exactly.
        computed = _generate_term_uuid(text, ttype, datatype_id=datatype_id)
        return f"'{computed}'::uuid"
    # Fallback: text + type lookup (for plain literals without datatype)
    return (
        f"(SELECT term_uuid FROM {term_table} "
        f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}' LIMIT 1)"
    )


def _sparql_to_sql_col(var_name: str,
                       var_map: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Find the SQL column name for a SPARQL variable via var_map."""
    if var_map:
        for sql_col, sparql_name in var_map.items():
            if sparql_name == var_name:
                return sql_col
    return None


def _binding_uuid_col(var_name: str,
                      var_map: Optional[Dict[str, str]] = None,
                      term_table: Optional[str] = None,
                      dt_table: Optional[str] = None) -> str:
    """Column reference for a variable's UUID in the _upd_bindings table.

    var_map maps sql_col → sparql_name.  We need the inverse: given a
    SPARQL variable name, find its SQL column name so we can reference
    the __uuid companion column.

    If the variable has no __uuid column (e.g. aggregates produce NULL),
    fall back to vitalgraph_term_uuid() which uses deterministic UUID v5
    including lang and datatype_id from companion columns.
    """
    sql_col = _sparql_to_sql_col(var_name, var_map)
    if sql_col:
        if term_table:
            # COALESCE: use __uuid if available (regular BGP vars), else
            # compute deterministic UUID from text+type+lang+datatype_id.
            fallback = _deterministic_uuid_expr(sql_col, dt_table)
            return f'COALESCE(CAST(b."{sql_col}__uuid" AS uuid), {fallback})'
        return f'b."{sql_col}__uuid"'
    # Fallback for variables not in var_map: deterministic UUID
    if term_table:
        col = var_name
        return _deterministic_uuid_expr(col, dt_table)
    return f'b."{var_name}__uuid"'


def _deterministic_uuid_expr(col: str, dt_table: Optional[str] = None) -> str:
    """SQL expression that computes a deterministic UUID v5 for a binding row.

    Uses vitalgraph_term_uuid(text, type, lang, datatype_id) which mirrors
    the Python _generate_term_uuid() function exactly.
    """
    text = f'CAST(b."{col}" AS text)'
    ttype = f'CAST(b."{col}__type" AS char(1))'
    lang = f'b."{col}__lang"'
    if dt_table:
        dt_id = (
            f'(SELECT dt.datatype_id FROM {dt_table} dt '
            f'WHERE dt.datatype_uri = b."{col}__datatype")'
        )
    else:
        dt_id = 'NULL::integer'
    return f'vitalgraph_term_uuid({text}, {ttype}, {lang}, {dt_id})'


def _node_to_uuid_expr(node: RDFNode, term_table: str,
                       default_graph: Optional[str] = None,
                       var_map: Optional[Dict[str, str]] = None,
                       dt_map: Optional[Dict[str, int]] = None,
                       dt_table: Optional[str] = None) -> str:
    """Resolve a template node to a UUID expression.

    VarNode  → reference __uuid column from _upd_bindings.
    Constant → deterministic UUID (using datatype_id when available).
    """
    if isinstance(node, VarNode):
        return _binding_uuid_col(node.name, var_map=var_map,
                                 term_table=term_table,
                                 dt_table=dt_table)
    text = _node_text(node)
    ttype = _node_type(node)
    dt_id = None
    dt_uri = _node_datatype_uri(node)
    if dt_uri and dt_map:
        dt_id = dt_map.get(dt_uri)
    return _term_uuid_subquery(term_table, text, ttype, datatype_id=dt_id)


# ===========================================================================
# Public dispatcher
# ===========================================================================

# Default graph URI used when no explicit graph is specified.
# Callers (e.g. DAWG test harness) can override via default_graph_uri param.
_FALLBACK_DEFAULT_GRAPH = "urn:default"


async def update_to_sql(
    ops: List[UpdateOp],
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
    default_graph_uri: Optional[str] = None,
) -> str:
    """Translate a list of update operations to SQL.

    Args:
        ops: List of update operations (multi-op sequences).
        space_id: PostgreSQL space ID (table prefix).
        conn_params: DB connection params (for WHERE-based ops).
        conn: Existing DB connection (for WHERE-based ops).
        default_graph_uri: URI for the default graph context.
            If None, uses 'urn:default'.

    Returns:
        Semicolon-separated SQL string.
    """
    dg = default_graph_uri or _FALLBACK_DEFAULT_GRAPH
    parts: List[str] = []
    for op in ops:
        parts.append(await _dispatch_one(op, space_id, conn_params=conn_params,
                                         conn=conn, default_graph_uri=dg))
    return ";".join(parts)


async def _dispatch_one(
    op: UpdateOp,
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
    default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH,
) -> str:
    """Dispatch a single update operation to its SQL generator.

    Only UpdateModify and UpdateDeleteWhere need async (they call generate_sql).
    All other ops are pure SQL generation.
    """
    if isinstance(op, UpdateDataInsert):
        dt_map = await _resolve_datatype_map(space_id, conn=conn, conn_params=conn_params)
        # Ensure datatype_ids exist for any new datatype URIs
        for q in op.quads:
            dt_uri = _node_datatype_uri(q.object)
            if dt_uri and dt_uri not in dt_map and conn is not None:
                await _ensure_datatype_id(space_id, dt_uri, dt_map, conn=conn)
        return _insert_data_sql(op.quads, space_id,
                                default_graph_uri=default_graph_uri,
                                dt_map=dt_map)
    elif isinstance(op, UpdateDataDelete):
        dt_map = await _resolve_datatype_map(space_id, conn=conn, conn_params=conn_params)
        return _delete_data_sql(op.quads, space_id,
                                default_graph_uri=default_graph_uri,
                                dt_map=dt_map)
    elif isinstance(op, UpdateModify):
        return await _modify_sql(op, space_id, conn_params=conn_params, conn=conn,
                                 default_graph_uri=default_graph_uri)
    elif isinstance(op, UpdateDeleteWhere):
        return await _delete_where_sql(op, space_id, conn_params=conn_params,
                                       conn=conn, default_graph_uri=default_graph_uri)
    elif isinstance(op, UpdateClear):
        return _clear_sql(op, space_id, default_graph_uri=default_graph_uri)
    elif isinstance(op, UpdateDrop):
        return _drop_sql(op, space_id, default_graph_uri=default_graph_uri)
    elif isinstance(op, UpdateCreate):
        return _create_sql(op, space_id)
    elif isinstance(op, UpdateLoad):
        return _load_sql(op, space_id)
    elif isinstance(op, UpdateCopy):
        return _copy_sql(op, space_id, default_graph_uri=default_graph_uri)
    elif isinstance(op, UpdateMove):
        return _move_sql(op, space_id, default_graph_uri=default_graph_uri)
    elif isinstance(op, UpdateAdd):
        return _add_sql(op, space_id, default_graph_uri=default_graph_uri)
    raise NotImplementedError(f"No SQL translation for {type(op).__name__}")


# ===========================================================================
# Tier 1: INSERT DATA
# ===========================================================================

def _insert_data_sql(quads: List[QuadPattern], space_id: str,
                     default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH,
                     dt_map: Optional[Dict[str, int]] = None) -> str:
    """INSERT DATA → term upserts + quad inserts.

    Uses deterministic UUID v5 for new terms, populates datatype_id and
    lang column for typed/language-tagged literals.
    """
    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"
    stmts: List[str] = []
    seen_terms: Set[Tuple[str, str, Optional[int]]] = set()

    def _node_dt_id(node: RDFNode) -> Optional[int]:
        dt_uri = _node_datatype_uri(node)
        if dt_uri and dt_map:
            return dt_map.get(dt_uri)
        return None

    for q in quads:
        graph_uri = _node_text(q.graph) if q.graph else default_graph_uri

        # Upsert terms (deduplicated within the batch)
        for node in [q.subject, q.predicate, q.object]:
            text = _node_text(node)
            ttype = _node_type(node)
            dt_id = _node_dt_id(node)
            key = (text, ttype, dt_id)
            if key not in seen_terms:
                seen_terms.add(key)
                lang = _node_lang(node)
                stmts.append(_term_upsert(term_table, text, ttype, lang,
                                          datatype_id=dt_id))

        # Graph term
        key = (graph_uri, "U", None)
        if key not in seen_terms:
            seen_terms.add(key)
            stmts.append(_term_upsert(term_table, graph_uri, "U"))

        # Insert quad using deterministic UUID references
        s_uuid = _term_uuid_subquery(term_table, _node_text(q.subject), _node_type(q.subject))
        p_uuid = _term_uuid_subquery(term_table, _node_text(q.predicate), _node_type(q.predicate))
        o_uuid = _term_uuid_subquery(term_table, _node_text(q.object), _node_type(q.object),
                                     datatype_id=_node_dt_id(q.object))
        g_uuid = _term_uuid_subquery(term_table, graph_uri, "U")

        stmts.append(
            f"INSERT INTO {quad_table} "
            f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
            f"SELECT {s_uuid}, {p_uuid}, {o_uuid}, {g_uuid} "
            f"WHERE NOT EXISTS ("
            f"SELECT 1 FROM {quad_table} "
            f"WHERE subject_uuid = {s_uuid} AND predicate_uuid = {p_uuid} "
            f"AND object_uuid = {o_uuid} AND context_uuid = {g_uuid})"
        )
    return ";\n".join(stmts)


# ===========================================================================
# Tier 1: DELETE DATA
# ===========================================================================

def _delete_data_sql(quads: List[QuadPattern], space_id: str,
                     default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH,
                     dt_map: Optional[Dict[str, int]] = None) -> str:
    """DELETE DATA → DELETE FROM statements with deterministic UUID lookups."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    stmts: List[str] = []

    def _obj_dt_id(node: RDFNode) -> Optional[int]:
        dt_uri = _node_datatype_uri(node)
        if dt_uri and dt_map:
            return dt_map.get(dt_uri)
        return None

    for q in quads:
        s_text, s_type = _node_text(q.subject), _node_type(q.subject)
        p_text, p_type = _node_text(q.predicate), _node_type(q.predicate)
        o_text, o_type = _node_text(q.object), _node_type(q.object)
        o_dt_id = _obj_dt_id(q.object)

        where_parts = [
            f"subject_uuid = {_term_uuid_subquery(term_table, s_text, s_type)}",
            f"predicate_uuid = {_term_uuid_subquery(term_table, p_text, p_type)}",
            f"object_uuid = {_term_uuid_subquery(term_table, o_text, o_type, datatype_id=o_dt_id)}",
        ]
        if q.graph:
            graph_text = _node_text(q.graph)
            where_parts.append(
                f"context_uuid = {_term_uuid_subquery(term_table, graph_text, 'U')}"
            )
        else:
            # No GRAPH clause → target default graph only
            where_parts.append(
                f"context_uuid = {_term_uuid_subquery(term_table, default_graph_uri, 'U')}"
            )
        stmts.append(f"DELETE FROM {quad_table} WHERE " + " AND ".join(where_parts))
    return ";\n".join(stmts)


# ===========================================================================
# Tier 2: DELETE/INSERT WHERE (UpdateModify)
# ===========================================================================

async def _modify_sql(
    op: UpdateModify,
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
    default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH,
) -> str:
    """DELETE/INSERT WHERE → combined SQL.

    If where_pattern is present, generates:
      1. Temp table with WHERE pattern bindings (including __uuid columns)
      2. DELETE using bindings + delete template
      3. Term upserts for new constants in insert template
      4. INSERT using bindings + insert template
      5. Cleanup
    """
    # Resolve datatype URI → ID map (used by all paths below)
    dt_map = await _resolve_datatype_map(space_id, conn=conn, conn_params=conn_params)
    # Ensure datatype_ids exist for any new datatype URIs in insert quads
    if op.insert_quads and conn is not None:
        for q in op.insert_quads:
            dt_uri = _node_datatype_uri(q.object)
            if dt_uri and dt_uri not in dt_map:
                await _ensure_datatype_id(space_id, dt_uri, dt_map, conn=conn)

    # Simple case: no WHERE pattern (plain DELETE + INSERT of constant quads)
    if not op.where_pattern:
        parts: List[str] = []
        if op.delete_quads:
            parts.append(_delete_data_sql(op.delete_quads, space_id, dt_map=dt_map))
        if op.insert_quads:
            parts.append(_insert_data_sql(op.insert_quads, space_id,
                                          default_graph_uri=default_graph_uri,
                                          dt_map=dt_map))
        return ";\n".join(parts)

    # Full WHERE pattern matching via V2 pipeline
    from .generator import generate_sql as v2_generate_sql

    term_table = f"{space_id}_term"

    if op.with_graph:
        where_graph = op.with_graph
        target_graph = op.with_graph
        where_algebra = op.where_pattern
    elif op.using_graphs:
        target_graph = default_graph_uri
        named_set = set(op.using_named_graphs) if op.using_named_graphs else set()
        base_pattern = op.where_pattern
        if not named_set:
            base_pattern = _strip_unavailable_graphs(base_pattern, named_set)

        if len(op.using_graphs) == 1:
            where_graph = op.using_graphs[0]
            where_algebra = base_pattern
        else:
            where_graph = None
            branches = [
                OpGraph(graph_node=URINode(g), sub_op=base_pattern)
                for g in op.using_graphs
            ]
            where_algebra = branches[0]
            for b in branches[1:]:
                where_algebra = OpUnion(left=where_algebra, right=b)
    else:
        where_graph = default_graph_uri
        where_algebra = op.where_pattern
        target_graph = default_graph_uri

    # Collect all template variables so they are projected by the WHERE clause.
    # Without this, OPTIONAL-only variables (e.g. ?old_mod) are not projected,
    # causing the DELETE to become a no-op.
    _template_vars: Set[str] = set()
    for _tq in (op.delete_quads or []) + (op.insert_quads or []):
        for _tn in [_tq.graph, _tq.subject, _tq.predicate, _tq.object]:
            if isinstance(_tn, VarNode):
                _template_vars.add(_tn.name)

    where_compile = CompileResult(
        ok=True,
        meta=ParsedQueryMeta(
            sparql_form="QUERY",
            query_type="SELECT",
            project_vars=sorted(_template_vars) if _template_vars else [],
        ),
        algebra=where_algebra,
    )
    where_result = await v2_generate_sql(
        where_compile, space_id,
        conn_params=conn_params, conn=conn,
        default_graph=where_graph,
    )
    if not where_result.ok:
        raise RuntimeError(
            f"V2 pipeline failed for UPDATE WHERE clause: {where_result.error}"
        )
    where_sql = where_result.sql
    var_map = where_result.var_map

    stmts: List[str] = []

    # Step 1: Materialize WHERE bindings into temp table
    stmts.append(
        f"CREATE TEMP TABLE _upd_bindings ON COMMIT DROP AS {where_sql}"
    )

    # Step 2: DELETE matching quads
    if op.delete_quads:
        for dq in op.delete_quads:
            stmts.append(_delete_from_bindings(dq, space_id, target_graph,
                                               var_map=var_map,
                                               dt_map=dt_map))

    # Step 3: Ensure new constant terms exist for INSERT template
    if op.insert_quads:
        seen_terms: Set[Tuple[str, str, Optional[int]]] = set()
        for iq in op.insert_quads:
            for node in [iq.graph, iq.subject, iq.predicate, iq.object]:
                if node is not None and not isinstance(node, VarNode):
                    text = _node_text(node)
                    ttype = _node_type(node)
                    dt_uri = _node_datatype_uri(node)
                    dt_id = dt_map.get(dt_uri) if dt_uri else None
                    key = (text, ttype, dt_id)
                    if key not in seen_terms:
                        seen_terms.add(key)
                        lang = _node_lang(node) if isinstance(node, LiteralNode) else None
                        stmts.append(_term_upsert(term_table, text, ttype, lang,
                                                  datatype_id=dt_id))

        # Step 3b: Upsert term entries for variable values from bindings
        # Variable values have __uuid from the WHERE clause; only create
        # term rows for values where __uuid is NULL (e.g. aggregates).
        # Uses deterministic UUID v5 via vitalgraph_term_uuid() so that
        # terms created here match the main write path exactly.
        dt_table = f"{space_id}_datatype"
        seen_var_upserts: Set[str] = set()
        for iq in op.insert_quads:
            for node in [iq.graph, iq.subject, iq.predicate, iq.object]:
                if isinstance(node, VarNode) and node.name not in seen_var_upserts:
                    seen_var_upserts.add(node.name)
                    sql_col = _sparql_to_sql_col(node.name, var_map)
                    col = sql_col or node.name
                    text_expr = f'CAST(b."{col}" AS text)'
                    type_expr = f'CAST(b."{col}__type" AS char(1))'
                    lang_expr = f'b."{col}__lang"'
                    dt_id_expr = (
                        f'(SELECT dt.datatype_id FROM {dt_table} dt '
                        f'WHERE dt.datatype_uri = b."{col}__datatype")'
                    )
                    uuid_expr = (
                        f'vitalgraph_term_uuid({text_expr}, {type_expr}, '
                        f'{lang_expr}, {dt_id_expr})'
                    )
                    stmts.append(
                        f"INSERT INTO {term_table} "
                        f"(term_uuid, term_text, term_type, lang, datatype_id) "
                        f"SELECT {uuid_expr}, "
                        f"{text_expr}, "
                        f"{type_expr}, "
                        f"{lang_expr}, "
                        f"{dt_id_expr} "
                        f"FROM _upd_bindings b "
                        f"WHERE b.\"{col}__uuid\" IS NULL "
                        f"AND NOT EXISTS ("
                        f"SELECT 1 FROM {term_table} "
                        f"WHERE term_uuid = {uuid_expr})"
                    )

        # Step 4: INSERT new quads from bindings
        for iq in op.insert_quads:
            stmts.append(_insert_from_bindings(iq, space_id, target_graph,
                                               var_map=var_map,
                                               dt_map=dt_map))

    # Step 5: Cleanup
    stmts.append("DROP TABLE IF EXISTS _upd_bindings")

    return ";\n".join(stmts)


async def _delete_where_sql(
    op: UpdateDeleteWhere,
    space_id: str,
    conn_params: Optional[Dict[str, Any]] = None,
    conn=None,
    default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH,
) -> str:
    """DELETE WHERE → convert to UpdateModify with identical delete/where patterns.

    DELETE WHERE { pattern } is equivalent to DELETE { pattern } WHERE { pattern }.
    """
    if not op.quads:
        logger.warning("UpdateDeleteWhere has no quads; returning no-op")
        return "SELECT 1"

    from collections import defaultdict
    graph_groups: Dict[Optional[str], List[TriplePattern]] = defaultdict(list)
    for q in op.quads:
        g_key = None
        if q.graph and isinstance(q.graph, URINode):
            g_key = q.graph.value
        elif q.graph and isinstance(q.graph, VarNode):
            g_key = f"?{q.graph.name}"
        graph_groups[g_key].append(TriplePattern(
            subject=q.subject,
            predicate=q.predicate,
            object=q.object,
        ))

    ops_list: List[Any] = []
    for g_key, triples in graph_groups.items():
        bgp = OpBGP(triples=triples)
        if g_key is None:
            ops_list.append(bgp)
        elif g_key.startswith("?"):
            ops_list.append(OpGraph(graph_node=VarNode(name=g_key[1:]), sub_op=bgp))
        else:
            ops_list.append(OpGraph(graph_node=URINode(g_key), sub_op=bgp))

    where_pattern: Op = ops_list[0]
    for op_extra in ops_list[1:]:
        where_pattern = OpJoin(left=where_pattern, right=op_extra)

    modify = UpdateModify(
        delete_quads=op.quads,
        insert_quads=[],
        where_pattern=where_pattern,
    )
    return await _modify_sql(modify, space_id, conn_params=conn_params, conn=conn,
                             default_graph_uri=default_graph_uri)


def _delete_from_bindings(dq: QuadPattern, space_id: str,
                          default_graph: Optional[str] = None,
                          var_map: Optional[Dict[str, str]] = None,
                          dt_map: Optional[Dict[str, int]] = None) -> str:
    """Generate DELETE ... USING _upd_bindings for one delete template quad."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    dt_table = f"{space_id}_datatype"

    conditions: List[str] = []
    needs_bindings = False  # track whether we reference _upd_bindings

    def _var_is_bound(name: str) -> bool:
        """Check if a variable is bound by the WHERE clause."""
        return _sparql_to_sql_col(name, var_map) is not None

    # Subject
    if isinstance(dq.subject, VarNode):
        if _var_is_bound(dq.subject.name):
            conditions.append(f"q.subject_uuid = {_binding_uuid_col(dq.subject.name, var_map, term_table, dt_table)}")
            needs_bindings = True
        # else: unbound variable → omit condition (wildcard match)
    else:
        conditions.append(
            f"q.subject_uuid = {_term_uuid_subquery(term_table, _node_text(dq.subject), _node_type(dq.subject))}"
        )

    # Predicate
    if isinstance(dq.predicate, VarNode):
        if _var_is_bound(dq.predicate.name):
            conditions.append(f"q.predicate_uuid = {_binding_uuid_col(dq.predicate.name, var_map, term_table, dt_table)}")
            needs_bindings = True
        # else: unbound variable → omit condition (wildcard match)
    else:
        conditions.append(
            f"q.predicate_uuid = {_term_uuid_subquery(term_table, _node_text(dq.predicate), _node_type(dq.predicate))}"
        )

    # Object
    if isinstance(dq.object, VarNode):
        if _var_is_bound(dq.object.name):
            conditions.append(f"q.object_uuid = {_binding_uuid_col(dq.object.name, var_map, term_table, dt_table)}")
            needs_bindings = True
        # else: unbound variable → omit condition (wildcard match)
    else:
        o_dt_id = None
        o_dt_uri = _node_datatype_uri(dq.object)
        if o_dt_uri and dt_map:
            o_dt_id = dt_map.get(o_dt_uri)
        conditions.append(
            f"q.object_uuid = {_term_uuid_subquery(term_table, _node_text(dq.object), _node_type(dq.object), datatype_id=o_dt_id)}"
        )

    # Graph
    if dq.graph and isinstance(dq.graph, VarNode):
        if _var_is_bound(dq.graph.name):
            conditions.append(f"q.context_uuid = {_binding_uuid_col(dq.graph.name, var_map, term_table, dt_table)}")
            needs_bindings = True
        # else: unbound graph variable → omit condition
    elif dq.graph:
        conditions.append(
            f"q.context_uuid = {_term_uuid_subquery(term_table, _node_text(dq.graph), 'U')}"
        )
    elif default_graph:
        conditions.append(
            f"q.context_uuid = {_term_uuid_subquery(term_table, default_graph, 'U')}"
        )

    if not conditions:
        return "SELECT 1"  # all positions are unbound variables → no-op

    if needs_bindings:
        return (
            f"DELETE FROM {quad_table} q "
            f"USING _upd_bindings b "
            f"WHERE " + " AND ".join(conditions)
        )
    # No variables reference bindings — direct DELETE without USING
    return (
        f"DELETE FROM {quad_table} q "
        f"WHERE " + " AND ".join(conditions)
    )


def _insert_from_bindings(iq: QuadPattern, space_id: str,
                          default_graph: Optional[str] = None,
                          var_map: Optional[Dict[str, str]] = None,
                          dt_map: Optional[Dict[str, int]] = None) -> str:
    """Generate INSERT ... SELECT from _upd_bindings for one insert template quad."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    dt_table = f"{space_id}_datatype"

    s_expr = _node_to_uuid_expr(iq.subject, term_table, var_map=var_map, dt_map=dt_map, dt_table=dt_table)
    p_expr = _node_to_uuid_expr(iq.predicate, term_table, var_map=var_map, dt_map=dt_map, dt_table=dt_table)
    o_expr = _node_to_uuid_expr(iq.object, term_table, var_map=var_map, dt_map=dt_map, dt_table=dt_table)

    if iq.graph:
        g_expr = _node_to_uuid_expr(iq.graph, term_table, var_map=var_map, dt_table=dt_table)
    elif default_graph:
        g_expr = _term_uuid_subquery(term_table, default_graph, "U")
    else:
        g_expr = _term_uuid_subquery(term_table, _FALLBACK_DEFAULT_GRAPH, "U")

    return (
        f"INSERT INTO {quad_table} "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"SELECT _s, _p, _o, _g FROM ("
        f"SELECT {s_expr} AS _s, {p_expr} AS _p, {o_expr} AS _o, {g_expr} AS _g "
        f"FROM _upd_bindings b) _ins "
        f"WHERE NOT EXISTS ("
        f"SELECT 1 FROM {quad_table} "
        f"WHERE subject_uuid = _ins._s AND predicate_uuid = _ins._p "
        f"AND object_uuid = _ins._o AND context_uuid = _ins._g)"
    )


# ===========================================================================
# Tier 3: Graph management operations
# ===========================================================================

def _clear_sql(op: UpdateClear, space_id: str,
               default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH) -> str:
    """CLEAR GRAPH/DEFAULT/NAMED/ALL → DELETE FROM statements."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    if op.target == "ALL":
        return f"DELETE FROM {quad_table}"

    if op.target == "DEFAULT":
        return (
            f"DELETE FROM {quad_table} WHERE context_uuid = "
            f"{_term_uuid_subquery(term_table, default_graph_uri, 'U')}"
        )

    if op.target == "NAMED":
        return (
            f"DELETE FROM {quad_table} WHERE context_uuid != "
            f"{_term_uuid_subquery(term_table, default_graph_uri, 'U')}"
        )

    # Specific graph URI
    graph_uri = op.graph or op.target
    return (
        f"DELETE FROM {quad_table} WHERE context_uuid = "
        f"{_term_uuid_subquery(term_table, graph_uri, 'U')}"
    )


def _drop_sql(op: UpdateDrop, space_id: str,
              default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH) -> str:
    """DROP GRAPH → same as CLEAR (no separate graph catalog)."""
    clear_op = UpdateClear(graph=op.graph, target=op.target, silent=op.silent)
    return _clear_sql(clear_op, space_id, default_graph_uri=default_graph_uri)


def _create_sql(op: UpdateCreate, space_id: str) -> str:
    """CREATE GRAPH → ensure graph term exists."""
    term_table = f"{space_id}_term"
    if not op.graph:
        return "SELECT 1"  # no-op for CREATE without URI
    return _term_upsert(term_table, op.graph, "U")


def _load_sql(op: UpdateLoad, space_id: str) -> str:
    """LOAD <url> → stub (requires HTTP fetch, delegated to application layer).

    LOAD SILENT on any error is a no-op per spec.
    """
    if op.silent:
        logger.info("LOAD SILENT %s — no-op (not implemented at SQL layer)",
                     op.source)
        return "SELECT 1"
    raise NotImplementedError(
        f"LOAD <{op.source}> is not supported at the SQL generation layer. "
        "Use the application API to load RDF data."
    )


def _copy_sql(op: UpdateCopy, space_id: str,
              default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH) -> str:
    """COPY source TO dest → clear dest, then insert all source quads with dest context."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    stmts: List[str] = []

    src_uri = op.source or default_graph_uri
    dst_uri = op.dest or default_graph_uri

    # Self-copy is a no-op
    if src_uri == dst_uri:
        return "SELECT 1"

    # Ensure dest graph term exists
    stmts.append(_term_upsert(term_table, dst_uri, "U"))

    # Clear destination
    dest_clear = UpdateClear(graph=dst_uri, target=dst_uri)
    stmts.append(_clear_sql(dest_clear, space_id, default_graph_uri=default_graph_uri))

    # Copy source quads with dest context
    src_uuid = _term_uuid_subquery(term_table, src_uri, "U")
    dst_uuid = _term_uuid_subquery(term_table, dst_uri, "U")

    stmts.append(
        f"INSERT INTO {quad_table} "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"SELECT q.subject_uuid, q.predicate_uuid, q.object_uuid, {dst_uuid} "
        f"FROM {quad_table} q "
        f"WHERE q.context_uuid = {src_uuid}"
    )
    return ";\n".join(stmts)


def _move_sql(op: UpdateMove, space_id: str,
              default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH) -> str:
    """MOVE source TO dest → COPY source TO dest, then DROP source."""
    stmts: List[str] = []

    src_uri = op.source or default_graph_uri
    dst_uri = op.dest or default_graph_uri

    # Self-move is a no-op
    if src_uri == dst_uri:
        return "SELECT 1"

    copy_op = UpdateCopy(source=op.source, dest=op.dest, silent=op.silent)
    stmts.append(_copy_sql(copy_op, space_id, default_graph_uri=default_graph_uri))

    drop_op = UpdateDrop(graph=src_uri, target=src_uri, silent=op.silent)
    stmts.append(_drop_sql(drop_op, space_id, default_graph_uri=default_graph_uri))
    return ";\n".join(stmts)


def _add_sql(op: UpdateAdd, space_id: str,
             default_graph_uri: str = _FALLBACK_DEFAULT_GRAPH) -> str:
    """ADD source TO dest → copy source quads into dest (additive, no clear)."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    stmts: List[str] = []

    src_uri = op.source or default_graph_uri
    dst_uri = op.dest or default_graph_uri

    # Ensure dest graph term exists
    stmts.append(_term_upsert(term_table, dst_uri, "U"))

    src_uuid = _term_uuid_subquery(term_table, src_uri, "U")
    dst_uuid = _term_uuid_subquery(term_table, dst_uri, "U")

    stmts.append(
        f"INSERT INTO {quad_table} "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"SELECT q.subject_uuid, q.predicate_uuid, q.object_uuid, {dst_uuid} "
        f"FROM {quad_table} q "
        f"WHERE q.context_uuid = {src_uuid}"
    )
    return ";\n".join(stmts)


