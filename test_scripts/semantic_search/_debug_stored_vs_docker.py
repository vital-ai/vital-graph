#!/usr/bin/env python3
"""Check stored sushi embedding vs Docker-generated embeddings."""
import asyncio
import numpy as np
import asyncpg
from vitalgraph.vectorization.registry import get_provider


async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@host.docker.internal:5432/sparql_sql_graph"
    )
    sp = "sp_semantic_search_test"
    provider = get_provider("vitalsigns", {}, cache_key="check")

    # Get sushi UUID
    r = await conn.fetchrow(
        f"SELECT term_uuid FROM {sp}_term "
        "WHERE term_text = 'http://vital.ai/test/semantic/entity/sushi_saito'"
    )
    sushi_uuid = r["term_uuid"]

    # Get stored embedding
    vec_row = await conn.fetchrow(
        f"SELECT embedding::text FROM {sp}_vec_entity_vector WHERE subject_uuid = $1",
        sushi_uuid,
    )
    stored_str = vec_row["embedding"]
    stored = np.array([float(x) for x in stored_str.strip("[]").split(",")])
    print(f"Stored embedding dim: {len(stored)}, norm: {np.linalg.norm(stored):.4f}")
    print(f"Stored first 5: {stored[:5]}")

    # Generate embeddings on Docker
    sushi_text = "Sushi Saito. Legendary omakase sushi counter with three Michelin stars in Minato Tokyo"
    italian_text = "italian"

    sushi_emb = np.array(await provider.vectorize_text(sushi_text))
    italian_emb = np.array(await provider.vectorize_text(italian_text))

    print(f"\nDocker sushi emb first 5: {sushi_emb[:5]}")
    print(f"Docker italian emb first 5: {italian_emb[:5]}")

    # Similarities
    def cos(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    print(f"\nStored vs Docker 'sushi text': {cos(stored, sushi_emb):.6f}")
    print(f"Stored vs Docker 'italian':    {cos(stored, italian_emb):.6f}")
    print(f"Docker sushi vs Docker italian: {cos(sushi_emb, italian_emb):.6f}")

    await conn.close()


asyncio.run(main())
