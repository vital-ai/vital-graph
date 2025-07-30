#!/usr/bin/env python3
"""
WordNet Data Reload Script with Graph URI
==========================================

This script removes current space tables and reloads WordNet data with the proper graph URI set.
Based on test_space_impl_tables.py functionality.

Usage:
    python reload_wordnet_with_graph.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from rdflib import URIRef, Literal, BNode

# Add the project root directory to the path to import vitalgraph modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph.impl.vitalgraph_impl import VitalGraphImpl

# Set up logging for clean output
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)

# Configuration
SPACE_ID = "wordnet_space"
GRAPH_URI = "http://vital.ai/graph/wordnet"  # Standard graph URI used by most scripts
TARGET_TRIPLE_COUNT = None  # Load all triples (set to number for testing with subset)
BATCH_SIZE = 50000  # Larger batch size for better performance

async def reload_wordnet_data():
    """Main function to reload WordNet data with graph URI."""
    
    # Reduce logging chatter from verbose modules
    logging.getLogger('vitalgraph.db.postgresql.postgresql_space_impl').setLevel(logging.WARNING)
    logging.getLogger('vitalgraph.rdf.rdf_utils').setLevel(logging.WARNING)
    logging.getLogger('vitalgraph.db.postgresql.postgresql_cache_term').setLevel(logging.WARNING)
    
    print("🔄 WordNet Data Reload with Graph URI")
    print("=" * 50)
    
    # Step 1: Initialize VitalGraphImpl with config
    print("\n1. Initializing VitalGraphImpl with config file...")
    try:
        project_root = Path(__file__).parent.parent.parent  # Go up to project root from test_scripts/data
        config_path = project_root / "vitalgraphdb_config" / "vitalgraphdb-config.yaml"
        print(f"   Using config file: {config_path}")
        
        from vitalgraph.config.config_loader import get_config
        config = get_config(str(config_path))
        
        # Initialize VitalGraphImpl
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
        print(f"   DB implementation: {type(db_impl).__name__}")
        
    except Exception as e:
        print(f"❌ Error initializing VitalGraph: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Step 2: Connect to database
    print("\n2. Connecting to database...")
    try:
        await db_impl.connect()
        space_impl = db_impl.get_space_impl()
        print("✅ Connected to database successfully")
        print(f"   Space implementation: {type(space_impl).__name__}")
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        return False

    # Step 3: Delete existing space tables if present
    print(f"\n3. Deleting existing tables for space '{SPACE_ID}' if present...")
    try:
        # Try to delete space tables if they exist (ignore errors if they don't exist)
        success = space_impl.delete_space_tables(SPACE_ID)
        if success:
            print(f"✅ Deleted existing tables for space '{SPACE_ID}'")
        else:
            print(f"⚠️  Warning: Could not delete existing tables for space '{SPACE_ID}'")
    except Exception as e:
        print(f"   No existing tables to delete for space '{SPACE_ID}' (this is normal): {e}")

    # Step 4: Create UUID-based space tables
    print(f"\n4. Creating UUID-based space tables for '{SPACE_ID}'...")
    print(f"   🧪 Using UUID-based LOGGED tables for performance testing")
    try:
        success = space_impl.create_space_tables(SPACE_ID)
        if success:
            print(f"✅ UUID-based space tables created successfully for '{SPACE_ID}'")
        else:
            print(f"❌ Failed to create UUID-based space tables for '{SPACE_ID}'")
            return False
    except Exception as e:
        print(f"❌ Error creating UUID-based space tables: {e}")
        return False

    # Step 5: Drop indexes before bulk loading for maximum performance
    print(f"\n5. Dropping indexes before bulk loading for optimal performance...")
    try:
        success = space_impl.drop_indexes_for_bulk_load(SPACE_ID)
        if success:
            print(f"✅ Indexes dropped - bulk loading will be much faster")
        else:
            print(f"⚠️  Warning: Some indexes may not have been dropped")
    except Exception as e:
        print(f"❌ Error dropping indexes: {e}")
        return False
    
    # Step 6: Load WordNet data using batch insert with UUID-based approach
    print(f"\n6. Loading WordNet data using optimized batch insert (no index overhead)...")
    try:
        # Find the WordNet data file
        project_root = Path(__file__).parent.parent.parent  # Go up two levels from test_scripts/data
        test_data_file = project_root / "test_data" / "kgentity_wordnet.nt"
        
        if not test_data_file.exists():
            print(f"❌ WordNet data file not found: {test_data_file}")
            return False
            
        print(f"Loading WordNet data from: {test_data_file.name}")
        print(f"Graph URI: {GRAPH_URI}")
        print(f"Batch size: {BATCH_SIZE:,} quads")
        
        # Import required modules
        from vitalgraph.rdf.rdf_utils import stream_parse_ntriples_nquads_generator, RDFFormat
        
        # Define local function to convert string to RDFLib term
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
        
        # Process triples in batches for optimal performance
        print("Processing triples...")
        current_batch = []
        total_inserted = 0
        batch_loading_start = time.time()
        
        # Create a transaction for all batch operations
        transaction = await space_impl.core.create_transaction(space_impl)
        print(f"✅ Created transaction: {transaction.transaction_id}")
        print(f"📊 Active transactions: {space_impl.core.get_active_transaction_count()}")
        print("Processing triples with transaction management...")
        
        # Stream triples and collect them into batches
        for triple in stream_parse_ntriples_nquads_generator(str(test_data_file), RDFFormat.NT, progress_interval=2500):
            
            # Extract subject, predicate, object from the triple and convert to RDFLib objects
            subject_str, predicate_str, obj_str = triple
            
            subject = convert_string_to_rdflib_term(subject_str)
            predicate = convert_string_to_rdflib_term(predicate_str)
            obj = convert_string_to_rdflib_term(obj_str)
            graph = URIRef(GRAPH_URI)  # Set the graph URI
            
            quad = (subject, predicate, obj, graph)
            current_batch.append(quad)
            
            # When batch is full, insert it
            if len(current_batch) >= BATCH_SIZE:
                batch_start = time.time()
                
                # Insert batch using UUID-based batch insert method with performance optimization
                # auto_commit=False, verify_count=False for maximum bulk loading speed (commit at end)
                inserted_count = await space_impl.db_ops.add_rdf_quads_batch(SPACE_ID, current_batch, 
                                                                     auto_commit=False, verify_count=False, transaction=transaction)
                total_inserted += inserted_count
                
                batch_time = time.time() - batch_start
                quads_per_sec = inserted_count / batch_time if batch_time > 0 else 0
                
                # Show transaction statistics every 10 batches
                if (total_inserted // BATCH_SIZE) % 10 == 0:
                    stats = transaction.get_transaction_stats()
                    print(f"Inserted {total_inserted:,} quads ({quads_per_sec:,.0f} quads/sec) - "
                          f"Transaction stats: {stats['quads_added']:,} quads, {stats['terms_added']:,} terms")
                else:
                    print(f"Inserted {total_inserted:,} quads ({quads_per_sec:,.0f} quads/sec)")
                
                if inserted_count != len(current_batch):
                    print(f"⚠️  Warning: Batch insert returned {inserted_count}, expected {len(current_batch)}")
                    if inserted_count == 0:
                        print("❌ ERROR: Batch insert failed completely. Exiting.")
                        return False
                
                current_batch = []  # Reset batch
                
                # Check if we've reached target count
                if TARGET_TRIPLE_COUNT and total_inserted >= TARGET_TRIPLE_COUNT:
                    print(f"   Reached target count of {TARGET_TRIPLE_COUNT:,} triples")
                    break
        
        # Insert any remaining quads in the final partial batch
        if current_batch:
            final_batch_start = time.time()
            
            batch_inserted = await space_impl.db_ops.add_rdf_quads_batch(SPACE_ID, current_batch, 
                                                                auto_commit=False, verify_count=False, transaction=transaction)
            total_inserted += batch_inserted
            
            final_batch_time = time.time() - final_batch_start
            final_quads_per_sec = batch_inserted / final_batch_time if final_batch_time > 0 else 0
            print(f"Final batch: {batch_inserted:,} quads ({final_quads_per_sec:,.0f} quads/sec)")
            
            if batch_inserted != len(current_batch):
                print(f"⚠️  Warning: Final batch insert returned {batch_inserted}, expected {len(current_batch)}")
        
        # Commit all the batch inserts in one transaction for maximum performance
        print(f"\n💾 Committing all WordNet data...")
        commit_start = time.time()
        
        try:
            # Commit the transaction (synchronous method)
            success = await space_impl.core.commit_transaction_object(transaction)
            
            commit_time = time.time() - commit_start
            if success:
                print(f"✅ Transaction committed in {commit_time:.2f}s")
                print(f"📊 Active transactions after commit: {space_impl.core.get_active_transaction_count()}")
            else:
                print(f"❌ Transaction commit failed")
                return False
        except Exception as e:
            # Rollback on error (synchronous method)
            rollback_success = await space_impl.core.rollback_transaction_object(transaction)
            print(f"❌ Transaction commit failed, rolled back: {e} (rollback success: {rollback_success})")
            return False
        
        # Calculate and display total batch loading time
        total_batch_time = time.time() - batch_loading_start
        quads_per_second = total_inserted / total_batch_time if total_batch_time > 0 else 0
        
        print(f"\n✅ WordNet data loading completed successfully!")
        print(f"WordNet quads inserted: {total_inserted:,}")
        print(f"Loading time: {total_batch_time:.1f}s")
        print(f"Average rate: {quads_per_second:,.0f} quads/sec")
        
        # Add sample triples with NO graph URI to test global graph assignment
        print(f"\n📝 Adding sample triples to global graph (no graph URI specified)...")
        sample_triples = [
            # Some sample entities and relationships for testing
            (URIRef("http://example.org/person/alice"), URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), URIRef("http://example.org/Person")),
            (URIRef("http://example.org/person/alice"), URIRef("http://example.org/hasName"), Literal("Alice Smith")),
            (URIRef("http://example.org/person/alice"), URIRef("http://example.org/hasAge"), Literal("30", datatype=URIRef("http://www.w3.org/2001/XMLSchema#integer"))),
            
            (URIRef("http://example.org/person/bob"), URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type"), URIRef("http://example.org/Person")),
            (URIRef("http://example.org/person/bob"), URIRef("http://example.org/hasName"), Literal("Bob Jones")),
            (URIRef("http://example.org/person/bob"), URIRef("http://example.org/hasAge"), Literal("25", datatype=URIRef("http://www.w3.org/2001/XMLSchema#integer"))),
            
            # Relationship between them
            (URIRef("http://example.org/person/alice"), URIRef("http://example.org/knows"), URIRef("http://example.org/person/bob")),
            
            # Some test data that should be findable in default graph queries
            (URIRef("http://example.org/test/entity1"), URIRef("http://example.org/hasProperty"), Literal("global_test_value")),
            (URIRef("http://example.org/test/entity2"), URIRef("http://example.org/hasProperty"), Literal("another_global_value")),
        ]
        
        # Convert triples to quads with None as graph (should trigger global graph assignment)
        sample_quads = [(s, p, o, None) for s, p, o in sample_triples]
        
        # Create a new transaction for sample data (previous transaction was committed)
        sample_transaction = await space_impl.core.create_transaction(space_impl)
        
        # Insert sample quads using the new transaction
        sample_start = time.time()
        sample_inserted = await space_impl.db_ops.add_rdf_quads_batch(SPACE_ID, sample_quads, 
                                                                     auto_commit=False, transaction=sample_transaction)
        sample_time = time.time() - sample_start
        
        # Commit the sample transaction
        sample_commit_success = await space_impl.core.commit_transaction_object(sample_transaction)
        
        print(f"✅ Sample global graph data inserted: {sample_inserted} quads in {sample_time:.3f}s")
        
        # Update totals
        total_inserted += sample_inserted
        total_batch_time += sample_time
        quads_per_second = total_inserted / total_batch_time if total_batch_time > 0 else 0
        
    except Exception as e:
        print(f"❌ Error loading WordNet data: {e}")
        import traceback
        traceback.print_exc()
        
        # Ensure transaction is rolled back on any error
        try:
            if 'transaction' in locals() and transaction:
                rollback_success = await space_impl.core.rollback_transaction_object(transaction)
                print(f"🔄 Transaction rolled back due to error (success: {rollback_success})")
        except Exception as rollback_error:
            print(f"⚠️ Warning: Failed to rollback transaction: {rollback_error}")
        
        return False

    # Step 7: Recreate indexes after bulk loading for optimal query performance
    print(f"\n7. Recreating indexes after bulk loading for optimal query performance...")
    try:
        success = space_impl.recreate_indexes_after_bulk_load(SPACE_ID, concurrent=False)
        if success:
            print(f"✅ All indexes recreated successfully - queries will be fast")
        else:
            print(f"⚠️  Warning: Some indexes may not have been recreated")
    except Exception as e:
        print(f"❌ Error recreating indexes: {e}")
        return False

    # Step 8: Verify data loading
    print(f"\n8. Verifying data loading...")
    try:
        # Add a small delay to ensure async operations are committed
        import asyncio
        await asyncio.sleep(0.5)
        
        # Get table names using the same logic as table creation (respects use_unlogged config)
        table_names = space_impl._get_table_names(SPACE_ID)
        quad_table_name = table_names['rdf_quad']
        
        # Use synchronous connection but ensure we're reading committed data
        with space_impl.get_connection() as conn:
            with conn.cursor() as cursor:
                # Ensure we read committed data
                cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                cursor.execute(f"SELECT COUNT(*) FROM {quad_table_name}")
                result = cursor.fetchone()
                quad_count = result['count'] if result else 0
        
        if quad_count and quad_count > 0:
            print(f"✅ Verification completed - {quad_count:,} quads in database")
        else:
            print(f"⚠️  Warning: No quads found in database - data loading may have failed")
            print(f"   Table queried: {quad_table_name}")
            # Let's also check if the table exists
            with space_impl.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)", (quad_table_name.split('.')[-1],))
                    table_exists = cursor.fetchone()['exists']
                    print(f"   Table exists: {table_exists}")
        
    except Exception as e:
        print(f"❌ Error verifying data: {e}")
        print(f"   Attempted to query table: {quad_table_name if 'quad_table_name' in locals() else 'unknown'}")
        return False

    # Step 8: Disconnect
    print(f"\n8. Disconnecting from database...")
    try:
        await db_impl.disconnect()
        print("✅ Database disconnected successfully")
    except Exception as e:
        print(f"❌ Error disconnecting: {e}")

    print("\n" + "=" * 60)
    print("🎉 WordNet Data Reload Completed Successfully!")
    print(f"Space: {SPACE_ID} | Graph: {GRAPH_URI}")
    print(f"Quads: {total_inserted:,} | Time: {total_batch_time:.1f}s | Rate: {quads_per_second:,.0f}/sec")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    asyncio.run(reload_wordnet_data())
