#!/usr/bin/env python3
"""Run inside Docker to check what text gets built for Sushi Saito."""
import asyncio
import asyncpg
from vitalgraph.vectorization.search_text_builder import (
    build_search_text, resolve_search_mapping, fetch_literal_properties,
)


async def main():
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@host.docker.internal:5432/sparql_sql_graph"
    )
    space_id = "sp_semantic_search_test"
    ctx = await conn.fetchrow(
        f"SELECT term_uuid FROM {space_id}_term "
        "WHERE term_text = 'urn:semantic_search_test'"
    )
    ctx_uuid = ctx["term_uuid"]

    # Sushi saito entity
    r = await conn.fetchrow(
        f"SELECT term_uuid FROM {space_id}_term "
        "WHERE term_text = 'http://vital.ai/test/semantic/entity/sushi_saito'"
    )
    sushi_uuid = r["term_uuid"]

    props = await fetch_literal_properties(conn, space_id, sushi_uuid, ctx_uuid)
    rule = await resolve_search_mapping(conn, space_id, "entity_vector", "kgentity", None)
    text = build_search_text(props, rule)

    print(f"source_type: {rule.source_type}")
    print(f"include_uris: {rule.include_uris}")
    print(f"Props count: {len(props)}")
    for p in props:
        short = p[0].rsplit("#", 1)[-1] if "#" in p[0] else p[0]
        print(f"  {short}: {p[1][:60]}")
    print(f"Built text: [{text}]")
    print(f"Text length: {len(text)}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
