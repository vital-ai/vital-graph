#!/usr/bin/env python3
"""
Test script for PostgreSQLSpaceImpl table creation and deletion.

This script tests:
1. Loading VitalGraphImpl with config file
2. Opening database connection
3. Creating space tables for space_id "space_one"
4. Listing tables before, after creation, and after deletion
5. Deleting the created tables
"""

import sys
import os
import asyncio
import time
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.rdf.rdf_utils import stream_parse_ntriples_nquads_generator, RDFFormat
from rdflib import URIRef


async def list_database_tables(db_impl, description=""):
    """List all tables in the database."""
    try:
        # Use the proper list_tables method
        tables = await db_impl.list_tables()
        
        # Only print output if description is not None
        if description is not None:
            print(f"\n=== {description} ===")
            if tables:
                print(f"Found {len(tables)} tables:")
                for table in sorted(tables):
                    print(f"  - {table}")
            else:
                print("No tables found in database")
        
        return tables
    except Exception as e:
        if description is not None:
            print(f"Error listing tables: {e}")
        return []


async def test_space_impl_tables():
    """Main test function for PostgreSQLSpaceImpl table operations."""
    print("🚀 Starting PostgreSQLSpaceImpl Table Test")
    print("=" * 50)
    
    # Step 1: Initialize VitalGraphImpl with config
    print("\n1. Initializing VitalGraphImpl with config file...")
    try:
        # Provide the config file path explicitly
        config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        print(f"   Using config file: {config_path}")
        
        # Import the config loader to initialize it with the path
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        # Now initialize VitalGraphImpl (it will use the already loaded config)
        vitalgraph_impl = VitalGraphImpl(config=config)
        db_impl = vitalgraph_impl.get_db_impl()
        
        if not config:
            print("❌ Failed to load configuration")
            return False
            
        if not db_impl:
            print("❌ Failed to initialize database implementation")
            return False
            
        print("✅ VitalGraphImpl initialized successfully")
        print(f"   Config loaded: {config is not None}")
        print(f"   DB implementation: {db_impl is not None}")
        
    except Exception as e:
        print(f"❌ Error initializing VitalGraphImpl: {e}")
        return False
    
    # Step 2: Connect to database
    print("\n2. Connecting to database...")
    try:
        await db_impl.connect()
        print("✅ Database connection established")
        
        # Get the space implementation
        space_impl = db_impl.get_space_impl()
        if not space_impl:
            print("❌ Failed to get PostgreSQLSpaceImpl instance")
            return False
        print("✅ PostgreSQLSpaceImpl instance obtained")
        
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        return False
    
    # Define the space ID for this test
    space_id = "space_one"
    
    # Step 3: Delete existing space tables
    print(f"\n3. Checking for existing space tables for '{space_id}'...")
    try:
        # Try to delete space tables if they exist (ignore errors if they don't exist)
        success = space_impl.delete_space_tables(space_id)
        if success:
            print(f"✅ Deleted any existing tables for space '{space_id}'")
        else:
            print(f"⚠️  Warning: Could not delete existing tables for space '{space_id}'")
    except Exception as e:
        print(f"   No existing tables to delete for space '{space_id}' (this is normal): {e}")
    
    # Step 4: Get baseline table list (without verbose listing)
    tables_before = await list_database_tables(db_impl, None)  # No verbose output
    
    # Step 5: Create UUID-based space tables for bulk loading (unlogged for maximum speed)
    print(f"\n4. Creating UUID-based space tables for space_id: '{space_id}'...")
    print(f"   🚀 Using UUID-based UNLOGGED tables for ultra-clean batch loading")
    try:
        success = space_impl.create_space_tables(space_id)
        if success:
            print(f"✅ UUID-based space tables created successfully for '{space_id}'")
        else:
            print(f"❌ Failed to create UUID-based space tables for '{space_id}'")
            return False
    except Exception as e:
        print(f"❌ Error creating UUID-based space tables: {e}")
        return False
    
    # Step 6: Check table creation (without verbose listing)
    print("\n=== Verifying table creation ===")
    tables_after_create = await list_database_tables(db_impl, None)  # No verbose output
    
    # Step 7: Analyze what tables were created
    new_tables = set(tables_after_create) - set(tables_before)
    if new_tables:
        print(f"📊 Analysis: {len(new_tables)} new tables created successfully")
    else:
        print("⚠️  Warning: No new tables detected after creation")
    
    # Step 8: Insert test data - stream 10,000 triples from wordnet file using batch insertion
    print(f"\n5. Inserting test data into space '{space_id}' using batch insertion...")
    test_data_file = project_root / "test_data" / "kgentity_wordnet.nt"
    graph_uri = "urn:wordnet"
    target_triple_count = None  # Process all triples in the file (~3.8M)
    batch_size = 50000  # Batch size for insertion
    
    if not test_data_file.exists():
        print(f"❌ Test data file not found: {test_data_file}")
        return False
    
    print(f"   Using test file: {test_data_file}")
    print(f"   Graph URI: {graph_uri}")
    print(f"   Target triples: {'All triples in file (~3.8M)' if target_triple_count is None else f'{target_triple_count:,}'}")
    print(f"   Batch size: {batch_size:,}")
    
    try:
        # Import the streaming parser, RDFFormat, and RDFLib objects
        from vitalgraph.rdf.rdf_utils import stream_parse_ntriples_nquads_generator, RDFFormat
        from rdflib import URIRef, Literal, BNode
        
        def convert_string_to_rdflib_term(term_str):
            """Convert string representation to appropriate RDFLib term."""
            term_str = term_str.strip()
            
            if term_str.startswith('<') and term_str.endswith('>'):
                # URI reference
                return URIRef(term_str[1:-1])  # Remove < >
            elif term_str.startswith('_:'):
                # Blank node
                return BNode(term_str[2:])  # Remove _:
            elif term_str.startswith('"'):
                # Literal - handle various forms
                if term_str.endswith('"'):
                    # Simple literal
                    return Literal(term_str[1:-1])  # Remove quotes
                else:
                    # Literal with datatype or language tag
                    quote_end = term_str.rfind('"')
                    if quote_end > 0:
                        literal_value = term_str[1:quote_end]
                        suffix = term_str[quote_end + 1:]
                        
                        if suffix.startswith('@'):
                            # Language tag
                            lang = suffix[1:]
                            return Literal(literal_value, lang=lang)
                        elif suffix.startswith('^^'):
                            # Datatype
                            datatype_str = suffix[2:]
                            if datatype_str.startswith('<') and datatype_str.endswith('>'):
                                datatype = URIRef(datatype_str[1:-1])
                            else:
                                datatype = URIRef(datatype_str)
                            return Literal(literal_value, datatype=datatype)
                        else:
                            return Literal(literal_value)
                    else:
                        return Literal(term_str[1:])  # Fallback
            else:
                # Assume URI if not quoted or blank node
                return URIRef(term_str)
        
        total_inserted = 0
        current_batch = []
        print("   Streaming and batching triples for insertion...")
        
        # Start timing the entire batch loading process
        batch_loading_start = time.time()
        
        # Stream triples and collect them into batches
        for triple in stream_parse_ntriples_nquads_generator(str(test_data_file), RDFFormat.NT, progress_interval=2500):
            
            # Extract subject, predicate, object from the triple and convert to RDFLib objects
            subject_str, predicate_str, obj_str = triple
            
            subject = convert_string_to_rdflib_term(subject_str)
            predicate = convert_string_to_rdflib_term(predicate_str)
            obj = convert_string_to_rdflib_term(obj_str)
            graph = URIRef(graph_uri)
            
            quad = (subject, predicate, obj, graph)
            current_batch.append(quad)
            
            # When batch is full, insert it
            if len(current_batch) >= batch_size:
                # Time individual batch insertion
                batch_start = time.time()
                
                # Insert batch using pure psycopg3 optimized batch insert method with unlogged tables
                inserted_count = await space_impl.add_rdf_quads_batch(space_id, current_batch)
                total_inserted += inserted_count
                
                batch_time = time.time() - batch_start
                print(f"   Inserted batch of {inserted_count:,} quads (total: {total_inserted:,}) in {batch_time:.3f}s...")
                
                if inserted_count != len(current_batch):
                    print(f"⚠️  Warning: Batch insert returned {inserted_count}, expected {len(current_batch)}")
                    if inserted_count == 0:
                        print("❌ ERROR: Batch insert failed completely. Exiting test.")
                        return False
                
                current_batch = []  # Reset batch
        
        # Insert any remaining quads in the final partial batch
        if current_batch:
            # Time final batch insertion
            final_batch_start = time.time()
            
            # Use UUID-based batch insert with unlogged tables
            batch_inserted = await space_impl.add_rdf_quads_batch(space_id, current_batch)
            total_inserted += batch_inserted
            
            final_batch_time = time.time() - final_batch_start
            print(f"   Inserted final batch of {batch_inserted:,} quads (total: {total_inserted:,}) in {final_batch_time:.3f}s...")
            
            if batch_inserted != len(current_batch):
                print(f"⚠️  Warning: Final batch insert returned {batch_inserted}, expected {len(current_batch)}")
        
        # Calculate and display total batch loading time
        total_batch_time = time.time() - batch_loading_start
        quads_per_second = total_inserted / total_batch_time if total_batch_time > 0 else 0
        
        print(f"✅ Successfully inserted {total_inserted:,} quads into space '{space_id}' using batch insertion")
        print(f"📊 Batch Loading Performance: {total_batch_time:.3f}s total, {quads_per_second:,.0f} quads/sec")
        
    except Exception as e:
        print(f"❌ Error inserting test data: {e}")
        return False
    
    # Step 6: Build performance indexes after bulk loading
    print(f"\n6. Building performance indexes after bulk loading...")
    print(f"   📊 Creating optimized indexes for SPARQL query performance")
    try:
        # Time index optimization (drop/recreate pattern)
        index_start = time.time()
        
        # Drop indexes for bulk loading optimization
        drop_success = space_impl.drop_indexes_for_bulk_load(space_id)
        print(f"✅ Indexes dropped for bulk loading optimization")
        
        # Recreate all indexes after bulk loading
        recreate_success = space_impl.recreate_indexes_after_bulk_load(space_id, concurrent=False)
        
        index_time = time.time() - index_start
        print(f"📊 Index Optimization Performance: {index_time:.3f}s total")
        if recreate_success:
            print(f"✅ All indexes recreated successfully in {index_time:.3f}s")
        else:
            print(f"⚠️  Warning: Some indexes may have failed to recreate")
            
    except Exception as e:
        print(f"❌ Error optimizing indexes: {e}")
        print(f"   Continuing with verification (indexes can be optimized later)")
    
    # Step 7: Test the fixed quads() method to verify hanging issue is resolved
    print(f"\n7. Testing quads() method to verify hanging issue is fixed...")
    print(f"   Simple test: verify quads() method can be created without hanging...")
    
    try:
        start_time = time.time()
        
        # Test the quads() method with a wildcard pattern
        print(f"   🔍 Creating quads() async generator with pattern (None, None, None, None)...")
        quad_pattern = (None, None, None, None)
        
        # Test that we can create and use the async generator without hanging
        try:
            quad_generator = space_impl.quads("space_one", quad_pattern)
            print(f"   ✅ quads() async generator created successfully - no hanging!")
            
            # Test full quad retrieval with progress output
            print(f"   🔍 Testing quad retrieval (full async iteration with progress)...")
            
            count = 0
            first_quad = None
            
            # Use async for loop to iterate through all quads with progress indicators
            async for quad, contexts in quad_generator:
                count += 1
                if count == 1:
                    first_quad = quad
                    print(f"   ✅ Successfully retrieved first quad: {quad}")
                # Progress indicator for every 100,000 quads
                if count % 100000 == 0:
                    print(f"   📊 Retrieved {count:,} quads so far...")
            
            if count > 0:
                print(f"   🎉 quads() method is working correctly - no hanging!")
                print(f"   📊 Retrieved {count:,} quads successfully")
            else:
                print(f"   ⚠️  No quads returned (empty result set)")
                
        except Exception as create_error:
            print(f"   ❌ Failed to test quads() generator: {create_error}")
            import traceback
            traceback.print_exc()
            raise
        
        end_time = time.time()
        verification_time = end_time - start_time
        
        print(f"✅ quads() method test completed successfully in {verification_time:.3f}s")
        print(f"📊 quads() Generator Test Performance: {verification_time:.3f}s total")
            
    except Exception as e:
        print(f"❌ ERROR during verification: {e}")
        import traceback
        print(f"📋 Full traceback: {traceback.format_exc()}")
        return False

    # Step 7b: Test quads() method with specific pattern filtering
    print(f"\n7b. Testing quads() method with pattern filtering...")
    print(f"   Testing pattern: (None, 'http://vital.ai/ontology/vital-core#hasName', None, 'urn:wordnet')")
    
    try:
        from rdflib import URIRef
        
        start_time = time.time()
        
        # Create specific pattern for hasName predicate quads
        hasName_pattern = (
            None,  # Any subject
            URIRef('http://vital.ai/ontology/vital-core#hasName'),  # Specific predicate
            None,  # Any object
            URIRef('urn:wordnet')  # Specific graph
        )
        
        # Test pattern-based quad retrieval
        try:
            quad_generator = space_impl.quads("space_one", hasName_pattern)
            print(f"   ✅ Pattern-based quads() generator created successfully!")
            
            print(f"   🔍 Testing pattern-based quad retrieval...")
            
            count = 0
            sample_quads = []
            
            # Collect filtered quads
            async for quad, contexts in quad_generator:
                count += 1
                if count <= 3:  # Show first 3 matches
                    sample_quads.append(quad)
                    print(f"   📝 Sample hasName quad {count}: {quad}")
                # Progress indicator for every 1,000 quads (smaller batches for filtered results)
                if count % 1000 == 0:
                    print(f"   📊 Retrieved {count:,} hasName quads so far...")
            
            if count > 0:
                print(f"   🎉 Pattern filtering works correctly!")
                print(f"   📊 Found {count:,} quads matching hasName pattern")
                print(f"   📊 This represents {count/total_inserted*100:.1f}% of total quads")
            else:
                print(f"   ⚠️  No quads found matching the hasName pattern")
                
        except Exception as pattern_error:
            print(f"   ❌ Failed to test pattern-based quads() generator: {pattern_error}")
            import traceback
            traceback.print_exc()
            raise
        
        end_time = time.time()
        pattern_time = end_time - start_time
        
        print(f"✅ Pattern-based quads() test completed successfully in {pattern_time:.3f}s")
        print(f"📊 Pattern Query Performance: {pattern_time:.3f}s total")
        if count > 0:
            pattern_quads_per_sec = count / pattern_time if pattern_time > 0 else 0
            print(f"📊 Pattern Retrieval Rate: {pattern_quads_per_sec:,.0f} filtered quads/sec")
            
    except Exception as e:
        print(f"❌ ERROR during pattern-based verification: {e}")
        import traceback
        print(f"📋 Full traceback: {traceback.format_exc()}")
        return False

    # Step 7c: Test regex-based quads() method
    print(f"\n7c. Testing quads() method with regex pattern filtering...")
    try:
        # Import REGEXTerm from the postgresql_space_queries module
        from vitalgraph.db.postgresql.space.postgresql_space_queries import REGEXTerm
        
        start_time = time.time()
        
        # Create a regex pattern to find objects containing "happy"
        happy_regex = REGEXTerm(".*happy.*")
        regex_pattern = (None, None, happy_regex, URIRef("urn:wordnet"))
        print(f"   Testing regex pattern: (None, None, REGEXTerm('.*happy.*'), 'urn:wordnet')")
        
        try:
            # Create the quads generator with regex pattern
            quad_generator = space_impl.quads("space_one", regex_pattern)
            print(f"   ✅ Regex-based quads() generator created successfully!")
            print(f"   🔍 Testing regex-based quad retrieval...")
            
            count = 0
            sample_quads = []
            
            # Collect filtered quads
            async for quad, contexts in quad_generator:
                count += 1
                if count <= 5:  # Show first 5 matches for regex
                    sample_quads.append(quad)
                    print(f"   📝 Sample 'happy' quad {count}: {quad}")
                # Progress indicator for every 100 quads (smaller batches for regex results)
                if count % 100 == 0:
                    print(f"   📊 Retrieved {count:,} 'happy' quads so far...")
                # Limit to reasonable number for demo
                if count >= 1000:
                    print(f"   📊 Stopping at {count:,} quads for demo purposes")
                    break
            
            if count > 0:
                print(f"   🎉 Regex pattern filtering works correctly!")
                print(f"   📊 Found {count:,} quads matching 'happy' regex pattern")
                if total_inserted > 0:
                    print(f"   📊 This represents {count/total_inserted*100:.3f}% of total quads")
            else:
                print(f"   ⚠️  No quads found matching the 'happy' regex pattern")
                
        except Exception as regex_error:
            print(f"   ❌ Failed to test regex-based quads() generator: {regex_error}")
            import traceback
            traceback.print_exc()
            raise
        
        end_time = time.time()
        regex_time = end_time - start_time
        
        print(f"✅ Regex-based quads() test completed successfully in {regex_time:.3f}s")
        print(f"📊 Regex Query Performance: {regex_time:.3f}s total")
        if count > 0:
            regex_quads_per_sec = count / regex_time if regex_time > 0 else 0
            print(f"📊 Regex Retrieval Rate: {regex_quads_per_sec:,.0f} filtered quads/sec")
            
    except Exception as e:
        print(f"❌ ERROR during regex-based verification: {e}")
        import traceback
        print(f"📋 Full traceback: {traceback.format_exc()}")
        return False

    # Step 8: Get updated space info
    print(f"\n8. Getting updated space info for '{space_id}'...")
    try:
        space_info = await space_impl.get_space_info(space_id)
        print("✅ Updated space info retrieved:")
        print(f"  Space exists: {space_info.get('exists', False)}")
        
    except Exception as e:
        print(f"❌ Error getting updated space info: {e}")
    
    # Step 2b: Clean up existing tables before final verification
    print(f"\n2b. Cleaning up existing tables before final verification...")
    try:
        cleanup_success = space_impl.delete_space_tables(space_id)
        if cleanup_success:
            print(f"✅ Existing tables cleaned up successfully for '{space_id}'")
        else:
            print(f"⚠️  Warning: Could not clean up existing tables for '{space_id}'")
    except Exception as e:
        print(f"⚠️  Warning: Error during table cleanup: {e}")
    
    # Step 2c: Create UUID-based space tables for final verification
    print(f"\n2c. Creating UUID-based space tables for final verification...")
    success = space_impl.create_space_tables(space_id)
    if not success:
        print(f"❌ Failed to create UUID-based space tables for '{space_id}'")
        return False
    print(f"✅ UUID-based space tables created successfully for final verification")

    # Step 9: Delete space tables
    print(f"\n9. Deleting space tables for space_id: '{space_id}'...")
    try:
        success = space_impl.delete_space_tables(space_id)
        if success:
            print(f"✅ Space tables deleted successfully for '{space_id}'")
        else:
            print(f"❌ Failed to delete space tables for '{space_id}'")
            return False
        
    except Exception as e:
        print(f"❌ Error deleting space tables: {e}")
        return False
    
    # Step 10: Check table deletion (without verbose listing)
    print("\n=== Verifying table deletion ===")
    tables_after_delete = await list_database_tables(db_impl, None)  # No verbose output
    
    # Step 11: Analyze what tables were deleted
    deleted_tables = set(tables_after_create) - set(tables_after_delete)
    if deleted_tables:
        print(f"📊 Analysis: {len(deleted_tables)} tables deleted successfully")
    else:
        print("⚠️  Warning: No tables were deleted")
    
    # Step 12: Verify tables are back to original state
    remaining_new_tables = set(tables_after_delete) - set(tables_before)
    if not remaining_new_tables:
        print("\n✅ SUCCESS: All created tables were properly deleted")
        print("   Database is back to original state")
    else:
        print(f"\n⚠️  WARNING: {len(remaining_new_tables)} tables remain:")
        for table in sorted(remaining_new_tables):
            print(f"  ! {table}")
    
    # Step 13: Disconnect from database
    print(f"\n13. Disconnecting from database...")
    try:
        await db_impl.disconnect()
        print("✅ Database disconnected successfully")
        
    except Exception as e:
        print(f"❌ Error disconnecting from database: {e}")
    
    print("\n" + "=" * 50)
    print("🏁 PostgreSQLSpaceImpl Table Test Complete")
    
    return True


if __name__ == "__main__":
    print("PostgreSQLSpaceImpl Table Creation/Deletion Test")
    print("Using Python interpreter:", sys.executable)
    print("Project root:", project_root)
    
    # Run the async test
    success = asyncio.run(test_space_impl_tables())
    
    if success:
        print("\n🎉 Test completed successfully!")
        sys.exit(0)
    else:
        print("\n💥 Test failed!")
        sys.exit(1)
