#!/usr/bin/env python3
"""Check Joe's Pizza embedding after the fix."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

import asyncpg
import numpy as np
from vitalgraph.vectorization.registry import get_provider


async def main():
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/sparql_sql_graph")
    sp = "sp_semantic_search_test"

    r = await conn.fetchrow(
        f"SELECT term_uuid FROM {sp}_term "
        "WHERE term_text = 'http://vital.ai/test/semantic/entity/joes_pizza'"
    )
    uuid = r["term_uuid"]
    print(f"Joe's Pizza UUID: {uuid}")

    vec = await conn.fetchrow(
        f"SELECT embedding::text, updated_time FROM {sp}_vec_entity_vector "
        "WHERE subject_uuid = $1", uuid,
    )
    if not vec:
        print("NOT in vec table!")
        await conn.close()
        return

    print(f"In vec table: updated={vec['updated_time']}")
    stored = np.array([float(x) for x in vec["embedding"].strip("[]").split(",")])

    p = get_provider("vitalsigns", {}, cache_key="final")

    def cos(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    for query in ["italian", "food", "pizza", "new york pizza", "pizza by the slice"]:
        q_emb = np.array(await p.vectorize_text(query))
        print(f"  '{query}': {cos(stored, q_emb):.4f}")

    # Check what text was stored
    expected = "Joe's Pizza. Classic New York style pizza by the slice in Greenwich Village since 1975"
    exp_emb = np.array(await p.vectorize_text(expected))
    print(f"\n  vs expected text embedding: {cos(stored, exp_emb):.4f}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
