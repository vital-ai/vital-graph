#!/usr/bin/env python3
"""
Quad Table Low-Level Query Test Script
=====================================

Low-level database testing of the RDF quad table with the new schema:
- quad_uuid column for unique identification
- Primary key (subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid)
- Support for duplicate quads with different quad_uuid values
- Physical clustering by subject for efficient range queries

Assumes test data has been loaded by:
- reload_test_data.py
- reload_wordnet_data.py
"""

import asyncio
import logging
import sys
import time
import uuid
from pathlib import Path
import psycopg.rows

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
from vitalgraph.db.postgresql.postgresql_space_impl import PostgreSQLSpaceImpl
from vitalgraph.db.postgresql.postgresql_log_utils import PostgreSQLLogUtils
from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

# Global variables for database connection
impl = None
sparql_impl = None
space_impl = None

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl, space_impl
    
    print("🔌 Setting up database connection...")
    
    # Initialize VitalGraphImpl with config file
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
    from vitalgraph.config.config_loader import get_config
    config = get_config(str(config_path))
    
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    # Get space implementation for direct database operations
    space_impl = impl.db_impl.get_space_impl()
    
    # Initialize SPARQL implementation for any SPARQL operations
    sparql_impl = PostgreSQLSparqlImpl(space_impl)
    
    print(f"✅ Connected to database")

async def cleanup_connection():
    """Clean up database connection."""
    global impl, sparql_impl, space_impl
    
    if impl:
        await impl.db_impl.disconnect()
        print("🔌 Database connection closed")
    
    # Clear global references
    impl = None
    sparql_impl = None
    space_impl = None

async def run_sql_query(name, sql_query, params=None, limit_results=10):
    """Execute a raw SQL query and display results."""
    print(f"\n  {name}:")
    print(f"    SQL: {sql_query}")
    if params:
        print(f"    Params: {params}")
    
    try:
        start_time = time.time()
        
        # Use async context manager with pooled connection
        async with space_impl.get_db_connection() as conn:
            # Configure row factory for dict results
            conn.row_factory = psycopg.rows.dict_row
            cursor = conn.cursor()
            cursor.execute(sql_query, params or [])
            results = cursor.fetchall()
            
        query_time = time.time() - start_time
        
        print(f"    ⏱️  {query_time:.3f}s | {len(results)} results")
        
        # Show limited results for readability
        for i, result in enumerate(results[:limit_results]):
            if isinstance(result, dict):
                print(f"    [{i+1}] {dict(result)}")
            else:
                print(f"    [{i+1}] {result}")
        
        if len(results) > limit_results:
            print(f"    ... and {len(results) - limit_results} more results")
            
        return results
            
    except Exception as e:
        print(f"    ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return []

async def test_quad_table_schema():
    """Test the quad table schema and structure."""
    print("\n📋 QUAD TABLE SCHEMA:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    
    print(f"  Using quad table: {quad_table_name}")
    
    # Check table structure
    await run_sql_query("Table structure", f"""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns 
        WHERE table_name = '{quad_table_name}'
        ORDER BY ordinal_position
    """)
    
    # Check primary key
    await run_sql_query("Primary key definition", f"""
        SELECT constraint_name, column_name, ordinal_position
        FROM information_schema.key_column_usage 
        WHERE table_name = '{quad_table_name}' 
        AND constraint_name LIKE '%%_pkey'
        ORDER BY ordinal_position
    """)
    
    # Check indexes
    await run_sql_query("Table indexes", f"""
        SELECT indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename = '{quad_table_name}'
        ORDER BY indexname
    """)

async def test_basic_quad_counts():
    """Test basic quad counting and statistics."""
    print("\n📊 BASIC QUAD STATISTICS:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    term_table_name = table_names.get('term')
    
    print(f"  Using tables: {quad_table_name}, {term_table_name}")
    
    # Total quad count
    await run_sql_query("Total quads", f"""
        SELECT COUNT(*) as total_quads FROM {quad_table_name}
    """)
    
    # Unique SPOC combinations vs total quads (shows duplicates)
    await run_sql_query("Unique SPOC vs Total", f"""
        SELECT 
            COUNT(DISTINCT (subject_uuid, predicate_uuid, object_uuid, context_uuid)) as unique_spoc,
            COUNT(*) as total_quads,
            COUNT(*) - COUNT(DISTINCT (subject_uuid, predicate_uuid, object_uuid, context_uuid)) as duplicates
        FROM {quad_table_name}
    """)
    
    # Unique elements count
    await run_sql_query("Unique elements", f"""
        SELECT 
            COUNT(DISTINCT subject_uuid) as unique_subjects,
            COUNT(DISTINCT predicate_uuid) as unique_predicates,
            COUNT(DISTINCT object_uuid) as unique_objects,
            COUNT(DISTINCT context_uuid) as unique_contexts,
            COUNT(DISTINCT quad_uuid) as unique_quad_uuids
        FROM {quad_table_name}
    """)

async def test_duplicate_quad_detection():
    """Test detection and handling of duplicate quads."""
    print("\n🔍 DUPLICATE QUAD DETECTION:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    term_table_name = table_names.get('term')
    
    print(f"  Using tables: {quad_table_name}, {term_table_name}")
    
    # Find SPOC combinations that have duplicates
    await run_sql_query("SPOC combinations with duplicates", f"""
        SELECT 
            subject_uuid, predicate_uuid, object_uuid, context_uuid,
            COUNT(*) as duplicate_count,
            COUNT(DISTINCT quad_uuid) as unique_quad_uuids
        FROM {quad_table_name}
        GROUP BY subject_uuid, predicate_uuid, object_uuid, context_uuid
        HAVING COUNT(*) > 1
        ORDER BY duplicate_count DESC
    """)
    
    # Show details of actual duplicate quads with human-readable terms
    await run_sql_query("Duplicate quad details", f"""
        SELECT 
            s.term_text as subject,
            p.term_text as predicate, 
            o.term_text as object,
            c.term_text as context,
            q.quad_uuid,
            q.created_time
        FROM {quad_table_name} q
        JOIN {term_table_name} s ON q.subject_uuid = s.term_uuid
        JOIN {term_table_name} p ON q.predicate_uuid = p.term_uuid
        JOIN {term_table_name} o ON q.object_uuid = o.term_uuid
        JOIN {term_table_name} c ON q.context_uuid = c.term_uuid
        WHERE (q.subject_uuid, q.predicate_uuid, q.object_uuid, q.context_uuid) IN (
            SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid
            FROM {quad_table_name} d
            GROUP BY subject_uuid, predicate_uuid, object_uuid, context_uuid
            HAVING COUNT(*) > 1
            LIMIT 5  -- Just show first 5 duplicate groups
        )
        ORDER BY q.created_time
    """)

async def test_subject_range_queries():
    """Test subject-based range queries to verify clustering performance."""
    print("\n🎯 SUBJECT RANGE QUERIES:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    term_table_name = table_names.get('term')
    
    print(f"  Using tables: {quad_table_name}, {term_table_name}")
    
    # Get some sample subject UUIDs for range testing
    sample_subjects = await run_sql_query("Sample subject UUIDs", f"""
        SELECT DISTINCT subject_uuid 
        FROM {quad_table_name} 
        ORDER BY subject_uuid 
        LIMIT 5
    """, limit_results=5)
    
    if sample_subjects:
        # Test range query between two subjects
        start_uuid = sample_subjects[0]['subject_uuid'] if len(sample_subjects) > 0 else None
        end_uuid = sample_subjects[2]['subject_uuid'] if len(sample_subjects) > 2 else start_uuid
        
        if start_uuid and end_uuid:
            await run_sql_query("Subject UUID range query", f"""
                SELECT 
                    COUNT(*) as quads_in_range,
                    COUNT(DISTINCT subject_uuid) as subjects_in_range
                FROM {quad_table_name}
                WHERE subject_uuid BETWEEN %s AND %s
            """, [start_uuid, end_uuid])
    
    # Test subject-based clustering efficiency
    await run_sql_query("Quads per subject (top 10)", f"""
        SELECT 
            s.term_text as subject,
            COUNT(*) as quad_count
        FROM {quad_table_name} q
        JOIN {term_table_name} s ON q.subject_uuid = s.term_uuid
        GROUP BY q.subject_uuid, s.term_text
        ORDER BY quad_count DESC
        LIMIT 10
    """)

async def test_quad_uuid_uniqueness():
    """Test quad_uuid uniqueness and generation."""
    print("\n🔑 QUAD UUID UNIQUENESS:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    
    print(f"  Using quad table: {quad_table_name}")
    
    # Verify all quad_uuids are unique
    await run_sql_query("Quad UUID uniqueness check", f"""
        SELECT 
            COUNT(*) as total_quads,
            COUNT(DISTINCT quad_uuid) as unique_quad_uuids,
            CASE 
                WHEN COUNT(*) = COUNT(DISTINCT quad_uuid) THEN 'PASS'
                ELSE 'FAIL'
            END as uniqueness_test
        FROM {quad_table_name}
    """)
    
    # Check quad_uuid format (should be valid UUIDs)
    await run_sql_query("Sample quad UUIDs", f"""
        SELECT quad_uuid, created_time
        FROM {quad_table_name}
        ORDER BY created_time DESC
        LIMIT 5
    """)
    
    # Verify quad_uuid is not null
    await run_sql_query("Null quad_uuid check", f"""
        SELECT COUNT(*) as null_quad_uuids
        FROM {quad_table_name}
        WHERE quad_uuid IS NULL
    """)

async def test_performance_queries():
    """Test performance-critical queries."""
    print("\n⚡ PERFORMANCE QUERIES:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    term_table_name = table_names.get('term')
    
    print(f"  Using tables: {quad_table_name}, {term_table_name}")
    
    # Test primary key lookup (should be very fast)
    sample_quad = await run_sql_query("Sample quad for PK test", f"""
        SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid, quad_uuid
        FROM {quad_table_name}
        LIMIT 1
    """, limit_results=1)
    
    if sample_quad:
        quad = sample_quad[0]
        s_uuid = quad['subject_uuid']
        p_uuid = quad['predicate_uuid']
        o_uuid = quad['object_uuid']
        c_uuid = quad['context_uuid']
        q_uuid = quad['quad_uuid']
        
        await run_sql_query("Primary key lookup", f"""
            SELECT COUNT(*)
            FROM {quad_table_name}
            WHERE subject_uuid = %s 
              AND predicate_uuid = %s 
              AND object_uuid = %s 
              AND context_uuid = %s 
              AND quad_uuid = %s
        """, [s_uuid, p_uuid, o_uuid, c_uuid, q_uuid])
    
    # Test subject index usage
    await run_sql_query("Subject-based query", f"""
        SELECT COUNT(*)
        FROM {quad_table_name}
        WHERE subject_uuid = (
            SELECT subject_uuid FROM {quad_table_name} LIMIT 1
        )
    """)
    
    # Test join performance with term table
    await run_sql_query("Quad-Term join performance", f"""
        SELECT COUNT(*)
        FROM {quad_table_name} q
        JOIN {term_table_name} s ON q.subject_uuid = s.term_uuid
        WHERE s.term_type = 'U'
    """)

async def test_clustering_analysis():
    """Analyze physical clustering and storage patterns."""
    print("\n🗂️  CLUSTERING ANALYSIS:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    
    print(f"  Using quad table: {quad_table_name}")
    
    # Check if table is clustered
    await run_sql_query("Table clustering status", f"""
        SELECT 
            schemaname, tablename, attname, n_distinct, correlation
        FROM pg_stats 
        WHERE tablename = '{quad_table_name}' 
          AND attname IN ('subject_uuid', 'predicate_uuid', 'object_uuid', 'context_uuid')
        ORDER BY attname
    """)
    
    # Analyze storage pages and clustering
    await run_sql_query("Table size and pages", f"""
        SELECT 
            pg_size_pretty(pg_total_relation_size('{quad_table_name}')) as total_size,
            pg_size_pretty(pg_relation_size('{quad_table_name}')) as table_size,
            (pg_relation_size('{quad_table_name}') / 8192) as pages_used
    """)

async def test_insert_duplicate_quad():
    """Test inserting duplicate quads to verify schema works correctly."""
    print("\n➕ DUPLICATE QUAD INSERTION TEST:")
    
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    
    print(f"  Using quad table: {quad_table_name}")
    
    sample_quad = await run_sql_query("Get sample quad for duplication", f"""
        SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid
        FROM {quad_table_name}
        LIMIT 1
    """, limit_results=1)
    
    if sample_quad:
        quad = sample_quad[0]
        s_uuid = quad['subject_uuid']
        p_uuid = quad['predicate_uuid']
        o_uuid = quad['object_uuid']
        c_uuid = quad['context_uuid']
        
        # Count existing instances
        existing_count = await run_sql_query("Count existing instances", f"""
            SELECT COUNT(*) as existing_count
            FROM {quad_table_name}
            WHERE subject_uuid = %s 
              AND predicate_uuid = %s 
              AND object_uuid = %s 
              AND context_uuid = %s
        """, [s_uuid, p_uuid, o_uuid, c_uuid])
        
        if existing_count:
            original_count = existing_count[0]['existing_count']
            
            # Insert duplicate (should succeed with new quad_uuid)
            try:
                # Use async context manager with pooled connection
                async with space_impl.get_db_connection() as conn:
                    # Configure row factory for dict results
                    conn.row_factory = psycopg.rows.dict_row
                    cursor = conn.cursor()
                    cursor.execute(f"""
                        INSERT INTO {quad_table_name} 
                        (subject_uuid, predicate_uuid, object_uuid, context_uuid, created_time)
                        VALUES (%s, %s, %s, %s, NOW())
                        RETURNING quad_uuid
                    """, [s_uuid, p_uuid, o_uuid, c_uuid])
                    
                    result = cursor.fetchone()
                    new_quad_uuid = result[0] if result else None
                    conn.commit()
                    
                    print(f"    ✅ Successfully inserted duplicate quad with UUID: {new_quad_uuid}")
                    
                    # Verify count increased
                    new_count = await run_sql_query("Count after duplicate insert", f"""
                        SELECT COUNT(*) as new_count
                        FROM {quad_table_name}
                        WHERE subject_uuid = %s 
                          AND predicate_uuid = %s 
                          AND object_uuid = %s 
                          AND context_uuid = %s
                    """, [s_uuid, p_uuid, o_uuid, c_uuid])
                    
                    if new_count and new_count[0]['new_count'] == original_count + 1:
                        print(f"    ✅ Duplicate insertion verified: {original_count} -> {new_count[0][0]} instances")
                    
                    # Clean up - remove the test duplicate
                    cursor.execute(f"""
                        DELETE FROM {quad_table_name} 
                        WHERE quad_uuid = %s
                    """, [new_quad_uuid])
                    conn.commit()
                    print(f"    🧹 Cleaned up test duplicate")
                    
            except Exception as e:
                print(f"    ❌ Failed to insert duplicate: {e}")

async def main():
    """Main test controller."""
    print("🧪 Quad Table Low-Level Query Test Suite")
    print("=" * 50)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Comprehensive test suite
        await test_quad_table_schema()
        await test_basic_quad_counts()
        await test_duplicate_quad_detection()
        await test_subject_range_queries()
        await test_quad_uuid_uniqueness()
        await test_performance_queries()
        await test_clustering_analysis()
        # await test_insert_duplicate_quad()
        
    finally:
        # Cleanup
        await cleanup_connection()
        print("\n✅ Quad Table Query Test Complete!")

if __name__ == "__main__":
    asyncio.run(main())
