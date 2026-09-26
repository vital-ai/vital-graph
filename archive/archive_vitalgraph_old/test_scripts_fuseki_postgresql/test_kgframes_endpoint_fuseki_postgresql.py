#!/usr/bin/env python3
"""
Comprehensive KGFrames Endpoint Test for Fuseki+PostgreSQL Backend

Tests the KGFrames endpoint with proper endpoint method calls following the established pattern:
- Create test space
- Insert KG frames via VitalSigns quad documents
- List KG frames (empty and populated states)
- Get individual KG frames by URI
- Update KG frame properties
- Delete specific KG frames
- Test KG slots within frame context
- Validate dual-write consistency between Fuseki and PostgreSQL
- Clean up test space

Architecture: test → endpoint → backend → database
VitalSigns Integration: KGFrame objects ↔ quads ↔ endpoint

Uses modular test implementations from test_script_kg_impl/kgframes/ package.
"""

import asyncio
import sys
import logging
import uuid
from typing import Dict, Any, List, Optional

# Import test framework
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Import endpoint and models
from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
from vitalgraph.model.kgframes_model import (
    FramesResponse,
    FrameCreateResponse,
    FrameUpdateResponse,
    FrameDeleteResponse,
    SlotCreateResponse,
    SlotUpdateResponse,
    SlotDeleteResponse
)
from vitalgraph.model.spaces_model import Space

# Import VitalSigns for KGFrame objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

# Import test cases from local test_script_kg_impl package
import test_script_kg_impl.kgframes.case_frame_create as case_frame_create
import test_script_kg_impl.kgframes.case_frame_delete as case_frame_delete
import test_script_kg_impl.kgframes.case_frame_get as case_frame_get
import test_script_kg_impl.kgframes.case_frame_update as case_frame_update
import test_script_kg_impl.kgframes.case_frame_hierarchical as case_frame_hierarchical
import test_script_kg_impl.kgframes.case_frame_slots as case_frame_slots


class KGFramesEndpointTester(FusekiPostgreSQLEndpointTester):
    """
    Comprehensive tester for KGFrames endpoint using Fuseki+PostgreSQL backend.
    
    Follows the established pattern from KGEntities testing with direct backend integration.
    """
    
    def __init__(self):
        """Initialize the KGFrames endpoint tester."""
        super().__init__()
        self.endpoint = None  # For backward compatibility with integration tests
        self.kgframes_endpoint = None
        self.kgentities_endpoint = None
        self.test_space_id = None
        self.test_graph_id = None
        self.vitalsigns = VitalSigns()
        self.logger = logging.getLogger(__name__)
        
    async def setup_test_environment(self) -> bool:
        """Set up the test environment with space and endpoint."""
        try:
            # Initialize hybrid backend
            if not await self.setup_hybrid_backend():
                return False
                
            # Endpoints are already initialized by parent class setup_hybrid_backend()
            # Just verify they exist
            if not hasattr(self, 'kgframes_endpoint') or not self.kgframes_endpoint:
                self.logger.error("KGFrames endpoint not initialized")
                return False
            if not hasattr(self, 'kgentities_endpoint') or not self.kgentities_endpoint:
                self.logger.error("KGEntities endpoint not initialized")
                return False
            
            # Set backend adapter for cleanup
            self.backend_adapter = self.hybrid_backend
            
            # Create test space
            self.test_space_id = f"test_kgframes_{uuid.uuid4().hex[:8]}"
            self.test_graph_id = f"http://vital.ai/graph/test_kgframes_graph_{uuid.uuid4().hex[:8]}"
            
            space = Space(
                space=self.test_space_id,
                space_name="KGFrames Test Space",
                description="Test space for KGFrames endpoint testing"
            )
            
            # Use create_space_with_tables to ensure proper setup (following KGEntities pattern)
            space_created = await self.space_manager.create_space_with_tables(
                space_id=self.test_space_id,
                space_name="KGFrames Test Space",
                space_description="Test space for KGFrames endpoint testing"
            )
            if not space_created:
                self.logger.error("Failed to create test space")
                return False
                
            self.logger.info(f"Created test space: {self.test_space_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup test environment: {e}")
            return False
    
    async def cleanup_test_environment(self) -> bool:
        """Clean up the test environment."""
        try:
            if self.test_space_id and self.space_manager:
                # Delete test space using space manager
                deleted = await self.space_manager.delete_space_with_tables(self.test_space_id)
                if deleted:
                    self.logger.info(f"Deleted test space: {self.test_space_id}")
                else:
                    self.logger.warning(f"Failed to delete test space: {self.test_space_id}")
                    
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to cleanup test environment: {e}")
            return False
    
    async def run_frame_create_tests(self) -> bool:
        """Run frame creation tests."""
        try:
            self.logger.info("🧪 Running frame creation tests...")
            
            # Use the modular test case
            result = await case_frame_create.test_frame_creation(
                endpoint=self.endpoint,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                logger=self.logger
            )
            
            if result:
                self.logger.info("✅ Frame creation tests passed")
            else:
                self.logger.error("❌ Frame creation tests failed")
                
            return result
            
        except Exception as e:
            self.logger.error(f"Frame creation tests failed with exception: {e}")
            return False
    
    async def run_frame_get_tests(self) -> bool:
        """Run frame retrieval tests."""
        try:
            self.logger.info("🧪 Running frame retrieval tests...")
            
            # Use the modular test case
            result = await case_frame_get.test_frame_retrieval(
                endpoint=self.endpoint,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                logger=self.logger
            )
            
            if result:
                self.logger.info("✅ Frame retrieval tests passed")
            else:
                self.logger.error("❌ Frame retrieval tests failed")
                
            return result
            
        except Exception as e:
            self.logger.error(f"Frame retrieval tests failed with exception: {e}")
            return False
    
    async def run_frame_update_tests(self) -> bool:
        """Run frame update tests."""
        try:
            self.logger.info("🧪 Running frame update tests...")
            
            # Use the modular test case
            result = await case_frame_update.test_frame_update(
                endpoint=self.endpoint,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                logger=self.logger
            )
            
            if result:
                self.logger.info("✅ Frame update tests passed")
            else:
                self.logger.error("❌ Frame update tests failed")
                
            return result
            
        except Exception as e:
            self.logger.error(f"Frame update tests failed with exception: {e}")
            return False
    
    async def run_frame_delete_tests(self) -> bool:
        """Run frame deletion tests."""
        try:
            self.logger.info("🧪 Running frame deletion tests...")
            
            # Use the modular test case
            result = await case_frame_delete.test_frame_deletion(
                endpoint=self.endpoint,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                logger=self.logger
            )
            
            if result:
                self.logger.info("✅ Frame deletion tests passed")
            else:
                self.logger.error("❌ Frame deletion tests failed")
                
            return result
            
        except Exception as e:
            self.logger.error(f"Frame deletion tests failed with exception: {e}")
            return False
    
    async def run_frame_hierarchical_tests(self) -> bool:
        """Run hierarchical frame tests."""
        try:
            self.logger.info("🔧 Running hierarchical frame tests...")
            
            # Use the modular test case
            hierarchical_success = await case_frame_hierarchical.test_hierarchical_frames(
                self.endpoint, self.test_space_id, self.test_graph_id, self.logger
            )
            
            if hierarchical_success:
                self.logger.info("✅ Hierarchical frame tests passed")
            else:
                self.logger.error("❌ Hierarchical frame tests failed")
                
            # Test 6: Slot operations (GET/POST/PUT/DELETE on /api/graphs/kgframes/kgslots)
            self.logger.info("🔧 Running slot operation tests...")
            slot_success = await case_frame_slots.test_slot_operations(
                self.endpoint, self.test_space_id, self.test_graph_id, self.logger
            )
            
            if slot_success:
                self.logger.info("✅ Slot operation tests passed")
            else:
                self.logger.error("❌ Slot operation tests failed")
                
            return hierarchical_success and slot_success
            
        except Exception as e:
            self.logger.error(f"Hierarchical frame tests failed with exception: {e}")
            return False
    
    async def test_client_api_with_frame_graph(self) -> bool:
        """Test client API get_kgframe with include_frame_graph parameter."""
        try:
            self.logger.info("🧪 Testing client API with include_frame_graph parameter...")
            
            # Create test entity with frames and slots
            from vitalgraph.utils.test_data import create_vitalsigns_entity_graphs
            entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=False)
            entity_objects = entity_graphs[0]
            entity_uri = str(entity_objects[0].URI)
            
            # Find frame URI from entity objects
            frame_uri = None
            for obj in entity_objects:
                if isinstance(obj, KGFrame):
                    frame_uri = str(obj.URI)
                    break
            
            if not frame_uri:
                self.logger.error("❌ No frame found in test entity graph")
                return False
            
            # Create entity graph via endpoint
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode as EntityOperationMode
            entity_response = await self.kgentities_endpoint._create_or_update_entities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                request=entity_objects,
                operation_mode=EntityOperationMode.CREATE,
                parent_uri=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if not entity_response or not (hasattr(entity_response, 'success') and entity_response.success):
                self.logger.error("❌ Failed to create test entity graph")
                return False
            
            self.logger.info(f"✅ Created test entity graph with frame: {frame_uri}")
            
            # Test 1: Get frame WITHOUT include_frame_graph
            self.logger.info("🔧 Test 1: Get frame without include_frame_graph...")
            response_without = await self.kgframes_endpoint._get_frame_by_uri(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=frame_uri,
                include_frame_graph=False,
                current_user={"username": "test_user"}
            )
            
            if not response_without or not response_without.success:
                self.logger.error("❌ Failed to get frame without include_frame_graph")
                return False
            
            if not response_without.frame:
                self.logger.error("❌ Frame field is None")
                return False
            
            self.logger.info("✅ Frame retrieved without complete_graph")
            
            # Test 2: Get frame WITH include_frame_graph=True
            self.logger.info("🔧 Test 2: Get frame with include_frame_graph=True...")
            response_with = await self.kgframes_endpoint._get_frame_by_uri(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=frame_uri,
                include_frame_graph=True,
                current_user={"username": "test_user"}
            )
            
            if not response_with or not response_with.success:
                self.logger.error("❌ Failed to get frame with include_frame_graph=True")
                return False
            
            if not response_with.frame:
                self.logger.error("❌ Frame field is None")
                return False
            
            # CRITICAL: Verify complete_graph is populated when include_frame_graph=True
            if not response_with.complete_graph:
                self.logger.error("❌ CRITICAL BUG: complete_graph is None despite include_frame_graph=True")
                self.logger.error(f"   Response type: {type(response_with).__name__}")
                self.logger.error(f"   Response success: {response_with.success}")
                self.logger.error(f"   Frame type: {type(response_with.frame).__name__}")
                return False
            
            # Verify complete_graph contains frame and slots
            from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects
            if hasattr(response_with.complete_graph, 'results') and response_with.complete_graph.results:
                graph_objects = quad_list_to_graphobjects(response_with.complete_graph.results)
                
                frames_in_graph = [obj for obj in graph_objects if isinstance(obj, KGFrame)]
                slots_in_graph = [obj for obj in graph_objects if isinstance(obj, KGSlot)]
                
                self.logger.info(f"✅ complete_graph populated with {len(frames_in_graph)} frame(s) and {len(slots_in_graph)} slot(s)")
                
                if len(frames_in_graph) == 0:
                    self.logger.error("❌ complete_graph has no frames")
                    return False
            else:
                self.logger.warning("⚠️  complete_graph has no results")
            
            self.logger.info("✅ Client API with include_frame_graph tests passed")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Client API with include_frame_graph test failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    async def test_pydantic_serialization(self) -> bool:
        """Test that Pydantic response models serialize correctly with aliases."""
        try:
            self.logger.info("🧪 Testing Pydantic response model serialization...")
            
            # Create a simple frame to test response serialization
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            
            test_frame = KGFrame()
            test_frame.URI = f"http://vital.ai/test/frame/serialization_test_{uuid.uuid4().hex[:8]}"
            test_frame.name = "Serialization Test Frame"
            
            # Create frame via endpoint - pass GraphObjects directly
            response = await self.kgframes_endpoint._create_or_update_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                objects=[test_frame],
                operation_mode="create",
                parent_uri=None,
                entity_uri=None,
                current_user={"username": "test_user"}
            )
            
            # Test 1: Response is correct type
            if not isinstance(response, FrameCreateResponse):
                self.logger.error(f"❌ Response is not FrameCreateResponse: {type(response)}")
                return False
            
            # Test 2: Response serializes correctly
            try:
                serialized = response.model_dump(by_alias=True)
                self.logger.info(f"✅ Response serialized: {serialized.keys()}")
            except Exception as e:
                self.logger.error(f"❌ Failed to serialize response: {e}")
                return False
            
            # Test 3: Check required fields are present
            required_fields = ["success", "message", "created_count"]
            for field in required_fields:
                if field not in serialized:
                    self.logger.error(f"❌ Missing required field in serialization: {field}")
                    return False
            
            # Test 4: Check alias fields work correctly
            # frames_created should map to created_count
            if "frames_created" in serialized:
                self.logger.warning("⚠️  Alias field 'frames_created' present in serialization (should be 'created_count')")
            
            # Test 5: Verify values are correct
            if response.success:
                if serialized.get("created_count", 0) != 1:
                    self.logger.error(f"❌ Expected created_count=1, got {serialized.get('created_count')}")
                    return False
            
            self.logger.info("✅ Pydantic serialization tests passed")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Pydantic serialization test failed: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False
    
    async def run_comprehensive_tests(self) -> Dict[str, bool]:
        """Run all KGFrames tests with two-tier architecture and return results."""
        results = {}
        
        try:
            # Setup test environment
            if not await self.setup_test_environment():
                self.logger.error("Failed to setup test environment")
                return {"setup": False}
            
            # Category 1: Client API Tests (CRITICAL)
            self.logger.info("=" * 80)
            self.logger.info("CLIENT API TESTS")
            self.logger.info("=" * 80)
            client_api_success = await self.test_client_api_with_frame_graph()
            results["client_api_frame_graph"] = client_api_success
            
            # Category 2: Pydantic Serialization Tests (CRITICAL)
            self.logger.info("=" * 80)
            self.logger.info("PYDANTIC SERIALIZATION TESTS")
            self.logger.info("=" * 80)
            pydantic_success = await self.test_pydantic_serialization()
            results["pydantic_serialization"] = pydantic_success
            
            # Category 3: Standalone Tests (Independent of Entities)
            self.logger.info("=" * 80)
            self.logger.info("STANDALONE FRAME/SLOT TESTS")
            self.logger.info("=" * 80)
            standalone_results = await self.run_standalone_tests()
            results.update({f"standalone_{k}": v for k, v in standalone_results.items()})
            
            # Category 4: Entity-Associated Tests (Using KGEntities Endpoint)
            self.logger.info("=" * 80)
            self.logger.info("ENTITY-FRAME INTEGRATION TESTS")
            self.logger.info("=" * 80)
            integration_results = await self.run_integration_tests()
            results.update({f"integration_{k}": v for k, v in integration_results.items()})
            
            # Cleanup
            cleanup_success = await self.cleanup_test_environment()
            results["cleanup"] = cleanup_success
            
            return results
            
        except Exception as e:
            self.logger.error(f"Comprehensive tests failed: {e}")
            return {"error": False}
    
    async def run_standalone_tests(self) -> Dict[str, bool]:
        """Run tests that don't require entities - test frame/slot functionality independently."""
        self.logger.info("🧪 Running standalone frame/slot tests...")
        
        try:
            # Import all missing test functions
            from test_script_kg_impl.kgframes.case_frame_standalone_create import run_standalone_frame_creation_tests
            from test_script_kg_impl.kgframes.case_slot_standalone_create import run_standalone_slot_creation_tests
            
            # Import missing GET /api/kgframes tests
            from test_script_kg_impl.kgframes.case_frame_get import (
                test_filter_frames_by_entity_uri,
                test_search_frames_by_properties,
                test_invalid_parameter_validation
            )
            
            # Import missing POST /api/kgframes tests
            from test_script_kg_impl.kgframes.case_frame_create import (
                test_invalid_input_validation,
                test_duplicate_uri_handling
            )
            
            # Import missing DELETE /api/kgframes tests
            from test_script_kg_impl.kgframes.case_frame_delete import (
                test_delete_hierarchical_frame_structure
            )
            
            # Import hierarchical frame tests (child frames with parent_uri)
            from test_script_kg_impl.kgframes.case_frame_hierarchical import (
                test_hierarchical_frames,
                test_parent_child_frame_creation,
                test_multi_level_hierarchy
            )
            
            # Import missing POST /api/kgframes/query tests
            from test_script_kg_impl.kgframes.case_frame_query import (
                test_query_by_frame_type,
                test_query_by_entity_association,
                test_query_by_hierarchical_relationship,
                test_complex_multi_criteria_queries,
                test_pagination_in_query_results,
                test_invalid_query_syntax_handling
            )
            
            # Import missing GET /api/kgframes/kgslots tests
            from test_script_kg_impl.kgframes.case_frame_slots import (
                test_filter_slots_by_type,
                test_search_slots_by_value,
                test_empty_slot_collection_handling,
                test_invalid_filter_parameters
            )
            
            # Import missing POST /api/kgframes/kgslots (Update) tests
            from test_script_kg_impl.kgframes.case_slot_update import (
                test_update_single_slot_value,
                test_update_multiple_slots_batch,
                test_update_slot_type,
                test_update_slot_metadata,
                test_non_existent_slot_handling,
                test_concurrent_update_handling
            )
            
            # Import missing DELETE /api/kgframes/kgslots tests
            from test_script_kg_impl.kgframes.case_slot_delete import (
                test_delete_single_slot_by_uri,
                test_delete_multiple_slots_batch,
                test_delete_slots_for_frame,
                test_non_existent_slot_deletion_handling,
                test_cascade_delete_validation
            )
            
            # Define all test categories with their functions
            standalone_categories = [
                # Original basic tests
                ("standalone_frame_creation", run_standalone_frame_creation_tests),
                ("standalone_slot_creation", run_standalone_slot_creation_tests),
                
                # GET /api/kgframes missing tests (3 tests)
                ("get_frames_filter_by_entity", test_filter_frames_by_entity_uri),
                ("get_frames_search_properties", test_search_frames_by_properties),
                ("get_frames_invalid_params", test_invalid_parameter_validation),
                
                # POST /api/kgframes missing tests (2 tests)
                ("post_frames_invalid_input", test_invalid_input_validation),
                ("post_frames_duplicate_uri", test_duplicate_uri_handling),
                
                # DELETE /api/kgframes missing tests (1 test)
                ("delete_frames_hierarchical", test_delete_hierarchical_frame_structure),
                
                # POST /api/kgframes with parent_uri - Child Frames Tests (3 tests)
                ("hierarchical_frames_basic", test_hierarchical_frames),
                ("parent_child_frame_creation", test_parent_child_frame_creation),
                ("multi_level_hierarchy", test_multi_level_hierarchy),
                
                # POST /api/kgframes/query missing tests (6 tests)
                ("query_frames_by_type", test_query_by_frame_type),
                ("query_frames_by_entity", test_query_by_entity_association),
                ("query_frames_hierarchical", test_query_by_hierarchical_relationship),
                ("query_frames_multi_criteria", test_complex_multi_criteria_queries),
                ("query_frames_pagination", test_pagination_in_query_results),
                ("query_frames_invalid_syntax", test_invalid_query_syntax_handling),
                
                # GET /api/kgframes/kgslots missing tests (4 tests)
                ("get_slots_filter_by_type", test_filter_slots_by_type),
                ("get_slots_search_by_value", test_search_slots_by_value),
                ("get_slots_empty_collection", test_empty_slot_collection_handling),
                ("get_slots_invalid_filters", test_invalid_filter_parameters),
                
                # POST /api/kgframes/kgslots (Update) missing tests (6 tests)
                ("update_slot_single_value", test_update_single_slot_value),
                ("update_slots_batch", test_update_multiple_slots_batch),
                ("update_slot_type", test_update_slot_type),
                ("update_slot_metadata", test_update_slot_metadata),
                ("update_slot_non_existent", test_non_existent_slot_handling),
                ("update_slot_concurrent", test_concurrent_update_handling),
                
                # DELETE /api/kgframes/kgslots missing tests (5 tests)
                ("delete_slot_single", test_delete_single_slot_by_uri),
                ("delete_slots_batch", test_delete_multiple_slots_batch),
                ("delete_slots_for_frame", test_delete_slots_for_frame),
                ("delete_slot_non_existent", test_non_existent_slot_deletion_handling),
                ("delete_slot_cascade", test_cascade_delete_validation)
            ]
            
            results = {}
            for category_name, test_func in standalone_categories:
                self.logger.info(f"🔧 Running {category_name}...")
                try:
                    # Check if test function expects two endpoints (new architecture) or one (old architecture)
                    import inspect
                    sig = inspect.signature(test_func)
                    param_count = len(sig.parameters)
                    
                    if param_count == 5:  # New two-endpoint architecture
                        result = await test_func(self.kgframes_endpoint, self.kgentities_endpoint, self.test_space_id, self.test_graph_id, self.logger)
                    else:  # Old single-endpoint architecture
                        result = await test_func(self.kgframes_endpoint, self.test_space_id, self.test_graph_id, self.logger)
                    
                    results[category_name] = result
                    if result:
                        self.logger.info(f"✅ {category_name} passed")
                    else:
                        self.logger.error(f"❌ {category_name} failed")
                except Exception as e:
                    self.logger.error(f"❌ {category_name} failed with exception: {e}")
                    results[category_name] = False
            
            return results
            
        except ImportError as e:
            self.logger.error(f"Failed to import standalone test modules: {e}")
            return {"standalone_import_error": False}
    
    async def run_integration_tests(self) -> Dict[str, bool]:
        """Run tests that integrate with KGEntities endpoint."""
        self.logger.info("🧪 Running entity-frame integration tests...")
        
        try:
            # Initialize KGEntities endpoint for integration testing
            from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
            
            # Create a mock auth dependency for testing
            def mock_auth_dependency():
                return {"username": "test_user", "user_id": "test_user_123"}
            
            kgentities_endpoint = KGEntitiesEndpoint(
                space_manager=self.space_manager,
                auth_dependency=mock_auth_dependency
            )
            kgentities_endpoint.logger = self.logger
            
            from test_script_kg_impl.kgframes.case_entity_frame_integration import run_entity_frame_integration_tests
            
            integration_categories = [
                ("entity_frame_integration", run_entity_frame_integration_tests)
            ]
            
            results = {}
            for category_name, test_func in integration_categories:
                self.logger.info(f"🔧 Running {category_name}...")
                try:
                    result = await test_func(kgentities_endpoint, self.endpoint, self.test_space_id, self.test_graph_id, self.logger)
                    results[category_name] = result
                    if result:
                        self.logger.info(f"✅ {category_name} passed")
                    else:
                        self.logger.error(f"❌ {category_name} failed")
                except Exception as e:
                    self.logger.error(f"❌ {category_name} failed with exception: {e}")
                    results[category_name] = False
            
            return results
            
        except ImportError as e:
            self.logger.error(f"Failed to import integration test modules: {e}")
            return {"integration_import_error": False}


async def main():
    """Main test execution function."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    print("=" * 80)
    print("KGFrames Endpoint Comprehensive Test Suite")
    print("Backend: Fuseki + PostgreSQL")
    print("=" * 80)
    
    # Create and run tester
    tester = KGFramesEndpointTester()
    results = await tester.run_comprehensive_tests()
    
    # Print results summary
    print("\n" + "=" * 80)
    print("TEST RESULTS SUMMARY")
    print("=" * 80)
    
    total_tests = 0
    passed_tests = 0
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:20} {status}")
        total_tests += 1
        if result:
            passed_tests += 1
    
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    print(f"\nOverall Success Rate: {passed_tests}/{total_tests} ({success_rate:.1f}%)")
    
    if success_rate == 100.0:
        print("🎉 All KGFrames tests passed!")
        return 0
    else:
        print("⚠️  Some KGFrames tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)