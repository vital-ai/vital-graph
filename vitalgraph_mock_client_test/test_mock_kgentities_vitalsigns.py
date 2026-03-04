#!/usr/bin/env python3
"""
Test suite for MockKGEntitiesEndpoint with VitalSigns native functionality.

This test suite validates the mock implementation of KGEntity operations using:
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
from vitalgraph.model.kgentities_model import EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse
from vitalgraph.model.quad_model import QuadResponse, QuadResultsResponse
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity
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
    config.config_path = "<programmatically created for KGEntities VitalSigns test>"
    
    return config


def create_test_kgentities() -> List[KGEntity]:
    """Create test KGEntity objects using VitalSigns helper functions."""
    entities = []
    
    # Create first test KGEntity
    entity1 = KGEntity()
    entity1.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_001"
    entity1.name = "Test Entity 1"
    entity1.kGraphDescription = "A test entity for VitalSigns mock client testing"
    entity1.kGIdentifier = "urn:test_entity_001"
    entity1.kGEntityType = "urn:TestType"
    entity1.kGEntityTypeDescription = "Test Type"
    entities.append(entity1)
    
    # Create second test KGEntity
    entity2 = KGEntity()
    entity2.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_002"
    entity2.name = "Test Entity 2"
    entity2.kGraphDescription = "Another test entity for VitalSigns mock client testing"
    entity2.kGIdentifier = "urn:test_entity_002"
    entity2.kGEntityType = "urn:TestType"
    entity2.kGEntityTypeDescription = "Test Type"
    entities.append(entity2)
    
    return entities


@pytest.fixture
def mock_client():
    """Create a mock client for testing."""
    config = create_mock_config()
    client = create_vitalgraph_client(config)
    return client


@pytest.fixture
def test_space_id():
    """Provide a test space ID."""
    return "test_kgentities_space"


@pytest.fixture
def test_graph_id():
    """Provide a test graph ID."""
    return "http://vital.ai/haley.ai/app/test_kgentities_graph"


class TestMockKGEntitiesVitalSigns:
    """Test suite for MockKGEntitiesEndpoint with VitalSigns integration."""
    
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
        
        # List entities should return empty result
        entities_response = mock_client.kgentities.list_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert isinstance(entities_response, EntitiesResponse)
        assert entities_response.total_count == 0
        assert entities_response.entities is not None
        # Quad response should have empty results
        if hasattr(entities_response, 'results'):
            assert len(entities_response.results) == 0
    
    def test_create_kgentities_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test creating KGEntities using VitalSigns native objects."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create test entities using VitalSigns
        test_entities = create_test_kgentities()
        
        # Create entities via mock client - pass GraphObjects directly
        create_response = mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_entities
        )
        
        assert isinstance(create_response, EntityCreateResponse)
        assert create_response.created_count == 2
        assert len(create_response.created_uris) == 2
        
        # Verify URIs match our test entities
        expected_uris = [entity.URI for entity in test_entities]
        assert all(uri in create_response.created_uris for uri in expected_uris)
    
    def test_get_kgentity_by_uri_vitalsigns_conversion(self, mock_client, test_space_id, test_graph_id):
        """Test retrieving single KGEntity with VitalSigns conversion."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_entities
        )
        
        # Get specific entity by URI
        target_uri = test_entities[0].URI
        entity_response = mock_client.kgentities.get_kgentity(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_uri
        )
        
        assert isinstance(entity_response, QuadResponse)
        assert entity_response.success
        assert entity_response.total_count >= 1
        
        # Convert quads back to VitalSigns objects to verify round-trip
        reconstructed_objects = quad_list_to_graphobjects(entity_response.results)
        assert len(reconstructed_objects) >= 1
        
        reconstructed_entity = reconstructed_objects[0]
        assert str(reconstructed_entity.URI) == str(target_uri)
    
    def test_list_kgentities_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test listing KGEntities with quad-based response."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_entities
        )
        
        # List all entities
        entities_response = mock_client.kgentities.list_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert isinstance(entities_response, (EntitiesResponse, QuadResponse))
        assert entities_response.total_count == 2
    
    def test_update_kgentities_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test updating KGEntities using VitalSigns native functionality."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_entities
        )
        
        # Modify entities for update
        test_entities[0].name = "Updated Test Entity 1"
        test_entities[0].kGraphDescription = "Updated description for testing"
        
        # Update entities - pass GraphObjects directly
        update_response = mock_client.kgentities.update_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_entities
        )
        
        assert isinstance(update_response, EntityUpdateResponse)
        assert update_response.updated_uri is not None
        
        # Verify update by retrieving the entity
        entity_response = mock_client.kgentities.get_kgentity(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=test_entities[0].URI
        )
        
        # Convert quads back to verify update
        reconstructed_objects = quad_list_to_graphobjects(entity_response.results)
        assert len(reconstructed_objects) >= 1
        reconstructed_entity = reconstructed_objects[0]
        assert str(reconstructed_entity.name) == "Updated Test Entity 1"
    
    def test_delete_kgentity_pyoxigraph_integration(self, mock_client, test_space_id, test_graph_id):
        """Test deleting KGEntity with pyoxigraph SPARQL operations."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_entities
        )
        
        # Delete one entity
        target_uri = test_entities[0].URI
        delete_response = mock_client.kgentities.delete_kgentity(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_uri
        )
        
        assert isinstance(delete_response, EntityDeleteResponse)
        assert delete_response.deleted_count == 1
        
        # Verify deletion by listing entities
        entities_response = mock_client.kgentities.list_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert entities_response.total_count == 1  # One entity should remain
    
    def test_kgentity_vitaltype_validation(self, mock_client, test_space_id, test_graph_id):
        """Test that KGEntity objects have correct vitaltype URI."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create entity and verify vitaltype
        test_entities = create_test_kgentities()
        
        # Check vitaltype URI is correct
        expected_vitaltype = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
        
        for entity in test_entities:
            # VitalSigns should set the correct vitaltype
            assert hasattr(entity, 'vitaltype') or hasattr(entity, 'get_class_uri')
            if hasattr(entity, 'get_class_uri'):
                assert entity.get_class_uri() == expected_vitaltype
    
    def test_end_to_end_workflow(self, mock_client, test_space_id, test_graph_id):
        """Test complete end-to-end workflow: Create Space → Add User → Create Entities → Query → Cleanup."""
        # Step 1: Create Space
        space = Space(space=test_space_id, tenant="test_tenant", space_description="Test space for KGEntities")
        space_response = mock_client.spaces.create_space(space)
        assert space_response.created_count == 1
        
        # Step 2: Add User (if user management is available)
        # Note: This would depend on user management implementation in mock client
        
        # Step 3: Create Entities - pass GraphObjects directly
        test_entities = create_test_kgentities()
        create_response = mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            objects=test_entities
        )
        assert create_response.created_count == 2
        
        # Step 4: Query Entities
        entities_response = mock_client.kgentities.list_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        assert entities_response.total_count == 2
        
        # Step 5: Cleanup (delete entities)
        for entity in test_entities:
            delete_response = mock_client.kgentities.delete_kgentity(
                space_id=test_space_id,
                graph_id=test_graph_id,
                uri=entity.URI
            )
            assert delete_response.deleted_count == 1
        
        # Verify cleanup
        final_response = mock_client.kgentities.list_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        assert final_response.total_count == 0


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
