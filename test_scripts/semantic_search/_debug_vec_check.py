#!/usr/bin/env python3
"""Check why Joe's Pizza is missing from vector search results."""
import asyncio
import asyncpg


async def main():
    conn = await asyncpg.connect("postgresql://postgres@localhost:5432/sparql_sql_graph")

    # Get Joe's Pizza subject UUID
    row = await conn.fetchrow(
        "SELECT term_uuid FROM sp_semantic_search_test_term "
        "WHERE term_text = 'http://vital.ai/test/semantic/entity/joes_pizza'"
    )
    if not row:
        print("Joe's Pizza URI not found in term table")
        await conn.close()
        return
    subj_uuid = row["term_uuid"]
    print(f"Joe's Pizza subject_uuid: {subj_uuid}")

    # Check vec table for this subject
    vec_rows = await conn.fetch(
        "SELECT subject_uuid, context_uuid "
        "FROM sp_semantic_search_test_vec_entity_vector "
        "WHERE subject_uuid = $1", subj_uuid
    )
    print(f"Rows in vec table: {len(vec_rows)}")
    for r in vec_rows:
        print(f"  context_uuid: {r['context_uuid']}")

    # Check graph context UUID
    graph_row = await conn.fetchrow(
        "SELECT term_uuid FROM sp_semantic_search_test_term "
        "WHERE term_text = 'urn:semantic_search_test'"
    )
    if graph_row:
        print(f"Graph context_uuid: {graph_row['term_uuid']}")

    # Check what context the quads use for Joe's Pizza
    quad_rows = await conn.fetch(
        "SELECT DISTINCT q.context_uuid, t.term_text "
        "FROM sp_semantic_search_test_rdf_quad q "
        "JOIN sp_semantic_search_test_term t ON q.context_uuid = t.term_uuid "
        "WHERE q.subject_uuid = $1 LIMIT 5", subj_uuid
    )
    print(f"Quad contexts for Joe's Pizza:")
    for r in quad_rows:
        print(f"  {r['context_uuid']} -> {r['term_text']}")

    # Compare: what context_uuid do vectorized docs use?
    doc_row = await conn.fetchrow(
        "SELECT t.term_uuid FROM sp_semantic_search_test_term t "
        "WHERE t.term_text = 'urn:semantic_test:doc:tokyo_food_guide_parent_markdown_heading_split'"
    )
    if doc_row:
        doc_vec = await conn.fetch(
            "SELECT context_uuid FROM sp_semantic_search_test_vec_entity_vector "
            "WHERE subject_uuid = $1", doc_row["term_uuid"]
        )
        print(f"\nTokyo doc vec context: {[r['context_uuid'] for r in doc_vec]}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
