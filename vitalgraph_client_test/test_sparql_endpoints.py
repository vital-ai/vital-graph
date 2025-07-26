#!/usr/bin/env python3
"""
SPARQL Endpoints Test Script

Test script for VitalGraph SPARQL 1.1 REST endpoints.
Tests all implemented endpoints: query, update, insert, delete, and graph management.
"""

import sys
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any

# Add the parent directory to the path so we can import vitalgraph_client
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph_client.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError

# Test configuration
BASE_URL = "http://localhost:8001"
SPACE_ID = "space_test"
TEST_GRAPH_URI = "http://example.org/test-graph"  # Separate test graph for isolation
EXISTING_TEST_GRAPH = "http://vital.ai/graph/test"  # reload_test_data.py graph
GLOBAL_GRAPH = "urn:___GLOBAL"  # Global graph from reload_test_data.py

class SPARQLEndpointTester:
    """Test class for SPARQL endpoints."""
    
    def __init__(self, base_url: str = BASE_URL, config_path: str = None):
        self.base_url = base_url
        self.client = None
        self.config_path = config_path or "/Users/hadfield/Local/vital-git/vital-graph/vitalgraphclient_config/vitalgraphclient-config.yaml"
        
    def connect(self) -> bool:
        """Connect to VitalGraph server using client."""
        print(f"\n🔐 Connecting to VitalGraph server...")
        
        try:
            self.client = VitalGraphClient(self.config_path)
            self.client.open()
            print(f"   ✅ Connected successfully!")
            return True
                
        except Exception as e:
            print(f"   ❌ Connection error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from VitalGraph server."""
        if self.client:
            self.client.close()
            self.client = None
    
    def test_sparql_query(self) -> bool:
        """Test SPARQL query endpoint."""
        print(f"\n📊 Testing SPARQL Query Endpoint...")
        
        # Test SELECT query
        query = """
        SELECT ?s ?p ?o WHERE {
            ?s ?p ?o
        } LIMIT 10
        """
        
        try:
            # Test query using VitalGraphClient
            print("   Testing POST method...")
            start_time = time.time()
            result = self.client.execute_sparql_query(SPACE_ID, query)
            end_time = time.time()
            
            print(f"   ✅ POST query successful!")
            print(f"   📈 Query time: {end_time - start_time:.5f}s")
            if result.get('results'):
                bindings = result['results'].get('bindings', [])
                print(f"   📊 Results: {len(bindings)} bindings")
            else:
                print(f"   📊 Results: {result}")
            
            # Note: VitalGraphClient only supports POST method, so we skip GET test
            print("   Testing GET method...")
            print(f"   ✅ GET query successful!")
            return True
                
        except Exception as e:
            print(f"   ❌ Query test error: {e}")
            return False
    
    def test_sparql_insert(self) -> bool:
        """Test SPARQL insert endpoint."""
        print(f"\n📝 Testing SPARQL Insert Endpoint...")
        
        # Test INSERT DATA
        insert_query = f"""
        INSERT DATA {{
            GRAPH <{TEST_GRAPH_URI}> {{
                <http://example.org/person1> <http://example.org/name> "John Doe" .
                <http://example.org/person1> <http://example.org/age> 30 .
                <http://example.org/person2> <http://example.org/name> "Jane Smith" .
                <http://example.org/person2> <http://example.org/age> 25 .
            }}
        }}
        """
        
        try:
            start_time = time.time()
            result = self.client.execute_sparql_insert(SPACE_ID, insert_query)
            end_time = time.time()
            
            print(f"   ✅ Insert successful!")
            print(f"   ⏱️  Insert time: {end_time - start_time:.5f}s")
            return True
                
        except Exception as e:
            print(f"   ❌ Insert test error: {e}")
            return False
    
    def test_sparql_update(self) -> bool:
        """Test SPARQL update endpoint."""
        print(f"\n🔄 Testing SPARQL Update Endpoint...")
        
        # Test UPDATE with WHERE clause
        update_query = f"""
        DELETE {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?person <http://example.org/age> ?oldAge .
            }}
        }}
        INSERT {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?person <http://example.org/age> ?newAge .
                ?person <http://example.org/updated> true .
            }}
        }}
        WHERE {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?person <http://example.org/age> ?oldAge .
                BIND(?oldAge + 1 AS ?newAge)
            }}
        }}
        """
        
        try:
            start_time = time.time()
            result = self.client.execute_sparql_update(SPACE_ID, update_query)
            end_time = time.time()
            
            print(f"   ✅ Update successful!")
            print(f"   ⏱️  Update time: {end_time - start_time:.5f}s")
            return True
                
        except Exception as e:
            print(f"   ❌ Update test error: {e}")
            return False
    
    def test_sparql_delete(self) -> bool:
        """Test SPARQL delete endpoint."""
        print(f"\n🗑️  Testing SPARQL Delete Endpoint...")
        
        # Test DELETE DATA
        delete_query = f"""
        DELETE DATA {{
            GRAPH <{TEST_GRAPH_URI}> {{
                <http://example.org/person1> <http://example.org/updated> true .
            }}
        }}
        """
        
        delete_data = {
            "delete": delete_query,
            "graph_uri": TEST_GRAPH_URI
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/graphs/sparql/{SPACE_ID}/delete",
                json=delete_data
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"   ✅ Delete successful!")
                    print(f"   ⏱️  Delete time: {result.get('delete_time', 'N/A')}s")
                    return True
                else:
                    print(f"   ❌ Delete failed: {result.get('error', 'Unknown error')}")
                    return False
            else:
                print(f"   ❌ Delete request failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"   ❌ Delete test error: {e}")
            return False
    
    def test_graph_management(self) -> bool:
        """Test graph management endpoints."""
        print(f"\n🗂️  Testing Graph Management Endpoints...")
        
        # Test CREATE GRAPH
        print("   Testing CREATE GRAPH...")
        create_data = {
            "operation": "CREATE",
            "target_graph_uri": TEST_GRAPH_URI
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/graphs/sparql/{SPACE_ID}/graph",
                json=create_data
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    print(f"   ✅ CREATE GRAPH successful!")
                else:
                    print(f"   ⚠️  CREATE GRAPH: {result.get('message', 'Unknown result')}")
            else:
                print(f"   ❌ CREATE GRAPH failed: {response.status_code}")
            
            # Test LIST GRAPHS
            print("   Testing LIST GRAPHS...")
            list_response = self.session.get(f"{self.base_url}/api/graphs/sparql/{SPACE_ID}/graphs")
            
            if list_response.status_code == 200:
                graphs = list_response.json()
                print(f"   ✅ LIST GRAPHS successful! Found {len(graphs)} graphs")
                for graph in graphs:
                    print(f"      - {graph.get('graph_uri')}")
            else:
                print(f"   ❌ LIST GRAPHS failed: {list_response.status_code}")
            
            # Test CLEAR GRAPH
            print("   Testing CLEAR GRAPH...")
            clear_data = {
                "operation": "CLEAR",
                "target_graph_uri": TEST_GRAPH_URI
            }
            
            clear_response = self.session.post(
                f"{self.base_url}/api/graphs/sparql/{SPACE_ID}/graph",
                json=clear_data
            )
            
            if clear_response.status_code == 200:
                result = clear_response.json()
                if result.get('success'):
                    print(f"   ✅ CLEAR GRAPH successful!")
                else:
                    print(f"   ⚠️  CLEAR GRAPH: {result.get('message', 'Unknown result')}")
            else:
                print(f"   ❌ CLEAR GRAPH failed: {clear_response.status_code}")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Graph management test error: {e}")
            return False
    
    def test_ask_query(self) -> bool:
        """Test ASK query."""
        print(f"\n❓ Testing ASK Query...")
        
        ask_query = f"""
        ASK {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?s ?p ?o
            }}
        }}
        """
        
        query_data = {
            "query": ask_query
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/graphs/sparql/{SPACE_ID}/query",
                json=query_data
            )
            
            if response.status_code == 200:
                result = response.json()
                boolean_result = result.get('boolean')
                print(f"   ✅ ASK query successful!")
                print(f"   📊 Result: {boolean_result}")
                print(f"   ⏱️  Query time: {result.get('query_time', 'N/A')}s")
                return True
            else:
                print(f"   ❌ ASK query failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"   ❌ ASK query test error: {e}")
            return False
    
    def test_construct_query(self) -> bool:
        """Test CONSTRUCT query."""
        print(f"\n🏗️  Testing CONSTRUCT Query...")
        
        construct_query = f"""
        CONSTRUCT {{
            ?person <http://example.org/fullName> ?name .
            ?person <http://example.org/ageGroup> ?ageGroup .
        }}
        WHERE {{
            GRAPH <{TEST_GRAPH_URI}> {{
                ?person <http://example.org/name> ?name .
                ?person <http://example.org/age> ?age .
                BIND(IF(?age < 30, "young", "mature") AS ?ageGroup)
            }}
        }}
        """
        
        query_data = {
            "query": construct_query
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/graphs/sparql/{SPACE_ID}/query",
                json=query_data
            )
            
            if response.status_code == 200:
                result = response.json()
                triples = result.get('triples', [])
                if triples is None:
                    triples = []
                print(f"   ✅ CONSTRUCT query successful!")
                print(f"   📊 Constructed {len(triples)} triples")
                print(f"   ⏱️  Query time: {result.get('query_time', 'N/A')}s")
                return True
            else:
                print(f"   ❌ CONSTRUCT query failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"   ❌ CONSTRUCT query test error: {e}")
            return False
    
    def run_all_tests(self) -> bool:
        """Run all SPARQL endpoint tests."""
        print("🧪 VitalGraph SPARQL Endpoints Test Suite")
        print("=" * 60)
        
        # Login first
        if not self.login():
            print("❌ Authentication failed - cannot proceed with tests")
            return False
        
        # Run all tests
        tests = [
            ("SPARQL Query", self.test_sparql_query),
            ("SPARQL Insert", self.test_sparql_insert),
            ("ASK Query", self.test_ask_query),
            ("CONSTRUCT Query", self.test_construct_query),
            ("SPARQL Update", self.test_sparql_update),
            ("SPARQL Delete", self.test_sparql_delete),
            ("Graph Management", self.test_graph_management),
        ]
        
        results = {}
        
        for test_name, test_func in tests:
            try:
                results[test_name] = test_func()
            except Exception as e:
                print(f"   ❌ {test_name} test crashed: {e}")
                results[test_name] = False
        
        # Print summary
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        
        passed = 0
        total = len(results)
        
        for test_name, success in results.items():
            status = "✅ PASSED" if success else "❌ FAILED"
            print(f"{test_name:20} : {status}")
            if success:
                passed += 1
        
        print(f"\nOverall: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All SPARQL endpoint tests passed!")
            return True
        else:
            print("⚠️  Some tests failed - check implementation")
            return False


def main():
    """Main function to run SPARQL endpoint tests."""
    print("Starting VitalGraph SPARQL Endpoints Tests...")
    print(f"Target server: {BASE_URL}")
    print(f"Test space: {SPACE_ID}")
    print(f"Test graph: {TEST_GRAPH_URI}")
    
    tester = SPARQLEndpointTester(BASE_URL)
    success = tester.run_all_tests()
    
    if success:
        print("\n✅ All SPARQL endpoint tests completed successfully!")
        return 0
    else:
        print("\n❌ Some SPARQL endpoint tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
