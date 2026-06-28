#!/usr/bin/env python3
"""Check what text the populator uses for Joe's Pizza entity."""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / ".env")

import asyncpg
from vitalgraph.vectorization.search_text_builder import (
    build_search_text, resolve_search_mapping, fetch_literal_properties,
)


async def main():
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/sparql_sql_graph")
    space_id = "sp_semantic_search_test"

    # Get Joe's Pizza subject UUID
    row = await conn.fetchrow(
        f"SELECT term_uuid FROM {space_id}_term "
        "WHERE term_text = 'http://vital.ai/test/semantic/entity/joes_pizza'"
    )
    subj_uuid = row["term_uuid"]
    print(f"Joe's Pizza UUID: {subj_uuid}")

    # Get graph context UUID
    ctx_row = await conn.fetchrow(
        f"SELECT term_uuid FROM {space_id}_term "
        "WHERE term_text = 'urn:semantic_search_test'"
    )
    ctx_uuid = ctx_row["term_uuid"]

    # Fetch literal properties
    props = await fetch_literal_properties(conn, space_id, subj_uuid, ctx_uuid)
    print(f"\nLiteral properties ({len(props)}):")
    for pred_uri, obj_text in props:
        short_pred = pred_uri.rsplit("#", 1)[-1] if "#" in pred_uri else pred_uri
        print(f"  {short_pred}: {obj_text[:100]}")

    # Resolve mapping rule
    mapping_rule = await resolve_search_mapping(
        conn, space_id, "entity_vector", "kgentity", None,
    )
    print(f"\nMapping rule: {mapping_rule}")
    if mapping_rule:
        print(f"  source_type: {mapping_rule.source_type}")
        print(f"  include_uris: {mapping_rule.include_uris}")
        print(f"  enabled: {mapping_rule.enabled}")

    # Build search text
    text = build_search_text(props, mapping_rule)
    print(f"\nSearch text for vectorization:")
    print(f"  '{text}'")
    print(f"  Length: {len(text)} chars")

    # Now embed this text and compare to stored embedding
    from vitalgraph.vectorization.registry import get_provider
    provider = get_provider("vitalsigns", {}, cache_key="debug")

    embedding = await provider.vectorize_text(text)
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"

    # Compare to stored embedding
    stored_sim = await conn.fetchval(f"""
        SELECT 1 - (embedding <=> '{vec_str}'::vector)
        FROM {space_id}_vec_entity_vector
        WHERE subject_uuid = $1::uuid
    """, subj_uuid)
    print(f"\nFresh embedding vs stored: similarity = {stored_sim}")

    # Also check food and italian query scores against fresh embedding
    for query in ["food", "italian", "pizza", "new york pizza"]:
        q_emb = await provider.vectorize_text(query)
        q_str = "[" + ",".join(str(v) for v in q_emb) + "]"
        score = await conn.fetchval(f"""
            SELECT 1 - (embedding <=> '{q_str}'::vector)
            FROM {space_id}_vec_entity_vector
            WHERE subject_uuid = $1::uuid
        """, subj_uuid)
        print(f"  '{query}' vs stored Joe's Pizza: {score:.4f}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
