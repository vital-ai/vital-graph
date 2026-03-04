"""
SPARQL Update operations → SQL translation.

Handles INSERT DATA, DELETE DATA, DELETE/INSERT WHERE (UpdateModify),
and graph management operations (CLEAR, DROP, CREATE, COPY, MOVE, ADD).
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set, Tuple

from .jena_types import (
    QuadPattern, URINode, LiteralNode, BNodeNode, VarNode, RDFNode,
    UpdateDataInsert, UpdateDataDelete, UpdateModify, UpdateDeleteWhere, UpdateOp,
    UpdateClear, UpdateDrop, UpdateCreate, UpdateCopy, UpdateMove, UpdateAdd,
    OpBGP, TriplePattern,
)
from .jena_sql_ir import SQLContext, AliasGenerator
from .jena_sql_helpers import _esc, _node_text, _node_type, build_constants_cte

logger = logging.getLogger(__name__)


# ===========================================================================
# Public dispatcher
# ===========================================================================

def update_to_sql(op: UpdateOp, space_id_or_ctx) -> str:
    """Translate an update operation to SQL.

    Args:
        op: The update operation.
        space_id_or_ctx: Either a string space_id or a SQLContext.
    """
    space_id = space_id_or_ctx.space_id if isinstance(space_id_or_ctx, SQLContext) else space_id_or_ctx
    if isinstance(op, UpdateDataInsert):
        return _insert_data_sql(op.quads, space_id)
    elif isinstance(op, UpdateDataDelete):
        return _delete_data_sql(op.quads, space_id)
    elif isinstance(op, UpdateModify):
        return _modify_sql(op, space_id)
    elif isinstance(op, UpdateDeleteWhere):
        return _delete_where_sql(op, space_id)
    elif isinstance(op, UpdateClear):
        return _clear_sql(op, space_id)
    elif isinstance(op, UpdateDrop):
        return _drop_sql(op, space_id)
    elif isinstance(op, UpdateCreate):
        return _create_sql(op, space_id)
    elif isinstance(op, UpdateCopy):
        return _copy_sql(op, space_id)
    elif isinstance(op, UpdateMove):
        return _move_sql(op, space_id)
    elif isinstance(op, UpdateAdd):
        return _add_sql(op, space_id)
    raise NotImplementedError(f"No SQL translation for {type(op).__name__}")


# ===========================================================================
# Helpers
# ===========================================================================

def _node_lang(node: RDFNode) -> Optional[str]:
    """Extract lang tag from a node if it's a LiteralNode with lang."""
    if isinstance(node, LiteralNode) and node.lang:
        return node.lang
    return None


def _term_upsert(term_table: str, text: str, ttype: str,
                 lang: Optional[str] = None) -> str:
    """Generate INSERT ... WHERE NOT EXISTS for a term row.

    Uses gen_random_uuid() for term_uuid since the column has no default.
    """
    lang_val = f"'{_esc(lang)}'" if lang else "NULL"
    return (
        f"INSERT INTO {term_table} (term_uuid, term_text, term_type, lang) "
        f"SELECT gen_random_uuid(), '{_esc(text)}', '{ttype}', {lang_val} "
        f"WHERE NOT EXISTS ("
        f"SELECT 1 FROM {term_table} "
        f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}')"
    )


def _term_uuid_subquery(term_table: str, text: str, ttype: str) -> str:
    """Scalar subquery to look up a term_uuid by text + type."""
    return (
        f"(SELECT term_uuid FROM {term_table} "
        f"WHERE term_text = '{_esc(text)}' AND term_type = '{ttype}' LIMIT 1)"
    )


# ===========================================================================
# INSERT DATA
# ===========================================================================

def _insert_data_sql(quads: List[QuadPattern], space_id: str) -> str:
    """INSERT DATA → term upserts + quad inserts.

    Generates term_uuid via gen_random_uuid() for new terms, populates
    lang column for language-tagged literals, and uses term_type filters
    for accurate UUID cross-join lookups.
    """
    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"
    stmts: List[str] = []
    seen_terms: Set[Tuple[str, str]] = set()

    for q in quads:
        graph_uri = _node_text(q.graph) if q.graph else "urn:default"

        # Upsert terms (deduplicated within the batch)
        for node in [q.subject, q.predicate, q.object]:
            text = _node_text(node)
            ttype = _node_type(node)
            key = (text, ttype)
            if key not in seen_terms:
                seen_terms.add(key)
                lang = _node_lang(node)
                stmts.append(_term_upsert(term_table, text, ttype, lang))

        # Graph term
        key = (graph_uri, "U")
        if key not in seen_terms:
            seen_terms.add(key)
            stmts.append(_term_upsert(term_table, graph_uri, "U"))

        # Insert quad via UUID cross-join lookup (with type filters)
        s_text, s_type = _node_text(q.subject), _node_type(q.subject)
        p_text, p_type = _node_text(q.predicate), _node_type(q.predicate)
        o_text, o_type = _node_text(q.object), _node_type(q.object)

        stmts.append(
            f"INSERT INTO {quad_table} "
            f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
            f"SELECT s.term_uuid, p.term_uuid, o.term_uuid, g.term_uuid "
            f"FROM {term_table} s, {term_table} p, {term_table} o, {term_table} g "
            f"WHERE s.term_text = '{_esc(s_text)}' AND s.term_type = '{s_type}' "
            f"AND p.term_text = '{_esc(p_text)}' AND p.term_type = '{p_type}' "
            f"AND o.term_text = '{_esc(o_text)}' AND o.term_type = '{o_type}' "
            f"AND g.term_text = '{_esc(graph_uri)}' AND g.term_type = 'U'"
        )
    return ";\n".join(stmts)


# ===========================================================================
# DELETE DATA
# ===========================================================================

def _delete_data_sql(quads: List[QuadPattern], space_id: str) -> str:
    """DELETE DATA → DELETE FROM statements with type-aware lookups."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    stmts: List[str] = []

    for q in quads:
        s_text, s_type = _node_text(q.subject), _node_type(q.subject)
        p_text, p_type = _node_text(q.predicate), _node_type(q.predicate)
        o_text, o_type = _node_text(q.object), _node_type(q.object)

        where_parts = [
            f"subject_uuid = {_term_uuid_subquery(term_table, s_text, s_type)}",
            f"predicate_uuid = {_term_uuid_subquery(term_table, p_text, p_type)}",
            f"object_uuid = {_term_uuid_subquery(term_table, o_text, o_type)}",
        ]
        if q.graph:
            graph_text = _node_text(q.graph)
            where_parts.append(
                f"context_uuid = {_term_uuid_subquery(term_table, graph_text, 'U')}"
            )
        stmts.append(f"DELETE FROM {quad_table} WHERE " + " AND ".join(where_parts))
    return ";\n".join(stmts)


# ===========================================================================
# DELETE/INSERT WHERE (UpdateModify)
# ===========================================================================

def _modify_sql(op: UpdateModify, space_id: str) -> str:
    """DELETE/INSERT WHERE → combined SQL.

    If where_pattern is present, generates:
      1. Temp table with WHERE pattern bindings (including __uuid columns)
      2. DELETE using bindings + delete template
      3. Term upserts for new constants in insert template
      4. INSERT using bindings + insert template
      5. Cleanup
    """
    # Simple case: no WHERE pattern (plain DELETE + INSERT of constant quads)
    if not op.where_pattern:
        parts: List[str] = []
        if op.delete_quads:
            parts.append(_delete_data_sql(op.delete_quads, space_id))
        if op.insert_quads:
            parts.append(_insert_data_sql(op.insert_quads, space_id))
        return ";\n".join(parts)

    # Full WHERE pattern matching via 3-pass pipeline
    from .jena_sql_collect import collect as _collect
    from .jena_sql_resolve import resolve as _resolve
    from .jena_sql_emit import emit as _emit

    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"
    aliases = AliasGenerator()
    graph_uri = op.with_graph

    plan = _collect(op.where_pattern, space_id, aliases, graph_uri=graph_uri)
    resolved = _resolve(plan, space_id, aliases)
    where_sql = _emit(resolved, space_id)

    cte_prefix = build_constants_cte(aliases, term_table)
    full_where_sql = cte_prefix + where_sql if cte_prefix else where_sql

    stmts: List[str] = []

    # Step 1: Materialize WHERE bindings into temp table
    stmts.append(
        f"CREATE TEMP TABLE _upd_bindings ON COMMIT DROP AS {full_where_sql}"
    )

    # Step 2: DELETE matching quads
    if op.delete_quads:
        for dq in op.delete_quads:
            stmts.append(_delete_from_bindings(dq, space_id, graph_uri))

    # Step 3: Ensure new constant terms exist for INSERT template
    if op.insert_quads:
        seen_terms: Set[Tuple[str, str]] = set()
        for iq in op.insert_quads:
            for node in [iq.graph, iq.subject, iq.predicate, iq.object]:
                if node is not None and not isinstance(node, VarNode):
                    text = _node_text(node)
                    ttype = _node_type(node)
                    key = (text, ttype)
                    if key not in seen_terms:
                        seen_terms.add(key)
                        lang = _node_lang(node) if isinstance(node, LiteralNode) else None
                        stmts.append(_term_upsert(term_table, text, ttype, lang))

        # Step 4: INSERT new quads from bindings
        for iq in op.insert_quads:
            stmts.append(_insert_from_bindings(iq, space_id, graph_uri))

    # Step 5: Cleanup
    stmts.append("DROP TABLE IF EXISTS _upd_bindings")

    return ";\n".join(stmts)


def _delete_where_sql(op: UpdateDeleteWhere, space_id: str) -> str:
    """DELETE WHERE → convert to UpdateModify with identical delete/where patterns.

    DELETE WHERE { pattern } is equivalent to DELETE { pattern } WHERE { pattern }.
    If the sidecar provided quads, convert them to a BGP for the WHERE pattern.
    If no quads (sidecar limitation), fall back to simple delete.
    """
    if not op.quads:
        logger.warning("UpdateDeleteWhere has no quads; returning no-op")
        return "SELECT 1"

    # Build WHERE pattern as an OpBGP from the quad patterns
    triples = []
    for q in op.quads:
        triples.append(TriplePattern(
            subject=q.subject,
            predicate=q.predicate,
            object=q.object,
        ))

    modify = UpdateModify(
        delete_quads=op.quads,
        insert_quads=[],
        where_pattern=OpBGP(triples=triples),
    )
    return _modify_sql(modify, space_id)


def _binding_uuid_col(var_name: str) -> str:
    """Column reference for a variable's UUID in the _upd_bindings table."""
    return f'b."{var_name}__uuid"'


def _node_to_uuid_expr(node: RDFNode, term_table: str,
                       default_graph: Optional[str] = None) -> str:
    """Resolve a template node to a UUID expression.

    VarNode  → reference __uuid column from _upd_bindings.
    Constant → scalar subquery against term table.
    None     → default graph UUID lookup.
    """
    if isinstance(node, VarNode):
        return _binding_uuid_col(node.name)
    text = _node_text(node)
    ttype = _node_type(node)
    return _term_uuid_subquery(term_table, text, ttype)


def _delete_from_bindings(dq: QuadPattern, space_id: str,
                          default_graph: Optional[str] = None) -> str:
    """Generate DELETE ... USING _upd_bindings for one delete template quad.

    Uses PostgreSQL DELETE ... USING to correlate each binding row with the
    quad to delete, ensuring only the exact (s, p, o, g) combinations from
    the WHERE result are removed.
    """
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    conditions: List[str] = []

    # Subject
    if isinstance(dq.subject, VarNode):
        conditions.append(f"q.subject_uuid = {_binding_uuid_col(dq.subject.name)}")
    else:
        conditions.append(
            f"q.subject_uuid = {_term_uuid_subquery(term_table, _node_text(dq.subject), _node_type(dq.subject))}"
        )

    # Predicate
    if isinstance(dq.predicate, VarNode):
        conditions.append(f"q.predicate_uuid = {_binding_uuid_col(dq.predicate.name)}")
    else:
        conditions.append(
            f"q.predicate_uuid = {_term_uuid_subquery(term_table, _node_text(dq.predicate), _node_type(dq.predicate))}"
        )

    # Object
    if isinstance(dq.object, VarNode):
        conditions.append(f"q.object_uuid = {_binding_uuid_col(dq.object.name)}")
    else:
        conditions.append(
            f"q.object_uuid = {_term_uuid_subquery(term_table, _node_text(dq.object), _node_type(dq.object))}"
        )

    # Graph
    if dq.graph and isinstance(dq.graph, VarNode):
        conditions.append(f"q.context_uuid = {_binding_uuid_col(dq.graph.name)}")
    elif dq.graph:
        conditions.append(
            f"q.context_uuid = {_term_uuid_subquery(term_table, _node_text(dq.graph), 'U')}"
        )
    elif default_graph:
        conditions.append(
            f"q.context_uuid = {_term_uuid_subquery(term_table, default_graph, 'U')}"
        )

    return (
        f"DELETE FROM {quad_table} q "
        f"USING _upd_bindings b "
        f"WHERE " + " AND ".join(conditions)
    )


def _insert_from_bindings(iq: QuadPattern, space_id: str,
                          default_graph: Optional[str] = None) -> str:
    """Generate INSERT ... SELECT from _upd_bindings for one insert template quad."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    s_expr = _node_to_uuid_expr(iq.subject, term_table)
    p_expr = _node_to_uuid_expr(iq.predicate, term_table)
    o_expr = _node_to_uuid_expr(iq.object, term_table)

    if iq.graph:
        g_expr = _node_to_uuid_expr(iq.graph, term_table)
    elif default_graph:
        g_expr = _term_uuid_subquery(term_table, default_graph, "U")
    else:
        g_expr = _term_uuid_subquery(term_table, "urn:default", "U")

    return (
        f"INSERT INTO {quad_table} "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"SELECT {s_expr}, {p_expr}, {o_expr}, {g_expr} "
        f"FROM _upd_bindings b"
    )


# ===========================================================================
# Graph management operations
# ===========================================================================

def _clear_sql(op: UpdateClear, space_id: str) -> str:
    """CLEAR GRAPH/DEFAULT/NAMED/ALL → DELETE FROM statements."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    if op.target == "ALL":
        return f"DELETE FROM {quad_table}"

    if op.target == "DEFAULT":
        return (
            f"DELETE FROM {quad_table} WHERE context_uuid = "
            f"{_term_uuid_subquery(term_table, 'urn:default', 'U')}"
        )

    if op.target == "NAMED":
        return (
            f"DELETE FROM {quad_table} WHERE context_uuid != "
            f"{_term_uuid_subquery(term_table, 'urn:default', 'U')}"
        )

    # Specific graph URI
    graph_uri = op.graph or op.target
    return (
        f"DELETE FROM {quad_table} WHERE context_uuid = "
        f"{_term_uuid_subquery(term_table, graph_uri, 'U')}"
    )


def _drop_sql(op: UpdateDrop, space_id: str) -> str:
    """DROP GRAPH → same as CLEAR (no separate graph catalog)."""
    clear_op = UpdateClear(graph=op.graph, target=op.target, silent=op.silent)
    return _clear_sql(clear_op, space_id)


def _create_sql(op: UpdateCreate, space_id: str) -> str:
    """CREATE GRAPH → ensure graph term exists."""
    term_table = f"{space_id}_term"
    if not op.graph:
        return "SELECT 1"  # no-op for CREATE without URI
    return _term_upsert(term_table, op.graph, "U")


def _copy_sql(op: UpdateCopy, space_id: str) -> str:
    """COPY source TO dest → clear dest, then insert all source quads with dest context."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    stmts: List[str] = []

    # Ensure dest graph term exists
    if op.dest:
        stmts.append(_term_upsert(term_table, op.dest, "U"))

    # Clear destination
    dest_clear = UpdateClear(graph=op.dest, target=op.dest or "DEFAULT")
    stmts.append(_clear_sql(dest_clear, space_id))

    # Copy source quads with dest context
    src_uuid = _term_uuid_subquery(term_table, op.source, "U")
    dst_uuid = _term_uuid_subquery(term_table, op.dest, "U") if op.dest else src_uuid

    stmts.append(
        f"INSERT INTO {quad_table} "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"SELECT q.subject_uuid, q.predicate_uuid, q.object_uuid, {dst_uuid} "
        f"FROM {quad_table} q "
        f"WHERE q.context_uuid = {src_uuid}"
    )
    return ";\n".join(stmts)


def _move_sql(op: UpdateMove, space_id: str) -> str:
    """MOVE source TO dest → COPY source TO dest, then DROP source."""
    stmts: List[str] = []
    copy_op = UpdateCopy(source=op.source, dest=op.dest, silent=op.silent)
    stmts.append(_copy_sql(copy_op, space_id))

    drop_op = UpdateDrop(graph=op.source, target=op.source, silent=op.silent)
    stmts.append(_drop_sql(drop_op, space_id))
    return ";\n".join(stmts)


def _add_sql(op: UpdateAdd, space_id: str) -> str:
    """ADD source TO dest → copy source quads into dest (additive, no clear)."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    stmts: List[str] = []

    # Ensure dest graph term exists
    if op.dest:
        stmts.append(_term_upsert(term_table, op.dest, "U"))

    src_uuid = _term_uuid_subquery(term_table, op.source, "U")
    dst_uuid = _term_uuid_subquery(term_table, op.dest, "U") if op.dest else src_uuid

    stmts.append(
        f"INSERT INTO {quad_table} "
        f"(subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"SELECT q.subject_uuid, q.predicate_uuid, q.object_uuid, {dst_uuid} "
        f"FROM {quad_table} q "
        f"WHERE q.context_uuid = {src_uuid}"
    )
    return ";\n".join(stmts)
