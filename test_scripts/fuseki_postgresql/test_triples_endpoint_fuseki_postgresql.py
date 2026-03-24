#!/usr/bin/env python3
"""
Comprehensive Triples Endpoint Test for Fuseki+PostgreSQL Backend

Tests the triples endpoint with proper endpoint method calls following the established pattern:
- Create test space
- Add triples via quad documents
- Search and list triples with various filters
- Delete specific triples
- Validate dual-write consistency between Fuseki and PostgreSQL
- Clean up test space

Architecture: test → endpoint → backend → database
"""

import asyncio
import sys
import logging
import uuid
from typing import Dict, Any, List, Optional

# Import test framework
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Import endpoint and models
from vitalgraph.endpoint.triples_endpoint import TriplesEndpoint
from vitalgraph.model.triples_model import TripleListRequest
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
from vitalgraph.model.spaces_model import Space

# Import modular test cases
from test_script_kg_impl.triples.case_triples_addition import TriplesAdditionTester
from test_script_kg_impl.triples.case_triples_listing import TriplesListingTester
from test_script_kg_impl.triples.case_triples_deletion import TriplesDeleteTester
from test_script_kg_impl.triples.case_triples_consistency import TriplesConsistencyTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TriplesEndpointFusekiPostgreSQLTester(FusekiPostgreSQLEndpointTester):
    """
    Comprehensive test suite for Triples Endpoint with Fuseki+PostgreSQL backend.
    
    Tests all triples operations:
    - Add triples via quad documents
    - List triples with pagination and filtering
    - Search triples by subject/predicate/object
    - Delete specific triples
    - Dual-write consistency validation
    """
    
    def __init__(self):
        super().__init__()
        self.triples_endpoint = None
        self.test_space_id = None
        self.test_graph_id = None
        self.added_triples_count = 0
        self.test_documents = []
        
    async def setup_triples_endpoint(self) -> bool:
        """Setup triples endpoint with hybrid backend."""
        try:
            # Mock auth dependency
            def mock_auth():
                return {"username": "test_user", "user_id": "test_user_123"}
            
            # Initialize triples endpoint
            self.triples_endpoint = TriplesEndpoint(
                space_manager=self.space_manager,
                auth_dependency=mock_auth
            )
            
            logger.info("✅ Triples endpoint initialized with hybrid backend")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup triples endpoint: {e}")
            return False
    
    async def _create_test_space(self):
        """Create a test space for triples operations."""
        if self.test_space_id:
            return
        
        self.test_space_id = f"test_triples_space_{uuid.uuid4().hex[:8]}"
        
        # Create space using space manager
        from vitalgraph.model.spaces_model import Space
        
        test_space = Space(
            space=self.test_space_id,
            space_name=f"Test Triples Space {self.test_space_id}",
            space_description="Test space for triples operations testing",
            tenant="test_tenant"
        )
        
        # Use create_space_with_tables to ensure proper setup
        success = await self.space_manager.create_space_with_tables(
            space_id=self.test_space_id,
            space_name=test_space.space_name,
            space_description=test_space.space_description
        )
        if not success:
            raise Exception("Failed to create test space for triples operations")
        
        logger.info(f"✅ Created test space: {self.test_space_id}")
    
    async def _create_test_graph(self):
        """Create a test graph for triples operations."""
        if self.test_graph_id:
            return
            
        self.test_graph_id = f"http://vital.ai/graph/triples_test_{uuid.uuid4().hex[:8]}"
        
        # Create graph using hybrid backend graphs functionality
        space_record = self.space_manager.get_space(self.test_space_id)
        space_impl = space_record.space_impl
        db_space_impl = space_impl.get_db_space_impl()
        
        # Create graph record in PostgreSQL
        success = await db_space_impl.graphs.create_graph(self.test_space_id, self.test_graph_id)
        if not success:
            raise Exception("Failed to create test graph for triples operations")
        
        logger.info(f"✅ Created test graph: {self.test_graph_id}")
    
    def _create_sample_graphobjects(self) -> List:
        """Create sample GraphObjects for testing."""
        objects = []
        
        node1 = VITAL_Node()
        node1.URI = "http://vital.ai/person/john_doe"
        node1.name = "John Doe"
        objects.append(node1)
        
        node2 = VITAL_Node()
        node2.URI = "http://vital.ai/org/acme_corp"
        node2.name = "ACME Corporation"
        objects.append(node2)
        
        node3 = VITAL_Node()
        node3.URI = "http://vital.ai/product/widget_123"
        node3.name = "Super Widget"
        objects.append(node3)
        
        return objects
    
    async def test_triples_addition(self):
        """Test adding triples using modular test case."""
        test_name = "Triples Addition via Quads"
        
        try:
            # Create test space and graph
            await self._create_test_space()
            await self._create_test_graph()
            
            # Use modular triples addition tester
            addition_tester = TriplesAdditionTester(self.triples_endpoint)
            addition_results = await addition_tester.test_triples_addition(self.test_space_id, self.test_graph_id)
            
            if addition_results['success']:
                # Extract total added count for other tests to use
                total_added = 0
                for detail in addition_results['test_details']:
                    if detail['name'] == 'Add Sample Documents' and detail.get('total_added'):
                        total_added = detail['total_added']
                        break
                
                self.added_triples_count = total_added
                
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Triples addition successful using modular test case - {addition_results['passed_tests']}/{addition_results['total_tests']} tests passed",
                    addition_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Triples addition failed in modular test case - Failed tests: {', '.join(addition_results['failed_tests'])}",
                    addition_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during triples addition test: {e}")
    
    async def test_triples_listing(self):
        """Test listing triples using modular test case."""
        test_name = "Triples Listing with Pagination"
        
        try:
            if not self.test_space_id or not self.test_graph_id:
                await self._create_test_space()
                await self._create_test_graph()
            
            # Use modular triples listing tester
            listing_tester = TriplesListingTester(self.triples_endpoint)
            listing_results = await listing_tester.test_triples_listing(self.test_space_id, self.test_graph_id)
            
            if listing_results['success']:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Triples listing successful using modular test case - {listing_results['passed_tests']}/{listing_results['total_tests']} tests passed",
                    listing_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Triples listing failed in modular test case - Failed tests: {', '.join(listing_results['failed_tests'])}",
                    listing_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during triples listing test: {e}")
    
    async def test_triples_deletion(self):
        """Test deleting triples using modular test case."""
        test_name = "Triples Deletion"
        
        try:
            if not self.test_space_id or not self.test_graph_id:
                await self._create_test_space()
                await self._create_test_graph()
            
            # Use modular triples deletion tester
            deletion_tester = TriplesDeleteTester(self.triples_endpoint)
            deletion_results = await deletion_tester.test_triples_deletion(self.test_space_id, self.test_graph_id)
            
            if deletion_results['success']:
                self.log_test_result(
                    test_name, 
                    True, 
                    f"Triples deletion successful using modular test case - {deletion_results['passed_tests']}/{deletion_results['total_tests']} tests passed",
                    deletion_results
                )
            else:
                self.log_test_result(
                    test_name, 
                    False, 
                    f"Triples deletion failed in modular test case - Failed tests: {', '.join(deletion_results['failed_tests'])}",
                    deletion_results
                )
            
        except Exception as e:
            self.log_test_result(test_name, False, f"Exception during triples deletion test: {e}")
    
    async def test_dual_write_consistency(self):
        """Test dual-write consistency using modular test case."""
        test_name = "Dual-Write Consistency Validation"
        
        try:
            if not self.test_space_id or not self.test_graph_id:
                await self._create_test_space()
                await self._create_test_graph()
            
            # Use modular triples consistency tester
            consistency_tester = TriplesConsistencyTester(self.triples_endpoint, self._validate_triples_dual_storage)
            consistency_results = await consistency_tester.test_dual_write_consistency(self.test_space_id, self.test_graph_id)
            
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

    async def _validate_triples_dual_storage(self) -> Dict[str, Any]:
        """Validate that triples are consistently stored in both Fuseki and PostgreSQL."""
        
        logger.info(f"🔍 STARTING dual-write consistency validation for space {self.test_space_id}, graph {self.test_graph_id}")
        
        try:
            space_record = self.space_manager.get_space(self.test_space_id)
            space_impl = space_record.space_impl
            
            # Get PostgreSQL triple count using hybrid backend method
            postgresql_count = 0
            try:
                logger.info(f"🔍 Starting PostgreSQL count validation...")
                
                db_space_impl = space_impl.get_db_space_impl()
                logger.info(f"🔍 db_space_impl: {db_space_impl}")
                logger.info(f"🔍 db_space_impl type: {type(db_space_impl)}")
                
                if db_space_impl:
                    logger.info(f"🔍 db_space_impl has postgresql_impl: {hasattr(db_space_impl, 'postgresql_impl')}")
                    if hasattr(db_space_impl, 'postgresql_impl'):
                        postgresql_impl = db_space_impl.postgresql_impl
                        logger.info(f"🔍 postgresql_impl: {postgresql_impl}")
                        logger.info(f"🔍 postgresql_impl has connection_pool: {hasattr(postgresql_impl, 'connection_pool')}")
                        
                        # Get table names for the space using correct format
                        quad_table = f"{self.test_space_id}_rdf_quad"
                        term_table = f"{self.test_space_id}_term"
                        logger.info(f"🔍 Table names: {term_table}, {quad_table}")
                        
                        # Get connection from PostgreSQL implementation
                        logger.info(f"🔍 Acquiring connection from PostgreSQL pool...")
                        conn = await postgresql_impl.connection_pool.acquire()
                        logger.info(f"🔍 Connection acquired: {conn}")
                        
                        try:
                            logger.info(f"🔍 Executing PostgreSQL count query...")
                            
                            # First check if table exists
                            table_exists = await conn.fetchval(
                                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
                                quad_table
                            )
                            logger.info(f"🔍 Table {quad_table} exists: {table_exists}")
                            
                            if table_exists:
                                # Count quads with optional graph filtering
                                if self.test_graph_id:
                                    # Count quads in specific graph by joining with term table
                                    term_table = f"{self.test_space_id}_term"
                                    count_query = f"""
                                    SELECT COUNT(*) 
                                    FROM {quad_table} q
                                    JOIN {term_table} t ON q.context_uuid = t.term_uuid
                                    WHERE q.dataset = 'primary' AND t.term_text = $1
                                    """
                                    total_quads = await conn.fetchval(count_query, self.test_graph_id)
                                    logger.info(f"🔍 Quads in PostgreSQL for graph {self.test_graph_id}: {total_quads}")
                                else:
                                    # Count all quads across all graphs
                                    total_quads = await conn.fetchval(f"SELECT COUNT(*) FROM {quad_table} WHERE dataset = 'primary'")
                                    logger.info(f"🔍 Total quads in PostgreSQL table (all graphs): {total_quads}")
                                postgresql_count = total_quads if total_quads else 0
                            else:
                                logger.warning(f"⚠️ Table {quad_table} does not exist")
                                postgresql_count = 0
                            
                        except Exception as query_error:
                            logger.error(f"❌ Query execution error: {query_error}")
                            import traceback
                            logger.error(f"❌ Query traceback: {traceback.format_exc()}")
                            postgresql_count = 0
                        finally:
                            logger.info(f"🔍 Releasing connection...")
                            await postgresql_impl.connection_pool.release(conn)
                            logger.info(f"🔍 Connection released")
                    else:
                        logger.error(f"❌ db_space_impl has no 'postgresql_impl' attribute")
                else:
                    logger.error(f"❌ db_space_impl is None")
                    
            except Exception as e:
                logger.error(f"❌ Failed to get PostgreSQL count: {e}")
                import traceback
                logger.error(f"❌ PostgreSQL validation traceback: {traceback.format_exc()}")
                postgresql_count = 0
                
            logger.info(f"🔍 Final PostgreSQL count: {postgresql_count}")
            
            # Get Fuseki triple count via SPARQL using hybrid backend
            fuseki_count = 0
            try:
                sparql_query = f"""
                SELECT (COUNT(*) as ?count) WHERE {{
                    GRAPH <{self.test_graph_id}> {{
                        ?s ?p ?o .
                    }}
                }}
                """
                # Use the hybrid backend's fuseki manager for count
                db_space_impl = space_impl.get_db_space_impl()
                if db_space_impl and hasattr(db_space_impl, 'fuseki_manager'):
                    # For COUNT queries, use the fuseki manager directly
                    count_info = await db_space_impl.fuseki_manager.get_dataset_info(self.test_space_id, self.test_graph_id)
                    if count_info and isinstance(count_info, dict):
                        fuseki_count = count_info.get('triple_count', 0)
                    else:
                        fuseki_count = 0
            except Exception as e:
                logger.warning(f"Failed to get Fuseki count: {e}")
            
            consistent = (postgresql_count == fuseki_count)
            
            return {
                "consistent": consistent,
                "postgresql_count": postgresql_count,
                "fuseki_count": fuseki_count,
                "space_id": self.test_space_id,
                "graph_id": self.test_graph_id
            }
            
        except Exception as e:
            logger.error(f"Error validating dual-write consistency: {e}")
            return {
                "consistent": False,
                "error": str(e),
                "space_id": self.test_space_id,
                "graph_id": self.test_graph_id
            }
    
    async def run_all_tests(self):
        """Run all triples endpoint tests."""
        logger.info("🚀 Starting Triples Endpoint Tests for Fuseki+PostgreSQL Backend")
        
        # CRITICAL: Test insertion first - all other tests depend on having data
        try:
            await self.test_triples_addition()
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"❌ Test method test_triples_addition failed with exception: {e}")
        
        # Check if insertion actually worked by verifying data exists
        try:
            insertion_successful = self.test_results.get("Triples Addition via Quads", False) if isinstance(self.test_results, dict) else False
            logger.info(f"🔍 Insertion successful check: {insertion_successful}")
            logger.info(f"🔍 Test results keys: {list(self.test_results.keys()) if isinstance(self.test_results, dict) else 'Not a dict'}")
            
            # Also check if we have added_triples_count > 0 as backup verification
            if not insertion_successful and hasattr(self, 'added_triples_count') and self.added_triples_count > 0:
                logger.info(f"🔍 Backup check: added_triples_count = {self.added_triples_count}")
                insertion_successful = True
                
        except AttributeError as e:
            logger.error(f"Error accessing test_results: {e}, type: {type(self.test_results)}")
            insertion_successful = False
        
        if not insertion_successful:
            # FAIL all remaining tests since they depend on having data
            dependent_tests = [
                "Triples Listing with Pagination",
                "Triples Deletion"
            ]
            
            for test_name in dependent_tests:
                self.log_test_result(test_name, False, 
                    "SKIPPED: Cannot test operations on empty database - insertion failed")
            
            logger.error("❌ CRITICAL: Triples insertion failed - skipping dependent tests to avoid false positives")
        else:
            # Only run other tests if insertion worked
            test_methods = [
                self.test_triples_listing,
                self.test_triples_deletion
            ]
            
            for test_method in test_methods:
                try:
                    await test_method()
                    await asyncio.sleep(0.1)  # Brief pause between tests
                except Exception as e:
                    logger.error(f"❌ Test method {test_method.__name__} failed with exception: {e}")
        
        # Always test dual-write consistency (works regardless of data presence)
        try:
            await self.test_dual_write_consistency()
        except Exception as e:
            logger.error(f"❌ Test method test_dual_write_consistency failed with exception: {e}")
        
        # Print summary
        self.print_test_summary()
    
    async def cleanup_resources(self):
        """Clean up test resources."""
        logger.info("🧹 Starting cleanup of test resources...")
        
        # Clean up test space
        if self.test_space_id:
            try:
                await self.space_manager.delete_space_with_tables(self.test_space_id)
                logger.info(f"✅ Cleaned up test space: {self.test_space_id}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup test space {self.test_space_id}: {e}")
        
        # Clean up hybrid backend
        await super().cleanup_resources()


async def main():
    """Main test execution function."""
    tester = TriplesEndpointFusekiPostgreSQLTester()
    
    try:
        # Setup hybrid backend
        if not await tester.setup_hybrid_backend():
            logger.error("❌ Failed to setup hybrid backend")
            return False
        
        # Setup triples endpoint
        if not await tester.setup_triples_endpoint():
            logger.error("❌ Failed to setup triples endpoint")
            return False
        
        # Run all tests
        await tester.run_all_tests()
        
        # Check if all tests passed
        success = all(result["success"] for result in tester.test_results)
        
        if success:
            logger.info("🎉 All triples endpoint tests PASSED!")
        else:
            logger.error("❌ Some triples endpoint tests FAILED!")
        
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
        print("\n🎉 SUCCESS: Triples endpoint tests completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ FAILURE: Triples endpoint tests failed!")
        sys.exit(1)
