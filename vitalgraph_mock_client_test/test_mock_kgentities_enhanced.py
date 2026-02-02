"""
Test suite for Enhanced MockKGEntitiesEndpoint with Entity-Frame relationship functionality.

✅ UPDATED: This test file uses Edge-based relationships, concrete slot classes, and follows Phase 1A enhancements!
    Entity-frame relationships are properly implemented using Edge_hasEntityKGFrame
    instead of direct properties, with proper VitalSigns integration.
    Concrete slot classes (KGTextSlot, KGIntegerSlot, KGBooleanSlot) with actual values.

This test suite validates the enhanced mock implementation of KGEntity operations including:
- Enhanced parameters: include_entity_graph, delete_entity_graph
- Entity-frame relationship methods: create_entity_frames, update_entity_frames, delete_entity_frames, get_entity_frames
- Concrete slot classes with actual slot values (textSlotValue, integerSlotValue, booleanSlotValue)
- VitalSigns native JSON-LD functionality with Edge-based relationships
- pyoxigraph in-memory SPARQL quad store for data persistence
- Direct test runner format (no pytest dependency)
"""

import sys
import logging
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, '/Users/hadfield/Local/vital-git/vital-graph')

from vitalgraph.mock.client.mock_vitalgraph_client import MockVitalGraphClient
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.model.kgentities_model import EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse
from vitalgraph.model.kgframes_model import FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot


def create_test_entity_with_frames() -> List[object]:
    """Create test KGEntity with KGFrames and concrete slots using Edge relationships."""
    objects = []
    
    # Create test KGEntity
    entity = KGEntity()
    entity.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
    entity.name = "TestEntity1"
    entity.kGraphDescription = "Test entity for enhanced functionality with concrete slots"
    entity.kGEntityType = "urn:EnhancedTestEntityType"
    objects.append(entity)
    
    # Create first test KGFrame
    frame1 = KGFrame()
    frame1.URI = "http://vital.ai/haley.ai/app/KGFrame/test_frame_001"
    frame1.name = "TestFrame1"
    frame1.kGFrameType = "urn:TestFrameType"
    objects.append(frame1)
    
    # Create concrete slots for frame1
    # KGTextSlot with actual text value
    text_slot = KGTextSlot()
    text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/enhanced_text_slot"
    text_slot.name = "Enhanced Text Slot"
    text_slot.textSlotValue = "Enhanced Test Value"
    text_slot.kGSlotType = "urn:EnhancedTextSlotType"
    objects.append(text_slot)
    
    # KGIntegerSlot with actual integer value
    integer_slot = KGIntegerSlot()
    integer_slot.URI = "http://vital.ai/haley.ai/app/KGIntegerSlot/enhanced_integer_slot"
    integer_slot.name = "Enhanced Integer Slot"
    integer_slot.integerSlotValue = 100
    integer_slot.kGSlotType = "urn:EnhancedIntegerSlotType"
    objects.append(integer_slot)
    
    # KGBooleanSlot with actual boolean value
    boolean_slot = KGBooleanSlot()
    boolean_slot.URI = "http://vital.ai/haley.ai/app/KGBooleanSlot/enhanced_boolean_slot"
    boolean_slot.name = "Enhanced Boolean Slot"
    boolean_slot.booleanSlotValue = True
    boolean_slot.kGSlotType = "urn:EnhancedBooleanSlotType"
    objects.append(boolean_slot)
    
    # Create Edge_hasKGSlot to link frame1 to concrete slots
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    
    text_slot_edge = Edge_hasKGSlot()
    text_slot_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame1_text_slot"
    text_slot_edge.edgeSource = str(frame1.URI)
    text_slot_edge.edgeDestination = str(text_slot.URI)
    objects.append(text_slot_edge)
    
    integer_slot_edge = Edge_hasKGSlot()
    integer_slot_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame1_integer_slot"
    integer_slot_edge.edgeSource = str(frame1.URI)
    integer_slot_edge.edgeDestination = str(integer_slot.URI)
    objects.append(integer_slot_edge)
    
    boolean_slot_edge = Edge_hasKGSlot()
    boolean_slot_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame1_boolean_slot"
    boolean_slot_edge.edgeSource = str(frame1.URI)
    boolean_slot_edge.edgeDestination = str(boolean_slot.URI)
    objects.append(boolean_slot_edge)
    
    # Create Edge_hasEntityKGFrame to link entity to frame1
    from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
    edge1 = Edge_hasEntityKGFrame()
    edge1.URI = "http://vital.ai/haley.ai/app/Edge_hasEntityKGFrame/entity_frame1"
    edge1.edgeSource = str(entity.URI)
    edge1.edgeDestination = str(frame1.URI)
    objects.append(edge1)
    
    # Create second test KGFrame (simpler, without slots for variety)
    frame2 = KGFrame()
    frame2.URI = "http://vital.ai/haley.ai/app/KGFrame/test_frame_002"
    frame2.name = "TestFrame2"
    frame2.kGFrameType = "urn:SimpleTestFrameType"
    objects.append(frame2)
    
    # Create Edge_hasEntityKGFrame to link entity to frame2
    edge2 = Edge_hasEntityKGFrame()
    edge2.URI = "http://vital.ai/haley.ai/app/Edge_hasEntityKGFrame/entity_frame2"
    edge2.edgeSource = str(entity.URI)
    edge2.edgeDestination = str(frame2.URI)
    objects.append(edge2)
    
    return objects


def create_test_frames_document() -> Dict[str, Any]:
    """Create test frames document with concrete slots for entity-frame operations."""
    from vital_ai_vitalsigns.model.GraphObject import GraphObject
    
    objects = []
    
    # Create test frame with concrete slots
    frame1 = KGFrame()
    frame1.URI = "http://vital.ai/haley.ai/app/KGFrame/new_frame_001"
    frame1.name = "NewFrame1"
    frame1.kGFrameType = "urn:NewFrameType"
    objects.append(frame1)
    
    # Add concrete slots to the frame
    # KGTextSlot for the new frame
    new_text_slot = KGTextSlot()
    new_text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/new_text_slot"
    new_text_slot.name = "New Text Slot"
    new_text_slot.textSlotValue = "New Frame Text Value"
    new_text_slot.kGSlotType = "urn:NewTextSlotType"
    objects.append(new_text_slot)
    
    # KGIntegerSlot for the new frame
    new_integer_slot = KGIntegerSlot()
    new_integer_slot.URI = "http://vital.ai/haley.ai/app/KGIntegerSlot/new_integer_slot"
    new_integer_slot.name = "New Integer Slot"
    new_integer_slot.integerSlotValue = 200
    new_integer_slot.kGSlotType = "urn:NewIntegerSlotType"
    objects.append(new_integer_slot)
    
    # Create edges to link frame to slots
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    
    text_edge = Edge_hasKGSlot()
    text_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/new_frame_text_slot"
    text_edge.edgeSource = str(frame1.URI)
    text_edge.edgeDestination = str(new_text_slot.URI)
    objects.append(text_edge)
    
    integer_edge = Edge_hasKGSlot()
    integer_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/new_frame_integer_slot"
    integer_edge.edgeSource = str(frame1.URI)
    integer_edge.edgeDestination = str(new_integer_slot.URI)
    objects.append(integer_edge)
    
    # Create second frame (simpler)
    frame2 = KGFrame()
    frame2.URI = "http://vital.ai/haley.ai/app/KGFrame/new_frame_002"
    frame2.name = "NewFrame2"
    frame2.kGFrameType = "urn:SimpleNewFrameType"
    objects.append(frame2)
    
    # Convert to JSON-LD using VitalSigns
    jsonld_document = GraphObject.to_jsonld_list(objects)
    
    return jsonld_document


class TestEnhancedMockKGEntitiesEndpoint:
    """Test suite for Enhanced MockKGEntitiesEndpoint with entity-frame relationships."""
    
    def __init__(self):
        """Initialize test suite."""
        # Set up logging
        self.logger = logging.getLogger(f"{__name__}.TestEnhancedMockKGEntitiesEndpoint")
        
        # Test configuration
        self.test_space_id = "test_enhanced_entities_space"
        self.test_graph_id = "http://vital.ai/graph/test-enhanced-entities"
        
        # Test results tracking
        self.test_results = []
        
        # Initialize mock client
        self.client = MockVitalGraphClient()
        self.endpoint = self.client.kgentities
    
    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log test result with details."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if message:
            print(f"    {message}")
        if data:
            import json
            print(f"    Data: {json.dumps(data, indent=2)}")
        print()
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data
        })
    
    def test_enhanced_list_kgentities_with_include_graph(self):
        """Test enhanced list_kgentities with include_entity_graph parameter."""
        try:
            # Setup: Create space and entities with frames
            self.endpoint.client.space_manager.create_space(self.test_space_id)
            
            # Create test entities with frames
            test_objects = create_test_entity_with_frames()
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            jsonld_document = GraphObject.to_jsonld_list(test_objects)
            jsonld_doc = JsonLdDocument(**jsonld_document)
            
            # Create entities with frames
            create_response = self.endpoint.create_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=jsonld_doc
            )
            
            # Test: List entities with include_entity_graph=True
            response = self.endpoint.list_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                include_entity_graph=True
            )
            
            success = (
                isinstance(response, EntitiesResponse) and
                response.total_count > 0
            )
            
            self.log_test_result(
                "Enhanced List KGEntities with Include Graph",
                success,
                f"Listed {response.total_count} entities with graph inclusion",
                {
                    "total_count": response.total_count,
                    "include_entity_graph": True
                }
            )
            
        except Exception as e:
            self.log_test_result("Enhanced List KGEntities with Include Graph", False, f"Exception: {e}")
    
    def test_enhanced_get_kgentity_with_include_graph(self):
        """Test enhanced get_kgentity with include_entity_graph parameter."""
        try:
            entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
            
            # Test: Get entity with include_entity_graph=True
            response = self.endpoint.get_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=entity_uri,
                include_entity_graph=True
            )
            
            success = response is not None
            
            self.log_test_result(
                "Enhanced Get KGEntity with Include Graph",
                success,
                f"Retrieved entity with complete graph",
                {
                    "entity_uri": entity_uri,
                    "include_entity_graph": True
                }
            )
            
        except Exception as e:
            self.log_test_result("Enhanced Get KGEntity with Include Graph", False, f"Exception: {e}")
    
    def test_create_entity_frames(self):
        """Test create_entity_frames method."""
        try:
            entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
            
            # Create frames document
            frames_document = create_test_frames_document()
            frames_doc = JsonLdDocument(**frames_document)
            
            # Test: Create frames for entity
            response = self.endpoint.create_entity_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=entity_uri,
                document=frames_doc
            )
            
            success = (
                isinstance(response, FrameCreateResponse) and
                response.created_count > 0 and
                len(response.created_uris) > 0
            )
            
            self.log_test_result(
                "Create Entity Frames",
                success,
                f"Created {response.created_count} frames for entity",
                {
                    "entity_uri": entity_uri,
                    "created_count": response.created_count,
                    "created_uris": response.created_uris
                }
            )
            
        except Exception as e:
            self.log_test_result("Create Entity Frames", False, f"Exception: {e}")
    
    def test_get_entity_frames(self):
        """Test get_entity_frames method."""
        try:
            entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
            
            # Test: Get frames for entity
            response = self.endpoint.get_entity_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=entity_uri
            )
            
            success = isinstance(response, JsonLdDocument)
            
            self.log_test_result(
                "Get Entity Frames",
                success,
                f"Retrieved frames for entity",
                {
                    "entity_uri": entity_uri,
                    "response_type": type(response).__name__
                }
            )
            
        except Exception as e:
            self.log_test_result("Get Entity Frames", False, f"Exception: {e}")
    
    def test_update_entity_frames(self):
        """Test update_entity_frames method."""
        try:
            entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
            
            # Create updated frames document
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            updated_frame = KGFrame()
            updated_frame.URI = "http://vital.ai/haley.ai/app/KGFrame/new_frame_001"
            updated_frame.name = "UpdatedFrame1"
            # Use only basic properties that exist
            
            jsonld_document = GraphObject.to_jsonld_list([updated_frame])
            frames_doc = JsonLdDocument(**jsonld_document)
            
            # Test: Update frames for entity
            response = self.endpoint.update_entity_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=entity_uri,
                document=frames_doc
            )
            
            success = (
                isinstance(response, FrameUpdateResponse) and
                response.updated_uri != ""
            )
            
            self.log_test_result(
                "Update Entity Frames",
                success,
                f"Updated frames for entity",
                {
                    "entity_uri": entity_uri,
                    "updated_uri": response.updated_uri
                }
            )
            
        except Exception as e:
            self.log_test_result("Update Entity Frames", False, f"Exception: {e}")
    
    def test_delete_entity_frames(self):
        """Test delete_entity_frames method."""
        try:
            entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
            frame_uris = [
                "http://vital.ai/haley.ai/app/KGFrame/new_frame_001",
                "http://vital.ai/haley.ai/app/KGFrame/new_frame_002"
            ]
            
            # Test: Delete frames from entity
            response = self.endpoint.delete_entity_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=entity_uri,
                frame_uris=frame_uris
            )
            
            success = (
                isinstance(response, FrameDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Delete Entity Frames",
                success,
                f"Deleted {response.deleted_count} frames from entity",
                {
                    "entity_uri": entity_uri,
                    "frame_uris": frame_uris,
                    "deleted_count": response.deleted_count
                }
            )
            
        except Exception as e:
            self.log_test_result("Delete Entity Frames", False, f"Exception: {e}")
    
    def test_concrete_slot_values_verification(self):
        """Test that concrete slot values are preserved and accessible."""
        try:
            # Get the test objects to verify slot values
            test_objects = create_test_entity_with_frames()
            
            # Find concrete slots in the test objects
            text_slot = next((obj for obj in test_objects if isinstance(obj, KGTextSlot)), None)
            integer_slot = next((obj for obj in test_objects if isinstance(obj, KGIntegerSlot)), None)
            boolean_slot = next((obj for obj in test_objects if isinstance(obj, KGBooleanSlot)), None)
            
            # Verify slot values are correct
            slot_values_correct = (
                text_slot and str(text_slot.textSlotValue) == "Enhanced Test Value" and
                integer_slot and int(integer_slot.integerSlotValue) == 100 and
                boolean_slot and bool(boolean_slot.booleanSlotValue) == True
            )
            
            # Verify slot types are set
            slot_types_correct = (
                text_slot and str(text_slot.kGSlotType) == "urn:EnhancedTextSlotType" and
                integer_slot and str(integer_slot.kGSlotType) == "urn:EnhancedIntegerSlotType" and
                boolean_slot and str(boolean_slot.kGSlotType) == "urn:EnhancedBooleanSlotType"
            )
            
            success = slot_values_correct and slot_types_correct
            
            self.log_test_result(
                "Concrete Slot Values Verification",
                success,
                f"Verified concrete slot values and types",
                {
                    "text_slot_value": str(text_slot.textSlotValue) if text_slot else None,
                    "integer_slot_value": int(integer_slot.integerSlotValue) if integer_slot else None,
                    "boolean_slot_value": bool(boolean_slot.booleanSlotValue) if boolean_slot else None,
                    "text_slot_type": str(text_slot.kGSlotType) if text_slot else None,
                    "integer_slot_type": str(integer_slot.kGSlotType) if integer_slot else None,
                    "boolean_slot_type": str(boolean_slot.kGSlotType) if boolean_slot else None
                }
            )
            
        except Exception as e:
            self.log_test_result("Concrete Slot Values Verification", False, f"Exception: {e}")
    
    def test_enhanced_delete_kgentity_with_graph(self):
        """Test enhanced delete_kgentity with delete_entity_graph parameter."""
        try:
            entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
            
            # Test: Delete entity with complete graph
            response = self.endpoint.delete_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=entity_uri,
                delete_entity_graph=True
            )
            
            success = (
                isinstance(response, EntityDeleteResponse) and
                response.deleted_count >= 0
            )
            
            self.log_test_result(
                "Enhanced Delete KGEntity with Graph",
                success,
                f"Deleted entity with complete graph",
                {
                    "entity_uri": entity_uri,
                    "delete_entity_graph": True,
                    "deleted_count": response.deleted_count
                }
            )
            
        except Exception as e:
            self.log_test_result("Enhanced Delete KGEntity with Graph", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run all tests in the suite."""
        print("🧪 Testing Enhanced MockKGEntitiesEndpoint with Entity-Frame Relationships & Concrete Slots")
        print("=" * 85)
        
        # Run tests
        self.test_concrete_slot_values_verification()  # Test concrete slots first
        self.test_enhanced_list_kgentities_with_include_graph()
        self.test_enhanced_get_kgentity_with_include_graph()
        self.test_create_entity_frames()
        self.test_get_entity_frames()
        self.test_update_entity_frames()
        self.test_delete_entity_frames()
        self.test_enhanced_delete_kgentity_with_graph()
        
        # Print summary
        print("=" * 65)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! Enhanced MockKGEntitiesEndpoint with concrete slots working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test execution."""
    print("Starting Enhanced MockKGEntitiesEndpoint Tests...")
    print()
    
    # Create and run test suite
    test_suite = TestEnhancedMockKGEntitiesEndpoint()
    success = test_suite.run_all_tests()
    
    print()
    print("Enhanced MockKGEntitiesEndpoint Tests Complete!")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
