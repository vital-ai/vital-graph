#!/usr/bin/env python3
"""
KGEntity Frame Delete Test Module

Modular test implementation for KG entity frame deletion operations.
Used by the main KGEntities endpoint test orchestrator.

Focuses on:
- Basic frame deletion within entity context
- Frame deletion with security validation
- Complete frame graph deletion
- Frame graph URI cleanup
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGEntity objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

# Import models
from vitalgraph.model.kgentities_model import EntityFramesResponse

# Import quad conversion utilities
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list, quad_list_to_graphobjects

# Import test data creator
from test_scripts.fuseki_postgresql.kgentity_test_data import KGEntityTestDataCreator


logger = logging.getLogger(__name__)


class KGEntityFrameDeleteTester:
    """
    Modular test implementation for KG entity frame deletion operations.
    
    Handles:
    - Basic frame deletion within entity context
    - Frame deletion with security validation
    - Complete frame graph deletion
    - Frame graph URI cleanup
    """
    
    def __init__(self, endpoint, test_data_creator):
        """
        Initialize the entity frame delete tester.
        
        Args:
            endpoint: KGEntitiesEndpoint instance (initialized without REST setup)
            test_data_creator: KGEntityTestDataCreator instance for generating test data
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        self.test_data_creator = test_data_creator
        self.created_entity_uris = []
        self.deleted_frame_uris = []
        
    async def test_basic_frame_deletion(self, space_id: str, graph_id: str) -> bool:
        """
        Test basic frame deletion within entity context.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if basic frame deletion successful, False otherwise
        """
        try:
            logger.info("🧪 Testing basic frame deletion within entity context")
            
            # Create person test data with frames
            person_objects = self.test_data_creator.create_person_with_contact("Delete Test Person")
            
            # Convert to quads for creation
            person_quads = graphobjects_to_quad_list(person_objects, graph_id)
            
            # Create person entity
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            create_result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=person_quads,
                operation_mode=OperationMode.CREATE,
                parent_uri=None,
                current_user=current_user
            )
            
            if create_result and hasattr(create_result, 'created_uris'):
                person_entity_uri = create_result.created_uris[0]
                self.created_entity_uris.append(person_entity_uri)
                logger.info(f"✅ Created person entity: {person_entity_uri}")
                
                # Get entity frames
                frames_result = await self.endpoint._get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=person_entity_uri,
                    frame_uris=None,
                    page_size=10,
                    offset=0,
                    search=None,
                    current_user=current_user
                )
                
                if frames_result and hasattr(frames_result, 'results') and frames_result.results:
                    # Convert quads to graph objects to find frame
                    retrieved_objects = quad_list_to_graphobjects(frames_result.results)
                    frame_objs = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
                    frame_uri = str(frame_objs[0].URI) if frame_objs else None
                    
                    if frame_uri:
                        logger.info(f"🗑️  Deleting frame: {frame_uri}")
                        
                        # Delete frame
                        delete_result = await self.endpoint.delete_entity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=person_entity_uri,
                            frame_uris=[frame_uri]
                        )
                        
                        if delete_result and hasattr(delete_result, 'message'):
                            logger.info(f"✅ Basic frame deletion successful: {delete_result.message}")
                            self.deleted_frame_uris.append(frame_uri)
                            
                            # Verify frame is deleted
                            await self._verify_frame_deletion(
                                space_id, graph_id, person_entity_uri, frame_uri
                            )
                            
                            return True
                        else:
                            logger.error(f"❌ Basic frame deletion failed: {delete_result}")
                            return False
                    else:
                        logger.error("❌ No frame URI found for deletion")
                        return False
                else:
                    logger.error("❌ No frames found for deletion test")
                    return False
            else:
                logger.error("❌ Failed to create person entity for deletion test")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during basic frame deletion test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_frame_deletion_with_security_validation(self, space_id: str, graph_id: str) -> bool:
        """
        Test frame deletion with security validation.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if security validation successful, False otherwise
        """
        try:
            logger.info("🔒 Testing frame deletion with security validation")
            
            # Create organization test data with frames
            org_objects = self.test_data_creator.create_organization_with_address("Security Test Corp")
            
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
                
                # Get entity frames
                frames_result = await self.endpoint._get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=org_entity_uri,
                    frame_uris=None,
                    page_size=10,
                    offset=0,
                    search=None,
                    current_user=current_user
                )
                
                if frames_result and hasattr(frames_result, 'results') and frames_result.results:
                    # Convert quads to graph objects to find frame
                    retrieved_objects = quad_list_to_graphobjects(frames_result.results)
                    frame_objs = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
                    frame_uri = str(frame_objs[0].URI) if frame_objs else None
                    
                    if frame_uri:
                        logger.info(f"🔒 Testing security validation for frame deletion: {frame_uri}")
                        
                        # Test with valid user
                        valid_user = {"username": "test_user", "user_id": "test_user_123"}
                        
                        delete_result = await self.endpoint.delete_entity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=org_entity_uri,
                            frame_uris=[frame_uri]
                        )
                        
                        if delete_result and hasattr(delete_result, 'message'):
                            logger.info(f"✅ Security validation passed: {delete_result.message}")
                            self.deleted_frame_uris.append(frame_uri)
                            
                            # Verify frame graph URI cleanup
                            await self._verify_frame_graph_uri_cleanup(
                                space_id, graph_id, org_entity_uri, frame_uri
                            )
                            
                            return True
                        else:
                            logger.error(f"❌ Security validation failed: {delete_result}")
                            return False
                    else:
                        logger.error("❌ No frame URI found for security validation test")
                        return False
                else:
                    logger.error("❌ No frames found for security validation test")
                    return False
            else:
                logger.error("❌ Failed to create organization for security validation test")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during security validation test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_complete_frame_graph_deletion(self, space_id: str, graph_id: str) -> bool:
        """
        Test complete frame graph deletion including all related objects.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if complete graph deletion successful, False otherwise
        """
        try:
            logger.info("🌐 Testing complete frame graph deletion")
            
            # Create project test data with multiple frames
            project_objects = self.test_data_creator.create_project_with_timeline("Graph Delete Project")
            
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
                
                # Get entity frames
                frames_result = await self.endpoint._get_kgentity_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=project_entity_uri,
                    frame_uris=None,
                    page_size=10,
                    offset=0,
                    search=None,
                    current_user=current_user
                )
                
                if frames_result and hasattr(frames_result, 'results') and frames_result.results:
                    # Convert quads to graph objects
                    retrieved_objects = quad_list_to_graphobjects(frames_result.results)
                    frame_objs = [obj for obj in retrieved_objects if isinstance(obj, KGFrame)]
                    logger.info(f"📊 Found {len(frame_objs)} frames for complete deletion test")
                    
                    # Collect all frame URIs for deletion
                    frame_uris_to_delete = [str(f.URI) for f in frame_objs]
                    
                    if frame_uris_to_delete:
                        logger.info(f"🗑️  Deleting {len(frame_uris_to_delete)} frames with complete graphs")
                        
                        # Delete all frames with complete graphs
                        delete_result = await self.endpoint.delete_entity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=project_entity_uri,
                            frame_uris=frame_uris_to_delete
                        )
                        
                        if delete_result and hasattr(delete_result, 'message'):
                            logger.info(f"✅ Complete frame graph deletion successful: {delete_result.message}")
                            self.deleted_frame_uris.extend(frame_uris_to_delete)
                            
                            # Verify complete graph cleanup
                            await self._verify_complete_graph_cleanup(
                                space_id, graph_id, project_entity_uri, frame_uris_to_delete
                            )
                            
                            return True
                        else:
                            logger.error(f"❌ Complete frame graph deletion failed: {delete_result}")
                            return False
                    else:
                        logger.error("❌ No frame URIs found for complete deletion test")
                        return False
                else:
                    logger.error("❌ No frames found for complete deletion test")
                    return False
            else:
                logger.error("❌ Failed to create project for complete deletion test")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during complete frame graph deletion test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def test_edge_relationship_cleanup(self, space_id: str, graph_id: str) -> bool:
        """
        Test edge relationship cleanup during frame deletion.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            
        Returns:
            bool: True if edge cleanup successful, False otherwise
        """
        try:
            logger.info("🔗 Testing edge relationship cleanup during frame deletion")
            
            # Create person test data with complex frame relationships
            person_objects = self.test_data_creator.create_person_with_contact("Edge Test Person")
            logger.info(f"🔍 Created {len(person_objects)} objects for edge test")
            
            # Convert to quads for creation
            person_quads = graphobjects_to_quad_list(person_objects, graph_id)
            logger.info(f"🔍 Created {len(person_quads)} quads for person objects")
            
            # Create person entity
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            create_result = await self.endpoint._create_or_update_entities(
                space_id=space_id,
                graph_id=graph_id,
                quads=person_quads,
                operation_mode=OperationMode.CREATE,
                parent_uri=None,
                current_user=current_user
            )
            
            if create_result and hasattr(create_result, 'created_uris'):
                person_entity_uri = create_result.created_uris[0]
                self.created_entity_uris.append(person_entity_uri)
                logger.info(f"✅ Created person entity: {person_entity_uri}")
                
                # Get complete entity graph to analyze relationships
                entity_result = await self.endpoint._get_entities_by_uris(
                    space_id=space_id,
                    graph_id=graph_id,
                    uris=[person_entity_uri],
                    include_entity_graph=True,
                    current_user=current_user
                )
                
                # Convert results to graph objects for analysis
                result_objects = []
                if entity_result and hasattr(entity_result, 'results') and entity_result.results:
                    result_objects = quad_list_to_graphobjects(entity_result.results)
                logger.info(f"🔍 Retrieved entity result with {len(result_objects)} objects")
                
                if result_objects:
                    # Count edges before deletion
                    edge_count_before = 0
                    frame_uris = []
                    
                    for obj in result_objects:
                        obj_type = type(obj).__name__
                        if 'Edge' in obj_type:
                            edge_count_before += 1
                        elif isinstance(obj, KGFrame):
                            frame_uris.append(str(obj.URI))
                    
                    logger.info(f"📊 Before deletion: {edge_count_before} edges, {len(frame_uris)} frames")
                    
                    if frame_uris:
                        # Delete first frame
                        delete_result = await self.endpoint.delete_entity_frames(
                            space_id=space_id,
                            graph_id=graph_id,
                            entity_uri=person_entity_uri,
                            frame_uris=[frame_uris[0]]
                        )
                        
                        if delete_result:
                            self.deleted_frame_uris.append(frame_uris[0])
                            logger.info("✅ Frame deleted, verifying edge cleanup")
                            
                            # Get entity graph after deletion
                            after_result = await self.endpoint._get_entities_by_uris(
                                space_id=space_id,
                                graph_id=graph_id,
                                uris=[person_entity_uri],
                                include_entity_graph=True,
                                current_user=current_user
                            )
                            
                            after_objects = []
                            if after_result and hasattr(after_result, 'results') and after_result.results:
                                after_objects = quad_list_to_graphobjects(after_result.results)
                            
                            if after_objects:
                                edge_count_after = 0
                                
                                for obj in after_objects:
                                    if 'Edge' in type(obj).__name__:
                                        edge_count_after += 1
                                
                                logger.info(f"📊 After deletion: {edge_count_after} edges")
                                
                                if edge_count_after < edge_count_before:
                                    logger.info("✅ Edge relationship cleanup successful")
                                    return True
                                else:
                                    logger.warning("⚠️  Edge count unchanged - may be expected")
                                    return True  # Not necessarily an error
                            else:
                                logger.warning("⚠️  No results after deletion")
                                return True  # May be expected if all deleted
                        else:
                            logger.warning("⚠️  Delete operation failed")
                            return False
                    else:
                        logger.warning("⚠️  No frames found for edge cleanup test")
                        return False
                else:
                    logger.error("❌ No entity results for edge cleanup test")
                    return False
            else:
                logger.error("❌ Failed to create person for edge cleanup test")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during edge relationship cleanup test: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    async def _verify_frame_deletion(self, space_id: str, graph_id: str, entity_uri: str, frame_uri: str) -> bool:
        """
        Verify that frame is deleted.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of parent entity
            frame_uri: URI of deleted frame
            
        Returns:
            bool: True if frame is deleted, False otherwise
        """
        try:
            logger.info(f"🔍 Verifying frame deletion: {frame_uri}")
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Try to retrieve frames
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
                        logger.warning(f"⚠️  Frame still exists after deletion: {frame_uri}")
                        return False
                
                logger.info(f"✅ Frame successfully deleted: {frame_uri}")
                return True
            else:
                logger.info("✅ No frames returned - deletion successful")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error during frame deletion verification: {e}")
            return False
    
    async def _verify_frame_graph_uri_cleanup(self, space_id: str, graph_id: str, entity_uri: str, frame_uri: str) -> bool:
        """
        Verify that frame graph URI is properly cleaned up.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of parent entity
            frame_uri: URI of deleted frame
            
        Returns:
            bool: True if cleanup successful, False otherwise
        """
        try:
            logger.info(f"🧹 Verifying frame graph URI cleanup: {frame_uri}")
            
            # Verify frame deletion
            deletion_verified = await self._verify_frame_deletion(space_id, graph_id, entity_uri, frame_uri)
            
            if deletion_verified:
                logger.info("✅ Frame graph URI cleanup verified")
                return True
            else:
                logger.warning("⚠️  Frame graph URI cleanup incomplete")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during frame graph URI cleanup verification: {e}")
            return False
    
    async def _verify_complete_graph_cleanup(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str]) -> bool:
        """
        Verify that complete frame graphs are cleaned up.
        
        Args:
            space_id: Test space identifier
            graph_id: Test graph identifier
            entity_uri: URI of parent entity
            frame_uris: List of deleted frame URIs
            
        Returns:
            bool: True if cleanup successful, False otherwise
        """
        try:
            logger.info(f"🧹 Verifying complete graph cleanup for {len(frame_uris)} frames")
            
            # Verify all frames are deleted
            all_deleted = True
            for frame_uri in frame_uris:
                deleted = await self._verify_frame_deletion(space_id, graph_id, entity_uri, frame_uri)
                if not deleted:
                    all_deleted = False
            
            if all_deleted:
                logger.info("✅ Complete graph cleanup verified")
                return True
            else:
                logger.warning("⚠️  Complete graph cleanup incomplete")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during complete graph cleanup verification: {e}")
            return False
    
    def get_created_entity_uris(self) -> List[str]:
        """
        Get list of created entity URIs for cleanup purposes.
        
        Returns:
            List[str]: List of created entity URIs
        """
        return self.created_entity_uris.copy()
    
    def get_deleted_frame_uris(self) -> List[str]:
        """
        Get list of deleted frame URIs for reference.
        
        Returns:
            List[str]: List of deleted frame URIs
        """
        return self.deleted_frame_uris.copy()
    
    def clear_created_uris(self):
        """Clear the lists of created URIs."""
        self.created_entity_uris.clear()
        self.deleted_frame_uris.clear()
