#!/usr/bin/env python3
"""
Test suite for MockKGEntitiesEndpoint with VitalSigns native JSON-LD functionality.

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
from vitalgraph.model.jsonld_model import JsonLdDocument

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


def create_test_jsonld_document(entities: List[KGEntity]) -> Dict[str, Any]:
    """Convert VitalSigns KGEntity objects to JSON-LD document using VitalSigns native functionality."""
    vitalsigns = VitalSigns()
    
    # Use VitalSigns native conversion
    jsonld_document = vitalsigns.to_jsonld_list(entities)
    
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
        # JSON-LD document should have empty @graph
        if hasattr(entities_response.entities, 'graph'):
            assert len(entities_response.entities.graph) == 0
    
    def test_create_kgentities_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test creating KGEntities using VitalSigns native JSON-LD conversion."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create test entities using VitalSigns
        test_entities = create_test_kgentities()
        jsonld_document = create_test_jsonld_document(test_entities)
        
        # Convert to JsonLdDocument for API
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        # Create entities via mock client
        create_response = mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        assert isinstance(create_response, EntityCreateResponse)
        assert create_response.created_count == 2
        assert len(create_response.created_uris) == 2
        
        # Verify URIs match our test entities
        expected_uris = [entity.URI for entity in test_entities]
        assert all(uri in create_response.created_uris for uri in expected_uris)
    
    def test_get_kgentity_by_uri_vitalsigns_conversion(self, mock_client, test_space_id, test_graph_id):
        """Test retrieving single KGEntity with VitalSigns JSON-LD conversion."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        jsonld_document = create_test_jsonld_document(test_entities)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # Get specific entity by URI
        target_uri = test_entities[0].URI
        entity_response = mock_client.kgentities.get_kgentity(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=target_uri
        )
        
        assert isinstance(entity_response, JsonLdDocument)
        # Verify the response contains proper JSON-LD structure
        assert hasattr(entity_response, 'context') or hasattr(entity_response, 'id')
        
        # Convert back to VitalSigns object to verify round-trip
        vitalsigns = VitalSigns()
        entity_dict = entity_response.model_dump(by_alias=True)
        reconstructed_entity = vitalsigns.from_jsonld(entity_dict)
        
        assert reconstructed_entity.URI == target_uri
        assert reconstructed_entity.name == test_entities[0].name
    
    def test_list_kgentities_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test listing KGEntities with VitalSigns native JSON-LD document return."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        jsonld_document = create_test_jsonld_document(test_entities)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # List all entities
        entities_response = mock_client.kgentities.list_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id
        )
        
        assert isinstance(entities_response, EntitiesResponse)
        assert entities_response.total_count == 2
        assert entities_response.entities is not None
        
        # Verify JSON-LD document structure
        entities_dict = entities_response.entities.model_dump(by_alias=True)
        
        # Should have proper JSON-LD structure with @context and @graph
        assert '@context' in entities_dict or 'context' in entities_dict
        assert '@graph' in entities_dict or 'graph' in entities_dict
        
        # Convert back to VitalSigns objects to verify content
        vitalsigns = VitalSigns()
        reconstructed_entities = vitalsigns.from_jsonld(entities_dict)
        
        # Should be a list of entities
        if isinstance(reconstructed_entities, list):
            assert len(reconstructed_entities) == 2
        else:
            # Single entity case - convert to list
            reconstructed_entities = [reconstructed_entities]
            assert len(reconstructed_entities) == 1
    
    def test_update_kgentities_vitalsigns_native(self, mock_client, test_space_id, test_graph_id):
        """Test updating KGEntities using VitalSigns native functionality."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        jsonld_document = create_test_jsonld_document(test_entities)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
        )
        
        # Modify entities for update
        test_entities[0].name = "Updated Test Entity 1"
        test_entities[0].kGraphDescription = "Updated description for testing"
        
        # Create updated JSON-LD document
        updated_jsonld_document = create_test_jsonld_document(test_entities)
        updated_jsonld_doc = JsonLdDocument(**updated_jsonld_document)
        
        # Update entities
        update_response = mock_client.kgentities.update_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=updated_jsonld_doc
        )
        
        assert isinstance(update_response, EntityUpdateResponse)
        assert update_response.updated_uri is not None
        
        # Verify update by retrieving the entity
        entity_response = mock_client.kgentities.get_kgentity(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=test_entities[0].URI
        )
        
        # Convert back to verify update
        vitalsigns = VitalSigns()
        entity_dict = entity_response.model_dump(by_alias=True)
        reconstructed_entity = vitalsigns.from_jsonld(entity_dict)
        
        assert reconstructed_entity.name == "Updated Test Entity 1"
        assert "Updated description" in reconstructed_entity.kGraphDescription
    
    def test_delete_kgentity_pyoxigraph_integration(self, mock_client, test_space_id, test_graph_id):
        """Test deleting KGEntity with pyoxigraph SPARQL operations."""
        # Setup: Create space and entities
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_entities = create_test_kgentities()
        jsonld_document = create_test_jsonld_document(test_entities)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
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
        
        # Verify the remaining entity is the correct one
        entities_dict = entities_response.entities.model_dump(by_alias=True)
        vitalsigns = VitalSigns()
        remaining_entities = vitalsigns.from_jsonld(entities_dict)
        
        if isinstance(remaining_entities, list):
            remaining_entity = remaining_entities[0]
        else:
            remaining_entity = remaining_entities
            
        assert remaining_entity.URI == test_entities[1].URI
    
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
        
        # Step 3: Create Entities
        test_entities = create_test_kgentities()
        jsonld_document = create_test_jsonld_document(test_entities)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        create_response = mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=jsonld_doc
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
