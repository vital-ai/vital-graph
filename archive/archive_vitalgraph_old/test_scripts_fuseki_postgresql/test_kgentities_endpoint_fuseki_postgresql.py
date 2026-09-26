#!/usr/bin/env python3
"""
Comprehensive KGEntities Endpoint Test for Fuseki+PostgreSQL Backend

Tests the KGEntities endpoint with proper endpoint method calls following the established pattern:
- Create test space
- Insert KG entities via VitalSigns quad documents
- List KG entities (empty and populated states)
- Get individual KG entities by URI
- Update KG entity properties
- Delete specific KG entities
- Test KG frames within entity context
- Validate dual-write consistency between Fuseki and PostgreSQL
- Clean up test space

Architecture: test → endpoint → backend → database
VitalSigns Integration: KGEntity objects ↔ quads ↔ endpoint

Uses modular test implementations from test_script_kg_impl/ package.
"""

import asyncio
import sys
import logging
import uuid
from typing import Dict, Any, List, Optional

# Import test framework
from test_fuseki_postgresql_endpoint_utils import FusekiPostgreSQLEndpointTester

# Import endpoint and models
from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
from vitalgraph.model.kgentities_model import (
    EntitiesResponse,
    EntityCreateResponse,
    EntityUpdateResponse,
    EntityDeleteResponse,
    EntityQueryRequest,
    EntityQueryResponse
)
from vitalgraph.model.spaces_model import Space

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame

# Import modular test implementations
sys.path.append('/Users/hadfield/Local/vital-git/vital-graph/test_script_kg_impl')
from kgentities.case_entity_insert import KGEntityInsertTester
from kgentities.case_entity_get import KGEntityGetTester
from kgentities.case_entity_list import KGEntityListTester
from kgentities.case_entity_update import KGEntityUpdateTester
from kgentities.case_entity_delete import KGEntityDeleteTester
from kgentities.case_entity_frame_create import KGEntityFrameCreateTester
from kgentities.case_entity_frame_get import KGEntityFrameGetTester
from kgentities.case_entity_frame_update import KGEntityFrameUpdateTester
from kgentities.case_entity_frame_delete import KGEntityFrameDeleteTester
from kgentities.case_entity_query import KGEntityQueryTester
from kgentities.case_entity_frame_hierarchical import KGEntityHierarchicalFrameTester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KGEntitiesEndpointFusekiPostgreSQLTester(FusekiPostgreSQLEndpointTester):
    """
    Comprehensive test suite for KGEntities Endpoint with Fuseki+PostgreSQL backend.
    
    Tests all KGEntities operations using modular test implementations:
    - Entity insertion (Phase 1)
    - Entity retrieval operations (Future)
    - Entity deletion operations (Future)
    - Frame operations within entity context (Future)
    - Advanced entity querying (Future)
    """
    
    def __init__(self):
        super().__init__()
        self.endpoint = None
        self.test_space_id = None
        self.test_graph_id = None
        self.created_entity_uris = []
        
        # Initialize VitalSigns
        self.vitalsigns = VitalSigns()
        
        # Initialize modular test implementations
        self.entity_insert_tester = None
        self.entity_get_tester = None
        self.entity_list_tester = None
        self.entity_update_tester = None
        self.entity_delete_tester = None
        self.entity_frame_create_tester = None
        self.entity_frame_get_tester = None
        self.entity_frame_update_tester = None
        self.entity_frame_delete_tester = None
        self.entity_query_tester = None
        self.entity_frame_hierarchical_tester = None
        
    async def setup_hybrid_backend(self) -> bool:
        """Setup hybrid backend and KGEntities endpoint."""
        success = await super().setup_hybrid_backend()
        if not success:
            return False
        
        try:
            # Create mock auth dependency for testing
            def mock_auth_dependency():
                return {"username": "test_user", "user_id": "test_user_123"}
            
            # Initialize KGEntities endpoint (without REST setup for direct method access)
            self.endpoint = KGEntitiesEndpoint.__new__(KGEntitiesEndpoint)
            self.endpoint.space_manager = self.space_manager
            self.endpoint.logger = logging.getLogger("test_kgentities")
            
            # Initialize VitalSigns components (from endpoint __init__)
            from vitalgraph.sparql.grouping_uri_queries import GroupingURIQueryBuilder, GroupingURIGraphRetriever
            from vitalgraph.sparql.graph_validation import EntityGraphValidator
            
            self.endpoint.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
            self.endpoint.vital_prefix = "http://vital.ai/ontology/vital-core#"
            self.endpoint.grouping_uri_builder = GroupingURIQueryBuilder()
            self.endpoint.graph_retriever = GroupingURIGraphRetriever(self.endpoint.grouping_uri_builder)
            self.endpoint.entity_validator = EntityGraphValidator()
            self.endpoint.relations = None  # Placeholder until KGRelationsEndpoint is implemented
            
            # Initialize test data creator
            from kgentity_test_data import KGEntityTestDataCreator
            test_data_creator = KGEntityTestDataCreator()
            
            # Initialize modular test implementations with test data creator
            self.entity_insert_tester = KGEntityInsertTester(self.endpoint, test_data_creator)
            self.entity_get_tester = KGEntityGetTester(self.endpoint, test_data_creator)
            self.entity_list_tester = KGEntityListTester(self.endpoint, test_data_creator)
            self.entity_update_tester = KGEntityUpdateTester(self.endpoint, test_data_creator)
            self.entity_delete_tester = KGEntityDeleteTester(self.endpoint, test_data_creator)
            self.entity_frame_create_tester = KGEntityFrameCreateTester(self.endpoint, test_data_creator)
            self.entity_frame_get_tester = KGEntityFrameGetTester(self.endpoint, test_data_creator)
            self.entity_frame_update_tester = KGEntityFrameUpdateTester(self.endpoint, test_data_creator)
            self.entity_frame_delete_tester = KGEntityFrameDeleteTester(self.endpoint, test_data_creator)
            self.entity_query_tester = KGEntityQueryTester(self.endpoint, test_data_creator)
            self.entity_frame_hierarchical_tester = KGEntityHierarchicalFrameTester(self.endpoint, test_data_creator)
            
            logger.info("✅ KGEntities endpoint and test modules initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize KGEntities endpoint: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def create_test_space(self) -> bool:
        """Create test space for KGEntities testing."""
        try:
            # Generate unique space and graph IDs
            self.test_space_id = f"test_kgentities_space_{uuid.uuid4().hex[:8]}"
            # Graph ID must be a complete URI for fuseki-postgresql backend
            self.test_graph_id = f"http://vital.ai/graph/test_kgentities_graph_{uuid.uuid4().hex[:8]}"
            
            logger.info(f"🔧 Creating test space: {self.test_space_id}")
            logger.info(f"🔧 Using test graph: {self.test_graph_id}")
            
            # Create space using space manager (following KGTypes pattern)
            test_space = Space(
                space=self.test_space_id,
                space_name=f"KGEntities Test Space {self.test_space_id}",
                space_description="Test space for KGEntities endpoint testing",
                tenant="test_tenant"
            )
            
            # Use create_space_with_tables to ensure proper setup
            success = await self.space_manager.create_space_with_tables(
                space_id=self.test_space_id,
                space_name=test_space.space_name,
                space_description=test_space.space_description
            )
            if success:
                logger.info(f"✅ Test space created successfully: {self.test_space_id}")
                return True
            else:
                logger.error(f"❌ Failed to create test space: {self.test_space_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error creating test space: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_insert_tests(self) -> bool:
        """Run entity insertion tests using modular implementation."""
        try:
            logger.info("🧪 Running KG entity insertion tests...")
            
            # Create multiple entities for comprehensive testing (including deletion tests)
            entities_to_create = 3
            successful_inserts = 0
            
            for i in range(entities_to_create):
                logger.info(f"🔧 Creating entity {i+1}/{entities_to_create}")
                
                # Use modular test implementation
                success = await self.entity_insert_tester.test_single_entity_insert(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id
                )
                
                if success:
                    successful_inserts += 1
                    logger.info(f"✅ Entity {i+1} created successfully")
                else:
                    logger.error(f"❌ Entity {i+1} creation failed")
            
            if successful_inserts >= 2:  # Need at least 2 for deletion tests
                logger.info(f"✅ Entity insertion tests completed successfully ({successful_inserts}/{entities_to_create} entities created)")
                # Track created entities for cleanup and deletion tests
                self.created_entity_uris.extend(self.entity_insert_tester.get_created_entity_uris())
                return True
            else:
                logger.error(f"❌ Entity insertion tests failed - only {successful_inserts}/{entities_to_create} entities created")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity insertion tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_get_tests(self) -> bool:
        """Run entity retrieval tests using modular implementation."""
        try:
            logger.info("🧪 Running KG entity retrieval tests...")
            
            # Get the first created entity URI for testing
            if not self.created_entity_uris:
                logger.error("❌ No entities available for get tests")
                return False
            
            test_entity_uri = self.created_entity_uris[0]
            logger.info(f"🎯 Testing retrieval of entity: {test_entity_uri}")
            
            # Test single entity retrieval
            success1 = await self.entity_get_tester.test_single_entity_get(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test entity retrieval with complete graph
            success2 = await self.entity_get_tester.test_entity_get_with_graph(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test error handling for non-existent entity
            success3 = await self.entity_get_tester.test_entity_get_not_found(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            if success1 and success2 and success3:
                logger.info("✅ Entity retrieval tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity retrieval tests failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity retrieval tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_list_tests(self) -> bool:
        """Run populated entity listing tests using modular implementation."""
        try:
            logger.info("📋 Running populated KG entity listing tests...")
            
            # Test populated listing (empty test is handled separately before entity creation)
            if self.created_entity_uris:
                success1 = await self.entity_list_tester.test_list_entities_populated(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id,
                    expected_count=len(self.created_entity_uris)
                )
                
                success2 = await self.entity_list_tester.test_list_entities_with_pagination(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id
                )
                
                success3 = await self.entity_list_tester.test_list_entities_with_search(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id,
                    search_term="Test"
                )
                
                if success1 and success2 and success3:
                    logger.info("✅ Populated entity listing tests completed successfully")
                    return True
                else:
                    logger.error("❌ Some populated entity listing tests failed")
                    return False
            else:
                logger.error("❌ No entities available for populated listing tests")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during populated entity listing tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_update_tests(self) -> bool:
        """Run entity update tests using modular implementation."""
        try:
            logger.info("🔄 Running KG entity update tests...")
            
            if not self.created_entity_uris:
                logger.error("❌ No entities available for update tests")
                return False
            
            # Test single entity update
            success1 = await self.entity_update_tester.test_single_entity_update(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=self.created_entity_uris[0]
            )
            
            # Test batch entity update (if we have multiple entities)
            if len(self.created_entity_uris) > 1:
                success2 = await self.entity_update_tester.test_batch_entity_update(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id,
                    entity_uris=self.created_entity_uris[:2]
                )
            else:
                success2 = True  # Skip if not enough entities
            
            # Test update non-existent entity
            success3 = await self.entity_update_tester.test_update_nonexistent_entity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test UPSERT operation
            success4 = await self.entity_update_tester.test_upsert_entity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=self.created_entity_uris[0] if self.created_entity_uris else "urn:test:upsert"
            )
            
            if success1 and success2 and success3 and success4:
                logger.info("✅ Entity update tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity update tests failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity update tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_delete_tests(self) -> bool:
        """Run entity deletion tests using modular implementation."""
        try:
            logger.info("🗑️ Running KG entity deletion tests...")
            
            if not self.created_entity_uris or len(self.created_entity_uris) < 2:
                logger.error("❌ Need at least 2 entities for deletion tests")
                return False
            
            # Test single entity deletion
            entity_to_delete = self.created_entity_uris[-1]
            success1 = await self.entity_delete_tester.test_single_entity_delete(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=entity_to_delete
            )
            
            if success1:
                self.created_entity_uris.remove(entity_to_delete)
            
            # Test entity graph deletion (if we have more entities)
            if len(self.created_entity_uris) > 1:
                entity_graph_to_delete = self.created_entity_uris[-1]
                success2 = await self.entity_delete_tester.test_entity_graph_delete(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id,
                    entity_uri=entity_graph_to_delete
                )
                
                if success2:
                    self.created_entity_uris.remove(entity_graph_to_delete)
            else:
                success2 = True  # Skip if not enough entities
            
            # Test batch deletion (if we have remaining entities)
            if len(self.created_entity_uris) > 1:
                entities_to_batch_delete = self.created_entity_uris[-2:]
                success3 = await self.entity_delete_tester.test_batch_entity_delete(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id,
                    entity_uris=entities_to_batch_delete
                )
                
                if success3:
                    for uri in entities_to_batch_delete:
                        if uri in self.created_entity_uris:
                            self.created_entity_uris.remove(uri)
            else:
                success3 = True  # Skip if not enough entities
            
            # Test delete non-existent entity
            success4 = await self.entity_delete_tester.test_delete_nonexistent_entity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            if success1 and success2 and success3 and success4:
                logger.info("✅ Entity deletion tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity deletion tests failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity deletion tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_frame_create_tests(self) -> bool:
        """Run entity frame creation tests using modular implementation."""
        try:
            logger.info("🧪 Running KG entity frame creation tests...")
            
            # Get the first created entity URI for frame testing
            if not self.created_entity_uris:
                logger.error("❌ No entities available for frame creation tests")
                return False
            
            test_entity_uri = self.created_entity_uris[0]
            logger.info(f"🎯 Testing frame creation for entity: {test_entity_uri}")
            
            # Test frame creation with processor
            success1 = await self.entity_frame_create_tester.test_frame_creation_with_processor(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test dual grouping URI assignment
            success2 = await self.entity_frame_create_tester.test_dual_grouping_uri_assignment(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test edge relationship creation
            success3 = await self.entity_frame_create_tester.test_edge_relationship_creation(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test concrete slot types
            success4 = await self.entity_frame_create_tester.test_concrete_slot_types(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test frame graph retrieval (Phase E1)
            success5 = await self.entity_frame_create_tester.test_frame_graph_retrieval(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test entity graph retrieval with frames (Phase E2)
            success6 = await self.entity_frame_create_tester.test_entity_graph_with_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Phase 1.5: Frame Deletion Tests (requires frame creation to be working)
            logger.info("🧪 Phase 1.5: Running frame deletion tests...")
            
            success7 = await self.entity_frame_create_tester.test_frame_deletion_basic(self.test_space_id, self.test_graph_id, test_entity_uri)
            success8 = await self.entity_frame_create_tester.test_frame_deletion_with_security_validation(self.test_space_id, self.test_graph_id, test_entity_uri)
            success9 = await self.entity_frame_create_tester.test_frame_deletion_complete_graph(self.test_space_id, self.test_graph_id, test_entity_uri)
            
            if success1 and success2 and success3 and success4 and success5 and success6 and success7 and success8 and success9:
                logger.info("✅ Entity frame creation and deletion tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity frame tests failed")
                logger.error(f"   - Frame creation: {'✅' if success1 else '❌'}")
                logger.error(f"   - Grouping URIs: {'✅' if success2 else '❌'}")
                logger.error(f"   - Edge relationships: {'✅' if success3 else '❌'}")
                logger.error(f"   - Concrete slot types: {'✅' if success4 else '❌'}")
                logger.error(f"   - Frame graph retrieval: {'✅' if success5 else '❌'}")
                logger.error(f"   - Entity graph with frames: {'✅' if success6 else '❌'}")
                logger.error(f"   - Basic frame deletion: {'✅' if success7 else '❌'}")
                logger.error(f"   - Security validation deletion: {'✅' if success8 else '❌'}")
                logger.error(f"   - Complete graph deletion: {'✅' if success9 else '❌'}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity frame creation tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    
    async def cleanup_test_space(self) -> bool:
        """Clean up test space and all created entities."""
        try:
            logger.info(f"🧹 Cleaning up test space: {self.test_space_id}")
            
            if self.test_space_id and self.space_manager:
                success = await self.space_manager.delete_space_with_tables(self.test_space_id)
                if success:
                    logger.info(f"✅ Test space deleted successfully: {self.test_space_id}")
                    return True
                else:
                    logger.error(f"❌ Failed to delete test space: {self.test_space_id}")
                    return False
            else:
                logger.warning("⚠️ No test space to clean up")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_frame_get_tests(self) -> bool:
        """Run entity frame get tests using modular implementation."""
        try:
            logger.info("🧪 Running KG entity frame get tests...")
            
            # Get the first created entity URI for frame testing
            if not self.created_entity_uris:
                logger.error("❌ No entities available for frame get tests")
                return False
            
            test_entity_uri = self.created_entity_uris[0]
            logger.info(f"🎯 Testing frame retrieval for entity: {test_entity_uri}")
            
            # Test frame retrieval for entity
            success1 = await self.entity_frame_get_tester.test_frame_retrieval_for_entity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test frame graph with security validation
            success2 = await self.entity_frame_get_tester.test_frame_graph_with_security_validation(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test complete entity graph with frames
            success3 = await self.entity_frame_get_tester.test_complete_entity_graph_with_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test grouping URI validation
            success4 = await self.entity_frame_get_tester.test_grouping_uri_validation(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            if success1 and success2 and success3 and success4:
                logger.info("✅ Entity frame get tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity frame get tests failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity frame get tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_frame_update_tests(self) -> bool:
        """Run entity frame update tests using modular implementation."""
        try:
            logger.info("🧪 Running KG entity frame update tests...")
            
            # Get the first created entity URI for frame testing
            if not self.created_entity_uris:
                logger.error("❌ No entities available for frame update tests")
                return False
            
            test_entity_uri = self.created_entity_uris[0]
            logger.info(f"🎯 Testing frame updates for entity: {test_entity_uri}")
            
            # Test frame slot modifications
            success1 = await self.entity_frame_update_tester.test_frame_slot_modifications(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test frame relationship updates
            success2 = await self.entity_frame_update_tester.test_frame_relationship_updates(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=test_entity_uri
            )
            
            # Test frame graph URI preservation
            success3 = await self.entity_frame_update_tester.test_frame_graph_uri_preservation(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            if success1 and success2 and success3:
                logger.info("✅ Entity frame update tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity frame update tests failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity frame update tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_hierarchical_frame_tests(self) -> bool:
        """Run hierarchical frame tests using modular implementation."""
        try:
            logger.info("🧪 Running hierarchical frame tests...")
            
            # Create organization entity with hierarchical frames for testing
            logger.info("📋 Creating organization with hierarchical frame structure...")
            
            # Create organization with Management → CEO/CTO/CFO hierarchy
            org_objects = self.entity_frame_hierarchical_tester.test_data_creator.create_organization_with_address("Hierarchical Test Corp")
            
            # Debug: Log what objects are being created
            logger.info(f"🔍 DEBUG: Created {len(org_objects)} objects for hierarchical test")
            frame_count = 0
            for obj in org_objects:
                if hasattr(obj, '__class__') and 'Frame' in obj.__class__.__name__:
                    frame_count += 1
                    logger.info(f"🔍 DEBUG: Frame {frame_count}: {obj.__class__.__name__} - {getattr(obj, 'URI', 'No URI')} - {getattr(obj, 'kGFrameType', 'No Type')}")
            
            # Extract entity URI
            org_entity = None
            for obj in org_objects:
                if hasattr(obj, '__class__') and obj.__class__.__name__ == 'KGEntity':
                    org_entity = obj
                    break
            
            if not org_entity:
                logger.error("❌ Failed to create organization entity for hierarchical testing")
                return False
            
            entity_uri = org_entity.URI
            logger.info(f"🎯 Testing hierarchical frames for entity: {entity_uri}")
            
            # Insert the organization with hierarchical structure
            # Insert entity with hierarchical frames - pass GraphObjects directly
            insert_result = await self.endpoint._create_or_update_entities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                objects=org_objects,
                operation_mode="create",
                parent_uri=None,
                current_user={"username": "test_user", "user_id": "test_123"}
            )
            
            if not (hasattr(insert_result, 'message') and 'success' in insert_result.message.lower()):
                logger.error(f"❌ Failed to insert hierarchical test entity: {insert_result}")
                return False
            
            # Track created entity
            self.created_entity_uris.append(entity_uri)
            
            # Test 1: Add child frame to existing parent frame
            success1 = await self.entity_frame_hierarchical_tester.test_add_child_frame_to_parent(
                entity_uri=entity_uri,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test 2: Update parent-child frame relationships
            success2 = await self.entity_frame_hierarchical_tester.test_update_parent_child_relationships(
                entity_uri=entity_uri,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test 3: Hierarchical frame discovery
            success3 = await self.entity_frame_hierarchical_tester.test_hierarchical_frame_discovery(
                entity_uri=entity_uri,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test 4: Multi-level frame hierarchy
            success4 = await self.entity_frame_hierarchical_tester.test_multi_level_frame_hierarchy(
                entity_uri=entity_uri,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test 5: Frame addition process requirements
            success5 = await self.entity_frame_hierarchical_tester.test_frame_addition_process_requirements(
                entity_uri=entity_uri,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test 6: Error conditions
            success6 = await self.entity_frame_hierarchical_tester.test_error_conditions(
                entity_uri=entity_uri,
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Evaluate results
            all_tests = [success1, success2, success3, success4, success5, success6]
            passed_tests = sum(all_tests)
            
            if all(all_tests):
                logger.info("✅ All hierarchical frame tests completed successfully")
                logger.info(f"📊 Test Results: {passed_tests}/6 tests passed")
                logger.info("🎯 Hierarchical frame functionality validated:")
                logger.info("   • Child frame addition with parent_frame_uri")
                logger.info("   • Parent-child relationship updates")
                logger.info("   • Hierarchical frame discovery via SPARQL")
                logger.info("   • Multi-level frame hierarchies")
                logger.info("   • Process requirements validation")
                logger.info("   • Error condition handling")
                return True
            else:
                logger.error(f"❌ Some hierarchical frame tests failed: {passed_tests}/6 tests passed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during hierarchical frame tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_frame_delete_tests(self) -> bool:
        """Run entity frame delete tests using modular implementation."""
        try:
            logger.info("🧪 Running KG entity frame delete tests...")
            
            # Test basic frame deletion
            success1 = await self.entity_frame_delete_tester.test_basic_frame_deletion(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test frame deletion with security validation
            success2 = await self.entity_frame_delete_tester.test_frame_deletion_with_security_validation(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test complete frame graph deletion
            success3 = await self.entity_frame_delete_tester.test_complete_frame_graph_deletion(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test edge relationship cleanup
            success4 = await self.entity_frame_delete_tester.test_edge_relationship_cleanup(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            if success1 and success2 and success3 and success4:
                logger.info("✅ Entity frame delete tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity frame delete tests failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity frame delete tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_entity_query_tests(self) -> bool:
        """Run entity query tests using modular implementation."""
        try:
            logger.info("🧪 Running KG entity query tests...")
            
            # Test criteria-based entity queries
            success1 = await self.entity_query_tester.test_criteria_based_entity_queries(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test SPARQL query generation and execution
            success2 = await self.entity_query_tester.test_sparql_query_generation_and_execution(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test query result processing and pagination
            success3 = await self.entity_query_tester.test_query_result_processing_and_pagination(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test entity graph URI filtering
            success4 = await self.entity_query_tester.test_entity_graph_uri_filtering(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            # Test complex entity structure queries
            success5 = await self.entity_query_tester.test_complex_entity_structure_queries(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            if success1 and success2 and success3 and success4 and success5:
                logger.info("✅ Entity query tests completed successfully")
                return True
            else:
                logger.error("❌ Some entity query tests failed")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during entity query tests: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def run_comprehensive_tests(self) -> bool:
        """
        Run comprehensive KGEntities endpoint tests.
        
        Phase 1: Basic entity insertion and space management
        Future phases will add retrieval, deletion, frames, querying
        """
        logger.info("🚀 Starting KGEntities comprehensive tests")
        logger.info("📋 Phase 1: Basic entity insertion and space management")
        
        try:
            # Phase 1.1: Create test space
            logger.info("\n" + "="*60)
            logger.info("Phase 1.1: Creating test space")
            logger.info("="*60)
            
            if not await self.create_test_space():
                logger.error("❌ Test space creation failed")
                return False
            
            # Phase 1.2: Test empty listing (before any entities are created)
            logger.info("\n" + "="*60)
            logger.info("Phase 1.2: Testing empty entity listing")
            logger.info("="*60)
            
            success_empty = await self.entity_list_tester.test_list_entities_empty(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            if not success_empty:
                logger.error("❌ Empty entity listing test failed")
                return False
            
            # Phase 1.3: Run entity insertion tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.3: Running entity insertion tests")
            logger.info("="*60)
            
            if not await self.run_entity_insert_tests():
                logger.error("❌ Entity insertion tests failed")
                return False
            
            # Phase 1.4: Run entity retrieval tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.4: Running entity retrieval tests")
            logger.info("="*60)
            
            if not await self.run_entity_get_tests():
                logger.error("❌ Entity retrieval tests failed")
                return False
            
            # Phase 1.5: Run populated entity listing tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.5: Running populated entity listing tests")
            logger.info("="*60)
            
            if not await self.run_entity_list_tests():
                logger.error("❌ Entity listing tests failed")
                return False
            
            # Phase 1.6: Run entity update tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.6: Running entity update tests")
            logger.info("="*60)
            
            if not await self.run_entity_update_tests():
                logger.error("❌ Entity update tests failed")
                return False
            
            # Phase 1.7: Run entity frame creation tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.7: Running entity frame creation tests")
            logger.info("="*60)
            
            if not await self.run_entity_frame_create_tests():
                logger.error("❌ Entity frame creation tests failed")
                return False
            
            # Phase 1.8: Run entity frame get tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.8: Running entity frame get tests")
            logger.info("="*60)
            
            if not await self.run_entity_frame_get_tests():
                logger.error("❌ Entity frame get tests failed")
                return False
            
            # Phase 1.9: Run entity frame update tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.9: Running entity frame update tests")
            logger.info("="*60)
            
            if not await self.run_entity_frame_update_tests():
                logger.error("❌ Entity frame update tests failed")
                return False
            
            # Phase 1.10: Run hierarchical frame tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.10: Running hierarchical frame tests")
            logger.info("="*60)
            
            if not await self.run_hierarchical_frame_tests():
                logger.error("❌ Hierarchical frame tests failed")
                return False
            
            # Phase 1.11: Run entity frame delete tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.11: Running entity frame delete tests")
            logger.info("="*60)
            
            if not await self.run_entity_frame_delete_tests():
                logger.error("❌ Entity frame delete tests failed")
                return False
            
            # Phase 1.12: Run entity query tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.12: Running entity query tests")
            logger.info("="*60)
            
            if not await self.run_entity_query_tests():
                logger.error("❌ Entity query tests failed")
                return False
            
            # Phase 1.13: Run entity deletion tests
            logger.info("\n" + "="*60)
            logger.info("Phase 1.13: Running entity deletion tests")
            logger.info("="*60)
            
            if not await self.run_entity_delete_tests():
                logger.error("❌ Entity deletion tests failed")
                return False
            
            # Phase 1.14: Cleanup (always attempt cleanup)
            logger.info("\n" + "="*60)
            logger.info("Phase 1.14: Cleaning up test space")
            logger.info("="*60)
            
            cleanup_success = await self.cleanup_test_space()
            if not cleanup_success:
                logger.warning("⚠️ Cleanup had issues, but tests completed")
            
            logger.info("\n" + "="*60)
            logger.info("✅ KGEntities comprehensive tests completed successfully!")
            logger.info("📊 Complete CRUD Cycle Results:")
            logger.info(f"   - Space creation: ✅ Success")
            logger.info(f"   - Entity creation (CREATE): ✅ Success")
            logger.info(f"   - Entity retrieval (READ): ✅ Success")
            logger.info(f"   - Frame creation (CREATE): ✅ Success")
            logger.info(f"   - Entity updates (UPDATE): ✅ Success")
            logger.info(f"   - Entity deletion (DELETE): ✅ Success")
            logger.info(f"   - Space cleanup: {'✅ Success' if cleanup_success else '⚠️ Issues'}")
            logger.info("🎯 Full CRUD cycle with enhanced KGFrames endpoint validated!")
            logger.info("🔧 Frame functionality includes:")
            logger.info("   • Frame creation: edge relationships, grouping URIs, concrete slot types")
            logger.info("   • Frame graph retrieval: specific frame URIs with two-phase SPARQL security")
            logger.info("   • Entity graph validation: complete frame-entity relationship verification")
            logger.info("="*60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Comprehensive tests failed with exception: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Always attempt cleanup on failure
            try:
                await self.cleanup_test_space()
            except:
                pass
            
            return False


async def main():
    """Main test execution function."""
    logger.info("🎯 KGEntities Endpoint Test - Fuseki+PostgreSQL Backend")
    logger.info("📋 Comprehensive test suite with modular implementations")
    
    tester = KGEntitiesEndpointFusekiPostgreSQLTester()
    
    try:
        # Setup hybrid backend
        logger.info("\n" + "="*60)
        logger.info("Setting up Fuseki+PostgreSQL hybrid backend")
        logger.info("="*60)
        
        if not await tester.setup_hybrid_backend():
            logger.error("❌ Backend setup failed")
            return False
        
        # Run comprehensive tests
        success = await tester.run_comprehensive_tests()
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Test execution failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False
    
    finally:
        # Cleanup backend
        try:
            await tester.cleanup_resources()
        except Exception as e:
            logger.error(f"⚠️ Backend cleanup error: {e}")


if __name__ == "__main__":
    # Run the test
    success = asyncio.run(main())
    
    if success:
        logger.info("🎉 All tests completed successfully!")
        sys.exit(0)
    else:
        logger.error("💥 Tests failed!")
        sys.exit(1)
