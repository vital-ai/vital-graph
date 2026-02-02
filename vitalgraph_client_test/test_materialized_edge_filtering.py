#!/usr/bin/env python3
"""
Test Materialized Edge Filtering

This script tests that materialized edge predicates (vg-direct:hasEntityFrame, 
vg-direct:hasFrame, vg-direct:hasSlot) are properly filtered out when retrieving
entity data from Fuseki, preventing VitalSigns conversion errors.

It queries the space_multi_org_crud_test dataset to verify:
1. Materialized triples exist in Fuseki (for query optimization)
2. Materialized triples are filtered out when retrieving entity data
3. Entity retrieval works without VitalSigns errors
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class MaterializedEdgeFilteringTester:
    """Test that materialized edge predicates are properly filtered."""
    
    def __init__(self):
        """Initialize the tester."""
        # Fuseki configuration (localhost)
        self.fuseki_url = "http://localhost:3030"
        
        # Test space configuration (from test_multiple_organizations_crud.py)
        self.space_id = "space_multi_org_crud_test"
        self.dataset_name = f"vitalgraph_space_{self.space_id}"
        self.graph_id = "urn:multi_org_crud_graph"
        
        logger.info(f"✅ Initialized Materialized Edge Filtering Tester")
        logger.info(f"   Fuseki URL: {self.fuseki_url}")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}\n")
    
    def query_fuseki(self, sparql_query: str, query_description: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Execute a SPARQL query against the test dataset in Fuseki.
        
        Args:
            sparql_query: SPARQL query to execute
            query_description: Description of what the query does
            timeout: Query timeout in seconds (default 30)
            
        Returns:
            Query results as dictionary, or None if failed
        """
        query_url = f"{self.fuseki_url}/{self.dataset_name}/query"
        
        logger.info(f"📊 {query_description}")
        
        headers = {
            'Accept': 'application/sparql-results+json',
        }
        
        params = {
            'query': sparql_query
        }
        
        try:
            response = requests.get(
                query_url,
                params=params,
                headers=headers,
                timeout=timeout
            )
            
            if response.status_code == 200:
                results = response.json()
                return results
            else:
                logger.error(f"   ❌ Query failed")
                logger.error(f"   Status code: {response.status_code}")
                logger.error(f"   Response: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"   ❌ Error executing query: {e}")
            return None
    
    def count_materialized_triples(self) -> bool:
        """Count materialized edge triples (vg-direct:*) in the graph."""
        query = f"""
        PREFIX vg-direct: <http://vital.ai/vitalgraph/direct#>
        
        SELECT (COUNT(*) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                {{
                    ?s vg-direct:hasEntityFrame ?o .
                }} UNION {{
                    ?s vg-direct:hasFrame ?o .
                }} UNION {{
                    ?s vg-direct:hasSlot ?o .
                }}
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting materialized edge triples (vg-direct:*)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = int(bindings[0]['count']['value'])
                logger.info(f"   ✅ Found {count} materialized edge triple(s)")
                logger.info(f"   These should exist for query optimization\n")
                return count > 0
        
        logger.error(f"   ❌ No materialized triples found")
        logger.error(f"   Materialization may not be working\n")
        return False
    
    def list_materialized_predicates(self) -> bool:
        """List all materialized predicates to verify they exist."""
        query = f"""
        SELECT DISTINCT ?p
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?s ?p ?o .
                FILTER(CONTAINS(STR(?p), "vitalgraph/direct"))
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Listing materialized predicates")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} materialized predicate type(s):")
                for binding in bindings:
                    predicate = binding.get('p', {}).get('value', 'N/A')
                    logger.info(f"      • {predicate}")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No materialized predicates found\n")
        return False
    
    def test_entity_query_without_filter(self) -> bool:
        """Test entity query WITHOUT filtering - should return materialized triples."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?p ?o
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity a haley:KGEntity .
                ?entity ?p ?o .
            }}
        }}
        LIMIT 100
        """
        
        results = self.query_fuseki(query, "Testing entity query WITHOUT filter (should include materialized triples)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            
            # Count how many have materialized predicates
            materialized_count = sum(1 for b in bindings 
                                    if 'vitalgraph/direct' in b.get('p', {}).get('value', ''))
            
            logger.info(f"   ✅ Query returned {len(bindings)} triple(s)")
            logger.info(f"   ✅ {materialized_count} triple(s) have materialized predicates")
            logger.info(f"   This confirms materialized triples exist in Fuseki\n")
            return materialized_count > 0
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def test_entity_query_with_filter(self) -> bool:
        """Test entity query WITH filtering - should exclude materialized triples."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?p ?o
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity a haley:KGEntity .
                ?entity ?p ?o .
                FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                       ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                       ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
            }}
        }}
        LIMIT 100
        """
        
        results = self.query_fuseki(query, "Testing entity query WITH filter (should exclude materialized triples)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            
            # Count how many have materialized predicates (should be 0)
            materialized_count = sum(1 for b in bindings 
                                    if 'vitalgraph/direct' in b.get('p', {}).get('value', ''))
            
            logger.info(f"   ✅ Query returned {len(bindings)} triple(s)")
            
            if materialized_count == 0:
                logger.info(f"   ✅ FILTER successfully excluded all materialized predicates")
                logger.info(f"   This confirms the FILTER syntax is correct\n")
                return True
            else:
                logger.error(f"   ❌ FILTER failed - {materialized_count} materialized triple(s) still present")
                logger.error(f"   The FILTER syntax may be incorrect\n")
                return False
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def test_construct_query_with_filter(self) -> bool:
        """Test CONSTRUCT query WITH filtering - mimics get_object behavior."""
        # Get first entity URI
        entity_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity a haley:KGEntity .
            }}
        }}
        LIMIT 1
        """
        
        entity_results = self.query_fuseki(entity_query, "Getting first entity URI")
        
        if not entity_results or 'results' not in entity_results:
            logger.error(f"   ❌ Could not get entity URI\n")
            return False
        
        bindings = entity_results['results']['bindings']
        if not bindings:
            logger.error(f"   ❌ No entities found\n")
            return False
        
        entity_uri = bindings[0]['entity']['value']
        logger.info(f"   Testing with entity: {entity_uri}\n")
        
        # Now test CONSTRUCT with filter
        construct_query = f"""
        CONSTRUCT {{
            <{entity_uri}> ?p ?o .
        }}
        WHERE {{
            GRAPH <{self.graph_id}> {{
                <{entity_uri}> ?p ?o .
                FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                       ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                       ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
            }}
        }}
        """
        
        # For CONSTRUCT queries, we need to use a different endpoint
        query_url = f"{self.fuseki_url}/{self.dataset_name}/query"
        
        headers = {
            'Accept': 'application/n-triples',
        }
        
        params = {
            'query': construct_query
        }
        
        try:
            response = requests.get(
                query_url,
                params=params,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                triples_text = response.text
                lines = [line for line in triples_text.split('\n') if line.strip()]
                
                # Count materialized predicates in result
                materialized_count = sum(1 for line in lines if 'vitalgraph/direct' in line)
                
                logger.info(f"📊 Testing CONSTRUCT query WITH filter")
                logger.info(f"   ✅ CONSTRUCT returned {len(lines)} triple(s)")
                
                if materialized_count == 0:
                    logger.info(f"   ✅ FILTER successfully excluded all materialized predicates")
                    logger.info(f"   This confirms get_object() filtering works\n")
                    return True
                else:
                    logger.error(f"   ❌ FILTER failed - {materialized_count} materialized triple(s) still present")
                    logger.error(f"   get_object() may return materialized triples\n")
                    return False
            else:
                logger.error(f"   ❌ CONSTRUCT query failed")
                logger.error(f"   Status code: {response.status_code}\n")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"   ❌ Error executing CONSTRUCT query: {e}\n")
            return False
    
    def test_entity_graph_query_with_filter(self) -> bool:
        """Test entity graph query WITH filtering - mimics get_entity_graph behavior."""
        # Get first entity URI
        entity_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity a haley:KGEntity .
            }}
        }}
        LIMIT 1
        """
        
        entity_results = self.query_fuseki(entity_query, "Getting first entity URI for graph test")
        
        if not entity_results or 'results' not in entity_results:
            logger.error(f"   ❌ Could not get entity URI\n")
            return False
        
        bindings = entity_results['results']['bindings']
        if not bindings:
            logger.error(f"   ❌ No entities found\n")
            return False
        
        entity_uri = bindings[0]['entity']['value']
        logger.info(f"   Testing with entity: {entity_uri}\n")
        
        # Test entity graph query with filter (mimics get_entity_graph)
        graph_query = f"""
        SELECT ?s ?p ?o WHERE {{
            GRAPH <{self.graph_id}> {{
                {{
                    # Get the entity itself
                    <{entity_uri}> ?p ?o .
                    BIND(<{entity_uri}> AS ?s)
                    FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                }}
                UNION
                {{
                    # Get objects with same entity-level grouping URI (hasKGGraphURI)
                    ?s <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{entity_uri}> .
                    ?s ?p ?o .
                    FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                           ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                }}
            }}
        }}
        """
        
        results = self.query_fuseki(graph_query, "Testing entity graph query WITH filter")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            
            # Count materialized predicates
            materialized_count = sum(1 for b in bindings 
                                    if 'vitalgraph/direct' in b.get('p', {}).get('value', ''))
            
            logger.info(f"   ✅ Query returned {len(bindings)} triple(s)")
            
            if materialized_count == 0:
                logger.info(f"   ✅ FILTER successfully excluded all materialized predicates")
                logger.info(f"   This confirms get_entity_graph() filtering works\n")
                return True
            else:
                logger.error(f"   ❌ FILTER failed - {materialized_count} materialized triple(s) still present")
                logger.error(f"   get_entity_graph() may return materialized triples\n")
                return False
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def run_tests(self) -> bool:
        """
        Run all filtering tests.
        
        Returns:
            True if all tests passed, False otherwise
        """
        logger.info("")
        logger.info("🚀 Starting Materialized Edge Filtering Tests")
        logger.info(f"   Testing space: {self.space_id}")
        logger.info(f"   Fuseki dataset: {self.dataset_name}")
        logger.info("")
        
        logger.info("=" * 80)
        logger.info("📊 Step 1: Verify Materialized Triples Exist")
        logger.info("=" * 80)
        logger.info("")
        
        all_passed = True
        
        # Test 1: Count materialized triples
        if not self.count_materialized_triples():
            logger.error("⚠️  Materialized triples not found - materialization may not be working")
            all_passed = False
        
        # Test 2: List materialized predicates
        if not self.list_materialized_predicates():
            all_passed = False
        
        logger.info("=" * 80)
        logger.info("📊 Step 2: Test FILTER Syntax")
        logger.info("=" * 80)
        logger.info("")
        
        # Test 3: Query without filter (should include materialized)
        if not self.test_entity_query_without_filter():
            all_passed = False
        
        # Test 4: Query with filter (should exclude materialized)
        if not self.test_entity_query_with_filter():
            all_passed = False
        
        logger.info("=" * 80)
        logger.info("📊 Step 3: Test Actual Query Patterns")
        logger.info("=" * 80)
        logger.info("")
        
        # Test 5: CONSTRUCT query with filter (mimics get_object)
        if not self.test_construct_query_with_filter():
            all_passed = False
        
        # Test 6: Entity graph query with filter (mimics get_entity_graph)
        if not self.test_entity_graph_query_with_filter():
            all_passed = False
        
        # Summary
        logger.info("=" * 80)
        if all_passed:
            logger.info("🎉 All Materialized Edge Filtering Tests Passed!")
            logger.info("=" * 80)
            logger.info("")
            logger.info("Summary:")
            logger.info("  ✅ Materialized triples exist in Fuseki")
            logger.info("  ✅ FILTER syntax correctly excludes materialized predicates")
            logger.info("  ✅ get_object() filtering works")
            logger.info("  ✅ get_entity_graph() filtering works")
            logger.info("")
            logger.info("✅ Entity retrieval should work without VitalSigns errors!")
        else:
            logger.info("❌ Some Filtering Tests Failed")
            logger.info("=" * 80)
            logger.info("")
            logger.info("⚠️  Materialized edge filtering may not be working correctly")
            logger.info("⚠️  This could cause VitalSigns conversion errors")
        
        return all_passed


def main():
    """Main entry point for the test script."""
    try:
        tester = MaterializedEdgeFilteringTester()
        success = tester.run_tests()
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
