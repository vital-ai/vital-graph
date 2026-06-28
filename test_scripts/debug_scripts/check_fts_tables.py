#!/usr/bin/env python3
"""Quick diagnostic: check FTS-related tables for framenet_kgtypes_test space."""
import asyncio
import asyncpg

SPACE = "framenet_kgtypes_test"

async def check():
    conn = await asyncpg.connect("postgresql://postgres@localhost/sparql_sql_graph")

    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE $1 ORDER BY table_name",
        f"{SPACE}_%",
    )
    print(f"Tables for {SPACE} ({len(rows)}):")
    for r in rows:
        print(f"  {r['table_name']}")

    # Check vector_index contents
    try:
        vi = await conn.fetch(f"SELECT index_name, provider FROM {SPACE}_vector_index")
        print(f"\nvector_index rows: {[dict(r) for r in vi]}")
    except Exception as e:
        print(f"\nvector_index: {e}")

    # Check fts_index contents
    try:
        fi = await conn.fetch(f"SELECT * FROM {SPACE}_fts_index")
        print(f"fts_index rows: {[dict(r) for r in fi]}")
    except Exception as e:
        print(f"fts_index: {e}")

    # Check search_mapping contents
    try:
        sm = await conn.fetch(f"SELECT * FROM {SPACE}_search_mapping")
        print(f"search_mapping rows: {[dict(r) for r in sm]}")
    except Exception as e:
        print(f"search_mapping: {e}")

    # Check rdf_quad count
    try:
        cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {SPACE}_rdf_quad")
        print(f"\nrdf_quad count: {cnt}")
    except Exception as e:
        print(f"\nrdf_quad: {e}")

    # Check vec table
    try:
        vec_cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {SPACE}_vec_kgtype_default")
        print(f"vec_kgtype_default count: {vec_cnt}")
    except Exception as e:
        print(f"vec_kgtype_default: {e}")

    # Try creating FTS index manually to see the actual error
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    schema = SparqlSQLSchema()
    stmts = schema.create_fts_data_table_sql(SPACE, "kgtype_default", ["english"])
    print(f"\nFTS DDL statements ({len(stmts)}):")
    for i, stmt in enumerate(stmts):
        try:
            await conn.execute(stmt)
            print(f"  [{i}] OK")
        except Exception as e:
            print(f"  [{i}] ERROR: {e}")
            print(f"      SQL: {stmt[:200]}")

    await conn.close()

asyncio.run(check())
