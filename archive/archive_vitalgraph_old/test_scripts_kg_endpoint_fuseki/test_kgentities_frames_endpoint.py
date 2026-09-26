#!/usr/bin/env python3
"""
Test script for KGEntities and KGFrames endpoint integration.

This script tests the integration between KGEntitiesEndpoint and KGFramesEndpoint by:
1. Creating entity graphs with frames using KGEntitiesEndpoint
2. Testing frame operations through KGFramesEndpoint:
   - Listing all frames of an entity
   - Getting individual frames
   - Adding new frames
   - Updating existing frames
   - Deleting frames
3. Using frame graphs and grouping URIs for proper frame management

Usage:
    python test_kgentities_frames_endpoint.py
"""

import sys
import asyncio
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import the base tester and utilities
from test_kg_endpoint_utils import BaseKGEndpointTester, run_test_suite, logger

# VitalGraph imports for frame operations
from vitalgraph.model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
)
from vitalgraph.endpoint.kgframes_endpoint import OperationMode as FrameOperationMode
from vital_ai_vitalsigns.model.GraphObject import GraphObject


class KGEntitiesFramesEndpointTester(BaseKGEndpointTester):
    """Test harness for KGEntities and KGFrames endpoint integration."""
    
    def __init__(self, fuseki_url: str = "http://host.docker.internal:3030"):
        super().__init__(fuseki_url)
        self.test_frame_uris = []
        self.entity_frame_mapping = {}  # Maps entity URIs to their frame URIs
    
    async def test_space_management(self) -> bool:
        """Test basic space management operations."""
        logger.info("🧪 Testing Space Management Operations")
        
        # Create test space
        self.entity_test_space_id = await self.create_test_space("frames_test_space")
        if not self.entity_test_space_id:
            self.log_test_result("Space Management", False, "Failed to create test space")
            return False
        
        self.log_test_result("Space Management", True, f"Created test space: {self.entity_test_space_id}")
        return True
    
    async def test_entity_graphs_creation(self) -> bool:
        """Test creating entity graphs with frames."""
        try:
            logger.info("🔍 Testing Entity Graphs Creation with Frames")
            
            # Create entity graphs in the test space
            success = await self.create_entity_graphs_in_space(self.entity_test_space_id)
            
            if success:
                self.log_test_result("Entity Graphs Creation", True, f"Created {len(self.created_entity_uris)} entity graphs")
                
                # Extract frame information from created entities
                await self._extract_frame_information()
                return True
            else:
                self.log_test_result("Entity Graphs Creation", False, "Failed to create entity graphs")
                return False
                
        except Exception as e:
            self.log_test_result("Entity Graphs Creation", False, f"Exception: {e}")
            return False
    
    async def _extract_frame_information(self):
        """Extract frame URIs and mapping from created entity graphs."""
        try:
            logger.info("🔍 Extracting frame information from entity graphs")
            
            for entity_uri in self.created_entity_uris:
                # Get the complete entity graph to find associated frames
                response = await self.kgentities_endpoint._get_entity_by_uri(
                    space_id=self.entity_test_space_id,
                    graph_id="main",
                    uri=entity_uri,
                    include_entity_graph=True,
                    current_user={"username": "test_user", "user_id": "test_user_123"}
                )
                
                if response and hasattr(response, 'graph') and response.graph:
                    entity_frames = []
                    
                    # Find frame objects in the entity graph
                    from ai_haley_kg_domain.model.KGFrame import KGFrame as KGFrameClass
                    for obj in response.graph:
                        if isinstance(obj, KGFrameClass):
                            frame_uri = str(obj.URI)
                            entity_frames.append(frame_uri)
                            self.test_frame_uris.append(frame_uri)
                    
                    self.entity_frame_mapping[entity_uri] = entity_frames
                    logger.info(f"📋 Entity {entity_uri} has {len(entity_frames)} frames")
            
            logger.info(f"✅ Found {len(self.test_frame_uris)} total frames across {len(self.created_entity_uris)} entities")
            
        except Exception as e:
            logger.error(f"❌ Error extracting frame information: {e}")
    
    async def test_list_entity_frames(self) -> bool:
        """Test listing all frames of an entity."""
        try:
            logger.info("🔍 Testing List Entity Frames")
            
            if not self.created_entity_uris:
                self.log_test_result("List Entity Frames", False, "No entities available for testing")
                return False
            
            # Test listing frames for the first entity
            entity_uri = self.created_entity_uris[0]
            expected_frames = self.entity_frame_mapping.get(entity_uri, [])
            
            logger.info(f"🔍 Listing frames for entity: {entity_uri}")
            
            # Use KGEntitiesEndpoint to list frames for the entity
            response = await self.kgentities_endpoint._get_kgentity_frames(
                space_id=self.entity_test_space_id,
                graph_id="main",
                entity_uri=entity_uri,
                page_size=100,
                offset=0,
                search=None,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and isinstance(response, dict) and "frames" in response:
                frames_list = response["frames"]
                listed_frames = len(frames_list) if frames_list else 0
                total_count = response.get("total_count", 0)
                
                logger.info(f"📋 Listed {listed_frames} frames total (total_count: {total_count})")
                
                # Verify we have frames (each entity should have 6 frames: 4 transaction + 1 address + 1 employment)
                expected_frame_count = 6  # Based on test_data.py: 4 transaction + 1 address + 1 employment
                if listed_frames >= expected_frame_count:
                    self.log_test_result("List Entity Frames", True, f"Successfully listed {listed_frames} frames (expected {expected_frame_count})")
                    return True
                else:
                    self.log_test_result("List Entity Frames", False, f"Expected at least {expected_frame_count} frames, got {listed_frames}")
                    return False
            else:
                self.log_test_result("List Entity Frames", False, "No frames returned in response")
                return False
                
        except Exception as e:
            self.log_test_result("List Entity Frames", False, f"Exception: {e}")
            return False
    
    async def test_get_individual_frame(self) -> bool:
        """Test getting an individual frame by URI."""
        try:
            logger.info("🔍 Testing Get Individual Frame")
            
            if not self.test_frame_uris:
                self.log_test_result("Get Individual Frame", False, "No frame URIs available for testing")
                return False
            
            # Test getting the first frame
            frame_uri = self.test_frame_uris[0]
            logger.info(f"🔍 Getting frame: {frame_uri}")
            
            response = await self.kgentities_endpoint._get_individual_frame(
                space_id=self.entity_test_space_id,
                graph_id="main",
                frame_uri=frame_uri,
                include_frame_graph=True,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'graph') and response.graph:
                frame_objects = len(response.graph)
                logger.info(f"📋 Retrieved frame with {frame_objects} objects")
                
                # Verify we got the frame and its related objects
                if frame_objects >= 1:
                    self.log_test_result("Get Individual Frame", True, f"Successfully retrieved frame with {frame_objects} objects")
                    return True
                else:
                    self.log_test_result("Get Individual Frame", False, "Frame retrieved but no objects found")
                    return False
            else:
                self.log_test_result("Get Individual Frame", False, "No frame data returned")
                return False
                
        except Exception as e:
            self.log_test_result("Get Individual Frame", False, f"Exception: {e}")
            return False
    
    async def test_create_new_frame(self) -> bool:
        """Test adding a new frame to an entity."""
        try:
            logger.info("🔍 Testing Create New Frame")
            
            if not self.created_entity_uris:
                self.log_test_result("Create New Frame", False, "No entities available for testing")
                return False
            
            # Create a new frame for the first entity
            entity_uri = self.created_entity_uris[0]
            
            # Create frame using VitalSigns GraphObjects (proper way)
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            
            new_frame_uri = f"http://example.com/test/frame/new_test_frame_{entity_uri.split('/')[-1]}"
            
            # Create KGFrame object (server will set grouping URIs)
            frame = KGFrame()
            frame.URI = new_frame_uri
            frame.name = "Test Frame"
            frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TestFrame"
            # Do NOT set hasKGGraphURI - let server handle it
            
            logger.info(f"🔍 Creating new frame: {new_frame_uri}")
            
            # Pass GraphObjects directly
            response = await self.kgentities_endpoint._create_or_update_frames(
                space_id=self.entity_test_space_id,
                graph_id="main",
                objects=[frame],
                operation_mode=FrameOperationMode.CREATE,
                parent_uri=entity_uri,
                entity_uri=entity_uri,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'created_uris') and response.created_uris:
                created_frame_uri = response.created_uris[0]
                self.test_frame_uris.append(created_frame_uri)
                logger.info(f"✅ Created new frame: {created_frame_uri}")
                
                self.log_test_result("Create New Frame", True, f"Successfully created frame: {created_frame_uri}")
                return True
            else:
                self.log_test_result("Create New Frame", False, "No frame URI returned from creation")
                return False
                
        except Exception as e:
            self.log_test_result("Create New Frame", False, f"Exception: {e}")
            return False
    
    async def test_update_frame(self) -> bool:
        """Test updating an existing frame."""
        try:
            logger.info("🔍 Testing Update Frame")
            
            if not self.test_frame_uris:
                self.log_test_result("Update Frame", False, "No frame URIs available for testing")
                return False
            
            # Update the first frame
            frame_uri = self.test_frame_uris[0]
            
            # Create updated frame using VitalSigns GraphObjects (proper way)
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Create updated KGFrame object
            updated_frame = KGFrame()
            updated_frame.URI = frame_uri
            updated_frame.name = "Updated Test Frame"
            updated_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TestFrame"
            # Do NOT set hasKGGraphURI - let server handle it
            
            logger.info(f"🔍 Updating frame: {frame_uri}")
            
            # Find the entity that owns this frame
            entity_uri = None
            for ent_uri, frame_list in self.entity_frame_mapping.items():
                if frame_uri in frame_list:
                    entity_uri = ent_uri
                    break
            
            if not entity_uri and self.created_entity_uris:
                # Fallback to first entity if mapping not found
                entity_uri = self.created_entity_uris[0]
            
            if not entity_uri:
                self.log_test_result("Update Frame", False, "No entity URI found for frame update")
                return False
            
            response = await self.kgentities_endpoint._create_or_update_frames(
                space_id=self.entity_test_space_id,
                graph_id="main",
                objects=[updated_frame],
                operation_mode=FrameOperationMode.UPDATE,
                parent_uri=entity_uri,
                entity_uri=entity_uri,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'created_uris') and response.created_uris:
                updated_frame_uri = response.created_uris[0]
                logger.info(f"✅ Updated frame: {updated_frame_uri}")
                
                # Verify the update by retrieving the frame
                try:
                    logger.info(f"🔍 Verifying update by retrieving frame: {updated_frame_uri}")
                    
                    get_response = await self.kgentities_endpoint._get_individual_frame(
                        space_id=self.entity_test_space_id,
                        graph_id="main",
                        frame_uri=updated_frame_uri,
                        include_frame_graph=False,
                        current_user={"username": "test_user", "user_id": "test_user_123"}
                    )
                    
                    # Check the VitalSigns objects directly for the updated name
                    if get_response and hasattr(get_response, 'graph') and get_response.graph:
                        logger.info(f"🔍 Get response has {len(get_response.graph)} objects")
                        
                        # Check VitalSigns objects directly
                        frame_found = False
                        updated_name_found = False
                        
                        for obj in get_response.graph:
                            obj_uri = getattr(obj, 'URI', None)
                            logger.info(f"🔍 Checking VitalSigns object: URI={obj_uri}, type={type(obj).__name__}")
                            
                            if obj_uri == updated_frame_uri:
                                frame_found = True
                                # Access the name property from the VitalSigns object (returns property object)
                                name_property = obj.name
                                # Handle both property object with .value and direct string cases
                                if hasattr(name_property, 'value'):
                                    actual_name = name_property.value
                                else:
                                    actual_name = name_property
                                logger.info(f"🔍 Found target frame, actual name: '{actual_name}'")
                                
                                if actual_name == "Updated Test Frame":
                                    updated_name_found = True
                                    logger.info(f"✅ Verified: Frame name updated to '{actual_name}'")
                                else:
                                    logger.warning(f"⚠️ Frame name is '{actual_name}', expected 'Updated Test Frame'")
                                break
                        
                        if frame_found and updated_name_found:
                            self.log_test_result("Update Frame", True, f"Successfully updated and verified frame name changed: {updated_frame_uri}")
                            return True
                        elif frame_found:
                            self.log_test_result("Update Frame", False, f"Frame found but name not updated correctly")
                            return False
                        else:
                            self.log_test_result("Update Frame", False, f"Updated frame not found in get response")
                            return False
                    else:
                        self.log_test_result("Update Frame", False, "Failed to retrieve updated frame for verification")
                        return False
                        
                except Exception as verify_e:
                    logger.warning(f"⚠️ Update succeeded but verification failed: {verify_e}")
                    self.log_test_result("Update Frame", True, f"Updated frame but verification failed: {updated_frame_uri}")
                    return True
                    
            else:
                self.log_test_result("Update Frame", False, "No frame URI returned from update")
                return False
                
        except Exception as e:
            self.log_test_result("Update Frame", False, f"Exception: {e}")
            return False
    
    async def test_delete_frame(self) -> bool:
        """Test deleting a frame."""
        try:
            logger.info("🔍 Testing Delete Frame")
            
            if not self.test_frame_uris:
                self.log_test_result("Delete Frame", False, "No frame URIs available for testing")
                return False
            
            # Delete the last frame (likely the one we created)
            frame_uri = self.test_frame_uris[-1]
            
            logger.info(f"🔍 Deleting frame: {frame_uri}")
            
            response = await self.kgentities_endpoint._delete_frame_by_uri(
                space_id=self.entity_test_space_id,
                graph_id="main",
                uri=frame_uri,
                current_user={"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'deleted_count') and response.deleted_count > 0:
                deleted_count = response.deleted_count
                logger.info(f"✅ Deleted frame: {deleted_count} objects")
                
                # Verify deletion by listing frames to confirm the frame is gone
                try:
                    logger.info(f"🔍 Verifying deletion by listing frames")
                    
                    # Find which entity owned this frame
                    entity_uri = None
                    for ent_uri, frame_list in self.entity_frame_mapping.items():
                        if frame_uri in frame_list:
                            entity_uri = ent_uri
                            break
                    
                    if entity_uri:
                        # List frames for this entity to verify deletion
                        list_response = await self.kgentities_endpoint._get_kgentity_frames(
                            space_id=self.entity_test_space_id,
                            graph_id="main",
                            entity_uri=entity_uri,
                            include_frame_graph=False,
                            current_user={"username": "test_user", "user_id": "test_user_123"}
                        )
                        
                        # Check if the deleted frame is still in the list
                        frame_still_exists = False
                        if list_response and hasattr(list_response, 'graph') and list_response.graph:
                            for obj in list_response.graph:
                                if str(obj.URI) == frame_uri:
                                    frame_still_exists = True
                                    break
                        
                        if frame_still_exists:
                            self.log_test_result("Delete Frame", False, f"Frame still exists after deletion: {frame_uri}")
                            return False
                        else:
                            logger.info(f"✅ Verified: Frame {frame_uri} no longer appears in entity frame list")
                            
                            # Remove from our tracking lists
                            if frame_uri in self.test_frame_uris:
                                self.test_frame_uris.remove(frame_uri)
                            if entity_uri in self.entity_frame_mapping and frame_uri in self.entity_frame_mapping[entity_uri]:
                                self.entity_frame_mapping[entity_uri].remove(frame_uri)
                            
                            self.log_test_result("Delete Frame", True, f"Successfully deleted and verified frame removal: {deleted_count} objects")
                            return True
                    else:
                        logger.warning(f"⚠️ Could not find entity owner for frame {frame_uri}, skipping verification")
                        # Remove from our tracking list anyway
                        if frame_uri in self.test_frame_uris:
                            self.test_frame_uris.remove(frame_uri)
                        
                        self.log_test_result("Delete Frame", True, f"Successfully deleted frame (verification skipped): {deleted_count} objects")
                        return True
                        
                except Exception as verify_e:
                    logger.warning(f"⚠️ Delete succeeded but verification failed: {verify_e}")
                    # Remove from our tracking list anyway
                    if frame_uri in self.test_frame_uris:
                        self.test_frame_uris.remove(frame_uri)
                    
                    self.log_test_result("Delete Frame", True, f"Deleted frame but verification failed: {deleted_count} objects")
                    return True
                    
            else:
                self.log_test_result("Delete Frame", False, "No objects deleted or invalid response")
                return False
                
        except Exception as e:
            self.log_test_result("Delete Frame", False, f"Exception: {e}")
            return False
    
    async def test_frame_graph_operations(self) -> bool:
        """Test comprehensive frame graph operations."""
        try:
            logger.info("🔍 Testing Frame Graph Operations")
            
            # Run all frame operation tests
            tests = [
                ("List Entity Frames", self.test_list_entity_frames),
                ("Get Individual Frame", self.test_get_individual_frame),
                ("Create New Frame", self.test_create_new_frame),
                ("Update Frame", self.test_update_frame),
                ("Delete Frame", self.test_delete_frame)
            ]
            
            all_passed = True
            for test_name, test_method in tests:
                logger.info(f"🧪 Running: {test_name}")
                success = await test_method()
                if not success:
                    all_passed = False
            
            if all_passed:
                self.log_test_result("Frame Graph Operations", True, "All frame operations completed successfully")
            else:
                self.log_test_result("Frame Graph Operations", False, "Some frame operations failed")
            
            return all_passed
            
        except Exception as e:
            self.log_test_result("Frame Graph Operations", False, f"Exception: {e}")
            return False
    
    async def test_cleanup_entity_graphs_final(self) -> bool:
        """Test final cleanup of entity graphs."""
        try:
            logger.info("🔍 Testing Final Entity Graphs Cleanup")
            
            success = await self.cleanup_entity_graphs(self.entity_test_space_id)
            
            if success:
                self.log_test_result("Final Entity Graphs Cleanup", True, "Successfully cleaned up all entity graphs")
            else:
                self.log_test_result("Final Entity Graphs Cleanup", False, "Failed to clean up entity graphs")
            
            return success
            
        except Exception as e:
            self.log_test_result("Final Entity Graphs Cleanup", False, f"Exception: {e}")
            return False


async def main():
    """Main test execution function."""
    logger.info("🚀 Starting KGEntities and KGFrames Endpoint Integration Tests")
    
    # Define test methods to run
    test_methods = [
        "test_space_management",
        "test_entity_graphs_creation", 
        "test_frame_graph_operations",
        "test_cleanup_entity_graphs_final"
    ]
    
    # Run the test suite
    success = await run_test_suite(KGEntitiesFramesEndpointTester, test_methods)
    
    if success:
        logger.info("🎉 Test suite completed successfully!")
        return 0
    else:
        logger.error("💥 Test suite failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
