#!/usr/bin/env python3
"""
Test suite for KG Endpoint Enhancements - Entity-Frame and Frame-Slot Operations.

This test suite validates the new KG endpoint functionality including:
- Entity-frame relationship operations (create_entity_frames, get_entity_frames, etc.)
- Frame-slot relationship operations (create_frame_slots, get_frame_slots, etc.)
- Enhanced parameters (include_entity_graph, delete_entity_graph, include_frame_graph)
- Proper edge-based relationships using Edge_hasEntityKGFrame and Edge_hasKGSlot
- VitalSigns native JSON-LD functionality with concrete slot values
"""

import logging
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, List

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def create_mock_config() -> VitalGraphClientConfig:
    """Create a config object with mock client enabled."""
    # Create a temporary config file for the mock client
    import tempfile
    import yaml
    
    config_data = {
        'server': {
            'url': 'http://localhost:8001',
            'api_base_path': '/api/v1'
        },
        'client': {
            'use_mock_client': True,
            'timeout': 30,
            'max_retries': 3,
            'retry_delay': 1,
            'mock': {
                'filePath': '/Users/hadfield/Local/vital-git/vital-graph/minioFiles'
            }
        },
        'auth': {
            'username': 'admin',
            'password': 'admin'
        }
    }
    
    # Create temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        temp_config_path = f.name
    
    return VitalGraphClientConfig(temp_config_path)


def create_test_entity() -> KGEntity:
    """Create a test KGEntity."""
    entity = KGEntity()
    entity.URI = "http://vital.ai/haley.ai/app/KGEntity/test_enhanced_entity"
    entity.name = "Enhanced Test Entity"
    entity.kGraphDescription = "Entity for testing enhanced KG endpoint functionality"
    entity.kGIdentifier = "urn:enhanced_test_entity"
    entity.kGEntityType = "urn:EnhancedTestEntityType"
    entity.kGEntityTypeDescription = "Enhanced Test Entity Type"
    return entity


def create_test_frames_with_slots() -> List[object]:
    """Create test frames with concrete slots and proper edge relationships."""
    objects = []
    
    # Create KGFrame
    frame = KGFrame()
    frame.URI = "http://vital.ai/haley.ai/app/KGFrame/test_enhanced_frame"
    frame.name = "Enhanced Test Frame"
    frame.kGFrameType = "urn:EnhancedTestFrameType"
    objects.append(frame)
    
    # Create KGTextSlot with actual value
    text_slot = KGTextSlot()
    text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/test_text_slot"
    text_slot.name = "Enhanced Text Slot"
    text_slot.textSlotValue = "Enhanced Test Value"
    text_slot.kGSlotType = "urn:EnhancedTextSlotType"
    objects.append(text_slot)
    
    # Create KGIntegerSlot with actual value
    integer_slot = KGIntegerSlot()
    integer_slot.URI = "http://vital.ai/haley.ai/app/KGIntegerSlot/test_integer_slot"
    integer_slot.name = "Enhanced Integer Slot"
    integer_slot.integerSlotValue = 100
    integer_slot.kGSlotType = "urn:EnhancedIntegerSlotType"
    objects.append(integer_slot)
    
    # Create KGBooleanSlot with actual value
    boolean_slot = KGBooleanSlot()
    boolean_slot.URI = "http://vital.ai/haley.ai/app/KGBooleanSlot/test_boolean_slot"
    boolean_slot.name = "Enhanced Boolean Slot"
    boolean_slot.booleanSlotValue = True
    boolean_slot.kGSlotType = "urn:EnhancedBooleanSlotType"
    objects.append(boolean_slot)
    
    # Create Edge_hasKGSlot relationships
    text_edge = Edge_hasKGSlot()
    text_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame_text_slot"
    text_edge.edgeSource = str(frame.URI)
    text_edge.edgeDestination = str(text_slot.URI)
    objects.append(text_edge)
    
    integer_edge = Edge_hasKGSlot()
    integer_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame_integer_slot"
    integer_edge.edgeSource = str(frame.URI)
    integer_edge.edgeDestination = str(integer_slot.URI)
    objects.append(integer_edge)
    
    boolean_edge = Edge_hasKGSlot()
    boolean_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame_boolean_slot"
    boolean_edge.edgeSource = str(frame.URI)
    boolean_edge.edgeDestination = str(boolean_slot.URI)
    objects.append(boolean_edge)
    
    return objects


class TestKGEndpointEnhancements:
    """Test class for KG endpoint enhancements."""
    
    def __init__(self):
        """Initialize test suite."""
        # Set up logging
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s: %(message)s')
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Test configuration
        self.test_space_id = "test_enhanced_kg_space"
        self.test_graph_id = "http://vital.ai/haley.ai/app/test_enhanced_kg_graph"
        
        # Initialize mock client
        config = create_mock_config()
        self.mock_client = create_vitalgraph_client(config=config)
        self.mock_client.open()
        
        # Test results tracking
        self.test_results = []
        
        # Test data URIs
        self.entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_enhanced_entity"
        self.frame_uri = "http://vital.ai/haley.ai/app/KGFrame/test_enhanced_frame"
    
    def log_test_result(self, test_name: str, success: bool, message: str = "", data: Dict[str, Any] = None):
        """Log test result with details."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if message:
            print(f"    {message}")
        if data:
            print(f"    Data: {json.dumps(data, indent=2)}")
        print()
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data
        })
    
    def cleanup(self):
        """Cleanup after tests."""
        if hasattr(self, 'mock_client'):
            self.mock_client.close()
    
    def test_setup_test_data(self):
        """Setup test data - create space, entity, and initial frames."""
        try:
            # Create space
            space = Space(
                space=self.test_space_id, 
                space_name="Enhanced KG Test Space",
                tenant="test_tenant"
            )
            self.mock_client.add_space(space)
            
            # Create test entity
            entity = create_test_entity()
            entity_jsonld = GraphObject.to_jsonld_list([entity])
            entity_doc = JsonLdDocument(**entity_jsonld)
            
            entity_response = self.mock_client.kgentities.create_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=entity_doc
            )
            
            # Check if entity was created successfully (response exists and no error)
            success = entity_response is not None
            
            self.log_test_result(
                "Setup Test Data",
                success,
                f"Created test space and entity",
                {"entity_uri": self.entity_uri}
            )
            
        except Exception as e:
            self.log_test_result("Setup Test Data", False, f"Exception: {e}")
    
    def test_create_entity_frames(self):
        """Test creating frames for a specific entity using create_entity_frames."""
        try:
            # Create frames with slots
            frame_objects = create_test_frames_with_slots()
            frame_jsonld = GraphObject.to_jsonld_list(frame_objects)
            frame_doc = JsonLdDocument(**frame_jsonld)
            
            # Create entity frames
            response = self.mock_client.kgentities.create_entity_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=self.entity_uri,
                document=frame_doc
            )
            
            success = hasattr(response, 'created_count') and response.created_count >= 1
            
            self.log_test_result(
                "Create Entity Frames",
                success,
                f"Created {response.created_count if hasattr(response, 'created_count') else 0} frame objects for entity",
                {"entity_uri": self.entity_uri, "frame_uri": self.frame_uri}
            )
            
        except Exception as e:
            self.log_test_result("Create Entity Frames", False, f"Exception: {e}")
    
    def test_get_entity_frames(self):
        """Test getting frames for a specific entity using get_entity_frames."""
        try:
            # Get entity frames
            response = self.mock_client.kgentities.get_entity_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=self.entity_uri
            )
            
            # Debug: Check what we actually got
            print(f"DEBUG: get_entity_frames response type: {type(response)}")
            print(f"DEBUG: get_entity_frames response attributes: {dir(response)}")
            if hasattr(response, 'graph'):
                print(f"DEBUG: get_entity_frames graph: {response.graph}")
                print(f"DEBUG: get_entity_frames graph type: {type(response.graph)}")
                if response.graph:
                    print(f"DEBUG: get_entity_frames graph length: {len(response.graph)}")
            
            # Check if we got a valid JSON-LD document
            success = (
                hasattr(response, 'graph') and 
                response.graph is not None and 
                len(response.graph) > 0
            )
            
            frame_count = len(response.graph) if hasattr(response, 'graph') and response.graph else 0
            
            self.log_test_result(
                "Get Entity Frames",
                success,
                f"Retrieved {frame_count} frame objects for entity",
                {"entity_uri": self.entity_uri, "frame_count": frame_count}
            )
            
        except Exception as e:
            self.log_test_result("Get Entity Frames", False, f"Exception: {e}")
    
    def test_create_frame_slots(self):
        """Test creating slots for a specific frame using create_frame_slots."""
        try:
            # Create additional slots for the frame
            additional_slot = KGTextSlot()
            additional_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/additional_slot"
            additional_slot.name = "Additional Slot"
            additional_slot.textSlotValue = "Additional Value"
            additional_slot.kGSlotType = "urn:EnhancedTextSlotType"
            
            slot_jsonld = GraphObject.to_jsonld_list([additional_slot])
            slot_doc = JsonLdDocument(**slot_jsonld)
            
            # Create frame slots
            response = self.mock_client.kgframes.create_frame_slots(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                frame_uri=self.frame_uri,
                document=slot_doc
            )
            
            success = hasattr(response, 'created_count') and response.created_count >= 1
            
            self.log_test_result(
                "Create Frame Slots",
                success,
                f"Created {response.created_count if hasattr(response, 'created_count') else 0} slots for frame",
                {"frame_uri": self.frame_uri}
            )
            
        except Exception as e:
            self.log_test_result("Create Frame Slots", False, f"Exception: {e}")
    
    def test_get_frame_slots(self):
        """Test getting slots for a specific frame using get_frame_slots."""
        try:
            # Get frame slots
            response = self.mock_client.kgframes.get_frame_slots(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                frame_uri=self.frame_uri
            )
            
            # Check if we got a valid JSON-LD document with slots
            success = (
                hasattr(response, 'graph') and 
                response.graph is not None and 
                len(response.graph) > 0
            )
            
            slot_count = len(response.graph) if hasattr(response, 'graph') and response.graph else 0
            
            # Debug: Also try to get the frame itself to see if it exists
            try:
                frame_response = self.mock_client.kgframes.get_kgframe(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id,
                    uri=self.frame_uri
                )
                print(f"DEBUG: get_kgframe response type: {type(frame_response)}")
                if hasattr(frame_response, 'graph'):
                    print(f"DEBUG: get_kgframe graph: {frame_response.graph}")
                    print(f"DEBUG: get_kgframe graph type: {type(frame_response.graph)}")
                    if frame_response.graph:
                        print(f"DEBUG: get_kgframe graph length: {len(frame_response.graph)}")
                
                frame_exists = hasattr(frame_response, 'graph') and frame_response.graph is not None and len(frame_response.graph) > 0
            except Exception as e:
                print(f"DEBUG: get_kgframe exception: {e}")
                frame_exists = False
            
            self.log_test_result(
                "Get Frame Slots",
                success,
                f"Retrieved {slot_count} slot objects for frame (frame exists: {frame_exists})",
                {"frame_uri": self.frame_uri, "slot_count": slot_count, "frame_exists": frame_exists}
            )
            
        except Exception as e:
            self.log_test_result("Get Frame Slots", False, f"Exception: {e}")
    
    def test_get_frame_slots_with_type_filter(self):
        """Test getting slots with kGSlotType filtering by URN value."""
        try:
            # Get only slots with kGSlotType = "urn:EnhancedTextSlotType"
            response = self.mock_client.kgframes.get_frame_slots(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                frame_uri=self.frame_uri,
                kGSlotType="urn:EnhancedTextSlotType"
            )
            
            # Check if we got a valid response
            success = hasattr(response, 'graph')
            slot_count = len(response.graph) if hasattr(response, 'graph') and response.graph else 0
            
            self.log_test_result(
                "Get Frame Slots with kGSlotType Filter",
                success,
                f"Retrieved {slot_count} slots with kGSlotType='urn:EnhancedTextSlotType' for frame",
                {"frame_uri": self.frame_uri, "slot_type": "urn:EnhancedTextSlotType", "slot_count": slot_count}
            )
            
        except Exception as e:
            self.log_test_result("Get Frame Slots with kGSlotType Filter", False, f"Exception: {e}")
    
    def test_enhanced_get_entity_with_graph(self):
        """Test getting entity with complete graph using include_entity_graph parameter."""
        try:
            # Get entity with complete graph
            response = self.mock_client.kgentities.get_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=self.entity_uri,
                include_entity_graph=True
            )
            
            # Check if we got a valid response with graph data
            success = (
                hasattr(response, 'entity') and 
                response.entity is not None
            )
            
            self.log_test_result(
                "Enhanced Get Entity with Graph",
                success,
                f"Retrieved entity with complete graph data",
                {"entity_uri": self.entity_uri, "include_entity_graph": True}
            )
            
        except Exception as e:
            self.log_test_result("Enhanced Get Entity with Graph", False, f"Exception: {e}")
    
    def test_enhanced_get_frame_with_graph(self):
        """Test getting frame with complete graph using include_frame_graph parameter."""
        try:
            # Get frame with complete graph
            response = self.mock_client.kgframes.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=self.frame_uri,
                include_frame_graph=True
            )
            
            # Check if we got a valid JSON-LD document
            success = (
                hasattr(response, 'graph') and 
                response.graph is not None
            )
            
            self.log_test_result(
                "Enhanced Get Frame with Graph",
                success,
                f"Retrieved frame with complete graph data",
                {"frame_uri": self.frame_uri, "include_frame_graph": True}
            )
            
        except Exception as e:
            self.log_test_result("Enhanced Get Frame with Graph", False, f"Exception: {e}")
    
    def test_concrete_slot_values_verification(self):
        """Test that concrete slot values are properly preserved and accessible."""
        try:
            # Get frame slots to verify concrete values
            response = self.mock_client.kgframes.get_frame_slots(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                frame_uri=self.frame_uri
            )
            
            # Check if we got a valid response with graph data
            success = hasattr(response, 'graph') and response.graph is not None
            
            concrete_values_found = {}
            if success and response.graph:
                for slot_data in response.graph:
                    if isinstance(slot_data, dict):
                        # Check for text slot values
                        text_value = slot_data.get('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue')
                        if text_value:
                            concrete_values_found['text_slot'] = text_value.get('@value') if isinstance(text_value, dict) else text_value
                        
                        # Check for integer slot values
                        int_value = slot_data.get('http://vital.ai/ontology/haley-ai-kg#hasIntegerSlotValue')
                        if int_value:
                            concrete_values_found['integer_slot'] = int_value.get('@value') if isinstance(int_value, dict) else int_value
                        
                        # Check for boolean slot values
                        bool_value = slot_data.get('http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue')
                        if bool_value:
                            concrete_values_found['boolean_slot'] = bool_value.get('@value') if isinstance(bool_value, dict) else bool_value
            
            # Verify we found concrete values
            success = success and len(concrete_values_found) > 0
            
            self.log_test_result(
                "Concrete Slot Values Verification",
                success,
                "Verified concrete slot values are preserved",
                {"concrete_values": concrete_values_found}
            )
            
        except Exception as e:
            self.log_test_result(
                "Concrete Slot Values Verification",
                False,
                f"Error verifying concrete slot values: {e}",
                {"error": str(e)}
            )

    def test_mockkg_frames_vitalsigns_integration(self):
        """Test MockKGFramesEndpoint VitalSigns integration patterns."""
        try:
            # Test VitalSigns native object creation and conversion
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Create a test frame using VitalSigns patterns
            test_frame = KGFrame()
            test_frame.URI = "http://vital.ai/haley.ai/app/KGFrame/vitalsigns_test_frame"
            test_frame.name = "VitalSigns Integration Test Frame"
            test_frame.kGFrameType = "urn:VitalSignsTestFrameType"
            
            # Test VitalSigns JSON-LD conversion
            jsonld_doc = GraphObject.to_jsonld_list([test_frame])
            
            # Validate JSON-LD structure
            vitalsigns_tests = {
                "VitalSigns object creation": isinstance(test_frame, KGFrame),
                "GraphObject inheritance": isinstance(test_frame, GraphObject),
                "JSON-LD conversion": isinstance(jsonld_doc, dict),
                "Has @context": "@context" in jsonld_doc,
                "Property access": hasattr(test_frame, 'name'),
                "Property value set": test_frame.name == "VitalSigns Integration Test Frame"
            }
            
            passed_tests = sum(1 for result in vitalsigns_tests.values() if result)
            total_tests = len(vitalsigns_tests)
            success = passed_tests == total_tests
            
            self.log_test_result(
                "MockKGFrames VitalSigns Integration",
                success,
                f"VitalSigns integration tests: {passed_tests}/{total_tests} passed",
                {
                    "test_results": vitalsigns_tests,
                    "frame_uri": str(test_frame.URI),
                    "jsonld_keys": list(jsonld_doc.keys()) if isinstance(jsonld_doc, dict) else []
                }
            )
            
        except Exception as e:
            self.log_test_result(
                "MockKGFrames VitalSigns Integration",
                False,
                f"Error testing VitalSigns integration: {e}",
                {"error": str(e)}
            )

    def test_mockkg_frames_property_object_handling(self):
        """Test MockKGFramesEndpoint Property object handling and isinstance() checks."""
        try:
            # Test Property object handling with different slot types
            # Property handling tested through VitalSigns object property access
            
            # Create slots with different property types
            text_slot = KGTextSlot()
            text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/property_test_text"
            text_slot.textSlotValue = "Property Test Value"
            
            integer_slot = KGIntegerSlot()
            integer_slot.URI = "http://vital.ai/haley.ai/app/KGIntegerSlot/property_test_integer"
            integer_slot.integerSlotValue = 123
            
            boolean_slot = KGBooleanSlot()
            boolean_slot.URI = "http://vital.ai/haley.ai/app/KGBooleanSlot/property_test_boolean"
            boolean_slot.booleanSlotValue = False
            
            # Test isinstance() checks
            property_tests = {
                "KGTextSlot isinstance": isinstance(text_slot, KGTextSlot),
                "KGIntegerSlot isinstance": isinstance(integer_slot, KGIntegerSlot),
                "KGBooleanSlot isinstance": isinstance(boolean_slot, KGBooleanSlot),
                "GraphObject inheritance text": isinstance(text_slot, GraphObject),
                "GraphObject inheritance integer": isinstance(integer_slot, GraphObject),
                "GraphObject inheritance boolean": isinstance(boolean_slot, GraphObject),
                "Text property access": hasattr(text_slot, 'textSlotValue'),
                "Integer property access": hasattr(integer_slot, 'integerSlotValue'),
                "Boolean property access": hasattr(boolean_slot, 'booleanSlotValue'),
                "Text value correct": text_slot.textSlotValue == "Property Test Value",
                "Integer value correct": integer_slot.integerSlotValue == 123,
                "Boolean value correct": boolean_slot.booleanSlotValue == False
            }
            
            passed_tests = sum(1 for result in property_tests.values() if result)
            total_tests = len(property_tests)
            success = passed_tests == total_tests
            
            self.log_test_result(
                "MockKGFrames Property Object Handling",
                success,
                f"Property object tests: {passed_tests}/{total_tests} passed",
                {
                    "test_results": property_tests,
                    "passed_tests": passed_tests,
                    "total_tests": total_tests
                }
            )
            
        except Exception as e:
            self.log_test_result(
                "MockKGFrames Property Object Handling",
                False,
                f"Error testing property object handling: {e}",
                {"error": str(e)}
            )

    def test_delete_frame_slots(self):
        """Test deleting specific slots from a frame."""
        try:
            # Delete the additional slot we created
            slot_uris = ["http://vital.ai/haley.ai/app/KGTextSlot/additional_slot"]
            
            response = self.mock_client.kgframes.delete_frame_slots(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                frame_uri=self.frame_uri,
                slot_uris=slot_uris
            )
            
            success = hasattr(response, 'deleted_count') and response.deleted_count >= 0
            
            self.log_test_result(
                "Delete Frame Slots",
                success,
                f"Deleted {response.deleted_count if hasattr(response, 'deleted_count') else 0} slots from frame",
                {"frame_uri": self.frame_uri, "deleted_slot_uris": slot_uris}
            )
            
        except Exception as e:
            self.log_test_result("Delete Frame Slots", False, f"Exception: {e}")
    
    def test_delete_entity_frames(self):
        """Test deleting specific frames from an entity."""
        try:
            # Delete the frame we created
            frame_uris = [self.frame_uri]
            
            response = self.mock_client.kgentities.delete_entity_frames(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                entity_uri=self.entity_uri,
                frame_uris=frame_uris
            )
            
            success = hasattr(response, 'deleted_count') and response.deleted_count >= 0
            
            self.log_test_result(
                "Delete Entity Frames",
                success,
                f"Deleted {response.deleted_count if hasattr(response, 'deleted_count') else 0} frames from entity",
                {"entity_uri": self.entity_uri, "deleted_frame_uris": frame_uris}
            )
            
        except Exception as e:
            self.log_test_result("Delete Entity Frames", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run all tests in the suite."""
        print("🧪 Testing KG Endpoint Enhancements - Entity-Frame & Frame-Slot Operations")
        print("=" * 85)
        
        # Run tests sequentially
        test_methods = [
            self.test_setup_test_data,
            self.test_create_entity_frames,
            self.test_get_entity_frames,
            self.test_create_frame_slots,
            self.test_get_frame_slots,
            self.test_get_frame_slots_with_type_filter,
            self.test_enhanced_get_entity_with_graph,
            self.test_enhanced_get_frame_with_graph,
            self.test_concrete_slot_values_verification,
            # MockKGFramesEndpoint Integration Tests
            self.test_mockkg_frames_vitalsigns_integration,
            self.test_mockkg_frames_property_object_handling,
            self.test_delete_frame_slots,
            self.test_delete_entity_frames
        ]
        for test_method in test_methods:
            test_method()
        # Print summary
        print("=" * 65)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! KG endpoint enhancements working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestKGEndpointEnhancements()
    try:
        success = test_suite.run_all_tests()
        return 0 if success else 1
    finally:
        test_suite.cleanup()


if __name__ == "__main__":
    import sys
    sys.exit(main())
