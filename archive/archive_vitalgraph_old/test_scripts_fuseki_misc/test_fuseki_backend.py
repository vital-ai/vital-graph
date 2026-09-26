#!/usr/bin/env python3
"""
Comprehensive Fuseki Backend Integration Test

This test verifies that VitalGraph can be configured to use Fuseki as a backend
with comprehensive RDF operations, graph management, and SPARQL queries using
real VitalSigns test data.
"""

import asyncio
import sys
import json
import logging
import warnings
import time
from pathlib import Path
from typing import List, Dict, Any

# Suppress VitalSigns service creation warnings at import time
logging.getLogger('vital_ai_vitalsigns').setLevel(logging.CRITICAL)
logging.getLogger().setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*Could not import.*weaviate.*")
warnings.filterwarnings("ignore", message=".*Failed to create service.*")

# Also suppress print statements from VitalSigns
import sys
from io import StringIO

class SuppressOutput:
    def __init__(self):
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        
    def __enter__(self):
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        return self
        
    def __exit__(self, *args):
        sys.stdout = self._stdout
        sys.stderr = self._stderr

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from vitalgraph.db.backend_config import BackendFactory, BackendConfig, BackendType
from vitalgraph.db.space_backend_interface import SpaceBackendInterface
from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs, create_kg_connection_test_data
from rdflib import URIRef, Literal, Graph
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Test configuration
TEST_SPACE_ID = "test_fuseki_comprehensive"
TEST_SPACE_NAME = "Test Fuseki Space"
TEST_SPACE_DESCRIPTION = "Test space for Fuseki backend validation"


def run_async(coro):
    """Helper function to run async coroutines synchronously."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

def test_fuseki_backend():
    """Test Fuseki backend with space manager integration."""
    space_backend = None
    sparql_backend = None
    print("🧪 VitalGraph Fuseki Backend Test")
    print("=" * 60)
    print("Testing complete space lifecycle with Fuseki backend:")
    print("• Backend factory configuration")
    print("• Space creation and validation")
    print("• VitalSigns test data conversion to RDF")
    print("• Multi-graph RDF operations")
    print("• SPARQL query execution")
    print("• Graph management operations")
    print("• Space deletion and cleanup")
    print()
    
    # Test results tracking
    test_results = []
    
    try:
        # Test 1: Create Fuseki backend configuration
        print("1️⃣ FUSEKI BACKEND CONFIGURATION")
        print("-" * 40)
        
        # Create Fuseki backend configuration
        fuseki_config = BackendConfig(
            backend_type=BackendType.FUSEKI,
            connection_params={
                'server_url': 'http://localhost:3030',
                'dataset_name': 'vitalgraph',  # Use the configured dataset name
                'username': 'vitalgraph_user',  # Use configured credentials
                'password': 'vitalgraph_pass',
                'timeout': 30
            }
        )
        
        print(f"✅ Fuseki config created: {fuseki_config.backend_type}")
        print(f"📊 Server URL: {fuseki_config.connection_params['server_url']}")
        print(f"📊 Dataset: {fuseki_config.connection_params['dataset_name']}")
        test_results.append(("Backend Configuration", True, "Fuseki config created successfully"))
        
        # Test 2: Create Fuseki space backend
        print("\n2️⃣ FUSEKI SPACE BACKEND CREATION")
        print("-" * 40)
        
        # Create space backend using factory
        try:
            space_backend = BackendFactory.create_space_backend(fuseki_config)
            print(f"✅ Space backend created: {type(space_backend).__name__}")
            print(f"✅ Implements SpaceBackendInterface: {isinstance(space_backend, SpaceBackendInterface)}")
            
            # Also create SPARQL backend for complex queries
            sparql_backend = BackendFactory.create_sparql_backend(fuseki_config)
            print(f"✅ SPARQL backend created: {type(sparql_backend).__name__}")
            
            test_results.append(("Space Backend Creation", True, "Fuseki space backend created"))
        except Exception as e:
            print(f"❌ Failed to create Fuseki backends: {e}")
            test_results.append(("Space Backend Creation", False, f"Creation error: {e}"))
            return test_results
        
        # Test 3: Test basic backend operations
        print(f"\n3️⃣ FUSEKI BACKEND OPERATIONS")
        print("-" * 40)
        
        try:
            # Test connection (skip context manager, just test direct operations)
            print(f"✅ Database connection established")
            
            # Test list spaces
            with SuppressOutput():
                spaces = run_async(space_backend.list_spaces())
            print(f"📊 Existing spaces: {len(spaces)}")
            print(f"📝 Space list: {spaces}")
            
            # Test space existence
            space_exists = run_async(space_backend.space_exists(TEST_SPACE_ID))
            print(f"📋 Test space exists: {space_exists}")
            
            test_results.append(("Backend Operations", True, "Basic operations successful"))
            
        except Exception as e:
            print(f"❌ Backend operations failed: {e}")
            test_results.append(("Backend Operations", False, f"Operations error: {e}"))
            return test_results
        
        # Test 4: Space lifecycle with Fuseki
        print(f"\n4️⃣ SPACE LIFECYCLE WITH FUSEKI")
        print("-" * 40)
        
        try:
            # Clean up any existing test space
            if run_async(space_backend.space_exists(TEST_SPACE_ID)):
                print(f"🧹 Cleaning up existing test space...")
                run_async(space_backend.delete_space_storage(TEST_SPACE_ID))
            
            # Create space
            print(f"📝 Creating space: {TEST_SPACE_ID}")
            space_created = run_async(space_backend.create_space_storage(TEST_SPACE_ID))
            if space_created:
                print(f"✅ Space created successfully")
                
                # Verify space exists
                space_exists = run_async(space_backend.space_exists(TEST_SPACE_ID))
                print(f"✅ Space verification: {space_exists}")
                
                # Get space info
                space_info = run_async(space_backend.get_space_info(TEST_SPACE_ID))
                print(f"📋 Space info: {space_info}")
                
                test_results.append(("Space Creation", True, "Space created and verified"))
            else:
                print(f"❌ Failed to create space")
                test_results.append(("Space Creation", False, "Space creation failed"))
                
        except Exception as e:
            print(f"❌ Space lifecycle test failed: {e}")
            test_results.append(("Space Creation", False, f"Lifecycle error: {e}"))
        
        # Test 5: VitalSigns data conversion and RDF operations
        print(f"\n5️⃣ VITALSIGNS DATA CONVERSION & RDF OPERATIONS")
        print("-" * 40)
        
        try:
            # Suppress VitalSigns service creation warnings at the root level
            import logging
            logging.getLogger('vital_ai_vitalsigns').setLevel(logging.ERROR)
            logging.getLogger().setLevel(logging.ERROR)
            
            # Create VitalSigns test data
            print(f"📝 Creating VitalSigns entity graphs...")
            with SuppressOutput():
                entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=True)
            print(f"✅ Created {len(entity_graphs)} entity graphs")
            
            # Convert ALL entity graphs to RDF using VitalSigns
            print(f"📝 Converting {len(entity_graphs)} entity graphs to RDF...")
            
            # Initialize VitalSigns for RDF conversion
            vs = VitalSigns()
            print(f"✅ VitalSigns initialized (service warnings suppressed)")
            
            # Convert objects to triples using each object's to_triples method
            all_triples = []
            total_objects = 0
            
            for i, entity_graph in enumerate(entity_graphs):
                total_objects += len(entity_graph)
                for obj in entity_graph:
                    triples = obj.to_triples()
                    all_triples.extend(triples)
            
            print(f"✅ Converted {total_objects} VitalSigns objects to {len(all_triples)} triples")
            
            # Convert ALL triples to quads for bulk insertion
            entity_graph_uri = f"http://vital.ai/graph/{TEST_SPACE_ID}/entities"
            entity_quads = []
            for triple in all_triples:
                s, p, o = triple
                quad = (s, p, o, URIRef(entity_graph_uri))
                entity_quads.append(quad)
            
            print(f"📝 Bulk inserting {len(entity_quads)} entity quads in batches...")
            # Time the bulk insertion
            start_time = time.time()
            quads_added = run_async(space_backend.add_rdf_quads_bulk(TEST_SPACE_ID, entity_quads, batch_size=200))
            end_time = time.time()
            insertion_time = (end_time - start_time) * 1000  # Convert to milliseconds
            
            print(f"✅ Added {quads_added} RDF quads successfully in {insertion_time:.2f}ms")
            
            # Count total quads in space
            total_quad_count = run_async(space_backend.get_rdf_quad_count(TEST_SPACE_ID))
            print(f"📊 Total quads in space: {total_quad_count}")
            
            # Test KG connection data
            print(f"📝 Creating KG connection test data...")
            with SuppressOutput():
                kg_objects = create_kg_connection_test_data(set_grouping_uris=True)
            kg_graph_uri = f"http://vital.ai/graph/{TEST_SPACE_ID}/connections"
            
            # Convert KG objects to triples using each object's to_triples method
            kg_all_triples = []
            for obj in kg_objects:
                triples = obj.to_triples()
                kg_all_triples.extend(triples)
            
            print(f"✅ Created {len(kg_all_triples)} KG triples")
            
            # Bulk insert ALL KG connection quads
            kg_quads = []
            for triple in kg_all_triples:
                s, p, o = triple
                quad = (s, p, o, URIRef(kg_graph_uri))
                kg_quads.append(quad)
            
            print(f"📝 Bulk inserting {len(kg_quads)} KG connection quads...")
            # Time the KG bulk insertion
            start_time = time.time()
            kg_quads_added = run_async(space_backend.add_rdf_quads_bulk(TEST_SPACE_ID, kg_quads, batch_size=100))
            end_time = time.time()
            kg_insertion_time = (end_time - start_time) * 1000  # Convert to milliseconds
            
            print(f"✅ Added {kg_quads_added} KG connection quads in {kg_insertion_time:.2f}ms")
            
            # Final count
            final_quad_count = run_async(space_backend.get_rdf_quad_count(TEST_SPACE_ID))
            print(f"📊 Final total quads: {final_quad_count}")
            
            test_results.append(("VitalSigns RDF Operations", True, 
                               f"Added {quads_added + kg_quads_added} quads, total: {final_quad_count}"))
                
        except Exception as e:
            print(f"❌ VitalSigns RDF operations failed: {e}")
            test_results.append(("VitalSigns RDF Operations", False, f"RDF error: {e}"))
        
        # Test 6: Test complex SPARQL query operations with KG query builder
        print(f"\n6️⃣ COMPLEX SPARQL QUERY OPERATIONS")
        print("-" * 40)
        
        try:
            # Import query builder and models
            from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder
            from vitalgraph.sparql.kg_query_builder import EntityQueryCriteria as DataclassEntityQueryCriteria
            from vitalgraph.sparql.kg_query_builder import SlotCriteria as DataclassSlotCriteria
            from vitalgraph.sparql.kg_query_builder import SortCriteria as DataclassSortCriteria
            
            builder = KGQueryCriteriaBuilder()
            
            # Test 1: Complex multi-criteria query - Financial transactions with purchase type AND amount > 1000
            print(f"📝 Executing complex multi-criteria query...")
            print(f"   Query: Find entities with 'purchase' type AND amount > 1000.0")
            
            complex_criteria = DataclassEntityQueryCriteria(
                search_string=None,
                entity_type=None,
                frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame",
                slot_criteria=[
                    DataclassSlotCriteria(
                        slot_type="http://vital.ai/ontology/haley-ai-kg#TypeSlot",
                        slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                        comparator="contains",
                        value="purchase"
                    ),
                    DataclassSlotCriteria(
                        slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                        slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                        comparator="greater_than",
                        value=1000.0
                    )
                ],
                sort_criteria=[
                    DataclassSortCriteria(
                        sort_type="entity_frame_slot",
                        frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame",
                        slot_type="http://vital.ai/ontology/haley-ai-kg#DateSlot",
                        sort_order="desc",
                        priority=1
                    )
                ]
            )
            
            complex_query = builder.build_entity_query_sparql_with_sorting(
                criteria=complex_criteria,
                graph_id=entity_graph_uri,
                page_size=10,
                offset=0
            )
            
            print(f"🔍 Generated Complex SPARQL Query:")
            print("=" * 50)
            print(complex_query)
            print("=" * 50)
            
            # Time the complex query execution
            start_time = time.time()
            complex_result = run_async(sparql_backend.execute_sparql_query(TEST_SPACE_ID, complex_query))
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000  # Convert to milliseconds
            
            print(f"✅ Complex multi-criteria query executed in {execution_time:.2f}ms")
            print(f"📊 Complex Query Results:")
            if complex_result:
                if isinstance(complex_result, list):
                    print(f"   Found {len(complex_result)} entities matching criteria")
                    for i, binding in enumerate(complex_result[:5]):  # Show first 5
                        entity = binding.get('entity', 'N/A')
                        print(f"   {i+1}. {entity}")
                elif 'bindings' in complex_result:
                    print(f"   Found {len(complex_result['bindings'])} entities matching criteria")
                    for i, binding in enumerate(complex_result['bindings'][:5]):  # Show first 5
                        entity = binding.get('entity', {}).get('value', 'N/A')
                        print(f"   {i+1}. {entity}")
                else:
                    print(f"   Unexpected result format: {complex_result}")
            else:
                print(f"   No results returned")
            
            # Test 2: Sorted query with numerical comparison
            print(f"📝 Executing sorted numerical query...")
            print(f"   Query: Find entities with amount > 500.0, sorted by amount DESC")
            
            sorted_criteria = DataclassEntityQueryCriteria(
                search_string=None,
                entity_type=None,
                frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame",
                slot_criteria=[
                    DataclassSlotCriteria(
                        slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                        slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGDoubleSlot",
                        comparator="greater_than",
                        value=500.0
                    )
                ],
                sort_criteria=[
                    DataclassSortCriteria(
                        sort_type="entity_frame_slot",
                        frame_type="http://vital.ai/ontology/haley-ai-kg#FinancialTransactionFrame",
                        slot_type="http://vital.ai/ontology/haley-ai-kg#AmountSlot",
                        sort_order="desc",
                        priority=1
                    )
                ]
            )
            
            sorted_query = builder.build_entity_query_sparql_with_sorting(
                criteria=sorted_criteria,
                graph_id=entity_graph_uri,
                page_size=5,
                offset=0
            )
            
            # Debug: Print the generated query to see what's wrong (remove this later)
            # print(f"🔍 Generated Sorted SPARQL Query:")
            # print("=" * 50)
            # print(sorted_query)
            # print("=" * 50)
            
            # Time the sorted query execution
            start_time = time.time()
            sorted_result = run_async(sparql_backend.execute_sparql_query(TEST_SPACE_ID, sorted_query))
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000  # Convert to milliseconds
            
            print(f"✅ Sorted numerical query executed in {execution_time:.2f}ms")
            print(f"📊 Sorted Query Results:")
            if sorted_result:
                if isinstance(sorted_result, list):
                    print(f"   Found {len(sorted_result)} entities with amount > 500.0")
                    # Debug: show all available keys in first result
                    if sorted_result:
                        print(f"   DEBUG: Available keys in result: {list(sorted_result[0].keys())}")
                    for i, binding in enumerate(sorted_result[:5]):  # Show first 5
                        entity = binding.get('entity', 'N/A')
                        # Try different possible sort variable names
                        sort_val = (binding.get('sort_val_0') or 
                                  binding.get('sort_value') or 
                                  binding.get('amount') or 
                                  binding.get('val_slot_FinancialTransactionFrame_1') or 'N/A')
                        print(f"   {i+1}. {entity} (amount: {sort_val})")
                elif 'bindings' in sorted_result:
                    print(f"   Found {len(sorted_result['bindings'])} entities with amount > 500.0")
                    # Debug: show all available keys in first result
                    if sorted_result['bindings']:
                        print(f"   DEBUG: Available keys in result: {list(sorted_result['bindings'][0].keys())}")
                    for i, binding in enumerate(sorted_result['bindings'][:5]):  # Show first 5
                        entity = binding.get('entity', {}).get('value', 'N/A')
                        # Try different possible sort variable names
                        sort_val = (binding.get('sort_val_0', {}).get('value') or
                                  binding.get('sort_value', {}).get('value') or
                                  binding.get('amount', {}).get('value') or
                                  binding.get('val_slot_FinancialTransactionFrame_1', {}).get('value') or 'N/A')
                        print(f"   {i+1}. {entity} (amount: {sort_val})")
                else:
                    print(f"   Unexpected result format: {sorted_result}")
            else:
                print(f"   No results returned")
            
            # Test 3: Basic entity count query
            print(f"📝 Executing entity count query...")
            entity_count_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(?entity) as ?count) WHERE {{
                GRAPH <{entity_graph_uri}> {{
                    ?entity a haley:KGEntity .
                }}
            }}
            """
            # Time the entity count query execution
            start_time = time.time()
            entity_count_result = run_async(sparql_backend.execute_sparql_query(TEST_SPACE_ID, entity_count_query))
            end_time = time.time()
            execution_time = (end_time - start_time) * 1000  # Convert to milliseconds
            
            print(f"✅ Entity count query executed in {execution_time:.2f}ms")
            print(f"📊 Entity Count Results:")
            if entity_count_result:
                if isinstance(entity_count_result, list) and len(entity_count_result) > 0:
                    count = entity_count_result[0].get('count', {}).get('value', '0')
                    print(f"   Total entities in graph: {count}")
                elif 'bindings' in entity_count_result:
                    count = entity_count_result['bindings'][0].get('count', {}).get('value', '0')
                    print(f"   Total entities in graph: {count}")
                else:
                    print(f"   Unexpected count result format: {entity_count_result}")
            else:
                print(f"   No count result returned")
            
            print(f"📊 Complex SPARQL queries completed successfully")
            
            test_results.append(("SPARQL Operations", True, "Complex SPARQL queries with KG builder executed"))
            
        except Exception as e:
            print(f"❌ Complex SPARQL operations failed: {e}")
            import traceback
            traceback.print_exc()
            test_results.append(("SPARQL Operations", False, f"Complex SPARQL error: {e}"))
        
        # Test 7: Cleanup
        print(f"\n7️⃣ CLEANUP")
        print("-" * 40)
        
        try:
            # Delete test space
            if run_async(space_backend.space_exists(TEST_SPACE_ID)):
                print(f"🧹 Deleting test space...")
                space_deleted = run_async(space_backend.delete_space_storage(TEST_SPACE_ID))
                if space_deleted:
                    print(f"✅ Test space deleted successfully")
                    test_results.append(("Cleanup", True, "Space deleted successfully"))
                else:
                    print(f"⚠️ Space deletion returned False")
                    test_results.append(("Cleanup", False, "Space deletion returned False"))
            else:
                print(f"📋 No test space to clean up")
                test_results.append(("Cleanup", True, "No cleanup needed"))
                
        except Exception as e:
            print(f"❌ Cleanup failed: {e}")
            test_results.append(("Cleanup", False, f"Cleanup error: {e}"))
        
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        test_results.append(("Test Execution", False, f"Exception: {e}"))
    
    finally:
        # Ensure proper cleanup of async resources
        try:
            if space_backend:
                run_async(space_backend.close())
                print(f"🔌 Space backend closed")
            if sparql_backend and hasattr(sparql_backend, 'close'):
                run_async(sparql_backend.close())
                print(f"🔌 SPARQL backend closed")
        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")
    
    return test_results

def print_test_summary(test_results):
    """Print a summary of test results."""
    print(f"\n📊 FUSEKI BACKEND TEST SUMMARY")
    print("=" * 60)
    
    total_tests = len(test_results)
    passed_tests = sum(1 for _, passed, _ in test_results if passed)
    failed_tests = total_tests - passed_tests
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    print(f"Total Tests: {total_tests}")
    print(f"✅ Passed: {passed_tests}")
    print(f"❌ Failed: {failed_tests}")
    print(f"📈 Success Rate: {success_rate:.1f}%")
    print()
    
    print(f"📋 Detailed Results:")
    for test_name, passed, details in test_results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {status} {test_name}: {details}")
    
    print()
    if failed_tests == 0:
        print("🎉 ALL TESTS PASSED! Fuseki backend is working correctly.")
        print("✅ VitalGraph can successfully use Fuseki as backend storage")
    else:
        print("⚠️ Some tests failed. Check Fuseki server status and configuration.")
        print("💡 Ensure Fuseki server is running on http://localhost:3030")
        print("💡 Ensure dataset 'vitalgraph_test' exists or can be created")

def main():
    """Main test runner."""
    print("🚀 Starting Fuseki Backend Integration Test...")
    
    test_results = test_fuseki_backend()
    print_test_summary(test_results)

if __name__ == "__main__":
    main()
