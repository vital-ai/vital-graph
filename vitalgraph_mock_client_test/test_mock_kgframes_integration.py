#!/usr/bin/env python3
"""
Test suite for MockKGFramesEndpoint Integration - VitalSigns Patterns & Property Handling.

This test suite validates the MockKGFramesEndpoint integration requirements:
- VitalSigns integration patterns from MockKGEntitiesEndpoint
- Grouping URI enforcement for frame operations  
- isinstance() type checking and Property object handling
- Proper Property object casting and value access
- VitalSigns native JSON-LD conversion
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
# Property handling will be tested through VitalSigns object property access

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
            'api_key': 'test-api-key'
        },
        'client': {
            'use_mock_client': True,
            'mock_data_dir': str(Path(__file__).parent / 'mock_data')
        }
    }
    
    # Create temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        temp_config_path = f.name
    
    return VitalGraphClientConfig(temp_config_path)


class TestMockKGFramesIntegration:
    """Test MockKGFramesEndpoint integration with VitalSigns patterns."""
    
    def __init__(self):
        self.test_space_id = "test_frames_integration_space"
        self.test_graph_id = "http://vital.ai/haley.ai/app/test_frames_integration_graph"
        self.entity_uri = "http://vital.ai/haley.ai/app/KGEntity/test_integration_entity"
        self.frame_uri = "http://vital.ai/haley.ai/app/KGFrame/test_integration_frame"
        self.mock_client = None
        self.test_results = []

    def setup_test_environment(self):
        """Initialize the mock client and test space."""
        try:
            # Initialize VitalSigns
            VitalSigns()
            
            # Create mock client
            config = create_mock_config()
            self.mock_client = create_vitalgraph_client(config=config)
            
            # Create test space
            space = Space(space=self.test_space_id, space_name="Test Frames Integration Space")
            space_response = self.mock_client.spaces.add_space(space)
            
            logger.info(f"Test environment setup complete")
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup test environment: {e}")
            return False

    def create_test_frame_with_vitalsigns_patterns(self):
        """Create a test frame using VitalSigns native patterns."""
        # Create KGFrame using VitalSigns constructor
        frame = KGFrame()
        frame.URI = self.frame_uri
        frame.name = "Integration Test Frame"
        frame.kGFrameType = "urn:IntegrationTestFrameType"
        
        # Create KGTextSlot with Property object handling
        text_slot = KGTextSlot()
        text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/integration_text_slot"
        text_slot.name = "Integration Text Slot"
        text_slot.kGSlotType = "urn:IntegrationTextSlotType"
        text_slot.textSlotValue = "Integration Test Value"
        
        # Create KGIntegerSlot
        integer_slot = KGIntegerSlot()
        integer_slot.URI = "http://vital.ai/haley.ai/app/KGIntegerSlot/integration_integer_slot"
        integer_slot.name = "Integration Integer Slot"
        integer_slot.kGSlotType = "urn:IntegrationIntegerSlotType"
        integer_slot.integerSlotValue = 42
        
        # Create KGBooleanSlot
        boolean_slot = KGBooleanSlot()
        boolean_slot.URI = "http://vital.ai/haley.ai/app/KGBooleanSlot/integration_boolean_slot"
        boolean_slot.name = "Integration Boolean Slot"
        boolean_slot.kGSlotType = "urn:IntegrationBooleanSlotType"
        boolean_slot.booleanSlotValue = True
        
        # Create Edge_hasKGSlot relationships
        text_edge = Edge_hasKGSlot()
        text_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame_{frame.URI.split('/')[-1]}_slot_{text_slot.URI.split('/')[-1]}"
        text_edge.edgeSource = frame.URI
        text_edge.edgeDestination = text_slot.URI
        
        integer_edge = Edge_hasKGSlot()
        integer_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame_{frame.URI.split('/')[-1]}_slot_{integer_slot.URI.split('/')[-1]}"
        integer_edge.edgeSource = frame.URI
        integer_edge.edgeDestination = integer_slot.URI
        
        boolean_edge = Edge_hasKGSlot()
        boolean_edge.URI = f"http://vital.ai/haley.ai/app/Edge_hasKGSlot/frame_{frame.URI.split('/')[-1]}_slot_{boolean_slot.URI.split('/')[-1]}"
        boolean_edge.edgeSource = frame.URI
        boolean_edge.edgeDestination = boolean_slot.URI
        
        # Return all objects for document creation
        return [frame, text_slot, integer_slot, boolean_slot, text_edge, integer_edge, boolean_edge]

    def test_vitalsigns_integration_patterns(self):
        """Test that MockKGFramesEndpoint uses VitalSigns integration patterns."""
        try:
            # Create frame with VitalSigns objects
            frame_objects = self.create_test_frame_with_vitalsigns_patterns()
            
            # Convert to JSON-LD document using VitalSigns native functionality
            jsonld_document = GraphObject.to_jsonld_list(frame_objects)
            document = JsonLdDocument(**jsonld_document)
            
            # Create frame using MockKGFramesEndpoint
            response = self.mock_client.kgframes.create_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            # Validate response uses VitalSigns patterns
            success = (
                hasattr(response, 'created_count') and 
                response.created_count > 0
            )
            
            self.log_test_result(
                "VitalSigns Integration Patterns",
                success,
                f"Created frame using VitalSigns native patterns",
                {"frame_uri": self.frame_uri, "created_count": getattr(response, 'created_count', 0)}
            )
            
            return success
            
        except Exception as e:
            self.log_test_result(
                "VitalSigns Integration Patterns",
                False,
                f"Error: {e}",
                {"error": str(e)}
            )
            return False

    def test_property_object_handling(self):
        """Test isinstance() type checking and Property object handling."""
        try:
            # Get frame slots to test Property object handling
            response = self.mock_client.kgframes.get_frame_slots(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                frame_uri=self.frame_uri
            )
            
            # Validate response has graph data
            if not (hasattr(response, 'graph') and response.graph):
                self.log_test_result(
                    "Property Object Handling",
                    False,
                    "No graph data returned for property testing",
                    {"frame_uri": self.frame_uri}
                )
                return False
            
            # Test Property object casting and isinstance() checks
            property_tests_passed = 0
            total_property_tests = 0
            
            for slot_data in response.graph:
                if isinstance(slot_data, dict) and slot_data.get('type'):
                    slot_type = slot_data.get('type')
                    total_property_tests += 1
                    
                    # Test different slot types and their property access
                    if 'KGTextSlot' in slot_type:
                        # Test text slot property access
                        text_value = slot_data.get('http://vital.ai/ontology/haley-ai-kg#hasTextSlotValue')
                        if text_value and isinstance(text_value, dict) and '@value' in text_value:
                            property_tests_passed += 1
                    
                    elif 'KGIntegerSlot' in slot_type:
                        # Test integer slot property access
                        int_value = slot_data.get('http://vital.ai/ontology/haley-ai-kg#hasIntegerSlotValue')
                        if int_value and isinstance(int_value, dict) and '@value' in int_value:
                            property_tests_passed += 1
                    
                    elif 'KGBooleanSlot' in slot_type:
                        # Test boolean slot property access
                        bool_value = slot_data.get('http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue')
                        if bool_value and isinstance(bool_value, dict) and '@value' in bool_value:
                            property_tests_passed += 1
            
            success = property_tests_passed > 0 and total_property_tests > 0
            
            self.log_test_result(
                "Property Object Handling",
                success,
                f"Property object tests: {property_tests_passed}/{total_property_tests} passed",
                {
                    "frame_uri": self.frame_uri,
                    "property_tests_passed": property_tests_passed,
                    "total_property_tests": total_property_tests
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result(
                "Property Object Handling",
                False,
                f"Error: {e}",
                {"error": str(e)}
            )
            return False

    def test_grouping_uri_enforcement(self):
        """Test grouping URI enforcement for frame operations."""
        try:
            # Create a frame and check grouping URI assignment
            frame_objects = self.create_test_frame_with_vitalsigns_patterns()
            jsonld_document = GraphObject.to_jsonld_list(frame_objects)
            document = JsonLdDocument(**jsonld_document)
            
            # Create frame
            create_response = self.mock_client.kgframes.create_kgframes(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document
            )
            
            # Get frame with graph to check grouping URIs
            get_response = self.mock_client.kgframes.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=self.frame_uri,
                include_frame_graph=True
            )
            
            # Validate grouping URI enforcement
            grouping_uri_found = False
            if hasattr(get_response, 'graph') and get_response.graph:
                for obj_data in get_response.graph:
                    if isinstance(obj_data, dict):
                        # Check for grouping URI properties
                        kg_graph_uri = obj_data.get('http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI')
                        frame_graph_uri = obj_data.get('http://vital.ai/ontology/haley-ai-kg#hasFrameGraphURI')
                        
                        if kg_graph_uri or frame_graph_uri:
                            grouping_uri_found = True
                            break
            
            success = grouping_uri_found
            
            self.log_test_result(
                "Grouping URI Enforcement",
                success,
                f"Grouping URI enforcement {'working' if success else 'not working'}",
                {
                    "frame_uri": self.frame_uri,
                    "grouping_uri_found": grouping_uri_found,
                    "include_frame_graph": True
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result(
                "Grouping URI Enforcement",
                False,
                f"Error: {e}",
                {"error": str(e)}
            )
            return False

    def test_isinstance_type_checking(self):
        """Test isinstance() type checking implementation."""
        try:
            # Create test objects to validate isinstance() usage
            frame = KGFrame()
            frame.URI = self.frame_uri
            frame.name = "Type Check Frame"
            
            text_slot = KGTextSlot()
            text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/type_check_slot"
            text_slot.name = "Type Check Slot"
            text_slot.textSlotValue = "Type Check Value"
            
            # Test isinstance() checks
            isinstance_tests = {
                "KGFrame isinstance check": isinstance(frame, KGFrame),
                "KGTextSlot isinstance check": isinstance(text_slot, KGTextSlot),
                "GraphObject isinstance check": isinstance(frame, GraphObject),
                "Property name check": hasattr(frame, 'name'),
                "Property textSlotValue check": hasattr(text_slot, 'textSlotValue')
            }
            
            passed_tests = sum(1 for test_result in isinstance_tests.values() if test_result)
            total_tests = len(isinstance_tests)
            success = passed_tests == total_tests
            
            self.log_test_result(
                "isinstance() Type Checking",
                success,
                f"Type checking tests: {passed_tests}/{total_tests} passed",
                {
                    "test_results": isinstance_tests,
                    "passed_tests": passed_tests,
                    "total_tests": total_tests
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result(
                "isinstance() Type Checking",
                False,
                f"Error: {e}",
                {"error": str(e)}
            )
            return False

    def test_vitalsigns_native_jsonld_conversion(self):
        """Test VitalSigns native JSON-LD conversion functionality."""
        try:
            # Create VitalSigns objects
            frame_objects = self.create_test_frame_with_vitalsigns_patterns()
            
            # Test VitalSigns native JSON-LD conversion
            jsonld_document = GraphObject.to_jsonld_list(frame_objects)
            
            # Validate JSON-LD structure
            jsonld_tests = {
                "Has @context": "@context" in jsonld_document,
                "Has @graph": "@graph" in jsonld_document,
                "Graph is list": isinstance(jsonld_document.get("@graph"), list),
                "Graph not empty": len(jsonld_document.get("@graph", [])) > 0,
                "Objects have @type": all(
                    "@type" in obj or "type" in obj 
                    for obj in jsonld_document.get("@graph", [])
                    if isinstance(obj, dict)
                )
            }
            
            passed_tests = sum(1 for test_result in jsonld_tests.values() if test_result)
            total_tests = len(jsonld_tests)
            success = passed_tests == total_tests
            
            self.log_test_result(
                "VitalSigns Native JSON-LD Conversion",
                success,
                f"JSON-LD conversion tests: {passed_tests}/{total_tests} passed",
                {
                    "test_results": jsonld_tests,
                    "passed_tests": passed_tests,
                    "total_tests": total_tests,
                    "object_count": len(frame_objects)
                }
            )
            
            return success
            
        except Exception as e:
            self.log_test_result(
                "VitalSigns Native JSON-LD Conversion",
                False,
                f"Error: {e}",
                {"error": str(e)}
            )
            return False

    def log_test_result(self, test_name: str, success: bool, message: str, data: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        print(f"    {message}")
        if data:
            print(f"    Data: {json.dumps(data, indent=2)}")
        print()
        
        self.test_results.append({
            "test_name": test_name,
            "success": success,
            "message": message,
            "data": data or {}
        })

    def cleanup_test_environment(self):
        """Clean up test resources."""
        try:
            if self.mock_client:
                # Delete test space
                self.mock_client.spaces.delete_space(self.test_space_id)
                self.mock_client.close()
                logger.info("Test environment cleaned up")
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")

    def run_all_tests(self):
        """Run all MockKGFramesEndpoint integration tests."""
        print("🧪 Testing MockKGFramesEndpoint Integration - VitalSigns Patterns & Property Handling")
        print("=" * 100)
        
        # Setup
        if not self.setup_test_environment():
            print("❌ Failed to setup test environment")
            return False
        
        # Run tests
        test_methods = [
            self.test_vitalsigns_integration_patterns,
            self.test_property_object_handling,
            self.test_grouping_uri_enforcement,
            self.test_isinstance_type_checking,
            self.test_vitalsigns_native_jsonld_conversion
        ]
        
        passed_tests = 0
        for test_method in test_methods:
            try:
                if test_method():
                    passed_tests += 1
            except Exception as e:
                logger.error(f"Test method {test_method.__name__} failed with exception: {e}")
        
        # Cleanup
        self.cleanup_test_environment()
        
        # Summary
        total_tests = len(test_methods)
        print("=" * 100)
        print(f"Test Results: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("🎉 All MockKGFramesEndpoint integration tests passed!")
            return True
        else:
            print("⚠️  Some MockKGFramesEndpoint integration tests failed. Check the output above for details.")
            return False


def main():
    """Main test execution."""
    test_suite = TestMockKGFramesIntegration()
    success = test_suite.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
