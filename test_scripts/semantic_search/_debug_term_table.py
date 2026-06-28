#!/opt/homebrew/anaconda3/envs/vital-graph/bin/python
"""Resync edge table from rdf_quad for the semantic search test space."""
import asyncio
import asyncpg
import sys
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")

async def main():
    conn = await asyncpg.connect(
        host="localhost", port=5432, user="postgres", password="", database="sparql_sql_graph",
    )

    from vitalgraph.db.sparql_sql.sync_edge_table import resync_edge_table
    
    print("Before resync:")
    rows = await conn.fetch("SELECT count(*) as cnt FROM sp_semantic_search_test_edge")
    print(f"  Edge table row count: {rows[0]['cnt']}")

    count = await resync_edge_table(conn, "sp_semantic_search_test")
    print(f"\nResynced edge table: {count} rows")

    print("\nAfter resync:")
    rows = await conn.fetch("SELECT count(*) as cnt FROM sp_semantic_search_test_edge")
    print(f"  Edge table row count: {rows[0]['cnt']}")

    # Check document edges
    rows2 = await conn.fetch(
        "SELECT s.term_text as src, d.term_text as dst "
        "FROM sp_semantic_search_test_edge e "
        "JOIN sp_semantic_search_test_term s ON e.source_node_uuid = s.term_uuid "
        "JOIN sp_semantic_search_test_term d ON e.dest_node_uuid = d.term_uuid "
        "WHERE s.term_text LIKE '%semantic_test:doc%' "
        "LIMIT 20"
    )
    print(f"\nDocument edges in edge table: {len(rows2)}")
    for r in rows2:
        print(f"  {r['src']} -> {r['dst']}")

    await conn.close()

asyncio.run(main())
