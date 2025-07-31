#!/usr/bin/env python3
"""
Quad RDF CRUD Operations Test Script
====================================

Comprehensive testing of high-level quad CRUD operations including:
- Create (add_quad, batch_add_quads)
- Read (get_quad_count, query operations)
- Update (not directly supported in RDF - tested via delete+add)
- Delete (remove_quad, batch_remove_quads)

Tests both success and failure cases, validates correctness and performance.
Uses high-level interface with low-level DB verification as needed.
"""

import asyncio
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import List, Tuple, Optional

import psycopg.rows

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.db.postgresql.postgresql_sparql_impl import PostgreSQLSparqlImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.postgresql_log_utils import PostgreSQLLogUtils
from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils
from rdflib import URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, XSD

# Reduce logging chatter
logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)

# Configuration
SPACE_ID = "space_test"
GRAPH_URI = "http://vital.ai/graph/test"
GLOBAL_GRAPH_URI = "urn:___GLOBAL"

# Test data URIs
TEST_SUBJECT_BASE = "http://test.crud.org/subject"
TEST_PREDICATE_BASE = "http://test.crud.org/predicate"
TEST_OBJECT_BASE = "http://test.crud.org/object"

# Global variables for database connection
impl = None
sparql_impl = None
space_impl = None

def create_test_quad(subject_id: str, predicate: str, object_val: str, is_literal: bool = False) -> Tuple:
    """Create a test quad tuple."""
    subject = URIRef(f"{TEST_SUBJECT_BASE}/{subject_id}")
    pred = URIRef(f"{TEST_PREDICATE_BASE}/{predicate}")
    
    if is_literal:
        obj = Literal(object_val)
    else:
        obj = URIRef(f"{TEST_OBJECT_BASE}/{object_val}")
    
    context = URIRef(GRAPH_URI)
    return (subject, pred, obj, context)

async def verify_quad_count(expected_count: int, description: str, context_uri: Optional[str] = None) -> bool:
    """Verify quad count matches expected value using high-level API."""
    try:
        actual_count = await space_impl.get_quad_count(SPACE_ID, context_uri)
        if actual_count == expected_count:
            print(f"    ✅ {description}: {actual_count} quads")
            return True
        else:
            print(f"    ❌ {description}: Expected {expected_count}, got {actual_count}")
            return False
    except Exception as e:
        print(f"    ❌ {description}: Error getting count - {e}")
        return False

async def debug_term_storage(quad: Tuple) -> None:
    """Debug function to see how terms are actually stored vs. queried."""
    try:
        subject, predicate, obj, context = quad
        table_names = space_impl._get_table_names(SPACE_ID)
        term_table_name = table_names.get('term')
        
        print(f"    🔍 DEBUG: Investigating term storage for quad:")
        print(f"      Subject: {repr(subject)} -> {str(subject)}")
        print(f"      Predicate: {repr(predicate)} -> {str(predicate)}")
        print(f"      Object: {repr(obj)} -> {str(obj)}")
        print(f"      Context: {repr(context)} -> {str(context)}")
        
        # Check what terms actually exist in the database
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            cursor = conn.cursor()
            
            # Look for terms that might match our quad terms
            for term_name, term_value in [("subject", subject), ("predicate", predicate), ("object", obj), ("context", context)]:
                cursor.execute(f"""
                    SELECT term_text, term_type, lang, datatype_id, term_uuid
                    FROM {term_table_name} 
                    WHERE term_text LIKE %s
                    LIMIT 5
                """, [f"%{str(term_value)[-20:]}%"])  # Match last 20 chars
                
                results = cursor.fetchall()
                print(f"      {term_name} matches: {len(results)} found")
                for result in results:
                    print(f"        - {result['term_text'][:50]}... (type: {result['term_type']}, uuid: {result['term_uuid']})")
                    
    except Exception as e:
        print(f"    ❌ DEBUG error: {e}")

async def debug_term_insertion_process(quad: Tuple, operation: str = "unknown") -> None:
    """Debug the term insertion process during quad creation."""
    try:
        subject, predicate, obj, context = quad
        table_names = space_impl._get_table_names(SPACE_ID)
        term_table_name = table_names.get('term')
        
        print(f"    🔧 DEBUG [{operation}]: Checking term insertion process:")
        
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            cursor = conn.cursor()
            
            # Count total terms before
            cursor.execute(f"SELECT COUNT(*) as count FROM {term_table_name}")
            before_count = cursor.fetchone()['count']
            print(f"      Terms in DB before: {before_count}")
            
            # Check if specific terms exist before
            terms_to_check = {
                "S": str(subject),
                "P": str(predicate), 
                "O": str(obj),
                "G": str(context)
            }
            
            before_exists = {}
            for name, term_text in terms_to_check.items():
                cursor.execute(f"SELECT COUNT(*) as count FROM {term_table_name} WHERE term_text = %s", [term_text])
                count = cursor.fetchone()['count']
                before_exists[name] = count > 0
                print(f"      {name} exists before: {before_exists[name]} ('{term_text[:30]}...')")
                    
    except Exception as e:
        print(f"    ❌ DEBUG term insertion error: {e}")

async def debug_quad_terms(quad: Tuple, operation: str = "unknown") -> None:
    """Debug function to investigate term storage and retrieval for a quad."""
    try:
        subject, predicate, obj, context = quad
        table_names = space_impl._get_table_names(SPACE_ID)
        term_table_name = table_names.get('term')
        quad_table_name = table_names.get('rdf_quad')
        
        print(f"    🔍 DEBUG [{operation}]: Investigating quad terms:")
        print(f"      S: {repr(subject)} -> '{str(subject)}'")
        print(f"      P: {repr(predicate)} -> '{str(predicate)}'")
        print(f"      O: {repr(obj)} -> '{str(obj)}'")
        print(f"      G: {repr(context)} -> '{str(context)}'")
        
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            cursor = conn.cursor()
            
            # Check if terms exist in database
            term_matches = {}
            for term_name, term_value in [("S", subject), ("P", predicate), ("O", obj), ("G", context)]:
                cursor.execute(f"""
                    SELECT term_uuid, term_text, term_type, lang, datatype_id
                    FROM {term_table_name} 
                    WHERE term_text = %s
                    LIMIT 3
                """, [str(term_value)])
                
                results = cursor.fetchall()
                term_matches[term_name] = results
                if results:
                    print(f"      {term_name} found: {len(results)} matches")
                    for r in results:
                        print(f"        UUID: {r['term_uuid']}, Type: {r['term_type']}, Lang: {r['lang']}, DT: {r['datatype_id']}")
                else:
                    print(f"      {term_name} NOT FOUND in database")
            
            # If all terms found, check for quad existence
            if all(term_matches.values()):
                s_uuid = term_matches['S'][0]['term_uuid']
                p_uuid = term_matches['P'][0]['term_uuid']
                o_uuid = term_matches['O'][0]['term_uuid']
                g_uuid = term_matches['G'][0]['term_uuid']
                
                cursor.execute(f"""
                    SELECT COUNT(*) as count, quad_uuid
                    FROM {quad_table_name}
                    WHERE subject_uuid = %s AND predicate_uuid = %s 
                      AND object_uuid = %s AND context_uuid = %s
                    GROUP BY quad_uuid
                """, [s_uuid, p_uuid, o_uuid, g_uuid])
                
                quad_results = cursor.fetchall()
                print(f"      Quad matches: {len(quad_results)} found")
                for qr in quad_results:
                    print(f"        Quad UUID: {qr.get('quad_uuid', 'N/A')}, Count: {qr.get('count', 0)}")
            else:
                print(f"      Cannot check quad - missing terms")
                    
    except Exception as e:
        print(f"    ❌ DEBUG error: {e}")
        import traceback
        print(f"    📋 DEBUG traceback: {traceback.format_exc()}")

async def verify_quad_exists_db(quad: Tuple, should_exist: bool = True) -> bool:
    """Verify quad existence using direct database queries (like debug_quad_terms)."""
    try:
        subject, predicate, obj, context = quad
        
        # Get proper table names using space_impl method
        table_names = space_impl._get_table_names(SPACE_ID)
        quad_table_name = table_names.get('rdf_quad')
        term_table_name = table_names.get('term')
        
        # Use async connection with dict pool for dictionary results
        async with space_impl.core.get_dict_connection() as conn:
            # Connection already configured with dict_row factory
            cursor = conn.cursor()
            
            # Find term UUIDs using complete term characteristics (same as insertion logic)
            from vitalgraph.db.postgresql.space.postgresql_space_utils import PostgreSQLSpaceUtils
            
            # Determine term types and characteristics for each term
            terms_info = []
            for term_name, term_value in [("subject", subject), ("predicate", predicate), ("object", obj), ("context", context)]:
                term_type, term_lang, term_datatype_uri = PostgreSQLSpaceUtils.determine_term_type(term_value)
                
                # Extract literal value if needed
                if term_type == 'L':
                    processed_value = PostgreSQLSpaceUtils.extract_literal_value(term_value)
                else:
                    processed_value = str(term_value)
                
                terms_info.append((term_name, processed_value, term_type, term_lang, term_datatype_uri))
            
            # Resolve datatype URIs to IDs
            datatype_uris = {info[4] for info in terms_info if info[4]}
            if datatype_uris:
                datatype_uri_to_id = await space_impl._resolve_datatype_ids_batch(SPACE_ID, datatype_uris)
            else:
                datatype_uri_to_id = {}
            
            # Look up terms using complete characteristics
            term_uuids = {}
            for term_name, term_text, term_type, term_lang, term_datatype_uri in terms_info:
                datatype_id = datatype_uri_to_id.get(term_datatype_uri) if term_datatype_uri else None
                
                # Build WHERE clause for complete term matching
                where_conditions = ["term_text = %s", "term_type = %s"]
                params = [term_text, term_type]
                
                if term_lang is not None:
                    where_conditions.append("lang = %s")
                    params.append(term_lang)
                else:
                    where_conditions.append("lang IS NULL")
                
                if datatype_id is not None:
                    where_conditions.append("datatype_id = %s")
                    params.append(datatype_id)
                else:
                    where_conditions.append("datatype_id IS NULL")
                
                cursor.execute(f"""
                    SELECT term_uuid FROM {term_table_name} 
                    WHERE {' AND '.join(where_conditions)}
                    LIMIT 1
                """, params)
                
                result = cursor.fetchone()
                term_uuids[term_name] = result['term_uuid'] if result else None
            
            # Check if quad exists using found term UUIDs
            if all(term_uuids.values()):
                cursor.execute(f"""
                    SELECT COUNT(*) as count
                    FROM {quad_table_name}
                    WHERE subject_uuid = %s AND predicate_uuid = %s 
                      AND object_uuid = %s AND context_uuid = %s
                """, [term_uuids['subject'], term_uuids['predicate'], term_uuids['object'], term_uuids['context']])
            else:
                # If any term UUID is missing, the quad doesn't exist
                cursor.execute("SELECT 0 as count")
            
            result = cursor.fetchone()
            count = result['count'] if result else 0
        
        if should_exist:
            exists = count > 0
            status = "✅" if exists else "❌"
            print(f"    {status} Quad exists in DB: {exists} (count: {count})")
            return exists
        else:
            not_exists = count == 0
            status = "✅" if not_exists else "❌"
            print(f"    {status} Quad not in DB: {not_exists} (count: {count})")
            return not_exists
                
    except Exception as e:
        print(f"    ❌ DB verification error: {e}")
        return False

async def run_timed_operation(operation_name: str, operation_func, *args, **kwargs):
    """Run an operation and time it."""
    print(f"\n  {operation_name}:")
    start_time = time.time()
    
    try:
        result = await operation_func(*args, **kwargs)
        elapsed = time.time() - start_time
        print(f"    ⏱️  {elapsed:.3f}s")
        return result, elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"    ❌ Error after {elapsed:.3f}s: {e}")
        return None, elapsed

async def setup_connection():
    """Initialize database connection for tests."""
    global impl, sparql_impl, space_impl
    
    print("🔌 Setting up database connection...")
    
    # Initialize VitalGraphImpl with config file
    project_root = Path(__file__).parent.parent.parent
    config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    
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

async def test_single_quad_create():
    """Test creating single quads - success and failure cases."""
    print("\n📝 SINGLE QUAD CREATE OPERATIONS:")
    
    # Test 1: Create a simple quad (should succeed)
    test_quad = create_test_quad("create1", "hasName", "TestObject1")
    
    await debug_term_insertion_process(test_quad, "before_single_uri_add")
    
    result, elapsed = await run_timed_operation(
        "Add single quad (URI objects)",
        space_impl.add_rdf_quad,
        SPACE_ID, test_quad
    )
    
    if result:
        await debug_quad_terms(test_quad, "after_single_uri_add")
        await verify_quad_exists_db(test_quad, should_exist=True)
    
    # Test 2: Create quad with literal object (should succeed)
    literal_quad = create_test_quad("create2", "hasAge", "25", is_literal=True)
    
    result, elapsed = await run_timed_operation(
        "Add single quad (literal object)",
        space_impl.add_rdf_quad,
        SPACE_ID, literal_quad
    )
    
    if result:
        await debug_quad_terms(literal_quad, "after_single_literal_add")
        await verify_quad_exists_db(literal_quad, should_exist=True)
    
    # Test 3: Try to add duplicate quad (should succeed with new quad_uuid)
    result, elapsed = await run_timed_operation(
        "Add duplicate quad (should succeed)",
        space_impl.add_rdf_quad,
        SPACE_ID, test_quad
    )
    
    # Test 4: Try invalid space (should fail)
    result, elapsed = await run_timed_operation(
        "Add quad to invalid space (should fail)",
        space_impl.add_rdf_quad,
        "invalid_space", test_quad
    )

async def test_single_quad_read():
    """Test reading/querying single quads."""
    print("\n📖 SINGLE QUAD READ OPERATIONS:")
    
    # Test 1: Get total quad count
    result, elapsed = await run_timed_operation(
        "Get total quad count",
        space_impl.get_quad_count,
        SPACE_ID
    )
    
    if result is not None:
        print(f"    📊 Total quads: {result}")
    
    # Test 2: Get quad count for specific context
    result, elapsed = await run_timed_operation(
        "Get quad count for test graph",
        space_impl.get_rdf_quad_count,
        SPACE_ID, GRAPH_URI
    )
    
    if result is not None:
        print(f"    📊 Test graph quads: {result}")
    
    # Test 3: Try to get count from invalid space (should fail)
    result, elapsed = await run_timed_operation(
        "Get count from invalid space (should fail)",
        space_impl.get_quad_count,
        "invalid_space"
    )

async def test_single_quad_delete():
    """Test deleting single quads."""
    print("\n🗑️  SINGLE QUAD DELETE OPERATIONS:")
    
    # Create a quad to delete
    delete_quad = create_test_quad("delete1", "toBeDeleted", "DeleteMe")
    
    # Add it first
    await space_impl.add_rdf_quad(SPACE_ID, delete_quad)
    await verify_quad_exists_db(delete_quad, should_exist=True)
    
    # Test 1: Delete the quad (should succeed)
    result, elapsed = await run_timed_operation(
        "Delete single quad",
        space_impl.remove_rdf_quad,
        SPACE_ID, *delete_quad
    )
    
    if result:
        await verify_quad_exists_db(delete_quad, should_exist=False)
    
    # Test 2: Try to delete non-existent quad (should handle gracefully)
    non_existent_quad = create_test_quad("nonexistent", "doesNotExist", "NotThere")
    
    result, elapsed = await run_timed_operation(
        "Delete non-existent quad",
        space_impl.remove_rdf_quad,
        SPACE_ID, *non_existent_quad
    )
    
    # Test 3: Try to delete from invalid space (should fail)
    result, elapsed = await run_timed_operation(
        "Delete from invalid space (should fail)",
        space_impl.remove_rdf_quad,
        "invalid_space", *delete_quad
    )

async def test_batch_quad_create():
    """Test batch quad creation operations."""
    print("\n📝 BATCH QUAD CREATE OPERATIONS:")
    
    # Test 1: Batch add multiple quads (should succeed)
    batch_quads = [
        create_test_quad("batch1", "hasName", "BatchObject1"),
        create_test_quad("batch2", "hasName", "BatchObject2"),
        create_test_quad("batch3", "hasAge", "30", is_literal=True),
        create_test_quad("batch4", "hasAge", "40", is_literal=True),
        create_test_quad("batch5", "hasType", "TestType"),
    ]
    
    initial_count = await space_impl.get_quad_count(SPACE_ID)
    
    result, elapsed = await run_timed_operation(
        f"Batch add {len(batch_quads)} quads",
        space_impl.add_rdf_quads_batch,
        SPACE_ID, batch_quads
    )
    
    if result:
        final_count = await space_impl.get_quad_count(SPACE_ID)
        expected_count = initial_count + len(batch_quads)
        await verify_quad_count(expected_count, "Post-batch-add count")
        
        # Verify a few quads exist
        await verify_quad_exists_db(batch_quads[0], should_exist=True)
        await verify_quad_exists_db(batch_quads[-1], should_exist=True)
    
    # Test 2: Batch add with duplicates (should succeed)
    duplicate_batch = [
        batch_quads[0],  # Duplicate
        batch_quads[1],  # Duplicate
        create_test_quad("batch6", "newProp", "NewValue"),  # New
    ]
    
    pre_dup_count = await space_impl.get_quad_count(SPACE_ID)
    
    result, elapsed = await run_timed_operation(
        f"Batch add with duplicates ({len(duplicate_batch)} quads)",
        space_impl.add_rdf_quads_batch,
        SPACE_ID, duplicate_batch
    )
    
    if result:
        post_dup_count = await space_impl.get_quad_count(SPACE_ID)
        expected_increase = len(duplicate_batch)  # All should be added with new UUIDs
        await verify_quad_count(pre_dup_count + expected_increase, "Post-duplicate-batch count")
    
    # Test 3: Empty batch (should handle gracefully)
    result, elapsed = await run_timed_operation(
        "Batch add empty list",
        space_impl.add_rdf_quads_batch,
        SPACE_ID, []
    )
    
    # Test 4: Batch add to invalid space (should fail)
    result, elapsed = await run_timed_operation(
        "Batch add to invalid space (should fail)",
        space_impl.add_rdf_quads_batch,
        "invalid_space", batch_quads[:2]
    )

async def test_batch_quad_delete():
    """Test batch quad deletion operations."""
    print("\n🗑️  BATCH QUAD DELETE OPERATIONS:")
    
    # Create quads to delete
    delete_batch = [
        create_test_quad("batchdel1", "toDelete", "Value1"),
        create_test_quad("batchdel2", "toDelete", "Value2"),
        create_test_quad("batchdel3", "toDelete", "Value3"),
        create_test_quad("batchdel4", "toDelete", "42", is_literal=True),
    ]
    
    # Add them first
    await space_impl.add_rdf_quads_batch(SPACE_ID, delete_batch)
    
    # Verify they exist
    for quad in delete_batch[:2]:  # Check a couple
        await verify_quad_exists_db(quad, should_exist=True)
    
    initial_count = await space_impl.get_quad_count(SPACE_ID)
    
    # Test 1: Batch delete multiple quads (should succeed)
    result, elapsed = await run_timed_operation(
        f"Batch delete {len(delete_batch)} quads",
        space_impl.remove_rdf_quads_batch,
        SPACE_ID, delete_batch
    )
    
    if result:
        final_count = await space_impl.get_quad_count(SPACE_ID)
        # Note: Due to duplicates from previous tests, we may not remove exactly len(delete_batch)
        print(f"    📊 Count change: {initial_count} -> {final_count} (removed: {initial_count - final_count})")
        
        # Verify some quads are gone (at least one instance)
        # Note: There might still be duplicates, so we check if count decreased
        if final_count < initial_count:
            print("    ✅ Batch delete reduced quad count as expected")
    
    # Test 2: Batch delete non-existent quads (should handle gracefully)
    non_existent_batch = [
        create_test_quad("nonexist1", "notThere", "Value1"),
        create_test_quad("nonexist2", "notThere", "Value2"),
    ]
    
    pre_count = await space_impl.get_quad_count(SPACE_ID)
    
    result, elapsed = await run_timed_operation(
        "Batch delete non-existent quads",
        space_impl.remove_rdf_quads_batch,
        SPACE_ID, non_existent_batch
    )
    
    post_count = await space_impl.get_quad_count(SPACE_ID)
    if post_count == pre_count:
        print("    ✅ Count unchanged for non-existent quads")
    
    # Test 3: Empty batch delete (should handle gracefully)
    result, elapsed = await run_timed_operation(
        "Batch delete empty list",
        space_impl.remove_rdf_quads_batch,
        SPACE_ID, []
    )
    
    # Test 4: Batch delete from invalid space (should fail)
    result, elapsed = await run_timed_operation(
        "Batch delete from invalid space (should fail)",
        space_impl.remove_rdf_quads_batch,
        "invalid_space", delete_batch[:2]
    )

async def test_performance_operations():
    """Test performance with larger batches."""
    print("\n⚡ PERFORMANCE OPERATIONS:")
    
    # Test 1: Large batch create
    large_batch_size = 1000
    large_batch = []
    
    for i in range(large_batch_size):
        quad = create_test_quad(f"perf{i}", "hasIndex", str(i), is_literal=True)
        large_batch.append(quad)
    
    initial_count = await space_impl.get_quad_count(SPACE_ID)
    
    result, elapsed = await run_timed_operation(
        f"Large batch add ({large_batch_size} quads)",
        space_impl.add_rdf_quads_batch,
        SPACE_ID, large_batch
    )
    
    if result:
        final_count = await space_impl.get_quad_count(SPACE_ID)
        rate = large_batch_size / elapsed if elapsed > 0 else 0
        print(f"    📈 Insert rate: {rate:.0f} quads/sec")
        await verify_quad_count(initial_count + large_batch_size, "Post-large-batch count")
    
    # Test 2: Large batch delete
    delete_count = await space_impl.get_quad_count(SPACE_ID)
    
    result, elapsed = await run_timed_operation(
        f"Large batch delete ({large_batch_size} quads)",
        space_impl.remove_rdf_quads_batch,
        SPACE_ID, large_batch
    )
    
    if result:
        final_count = await space_impl.get_quad_count(SPACE_ID)
        removed = delete_count - final_count
        rate = removed / elapsed if elapsed > 0 else 0
        print(f"    📉 Delete rate: {rate:.0f} quads/sec")
        print(f"    📊 Removed: {removed} quads")

async def test_edge_cases():
    """Test edge cases and error conditions."""
    print("\n🔍 EDGE CASES AND ERROR CONDITIONS:")
    
    # Test 1: Very long URI
    long_uri_quad = (
        URIRef("http://test.crud.org/" + "x" * 1000),
        URIRef(f"{TEST_PREDICATE_BASE}/longTest"),
        URIRef(f"{TEST_OBJECT_BASE}/longValue"),
        URIRef(GRAPH_URI)
    )
    
    result, elapsed = await run_timed_operation(
        "Add quad with very long URI",
        space_impl.add_rdf_quad,
        SPACE_ID, long_uri_quad
    )
    
    # Test 2: Special characters in literals
    special_char_quad = create_test_quad("special", "hasText", "Text with 'quotes' and \"double quotes\" and \n newlines", is_literal=True)
    
    result, elapsed = await run_timed_operation(
        "Add quad with special characters",
        space_impl.add_rdf_quad,
        SPACE_ID, special_char_quad
    )
    
    if result:
        await verify_quad_exists_db(special_char_quad, should_exist=True)
    
    # Test 3: Unicode characters
    unicode_quad = create_test_quad("unicode", "hasName", "测试数据 🌟 émojis", is_literal=True)
    
    result, elapsed = await run_timed_operation(
        "Add quad with Unicode characters",
        space_impl.add_rdf_quad,
        SPACE_ID, unicode_quad
    )
    
    if result:
        await verify_quad_exists_db(unicode_quad, should_exist=True)

async def test_consistency_checks():
    """Test data consistency after operations."""
    print("\n🔍 CONSISTENCY CHECKS:")
    
    # Get final counts
    total_count = await space_impl.get_quad_count(SPACE_ID)
    graph_count = await space_impl.get_rdf_quad_count(SPACE_ID, GRAPH_URI)
    
    print(f"    📊 Final total quad count: {total_count}")
    print(f"    📊 Final test graph count: {graph_count}")
    
    # Verify no null quad_uuids
    # Get proper table names using space_impl method
    table_names = space_impl._get_table_names(SPACE_ID)
    quad_table_name = table_names.get('rdf_quad')
    
    # Use async context manager with dict pool for dict results
    async with space_impl.core.get_dict_connection() as conn:
        # Connection already configured with dict_row factory
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) as null_count FROM {quad_table_name} WHERE quad_uuid IS NULL")
        result = cursor.fetchone()
        null_count = result['null_count'] if result else 0
        
        if null_count == 0:
            print("    ✅ No null quad_uuid values found")
        else:
            print(f"    ❌ Found {null_count} null quad_uuid values")
    
    # Verify UUID uniqueness
    # Use async context manager with pooled connection
    async with space_impl.core.get_dict_connection() as conn:
        # Connection already configured with dict_row factory
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT 
                COUNT(*) as total_quads,
                COUNT(DISTINCT quad_uuid) as unique_uuids
            FROM {quad_table_name}
        """)
        result = cursor.fetchone()
        
        if result:
            total = result['total_quads']
            unique = result['unique_uuids']
            
            if total == unique:
                print(f"    ✅ All {total} quad_uuid values are unique")
            else:
                print(f"    ❌ UUID uniqueness violation: {total} total, {unique} unique")

async def reset_test_environment():
    """
    Reset the test environment by deleting the test space and reloading test data.
    Follows the same pattern as the data scripts (unload_test_data.py and reload_test_data.py).
    """
    print("\n🔄 RESETTING TEST ENVIRONMENT...")
    print("==================================================\n")
    
    try:
        # Initialize database connection (following main test pattern)
        config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        
        config = get_config(str(config_path))
        impl = VitalGraphImpl(config=config)
        await impl.db_impl.connect()
        
        space_impl = impl.db_impl.get_space_impl()
        
        # Delete the test space if it exists (following unload_test_data.py pattern)
        print(f"🗑️  Deleting test space '{SPACE_ID}'...")
        if await space_impl.space_exists(SPACE_ID):
            quad_count = await space_impl.get_quad_count(SPACE_ID)
            print(f"   📊 Found space with {quad_count:,} quads")
            success = await space_impl.delete_space_tables(SPACE_ID)
            if success:
                print(f"✅ Successfully deleted space '{SPACE_ID}'")
                print(f"   📈 Freed: {quad_count:,} quads")
            else:
                print(f"❌ Failed to delete space '{SPACE_ID}'")
                return
        else:
            print(f"ℹ️  Space '{SPACE_ID}' does not exist, nothing to delete")
        
        # Reload test data using the actual reload_test_data script
        print(f"\n📥 Reloading test data for space '{SPACE_ID}'...")
        
        # Import and call the reload_test_data wrapper function
        sys.path.insert(0, str(Path(__file__).parent.parent / "data"))
        from reload_test_data import reload_test_data_for_reset
        
        # Call the reload function (it handles space creation and data loading)
        try:
            await reload_test_data_for_reset()
            # Verify the reset
            total_count = await space_impl.get_rdf_quad_count(SPACE_ID)
            print(f"📊 Total quads after reset: {total_count}")
        except Exception as reload_error:
            print(f"❌ Failed to reload test data: {reload_error}")
            return
        
        await impl.db_impl.disconnect()
        print("\n  Test environment reset complete!")
        
    except Exception as e:
        print(f"❌ Error during reset: {e}")
        import traceback
        traceback.print_exc()
        raise

async def main():
    """Main test controller."""
    print("🧪 Quad RDF CRUD Operations Test Suite")
    print("=" * 50)
    
    # Setup connection
    await setup_connection()
    
    try:
        # Ensure we start with a clean space_test
        print("\n🔄 Ensuring clean test environment...")
        
        # Check if space exists and get initial count
        try:
            if await space_impl.space_exists(SPACE_ID):
                initial_count = await space_impl.get_quad_count(SPACE_ID)
                print(f"    📊 Initial quad count: {initial_count}")
            else:
                print(f"    ⚠️  Space '{SPACE_ID}' does not exist")
                initial_count = 0
        except Exception as e:
            print(f"    ⚠️  Space may not exist or be empty: {e}")
            initial_count = 0
        
        # Run comprehensive CRUD test suite
        await test_single_quad_create()
        await test_single_quad_read()
        await test_single_quad_delete()
        await test_batch_quad_create()
        await test_batch_quad_delete()
        await test_performance_operations()
        await test_edge_cases()
        await test_consistency_checks()
        
    finally:
        # Performance summary
        try:
            if await space_impl.space_exists(SPACE_ID):
                final_count = await space_impl.get_quad_count(SPACE_ID)
                print(f"\n📊 Final quad count: {final_count}")
                print(f"📊 Net change: {final_count - initial_count} quads")
        except:
            pass
        
        # Cleanup
        await cleanup_connection()
        print("\n✅ Quad RDF CRUD Operations Test Complete!")
        
        # Uncomment the line below to reset the test environment after the test
        # This will delete the test space and reload fresh test data
        print("\n🔄 Resetting test environment...")
        await reset_test_environment()
        print("\n✅ Test environment reset complete!")

if __name__ == "__main__":
    asyncio.run(main())
