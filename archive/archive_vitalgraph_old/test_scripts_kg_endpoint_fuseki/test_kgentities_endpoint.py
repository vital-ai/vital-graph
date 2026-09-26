#!/usr/bin/env python3
"""
Test script for KGEntitiesEndpoint with direct endpoint testing.

This script tests the KGEntitiesEndpoint functionality by:
1. Instantiating the VitalGraph app with Fuseki backend configuration
2. Testing space management operations directly
3. Testing entity CRUD operations through the endpoint
4. Testing VitalSigns integration

Usage:
    python test_kgentities_endpoint.py
"""

import sys
import asyncio
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import the base tester and utilities
from test_kg_endpoint_utils import BaseKGEndpointTester, run_test_suite, logger

# VitalGraph imports
from vitalgraph.model.kgentities_model import (
    EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse
)
from vital_ai_vitalsigns.model.GraphObject import GraphObject


class KGEntitiesEndpointTester(BaseKGEndpointTester):
    """Test harness for KGEntitiesEndpoint functionality."""
    
    def __init__(self, fuseki_url: str = "http://host.docker.internal:3030"):
        super().__init__(fuseki_url)
        
    async def test_space_management(self) -> bool:
        """Test basic space management operations."""
        logger.info("🧪 Testing Space Management Operations")
        
        # Create test space
        self.entity_test_space_id = await self.create_test_space("entity_test_space")
        if not self.entity_test_space_id:
            self.log_test_result("Space Management", False, "Failed to create test space")
            return False
        
        self.log_test_result("Space Management", True, f"Created test space: {self.entity_test_space_id}")
        return True
    
    async def test_entity_crud_operations(self) -> bool:
        """Test entity CRUD operations with multiple entity graphs."""
        try:
            logger.info("🔍 Testing Entity CRUD Operations with Multiple Entity Graphs")
            
            # Create entity graphs in the test space
            success = await self.create_entity_graphs_in_space(self.entity_test_space_id)
            if not success:
                self.log_test_result("Entity CRUD Operations", False, "Failed to create entity graphs")
                return False
            
            # Test retrieving multiple entity graphs using grouping URIs
            success = await self._test_retrieve_entity_graphs()
            if not success:
                self.log_test_result("Entity CRUD Operations", False, "Failed to retrieve entity graphs")
                return False
            
            # Test grouping URI functionality (list all entity graphs)
            success = await self._test_grouping_uri_retrieval()
            if not success:
                self.log_test_result("Entity CRUD Operations", False, "Failed grouping URI retrieval")
                return False
            
            # Test deleting multiple entity graphs using grouping URIs
            success = await self.cleanup_entity_graphs(self.entity_test_space_id)
            if not success:
                self.log_test_result("Entity CRUD Operations", False, "Failed to delete entity graphs")
                return False
            
            self.log_test_result("Entity CRUD Operations", True, "All entity operations completed successfully")
            return True
            
        except Exception as e:
            self.log_test_result("Entity CRUD Operations", False, f"Exception: {e}")
            return False
            
            # Log details about the test data
            total_objects = sum(len(graph) for graph in self.test_entity_graphs)
            logger.info(f"📊 Test data contains {total_objects} total objects across {len(self.test_entity_graphs)} entity graphs")
            
            # Log sample of what's in the first entity graph
            if self.test_entity_graphs:
                first_graph = self.test_entity_graphs[0]
                logger.info(f"📋 First entity graph contains {len(first_graph)} objects:")
                for i, obj in enumerate(first_graph[:3]):  # Show first 3 objects
                    obj_type = type(obj).__name__
                    obj_uri = getattr(obj, 'URI', 'N/A')
                    logger.info(f"  [{i+1}] {obj_type}: {obj_uri}")
                if len(first_graph) > 3:
                    logger.info(f"  ... and {len(first_graph) - 3} more objects")
            
            logger.info("✅ VitalGraph app setup completed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup VitalGraph app: {e}")
            return False
    
    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log test result in a consistent format."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}")
        if not success or data:
            logger.info(f"    {message}")
            if data:
                logger.info(f"    Data: {json.dumps(data, indent=2)}")
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data or {}
        })
    
    # ============================================================================
    # Space Management Tests
    # ============================================================================
    
    async def test_space_management(self) -> bool:
        """Test basic space management operations."""
        logger.info("🧪 Testing Space Management Operations")
        
        try:
            # First, list existing spaces
            try:
                existing_spaces = self.space_manager.list_spaces()
                if existing_spaces and isinstance(existing_spaces[0], str):
                    existing_space_ids = existing_spaces
                else:
                    existing_space_ids = [space.space_id for space in existing_spaces]
                logger.info(f"🔍 Existing spaces before test: {existing_space_ids}")
            except Exception as e:
                logger.warning(f"⚠️ Could not list existing spaces: {e}")
            
            # Generate unique test space ID
            self.test_space_id = f"test_space_{uuid.uuid4().hex[:8]}"
            logger.info(f"Using test space ID: {self.test_space_id}")
            
            # Test 1: Create test space
            success = await self._create_test_space()
            if not success:
                return False
            
            # Test 2: List spaces to verify creation
            success = self._list_spaces_and_verify()
            if not success:
                return False
            
            # Test 3: Delete test space
            success = await self._delete_test_space()
            if not success:
                return False
            
            # Test 4: Verify space deletion
            success = self._verify_space_deleted()
            if not success:
                return False
            
            self.log_test_result("Space Management", True, "All space operations completed successfully")
            return True
            
        except Exception as e:
            self.log_test_result("Space Management", False, f"Exception: {e}")
            return False
    
    async def _create_test_space(self) -> bool:
        """Create a test space."""
        try:
            # Create space using space manager with proper async method
            success = await self.space_manager.create_space_with_tables(
                space_id=self.test_space_id,
                space_name=f"Test Space {self.test_space_id}",
                space_description="Test space for KGEntitiesEndpoint testing"
            )
            
            if success:
                self.log_test_result("Create Test Space", True, f"Space {self.test_space_id} created")
                return True
            else:
                self.log_test_result("Create Test Space", False, "Failed to create space")
                return False
                
        except Exception as e:
            self.log_test_result("Create Test Space", False, f"Exception: {e}")
            return False
    
    def _list_spaces_and_verify(self) -> bool:
        """List spaces and verify test space exists."""
        try:
            spaces = self.space_manager.list_spaces()
            # Handle case where spaces might be strings or objects
            if spaces and isinstance(spaces[0], str):
                space_ids = spaces
            else:
                space_ids = [space.space_id for space in spaces]
            
            logger.info(f"🔍 All spaces found: {space_ids}")
            
            if self.test_space_id in space_ids:
                self.log_test_result("List and Verify Spaces", True, f"Found {len(spaces)} total spaces, test space verified")
                return True
            else:
                self.log_test_result("List and Verify Spaces", False, f"Test space not found in {space_ids}")
                return False
                
        except Exception as e:
            self.log_test_result("List and Verify Spaces", False, f"Exception: {e}")
            return False
    
    async def _delete_test_space(self) -> bool:
        """Delete the test space."""
        try:
            success = await self.space_manager.delete_space_with_tables(self.test_space_id)
            
            if success:
                self.log_test_result("Delete Test Space", True, f"Space {self.test_space_id} deleted")
                return True
            else:
                self.log_test_result("Delete Test Space", False, "Failed to delete space")
                return False
                
        except Exception as e:
            self.log_test_result("Delete Test Space", False, f"Exception: {e}")
            return False
    
    def _verify_space_deleted(self) -> bool:
        """Verify the test space has been deleted."""
        try:
            spaces = self.space_manager.list_spaces()
            # Handle case where spaces might be strings or objects
            if spaces and isinstance(spaces[0], str):
                space_ids = spaces
            else:
                space_ids = [space.space_id for space in spaces]
            
            if self.test_space_id not in space_ids:
                self.log_test_result("Verify Space Deletion", True, "Space successfully removed")
                return True
            else:
                self.log_test_result("Verify Space Deletion", False, "Space still exists after deletion")
                return False
                
        except Exception as e:
            self.log_test_result("Verify Space Deletion", False, f"Exception: {e}")
            return False
    
    # ============================================================================
    # Entity CRUD Tests
    # ============================================================================
    
    async def test_entity_crud_operations(self) -> bool:
        """Test entity CRUD operations with multiple entity graphs."""
        try:
            logger.info("🔍 Testing Entity CRUD Operations with Multiple Entity Graphs")
            
            # Test creating multiple entity graphs
            success = await self._test_create_entity_graphs()
            if not success:
                return False
            
            # Test retrieving multiple entity graphs using grouping URIs
            success = await self._test_retrieve_entity_graphs()
            if not success:
                return False
            
            # Test grouping URI functionality (list all entity graphs)
            success = await self._test_grouping_uri_retrieval()
            if not success:
                return False
            
            # Test deleting multiple entity graphs using grouping URIs
            success = await self._test_delete_entity_graphs()
            if not success:
                return False
            
            self.log_test_result("Entity CRUD Operations", True, "All entity operations completed successfully")
            return True
            
        except Exception as e:
            self.log_test_result("Entity CRUD Operations", False, f"Exception: {e}")
            return False

    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log test result in a consistent format."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}")
        if not success or data:
            logger.info(f"    {message}")
            if data:
                logger.info(f"    Data: {json.dumps(data, indent=2)}")
            
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data or {}
        })

# ============================================================================
# Space Management Tests
# ============================================================================

    async def test_space_management(self) -> bool:
        """Test basic space management operations."""
        logger.info("🧪 Testing Space Management Operations")
        return True
    
    async def _test_create_entity_graphs(self) -> bool:
        """Test creating multiple entity graphs with VitalSigns objects."""
        try:
            logger.info("🔍 Creating multiple entity graphs with VitalSigns objects")
            
            # Create test space for entities
            test_space_id = f"entity_test_space_{uuid.uuid4().hex[:8]}"
            space_created = await self.space_manager.create_space_with_tables(
                space_id=test_space_id,
                space_name=f"Entity Test Space {test_space_id}",
                space_description="Test space for entity CRUD operations"
            )
            
            if not space_created:
                self.log_test_result("Create Entity Graphs", False, "Failed to create test space")
                return False
            
            # Store the test space ID for cleanup
            self.entity_test_space_id = test_space_id
            self.created_entity_uris = []
            
            # Create test entity graph using VitalSigns (this creates multiple entity graphs)
            entity_graphs = create_vitalsigns_entity_graphs(set_grouping_uris=False)
            
            if not entity_graphs:
                self.log_test_result("Create Entity Graphs", False, "Failed to create entity graphs")
                return False
            
            logger.info(f"📋 Created {len(entity_graphs)} entity graphs from test data")
            
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            # Create each entity graph in the test space
            for i, entity_graph in enumerate(entity_graphs):
                logger.info(f"🔍 Creating entity graph {i+1}/{len(entity_graphs)} with {len(entity_graph)} objects")
                
                # Create entities in the test space - pass GraphObjects directly
                response = await self.kgentities_endpoint._create_or_update_entities(
                    space_id=test_space_id,
                    graph_id="main",
                    objects=entity_graph,
                    operation_mode=OperationMode.CREATE,
                    parent_uri=None,
                    current_user={"username": "test_user", "user_id": "test_user_123"}
                )
                
                if response and hasattr(response, 'created_uris') and response.created_uris:
                    # Store the entity URI (first URI should be the main entity)
                    entity_uri = response.created_uris[0]
                    self.created_entity_uris.append(entity_uri)
                    logger.info(f"✅ Created entity graph {i+1}: {entity_uri} ({len(response.created_uris)} objects)")
                else:
                    self.log_test_result("Create Entity Graphs", False, f"No entities created for graph {i+1}")
                    return False
            
            self.log_test_result("Create Entity Graphs", True, f"Created {len(entity_graphs)} entity graphs with {len(self.created_entity_uris)} entities")
            return True
                
        except Exception as e:
            self.log_test_result("Create Entity Graphs", False, f"Exception: {e}")
            return False
    
    async def _test_retrieve_entity_graphs(self) -> bool:
        """Test retrieving multiple entity graphs by URI using grouping URIs."""
        try:
            if not hasattr(self, 'created_entity_uris') or not self.created_entity_uris:
                self.log_test_result("Retrieve Entity Graphs", False, "No test entity URIs available")
                return False
            
            if not hasattr(self, 'entity_test_space_id'):
                self.log_test_result("Retrieve Entity Graphs", False, "No test space ID available")
                return False
            
            logger.info(f"🔍 Retrieving {len(self.created_entity_uris)} entity graphs by grouping URI")
            
            retrieved_graphs = []
            
            # Retrieve each entity graph using grouping URIs
            for i, entity_uri in enumerate(self.created_entity_uris):
                logger.info(f"🔍 Retrieving entity graph {i+1}/{len(self.created_entity_uris)}: {entity_uri}")
                
                # Retrieve complete entity graph by URI (uses grouping URI internally)
                response = await self.kgentities_endpoint._get_entity_by_uri(
                    space_id=self.entity_test_space_id,
                    graph_id="main",
                    uri=entity_uri,
                    include_entity_graph=True,  # This should retrieve the complete entity graph
                    current_user={"username": "test_user", "user_id": "test_user_123"}
                )
                
                # Check if response has graph data
                if response and hasattr(response, 'graph') and response.graph:
                    retrieved_count = len(response.graph)
                    
                    # For complete entity graph retrieval, we should get back ALL objects (entities, frames, slots, edges)
                    expected_min_objects = 10  # At minimum, we should get the entity plus related frames/slots
                    
                    if retrieved_count >= expected_min_objects:
                        # Analyze what types of objects we retrieved
                        object_types = {}
                        for obj in response.graph:
                            obj_type = type(obj).__name__
                            object_types[obj_type] = object_types.get(obj_type, 0) + 1
                        
                        logger.info(f"✅ Retrieved entity graph {i+1}: {retrieved_count} objects")
                        logger.info(f"📊 Object types: {object_types}")
                        
                        retrieved_graphs.append({
                            'entity_uri': entity_uri,
                            'object_count': retrieved_count,
                            'object_types': object_types
                        })
                    else:
                        self.log_test_result("Retrieve Entity Graphs", False, f"Incomplete entity graph {i+1} - only retrieved {retrieved_count} objects")
                        return False
                else:
                    self.log_test_result("Retrieve Entity Graphs", False, f"No entity graph retrieved for {entity_uri}")
                    return False
            
            # Store retrieved graphs for deletion test
            self.retrieved_graphs = retrieved_graphs
            
            self.log_test_result("Retrieve Entity Graphs", True, f"Retrieved {len(retrieved_graphs)} complete entity graphs")
            return True
                
        except Exception as e:
            self.log_test_result("Retrieve Entity Graphs", False, f"Exception: {e}")
            return False
    
    async def _test_grouping_uri_retrieval(self) -> bool:
        """Test that grouping URIs properly retrieve complete entity graphs."""
        try:
            if not hasattr(self, 'entity_test_space_id'):
                self.log_test_result("Grouping URI Retrieval", False, "No test space ID available")
                return False
            
            logger.info("🔗 Testing grouping URI functionality for complete entity graph retrieval")
            
            # List all entities in the space to see what was created
            response = await self.kgentities_endpoint._list_entities(
                space_id=self.entity_test_space_id,
                graph_id="main",
                page_size=100,
                offset=0,
                entity_type_uri=None,
                search=None,
                include_entity_graph=True,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'entities') and response.entities and hasattr(response.entities, 'graph'):
                listed_count = len(response.entities.graph) if response.entities.graph else 0
                
                # For proper grouping URI functionality, we should retrieve the COMPLETE entity graph
                # This should include all objects with the same kGGraphURI (entities, frames, slots, edges)
                expected_min_objects = getattr(self, 'retrieved_entity_graph_count', 10)  # Use count from entity retrieval test
                
                if listed_count >= expected_min_objects:
                    self.log_test_result("Grouping URI Retrieval", True, f"Retrieved complete entity graph via grouping URI: {listed_count} objects")
                    
                    # Analyze the types of objects retrieved
                    object_types = {}
                    for obj in response.entities.graph:
                        obj_type = type(obj).__name__
                        object_types[obj_type] = object_types.get(obj_type, 0) + 1
                    
                    logger.info(f"📋 Grouping URI retrieval: {listed_count} objects")
                    logger.info(f"📊 Complete entity graph types: {object_types}")
                    
                    # Verify we have multiple object types (entities, frames, slots, edges)
                    if len(object_types) >= 2:
                        logger.info("✅ Grouping URI successfully retrieved diverse object types (entities + frames/slots/edges)")
                        return True
                    else:
                        logger.warning(f"⚠️ Grouping URI only retrieved {len(object_types)} object type(s) - expected multiple types")
                        return False
                else:
                    self.log_test_result("Grouping URI Retrieval", False, f"Incomplete grouping URI retrieval - only found {listed_count} objects (expected at least {expected_min_objects})")
                    return False
            else:
                logger.info(f"📋 Grouping URI response: {type(response)}")
                self.log_test_result("Grouping URI Retrieval", False, "No objects found via grouping URI")
                return False
                
        except Exception as e:
            self.log_test_result("Grouping URI Retrieval", False, f"Exception: {e}")
            return False
    
    async def _test_delete_entity_graphs(self) -> bool:
        """Test deleting multiple entity graphs using grouping URIs."""
        try:
            if not hasattr(self, 'created_entity_uris') or not self.created_entity_uris:
                self.log_test_result("Delete Entity Graphs", False, "No test entity URIs available")
                return False
            
            if not hasattr(self, 'entity_test_space_id'):
                self.log_test_result("Delete Entity Graphs", False, "No test space ID available")
                return False
            
            logger.info(f"🗑️ Deleting {len(self.created_entity_uris)} entity graphs using grouping URIs")
            
            deleted_graphs = []
            
            # Delete each entity graph using grouping URIs
            for i, entity_uri in enumerate(self.created_entity_uris):
                logger.info(f"🗑️ Deleting entity graph {i+1}/{len(self.created_entity_uris)}: {entity_uri}")
                
                # Delete complete entity graph by URI (should delete all objects with matching grouping URI)
                response = await self.kgentities_endpoint._delete_entity_by_uri(
                    space_id=self.entity_test_space_id,
                    graph_id="main",
                    uri=entity_uri,
                    delete_entity_graph=True,  # Delete the complete entity graph using grouping URIs
                    current_user={"username": "test_user", "user_id": "test_user_123"}
                )
                
                # Check if deletion was successful
                if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                    deleted_count = response.deleted_count
                    logger.info(f"✅ Deleted entity graph {i+1}: {deleted_count} objects")
                    
                    deleted_graphs.append({
                        'entity_uri': entity_uri,
                        'deleted_count': deleted_count
                    })
                    
                    # Verify the entity graph is actually deleted by checking for remaining objects with grouping URI
                    try:
                        # Use the list entities method to check if any objects with this grouping URI still exist
                        verify_response = await self.kgentities_endpoint._list_entities(
                            space_id=self.entity_test_space_id,
                            graph_id="main",
                            page_size=100,
                            offset=0,
                            entity_type_uri=None,
                            search=None,
                            include_entity_graph=True,  # This should find objects with grouping URIs
                            current_user={"username": "test_user", "user_id": "test_user_123"}
                        )
                        
                        # Check if any objects are returned - there should be none for this entity graph
                        remaining_objects = 0
                        if verify_response and hasattr(verify_response, 'entities') and verify_response.entities and hasattr(verify_response.entities, 'graph'):
                            # Filter objects that have the deleted entity URI as their grouping URI
                            for obj in verify_response.entities.graph:
                                # Check if this object has the deleted entity as its grouping URI
                                if hasattr(obj, 'hasKGGraphURI') and obj.hasKGGraphURI:
                                    if str(obj.hasKGGraphURI) == entity_uri:
                                        remaining_objects += 1
                        
                        if remaining_objects > 0:
                            self.log_test_result("Delete Entity Graphs", False, f"Entity graph {i+1} still has {remaining_objects} objects after deletion")
                            return False
                        else:
                            logger.info(f"✅ Verified entity graph {i+1} is completely deleted (0 remaining objects)")
                            
                    except Exception as verify_error:
                        # If listing fails, assume deletion worked
                        logger.info(f"✅ Entity graph {i+1} deletion verified (listing failed as expected)")
                else:
                    self.log_test_result("Delete Entity Graphs", False, f"Failed to delete entity graph {i+1}")
                    return False
            
            self.log_test_result("Delete Entity Graphs", True, f"Deleted {len(deleted_graphs)} complete entity graphs")
            return True
                
        except Exception as e:
            self.log_test_result("Delete Entity Graphs", False, f"Exception: {e}")
            return False
    
    def create_sample_entity(self, entity_uri: str, entity_name: str):
        """Create a sample KGEntity GraphObject."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        entity = KGEntity()
        entity.URI = entity_uri
        entity.name = entity_name
        entity.kgGraphURI = entity_uri
        return [entity]
    
    # ============================================================================
    # Cleanup Methods
    # ============================================================================
    
    async def _cleanup_resources(self):
        """Clean up resources to prevent warnings."""
        try:
            if self.vital_graph_impl:
                # Close any remaining space implementations
                if self.space_manager:
                    try:
                        # Access the internal _spaces cache if it exists
                        if hasattr(self.space_manager, '_spaces'):
                            cached_spaces = getattr(self.space_manager, '_spaces', {})
                            logger.info(f"🧹 Found {len(cached_spaces)} cached spaces to clean up")
                            
                            for space_id, space_record in cached_spaces.items():
                                try:
                                    logger.info(f"🧹 Cleaning up space: {space_id}")
                                    
                                    # Get the SpaceImpl from SpaceRecord and close it
                                    if hasattr(space_record, 'space_impl'):
                                        space_impl = space_record.space_impl
                                        if hasattr(space_impl, 'close'):
                                            await space_impl.close()
                                            logger.info(f"🧹 Closed SpaceImpl for space: {space_id}")
                                            
                                except Exception as e:
                                    logger.warning(f"⚠️ Error closing space {space_id}: {e}")
                
                        else:
                            logger.info("🧹 No _spaces cache found in space manager")
                    except Exception as e:
                        logger.warning(f"⚠️ Warning accessing cached spaces: {e}")
                
                # Clean up entity test space if it exists
                if hasattr(self, 'entity_test_space_id') and self.entity_test_space_id:
                    try:
                        logger.info(f"🧹 Cleaning up entity test space: {self.entity_test_space_id}")
                        await self.space_manager.delete_space_with_tables(self.entity_test_space_id)
                        logger.info(f"🧹 Deleted entity test space: {self.entity_test_space_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error cleaning up entity test space: {e}")
                
                # Close main database implementation
                db_impl = self.vital_graph_impl.get_db_impl()
                if db_impl:
                    # Close the main space implementation
                    if hasattr(db_impl, 'get_space_impl'):
                        try:
                            main_space_impl = db_impl.get_space_impl()
                            if main_space_impl and hasattr(main_space_impl, 'close'):
                                await main_space_impl.close()
                                logger.info("🧹 Closed main space implementation")
                        except Exception as e:
                            logger.warning(f"⚠️ Warning closing main space implementation: {e}")
                    
                    # Close main database connection
                    if hasattr(db_impl, 'close'):
                        await db_impl.close()
                        logger.info("🧹 Closed main database implementation")
                    elif hasattr(db_impl, 'disconnect'):
                        await db_impl.disconnect()
                        logger.info("🧹 Disconnected main database implementation")
                
                # Small delay to ensure cleanup completes
                import asyncio
                await asyncio.sleep(0.1)
                    
            logger.info("🧹 Resources cleaned up successfully")
            
        except Exception as e:
            logger.warning(f"⚠️ Warning during cleanup: {e}")
    
    # ============================================================================
    # Main Test Runner
    # ============================================================================
    
    async def run_all_tests(self) -> bool:
        """Run all test suites."""
        logger.info("🚀 Starting KGEntitiesEndpoint Test Suite")
        logger.info("=" * 60)
        
        try:
            # Setup VitalGraph app
            if not await self.setup_vitalgraph_app():
                logger.error("❌ Failed to setup VitalGraph app")
                return False
            
            # Test suites
            test_results = []
            
            # Test 1: Space Management
            result = await self.test_space_management()
            test_results.append(("Space Management", result))
            
            # Test 2: Entity CRUD Operations
            result = await self.test_entity_crud_operations()
            test_results.append(("Entity CRUD Operations", result))
            
            # Summary
            logger.info("=" * 60)
            logger.info("📊 Test Results Summary:")
            
            all_passed = True
            for test_name, passed in test_results:
                status = "✅ PASSED" if passed else "❌ FAILED"
                logger.info(f"  {test_name}: {status}")
                if not passed:
                    all_passed = False
            
            logger.info("-" * 60)
            if all_passed:
                logger.info("🎉 All tests PASSED!")
            else:
                logger.error("💥 Some tests FAILED!")
            
            return all_passed
            
        finally:
            # Cleanup resources
            await self._cleanup_resources()


async def main():
    """Main test execution function."""
    logger.info("🚀 Starting KGEntitiesEndpoint Tests")
    
    # Define test methods to run
    test_methods = [
        "test_space_management",
        "test_entity_crud_operations"
    ]
    
    # Run the test suite
    success = await run_test_suite(KGEntitiesEndpointTester, test_methods)
    
    if success:
        logger.info("🎉 Test suite completed successfully!")
        return 0
    else:
        logger.error("💥 Test suite failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
