#!/usr/bin/env python3
"""
Test suite for MockKGFramesEndpoint with VitalSigns native JSON-LD functionality.

This test suite validates the mock implementation of KGFrame operations using:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store
- Proper test lifecycle management (clean slate for each test)
- Complete CRUD operations with proper vitaltype handling
- Frame-slot relationship handling
"""

import pytest
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.kgframes_model import KGFrameListResponse, KGFrameCreateResponse, KGFrameUpdateResponse, KGFrameDeleteResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGFrameSlot import KGFrameSlot
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def create_mock_config() -> VitalGraphClientConfig:
    """Create a config object with mock client enabled."""
    config = VitalGraphClientConfig()
    
    config.config_data = {
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
    config.config_path = "<programmatically created for KGFrames VitalSigns test>"
    
    return config


def create_test_kgframes_with_slots() -> List[object]:
    """Create test KGFrame objects with slots using VitalSigns helper functions."""
    objects = []
    
    # Create first test KGFrame
    frame1 = KGFrame()
    frame1.URI = "http://vital.ai/haley.ai/app/KGFrame/test_frame_001"
    frame1.name = "TestFrame1"
    frame1.kGFrameDescription = "A test frame for VitalSigns mock client testing"
    frame1.kGFrameIdentifier = "urn:test_frame_001"
    frame1.kGFrameCategory = "urn:TestFrameCategory"
    frame1.kGFrameCategoryDescription = "Test Frame Category"
    objects.append(frame1)
    
    # Create slots for frame1
    slot1 = KGFrameSlot()
    slot1.URI = "http://vital.ai/haley.ai/app/KGFrameSlot/test_slot_001"
    slot1.name = "TestSlot1"
    slot1.kGFrameSlotDescription = "A test slot for frame 1"
    slot1.kGFrameSlotIdentifier = "urn:test_slot_001"
    slot1.kGFrameSlotType = "urn:StringSlot"
    slot1.kGFrameSlotRequired = True
    # Link slot to frame
    slot1.kGFrameSlotFrame = frame1.URI
    objects.append(slot1)
    
    slot2 = KGFrameSlot()
    slot2.URI = "http://vital.ai/haley.ai/app/KGFrameSlot/test_slot_002"
    slot2.name = "TestSlot2"
    slot2.kGFrameSlotDescription = "Another test slot for frame 1"
    slot2.kGFrameSlotIdentifier = "urn:test_slot_002"
    slot2.kGFrameSlotType = "urn:IntegerSlot"
    slot2.kGFrameSlotRequired = False
    # Link slot to frame
    slot2.kGFrameSlotFrame = frame1.URI
    objects.append(slot2)
    
    # Create second test KGFrame
    frame2 = KGFrame()
    frame2.URI = "http://vital.ai/haley.ai/app/KGFrame/test_frame_002"
    frame2.name = "TestFrame2"
    frame2.kGFrameDescription = "Another test frame for VitalSigns mock client testing"
    frame2.kGFrameIdentifier = "urn:test_frame_002"
    frame2.kGFrameCategory = "urn:TestFrameCategory"
    frame2.kGFrameCategoryDescription = "Test Frame Category"
    objects.append(frame2)
    
    # Create slot for frame2
    slot3 = KGFrameSlot()
    slot3.URI = "http://vital.ai/haley.ai/app/KGFrameSlot/test_slot_003"
    slot3.name = "TestSlot3"
    slot3.kGFrameSlotDescription = "A test slot for frame 2"
    slot3.kGFrameSlotIdentifier = "urn:test_slot_003"
    slot3.kGFrameSlotType = "urn:BooleanSlot"
    slot3.kGFrameSlotRequired = True
    # Link slot to frame
    slot3.kGFrameSlotFrame = frame2.URI
    objects.append(slot3)
    
    return objects


def create_test_jsonld_document(objects: List[object]) -> Dict[str, Any]:
    """Convert VitalSigns objects to JSON-LD document using VitalSigns native functionality."""
    vitalsigns = VitalSigns()
    
    # Use VitalSigns native conversion
    jsonld_document = vitalsigns.to_jsonld_list(objects)
    
    return jsonld_document


@pytest.fixture
def mock_client():
    """Create a mock client for testing."""
    config = create_mock_config()
    client = create_vitalgraph_client(config)
    return client


@pytest.fixture
def test_space_id():
    """Provide a test space ID."""
    return "test_kgframes_space"


@pytest.fixture
def test_graph_id():
    """Provide a test graph ID."""
    return "http://vital.ai/haley.ai/app/test_kgframes_graph"


class TestMockKGFramesVitalSigns:
    """Test suite for MockKGFramesEndpoint with VitalSigns integration."""
    
    def setup_method(self):
        """Setup for each test - ensure clean slate."""
        logger.info("Setting up test - ensuring clean pyoxigraph storage")
        # Note: Mock client should start with empty pyoxigraph storage
    
    def teardown_method(self):
        """Cleanup after each test."""
        logger.info("Tearing down test - cleaning up test data")
        # Note: pyoxigraph is in-memory only, so no persistent cleanup needed
    
    def test_clean_slate_startup(self, mock_client, test_space_id, test_graph_id):
        """Test that mock client starts with empty storage."""
        # First, create a test space
        space = Space(space=test_space_id, tenant="test_tenant")
        space_response = mock_client.spaces.create_space(space)
        assert space_response.created_count == 1
        
        # List frames should return empty result
        frames_response = mock_client.kgframes.list_kgframes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert isinstance(frames_response, KGFrameListResponse)
        assert frames_response.total_count == 0
        assert frames_response.frames is not None
        # JSON-LD document should have empty @graph
        if hasattr(frames_response.frames, 'graph'):
            assert len(frames_response.frames.graph) == 0
    
    def test_create_kgframes_with_slots_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test creating KGFrames with slots using VitalSigns native JSON-LD conversion."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create test frames with slots using VitalSigns
        test_objects = create_test_kgframes_with_slots()
        jsonld_document = create_test_jsonld_document(test_objects)
        
        # Convert to JsonLdDocument for API
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        # Create frames with slots via mock client
        create_response = mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        assert isinstance(create_response, KGFrameCreateResponse)
        assert create_response.created_count == 5  # 2 frames + 3 slots
        assert len(create_response.created_uris) == 5
        
        # Verify URIs match our test objects
        expected_uris = [obj.URI for obj in test_objects]
        assert all(uri in create_response.created_uris for uri in expected_uris)
    
    def test_get_kgframe_by_uri_vitalsigns_conversion(self, mock_client, test_space_id, test_graph_id):
        """Test retrieving single KGFrame with VitalSigns JSON-LD conversion."""
        # Setup: Create space and frames
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_test_kgframes_with_slots()
        jsonld_document = create_test_jsonld_document(test_objects)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # Get specific frame by URI (first frame)
        target_frame = [obj for obj in test_objects if isinstance(obj, KGFrame)][0]
        frame_response = mock_client.kgframes.get_kgframe(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_frame.URI
        )
        
        assert isinstance(frame_response, JsonLdDocument)
        # Verify the response contains proper JSON-LD structure
        assert hasattr(frame_response, 'context') or hasattr(frame_response, 'id')
        
        # Convert back to VitalSigns object to verify round-trip
        vitalsigns = VitalSigns()
        frame_dict = frame_response.model_dump(by_alias=True)
        reconstructed_frame = vitalsigns.from_jsonld(frame_dict)
        
        assert reconstructed_frame.URI == target_frame.URI
        assert reconstructed_frame.name == target_frame.name
    
    def test_list_kgframes_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test listing KGFrames with VitalSigns native JSON-LD document return."""
        # Setup: Create space and frames
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_test_kgframes_with_slots()
        jsonld_document = create_test_jsonld_document(test_objects)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # List all frames
        frames_response = mock_client.kgframes.list_kgframes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert isinstance(frames_response, KGFrameListResponse)
        assert frames_response.total_count == 2  # Only frames, not slots
        assert frames_response.frames is not None
        
        # Verify JSON-LD document structure
        frames_dict = frames_response.frames.model_dump(by_alias=True)
        
        # Should have proper JSON-LD structure with @context and @graph
        assert '@context' in frames_dict or 'context' in frames_dict
        assert '@graph' in frames_dict or 'graph' in frames_dict
        
        # Convert back to VitalSigns objects to verify content
        vitalsigns = VitalSigns()
        reconstructed_frames = vitalsigns.from_jsonld(frames_dict)
        
        # Should be a list of frames
        if isinstance(reconstructed_frames, list):
            assert len(reconstructed_frames) == 2
        else:
            # Single frame case - convert to list
            reconstructed_frames = [reconstructed_frames]
            assert len(reconstructed_frames) == 1
    
    def test_frame_slot_relationship_handling(self, mock_client, test_space_id, test_graph_id):
        """Test that frame-slot relationships are properly maintained in pyoxigraph."""
        # Setup: Create space and frames with slots
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_test_kgframes_with_slots()
        jsonld_document = create_test_jsonld_document(test_objects)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # Get frame with its slots
        target_frame = [obj for obj in test_objects if isinstance(obj, KGFrame)][0]
        frame_with_slots_response = mock_client.kgframes.get_kgframe_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_frame.URI
        )
        
        assert isinstance(frame_with_slots_response, JsonLdDocument)
        
        # Convert back to verify frame-slot relationships
        vitalsigns = VitalSigns()
        response_dict = frame_with_slots_response.model_dump(by_alias=True)
        reconstructed_objects = vitalsigns.from_jsonld(response_dict)
        
        # Should contain both frame and its slots
        if not isinstance(reconstructed_objects, list):
            reconstructed_objects = [reconstructed_objects]
        
        frames = [obj for obj in reconstructed_objects if isinstance(obj, KGFrame)]
        slots = [obj for obj in reconstructed_objects if isinstance(obj, KGFrameSlot)]
        
        assert len(frames) == 1
        assert len(slots) == 2  # Frame1 has 2 slots
        
        # Verify slot relationships
        frame_uri = frames[0].URI
        for slot in slots:
            assert slot.kGFrameSlotFrame == frame_uri
    
    def test_update_kgframes_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test updating KGFrames using VitalSigns native functionality."""
        # Setup: Create space and frames
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_test_kgframes_with_slots()
        jsonld_document = create_test_jsonld_document(test_objects)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # Modify frame for update
        frames = [obj for obj in test_objects if isinstance(obj, KGFrame)]
        frames[0].name = "UpdatedTestFrame1"
        frames[0].kGFrameDescription = "Updated description for testing"
        
        # Create updated JSON-LD document (just the frame)
        updated_jsonld_document = create_test_jsonld_document([frames[0]])
        updated_jsonld_doc = JsonLdDocument(**updated_jsonld_document)
        
        # Update frame
        update_response = mock_client.kgframes.update_kgframes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=updated_jsonld_doc
        )
        
        assert isinstance(update_response, KGFrameUpdateResponse)
        assert update_response.updated_uri is not None
        
        # Verify update by retrieving the frame
        frame_response = mock_client.kgframes.get_kgframe(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=frames[0].URI
        )
        
        # Convert back to verify update
        vitalsigns = VitalSigns()
        frame_dict = frame_response.model_dump(by_alias=True)
        reconstructed_frame = vitalsigns.from_jsonld(frame_dict)
        
        assert reconstructed_frame.name == "UpdatedTestFrame1"
        assert "Updated description" in reconstructed_frame.kGFrameDescription
    
    def test_delete_kgframe_pyoxigraph_integration(self, mock_client, test_space_id, test_graph_id):
        """Test deleting KGFrame with pyoxigraph SPARQL operations."""
        # Setup: Create space and frames
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_test_kgframes_with_slots()
        jsonld_document = create_test_jsonld_document(test_objects)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # Delete one frame
        frames = [obj for obj in test_objects if isinstance(obj, KGFrame)]
        target_uri = frames[0].URI
        delete_response = mock_client.kgframes.delete_kgframe(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_uri
        )
        
        assert isinstance(delete_response, KGFrameDeleteResponse)
        assert delete_response.deleted_count == 1
        
        # Verify deletion by listing frames
        frames_response = mock_client.kgframes.list_kgframes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert frames_response.total_count == 1  # One frame should remain
        
        # Verify the remaining frame is the correct one
        frames_dict = frames_response.frames.model_dump(by_alias=True)
        vitalsigns = VitalSigns()
        remaining_frames = vitalsigns.from_jsonld(frames_dict)
        
        if isinstance(remaining_frames, list):
            remaining_frame = remaining_frames[0]
        else:
            remaining_frame = remaining_frames
            
        assert remaining_frame.URI == frames[1].URI
    
    def test_kgframe_vitaltype_validation(self, mock_client, test_space_id, test_graph_id):
        """Test that KGFrame objects have correct vitaltype URI."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create frames and verify vitaltype
        test_objects = create_test_kgframes_with_slots()
        frames = [obj for obj in test_objects if isinstance(obj, KGFrame)]
        
        # Check vitaltype URI is correct
        expected_frame_vitaltype = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
        expected_slot_vitaltype = "http://vital.ai/ontology/haley-ai-kg#KGFrameSlot"
        
        for frame in frames:
            # VitalSigns should set the correct vitaltype
            assert hasattr(frame, 'vitaltype') or hasattr(frame, 'get_class_uri')
            if hasattr(frame, 'get_class_uri'):
                assert frame.get_class_uri() == expected_frame_vitaltype
        
        slots = [obj for obj in test_objects if isinstance(obj, KGFrameSlot)]
        for slot in slots:
            # VitalSigns should set the correct vitaltype
            assert hasattr(slot, 'vitaltype') or hasattr(slot, 'get_class_uri')
            if hasattr(slot, 'get_class_uri'):
                assert slot.get_class_uri() == expected_slot_vitaltype
    
    def test_end_to_end_workflow(self, mock_client, test_space_id, test_graph_id):
        """Test complete end-to-end workflow: Create Space → Create Frames → Query → Update → Delete → Cleanup."""
        # Step 1: Create Space
        space = Space(space=test_space_id, tenant="test_tenant", space_description="Test space for KGFrames")
        space_response = mock_client.spaces.create_space(space)
        assert space_response.created_count == 1
        
        # Step 2: Create Frames with Slots
        test_objects = create_test_kgframes_with_slots()
        jsonld_document = create_test_jsonld_document(test_objects)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        create_response = mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        assert create_response.created_count == 5  # 2 frames + 3 slots
        
        # Step 3: Query Frames
        frames_response = mock_client.kgframes.list_kgframes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        assert frames_response.total_count == 2
        
        # Step 4: Update a Frame
        frames = [obj for obj in test_objects if isinstance(obj, KGFrame)]
        frames[0].name = "UpdatedFrame"
        updated_jsonld_document = create_test_jsonld_document([frames[0]])
        updated_jsonld_doc = JsonLdDocument(**updated_jsonld_document)
        
        update_response = mock_client.kgframes.update_kgframes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=updated_jsonld_doc
        )
        assert update_response.updated_uri is not None
        
        # Step 5: Delete Frames
        for frame in frames:
            delete_response = mock_client.kgframes.delete_kgframe(
                space_id=test_space_id,
                graph_id=test_graph_id,
                uri=frame.URI
            )
            assert delete_response.deleted_count == 1
        
        # Step 6: Verify Cleanup
        final_response = mock_client.kgframes.list_kgframes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        assert final_response.total_count == 0


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
