#!/usr/bin/env python3
"""
Graphs Endpoint Test Script for Fuseki+PostgreSQL Backend

Tests graph management operations (create, list, get, drop, clear) using the
Fuseki+PostgreSQL hybrid backend without running the full REST service.

This script validates:
- Graph creation with dual-write to both Fuseki datasets and PostgreSQL graph tables
- Graph listing and information retrieval operations
- Graph metadata management and updates
- Graph deletion with cleanup of both storage layers and RDF data
- Dual-write consistency validation between Fuseki and PostgreSQL
- Error handling and edge cases

Test Coverage:
- Graph lifecycle management (CRUD operations)
- Graph metadata operations via PostgreSQL graph tables
- Fuseki dataset graph management
- Dual-write consistency validation
- Graph access control and filtering
- Performance comparison between storage layers
"""

import sys
import os
import json
import logging
import uuid
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import the base tester class
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester, run_hybrid_test_suite

# VitalGraph imports
from vitalgraph.endpoint.sparql_graph_endpoint import SPARQLGraphEndpoint
from vitalgraph.model.sparql_model import SPARQLGraphRequest, SPARQLGraphResponse, GraphInfo

# Import modular test cases
from test_script_kg_impl.graphs.case_graph_create import GraphCreateTester
from test_script_kg_impl.graphs.case_graph_list import GraphListTester
from test_script_kg_impl.graphs.case_graph_get import GraphGetTester
from test_script_kg_impl.graphs.case_graph_delete import GraphDeleteTester
from test_script_kg_impl.graphs.case_graph_dual_write_consistency import GraphDualWriteConsistencyTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GraphsEndpointFusekiPostgreSQLTester(FusekiPostgreSQLEndpointTester):
    """Test Graphs endpoint operations with Fuseki+PostgreSQL hybrid backend."""
    
    def __init__(self):
        super().__init__()
        self.graphs_endpoint = None
        self.test_graphs = []
        self.created_graph_uris = []
        self.test_space_id = None
    
    async def setup_hybrid_backend(self) -> bool:
        """Setup hybrid backend and graphs endpoint."""
        success = await super().setup_hybrid_backend()
        if not success:
            return False
        
        try:
            # Create mock auth dependency for testing
            def mock_auth_dependency():
                return {"username": "test_user", "user_id": "test_user_123"}
            
            # Initialize graphs endpoint with space manager (like KG endpoint tests)
            self.graphs_endpoint = SPARQLGraphEndpoint(
                space_manager=self.space_manager,
                auth_dependency=mock_auth_dependency
            )
            
            logger.info("✅ Graphs endpoint initialized with hybrid backend")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup graphs endpoint: {e}")
            return False
    
    async def test_graph_creation(self):
        """Test graph creation using modular test case."""
        test_name = "Graph Creation with Dual-Write"
        
        try:
            # First create a test space for graphs
            await self._create_test_space()
            
            # Use modular graph creation tester
            create_tester = GraphCreateTester(self.graphs_endpoint)
            create_results = await create_tester.test_graph_creation(self.test_space_id)
            
            # Track created graphs for cleanup
            if 'created_graphs' in create_results:
                self.created_graph_uris.extend(create_results['created_graphs'])
            
            if create_results['success']:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Graph creation successful using modular test case - {create_results['passed_tests']}/{create_results['total_tests']} tests passed",
                    create_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Graph creation failed in modular test case - Failed tests: {', '.join(create_results['failed_tests'])}",
                    create_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during graph creation test: {e}")
    
    async def test_graph_listing(self):
        """Test graph listing using modular test case."""
        test_name = "Graph Listing"
        
        try:
            if not self.test_space_id:
                await self._create_test_space()
            
            # Use modular graph listing tester
            list_tester = GraphListTester(self.graphs_endpoint)
            list_results = await list_tester.test_graph_listing(self.test_space_id, self.created_graph_uris)
            
            if list_results['success']:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Graph listing successful using modular test case - {list_results['passed_tests']}/{list_results['total_tests']} tests passed",
                    list_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Graph listing failed in modular test case - Failed tests: {', '.join(list_results['failed_tests'])}",
                    list_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during graph listing test: {e}")
    
    async def test_graph_info_retrieval(self):
        """Test graph information retrieval using modular test case."""
        test_name = "Graph Info Retrieval"
        
        try:
            if not self.test_space_id:
                await self._create_test_space()
            
            # Use modular graph get tester
            get_tester = GraphGetTester(self.graphs_endpoint)
            get_results = await get_tester.test_graph_retrieval(self.test_space_id, self.created_graph_uris)
            
            if get_results['success']:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Graph retrieval successful using modular test case - {get_results['passed_tests']}/{get_results['total_tests']} tests passed",
                    get_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Graph retrieval failed in modular test case - Failed tests: {', '.join(get_results['failed_tests'])}",
                    get_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during graph info retrieval test: {e}")
    
    async def test_graph_clear(self):
        """Test graph clear operations."""
        test_name = "Graph Clear"
        
        try:
            if not self.test_space_id:
                await self._create_test_space()
            
            # Create a test graph using endpoint
            test_graph_uri = f"http://vital.ai/graph/clear_test_{uuid.uuid4().hex[:8]}"
            
            # Create graph using endpoint
            create_request = SPARQLGraphRequest(
                operation="CREATE",
                target_graph_uri=test_graph_uri
            )
            create_response = await self.graphs_endpoint._execute_graph_operation(
                self.test_space_id, 
                create_request,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if create_response.success:
                self.created_graph_uris.append(test_graph_uri)
                
                # Clear the graph using endpoint
                clear_request = SPARQLGraphRequest(
                    operation="CLEAR",
                    target_graph_uri=test_graph_uri
                )
                clear_response = await self.graphs_endpoint._execute_graph_operation(
                    self.test_space_id, 
                    clear_request,
                    {"username": "test_user", "user_id": "test_user_123"}
                )
                
                if clear_response.success:
                    # Validate graph still exists but is empty using endpoint
                    graph_info = await self.graphs_endpoint._get_graph_info(
                        self.test_space_id, 
                        test_graph_uri, 
                        {"username": "test_user", "user_id": "test_user_123"}
                    )
                    
                    if graph_info and graph_info.triple_count == 0:
                        self.log_test_result(
                            test_name, 
                            True, 
                            f"Graph cleared successfully (exists but empty)",
                            {"graph_uri": test_graph_uri, "triple_count": graph_info.triple_count}
                        )
                    else:
                        self.log_test_result(
                            test_name, 
                            False, 
                            f"Graph clear validation failed",
                            {"graph_uri": test_graph_uri, "graph_info": graph_info.model_dump() if graph_info else None}
                        )
                else:
                    self.log_test_result(
                        test_name, 
                        False, 
                        f"Graph clear operation failed: {clear_response.message}",
                        {"response": clear_response.model_dump()}
                    )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Failed to create test graph for clear operation: {create_response.message}"
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during graph clear test: {e}")
    
    async def test_graph_deletion(self):
        """Test graph deletion using modular test case."""
        test_name = "Graph Deletion with Cleanup"
        
        try:
            if not self.test_space_id:
                await self._create_test_space()
            
            # Use modular graph delete tester
            delete_tester = GraphDeleteTester(self.graphs_endpoint)
            delete_results = await delete_tester.test_graph_deletion(self.test_space_id, self.created_graph_uris)
            
            if delete_results['success']:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Graph deletion successful using modular test case - {delete_results['passed_tests']}/{delete_results['total_tests']} tests passed",
                    delete_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Graph deletion failed in modular test case - Failed tests: {', '.join(delete_results['failed_tests'])}",
                    delete_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during graph deletion test: {e}")
    
    async def test_dual_write_consistency(self):
        """Test dual-write consistency using modular test case."""
        test_name = "Dual-Write Consistency Validation"
        
        try:
            if not self.test_space_id:
                await self._create_test_space()
            
            # Use modular dual-write consistency tester
            consistency_tester = GraphDualWriteConsistencyTester(self.graphs_endpoint)
            consistency_results = await consistency_tester.test_dual_write_consistency(self.test_space_id)
            
            if consistency_results['success']:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Dual-write consistency successful using modular test case - {consistency_results['passed_tests']}/{consistency_results['total_tests']} tests passed",
                    consistency_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Dual-write consistency failed in modular test case - Failed tests: {', '.join(consistency_results['failed_tests'])}",
                    consistency_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during dual-write consistency test: {e}")
    
    async def _create_test_space(self):
        """Create a test space for graph operations."""
        if self.test_space_id:
            return
        
        self.test_space_id = f"test_graphs_space_{uuid.uuid4().hex[:8]}"
        
        # Create space using space manager
        from vitalgraph.model.spaces_model import Space
        
        test_space = Space(
            space=self.test_space_id,
            space_name=f"Test Graphs Space {self.test_space_id}",
            space_description="Test space for graph operations testing",
            tenant="test_tenant"
        )
        
        # Use create_space_with_tables to ensure proper setup
        success = await self.space_manager.create_space_with_tables(
            space_id=self.test_space_id,
            space_name=test_space.space_name,
            space_description=test_space.space_description
        )
        if not success:
            raise Exception("Failed to create test space for graph operations")
        
        logger.info(f"✅ Created test space: {self.test_space_id}")
    
    async def _validate_graph_dual_storage(self, space_id: str, graph_uri: str) -> Dict[str, Any]:
        """Validate that graph exists in both Fuseki and PostgreSQL storage."""
        try:
            # Check Fuseki graph existence
            fuseki_exists = False
            try:
                # Check if graph exists in Fuseki dataset
                space_record = self.space_manager.get_space(space_id)
                if space_record:
                    space_impl = space_record.space_impl
                    db_space_impl = space_impl.get_db_space_impl()
                    if db_space_impl:
                        # Try to get graph info - if it exists, this won't throw
                        graph_data = await db_space_impl.graphs.get_graph(space_id, graph_uri)
                        fuseki_exists = graph_data is not None
            except Exception as e:
                logger.warning(f"Error checking Fuseki graph: {e}")
            
            # Check PostgreSQL graph table
            postgresql_exists = False
            try:
                # Check if graph metadata exists in PostgreSQL graph table
                pg_query = "SELECT COUNT(*) as count FROM graph WHERE space_id = $1 AND graph_uri = $2"
                pg_results = await self.hybrid_backend.postgresql_impl.execute_query(pg_query, [space_id, graph_uri])
                postgresql_exists = pg_results and len(pg_results) > 0 and pg_results[0].get('count', 0) > 0
            except Exception as e:
                logger.warning(f"Error checking PostgreSQL graph table: {e}")
            
            return {
                "space_id": space_id,
                "graph_uri": graph_uri,
                "fuseki_exists": fuseki_exists,
                "postgresql_exists": postgresql_exists,
                "consistent": fuseki_exists and postgresql_exists,  # Both must exist for consistency
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Exception validating graph dual storage: {e}")
            return {
                "space_id": space_id,
                "graph_uri": graph_uri,
                "fuseki_exists": False,
                "postgresql_exists": False,
                "consistent": False,
                "error": str(e)
            }
    
    async def cleanup_resources(self):
        """Clean up test graphs and space."""
        logger.info("🧹 Starting cleanup of test resources...")
        
        try:
            # Clean up created graphs
            if self.test_space_id and self.created_graph_uris:
                for graph_uri in self.created_graph_uris:
                    try:
                        delete_request = SPARQLGraphRequest(
                            operation="DROP",
                            target_graph_uri=graph_uri,
                            silent=True
                        )
                        
                        await self.graphs_endpoint._execute_graph_operation(
                            self.test_space_id, delete_request, {"username": "test_user", "user_id": "test_user_123"}
                        )
                        logger.info(f"🗑️ Cleaned up graph: {graph_uri}")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to cleanup graph {graph_uri}: {e}")
            
            # Clean up test space
            if self.test_space_id:
                try:
                    await self.space_manager.delete_space_with_tables(self.test_space_id)
                    logger.info(f"🗑️ Cleaned up test space: {self.test_space_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to cleanup test space {self.test_space_id}: {e}")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
        
        # Call parent cleanup
        await super().cleanup_resources()
    
    async def run_all_tests(self):
        """Run all graph endpoint tests."""
        logger.info("🚀 Starting Graphs Endpoint Tests for Fuseki+PostgreSQL Backend")
        
        test_methods = [
            self.test_graph_creation,
            self.test_graph_listing,
            self.test_graph_info_retrieval,
            self.test_graph_clear,
            self.test_graph_deletion,
            self.test_dual_write_consistency
        ]
        
        for test_method in test_methods:
            try:
                await test_method()
                await asyncio.sleep(0.1)  # Brief pause between tests
            except Exception as e:
                logger.error(f"❌ Test method {test_method.__name__} failed with exception: {e}")
        
        # Print summary
        self.print_test_summary()


async def main():
    """Main test execution function."""
    tester = GraphsEndpointFusekiPostgreSQLTester()
    
    try:
        # Setup hybrid backend
        if not await tester.setup_hybrid_backend():
            logger.error("❌ Failed to setup hybrid backend")
            return False
        
        # Run all tests
        await tester.run_all_tests()
        
        # Check if all tests passed
        success = all(result["success"] for result in tester.test_results)
        
        if success:
            logger.info("🎉 All graphs endpoint tests PASSED!")
        else:
            logger.error("❌ Some graphs endpoint tests FAILED!")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Test execution failed: {e}")
        return False
    finally:
        # Cleanup resources
        await tester.cleanup_resources()


if __name__ == "__main__":
    # Run the test suite
    success = asyncio.run(main())
    
    if success:
        print("\n🎉 SUCCESS: Graphs endpoint tests completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ FAILURE: Graphs endpoint tests failed!")
        sys.exit(1)
