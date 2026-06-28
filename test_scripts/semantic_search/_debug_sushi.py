#!/usr/bin/env python3
"""Check Sushi Saito embedding vs 'italian' text embedding."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

import asyncpg
from vitalgraph.vectorization.registry import get_provider
from vitalgraph.vectorization.search_text_builder import (
    build_search_text, resolve_search_mapping, fetch_literal_properties,
)


async def main():
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/sparql_sql_graph")
    space_id = "sp_semantic_search_test"

    # Context UUID
    ctx_row = await conn.fetchrow(
        f"SELECT term_uuid FROM {space_id}_term "
        "WHERE term_text = 'urn:semantic_search_test'"
    )
    ctx_uuid = ctx_row["term_uuid"]

    # Sushi Saito entity UUID
    row = await conn.fetchrow(
        f"SELECT term_uuid FROM {space_id}_term "
        "WHERE term_text = 'http://vital.ai/test/semantic/entity/sushi_saito'"
    )
    sushi_uuid = row["term_uuid"]
    print(f"Sushi Saito UUID: {sushi_uuid}")

    # Fetch its literal properties
    props = await fetch_literal_properties(conn, space_id, sushi_uuid, ctx_uuid)
    print(f"Literal properties ({len(props)}):")
    for pred_uri, obj_text in props:
        short = pred_uri.rsplit("#", 1)[-1] if "#" in pred_uri else pred_uri
        print(f"  {short}: {obj_text[:100]}")

    # Resolve mapping rule
    mapping_rule = await resolve_search_mapping(
        conn, space_id, "entity_vector", "kgentity", None,
    )

    # Build text
    text = build_search_text(props, mapping_rule)
    print(f"\nSearch text: '{text}'")

    # Get provider and embed
    provider = get_provider("vitalsigns", {}, cache_key="debug2")

    # Embed the text and also "italian"
    sushi_emb = await provider.vectorize_text(text)
    italian_emb = await provider.vectorize_text("italian")

    # Compare locally
    import numpy as np
    s = np.array(sushi_emb)
    i = np.array(italian_emb)
    cos_sim = float(np.dot(s, i) / (np.linalg.norm(s) * np.linalg.norm(i)))
    print(f"\nLocal cos sim (sushi text vs 'italian'): {cos_sim:.4f}")

    # Check stored embedding similarity to both
    sushi_vec_str = "[" + ",".join(str(v) for v in sushi_emb) + "]"
    italian_vec_str = "[" + ",".join(str(v) for v in italian_emb) + "]"

    stored_vs_fresh = await conn.fetchval(f"""
        SELECT 1 - (embedding <=> '{sushi_vec_str}'::vector)
        FROM {space_id}_vec_entity_vector WHERE subject_uuid = $1::uuid
    """, sushi_uuid)
    stored_vs_italian = await conn.fetchval(f"""
        SELECT 1 - (embedding <=> '{italian_vec_str}'::vector)
        FROM {space_id}_vec_entity_vector WHERE subject_uuid = $1::uuid
    """, sushi_uuid)
    print(f"Stored sushi embedding vs fresh sushi text: {stored_vs_fresh:.4f}")
    print(f"Stored sushi embedding vs 'italian': {stored_vs_italian:.4f}")

    # Check: what text has embedding closest to what's stored for sushi?
    # Compare "japanese" embedding
    jp_emb = await provider.vectorize_text("japanese")
    jp_vec_str = "[" + ",".join(str(v) for v in jp_emb) + "]"
    stored_vs_jp = await conn.fetchval(f"""
        SELECT 1 - (embedding <=> '{jp_vec_str}'::vector)
        FROM {space_id}_vec_entity_vector WHERE subject_uuid = $1::uuid
    """, sushi_uuid)
    print(f"Stored sushi embedding vs 'japanese': {stored_vs_jp:.4f}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
