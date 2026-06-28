#!/usr/bin/env python3
"""Check the server-side query embedding for 'italian' vs stored vectors."""
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
    p = get_provider("vitalsigns", {}, cache_key="qcheck")

    # Get query embedding for "italian"
    italian_emb = np.array(await p.vectorize_text("italian"))
    pizza_emb = np.array(await p.vectorize_text("pizza"))

    # Get ALL embeddings from vec table
    rows = await conn.fetch(
        f"SELECT subject_uuid, embedding::text FROM {sp}_vec_entity_vector"
    )
    print(f"Total vec rows: {len(rows)}")

    def cos(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    # Compute scores for "italian" and count those > 0.01
    italian_scores = []
    pizza_scores = []
    for row in rows:
        emb = np.array([float(x) for x in row["embedding"].strip("[]").split(",")])
        italian_scores.append((cos(emb, italian_emb), row["subject_uuid"]))
        pizza_scores.append((cos(emb, pizza_emb), row["subject_uuid"]))

    italian_scores.sort(reverse=True)
    pizza_scores.sort(reverse=True)

    above_01_italian = sum(1 for s, _ in italian_scores if s > 0.01)
    above_01_pizza = sum(1 for s, _ in pizza_scores if s > 0.01)
    print(f"\n'italian' scores > 0.01: {above_01_italian}")
    print(f"'pizza'   scores > 0.01: {above_01_pizza}")

    print(f"\nTop 5 for 'italian':")
    for s, uuid in italian_scores[:5]:
        t = await conn.fetchval(
            f"SELECT term_text FROM {sp}_term WHERE term_uuid = $1", uuid
        )
        print(f"  {s:.4f}  {t}")

    print(f"\nTop 5 for 'pizza':")
    for s, uuid in pizza_scores[:5]:
        t = await conn.fetchval(
            f"SELECT term_text FROM {sp}_term WHERE term_uuid = $1", uuid
        )
        print(f"  {s:.4f}  {t}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
