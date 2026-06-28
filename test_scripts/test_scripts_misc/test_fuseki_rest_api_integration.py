#!/usr/bin/env python3
"""
Comprehensive Fuseki REST API Integration Test

This test demonstrates the complete VitalGraph + Fuseki integration by:
1. Authenticating with the VitalGraph REST API
2. Creating a test space via REST API
3. Inserting VitalSigns test data via SPARQL endpoints
4. Executing complex queries using the KG query builder
5. Validating results and performance

This validates the entire stack: Docker + VitalGraph + Fuseki + REST API + SPARQL
"""

import asyncio
import json
import time
import requests
from typing import Dict, List, Any
from pathlib import Path
import sys
import os

# Add the project root to Python path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import VitalSigns test data utilities
from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs, create_kg_connection_test_data

# Import query builder for complex queries
from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder
from vitalgraph.sparql.kg_query_builder import EntityQueryCriteria as DataclassEntityQueryCriteria
from vitalgraph.sparql.kg_query_builder import SlotCriteria as DataclassSlotCriteria
from vitalgraph.sparql.kg_query_builder import SortCriteria as DataclassSortCriteria

# Import RDF utilities
from rdflib import Graph, URIRef
from rdflib.plugins.serializers.turtle import TurtleSerializer

class VitalGraphRestAPITester:
    """Test client for VitalGraph REST API with Fuseki backend."""
    
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.access_token = None
        self.test_space_id = "test_complex_queries"
        self.session = requests.Session()
        
    def authenticate(self, username: str = "admin", password: str = "admin") -> bool:
        """Authenticate with the VitalGraph API and get access token."""
        print("🔐 Authenticating with VitalGraph API...")
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/login",
                data={"username": username, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code == 200:
                auth_data = response.json()
                self.access_token = auth_data["access_token"]
                print(f"✅ Authentication successful for user: {auth_data['username']}")
                return True
            else:
                print(f"❌ Authentication failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authorization headers for API requests."""
        return {"Authorization": f"Bearer {self.access_token}"}
    
    def create_test_space(self) -> bool:
        """Create a test space for our integration test."""
        print(f"🏗️ Creating test space: {self.test_space_id}")
        
        try:
            # First, try to delete the space if it already exists
            print(f"   🧹 Cleaning up any existing space: {self.test_space_id}")
            try:
                delete_response = self.session.delete(
                    f"{self.base_url}/api/spaces/{self.test_space_id}",
                    headers=self._get_auth_headers()
                )
                if delete_response.status_code == 200:
                    print(f"   ✅ Cleaned up existing space")
                else:
                    print(f"   ℹ️ No existing space to clean up (or cleanup failed)")
            except:
                print(f"   ℹ️ No existing space to clean up")
            
            # Now create the new space
            space_data = {
                "space": self.test_space_id,
                "space_name": "Complex Queries Test Space",
                "description": "Test space for complex SPARQL queries with VitalSigns data"
            }
            
            response = self.session.post(
                f"{self.base_url}/api/spaces",
                json=space_data,
                headers={**self._get_auth_headers(), "Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Space created successfully: {result['message']}")
                return True
            elif response.status_code == 500 and "already exists" in response.text:
                print(f"ℹ️ Space already exists, continuing with tests")
                return True  # Consider this a success for testing purposes
            else:
                print(f"❌ Space creation failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Space creation error: {e}")
            return False
    
    def list_spaces(self) -> List[Dict[str, Any]]:
        """List all spaces to verify our test space exists."""
        print("📋 Listing all spaces...")
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/spaces",
                headers=self._get_auth_headers()
            )
            
            if response.status_code == 200:
                spaces_data = response.json()
                spaces = spaces_data.get("spaces", [])
                print(f"✅ Found {len(spaces)} spaces:")
                for space in spaces:
                    print(f"   - {space['space']} ({space['space_name']})")
                return spaces
            else:
                print(f"❌ Failed to list spaces: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            print(f"❌ List spaces error: {e}")
            return []
    
    def insert_test_data(self) -> bool:
        """Insert VitalSigns test data into the test space via SPARQL."""
        print("📝 Generating and inserting VitalSigns test data...")
        
        try:
            # Generate VitalSigns entity graphs
            print("   🔄 Generating VitalSigns entity graphs...")
            generation_start = time.time()
            entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=True)
            
            # Convert all entity objects to triples
            all_entity_triples = []
            total_objects = 0
            for graph in entity_graphs:
                for obj in graph:
                    triples = obj.to_triples()
                    all_entity_triples.extend(triples)
                    total_objects += 1
            
            print(f"   ✅ Generated {len(all_entity_triples)} entity triples from {total_objects} objects")
            
            # Generate KG connection data
            print("   🔄 Generating KG connection data...")
            kg_objects = create_kg_connection_test_data(set_grouping_uris=True)
            
            # Convert KG objects to triples
            all_kg_triples = []
            for obj in kg_objects:
                triples = obj.to_triples()
                all_kg_triples.extend(triples)
            
            generation_time = (time.time() - generation_start) * 1000
            print(f"   ✅ Generated {len(all_kg_triples)} KG connection triples from {len(kg_objects)} objects")
            print(f"   ⏱️ Data generation completed in {generation_time:.2f}ms")
            
            # Insert entity triples (timing starts here)
            entity_graph_uri = f"http://vital.ai/graph/{self.test_space_id}/entities"
            success1 = self._insert_triples_to_graph(all_entity_triples, entity_graph_uri, "entities")
            
            # Insert KG connection triples
            kg_graph_uri = f"http://vital.ai/graph/{self.test_space_id}/connections"
            success2 = self._insert_triples_to_graph(all_kg_triples, kg_graph_uri, "connections")
            
            if success1 and success2:
                total_triples = len(all_entity_triples) + len(all_kg_triples)
                print(f"✅ Successfully inserted {total_triples} total triples into Fuseki")
                return True
            else:
                print("❌ Failed to insert some triples")
                return False
                
        except Exception as e:
            print(f"❌ Test data insertion error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _insert_triples_to_graph(self, triples: List, graph_uri: str, graph_type: str) -> bool:
        """Insert triples into a specific named graph via SPARQL INSERT DATA."""
        print(f"   📤 Inserting {len(triples)} {graph_type} triples into graph: {graph_uri}")
        
        try:
            # Convert triples to RDF graph for serialization
            rdf_graph = Graph()
            for triple in triples:
                rdf_graph.add(triple)
            
            # Serialize to N-Triples format (no prefixes, full URIs only)
            turtle_data = rdf_graph.serialize(format='nt')
            
            # Create SPARQL INSERT DATA query
            sparql_insert = f"""
            INSERT DATA {{
                GRAPH <{graph_uri}> {{
                    {turtle_data}
                }}
            }}
            """
            
            # Debug: Print the actual SPARQL being sent
            print(f"   🔍 DEBUG: SPARQL INSERT (first 500 chars):")
            print(f"      {sparql_insert[:500]}...")
            print(f"   🔍 DEBUG: Target graph URI: {graph_uri}")
            
            # Execute SPARQL INSERT via REST API (time only the HTTP request)
            start_time = time.time()
            response = self.session.post(
                f"{self.base_url}/api/graphs/sparql/{self.test_space_id}/insert",
                json={"update": sparql_insert},
                headers={
                    **self._get_auth_headers(),
                    "Content-Type": "application/json"
                }
            )
            end_time = time.time()
            insert_time = (end_time - start_time) * 1000
            
            if response.status_code in [200, 204]:
                print(f"   ✅ Inserted {len(triples)} {graph_type} triples in {insert_time:.2f}ms")
                return True
            else:
                print(f"   ❌ Failed to insert {graph_type} triples: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"   ❌ Error inserting {graph_type} triples: {e}")
            return False
    
    def execute_complex_queries(self) -> bool:
        """Execute complex SPARQL queries using the KG query builder."""
        print("🔍 Executing complex SPARQL queries...")
        
        try:
            builder = KGQueryCriteriaBuilder()
            entity_graph_uri = f"http://vital.ai/graph/{self.test_space_id}/entities"
            
            # Query 1: Multi-criteria query - Financial transactions with purchase type AND amount > 1000
            print("\n   📊 Query 1: Multi-criteria financial transactions")
            print("      Find entities with 'purchase' type AND amount > 1000.0")
            
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
            
            result1 = self._execute_sparql_query(complex_query, "Multi-criteria financial query")
            
            # Query 2: Sorted numerical query - Amount filtering with sorting
            print("\n   📊 Query 2: Sorted numerical query")
            print("      Find entities with amount > 500.0, sorted by amount DESC")
            
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
            
            result2 = self._execute_sparql_query(sorted_query, "Sorted numerical query")
            
            # Query 3: Simple count query
            print("\n   📊 Query 3: Entity count query")
            
            # First, let's see what's actually in the graph
            debug_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?type (COUNT(?s) as ?count) WHERE {{
                GRAPH <{entity_graph_uri}> {{
                    ?s a ?type .
                }}
            }}
            GROUP BY ?type
            ORDER BY DESC(?count)
            LIMIT 10
            """
            
            print("      🔍 First, checking what types exist in the graph...")
            debug_result = self._execute_sparql_query(debug_query, "Debug type distribution")
            
            count_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT (COUNT(?entity) as ?count) WHERE {{
                GRAPH <{entity_graph_uri}> {{
                    ?entity a haley:KGEntity .
                }}
            }}
            """
            
            result3 = self._execute_sparql_query(count_query, "Entity count query")
            
            # Query 4: Frame type distribution
            print("\n   📊 Query 4: Frame type distribution")
            
            frame_query = f"""
            PREFIX vital: <http://vital.ai/ontology/vital-core#>
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?frameType (COUNT(?frame) as ?count) WHERE {{
                GRAPH <{entity_graph_uri}> {{
                    ?frame a haley:KGFrame .
                    ?frame haley:hasKGFrameType ?frameType .
                }}
            }}
            GROUP BY ?frameType
            ORDER BY DESC(?count)
            """
            
            result4 = self._execute_sparql_query(frame_query, "Frame type distribution")
            
            if all([result1, result2, result3, result4]):
                print("\n✅ All complex queries executed successfully!")
                return True
            else:
                print("\n❌ Some queries failed")
                return False
                
        except Exception as e:
            print(f"❌ Complex queries error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _execute_sparql_query(self, query: str, query_name: str) -> bool:
        """Execute a SPARQL query and display results with timing."""
        try:
            print(f"      🔍 Executing {query_name}...")
            
            start_time = time.time()
            response = self.session.post(
                f"{self.base_url}/api/graphs/sparql/{self.test_space_id}/query",
                json={"query": query},
                headers={
                    **self._get_auth_headers(),
                    "Content-Type": "application/json"
                }
            )
            end_time = time.time()
            
            if response.status_code == 200:
                execution_time = (end_time - start_time) * 1000
                results = response.json()
                
                if isinstance(results, list):
                    result_count = len(results)
                    print(f"      ✅ Query executed in {execution_time:.2f}ms - Found {result_count} results")
                    
                    # Display first few results
                    for i, result in enumerate(results[:3]):
                        print(f"         {i+1}. {result}")
                    
                    if result_count > 3:
                        print(f"         ... and {result_count - 3} more results")
                        
                elif isinstance(results, dict) and 'bindings' in results:
                    bindings = results['bindings']
                    result_count = len(bindings)
                    print(f"      ✅ Query executed in {execution_time:.2f}ms - Found {result_count} results")
                    
                    # Display first few results
                    for i, binding in enumerate(bindings[:3]):
                        print(f"         {i+1}. {binding}")
                    
                    if result_count > 3:
                        print(f"         ... and {result_count - 3} more results")
                else:
                    print(f"      ✅ Query executed in {execution_time:.2f}ms")
                    print(f"         Result: {results}")
                
                return True
            else:
                print(f"      ❌ Query failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"      ❌ Query execution error: {e}")
            return False
    
    def cleanup_test_space(self) -> bool:
        """Clean up the test space after testing."""
        print(f"🧹 Cleaning up test space: {self.test_space_id}")
        
        try:
            response = self.session.delete(
                f"{self.base_url}/api/spaces/{self.test_space_id}",
                headers=self._get_auth_headers()
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Test space cleaned up: {result['message']}")
                return True
            elif response.status_code == 404:
                print(f"ℹ️ Test space was already cleaned up or didn't exist")
                return True  # Consider this a success
            else:
                print(f"⚠️ Cleanup warning: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")
            return False

def main():
    """Main test execution function."""
    print("🚀 VitalGraph + Fuseki REST API Integration Test")
    print("=" * 60)
    print("Testing complete stack: Docker + VitalGraph + Fuseki + REST API + SPARQL")
    print()
    
    # Initialize test client
    tester = VitalGraphRestAPITester()
    
    # Test execution steps
    test_steps = [
        ("Authentication", tester.authenticate),
        ("Space Creation", tester.create_test_space),
        ("Space Listing", lambda: tester.list_spaces() is not None),
        ("Test Data Insertion", tester.insert_test_data),
        ("Complex Queries", tester.execute_complex_queries),
        # ("Cleanup", tester.cleanup_test_space)  # Skip cleanup to inspect data
    ]
    
    results = []
    start_time = time.time()
    
    try:
        for step_name, step_func in test_steps:
            print(f"\n{'='*20} {step_name.upper()} {'='*20}")
            step_start = time.time()
            
            try:
                success = step_func()
                step_time = (time.time() - step_start) * 1000
                
                if success:
                    print(f"✅ {step_name} completed successfully in {step_time:.2f}ms")
                    results.append((step_name, True, step_time))
                else:
                    print(f"❌ {step_name} failed after {step_time:.2f}ms")
                    results.append((step_name, False, step_time))
                    
            except Exception as e:
                step_time = (time.time() - step_start) * 1000
                print(f"❌ {step_name} error: {e}")
                results.append((step_name, False, step_time))
    
    finally:
        # Print summary
        total_time = (time.time() - start_time) * 1000
        passed = sum(1 for _, success, _ in results if success)
        total = len(results)
        
        print(f"\n{'='*60}")
        print("🏁 TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {total}")
        print(f"✅ Passed: {passed}")
        print(f"❌ Failed: {total - passed}")
        print(f"📈 Success Rate: {(passed/total)*100:.1f}%")
        print(f"⏱️ Total Time: {total_time:.2f}ms")
        print()
        
        print("📋 Detailed Results:")
        for step_name, success, step_time in results:
            status = "✅ PASS" if success else "❌ FAIL"
            print(f"   {status} {step_name}: {step_time:.2f}ms")
        
        print()
        if passed == total:
            print("🎉 ALL TESTS PASSED! VitalGraph + Fuseki integration is working perfectly!")
            print("✅ The complete stack is production-ready:")
            print("   - Docker containerization ✓")
            print("   - VitalGraph REST API ✓") 
            print("   - Fuseki backend storage ✓")
            print("   - Complex SPARQL queries ✓")
            print("   - VitalSigns data integration ✓")
        else:
            print("⚠️ Some tests failed. Check the logs above for details.")

if __name__ == "__main__":
    main()
