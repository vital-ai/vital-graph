"""
Execute SPARQL queries through the v2 SQL pipeline.

This is the v2 equivalent of dawg_sql_executor.py. It uses the v2
generator (collect → emit → materialize → substitute) instead of v1.

Allowed to import from both v1 and v2 per §11.7 (test harness exception).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .dawg_srx_parser import SparqlBinding, SparqlResults

logger = logging.getLogger(__name__)

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
XSD_BOOLEAN = "http://www.w3.org/2001/XMLSchema#boolean"


class SqlV2PipelineError(Exception):
    pass


async def execute_query_via_v2_pipeline(
    sparql: str,
    sidecar_url: str = "http://localhost:7070",
    space_id: str = "dawg_test",
    conn=None,
    conn_params=None,
    graph_lock_uri: str = None,
    default_graph: str = None,
) -> SparqlResults:
    """Execute a SPARQL query through the v2 SQL pipeline.

    Args:
        sparql: The SPARQL query string.
        sidecar_url: URL of the Jena sidecar.
        space_id: PostgreSQL space ID.
        conn: Existing DB connection.
        conn_params: DB connection params.
        graph_lock_uri: Optional graph lock — always applied to every quad scan.
        default_graph: Optional default graph URI — constrains outer BGPs
            only (not inside GRAPH clauses).

    Returns:
        SparqlResults for comparison with expected results.
    """
    import json
    import urllib.request

    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql

    # Step 1: Compile via sidecar
    try:
        req = urllib.request.Request(
            f"{sidecar_url}/v1/sparql/compile",
            data=json.dumps({"sparql": sparql}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
    except Exception as e:
        raise SqlV2PipelineError(f"Sidecar compile error: {e}")

    # Step 2: Map JSON → Op tree
    try:
        compile_result = map_compile_response(raw)
    except Exception as e:
        raise SqlV2PipelineError(f"AST mapping error: {e}")

    if not compile_result.ok:
        raise SqlV2PipelineError(f"SPARQL parse error: {compile_result.error}")

    query_type = compile_result.meta.query_type if compile_result.meta else None

    # ASK queries — run WHERE clause, return boolean
    if query_type == "ASK":
        return await _execute_ask(
            compile_result, space_id, conn, conn_params,
            graph_lock_uri, default_graph,
        )

    # CONSTRUCT
    if query_type == "CONSTRUCT":
        return await _execute_construct(
            compile_result, space_id, conn, conn_params,
            graph_lock_uri, default_graph,
        )

    # DESCRIBE — fetch all triples for described resources
    if query_type == "DESCRIBE":
        return await _execute_describe(
            compile_result, space_id, conn, conn_params,
            graph_lock_uri, default_graph,
        )

    # Step 3: Generate SQL via v2 pipeline
    try:
        gen_result = await generate_sql(
            compile_result, space_id,
            conn=conn, conn_params=conn_params,
            graph_lock_uri=graph_lock_uri,
            default_graph=default_graph,
        )
    except Exception as e:
        raise SqlV2PipelineError(f"v2 SQL generation error: {e}")

    if not gen_result.ok:
        raise SqlV2PipelineError(f"v2 generation error: {gen_result.error}")

    sql = gen_result.sql
    var_map = gen_result.var_map
    sparql_vars = gen_result.sparql_vars

    # Step 4: Execute SQL
    from vitalgraph.db.sparql_sql import db_provider as db

    try:
        rows = await db.execute_query(sql, conn_params=conn_params, conn=conn)
    except Exception as e:
        raise SqlV2PipelineError(f"SQL execution error: {e}\nSQL: {sql[:500]}")

    # Step 5: Convert to SparqlResults
    from vitalgraph.db.sparql_sql.sql_type_binding import (
        sql_to_sparql_binding, SparqlBinding as V2Binding,
    )

    # Build inverse var_map: sparql_name → sql_col.
    # The generator builds var_map from the final TypeRegistry, which has
    # exactly one canonical sql_name per SPARQL variable — no duplicates.
    inv_map = {sparql: sql_col for sql_col, sparql in var_map.items()}

    result_rows: List[Dict[str, SparqlBinding]] = []
    for row in rows:
        bindings: Dict[str, SparqlBinding] = {}
        for sparql_name in sparql_vars:
            sql_col = inv_map.get(sparql_name, sparql_name)
            val = row.get(sql_col)
            if val is None:
                continue

            b = sql_to_sparql_binding(sql_col, val, row)
            if b is not None:
                bindings[sparql_name] = SparqlBinding(
                    type=b.type, value=b.value,
                    datatype=b.datatype, lang=b.lang,
                )

        result_rows.append(bindings)

    return SparqlResults(variables=sparql_vars, rows=result_rows)


async def execute_update_via_v2_pipeline(
    sparql: str,
    sidecar_url: str = "http://localhost:7070",
    space_id: str = "dawg_test",
    conn=None,
    conn_params=None,
    default_graph: str = None,
) -> None:
    """Execute a SPARQL Update through the v2 SQL pipeline.

    Args:
        sparql: The SPARQL Update string.
        sidecar_url: URL of the Jena sidecar.
        space_id: PostgreSQL space ID.
        conn: Existing DB connection.
        conn_params: DB connection params.
        default_graph: Default graph URI for unqualified triples.

    Raises:
        SqlV2PipelineError on any failure.
    """
    import json
    import urllib.request

    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql import db_provider as db

    # Step 1: Compile via sidecar
    try:
        req = urllib.request.Request(
            f"{sidecar_url}/v1/sparql/compile",
            data=json.dumps({"sparql": sparql}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read())
    except Exception as e:
        raise SqlV2PipelineError(f"Sidecar compile error: {e}")

    # Step 2: Map JSON → UpdateOps
    try:
        compile_result = map_compile_response(raw)
    except Exception as e:
        raise SqlV2PipelineError(f"AST mapping error: {e}")

    if not compile_result.ok:
        raise SqlV2PipelineError(f"SPARQL parse error: {compile_result.error}")

    if not compile_result.update_ops:
        raise SqlV2PipelineError("Expected UPDATE but got no update_ops")

    # Step 3: Generate SQL via v2 pipeline
    try:
        gen_result = await generate_sql(
            compile_result, space_id,
            conn=conn, conn_params=conn_params,
            default_graph=default_graph,
        )
    except Exception as e:
        raise SqlV2PipelineError(f"v2 SQL generation error: {e}")

    if not gen_result.ok:
        raise SqlV2PipelineError(f"v2 generation error: {gen_result.error}")

    sql = gen_result.sql

    # Step 4: Execute SQL statements
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    try:
        async with conn.transaction():
            for stmt in statements:
                await conn.execute(stmt)
    except Exception as e:
        raise SqlV2PipelineError(f"SQL execution error: {e}\nSQL: {sql[:500]}")


async def _execute_ask(
    compile_result,
    space_id: str,
    conn=None,
    conn_params=None,
    graph_lock_uri: str = None,
    default_graph: str = None,
) -> SparqlResults:
    """Execute an ASK query: run WHERE clause, return boolean."""
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql import db_provider as db

    try:
        gen_result = await generate_sql(
            compile_result, space_id,
            conn=conn, conn_params=conn_params,
            graph_lock_uri=graph_lock_uri,
            default_graph=default_graph,
        )
    except Exception as e:
        raise SqlV2PipelineError(f"v2 SQL generation error: {e}")

    if not gen_result.ok:
        raise SqlV2PipelineError(f"v2 generation error: {gen_result.error}")

    # Wrap with EXISTS check for efficiency
    ask_sql = f"SELECT EXISTS ({gen_result.sql}) AS result"

    try:
        rows = await db.execute_query(ask_sql, conn_params=conn_params, conn=conn)
    except Exception as e:
        raise SqlV2PipelineError(f"SQL execution error: {e}")

    result_bool = bool(rows[0]["result"]) if rows else False

    return SparqlResults(
        variables=[],
        rows=[],
        is_boolean=True,
        boolean_value=result_bool,
    )


async def _execute_describe(
    compile_result,
    space_id: str,
    conn=None,
    conn_params=None,
    graph_lock_uri: str = None,
    default_graph: str = None,
) -> SparqlResults:
    """Execute a DESCRIBE query: fetch triples for described resources."""
    from vitalgraph.db.jena_sparql.jena_types import VarNode, URINode
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql.sql_type_binding import sql_to_sparql_binding
    from vitalgraph.db.sparql_sql import db_provider as db

    meta = compile_result.meta
    describe_nodes = meta.describe_nodes if meta else []

    # Step 1: Collect URIs to describe
    uris_to_describe = set()

    # Direct URI nodes
    for node in describe_nodes:
        if isinstance(node, URINode):
            uris_to_describe.add(node.value)

    # Variable nodes — need to run WHERE clause to get bindings
    var_nodes = [n for n in describe_nodes if isinstance(n, VarNode)]
    if var_nodes and compile_result.algebra:
        try:
            gen_result = await generate_sql(
                compile_result, space_id,
                conn=conn, conn_params=conn_params,
                graph_lock_uri=graph_lock_uri,
                default_graph=default_graph,
            )
        except Exception as e:
            raise SqlV2PipelineError(f"v2 SQL generation error: {e}")

        if gen_result.ok:
            try:
                rows = await db.execute_query(
                    gen_result.sql, conn_params=conn_params, conn=conn)
            except Exception as e:
                raise SqlV2PipelineError(f"SQL execution error: {e}")

            inv_map = {s: c for c, s in gen_result.var_map.items()}
            var_names = {n.name for n in var_nodes}
            for row in rows:
                for vn in var_names:
                    sql_col = inv_map.get(vn, vn)
                    val = row.get(sql_col)
                    if val is not None:
                        b = sql_to_sparql_binding(sql_col, val, row)
                        if b and b.type == "uri":
                            uris_to_describe.add(b.value)

    if not uris_to_describe:
        return SparqlResults(
            variables=["subject", "predicate", "object"],
            rows=[], is_graph=True,
        )

    # Step 2: Fetch all triples where URI is subject or object
    uri_list = ", ".join(f"'{u}'" for u in uris_to_describe)
    describe_sql = f"""
        SELECT
            ts.term_text AS s_val, ts.term_type AS s_type,
            tp.term_text AS p_val,
            tobj.term_text AS o_val, tobj.term_type AS o_type,
            tobj.lang AS o_lang, tobj.datatype_id AS o_dt
        FROM {space_id}_rdf_quad q
        JOIN {space_id}_term ts ON q.subject_uuid = ts.term_uuid
        JOIN {space_id}_term tp ON q.predicate_uuid = tp.term_uuid
        JOIN {space_id}_term tobj ON q.object_uuid = tobj.term_uuid
        WHERE ts.term_text IN ({uri_list}) AND ts.term_type = 'U'
    """

    try:
        rows = await db.execute_query(describe_sql, conn_params=conn_params, conn=conn)
    except Exception as e:
        raise SqlV2PipelineError(f"SQL execution error: {e}")

    # Step 3: Convert to triples
    triples: List[Dict[str, SparqlBinding]] = []
    seen = set()
    for row in rows:
        s = SparqlBinding(type="uri", value=row["s_val"])
        p = SparqlBinding(type="uri", value=row["p_val"])

        o_type = row["o_type"]
        if o_type == "U":
            o = SparqlBinding(type="uri", value=row["o_val"])
        elif o_type == "B":
            o = SparqlBinding(type="bnode", value=row["o_val"])
        else:
            dt = row.get("o_dt") or None
            lang = row.get("o_lang") or None
            if dt == XSD_STRING:
                dt = None
            if dt == XSD_BOOLEAN:
                val = row["o_val"]
                if val == "0":
                    val = "false"
                elif val == "1":
                    val = "true"
                o = SparqlBinding(type="literal", value=val,
                                  datatype=dt, lang=lang)
            else:
                o = SparqlBinding(type="literal", value=row["o_val"],
                                  datatype=dt, lang=lang)

        key = (s.value, p.value, o.type, o.value, o.datatype or "", o.lang or "")
        if key not in seen:
            seen.add(key)
            triples.append({"subject": s, "predicate": p, "object": o})

    return SparqlResults(
        variables=["subject", "predicate", "object"],
        rows=triples,
        is_graph=True,
    )


async def _execute_construct(
    compile_result,
    space_id: str,
    conn=None,
    conn_params=None,
    graph_lock_uri: str = None,
    default_graph: str = None,
) -> SparqlResults:
    """Execute a CONSTRUCT query: run WHERE clause, apply template."""
    from vitalgraph.db.jena_sparql.jena_types import VarNode, URINode, LiteralNode, BNodeNode
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql.sql_type_binding import sql_to_sparql_binding
    from vitalgraph.db.sparql_sql import db_provider as db

    template = compile_result.meta.construct_template if compile_result.meta else []

    # Generate SQL for the WHERE clause body
    try:
        gen_result = await generate_sql(
            compile_result, space_id,
            conn=conn, conn_params=conn_params,
            graph_lock_uri=graph_lock_uri,
            default_graph=default_graph,
        )
    except Exception as e:
        raise SqlV2PipelineError(f"v2 SQL generation error: {e}")

    if not gen_result.ok:
        raise SqlV2PipelineError(f"v2 generation error: {gen_result.error}")

    sql = gen_result.sql
    var_map = gen_result.var_map
    sparql_vars = gen_result.sparql_vars

    # Execute SQL
    try:
        rows = await db.execute_query(sql, conn_params=conn_params, conn=conn)
    except Exception as e:
        raise SqlV2PipelineError(f"SQL execution error: {e}")

    # Build inverse var_map
    inv_map = {sparql: sql_col for sql_col, sparql in var_map.items()}

    # Convert SQL rows to bindings
    solution_rows = []
    for row in rows:
        bindings: Dict[str, SparqlBinding] = {}
        for sparql_name in sparql_vars:
            sql_col = inv_map.get(sparql_name, sparql_name)
            val = row.get(sql_col)
            if val is None:
                continue
            b = sql_to_sparql_binding(sql_col, val, row)
            if b is not None:
                bindings[sparql_name] = SparqlBinding(
                    type=b.type, value=b.value,
                    datatype=b.datatype, lang=b.lang,
                )
        solution_rows.append(bindings)

    # Apply template to each solution row → produce triples
    # Blank nodes in the template get fresh labels per solution row
    triples: List[Dict[str, SparqlBinding]] = []
    seen = set()
    for row_idx, bindings in enumerate(solution_rows):
        for tp in template:
            triple = _instantiate_template_triple(tp, bindings, row_idx)
            if triple is None:
                continue
            # Deduplicate
            key = tuple(sorted(
                (k, v.type, v.value, v.datatype or "", v.lang or "")
                for k, v in triple.items()
            ))
            if key not in seen:
                seen.add(key)
                triples.append(triple)

    return SparqlResults(
        variables=["subject", "predicate", "object"],
        rows=triples,
        is_graph=True,
    )


def _instantiate_template_triple(tp, bindings, row_idx=0):
    """Instantiate a template triple from a solution row.

    Returns a dict with 'subject', 'predicate', 'object' SparqlBindings,
    or None if any variable is unbound.
    Blank nodes get fresh labels per row_idx to avoid cross-row collisions.
    """
    from vitalgraph.db.jena_sparql.jena_types import VarNode, URINode, LiteralNode, BNodeNode

    result = {}
    for role, node in [("subject", tp.subject),
                       ("predicate", tp.predicate),
                       ("object", tp.object)]:
        if isinstance(node, VarNode):
            b = bindings.get(node.name)
            if b is None:
                return None  # unbound → skip triple
            result[role] = b
        elif isinstance(node, URINode):
            result[role] = SparqlBinding(type="uri", value=node.value)
        elif isinstance(node, LiteralNode):
            dt = node.datatype if node.datatype else None
            if dt == XSD_STRING:
                dt = None
            result[role] = SparqlBinding(
                type="literal", value=node.value,
                lang=node.lang, datatype=dt,
            )
        elif isinstance(node, BNodeNode):
            # Fresh bnode label per solution row
            result[role] = SparqlBinding(
                type="bnode", value=f"{node.label}_r{row_idx}")
        else:
            return None
    return result
