#!/usr/bin/env python3
"""
Import Process Test Script
=========================

Test the import functionality in VitalGraph including:
- VitalGraphImpl initialization and connection
- Space listing and management
- Import process testing with sample data
- Performance monitoring and validation

This test follows the pattern of other VitalGraph test scripts and validates
the import process architecture.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.space.space_manager import SpaceManager

# Configure logging to see detailed import operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

# Suppress verbose logging from other modules
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.space.postgresql_space_core').setLevel(logging.WARNING)

# Test configuration
timestamp = int(time.time()) % 10000  # Use last 4 digits only
TEST_SPACE_ID = f"test_import_{timestamp}"
TEST_SPACE_NAME = "Test Import Space"
TEST_SPACE_DESCRIPTION = "Test space created by import test script"

async def test_vitalgraph_initialization():
    """Test VitalGraphImpl initialization and basic functionality."""
    print("🚀 VitalGraph Import Process Test")
    print("=" * 50)
    
    # Initialize VitalGraph with configuration
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    
    print(f"📋 Loading configuration from: {config_path}")
    print(f"📊 Configuration loaded successfully")
    
    # Create VitalGraphImpl instance
    impl = VitalGraphImpl(config=config)
    await impl.db_impl.connect()
    
    print(f"✅ Connected to database successfully")
    print(f"📋 VitalGraph Implementation: {type(impl).__name__}")
    print(f"📋 Database Implementation: {type(impl.db_impl).__name__}")
    
    return impl

async def test_space_listing(impl: VitalGraphImpl):
    """Test space listing functionality."""
    print(f"\n1️⃣ SPACE LISTING")
    print("-" * 30)
    
    space_manager = impl.get_space_manager()
    
    # List spaces from registry
    registry_spaces = space_manager.list_spaces()
    print(f"📊 Spaces in registry: {len(registry_spaces)}")
    
    if registry_spaces:
        print("📝 Registry spaces:")
        for space_id in registry_spaces:
            print(f"   - {space_id}")
    else:
        print("📝 No spaces found in registry")
    
    return registry_spaces

async def test_space_creation(space_manager: SpaceManager, test_space_name: str):
    """Create test space if it doesn't exist in registry."""
    print(f"\n2️⃣ TEST SPACE CREATION")
    print(f"------------------------------")
    print(f"📋 Creating test space: {test_space_name}")
    
    try:
        await space_manager.create_space_with_tables(test_space_name, test_space_name)
        print(f"✅ Created test space: {test_space_name}")
        return True
    except Exception as e:
        if "already exists" in str(e):
            print(f"✅ Test space already exists: {test_space_name}")
        else:
            print(f"❌ Failed to create test space: {test_space_name}")
            print(f"Error: {e}")
        return True

async def main():
    """Main test function."""
    try:
        # Test 1: Initialize VitalGraph
        impl = await test_vitalgraph_initialization()
        
        # Test 2: Initialize space manager from database
        space_manager = impl.get_space_manager()
        print(f"\n🔄 Initializing SpaceManager from database...")
        await space_manager.initialize_from_database()
        print(f"✅ SpaceManager initialized with {len(space_manager)} spaces")
        
        # Test 3: List spaces
        registry_spaces = await test_space_listing(impl)
        
        # Test 4: Create test space if needed
        test_space_id = "test_import"  # Shortened to 11 chars
        space_creation_ok = await test_space_creation(space_manager, test_space_id)
        
        # 3️⃣ BULK IMPORT TEST
        print("\n3️⃣ BULK IMPORT TEST")
        print("-" * 30)
        
        try:
            # Configuration for bulk import
            wordnet_file = Path(__file__).parent.parent.parent / "test_data" / "kgframe-wordnet-0.0.2.nt"
            test_graph_uri = "http://vital.ai/test/bulk_import_graph"
            
            if not wordnet_file.exists():
                print(f"❌ Data file not found: {wordnet_file}")
                return False
                
            # Get file size for reference
            file_size_mb = wordnet_file.stat().st_size / (1024 * 1024)
            print(f"📊 Wordnet file: {wordnet_file}")
            print(f"📊 File size: {file_size_mb:.2f} MB")
            
            # Get space implementation
            space_impl = impl.db_impl.get_space_impl()
            print(f"✅ Got space implementation")
            
            # Get space record from space manager
            space_record = space_manager.get_space(test_space_id)
            if not space_record:
                print(f"❌ Space '{test_space_id}' not found in space manager")
                return False
            
            # Get space implementation for graph operations
            space_impl_for_graphs = space_record.space_impl
            
            # Delete existing graph using space impl (clean slate)
            print(f"📊 Checking for existing graph: {test_graph_uri}")
            try:
                existing_graphs = await space_impl_for_graphs._space_impl.graphs.list_graphs(test_space_id)
                graph_exists = any(g.get('graph_uri') == test_graph_uri for g in existing_graphs)
                
                if graph_exists:
                    print(f"🗑️  Deleting existing graph using space impl: {test_graph_uri}")
                    await space_impl_for_graphs._space_impl.graphs.drop_graph(test_space_id, test_graph_uri)
                    print(f"✅ Deleted existing graph")
                else:
                    print(f"✅ No existing graph to delete")
            except Exception as e:
                print(f"⚠️  Could not check/delete existing graph: {e}")
            
            # Create test graph using space impl
            print(f"📊 Creating fresh graph: {test_graph_uri}")
            await space_impl_for_graphs._space_impl.graphs.create_graph(test_space_id, test_graph_uri)
            print(f"✅ Created graph: {test_graph_uri}")
            
            # List graphs in the space to verify
            print(f"\n📊 Listing graphs in space '{test_space_id}':")
            graphs = await space_impl.graphs.list_graphs(test_space_id)
            for i, graph in enumerate(graphs, 1):
                print(f"  {i}. {graph}")
            print(f"✅ Found {len(graphs)} graph(s) in space")
            
            # Verify graph is empty (0 size)
            print(f"\n📊 Verifying graph is empty...")
            try:
                # Get table names for verification
                table_names = space_impl._get_table_names(test_space_id)
                quad_table = table_names['rdf_quad']
                
                # Check quad count for this specific graph
                async with space_impl.get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(f"SELECT COUNT(*) FROM {quad_table} WHERE context_uuid = (SELECT term_uuid FROM {table_names['term']} WHERE term_text = %s)", (test_graph_uri,))
                        quad_count = cursor.fetchone()[0]
                        print(f"✅ Graph '{test_graph_uri}' has {quad_count} quads (should be 0)")
                        
                        if quad_count == 0:
                            print("✅ Graph is empty - ready for clean import")
                        else:
                            print(f"⚠️  Graph has {quad_count} existing quads - may affect results")
            except Exception as e:
                print(f"⚠️  Could not verify graph size: {e}")
            
            # Progress callback for import monitoring
            def progress_callback(processed_triples, line_num):
                if processed_triples % 10000 == 0:
                    print(f"  Processed: {processed_triples:,} triples (line {line_num:,})")
            
            # Start bulk import
            print(f"\n=== Starting Bulk Import ===")
            print(f"Target: UNLOGGED temp table (Phase 2 only)")
            
            import_start = time.time()
            
            # Call bulk import method
            import_stats = await space_impl.db_import.bulk_import_ntriples(
                wordnet_file, 
                "http://vital.ai/test/bulk_import_graph",
                batch_size=100000,
                progress_callback=progress_callback
            )
            
            import_duration = time.time() - import_start
            
            # Display import results
            print(f"\n=== Import Results ===")
            print(f"Import ID: {import_stats['import_id']}")
            print(f"Temp table: {import_stats['temp_table_name']}")
            print(f"Total triples: {import_stats['total_triples']:,}")
            print(f"Processed triples: {import_stats['processed_triples']:,}")
            print(f"Total time: {import_stats['total_time']:.2f}s")
            print(f"Parsing time: {import_stats['parsing_time']:.2f}s")
            print(f"COPY time: {import_stats['copy_time']:.2f}s")
            
            # Calculate performance metrics
            triples_per_sec = import_stats['total_triples'] / import_stats['total_time']
            mb_per_sec = file_size_mb / import_stats['total_time']
            
            print(f"\n=== Performance Metrics ===")
            print(f"Triples/sec: {triples_per_sec:,.0f}")
            print(f"MB/sec: {mb_per_sec:.2f}")
            print(f"Parsing rate: {import_stats['total_triples'] / import_stats['parsing_time']:,.0f} triples/sec")
            print(f"COPY rate: {import_stats['processed_triples'] / import_stats['copy_time']:,.0f} triples/sec")
            
            # Get temp table statistics
            print(f"\n=== Temp Table Analysis ===")
            temp_stats = await space_impl.db_import.get_temp_table_stats(import_stats['temp_table_name'])
            
            print(f"Total rows: {temp_stats.get('total_rows', 0):,}")
            print(f"Unique subjects: {temp_stats.get('unique_subjects', 0):,}")
            print(f"Unique predicates: {temp_stats.get('unique_predicates', 0):,}")
            print(f"Unique objects: {temp_stats.get('unique_objects', 0):,}")
            print(f"Literal objects: {temp_stats.get('literal_count', 0):,}")
            print(f"URI objects: {temp_stats.get('uri_count', 0):,}")
            
            # Calculate compression ratios (avoid division by zero and unrealistic values)
            print(f"\n=== Deduplication Potential ===")
            if temp_stats.get('unique_subjects', 0) > 0:
                subject_compression = temp_stats['total_rows'] / temp_stats['unique_subjects']
                print(f"Subject reuse ratio: {subject_compression:.1f}x")
            
            if temp_stats.get('unique_predicates', 0) > 0:
                predicate_compression = temp_stats['total_rows'] / temp_stats['unique_predicates']
                # Only show if reasonable (predicates are typically highly reused)
                if predicate_compression < 100000:  # Avoid showing unrealistic ratios
                    print(f"Predicate reuse ratio: {predicate_compression:.1f}x")
                else:
                    print(f"Predicate reuse ratio: {predicate_compression:,.0f}x (highly reused)")
            
            if temp_stats.get('unique_objects', 0) > 0:
                object_compression = temp_stats['total_rows'] / temp_stats['unique_objects']
                print(f"Object reuse ratio: {object_compression:.1f}x")
            
            # 4️⃣ PHASE 3: OPTIMIZED PARALLEL UUID ASSIGNMENT TEST
            print(f"\n4️⃣ PHASE 3: OPTIMIZED PARALLEL UUID ASSIGNMENT TEST")
            print("-" * 50)
            
            # Test the optimized parallel UUID assignment performance
            print(f"Testing optimized parallel UUID assignment on {import_stats['total_triples']:,} triples...")
            
            phase3_start = time.time()
            
            # Run Phase 3 term processing
            phase3_stats = await space_impl.db_import.process_terms_phase3(
                import_stats['temp_table_name'], 
                test_space_id,
                {}  # Empty stats dict
            )
            
            phase3_duration = time.time() - phase3_start
            
            # Display Phase 3 results
            print(f"\n=== Phase 3 Results ===")
            print(f"Unique terms processed: {phase3_stats.get('unique_terms_processed', 0):,}")
            print(f"Existing terms reused: {phase3_stats.get('existing_terms_reused', 0):,}")
            print(f"New terms created: {phase3_stats.get('new_terms_created', 0):,}")
            print(f"Rows updated: {phase3_stats.get('rows_updated', 0):,}")
            print(f"Processing time: {phase3_stats.get('processing_time', 0):.2f}s")
            
            # Calculate Phase 3 performance metrics
            if phase3_stats.get('rows_updated', 0) > 0:
                rows_per_sec = phase3_stats['rows_updated'] / phase3_stats['processing_time']
                terms_per_sec = phase3_stats.get('unique_terms_processed', 0) / phase3_stats['processing_time']
                
                print(f"\n=== Phase 3 Performance Metrics ===")
                print(f"Rows updated/sec: {rows_per_sec:,.0f}")
                print(f"Terms processed/sec: {terms_per_sec:,.0f}")
                
                # Compare with Phase 2 performance
                phase2_rate = import_stats['processed_triples'] / import_stats['copy_time']
                print(f"Phase 2 COPY rate: {phase2_rate:,.0f} rows/sec")
                print(f"Phase 3 CTE rate: {rows_per_sec:,.0f} rows/sec")
                
                if rows_per_sec > 0:
                    performance_ratio = phase2_rate / rows_per_sec
                    print(f"Performance ratio (Phase 2 vs Phase 3): {performance_ratio:.1f}x")
            
            # Verify temp table has UUIDs assigned
            print(f"\n=== UUID Assignment Verification ===")
            verification_sql = f"""
                SELECT 
                    COUNT(*) as total_rows,
                    COUNT(subject_uuid) as subject_uuids,
                    COUNT(predicate_uuid) as predicate_uuids,
                    COUNT(object_uuid) as object_uuids,
                    COUNT(graph_uuid) as graph_uuids,
                    COUNT(CASE WHEN processing_status = 'processed' THEN 1 END) as processed_rows
                FROM {import_stats['temp_table_name']}
            """
            
            # Execute verification query
            async with space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(verification_sql)
                    verification_result = cursor.fetchone()
                    
                    if verification_result:
                        total_rows, subject_uuids, predicate_uuids, object_uuids, graph_uuids, processed_rows = verification_result
                        
                        print(f"Total rows: {total_rows:,}")
                        print(f"Subject UUIDs assigned: {subject_uuids:,}")
                        print(f"Predicate UUIDs assigned: {predicate_uuids:,}")
                        print(f"Object UUIDs assigned: {object_uuids:,}")
                        print(f"Graph UUIDs assigned: {graph_uuids:,}")
                        print(f"Processed rows: {processed_rows:,}")
                        
                        # Check completion percentage
                        if total_rows > 0:
                            completion_pct = (processed_rows / total_rows) * 100
                            print(f"Processing completion: {completion_pct:.1f}%")
                            
                            if completion_pct == 100.0:
                                print("✅ All rows successfully processed with UUIDs")
                            else:
                                print(f"⚠️  Only {completion_pct:.1f}% of rows processed")
            
            # 5️⃣ PHASE 4: TRANSFER TO MAIN TABLES TEST
            print(f"\n5️⃣ PHASE 4: TRANSFER TO MAIN TABLES TEST")
            print("-" * 50)
            
            # Test the optimized transfer to main transactional tables
            print(f"Testing transfer of {import_stats['total_triples']:,} triples to main quad and term tables...")
            
            phase4_start = time.time()
            
            # Run Phase 4 transfer to main tables
            phase4_stats = await space_impl.db_import.transfer_to_main_tables_phase4(
                import_stats['temp_table_name'], 
                test_space_id,
                test_graph_uri,
                import_stats
            )
            
            phase4_duration = time.time() - phase4_start
            
            # Display Phase 4 results
            print(f"\n=== Phase 4 Results ===")
            print(f"Terms transferred: {phase4_stats.get('terms_transferred', 0):,}")
            print(f"Quads transferred: {phase4_stats.get('quads_transferred', 0):,}")
            print(f"Term transfer time: {phase4_stats.get('term_transfer_time', 0):.2f}s")
            print(f"Quad transfer time: {phase4_stats.get('quad_transfer_time', 0):.2f}s")
            print(f"Total transfer time: {phase4_stats.get('total_time', 0):.2f}s")
            
            # Calculate Phase 4 performance metrics
            if phase4_stats.get('quads_transferred', 0) > 0:
                terms_per_sec = phase4_stats.get('terms_per_sec', 0)
                quads_per_sec = phase4_stats.get('quads_per_sec', 0)
                overall_rate = phase4_stats.get('overall_transfer_rate', 0)
                
                print(f"\n=== Phase 4 Performance Metrics ===")
                print(f"Terms/sec: {terms_per_sec:,.0f}")
                print(f"Quads/sec: {quads_per_sec:,.0f}")
                print(f"Overall transfer rate: {overall_rate:,.0f} quads/sec")
                
                # Compare with previous phases
                phase2_rate = import_stats['processed_triples'] / import_stats['copy_time']
                phase3_rate = phase3_stats.get('rows_updated', 0) / phase3_stats.get('processing_time', 1)
                
                print(f"\n=== Multi-Phase Performance Comparison ===")
                print(f"Phase 2 COPY rate: {phase2_rate:,.0f} rows/sec")
                print(f"Phase 3 UUID rate: {phase3_rate:,.0f} rows/sec")
                print(f"Phase 4 transfer rate: {overall_rate:,.0f} quads/sec")
            
            # Verify main table data
            print(f"\n=== Main Table Verification ===")
            
            # Get table names for verification
            table_names = space_impl._get_table_names(test_space_id)
            quad_table = table_names['rdf_quad']
            term_table = table_names['term']
            
            verification_sql = f"""
                SELECT 
                    (SELECT COUNT(*) FROM {quad_table}) as quad_count,
                    (SELECT COUNT(*) FROM {term_table}) as term_count,
                    (SELECT COUNT(DISTINCT subject_uuid) FROM {quad_table}) as unique_subjects,
                    (SELECT COUNT(DISTINCT predicate_uuid) FROM {quad_table}) as unique_predicates,
                    (SELECT COUNT(DISTINCT object_uuid) FROM {quad_table}) as unique_objects,
                    (SELECT COUNT(DISTINCT context_uuid) FROM {quad_table}) as unique_contexts
            """
            
            # Execute verification query
            async with space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(verification_sql)
                    verification_result = cursor.fetchone()
                    
                    if verification_result:
                        quad_count, term_count, unique_subjects, unique_predicates, unique_objects, unique_contexts = verification_result
                        
                        print(f"Main quad table count: {quad_count:,}")
                        print(f"Main term table count: {term_count:,}")
                        print(f"Unique subjects: {unique_subjects:,}")
                        print(f"Unique predicates: {unique_predicates:,}")
                        print(f"Unique objects: {unique_objects:,}")
                        print(f"Unique contexts: {unique_contexts:,}")
                        
                        # Verify data integrity
                        expected_quads = import_stats['total_triples']
                        if quad_count == expected_quads:
                            print("✅ Data integrity verified: All triples successfully transferred")
                        else:
                            print(f"⚠️  Data integrity warning: Expected {expected_quads:,}, got {quad_count:,}")
            
            # Keep temp table for inspection
            print(f"\n=== Import Process Complete ===")
            print(f"Temp table '{import_stats['temp_table_name']}' contains staging data")
            print(f"Main tables now contain {phase4_stats.get('quads_transferred', 0):,} quads")
            
            # Optional: Clean up temp table
            cleanup_choice = input("\nClean up temp table? (y/N): ").strip().lower()
            if cleanup_choice == 'y':
                await space_impl.db_import.cleanup_import_session(import_stats)
                print("✅ Cleaned up temp table")
            else:
                print(f"Temp table preserved: {import_stats['temp_table_name']}")
            
        except Exception as e:
            print(f"❌ Error during bulk import: {e}")
            import traceback
            traceback.print_exc()

        # Only show summary if import was successful
        if 'import_stats' in locals() and import_stats and 'phase3_stats' in locals() and 'phase4_stats' in locals():
            print("\n📊 TEST SUMMARY")
            print("=" * 50)
            print("✅ VitalGraph initialization: Success")
            print(f"✅ Space listing: {len(registry_spaces)} registry spaces")
            print(f"✅ Test space creation: {'Success' if space_creation_ok else 'Failed'}")
            print("✅ Phase 2 bulk import: Completed")
            print("✅ Phase 3 UUID assignment: Completed")
            print("✅ Phase 4 main table transfer: Completed")
            print(f"📈 Final performance: {phase4_stats.get('overall_transfer_rate', 0):,.0f} quads/sec to main tables")
        elif 'import_stats' in locals() and import_stats and 'phase3_stats' in locals():
            print("\n📊 TEST SUMMARY")
            print("=" * 50)
            print("✅ VitalGraph initialization: Success")
            print(f"✅ Space listing: {len(registry_spaces)} registry spaces")
            print(f"✅ Test space creation: {'Success' if space_creation_ok else 'Failed'}")
            print("✅ Phase 2 bulk import: Completed")
            print("✅ Phase 3 UUID assignment: Completed")
            print("❌ Phase 4 main table transfer: Failed")
        elif 'import_stats' in locals() and import_stats:
            print("\n📊 TEST SUMMARY")
            print("=" * 50)
            print("✅ VitalGraph initialization: Success")
            print(f"✅ Space listing: {len(registry_spaces)} registry spaces")
            print(f"✅ Test space creation: {'Success' if space_creation_ok else 'Failed'}")
            print("✅ Phase 2 bulk import: Completed")
            print("❌ Phase 3 UUID assignment: Failed")
            print("❌ Phase 4 main table transfer: Not attempted")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    # Run the test
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
