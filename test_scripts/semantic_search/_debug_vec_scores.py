#!/usr/bin/env python3
"""Check raw vector scores for all entities against 'italian'."""
import asyncio
import asyncpg
import json


async def main():
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/sparql_sql_graph")

    # Get all vectorized subjects with their names
    rows = await conn.fetch("""
        SELECT v.subject_uuid, t.term_text AS uri,
               1 - (v.embedding <=> (
                   SELECT embedding FROM sp_semantic_search_test_vec_entity_vector
                   WHERE subject_uuid = v.subject_uuid LIMIT 1
               )) AS self_sim
        FROM sp_semantic_search_test_vec_entity_vector v
        JOIN sp_semantic_search_test_term t ON v.subject_uuid = t.term_uuid
        WHERE v.context_uuid = 'c8760144-c220-50df-98ae-89bc0d353af4'::uuid
        LIMIT 5
    """)
    print(f"Sample vectorized subjects: {len(rows)}")
    for r in rows:
        print(f"  {r['uri']}")

    # Get the query embedding for "italian" by checking what the system generates
    # Instead, compute cosine similarity directly
    # First find the entity vector for Joe's Pizza
    joes_uuid = '1bb7c664-21c1-534f-a5e9-2ba34389c05f'

    # Get raw cosine distances between Joe's Pizza and all other vectors
    scores = await conn.fetch("""
        SELECT t.term_text AS uri,
               1 - (v.embedding <=> (
                   SELECT embedding FROM sp_semantic_search_test_vec_entity_vector
                   WHERE subject_uuid = $1::uuid
               )) AS similarity
        FROM sp_semantic_search_test_vec_entity_vector v
        JOIN sp_semantic_search_test_term t ON v.subject_uuid = t.term_uuid
        WHERE v.context_uuid = 'c8760144-c220-50df-98ae-89bc0d353af4'::uuid
        ORDER BY similarity DESC
        LIMIT 10
    """, joes_uuid)
    print(f"\nTop 10 most similar to Joe's Pizza:")
    for r in scores:
        print(f"  {r['similarity']:.4f}  {r['uri']}")

    # Check the total count in vec table
    count = await conn.fetchval(
        "SELECT count(*) FROM sp_semantic_search_test_vec_entity_vector "
        "WHERE context_uuid = 'c8760144-c220-50df-98ae-89bc0d353af4'::uuid"
    )
    print(f"\nTotal vectors in graph context: {count}")

    # List all vectorized entities with 'entity/' in URI
    entities = await conn.fetch("""
        SELECT t.term_text
        FROM sp_semantic_search_test_vec_entity_vector v
        JOIN sp_semantic_search_test_term t ON v.subject_uuid = t.term_uuid
        WHERE t.term_text LIKE '%/entity/%'
        ORDER BY t.term_text
    """)
    print(f"\nVectorized entity subjects ({len(entities)}):")
    for r in entities:
        print(f"  {r['term_text']}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
