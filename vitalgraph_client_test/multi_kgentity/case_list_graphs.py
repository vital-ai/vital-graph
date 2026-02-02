#!/usr/bin/env python3
"""
List Graphs Test Case

Tests graph listing and verification after entity graph creation.
Verifies that the graph URI used for entity creation appears in the graphs list
and can be retrieved via get_graph_info.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ListGraphsTester:
    """
    Test case for listing and verifying graphs after entity creation.
    
    Validates:
    - Graph listing returns the expected graph URI
    - Graph info can be retrieved for the entity graph
    - Graph metadata is correct
    """
    
    def __init__(self, client):
        """
        Initialize the graphs list tester.
        
        Args:
            client: VitalGraphClient instance
        """
        self.client = client
    
    def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run graph listing and verification tests.
        
        Args:
            space_id: Space ID containing the graphs
            graph_id: Expected graph URI that should exist
            
        Returns:
            Dictionary with test results
        """
        logger.info("\n" + "=" * 80)
        logger.info("  List and Verify Graphs")
        logger.info("=" * 80)
        
        results = {
            "test_name": "List and Verify Graphs",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "details": []
        }
        
        # Test 1: List all graphs in the space
        logger.info("\n--- List All Graphs ---\n")
        list_result = self._test_list_graphs(space_id, graph_id)
        results["details"].append(list_result)
        results["tests_run"] += 1
        
        if list_result["passed"]:
            results["tests_passed"] += 1
            logger.info(f"✅ PASS: {list_result['test']}")
        else:
            results["tests_failed"] += 1
            error_msg = list_result.get('error', 'Unknown error')
            results["errors"].append(f"{list_result['test']}: {error_msg}")
            logger.error(f"❌ FAIL: {list_result['test']}")
            logger.error(f"   Error: {error_msg}")
        
        # Test 2: Get graph info for the entity graph
        logger.info("\n--- Get Graph Info ---\n")
        info_result = self._test_get_graph_info(space_id, graph_id)
        results["details"].append(info_result)
        results["tests_run"] += 1
        
        if info_result["passed"]:
            results["tests_passed"] += 1
            logger.info(f"✅ PASS: {info_result['test']}")
        else:
            results["tests_failed"] += 1
            error_msg = info_result.get('error', 'Unknown error')
            results["errors"].append(f"{info_result['test']}: {error_msg}")
            logger.error(f"❌ FAIL: {info_result['test']}")
            logger.error(f"   Error: {error_msg}")
        
        # Summary
        total_tests = results["tests_passed"] + results["tests_failed"]
        logger.info(f"\n{'='*80}")
        logger.info(f"Graph Tests Summary: {results['tests_passed']}/{total_tests} passed")
        logger.info(f"{'='*80}\n")
        
        return results
    
    def _test_list_graphs(self, space_id: str, expected_graph_id: str) -> Dict[str, Any]:
        """
        Test listing graphs and verify expected graph is present.
        
        Args:
            space_id: Space ID to list graphs from
            expected_graph_id: Graph URI that should be in the list
            
        Returns:
            Test result dictionary
        """
        try:
            logger.info(f"Listing graphs in space: {space_id}")
            
            # List graphs using the new Graphs API
            response = self.client.graphs.list_graphs(space_id)
            
            if not response.is_success:
                return {
                    "test": "List graphs in space",
                    "passed": False,
                    "error": f"Failed to list graphs: {response.error_message}"
                }
            
            logger.info(f"   Found {response.count} graph(s)")
            
            # Extract graph URIs
            graph_uris = []
            for graph in response.graphs:
                if hasattr(graph, 'graph_uri'):
                    graph_uris.append(graph.graph_uri)
                    logger.info(f"   - {graph.graph_uri}")
            
            # Verify expected graph is in the list
            if expected_graph_id in graph_uris:
                logger.info(f"\n   ✅ Expected graph found in list: {expected_graph_id}")
                return {
                    "test": "List graphs in space",
                    "passed": True,
                    "graph_count": response.count,
                    "graph_uris": graph_uris,
                    "expected_graph_found": True
                }
            else:
                return {
                    "test": "List graphs in space",
                    "passed": False,
                    "error": f"Expected graph not found in list: {expected_graph_id}",
                    "graph_count": response.count,
                    "graph_uris": graph_uris,
                    "expected_graph": expected_graph_id
                }
                
        except Exception as e:
            logger.error(f"   ❌ Exception listing graphs: {e}")
            return {
                "test": "List graphs in space",
                "passed": False,
                "error": f"Exception: {str(e)}"
            }
    
    def _test_get_graph_info(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Test getting graph info for the entity graph.
        
        Args:
            space_id: Space ID containing the graph
            graph_id: Graph URI to retrieve info for
            
        Returns:
            Test result dictionary
        """
        try:
            logger.info(f"Getting graph info for: {graph_id}")
            
            # Get graph info using the new Graphs API
            response = self.client.graphs.get_graph_info(space_id, graph_id)
            
            if not response.is_success:
                return {
                    "test": "Get graph info",
                    "passed": False,
                    "error": f"Failed to get graph info: {response.error_message}"
                }
            
            if not response.graph:
                return {
                    "test": "Get graph info",
                    "passed": False,
                    "error": f"Graph info returned None for graph: {graph_id}"
                }
            
            graph_info = response.graph
            logger.info(f"   ✅ Graph info retrieved successfully")
            
            # Display graph metadata
            if hasattr(graph_info, 'graph_uri'):
                logger.info(f"   Graph URI: {graph_info.graph_uri}")
            if hasattr(graph_info, 'triple_count'):
                logger.info(f"   Triple count: {graph_info.triple_count}")
            
            return {
                "test": "Get graph info",
                "passed": True,
                "graph_uri": graph_id,
                "graph_info": graph_info
            }
                
        except Exception as e:
            logger.error(f"   ❌ Exception getting graph info: {e}")
            return {
                "test": "Get graph info",
                "passed": False,
                "error": f"Exception: {str(e)}"
            }
