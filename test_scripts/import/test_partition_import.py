#!/usr/bin/env python3
"""
Partition Import Process Test Script
===================================

Test the partition import functionality in VitalGraph including:
- VitalGraphImpl initialization and connection
- Space creation and management
- Partition import process testing with WordNet data
- Performance monitoring and validation

This test follows the pattern of test_import_process.py but uses the
partition-based import method with zero-copy partition attachment.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.db.postgresql.space.postgresql_space_db_import import PostgreSQLSpaceDBImport

# Configure logging to see detailed import operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

# Suppress verbose logging from other modules
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.space.postgresql_space_core').setLevel(logging.WARNING)

# Test configuration
timestamp = int(time.time()) % 10000  # Use last 4 digits only
TEST_SPACE_ID = f"part_{timestamp}"  # Shortened to fit 15 char limit
TEST_SPACE_NAME = "Partition Import Test Space"
TEST_SPACE_DESCRIPTION = "Test space created by partition import test script"
TEST_GRAPH_URI = "http://vital.ai/test/partition_import_graph"

async def test_vitalgraph_initialization():
    """Test VitalGraphImpl initialization and basic functionality."""
    print("🚀 VitalGraph Partition Import Process Test")
    print("=" * 50)
    
    # Initialize VitalGraph with configuration
    config_path = Path(__file__).parent.parent.parent / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
    config = get_config(str(config_path))
    
    print(f"📋 Loading configuration from: {config_path}")
    print(f"📊 Configuration loaded successfully")
    
    # Create VitalGraphImpl instance
    impl = VitalGraphImpl(config=config)
    
    # Force disconnect first to clear any cached settings
    try:
        await impl.db_impl.disconnect()
    except:
        pass
    
    await impl.db_impl.connect()
    
    print(f"✅ Connected to database successfully")
    print(f"📋 VitalGraph Implementation: {type(impl).__name__}")
    print(f"📋 Database Implementation: {type(impl.db_impl).__name__}")
    
    return impl

async def test_space_creation(space_manager, test_space_name: str):
    """Create test space if it doesn't exist in registry."""
    print(f"\n1️⃣ TEST SPACE CREATION")
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
        
        # Test 3: Delete and recreate test space to ensure partitioned tables
        print(f"\n🗑️ Deleting test space '{TEST_SPACE_ID}' if it exists...")
        try:
            await space_manager.delete_space_with_tables(TEST_SPACE_ID)
            print(f"🗑️  Deleted existing space: {TEST_SPACE_ID}")
        except Exception as e:
            print(f"ℹ️  Space {TEST_SPACE_ID} didn't exist or couldn't be deleted: {e}")
        
        # Create the test space
        print(f"🏗️  Creating space: {TEST_SPACE_ID}")
        await space_manager.create_space_with_tables(TEST_SPACE_ID, "Partition Import Test Space")
        print(f"✅ Space created successfully: {TEST_SPACE_ID}")
        
        # Get space implementation for database operations
        space_impl = impl.db_impl.space_impl
        
        # Create the test graph in the space
        test_graph_uri = "http://vital.ai/test/partition_import_graph"
        print(f"📊 Creating test graph: {test_graph_uri}")
        
        from vitalgraph.db.postgresql.space.postgresql_space_graphs import PostgreSQLSpaceGraphs
        graph_manager = PostgreSQLSpaceGraphs(space_impl)
        await graph_manager.create_graph(TEST_SPACE_ID, test_graph_uri, "Partition Import Test Graph")
        print(f"✅ Test graph created successfully")
        
        # Get database import functionality
        db_import = PostgreSQLSpaceDBImport(space_impl)
        
        print(f"📋 Space Implementation: {type(space_impl).__name__}")
        print(f"📋 Database Import: {type(db_import).__name__}")
        
        # Debug: Check configuration
        print(f"\n🔍 Configuration check:")
        print(f"  - Using logged tables (partitioned) for production")
        
        # Check if tables are partitioned
        async with space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                table_names = space_impl._get_table_names(TEST_SPACE_ID)
                term_table = table_names.get('term')
                quad_table = table_names.get('rdf_quad')
                
                # Check if term table is partitioned
                cursor.execute(f"""
                    SELECT partrelid FROM pg_partitioned_table WHERE partrelid = '{term_table}'::regclass
                """)
                term_partitioned = cursor.fetchone() is not None
                
                # Check if quad table is partitioned  
                cursor.execute(f"""
                    SELECT partrelid FROM pg_partitioned_table WHERE partrelid = '{quad_table}'::regclass
                """)
                quad_partitioned = cursor.fetchone() is not None
                
                print(f"  - Term table partitioned: {term_partitioned}")
                print(f"  - Quad table partitioned: {quad_partitioned}")
        
        # Verify WordNet data file exists
        wordnet_file = Path(__file__).parent.parent.parent / "test_data" / "kgframe-wordnet-0.0.2.nt"
        if not wordnet_file.exists():
            print(f"❌ Data file not found: {wordnet_file}")
            return False
        
        print(f"📁 WordNet data file: {wordnet_file}")
        print(f"📊 File size: {wordnet_file.stat().st_size / 1024 / 1024:.1f} MB")
        
        # Progress callback for import monitoring
        def progress_callback(processed_triples, rate):
            if processed_triples % 1000000 == 0:
                print(f"  Processed: {processed_triples:,} triples ({rate:.0f} triples/sec)")
        
        # Start partition import
        print(f"\n=== Starting Partition Import ===")
        print(f"Target: Zero-copy partition attachment method")
        
        import_start = time.time()
        import_id = f"partition_import_{int(time.time())}"
        
        # Phase 1: Setup partition import session
        print(f"\n🔧 Phase 1: Setting up partition import session")
        import_session = await db_import.setup_partition_import_session(
            TEST_SPACE_ID, TEST_GRAPH_URI, import_id=import_id
        )
        
        print(f"Created temp tables:")
        print(f"  - Temp quad table: {import_session['temp_quad_table']}")
        print(f"  - Temp term table: {import_session['temp_term_table']}")
        print(f"  - Dataset: {import_session['dataset_value']}")
        
        # Phase 2-3: Load N-Triples data into partition session
        print(f"\n📥 Phase 2-3: Loading N-Triples data into partition session")
        
        await db_import.load_ntriples_into_partition_session(
            import_session, 
            str(wordnet_file), 
            test_graph_uri,
            batch_size=100000,
            progress_callback=progress_callback
        )
        
        # Check loaded data counts
        async with space_impl.get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Check temp term table
                cursor.execute(f"SELECT COUNT(*) FROM {import_session['temp_term_table']}")
                term_count = cursor.fetchone()[0]
                
                # Check temp quad table
                cursor.execute(f"SELECT COUNT(*) FROM {import_session['temp_quad_table']}")
                quad_count = cursor.fetchone()[0]
                
                print(f"\n📊 Loaded data summary:")
                print(f"  - Terms: {term_count:,}")
                print(f"  - Quads: {quad_count:,}")
        
        # Phase 4: Zero-copy partition attachment
        print(f"\n🔗 Phase 4: Zero-copy partition attachment")
        attachment_result = await db_import.attach_partitions_zero_copy(import_session)
        
        if attachment_result['status'] == 'attached':
            print("✅ Partition attachment successful!")
            
            # Verify data is accessible through main tables
            async with space_impl.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    # Check main term table with dataset filter
                    cursor.execute(f"""
                        SELECT COUNT(*) FROM {import_session['main_term_table']} 
                        WHERE dataset = '{import_session['dataset_value']}'
                    """)
                    main_term_count = cursor.fetchone()[0]
                    
                    # Check main quad table with dataset filter
                    cursor.execute(f"""
                        SELECT COUNT(*) FROM {import_session['main_quad_table']} 
                        WHERE dataset = '{import_session['dataset_value']}'
                    """)
                    main_quad_count = cursor.fetchone()[0]
                    
                    # Debug: Check total counts without dataset filter
                    cursor.execute(f"SELECT COUNT(*) FROM {import_session['main_term_table']}")
                    total_term_count = cursor.fetchone()[0]
                    
                    cursor.execute(f"SELECT COUNT(*) FROM {import_session['main_quad_table']}")
                    total_quad_count = cursor.fetchone()[0]
                    
                    # Debug: Check what dataset values exist
                    cursor.execute(f"SELECT DISTINCT dataset FROM {import_session['main_term_table']} LIMIT 10")
                    term_datasets = [row[0] for row in cursor.fetchall()]
                    
                    cursor.execute(f"SELECT DISTINCT dataset FROM {import_session['main_quad_table']} LIMIT 10")
                    quad_datasets = [row[0] for row in cursor.fetchall()]
                    
                    print(f"\n🔍 Debug info:")
                    print(f"  - Expected dataset: '{import_session['dataset_value']}'")
                    print(f"  - Total terms (all datasets): {total_term_count:,}")
                    print(f"  - Total quads (all datasets): {total_quad_count:,}")
                    print(f"  - Term datasets found: {term_datasets}")
                    print(f"  - Quad datasets found: {quad_datasets}")
                    
                    print(f"\n📈 Final data counts in main tables:")
                    print(f"  - Terms: {main_term_count:,}")
                    print(f"  - Quads: {main_quad_count:,}")
        else:
            print(f"❌ Partition attachment failed: {attachment_result}")
            return False
        
        import_duration = time.time() - import_start
        
        # Display import results
        print(f"\n=== Partition Import Results ===")
        print(f"Import ID: {import_id}")
        print(f"Dataset: {import_session['dataset_value']}")
        print(f"Total quads imported: {main_quad_count:,}")
        print(f"Total terms imported: {main_term_count:,}")
        print(f"Total time: {import_duration:.2f}s")
        
        # Calculate performance metrics
        file_size_mb = wordnet_file.stat().st_size / 1024 / 1024
        if import_duration > 0:
            quads_per_sec = main_quad_count / import_duration
            mb_per_sec = file_size_mb / import_duration
            
            print(f"\n=== Performance Metrics ===")
            print(f"Quads/sec: {quads_per_sec:,.0f}")
            print(f"MB/sec: {mb_per_sec:.2f}")
        
        print(f"\n🎉 Partition import completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Partition import failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Close VitalGraph connection
        if impl:
            try:
                await impl.db_impl.disconnect()
                print(f"✅ Closed VitalGraph connection")
            except Exception as e:
                print(f"⚠️  Error closing VitalGraph: {e}")

if __name__ == "__main__":
    success = asyncio.run(main())
    if success:
        print("\n✅ SUCCESS: Partition import test completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ FAILURE: Partition import test failed!")
        sys.exit(1)
