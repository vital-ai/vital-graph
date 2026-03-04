#!/usr/bin/env python3
"""
Test suite for MockKGTypesEndpoint with VitalSigns native functionality.

This test suite validates the mock implementation of KGType operations using:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store
- Proper test lifecycle management (clean slate for each test)
- Complete CRUD operations with proper vitaltype handling
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
from vitalgraph.model.kgtypes_model import KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse
from vitalgraph.model.quad_model import QuadResponse, QuadResultsResponse
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGType import KGType
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
    config.config_path = "<programmatically created for KGTypes VitalSigns test>"
    
    return config


def create_test_kgtypes() -> List[KGType]:
    """Create test KGType objects using VitalSigns helper functions."""
    types = []
    
    # Create first test KGType
    type1 = KGType()
    type1.URI = "http://vital.ai/haley.ai/app/KGType/test_type_001"
    type1.name = "TestType1"
    type1.kGTypeDescription = "A test type for VitalSigns mock client testing"
    type1.kGTypeIdentifier = "urn:test_type_001"
    type1.kGTypeCategory = "urn:TestCategory"
    type1.kGTypeCategoryDescription = "Test Category"
    types.append(type1)
    
    # Create second test KGType
    type2 = KGType()
    type2.URI = "http://vital.ai/haley.ai/app/KGType/test_type_002"
    type2.name = "TestType2"
    type2.kGTypeDescription = "Another test type for VitalSigns mock client testing"
    type2.kGTypeIdentifier = "urn:test_type_002"
    type2.kGTypeCategory = "urn:TestCategory"
    type2.kGTypeCategoryDescription = "Test Category"
    types.append(type2)
    
    return types




@pytest.fixture
def mock_client():
    """Create a mock client for testing."""
    config = create_mock_config()
    client = create_vitalgraph_client(config)
    return client


@pytest.fixture
def test_space_id():
    """Provide a test space ID."""
    return "test_kgtypes_space"


@pytest.fixture
def test_graph_id():
    """Provide a test graph ID."""
    return "http://vital.ai/haley.ai/app/test_kgtypes_graph"


class TestMockKGTypesVitalSigns:
    """Test suite for MockKGTypesEndpoint with VitalSigns integration."""
    
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
        
        # List types should return empty result
        types_response = mock_client.kgtypes.list_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert isinstance(types_response, KGTypeListResponse)
        assert types_response.total_count == 0
        assert types_response.types is not None
        # Quad response should have empty results
        if hasattr(types_response, 'results'):
            assert len(types_response.results) == 0
    
    def test_create_kgtypes_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test creating KGTypes using VitalSigns native objects."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create test types using VitalSigns
        test_types = create_test_kgtypes()
        
        # Create types via mock client - pass GraphObjects directly
        create_response = mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        
        assert isinstance(create_response, KGTypeCreateResponse)
        assert create_response.created_count == 2
        assert len(create_response.created_uris) == 2
        
        # Verify URIs match our test types
        expected_uris = [kgtype.URI for kgtype in test_types]
        assert all(uri in create_response.created_uris for uri in expected_uris)
    
    def test_get_kgtype_by_uri_vitalsigns_conversion(self, mock_client, test_space_id, test_graph_id):
        """Test retrieving single KGType with VitalSigns conversion."""
        # Setup: Create space and types
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_types = create_test_kgtypes()
        mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        
        # Get specific type by URI
        target_uri = test_types[0].URI
        type_response = mock_client.kgtypes.get_kgtype(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_uri
        )
        
        assert isinstance(type_response, QuadResponse)
        assert type_response.success
        assert type_response.total_count == 1
        
        # Convert quads back to VitalSigns objects to verify round-trip
        reconstructed_objects = quad_list_to_graphobjects(type_response.results)
        assert len(reconstructed_objects) >= 1
        
        reconstructed_type = reconstructed_objects[0]
        assert str(reconstructed_type.URI) == str(target_uri)
    
    def test_list_kgtypes_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test listing KGTypes with quad-based response."""
        # Setup: Create space and types
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_types = create_test_kgtypes()
        mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        
        # List all types
        types_response = mock_client.kgtypes.list_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert isinstance(types_response, (KGTypeListResponse, QuadResponse))
        assert types_response.total_count == 2
    
    def test_update_kgtypes_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test updating KGTypes using VitalSigns native functionality."""
        # Setup: Create space and types
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_types = create_test_kgtypes()
        mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        
        # Modify types for update
        test_types[0].name = "UpdatedTestType1"
        test_types[0].kGTypeDescription = "Updated description for testing"
        
        # Update types - pass GraphObjects directly
        update_response = mock_client.kgtypes.update_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        
        assert isinstance(update_response, KGTypeUpdateResponse)
        assert update_response.updated_uri is not None
        
        # Verify update by retrieving the type
        type_response = mock_client.kgtypes.get_kgtype(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=test_types[0].URI
        )
        
        # Convert quads back to verify update
        reconstructed_objects = quad_list_to_graphobjects(type_response.results)
        assert len(reconstructed_objects) >= 1
        reconstructed_type = reconstructed_objects[0]
        
        assert str(reconstructed_type.name) == "UpdatedTestType1"
    
    def test_delete_kgtype_pyoxigraph_integration(self, mock_client, test_space_id, test_graph_id):
        """Test deleting KGType with pyoxigraph SPARQL operations."""
        # Setup: Create space and types
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_types = create_test_kgtypes()
        mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        
        # Delete one type
        target_uri = test_types[0].URI
        delete_response = mock_client.kgtypes.delete_kgtype(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_uri
        )
        
        assert isinstance(delete_response, KGTypeDeleteResponse)
        assert delete_response.deleted_count == 1
        
        # Verify deletion by listing types
        types_response = mock_client.kgtypes.list_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert types_response.total_count == 1  # One type should remain
    
    def test_kgtype_vitaltype_validation(self, mock_client, test_space_id, test_graph_id):
        """Test that KGType objects have correct vitaltype URI."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create type and verify vitaltype
        test_types = create_test_kgtypes()
        
        # Check vitaltype URI is correct
        expected_vitaltype = "http://vital.ai/ontology/haley-ai-kg#KGType"
        
        for kgtype in test_types:
            # VitalSigns should set the correct vitaltype
            assert hasattr(kgtype, 'vitaltype') or hasattr(kgtype, 'get_class_uri')
            if hasattr(kgtype, 'get_class_uri'):
                assert kgtype.get_class_uri() == expected_vitaltype
    
    def test_kgtype_sparql_query_integration(self, mock_client, test_space_id, test_graph_id):
        """Test KGType operations with pyoxigraph SPARQL query capabilities."""
        # Setup: Create space and types
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_types = create_test_kgtypes()
        mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        
        # Test filtering by type category
        types_response = mock_client.kgtypes.list_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            search="TestCategory"  # Search by category
        )
        
        assert isinstance(types_response, KGTypeListResponse)
        # Both types should match the category filter
        assert types_response.total_count == 2
    
    def test_end_to_end_workflow(self, mock_client, test_space_id, test_graph_id):
        """Test complete end-to-end workflow: Create Space → Create Types → Query → Update → Delete → Cleanup."""
        # Step 1: Create Space
        space = Space(space=test_space_id, tenant="test_tenant", space_description="Test space for KGTypes")
        space_response = mock_client.spaces.create_space(space)
        assert space_response.created_count == 1
        
        # Step 2: Create Types - pass GraphObjects directly
        test_types = create_test_kgtypes()
        create_response = mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_types
        )
        assert create_response.created_count == 2
        
        # Step 3: Query Types
        types_response = mock_client.kgtypes.list_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        assert types_response.total_count == 2
        
        # Step 4: Update a Type - pass GraphObjects directly
        test_types[0].name = "UpdatedType"
        update_response = mock_client.kgtypes.update_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=[test_types[0]]
        )
        assert update_response.updated_uri is not None
        
        # Step 5: Delete Types
        for kgtype in test_types:
            delete_response = mock_client.kgtypes.delete_kgtype(
                space_id=test_space_id,
                graph_id=test_graph_id,
                uri=kgtype.URI
            )
            assert delete_response.deleted_count == 1
        
        # Step 6: Verify Cleanup
        final_response = mock_client.kgtypes.list_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        assert final_response.total_count == 0


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
