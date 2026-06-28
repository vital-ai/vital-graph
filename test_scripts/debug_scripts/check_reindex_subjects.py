#!/usr/bin/env python3
"""Diagnose why vector reindex finds 0 subjects."""
import asyncio
import uuid
import asyncpg

SPACE = "framenet_kgtypes_test"
GRAPH_URI = "urn:vitalgraph:framenet_kgtypes_test:kg_types"

async def check():
    conn = await asyncpg.connect("postgresql://postgres@localhost/sparql_sql_graph")

    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    ctx = uuid.uuid5(ns, f"{GRAPH_URI}\x00U")
    print(f"context_uuid: {ctx}")

    # All subjects (no type filter)
    rows = await conn.fetch(
        f"SELECT DISTINCT q.subject_uuid FROM {SPACE}_rdf_quad q WHERE q.context_uuid = $1",
        ctx,
    )
    print(f"All subjects (no type filter): {len(rows)}")

    # RDF types present
    type_rows = await conn.fetch(f"""
        SELECT t_obj.term_text, COUNT(*) as cnt
        FROM {SPACE}_rdf_quad q
        JOIN {SPACE}_term t_pred ON q.predicate_uuid = t_pred.term_uuid
        JOIN {SPACE}_term t_obj ON q.object_uuid = t_obj.term_uuid
        WHERE q.context_uuid = $1
          AND t_pred.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
        GROUP BY t_obj.term_text
    """, ctx)
    print(f"\nRDF types ({len(type_rows)}):")
    for r in type_rows:
        print(f"  {r['term_text']}  count={r['cnt']}")

    # Check search_mapping
    sm_rows = await conn.fetch(f"SELECT * FROM {SPACE}_search_mapping")
    print(f"\nsearch_mapping rows ({len(sm_rows)}):")
    for r in sm_rows:
        print(f"  {dict(r)}")

    # Check vector_index
    vi_rows = await conn.fetch(f"SELECT * FROM {SPACE}_vector_index")
    print(f"\nvector_index rows ({len(vi_rows)}):")
    for r in vi_rows:
        print(f"  index_name={r['index_name']}  provider={r['provider']}")

    # Check vec table
    try:
        vec_cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {SPACE}_vec_kgtype_default")
        print(f"\nvec_kgtype_default rows: {vec_cnt}")
    except Exception as e:
        print(f"\nvec_kgtype_default: {e}")

    await conn.close()

asyncio.run(check())
