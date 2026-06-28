"""
Test the vector/geo DDL in sparql_sql_schema.py against a real PostgreSQL database.

Verifies:
1. Extensions (vector, postgis) can be created
2. Per-space tables (vector_index, vector_mapping, geo) are created
3. Dynamic vector data table creation works
4. HNSW index is created on vector data table
5. GiST index is created on geo table
6. Cleanup (drop) works correctly

Usage:
    python test_scripts/vectorization/test_vector_geo_schema.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

DB_NAME = os.environ.get("VITALGRAPH_DB", "sparql_sql_graph")
DB_USER = os.environ.get("VITALGRAPH_DB_USER", "postgres")
DB_HOST = os.environ.get("VITALGRAPH_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("VITALGRAPH_DB_PORT", "5432"))

TEST_SPACE = "test_vec_geo"


async def main():
    import asyncpg

    print("=" * 60)
    print("TEST: Vector/Geo Schema DDL")
    print("=" * 60)
    print(f"  Database: {DB_NAME} @ {DB_HOST}:{DB_PORT}")

    conn = await asyncpg.connect(
        database=DB_NAME, user=DB_USER, host=DB_HOST, port=DB_PORT
    )

    has_postgis = False

    try:
        # 1. Create extensions
        print("\n  [1] Creating extensions...")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
            has_postgis = True
        except Exception as e:
            print(f"      ⚠️  PostGIS not available locally (skipping geo tests): {e}")

        print(f"      ✅ pg_trgm, vector" + (", postgis" if has_postgis else ""))

        # Verify extension versions
        row = await conn.fetchrow("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        print(f"      pgvector version: {row['extversion']}")
        if has_postgis:
            row = await conn.fetchrow("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
            print(f"      PostGIS version: {row['extversion']}")

        # 2. Create per-space tables using SparqlSQLSchema
        print("\n  [2] Creating per-space tables...")
        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        schema = SparqlSQLSchema()

        # Drop first (clean slate)
        for stmt in schema.drop_space_tables_sql(TEST_SPACE):
            await conn.execute(stmt)

        for stmt in schema.create_space_tables_sql(TEST_SPACE):
            await conn.execute(stmt)
        print("      ✅ All per-space tables created")

        # 3. Create indexes
        print("\n  [3] Creating per-space indexes...")
        for stmt in schema.create_space_indexes_sql(TEST_SPACE):
            await conn.execute(stmt)
        print("      ✅ All per-space indexes created")

        # 4. Verify vector_index table exists and has correct columns
        print("\n  [4] Verifying vector_index table...")
        cols = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = $1 ORDER BY ordinal_position",
            f"{TEST_SPACE}_vector_index"
        )
        col_names = [r['column_name'] for r in cols]
        expected = ['index_id', 'index_name', 'dimensions', 'distance_metric',
                    'provider', 'model_name', 'provider_config', 'description', 'created_time']
        assert set(expected).issubset(set(col_names)), f"Missing columns: {set(expected) - set(col_names)}"
        print(f"      ✅ Columns: {col_names}")

        # 5. Verify geo table exists with geography column
        print("\n  [5] Verifying geo table...")
        cols = await conn.fetch(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_name = $1 ORDER BY ordinal_position",
            f"{TEST_SPACE}_geo"
        )
        col_map = {r['column_name']: r['udt_name'] for r in cols}
        assert 'location' in col_map, "Missing 'location' column"
        assert col_map['location'] == 'geography', f"Expected geography type, got {col_map['location']}"
        print(f"      ✅ Columns: {list(col_map.keys())}")
        print(f"      ✅ location type: {col_map['location']}")

        # 6. Register a vector index and create its data table
        print("\n  [6] Registering vector index + creating data table...")
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_vector_index "
            f"(index_name, dimensions, distance_metric, provider, model_name, description) "
            f"VALUES ($1, $2, $3, $4, $5, $6)",
            'entity_default', 384, 'cosine', 'vitalsigns',
            'paraphrase-multilingual-MiniLM-L12-v2', 'Default entity embeddings'
        )
        print("      ✅ Inserted vector index record: entity_default (384d, cosine)")

        # Create the dynamic data table
        for stmt in schema.create_vector_data_table_sql(TEST_SPACE, 'entity_default', 384, 'cosine'):
            await conn.execute(stmt)
        print("      ✅ Created data table: test_vec_geo_vec_entity_default")

        # 7. Verify vector data table structure
        print("\n  [7] Verifying vector data table...")
        cols = await conn.fetch(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_name = $1 ORDER BY ordinal_position",
            f"{TEST_SPACE}_vec_entity_default"
        )
        col_map = {r['column_name']: r['udt_name'] for r in cols}
        assert 'embedding' in col_map, "Missing 'embedding' column"
        assert 'search_text' in col_map, "Missing 'search_text' column"
        assert 'tsv' in col_map, "Missing 'tsv' column"
        print(f"      ✅ Columns: {list(col_map.keys())}")

        # 8. Verify HNSW index exists
        print("\n  [8] Verifying HNSW index on vector data table...")
        idx = await conn.fetchrow(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE indexname = $1",
            f"idx_{TEST_SPACE}_vec_entity_default_hnsw"
        )
        assert idx is not None, "HNSW index not found"
        assert 'hnsw' in idx['indexdef'].lower()
        print(f"      ✅ {idx['indexname']}")

        # 9. Verify GiST index on geo table
        print("\n  [9] Verifying GiST index on geo table...")
        idx = await conn.fetchrow(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE indexname = $1",
            f"idx_{TEST_SPACE}_geo_gist"
        )
        assert idx is not None, "GiST index not found"
        assert 'gist' in idx['indexdef'].lower()
        print(f"      ✅ {idx['indexname']}")

        # 10. Insert test data into vector data table
        print("\n  [10] Inserting test vector data...")
        import struct
        # Create a dummy 384-dim vector (pgvector binary format via SQL cast)
        dummy_vec = '[' + ','.join(['0.1'] * 384) + ']'
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_vec_entity_default "
            f"(subject_uuid, context_uuid, embedding, search_text) "
            f"VALUES ($1, $2, $3::vector, $4)",
            '00000000-0000-0000-0000-000000000001',
            '00000000-0000-0000-0000-000000000099',
            dummy_vec,
            'Acme Corporation renewable energy solutions'
        )
        row = await conn.fetchrow(
            f"SELECT subject_uuid, tsv IS NOT NULL as has_tsv "
            f"FROM {TEST_SPACE}_vec_entity_default "
            f"WHERE subject_uuid = $1",
            '00000000-0000-0000-0000-000000000001',
        )
        assert row is not None
        assert row['has_tsv'] is True, "tsvector not generated"
        print("      ✅ Vector + search_text inserted, tsvector auto-generated")

        # 11. Insert test geo data
        print("\n  [11] Inserting test geo data...")
        await conn.execute(
            f"INSERT INTO {TEST_SPACE}_geo "
            f"(subject_uuid, location, latitude, longitude, context_uuid) "
            f"VALUES ($1, ST_MakePoint($3, $2)::geography, $2, $3, $4)",
            '00000000-0000-0000-0000-000000000001',
            40.730610,   # latitude
            -73.935242,  # longitude
            '00000000-0000-0000-0000-000000000099',
        )

        # Verify ST_DWithin works
        row = await conn.fetchrow(
            f"SELECT subject_uuid FROM {TEST_SPACE}_geo "
            f"WHERE ST_DWithin(location, ST_MakePoint(-73.935, 40.731)::geography, 1000)"
        )
        assert row is not None, "ST_DWithin query returned no results"
        print("      ✅ Geo point inserted, ST_DWithin query works (1km radius)")

        # 12. Cleanup
        print("\n  [12] Cleaning up...")
        for stmt in schema.drop_vector_data_table_sql(TEST_SPACE, 'entity_default'):
            await conn.execute(stmt)
        for stmt in schema.drop_space_tables_sql(TEST_SPACE):
            await conn.execute(stmt)
        print("      ✅ All test tables dropped")

        print("\n" + "=" * 60)
        print("  ✅ ALL TESTS PASSED — Vector/Geo DDL is correct")
        print("=" * 60 + "\n")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
