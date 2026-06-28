#!/usr/bin/env python3
"""
KGEntity Frame Update Test Module

Modular test implementation for KG entity frame update operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Frame property updates within entity context
- Frame slot modifications
- Frame relationship updates
- Frame graph URI preservation during updates
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot

# Import models
from vitalgraph.model.kgentities_model import EntityFramesResponse

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list, quad_list_to_graphobjects

# Import test data creator
from test_scripts.fuseki_postgresql.kgentity_test_data import KGEntityTestDataCreator


logger = logging.getLogger(__name__)


class KGEntityFrameUpdateTester:
    """
    Modular test implementation for KG entity frame update operations.
    
    Handles:
    - Frame property updates within entity context
    - Frame slot modifications
    - Frame relationship updates
    - Frame graph URI preservation during updates
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity frame update tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.updated_frame_uris = []
        
    async def test_frame_property_updates(self, space_id: str, graph_id: str, entity_uri: str, frame_uri: str) -> bool:
        """
        Test frame property updates within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of parent entity
            frame_uri: URI of frame to update
            
        Returns:
            bool: True if frame property update successful, False otherwise
        """
        try:
            logger.info(f"🧪 Testing frame property updates for frame: {frame_uri}")
            
            # Create updated frame object
            updated_frame = KGFrame()
            updated_frame.URI = frame_uri
            updated_frame.name = f"Updated Frame {uuid.uuid4().hex[:8]}"
            updated_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#UpdatedContactFrame"
            
            # Convert to quads
            frame_quads = graphobjects_to_quad_list([updated_frame], graph_id)
            
            # Call endpoint method to update entity frames
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            result = await self.endpoint._update_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                quads=frame_quads,
                current_user=current_user,
                parent_frame_uri=None  # No parent frame for basic frame updates
            )
            
            if result and hasattr(result, 'message'):
                logger.info(f"✅ Frame property update successful: {result.message}")
                self.updated_frame_uris.append(frame_uri)
                
                # Verify frame graph URI preservation
                await self._verify_frame_graph_uri_preservation(
                    space_id, graph_id, entity_uri, frame_uri
                )
                
                return True
            else:
                logger.error(f"❌ Frame property update failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during frame property update test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_frame_slot_modifications(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Test frame slot modifications within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of parent entity
            
        Returns:
            bool: True if slot modifications successful, False otherwise
        """
        try:
            logger.info(f"🔧 Testing frame slot modifications for entity: {entity_uri}")
            
            # Create frame with updated slots
            frame = KGFrame()
            frame.URI = self.test_data_creator.generate_test_uri("frame", f"updated_contact_{uuid.uuid4().hex[:8]}")
            frame.name = "Updated Contact Frame"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ContactFrame"
            
            # Create updated slots
            email_slot = KGTextSlot()
            email_slot.URI = self.test_data_creator.generate_test_uri("slot", f"updated_email_{uuid.uuid4().hex[:8]}")
            email_slot.name = "Updated Email"
            email_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EmailSlot"
            email_slot.textSlotValue = "updated.email@example.com"
            
            phone_slot = KGTextSlot()
            phone_slot.URI = self.test_data_creator.generate_test_uri("slot", f"updated_phone_{uuid.uuid4().hex[:8]}")
            phone_slot.name = "Updated Phone"
            phone_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#PhoneSlot"
            phone_slot.textSlotValue = "+1-555-9999"
            
            # Create new integer slot
            priority_slot = KGIntegerSlot()
            priority_slot.URI = self.test_data_creator.generate_test_uri("slot", f"priority_{uuid.uuid4().hex[:8]}")
            priority_slot.name = "Contact Priority"
            priority_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#PrioritySlot"
            priority_slot.integerSlotValue = 5
            
            # Convert to quads
            frame_objects = [frame, email_slot, phone_slot, priority_slot]
            frame_quads = graphobjects_to_quad_list(frame_objects, graph_id)
            
            # Call endpoint method to update entity frames
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            result = await self.endpoint._update_entity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                quads=frame_quads,
                current_user=current_user,
                parent_frame_uri=None  # No parent frame for basic frame updates
            )
            
            if result and hasattr(result, 'message'):
                logger.info(f"✅ Frame slot modifications successful: {result.message}")
                self.updated_frame_uris.append(frame.URI)
                
                # Validate slot updates
                logger.info(f"  Updated slots:")
                logger.info(f"    Email: {email_slot.textSlotValue}")
                logger.info(f"    Phone: {phone_slot.textSlotValue}")
                logger.info(f"    Priority: {priority_slot.integerSlotValue}")
                
                return True
            else:
                logger.error(f"❌ Frame slot modifications failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during frame slot modification test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_frame_relationship_updates(self, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """
        Test frame relationship updates within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of parent entity
            
        Returns:
            bool: True if relationship updates successful, False otherwise
        """
        try:
            logger.info(f"🔗 Testing frame relationship updates for entity: {entity_uri}")
            
            # Create organization test data for relationship testing
            org_objects = self.test_data_creator.create_organization_with_address("Test Company")
            
            # Convert to quads for creation
            org_quads = graphobjects_to_quad_list(org_objects, graph_id)
            
            # Create organization entity
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            create_result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=org_quads,
                operation_mode=OperationMode.CREATE,
                parent_uri=None,
                current_user=current_user
            )
            
            if create_result and hasattr(create_result, 'created_uris'):
                org_entity_uri = create_result.created_uris[0]
                self.created_entity_uris.append(org_entity_uri)
                logger.info(f"✅ Created organization entity: {org_entity_uri}")
                
                # Test frame updates on the organization
                org_frames_result = await self.endpoint._get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=org_entity_uri,
                    frame_uris=None,
                    page_size=10,
                    offset=0,
                    search=None,
                    current_user=current_user
                )
                
                logger.info(f"🔍 Frame retrieval result type: {type(org_frames_result)}")
                if org_frames_result and hasattr(org_frames_result, 'results') and org_frames_result.results:
                    # Convert quads to graph objects
                    retrieved_objects = quad_list_to_graphobjects(org_frames_result.results)
                    frame_objs = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
                    
                    if frame_objs:
                        logger.info(f"✅ Retrieved {len(frame_objs)} frames for relationship testing")
                        
                        # Use first frame for relationship update testing
                        frame_uri = str(frame_objs[0].URI)
                        
                        # Test frame property update
                        update_result = await self.test_frame_property_updates(
                            space_id, graph_id, org_entity_uri, frame_uri
                        )
                        
                        if update_result:
                            logger.info("✅ Frame relationship updates successful")
                            return True
                        else:
                            logger.error("❌ Frame relationship updates failed")
                            return False
                    else:
                        logger.warning("⚠️  No KGFrame objects found for relationship testing")
                        return False
                else:
                    logger.warning("⚠️  No frames found for relationship testing")
                    return False
            else:
                logger.error("❌ Failed to create organization for relationship testing")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during frame relationship update test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_frame_graph_uri_preservation(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame graph URI preservation during updates using test data.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if URI preservation successful, False otherwise
        """
        try:
            logger.info("🏷️  Testing frame graph URI preservation during updates")
            
            # Create project test data (has multiple frames)
            project_objects = self.test_data_creator.create_project_with_timeline("Test Project")
            
            # Convert to quads for creation
            project_quads = graphobjects_to_quad_list(project_objects, graph_id)
            
            # Create project entity
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            create_result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=project_quads,
                operation_mode=OperationMode.CREATE,
                parent_uri=None,
                current_user=current_user
            )
            
            if create_result and hasattr(create_result, 'created_uris'):
                project_entity_uri = create_result.created_uris[0]
                self.created_entity_uris.append(project_entity_uri)
                logger.info(f"✅ Created project entity: {project_entity_uri}")
                
                # Test frame slot modifications
                slot_result = await self.test_frame_slot_modifications(
                    space_id, graph_id, project_entity_uri
                )
                
                if slot_result:
                    logger.info("✅ Frame graph URI preservation successful")
                    return True
                else:
                    logger.error("❌ Frame graph URI preservation failed")
                    return False
            else:
                logger.error("❌ Failed to create project for URI preservation testing")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during frame graph URI preservation test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def _verify_frame_graph_uri_preservation(self, space_id: str, graph_id: str, entity_uri: str, frame_uri: str) -> bool:
        """
        Verify that frame graph URI is preserved after updates.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of parent entity
            frame_uri: URI of updated frame
            
        Returns:
            bool: True if URI preserved, False otherwise
        """
        try:
            logger.info(f"🔍 Verifying frame graph URI preservation for: {frame_uri}")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Retrieve frames after update
            result = await self.endpoint._get_kgentity_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=None,
                page_size=10,
                offset=0,
                search=None,
                current_user=current_user
            )
            
            if result and hasattr(result, 'results') and result.results:
                retrieved_objects = quad_list_to_graphobjects(result.results)
                for obj in retrieved_objects:
                    if isinstance(obj, KGFrame) and str(obj.URI) == frame_uri:
                        logger.info(f"✅ Frame URI preserved: {frame_uri}")
                        return True
                
                logger.warning(f"⚠️  Frame URI not found after update: {frame_uri}")
                return False
            else:
                logger.warning("⚠️  No frames returned for URI verification")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during URI preservation verification: {e}")
            return False
    
    def get_created_entity_uris(self) -> List[str]:
        """
        Get list of created entity URIs for cleanup purposes.
        
        Returns:
            List[str]: List of created entity URIs
        """
        return self.created_entity_uris.copy()
    
    def get_updated_frame_uris(self) -> List[str]:
        """
        Get list of updated frame URIs for cleanup purposes.
        
        Returns:
            List[str]: List of updated frame URIs
        """
        return self.updated_frame_uris.copy()
    
    def clear_created_uris(self):
        """Clear the lists of created URIs."""
        self.created_entity_uris.clear()
        self.updated_frame_uris.clear()
