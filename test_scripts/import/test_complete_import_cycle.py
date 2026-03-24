#!/usr/bin/env python3
"""
Complete Import Cycle Test Script
=================================

Test the complete end-to-end import process in VitalGraph including:
- GraphImportOp with database integration
- Complete Phase 1-5 import cycle (validation, loading, processing, transfer, cleanup)
- Performance validation and correctness verification
- Integration between GraphImportOp and PostgreSQLSpaceDBImport

This test validates the newly connected import components work together correctly.
"""

import asyncio
import logging
import sys
import time
import tempfile
import os
import argparse
from pathlib import Path

# Add project root directory for vitalgraph imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl
from vitalgraph.config.config_loader import get_config
from vitalgraph.ops.graph_import_op import GraphImportOp, ImportMethod

# Configure logging to see detailed import operations
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(name)s - %(message)s')

# Suppress verbose logging from other modules
logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
logging.getLogger('vitalgraph.db.postgresql.space.postgresql_space_core').setLevel(logging.WARNING)

# Test configuration
timestamp = int(time.time()) % 10000  # Use last 4 digits only
TEST_SPACE_ID = f"test_{timestamp}"  # Shortened to fit 15 char limit
TEST_SPACE_NAME = "Complete Import Test Space"
TEST_SPACE_DESCRIPTION = "Test space created by complete import test script"
DEFAULT_TEST_GRAPH_URI = "http://vital.ai/test/complete_import_graph"
WORDNET_GRAPH_URI = "urn:kgframe-wordnet-002"

def create_small_test_file() -> str:
    """Create a small N-Triples test file for import testing."""
    test_data = """<http://example.org/person/1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
<http://example.org/person/1> <http://example.org/name> "John Doe" .
<http://example.org/person/1> <http://example.org/age> "30"^^<http://www.w3.org/2001/XMLSchema#integer> .
<http://example.org/person/1> <http://example.org/email> "john@example.org" .
<http://example.org/person/2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .
<http://example.org/person/2> <http://example.org/name> "Jane Smith" .
<http://example.org/person/2> <http://example.org/age> "25"^^<http://www.w3.org/2001/XMLSchema#integer> .
<http://example.org/person/2> <http://example.org/email> "jane@example.org" .
<http://example.org/organization/1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Organization> .
<http://example.org/organization/1> <http://example.org/name> "Example Corp" .
<http://example.org/person/1> <http://example.org/worksFor> <http://example.org/organization/1> .
<http://example.org/person/2> <http://example.org/worksFor> <http://example.org/organization/1> .
"""
    
    # Create temporary file
    fd, temp_path = tempfile.mkstemp(suffix='.nt', prefix='vitalgraph_test_')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(test_data)
        return temp_path
    except:
        os.close(fd)
        raise

def create_large_test_file(num_triples: int = 100000) -> str:
    """Create a larger N-Triples test file for performance testing."""
    print(f"📝 Generating large test file with {num_triples:,} triples...")
    
    # Create temporary file
    fd, temp_path = tempfile.mkstemp(suffix='.nt', prefix='vitalgraph_large_test_')
    
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            # Generate test data in batches to avoid memory issues
            batch_size = 10000
            for batch_start in range(0, num_triples, batch_size):
                batch_end = min(batch_start + batch_size, num_triples)
                batch_data = []
                
                for i in range(batch_start, batch_end):
                    person_id = i % 1000  # Cycle through 1000 persons
                    org_id = i % 100      # Cycle through 100 organizations
                    
                    # Generate varied triples for each person
                    if i % 4 == 0:
                        batch_data.append(f'<http://example.org/person/{person_id}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://example.org/Person> .')
                    elif i % 4 == 1:
                        batch_data.append(f'<http://example.org/person/{person_id}> <http://example.org/name> "Person {person_id}" .')
                    elif i % 4 == 2:
                        age = 20 + (person_id % 50)
                        batch_data.append(f'<http://example.org/person/{person_id}> <http://example.org/age> "{age}"^^<http://www.w3.org/2001/XMLSchema#integer> .')
                    else:
                        batch_data.append(f'<http://example.org/person/{person_id}> <http://example.org/worksFor> <http://example.org/organization/{org_id}> .')
                
                f.write('\n'.join(batch_data) + '\n')
                
                # Progress indicator
                if (batch_end % 50000) == 0:
                    print(f"  Generated {batch_end:,} triples...")
        
        file_size = os.path.getsize(temp_path)
        print(f"✅ Generated test file: {file_size / 1024 / 1024:.1f} MB")
        return temp_path
        
    except:
        os.close(fd)
        raise

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='VitalGraph Import Cycle Test',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with WordNet file using partition method
  python test_complete_import_cycle.py --file /path/to/wordnet.nt --method partition
  
  # Test with WordNet file using traditional method
  python test_complete_import_cycle.py --file /path/to/wordnet.nt --method traditional
  
  # Test with generated data (50K triples)
  python test_complete_import_cycle.py --method partition --triples 50000
  
  # Test with small generated data
  python test_complete_import_cycle.py --method traditional --triples 100
        """
    )
    
    parser.add_argument(
        '--file', '-f',
        type=str,
        help='Path to N-Triples file to import (if not specified, generates test data)'
    )
    
    parser.add_argument(
        '--method', '-m',
        choices=['partition', 'traditional', 'auto'],
        default='partition',
        help='Import method to use (default: partition)'
    )
    
    parser.add_argument(
        '--triples', '-t',
        type=int,
        default=50000,
        help='Number of triples to generate if no file specified (default: 50000)'
    )
    
    parser.add_argument(
        '--batch-size', '-b',
        type=int,
        default=100000,
        help='Batch size for import operations (default: 100000)'
    )
    
    return parser.parse_args()

async def test_vitalgraph_initialization():
    """Test VitalGraphImpl initialization and basic functionality."""
    print("🚀 VitalGraph Complete Import Cycle Test")
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

class ProgressTracker:
    """Track and display detailed progress during import operations."""
    
    def __init__(self):
        self.last_update = time.time()
        self.last_count = 0
        
    def __call__(self, processed_count: int, rate: float = None):
        """Progress callback function with detailed logging."""
        current_time = time.time()
        
        # Calculate rate if not provided
        if rate is None and processed_count > self.last_count:
            time_diff = current_time - self.last_update
            if time_diff > 0:
                rate = (processed_count - self.last_count) / time_diff
        
        # Log progress every 10,000 items or every 5 seconds
        if (processed_count % 10000 == 0) or (current_time - self.last_update >= 5.0):
            if rate:
                print(f"    📊 Progress: {processed_count:,} items processed ({rate:,.0f} items/sec)")
            else:
                print(f"    📊 Progress: {processed_count:,} items processed")
            
            self.last_update = current_time
            self.last_count = processed_count

async def test_complete_import_cycle(impl, space_id: str, test_file_path: str, import_method: ImportMethod = ImportMethod.AUTO, graph_uri: str = DEFAULT_TEST_GRAPH_URI, batch_size: int = 100000):
    """Test the complete import cycle using GraphImportOp."""
    print(f"\n2️⃣ COMPLETE IMPORT CYCLE TEST ({import_method.value.upper()})")
    print(f"------------------------------")
    
    # Get space implementation for GraphImportOp
    space_impl = impl.db_impl.space_impl
    
    # Create progress tracker
    progress_tracker = ProgressTracker()
    
    # Create GraphImportOp with database integration
    import_op = GraphImportOp(
        file_path=test_file_path,
        space_id=space_id,
        graph_uri=graph_uri,
        validate_before_import=True,
        batch_size=batch_size,
        import_method=import_method,
        space_impl=space_impl
    )
    
    print(f"📋 Created GraphImportOp:")
    print(f"  - File: {test_file_path}")
    print(f"  - Space: {space_id}")
    print(f"  - Graph: {graph_uri}")
    print(f"  - Batch size: {batch_size:,}")
    print(f"  - Operation ID: {import_op.operation_id}")
    
    # Execute the complete import with detailed progress tracking
    print(f"\n🔄 Executing complete import cycle...")
    print(f"    🔍 Phase 1: File validation and format detection...")
    start_time = time.time()
    
    # Override the internal progress callback to use our detailed tracker
    original_update_progress = import_op.update_progress
    def enhanced_update_progress(message):
        print(f"    📋 {message}")
        original_update_progress(message)
    
    import_op.update_progress = enhanced_update_progress
    
    result = await import_op.execute()
    
    execution_time = time.time() - start_time
    
    print(f"\n📊 Import Results:")
    print(f"  - Status: {result.status.value}")
    print(f"  - Message: {result.message}")
    print(f"  - Execution Time: {execution_time:.2f}s")
    
    if result.warnings:
        print(f"  - Warnings: {len(result.warnings)}")
        for warning in result.warnings:
            print(f"    ⚠️  {warning}")
    
    if result.status.value == 'success':
        print(f"✅ Import completed successfully!")
        
        # Display detailed statistics
        if result.details and 'import_stats' in result.details:
            import_stats = result.details['import_stats']
            print(f"\n📈 Import Statistics:")
            
            if 'total_triples_imported' in import_stats:
                print(f"  - Triples imported: {import_stats['total_triples_imported']:,}")
            if 'total_terms_created' in import_stats:
                print(f"  - Terms created: {import_stats['total_terms_created']:,}")
            if 'import_method' in import_stats:
                print(f"  - Import method: {import_stats['import_method']}")
            
            # Show phase-by-phase performance
            if 'bulk_import_stats' in import_stats:
                bulk_stats = import_stats['bulk_import_stats']
                print(f"\n📊 Phase Performance:")
                print(f"  - Phase 2 (Parsing): {bulk_stats.get('parsing_time', 0):.2f}s")
                print(f"  - Phase 2 (Loading): {bulk_stats.get('copy_time', 0):.2f}s")
                print(f"  - Total Phases 1-3: {bulk_stats.get('total_time', 0):.2f}s")
            
            if 'transfer_stats' in import_stats:
                transfer_stats = import_stats['transfer_stats']
                print(f"  - Phase 4 (Transfer): {transfer_stats.get('total_time', 0):.2f}s")
                if 'terms_per_sec' in transfer_stats:
                    print(f"  - Terms/sec: {transfer_stats['terms_per_sec']:,.0f}")
                if 'quads_per_sec' in transfer_stats:
                    print(f"  - Quads/sec: {transfer_stats['quads_per_sec']:,.0f}")
        
        return True
    else:
        print(f"❌ Import failed!")
        if result.error:
            print(f"  - Error: {result.error}")
        return False

async def verify_imported_data(impl, space_id: str):
    """Verify that the imported data is accessible in the main tables."""
    print(f"\n3️⃣ DATA VERIFICATION")
    print(f"------------------------------")
    
    space_impl = impl.db_impl.space_impl
    table_names = space_impl._get_table_names(space_id)
    term_table = table_names['term']
    quad_table = table_names['rdf_quad']
    
    async with space_impl.get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Check term count
            cursor.execute(f"SELECT COUNT(*) FROM {term_table}")
            term_count = cursor.fetchone()[0]
            
            # Check quad count
            cursor.execute(f"SELECT COUNT(*) FROM {quad_table}")
            quad_count = cursor.fetchone()[0]
            
            # Debug: Check dataset distribution
            cursor.execute(f"SELECT dataset, COUNT(*) FROM {term_table} GROUP BY dataset")
            term_datasets = cursor.fetchall()
            cursor.execute(f"SELECT dataset, COUNT(*) FROM {quad_table} GROUP BY dataset")
            quad_datasets = cursor.fetchall()
            
            print(f"\n🔍 Debug - Dataset Distribution:")
            print(f"  - Term datasets: {term_datasets}")
            print(f"  - Quad datasets: {quad_datasets}")
            
            # Check specific data samples
            cursor.execute(f"""
                SELECT term_text, term_type FROM {term_table} 
                WHERE term_text LIKE '%person%' 
                ORDER BY term_text LIMIT 5
            """)
            sample_terms = cursor.fetchall()
            
            cursor.execute(f"""
                SELECT COUNT(*) FROM {quad_table} q
                JOIN {term_table} s ON q.subject_uuid = s.term_uuid
                JOIN {term_table} p ON q.predicate_uuid = p.term_uuid
                WHERE s.term_text LIKE '%person%'
            """)
            person_quad_count = cursor.fetchone()[0]
            
            print(f"📊 Data Verification Results:")
            print(f"  - Total terms: {term_count:,}")
            print(f"  - Total quads: {quad_count:,}")
            print(f"  - Person-related quads: {person_quad_count:,}")
            
            print(f"\n📋 Sample terms:")
            for term_text, term_type in sample_terms:
                print(f"  - {term_type}: {term_text}")
            
            # Verify expected data
            expected_min_terms = 10  # At least 10 unique terms
            expected_min_quads = 12  # 12 triples in test data
            
            if term_count >= expected_min_terms and quad_count >= expected_min_quads:
                print(f"✅ Data verification passed!")
                return True
            else:
                print(f"❌ Data verification failed!")
                print(f"  Expected: ≥{expected_min_terms} terms, ≥{expected_min_quads} quads")
                print(f"  Actual: {term_count} terms, {quad_count} quads")
                return False

async def main():
    """Main test function."""
    # Parse command line arguments
    args = parse_arguments()
    
    test_file_path = None
    impl = None
    
    try:
        # Test 1: Initialize VitalGraph
        impl = await test_vitalgraph_initialization()
        
        # Test 2: Initialize space manager from database
        space_manager = impl.get_space_manager()
        print(f"\n🔄 Initializing SpaceManager from database...")
        await space_manager.initialize_from_database()
        print(f"✅ SpaceManager initialized with {len(space_manager)} spaces")
        
        # Test 3: Delete and recreate test space to ensure clean state
        print(f"\n🗑️ Cleaning up test space '{TEST_SPACE_ID}' if it exists...")
        try:
            await space_manager.delete_space_with_tables(TEST_SPACE_ID)
            print(f"🗑️  Deleted existing space: {TEST_SPACE_ID}")
        except Exception as e:
            print(f"ℹ️  Space {TEST_SPACE_ID} didn't exist or couldn't be deleted: {e}")
        
        # Create the test space
        print(f"🏗️  Creating space: {TEST_SPACE_ID}")
        await space_manager.create_space_with_tables(TEST_SPACE_ID, TEST_SPACE_NAME)
        print(f"✅ Space created successfully: {TEST_SPACE_ID}")
        
        # Test 4: Prepare test data file
        print(f"\n📁 Preparing test data file...")
        
        if args.file:
            # Use specified file
            test_file_path = args.file
            if not os.path.exists(test_file_path):
                print(f"❌ File not found: {test_file_path}")
                return False
            
            file_size = os.path.getsize(test_file_path)
            print(f"✅ Using specified file: {test_file_path}")
            print(f"📊 File size: {file_size / 1024 / 1024:.1f} MB ({file_size:,} bytes)")
            
            # Use WordNet graph URI for WordNet files
            if 'wordnet' in test_file_path.lower():
                graph_uri = WORDNET_GRAPH_URI
                print(f"🔗 Using WordNet graph URI: {graph_uri}")
            else:
                graph_uri = DEFAULT_TEST_GRAPH_URI
                print(f"🔗 Using default graph URI: {graph_uri}")
        else:
            # Generate test data
            if args.triples <= 100:
                test_file_path = create_small_test_file()
                print(f"✅ Using small test file (12 triples)")
            else:
                test_file_path = create_large_test_file(args.triples)
                print(f"✅ Using generated test file ({args.triples:,} triples)")
            
            file_size = os.path.getsize(test_file_path)
            print(f"📊 File size: {file_size / 1024 / 1024:.1f} MB ({file_size:,} bytes)")
            graph_uri = DEFAULT_TEST_GRAPH_URI
        
        # Convert method string to ImportMethod enum
        method_map = {
            'partition': ImportMethod.PARTITION,
            'traditional': ImportMethod.TRADITIONAL,
            'auto': ImportMethod.AUTO
        }
        import_method = method_map[args.method]
        
        # Test 5: Execute complete import cycle with specified method
        print(f"\n🔄 Testing {args.method.upper()} import method...")
        success = await test_complete_import_cycle(
            impl, 
            TEST_SPACE_ID, 
            test_file_path, 
            import_method,
            graph_uri,
            args.batch_size
        )
        if not success:
            return False
        
        # Test 6: Verify imported data
        verification_success = await verify_imported_data(impl, TEST_SPACE_ID)
        if not verification_success:
            return False
        
        print(f"\n🎉 {args.method.upper()} import cycle test completed successfully!")
        print(f"✅ {args.method.upper()} method: {'✅ PASSED' if success else '❌ FAILED'}")
        print(f"✅ Data verification: {'✅ PASSED' if verification_success else '❌ FAILED'}")
        return True
        
    except Exception as e:
        print(f"❌ Complete import cycle test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        if test_file_path and os.path.exists(test_file_path):
            os.unlink(test_file_path)
            print(f"🧹 Cleaned up test file: {test_file_path}")
        
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
        args = parse_arguments()
        print(f"\n✅ SUCCESS: {args.method.upper()} import cycle test passed!")
        print(f"🎯 Import method '{args.method}' validated:")
        if args.file:
            print(f"  - File: {args.file}")
        else:
            print(f"  - Generated data: {args.triples:,} triples")
        print(f"  - Batch size: {args.batch_size:,}")
        print("  - Detailed progress logging throughout all phases")
        if args.method == 'partition':
            print("  - Zero-copy partition attachment with automatic index inheritance")
        elif args.method == 'traditional':
            print("  - Complete index optimization with drop/recreate cycle")
        print("  - ANALYZE run for optimal query planning")
        sys.exit(0)
    else:
        print("\n❌ FAILURE: Import cycle test failed!")
        sys.exit(1)
