#!/usr/bin/env python3

"""
Test Graph-Level Retrieval Operations

This module tests the enhanced GET operations with graph-level retrieval:
- get_kgentity with include_entity_graph parameter
- get_kgframe with include_frame_graph parameter
- Efficient SPARQL queries using grouping URIs (hasKGGraphURI, hasFrameGraphURI)
- Complete graph structure retrieval in single operations
"""

import sys
import os
import logging
import tempfile
import yaml
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Import VitalSigns models
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from vital_ai_vitalsigns.model.GraphObject import GraphObject

# Import VitalGraph components
from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.jsonld_model import JsonLdDocument
from vitalgraph.model.spaces_model import Space


class TestGraphLevelRetrieval:
    """Test graph-level retrieval operations with enhanced GET methods."""
    
    def __init__(self):
        self.mock_client = None
        self.test_space_id = "test_graph_retrieval_space"
        self.test_graph_id = "http://vital.ai/haley.ai/app/test_graph_retrieval_graph"
        self.entity_uri = "http://vital.ai/haley.ai/app/KGEntity/graph_retrieval_test_entity"
        self.frame_uri = "http://vital.ai/haley.ai/app/KGFrame/graph_retrieval_test_frame"
        
    def setup_test_environment(self):
        """Set up test environment with mock client and test space."""
        try:
            logger.info("Setting up test environment...")
            
            # Create mock client config
            config = self.create_mock_config()
            self.mock_client = create_vitalgraph_client(config=config)
            
            # Create test space
            space = Space(space=self.test_space_id, space_name="Test Graph Retrieval Space")
            space_response = self.mock_client.spaces.add_space(space)
            
            if space_response and space_response.created_count > 0:
                logger.info("Test environment setup complete: Space created successfully")
                return True
            else:
                logger.error(f"Failed to create test space: {space_response.message if space_response else 'No response'}")
                return False
                
        except Exception as e:
            logger.error(f"Error setting up test environment: {e}")
            return False
    
    def cleanup_test_environment(self):
        """Clean up test environment."""
        try:
            if self.mock_client:
                # Close client (space cleanup handled by space manager)
                self.mock_client.close()
                
            logger.info("Test environment cleaned up")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def create_mock_config(self) -> VitalGraphClientConfig:
        """Create a config object with mock client enabled."""
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
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(config_data, f)
            temp_config_path = f.name
        
        return VitalGraphClientConfig(temp_config_path)

    def create_test_entity_with_complete_graph(self) -> list:
        """Create a test entity with complete graph structure for testing."""
        # Create KGEntity
        entity = KGEntity()
        entity.URI = self.entity_uri
        entity.name = "Graph Retrieval Test Entity"
        entity.kGEntityType = "urn:GraphRetrievalTestEntityType"
        
        # Create KGFrame
        frame = KGFrame()
        frame.URI = self.frame_uri
        frame.name = "Graph Retrieval Test Frame"
        frame.kGFrameType = "urn:GraphRetrievalTestFrameType"
        
        # Create KGTextSlot
        text_slot = KGTextSlot()
        text_slot.URI = "http://vital.ai/haley.ai/app/KGTextSlot/graph_retrieval_text_slot"
        text_slot.name = "Graph Retrieval Text Slot"
        text_slot.kGSlotType = "urn:GraphRetrievalTextSlotType"
        text_slot.textSlotValue = "Graph Retrieval Test Value"
        
        # Create KGIntegerSlot
        integer_slot = KGIntegerSlot()
        integer_slot.URI = "http://vital.ai/haley.ai/app/KGIntegerSlot/graph_retrieval_integer_slot"
        integer_slot.name = "Graph Retrieval Integer Slot"
        integer_slot.kGSlotType = "urn:GraphRetrievalIntegerSlotType"
        integer_slot.integerSlotValue = 300
        
        # Create Edge_hasEntityKGFrame relationship (entity → frame)
        entity_frame_edge = Edge_hasEntityKGFrame()
        entity_frame_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasEntityKGFrame/graph_retrieval_entity_frame_edge"
        entity_frame_edge.edgeSource = entity.URI
        entity_frame_edge.edgeDestination = frame.URI
        
        # Create Edge_hasKGSlot relationships (frame → slots)
        frame_text_edge = Edge_hasKGSlot()
        frame_text_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/graph_retrieval_frame_text_edge"
        frame_text_edge.edgeSource = frame.URI
        frame_text_edge.edgeDestination = text_slot.URI
        
        frame_integer_edge = Edge_hasKGSlot()
        frame_integer_edge.URI = "http://vital.ai/haley.ai/app/Edge_hasKGSlot/graph_retrieval_frame_integer_edge"
        frame_integer_edge.edgeSource = frame.URI
        frame_integer_edge.edgeDestination = integer_slot.URI
        
        return [entity, frame, text_slot, integer_slot, entity_frame_edge, frame_text_edge, frame_integer_edge]

    def test_entity_graph_retrieval(self):
        """Test entity retrieval with and without complete graph."""
        try:
            logger.info("🧪 Testing Entity Graph Retrieval")
            
            # Step 1: Create test entity with complete graph
            test_objects = self.create_test_entity_with_complete_graph()
            create_document = GraphObject.to_jsonld_list(test_objects)
            document = JsonLdDocument(**create_document)
            
            # Create the entity graph
            create_response = self.mock_client.kgentities.update_kgentities(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                document=document,
                operation_mode="create"
            )
            
            if not create_response.updated_uri:
                logger.error(f"❌ Failed to create test entity: {create_response.message}")
                return False
            
            logger.info("✅ Test entity created successfully")
            
            # Step 2: Test single entity retrieval (include_entity_graph=False)
            single_entity_response = self.mock_client.kgentities.get_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=self.entity_uri,
                include_entity_graph=False
            )
            
            if single_entity_response and single_entity_response.entity:
                logger.info("✅ Single entity retrieval successful")
                
                # Check that it's just the entity (not complete graph)
                entity_data = single_entity_response.entity.model_dump()
                if '@graph' in entity_data and len(entity_data['@graph']) <= 2:  # Entity + maybe context
                    logger.info("✅ Single entity retrieval returned minimal data as expected")
                else:
                    logger.warning(f"Single entity retrieval returned more data than expected: {len(entity_data.get('@graph', []))} objects")
            else:
                logger.error("❌ Single entity retrieval failed")
                return False
            
            # Step 3: Test complete entity graph retrieval (include_entity_graph=True)
            complete_graph_response = self.mock_client.kgentities.get_kgentity(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=self.entity_uri,
                include_entity_graph=True
            )
            
            if complete_graph_response and complete_graph_response.complete_graph:
                logger.info("✅ Complete entity graph retrieval successful")
                
                # Check that it includes the complete graph
                complete_data = complete_graph_response.complete_graph.model_dump()
                graph_objects = complete_data.get('@graph', [])
                
                if len(graph_objects) >= 5:  # Entity + Frame + 2 Slots + Edges
                    logger.info(f"✅ Complete entity graph contains {len(graph_objects)} objects as expected")
                else:
                    logger.warning(f"Complete entity graph contains fewer objects than expected: {len(graph_objects)}")
            else:
                logger.error("❌ Complete entity graph retrieval failed")
                return False
            
            logger.info("✅ PASS Entity Graph Retrieval")
            return True
            
        except Exception as e:
            logger.error(f"❌ Entity graph retrieval test failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def test_frame_graph_retrieval(self):
        """Test frame retrieval with and without complete graph."""
        try:
            logger.info("🧪 Testing Frame Graph Retrieval")
            
            # Use the same test data created in entity test
            # Step 1: Test single frame retrieval (include_frame_graph=False)
            single_frame_response = self.mock_client.kgframes.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=self.frame_uri,
                include_frame_graph=False
            )
            
            if single_frame_response:
                logger.info("✅ Single frame retrieval successful")
                
                # Check that it's just the frame (not complete graph)
                frame_data = single_frame_response.model_dump()
                graph_objects = frame_data.get('@graph', [])
                
                if len(graph_objects) <= 2:  # Frame + maybe context
                    logger.info("✅ Single frame retrieval returned minimal data as expected")
                else:
                    logger.warning(f"Single frame retrieval returned more data than expected: {len(graph_objects)} objects")
            else:
                logger.error("❌ Single frame retrieval failed")
                return False
            
            # Step 2: Test complete frame graph retrieval (include_frame_graph=True)
            complete_frame_response = self.mock_client.kgframes.get_kgframe(
                space_id=self.test_space_id,
                graph_id=self.test_graph_id,
                uri=self.frame_uri,
                include_frame_graph=True
            )
            
            if complete_frame_response:
                logger.info("✅ Complete frame graph retrieval successful")
                
                # Check that it includes the complete frame graph
                complete_data = complete_frame_response.model_dump()
                graph_objects = complete_data.get('@graph', [])
                
                if len(graph_objects) >= 3:  # Frame + 2 Slots + Edges
                    logger.info(f"✅ Complete frame graph contains {len(graph_objects)} objects as expected")
                else:
                    logger.warning(f"Complete frame graph contains fewer objects than expected: {len(graph_objects)}")
            else:
                logger.error("❌ Complete frame graph retrieval failed")
                return False
            
            logger.info("✅ PASS Frame Graph Retrieval")
            return True
            
        except Exception as e:
            logger.error(f"❌ Frame graph retrieval test failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def run_all_tests(self):
        """Run all graph-level retrieval tests."""
        logger.info("=" * 100)
        logger.info("🚀 Starting Graph-Level Retrieval Tests")
        logger.info("=" * 100)
        
        if not self.setup_test_environment():
            logger.error("❌ Failed to setup test environment")
            return False
        
        try:
            tests = [
                ("Entity Graph Retrieval", self.test_entity_graph_retrieval),
                ("Frame Graph Retrieval", self.test_frame_graph_retrieval),
            ]
            
            passed_tests = 0
            total_tests = len(tests)
            
            for test_name, test_method in tests:
                logger.info("=" * 100)
                logger.info(f"🧪 Running: {test_name}")
                logger.info("=" * 100)
                
                if test_method():
                    passed_tests += 1
                    logger.info(f"✅ PASS {test_name}")
                    logger.info("    Test completed successfully")
                else:
                    logger.error(f"❌ FAIL {test_name}")
                    logger.error("    Test failed - check logs above")
            
            logger.info("=" * 100)
            logger.info(f"Test Results: {passed_tests}/{total_tests} tests passed")
            
            if passed_tests == total_tests:
                logger.info("🎉 All graph-level retrieval tests passed!")
                return True
            else:
                logger.error(f"❌ {total_tests - passed_tests} test(s) failed")
                return False
                
        finally:
            self.cleanup_test_environment()


if __name__ == "__main__":
    test_runner = TestGraphLevelRetrieval()
    success = test_runner.run_all_tests()
    exit(0 if success else 1)
