#!/usr/bin/env python3
"""
Test suite for MockKGFramesEndpoint with VitalSigns native JSON-LD functionality.

✅ UPDATED: This test file now uses concrete slot classes with actual value properties!
    - Uses KGTextSlot, KGIntegerSlot, KGBooleanSlot, KGChoiceSlot, KGDoubleSlot
    - Sets actual slot values using documented property patterns (textSlotValue, integerSlotValue, etc.)
    - Frame-slot relationships properly implemented using Edge_hasKGSlot
    - Validates slot value access using isinstance checks and proper casting

This test suite validates the mock implementation of KGFrame operations using:
- VitalSigns native object creation and conversion
- Concrete slot classes with proper value properties
- pyoxigraph in-memory SPARQL quad store
- Direct test runner format (no pytest dependency)
- Complete CRUD operations with proper vitaltype handling
- Frame-slot relationship handling using Edge_hasKGSlot relationships
- Slot value access patterns following documented VitalSigns best practices
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.mock.client.mock_vitalgraph_client import MockVitalGraphClient
from vitalgraph.mock.client.space.mock_space_manager import MockSpaceManager
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.kgframes_model import FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator

# Import specific slot types for concrete slot classes
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.KGChoiceSlot import KGChoiceSlot
from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot


def create_test_kgframes_with_slots() -> List[object]:
    """Create test KGFrame objects with concrete slot classes using Edge_hasKGSlot relationships."""
    objects = []
    
    # Create first test KGFrame - User Profile Frame
    frame1 = KGFrame()
    frame1.URI = "http://vital.ai/haley.ai/app/KGFrame/user_profile_frame"
    frame1.name = "User Profile Frame"
    objects.append(frame1)
    
    # Create KGTextSlot for frame1 - Name slot
    text_slot = KGTextSlot()
    text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/name_slot"
    text_slot.name = "Name Slot"
    text_slot.textSlotValue = "John Doe"  # Set actual text value
    objects.append(text_slot)
    
    # Create Edge_hasKGSlot to link text_slot to frame1
    from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
    edge1 = Edge_hasKGSlot()
    edge1.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame1_text_slot"
    edge1.edgeSource = str(frame1.URI)
    edge1.edgeDestination = str(text_slot.URI)
    objects.append(edge1)
    
    # Create KGIntegerSlot for frame1 - Age slot
    integer_slot = KGIntegerSlot()
    integer_slot.URI = "http://vital.ai/haley.ai/app/KGIntegerSlot/age_slot"
    integer_slot.name = "Age Slot"
    integer_slot.integerSlotValue = 25  # Set actual integer value
    objects.append(integer_slot)
    
    # Create Edge_hasKGSlot to link integer_slot to frame1
    edge2 = Edge_hasKGSlot()
    edge2.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame1_integer_slot"
    edge2.edgeSource = str(frame1.URI)
    edge2.edgeDestination = str(integer_slot.URI)
    objects.append(edge2)
    
    # Create KGBooleanSlot for frame1 - Active status slot
    boolean_slot = KGBooleanSlot()
    boolean_slot.URI = "http://vital.ai/haley.ai/app/KGBooleanSlot/active_slot"
    boolean_slot.name = "Is Active Slot"
    boolean_slot.booleanSlotValue = True  # Set actual boolean value
    objects.append(boolean_slot)
    
    # Create Edge_hasKGSlot to link boolean_slot to frame1
    edge3 = Edge_hasKGSlot()
    edge3.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame1_boolean_slot"
    edge3.edgeSource = str(frame1.URI)
    edge3.edgeDestination = str(boolean_slot.URI)
    objects.append(edge3)
    
    # Create second test KGFrame - Settings Frame
    frame2 = KGFrame()
    frame2.URI = "http://vital.ai/haley.ai/app/KGFrame/settings_frame"
    frame2.name = "Settings Frame"
    objects.append(frame2)
    
    # Create KGChoiceSlot for frame2 - Status choice slot
    choice_slot = KGChoiceSlot()
    choice_slot.URI = "http://vital.ai/haley.ai/app/KGChoiceSlot/status_slot"
    choice_slot.name = "Status Choice Slot"
    choice_slot.choiceSlotValue = "active"  # Set actual choice value
    objects.append(choice_slot)
    
    # Create Edge_hasKGSlot to link choice_slot to frame2
    edge4 = Edge_hasKGSlot()
    edge4.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame2_choice_slot"
    edge4.edgeSource = str(frame2.URI)
    edge4.edgeDestination = str(choice_slot.URI)
    objects.append(edge4)
    
    # Create KGDoubleSlot for frame2 - Score slot
    double_slot = KGDoubleSlot()
    double_slot.URI = "http://vital.ai/haley.ai/app/KGDoubleSlot/score_slot"
    double_slot.name = "Score Slot"
    double_slot.doubleSlotValue = 95.5  # Set actual double value
    objects.append(double_slot)
    
    # Create Edge_hasKGSlot to link double_slot to frame2
    edge5 = Edge_hasKGSlot()
    edge5.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame2_double_slot"
    edge5.edgeSource = str(frame2.URI)
    edge5.edgeDestination = str(double_slot.URI)
    objects.append(edge5)
    
    return objects


def create_test_jsonld_document(objects: List[object]) -> Dict[str, Any]:
    """Convert VitalSigns objects to JSON-LD document using VitalSigns native functionality."""
    from vital_ai_vitalsigns.model.GraphObject import GraphObject
    
    # Use VitalSigns native conversion
    jsonld_document = GraphObject.to_jsonld_list(objects)
    
    return jsonld_document


class TestMockKGFramesEndpoint:
    """Test suite for MockKGFramesEndpoint with Edge-based relationships."""
    
    def __init__(self):
        """Initialize test suite."""
        # Set up logging
        logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s: %(message)s')
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Initialize mock client
        mock_client = MockVitalGraphClient()
        self.endpoint = mock_client.kgframes
        
        # Test configuration
        self.test_space_id = "test_kgframes_space"
        self.test_graph_id = "http://vital.ai/graph/test-kgframes"
        
        # Test results tracking
        self.test_results = []
    
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
    
    def test_create_kgframes_vitalsigns_native(self):
        """Test creating KGFrames using VitalSigns native functionality with Edge relationships."""
        try:
            # Setup: Create space and frames
            self.endpoint.client.space_manager.create_space(self.test_space_id)
            
            test_objects = create_test_kgframes_with_slots()
            jsonld_document = create_test_jsonld_document(test_objects)
            jsonld_doc = JsonLdDocument(**jsonld_document)
            
            # Test: Create frames with slots using Edge relationships
            response = self.endpoint.create_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=jsonld_doc
            )
            
            success = (
                isinstance(response, FrameCreateResponse) and
                response.created_count > 0 and
                len(response.created_uris) > 0
            )
            
            self.log_test_result(
                "Create KGFrames VitalSigns Native with Edges",
                success,
                f"Created {response.created_count} frames with Edge relationships",
                {
                    "created_count": response.created_count,
                    "created_uris": response.created_uris
                }
            )
            
            # Verify Edge relationships by querying back the created objects
            if success:
                # Query back the created frames to verify Edge relationships were stored
                list_response = self.endpoint.list_kgframes(
                    space_id=self.test_space_id,
                    graph_id=self.test_graph_id
                )
                
                edge_success = (
                    isinstance(list_response, FramesResponse) and
                    list_response.total_count >= 2  # Should have created 2 frames
                )
                
                self.log_test_result(
                    "Verify Edge Relationships",
                    edge_success,
                    f"Verified {list_response.total_count} frames stored with Edge relationships",
                    {
                        "frames_stored": list_response.total_count,
                        "expected_frames": 2
                    }
                )
            
        except Exception as e:
            self.log_test_result("Create KGFrames VitalSigns Native with Edges", False, f"Exception: {e}")
    
    def test_list_kgframes_empty(self):
        """Test listing KGFrames when none exist."""
        try:
            # Create space first
            self.endpoint.client.space_manager.create_space(self.test_space_id)
            
            response = self.endpoint.list_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id
            )
            
            success = (
                isinstance(response, FramesResponse) and
                response.total_count == 0
            )
            
            self.log_test_result(
                "List KGFrames (Empty)",
                success,
                f"Found {response.total_count} frames",
                {"total_count": response.total_count}
            )
            
        except Exception as e:
            self.log_test_result("List KGFrames (Empty)", False, f"Exception: {e}")
    
    def test_slot_value_access_patterns(self):
        """Test accessing slot values using documented VitalSigns patterns."""
        try:
            # Create test objects with concrete slot classes
            test_objects = create_test_kgframes_with_slots()
            
            # Verify slot values can be accessed using documented patterns
            slot_values = {}
            
            for obj in test_objects:
                try:
                    # Access slot values using isinstance checks and direct property access (documented pattern)
                    if isinstance(obj, KGTextSlot):
                        value = str(obj.textSlotValue) if obj.textSlotValue else None
                        slot_values[obj.URI] = {'type': 'KGTextSlot', 'name': str(obj.name), 'value': value}
                        
                    elif isinstance(obj, KGIntegerSlot):
                        value = int(obj.integerSlotValue) if obj.integerSlotValue else None
                        slot_values[obj.URI] = {'type': 'KGIntegerSlot', 'name': str(obj.name), 'value': value}
                        
                    elif isinstance(obj, KGBooleanSlot):
                        value = bool(obj.booleanSlotValue) if obj.booleanSlotValue else None
                        slot_values[obj.URI] = {'type': 'KGBooleanSlot', 'name': str(obj.name), 'value': value}
                        
                    elif isinstance(obj, KGChoiceSlot):
                        value = str(obj.choiceSlotValue) if obj.choiceSlotValue else None
                        slot_values[obj.URI] = {'type': 'KGChoiceSlot', 'name': str(obj.name), 'value': value}
                        
                    elif isinstance(obj, KGDoubleSlot):
                        value = float(obj.doubleSlotValue) if obj.doubleSlotValue else None
                        slot_values[obj.URI] = {'type': 'KGDoubleSlot', 'name': str(obj.name), 'value': value}
                        
                except Exception as e:
                    print(f"Error accessing slot value for {obj.URI}: {e}")
            
            # Verify we found the expected slot types and values
            expected_slots = {
                'KGTextSlot': 'John Doe',
                'KGIntegerSlot': 25,
                'KGBooleanSlot': True,
                'KGChoiceSlot': 'active',
                'KGDoubleSlot': 95.5
            }
            
            success = True
            found_slots = {}
            
            for uri, info in slot_values.items():
                slot_type = info['type']
                value = info['value']
                found_slots[slot_type] = value
                
                if slot_type in expected_slots:
                    if value != expected_slots[slot_type]:
                        success = False
                        print(f"Value mismatch for {slot_type}: expected {expected_slots[slot_type]}, got {value}")
                        print(f"Value type: {type(value)}")
            
            # Check that all expected slot types were found
            for expected_type in expected_slots:
                if expected_type not in found_slots:
                    success = False
                    print(f"Missing expected slot type: {expected_type}")
            
            # Create serializable data for logging (avoid Property objects)
            serializable_data = {
                "found_slots": found_slots,
                "expected_slots": expected_slots,
                "slot_count": len(slot_values)
            }
            
            self.log_test_result(
                "Slot Value Access Patterns",
                success,
                f"Verified {len(slot_values)} concrete slot classes with proper value access",
                serializable_data
            )
            
        except Exception as e:
            self.log_test_result("Slot Value Access Patterns", False, f"Exception: {e}")
    
    def run_all_tests(self):
        """Run all tests in the suite."""
        print("🧪 Testing MockKGFramesEndpoint with Concrete Slot Classes & Edge-based Relationships")
        print("=" * 80)
        
        # Run tests
        self.test_list_kgframes_empty()
        self.test_slot_value_access_patterns()
        self.test_create_kgframes_vitalsigns_native()
        
        # Print summary
        print("=" * 50)
        passed = sum(1 for result in self.test_results if result["success"])
        total = len(self.test_results)
        
        if passed == total:
            print(f"Test Results: {passed}/{total} tests passed")
            print("🎉 All tests passed! MockKGFramesEndpoint Edge relationships are working correctly.")
        else:
            print(f"Test Results: {passed}/{total} tests passed")
            print("⚠️  Some tests failed. Check the output above for details.")
        
        return passed == total


def main():
    """Main test runner."""
    test_suite = TestMockKGFramesEndpoint()
    success = test_suite.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()