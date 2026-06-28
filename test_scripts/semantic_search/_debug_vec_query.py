#!/usr/bin/env python3
"""Compute embedding for 'italian' and check similarity to Joe's Pizza."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

import asyncpg
from vitalgraph.vectorization.registry import get_provider


async def main():
    # Get the provider config from the vector index table
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/sparql_sql_graph")
    row = await conn.fetchrow(
        "SELECT provider, provider_config, dimensions "
        "FROM sp_semantic_search_test_vector_index "
        "WHERE index_name = 'entity_vector'"
    )
    print(f"Provider: {row['provider']}, dimensions: {row['dimensions']}")
    print(f"Config: {row['provider_config']}")

    provider = get_provider(
        row["provider"], row["provider_config"] or {},
        cache_key="debug",
    )

    # Embed "italian"
    query_embedding = await provider.vectorize_text("italian")
    vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
    print(f"Query embedding length: {len(query_embedding)}")

    # Compute similarity to Joe's Pizza
    joes_uuid = "1bb7c664-21c1-534f-a5e9-2ba34389c05f"
    score = await conn.fetchval(f"""
        SELECT 1 - (embedding <=> '{vec_str}'::vector)
        FROM sp_semantic_search_test_vec_entity_vector
        WHERE subject_uuid = $1::uuid
    """, joes_uuid)
    print(f"\nJoe's Pizza similarity to 'italian': {score}")

    # Top 15 by this embedding
    rows = await conn.fetch(f"""
        SELECT t.term_text AS uri,
               1 - (v.embedding <=> '{vec_str}'::vector) AS score
        FROM sp_semantic_search_test_vec_entity_vector v
        JOIN sp_semantic_search_test_term t ON v.subject_uuid = t.term_uuid
        ORDER BY v.embedding <=> '{vec_str}'::vector
        LIMIT 15
    """)
    print(f"\nTop 15 by 'italian' query embedding:")
    for r in rows:
        print(f"  {r['score']:.4f}  {r['uri']}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
