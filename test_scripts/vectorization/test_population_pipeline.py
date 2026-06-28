"""
End-to-end test of the vector + geo population pipeline.

Creates test RDF data, runs the vector and geo populators, and verifies:
1. search_text is built correctly from properties
2. Embeddings are stored and vector similarity search works
3. tsvector full-text search works
4. Geo points are populated and ST_DWithin queries work

Usage:
    python test_scripts/vectorization/test_population_pipeline.py
"""

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

DB_NAME = os.environ.get("VITALGRAPH_DB", "sparql_sql_graph")
DB_USER = os.environ.get("VITALGRAPH_DB_USER", "postgres")
DB_HOST = os.environ.get("VITALGRAPH_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("VITALGRAPH_DB_PORT", "5432"))

TEST_SPACE = "test_pop_pipe"


def make_uuid(n: int) -> str:
    """Create a deterministic UUID from an integer."""
    return str(uuid.UUID(int=n))


GRAPH_UUID = make_uuid(99)
ENTITY1_UUID = make_uuid(1)
ENTITY2_UUID = make_uuid(2)
ENTITY3_UUID = make_uuid(3)

# Predicate UUIDs (deterministic from URI hash)
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
HAS_NAME = "http://vital.ai/ontology/haley-ai-kg#hasName"
HAS_DESC = "http://vital.ai/ontology/haley-ai-kg#hasDescription"
HAS_LAT = "http://vital.ai/ontology/haley-ai-kg#hasLatitude"
HAS_LON = "http://vital.ai/ontology/haley-ai-kg#hasLongitude"
HAS_KGRAPH_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
KG_ENTITY_TYPE = "http://vital.ai/ontology/haley-ai-kg#KGEntity"


async def _term_uuid(conn, space_id: str, text: str, term_type: str = 'U') -> str:
    """Generate a term UUID using the DB function and insert the term."""
    term_table = f"{space_id}_term"
    # Use vitalgraph_term_uuid function
    term_uuid = await conn.fetchval(
        "SELECT vitalgraph_term_uuid($1, $2, NULL, NULL)",
        text, term_type,
    )
    await conn.execute(
        f"INSERT INTO {term_table} (term_uuid, term_text, term_type) "
        f"VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        term_uuid, text, term_type,
    )
    return term_uuid


async def _add_quad(conn, space_id: str, s_uuid, p_uuid, o_uuid, g_uuid):
    """Insert a quad."""
    await conn.execute(
        f"INSERT INTO {space_id}_rdf_quad (subject_uuid, predicate_uuid, object_uuid, context_uuid) "
        f"VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
        s_uuid, p_uuid, o_uuid, g_uuid,
    )


async def main():
    import asyncpg

    print("=" * 60)
    print("TEST: Population Pipeline (Vector + Geo)")
    print("=" * 60)
    print(f"  Database: {DB_NAME} @ {DB_HOST}:{DB_PORT}")

    conn = await asyncpg.connect(
        database=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
    )

    try:
        # Setup: extensions + tables
        print("\n  [1] Setting up test space...")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")

        # Check vitalgraph_term_uuid function exists
        fn_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_proc WHERE proname = 'vitalgraph_term_uuid')"
        )
        if not fn_exists:
            print("      ⚠️  vitalgraph_term_uuid function not found, creating it...")
            # Minimal version for testing
            await conn.execute("""
                CREATE OR REPLACE FUNCTION vitalgraph_term_uuid(
                    p_text TEXT, p_type TEXT, p_lang TEXT DEFAULT NULL, p_dt BIGINT DEFAULT NULL
                ) RETURNS UUID LANGUAGE plpgsql IMMUTABLE AS $$
                BEGIN
                    RETURN uuid_generate_v5(
                        'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'::uuid,
                        COALESCE(p_text,'') || '|' || COALESCE(p_type,'') || '|' || COALESCE(p_lang,'') || '|' || COALESCE(p_dt::text,'')
                    );
                END $$;
            """)
            # Also need uuid-ossp for uuid_generate_v5
            try:
                await conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            except Exception:
                pass

        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        schema = SparqlSQLSchema()

        # Clean slate
        try:
            for stmt in schema.drop_vector_data_table_sql(TEST_SPACE, 'entity_default'):
                await conn.execute(stmt)
        except Exception:
            pass
        for stmt in schema.drop_space_tables_sql(TEST_SPACE):
            await conn.execute(stmt)
        for stmt in schema.create_space_tables_sql(TEST_SPACE):
            await conn.execute(stmt)
        for stmt in schema.create_space_indexes_sql(TEST_SPACE):
            await conn.execute(stmt)
        print("      ✅ Tables + indexes created")

        # Register vector index + create data table
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_vector_index "
            f"(index_name, dimensions, distance_metric, provider, model_name, description) "
            f"VALUES ($1, $2, $3, $4, $5, $6)",
            'entity_default', 384, 'cosine', 'vitalsigns',
            'paraphrase-multilingual-MiniLM-L12-v2', 'Test entity embeddings',
        )
        for stmt in schema.create_vector_data_table_sql(TEST_SPACE, 'entity_default', 384):
            await conn.execute(stmt)
        print("      ✅ Vector index registered + data table created")

        # [2] Populate test RDF data
        print("\n  [2] Inserting test RDF data...")

        g_uuid = await _term_uuid(conn, TEST_SPACE, GRAPH_UUID, 'G')

        # Entity 1: Acme Corp (NYC)
        e1_uuid = await _term_uuid(conn, TEST_SPACE, ENTITY1_UUID)
        type_pred = await _term_uuid(conn, TEST_SPACE, RDF_TYPE)
        type_obj = await _term_uuid(conn, TEST_SPACE, KG_ENTITY_TYPE)
        name_pred = await _term_uuid(conn, TEST_SPACE, HAS_NAME)
        desc_pred = await _term_uuid(conn, TEST_SPACE, HAS_DESC)
        kgdesc_pred = await _term_uuid(conn, TEST_SPACE, HAS_KGRAPH_DESC)
        lat_pred = await _term_uuid(conn, TEST_SPACE, HAS_LAT)
        lon_pred = await _term_uuid(conn, TEST_SPACE, HAS_LON)

        name1 = await _term_uuid(conn, TEST_SPACE, "Acme Corporation", 'L')
        desc1 = await _term_uuid(conn, TEST_SPACE, "A leading provider of renewable energy solutions worldwide", 'L')
        kgdesc1 = await _term_uuid(conn, TEST_SPACE, "Acme Corp is a renewable energy solutions company", 'L')
        lat1 = await _term_uuid(conn, TEST_SPACE, "40.730610", 'L')
        lon1 = await _term_uuid(conn, TEST_SPACE, "-73.935242", 'L')

        await _add_quad(conn, TEST_SPACE, e1_uuid, type_pred, type_obj, g_uuid)
        await _add_quad(conn, TEST_SPACE, e1_uuid, name_pred, name1, g_uuid)
        await _add_quad(conn, TEST_SPACE, e1_uuid, desc_pred, desc1, g_uuid)
        await _add_quad(conn, TEST_SPACE, e1_uuid, kgdesc_pred, kgdesc1, g_uuid)
        await _add_quad(conn, TEST_SPACE, e1_uuid, lat_pred, lat1, g_uuid)
        await _add_quad(conn, TEST_SPACE, e1_uuid, lon_pred, lon1, g_uuid)

        # Entity 2: Smith & Associates (LA)
        e2_uuid = await _term_uuid(conn, TEST_SPACE, ENTITY2_UUID)
        name2 = await _term_uuid(conn, TEST_SPACE, "Smith & Associates Law Firm", 'L')
        desc2 = await _term_uuid(conn, TEST_SPACE, "Corporate law firm specializing in mergers and acquisitions", 'L')
        kgdesc2 = await _term_uuid(conn, TEST_SPACE, "Smith & Associates is a corporate law firm", 'L')
        lat2 = await _term_uuid(conn, TEST_SPACE, "34.052235", 'L')
        lon2 = await _term_uuid(conn, TEST_SPACE, "-118.243683", 'L')

        await _add_quad(conn, TEST_SPACE, e2_uuid, type_pred, type_obj, g_uuid)
        await _add_quad(conn, TEST_SPACE, e2_uuid, name_pred, name2, g_uuid)
        await _add_quad(conn, TEST_SPACE, e2_uuid, desc_pred, desc2, g_uuid)
        await _add_quad(conn, TEST_SPACE, e2_uuid, kgdesc_pred, kgdesc2, g_uuid)
        await _add_quad(conn, TEST_SPACE, e2_uuid, lat_pred, lat2, g_uuid)
        await _add_quad(conn, TEST_SPACE, e2_uuid, lon_pred, lon2, g_uuid)

        # Entity 3: Pacific Coffee (Seattle, no geo)
        e3_uuid = await _term_uuid(conn, TEST_SPACE, ENTITY3_UUID)
        name3 = await _term_uuid(conn, TEST_SPACE, "Pacific Northwest Coffee Roasters", 'L')
        desc3 = await _term_uuid(conn, TEST_SPACE, "Artisan coffee roasting company using sustainable beans", 'L')
        kgdesc3 = await _term_uuid(conn, TEST_SPACE, "Pacific Northwest Coffee is an artisan coffee roaster", 'L')

        await _add_quad(conn, TEST_SPACE, e3_uuid, type_pred, type_obj, g_uuid)
        await _add_quad(conn, TEST_SPACE, e3_uuid, name_pred, name3, g_uuid)
        await _add_quad(conn, TEST_SPACE, e3_uuid, desc_pred, desc3, g_uuid)
        await _add_quad(conn, TEST_SPACE, e3_uuid, kgdesc_pred, kgdesc3, g_uuid)

        print("      ✅ 3 entities with properties inserted")

        # [3] Test search_text builder
        print("\n  [3] Testing search_text builder...")
        from vitalgraph.vectorization.search_text_builder import (
            MappingRule,
            build_search_text,
            fetch_literal_properties,
            resolve_mapping,
        )

        # 3a. Fallback mode (no rule) — includes all properties
        props = await fetch_literal_properties(conn, TEST_SPACE, e1_uuid, g_uuid)
        assert len(props) > 0, "No properties found for entity 1"
        text_all = build_search_text(props)
        print(f"      Fallback (all props): '{text_all[:80]}...'")
        assert "Acme Corporation" in text_all
        assert "renewable energy" in text_all

        # 3b. Default mode — uses hasKGraphDescription only
        default_rule = MappingRule(source_type="default")
        text_default = build_search_text(props, default_rule)
        print(f"      Default (hasKGraphDescription): '{text_default[:80]}'")
        assert "renewable energy solutions company" in text_default
        assert "Acme Corporation" not in text_default  # hasName not used in default

        # 3c. Properties mode — explicit predicate list
        prop_rule = MappingRule(
            source_type="properties",
            include_uris=[HAS_NAME, HAS_DESC],
            separator=". ",
        )
        text_props = build_search_text(props, prop_rule)
        print(f"      Properties override: '{text_props[:80]}'")
        assert "Acme Corporation" in text_props
        assert "renewable energy solutions worldwide" in text_props
        assert "40.730610" not in text_props  # lat excluded

        print("      ✅ search_text builder: all 3 modes work")

        # [3d] Test mapping table resolution
        print("\n  [3d] Testing mapping table resolution...")
        # Insert a mapping override for 'kgentity' class-level
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_vector_mapping "
            f"(mapping_type, type_uri, index_name, source_type, separator, include_type_desc) "
            f"VALUES ($1, NULL, $2, $3, $4, $5)",
            'kgentity', 'entity_default', 'properties', '. ', False,
        )
        mapping_id = await conn.fetchval(
            f"SELECT mapping_id FROM {TEST_SPACE}_vector_mapping WHERE mapping_type = 'kgentity'"
        )
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_vector_mapping_property "
            f"(mapping_id, property_uri, property_role, ordinal) VALUES ($1, $2, $3, $4)",
            mapping_id, HAS_NAME, 'include', 1,
        )
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_vector_mapping_property "
            f"(mapping_id, property_uri, property_role, ordinal) VALUES ($1, $2, $3, $4)",
            mapping_id, HAS_DESC, 'include', 2,
        )

        resolved = await resolve_mapping(conn, TEST_SPACE, 'entity_default', 'kgentity')
        assert resolved is not None, "Mapping should resolve"
        assert resolved.source_type == 'properties'
        assert len(resolved.include_uris) == 2
        assert resolved.include_uris[0] == HAS_NAME
        print(f"      Resolved mapping: source_type={resolved.source_type}, {len(resolved.include_uris)} properties")

        text_resolved = build_search_text(props, resolved)
        assert "Acme Corporation" in text_resolved
        assert "40.730610" not in text_resolved
        print(f"      Resolved text: '{text_resolved[:80]}'")

        # Clean up the mapping (so vector population uses default)
        await conn.execute(f"DELETE FROM {TEST_SPACE}_vector_mapping WHERE mapping_id = $1", mapping_id)
        print("      ✅ Mapping table resolution works")

        # [4] Run vector population pipeline
        print("\n  [4] Running vector population pipeline...")
        from vitalgraph.vectorization.vector_populator import populate_index

        # 4a. Opt-in model: no mapping → should skip (0 stored)
        vec_stats_skip = await populate_index(
            conn, TEST_SPACE, 'entity_default', g_uuid,
            type_uri=KG_ENTITY_TYPE,
            mapping_type='kgentity',
        )
        assert vec_stats_skip.embeddings_stored == 0, \
            f"Expected 0 (no mapping), got {vec_stats_skip.embeddings_stored}"
        print("      ✅ Opt-in: no mapping → 0 stored (correct)")

        # 4b. Enable vectorization at class level
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_vector_mapping "
            f"(mapping_type, type_uri, index_name, enabled, source_type) "
            f"VALUES ($1, NULL, $2, $3, $4)",
            'kgentity', 'entity_default', True, 'default',
        )
        print("      Inserted class-level mapping: kgentity → enabled=true, source_type=default")

        vec_stats = await populate_index(
            conn, TEST_SPACE, 'entity_default', g_uuid,
            type_uri=KG_ENTITY_TYPE,
            mapping_type='kgentity',
        )
        print(f"      Processed: {vec_stats.subjects_processed}")
        print(f"      Stored: {vec_stats.embeddings_stored}")
        print(f"      Skipped: {vec_stats.subjects_skipped}")
        print(f"      Time: {vec_stats.elapsed_seconds:.2f}s")
        # With default mode, entities have hasKGraphDescription so all 3 should be stored
        assert vec_stats.embeddings_stored == 3, f"Expected 3, got {vec_stats.embeddings_stored}"
        assert not vec_stats.errors, f"Errors: {vec_stats.errors}"
        print("      ✅ 3 embeddings stored")

        # [5] Verify vector similarity search
        print("\n  [5] Testing vector similarity search...")
        from vitalgraph.vectorization.registry import get_provider
        provider = get_provider("vitalsigns", {"device": "cpu"})
        query_vec = await provider.vectorize_text("renewable energy company")
        query_vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

        results = await conn.fetch(
            f"SELECT subject_uuid, 1 - (embedding <=> $1::vector) AS similarity "
            f"FROM {TEST_SPACE}_vec_entity_default "
            f"WHERE context_uuid = $2 "
            f"ORDER BY embedding <=> $1::vector "
            f"LIMIT 3",
            query_vec_str, g_uuid,
        )
        assert len(results) == 3
        print(f"      Top result similarity: {results[0]['similarity']:.4f}")
        # Acme (renewable energy) should rank higher than law firm
        sims = {str(r['subject_uuid']): r['similarity'] for r in results}
        print(f"      All similarities: { {k[:8]: f'{v:.4f}' for k, v in sims.items()} }")
        print("      ✅ Vector similarity search works")

        # [6] Verify full-text search (tsvector)
        print("\n  [6] Testing full-text search...")
        fts_results = await conn.fetch(
            f"SELECT subject_uuid, ts_rank_cd(tsv, plainto_tsquery('english', $1)) AS rank "
            f"FROM {TEST_SPACE}_vec_entity_default "
            f"WHERE tsv @@ plainto_tsquery('english', $1) "
            f"ORDER BY rank DESC",
            "renewable energy",
        )
        assert len(fts_results) >= 1, "FTS should find at least 1 result for 'renewable energy'"
        print(f"      FTS results: {len(fts_results)}")
        for r in fts_results:
            print(f"        {str(r['subject_uuid'])[:8]}... rank={r['rank']:.4f}")
        print("      ✅ Full-text search works")

        # [7] Run geo population pipeline
        print("\n  [7] Running geo population pipeline...")
        from vitalgraph.vectorization.geo_populator import populate_geo
        geo_stats = await populate_geo(conn, TEST_SPACE, g_uuid)
        print(f"      Scanned: {geo_stats.subjects_scanned}")
        print(f"      Upserted: {geo_stats.points_upserted}")
        print(f"      Incomplete: {geo_stats.incomplete_pairs}")
        assert geo_stats.points_upserted == 2, f"Expected 2, got {geo_stats.points_upserted}"
        assert not geo_stats.errors, f"Errors: {geo_stats.errors}"
        print("      ✅ 2 geo points populated")

        # [8] Verify spatial query
        print("\n  [8] Testing spatial query (ST_DWithin)...")
        # Find entities within 100km of NYC (40.73, -73.94)
        geo_results = await conn.fetch(
            f"SELECT subject_uuid, "
            f"  ST_Distance(location, ST_MakePoint(-73.94, 40.73)::geography) AS distance_m "
            f"FROM {TEST_SPACE}_geo "
            f"WHERE ST_DWithin(location, ST_MakePoint(-73.94, 40.73)::geography, 100000) "
            f"  AND context_uuid = $1",
            g_uuid,
        )
        assert len(geo_results) == 1, f"Expected 1 near NYC, got {len(geo_results)}"
        print(f"      Found {len(geo_results)} entity within 100km of NYC")
        print(f"      Distance: {geo_results[0]['distance_m']:.0f}m")
        print("      ✅ Spatial query works")

        # [9] Test incremental update
        print("\n  [9] Testing incremental update...")
        from vitalgraph.vectorization.vector_populator import update_subject_vector
        ok = await update_subject_vector(
            conn, TEST_SPACE, 'entity_default', e1_uuid, g_uuid,
        )
        assert ok, "Incremental update failed"
        print("      ✅ Single-subject re-vectorization works")

        # [10] Cleanup
        print("\n  [10] Cleaning up...")
        for stmt in schema.drop_vector_data_table_sql(TEST_SPACE, 'entity_default'):
            await conn.execute(stmt)
        for stmt in schema.drop_space_tables_sql(TEST_SPACE):
            await conn.execute(stmt)
        print("      ✅ All test tables dropped")

        print("\n" + "=" * 60)
        print("  ✅ ALL TESTS PASSED — Population Pipeline works")
        print("=" * 60 + "\n")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
