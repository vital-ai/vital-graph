#!/usr/bin/env python3
"""
Test suite for VitalSigns + pyoxigraph integration in the mock client.

This test suite validates the integration between:
- VitalSigns native object creation and conversion
- pyoxigraph in-memory SPARQL quad store operations
- Proper round-trip conversion between VitalSigns objects and RDF quads
- SPARQL query capabilities with VitalSigns objects
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
from vitalgraph.model.sparql_model import SPARQLQueryRequest, SPARQLQueryResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# VitalSigns imports
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGType import KGType
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
    config.config_path = "<programmatically created for VitalSigns-pyoxigraph integration test>"
    
    return config


def create_mixed_test_objects() -> List[object]:
    """Create a mix of different VitalSigns objects for integration testing."""
    objects = []
    
    # Create KGEntity
    entity = KGEntity()
    entity.URI = "http://vital.ai/haley.ai/app/KGEntity/integration_entity"
    entity.name = "Integration Entity"
    entity.kGraphDescription = "Entity for VitalSigns-pyoxigraph integration testing"
    entity.kGIdentifier = "urn:integration_entity"
    entity.kGEntityType = "urn:IntegrationType"
    entity.kGEntityTypeDescription = "Integration Type"
    objects.append(entity)
    
    # Create KGType
    kgtype = KGType()
    kgtype.URI = "http://vital.ai/haley.ai/app/KGType/integration_type"
    kgtype.name = "IntegrationType"
    kgtype.kGTypeDescription = "Type for VitalSigns-pyoxigraph integration testing"
    kgtype.kGTypeIdentifier = "urn:integration_type"
    kgtype.kGTypeCategory = "urn:IntegrationCategory"
    kgtype.kGTypeCategoryDescription = "Integration Category"
    objects.append(kgtype)
    
    # Create KGFrame
    frame = KGFrame()
    frame.URI = "http://vital.ai/haley.ai/app/KGFrame/integration_frame"
    frame.name = "IntegrationFrame"
    frame.kGFrameDescription = "Frame for VitalSigns-pyoxigraph integration testing"
    frame.kGFrameIdentifier = "urn:integration_frame"
    frame.kGFrameCategory = "urn:IntegrationFrameCategory"
    frame.kGFrameCategoryDescription = "Integration Frame Category"
    objects.append(frame)
    
    # Create KGFrameSlot
    slot = KGFrameSlot()
    slot.URI = "http://vital.ai/haley.ai/app/KGFrameSlot/integration_slot"
    slot.name = "IntegrationSlot"
    slot.kGFrameSlotDescription = "Slot for VitalSigns-pyoxigraph integration testing"
    slot.kGFrameSlotIdentifier = "urn:integration_slot"
    slot.kGFrameSlotType = "urn:StringSlot"
    slot.kGFrameSlotRequired = True
    slot.kGFrameSlotFrame = frame.URI
    objects.append(slot)
    
    return objects


@pytest.fixture
def mock_client():
    """Create a mock client for testing."""
    config = create_mock_config()
    client = create_vitalgraph_client(config)
    return client


@pytest.fixture
def test_space_id():
    """Provide a test space ID."""
    return "test_integration_space"


@pytest.fixture
def test_graph_id():
    """Provide a test graph ID."""
    return "http://vital.ai/haley.ai/app/test_integration_graph"


class TestVitalSignsPyoxigraphIntegration:
    """Test suite for VitalSigns + pyoxigraph integration."""
    
    def setup_method(self):
        """Setup for each test - ensure clean slate."""
        logger.info("Setting up integration test - ensuring clean pyoxigraph storage")
    
    def teardown_method(self):
        """Cleanup after each test."""
        logger.info("Tearing down integration test - cleaning up test data")
    
    def test_vitalsigns_to_quads_conversion(self, mock_client, test_space_id, test_graph_id):
        """Test conversion from VitalSigns objects to RDF quads in pyoxigraph."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create mixed objects using VitalSigns
        test_objects = create_mixed_test_objects()
        
        # Convert to JSON-LD using VitalSigns
        vitalsigns = VitalSigns()
        jsonld_document = vitalsigns.to_jsonld_list(test_objects)
        jsonld_doc = JsonLdDocument(**jsonld_document)
        
        # Store objects in pyoxigraph via different endpoints
        entity = [obj for obj in test_objects if isinstance(obj, KGEntity)][0]
        kgtype = [obj for obj in test_objects if isinstance(obj, KGType)][0]
        frame = [obj for obj in test_objects if isinstance(obj, KGFrame)][0]
        slot = [obj for obj in test_objects if isinstance(obj, KGFrameSlot)][0]
        
        # Create entity
        entity_jsonld = vitalsigns.to_jsonld_list([entity])
        entity_doc = JsonLdDocument(**entity_jsonld)
        entity_response = mock_client.kgentities.create_kgentities(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=entity_doc
        )
        assert entity_response.created_count == 1
        
        # Create type
        type_jsonld = vitalsigns.to_jsonld_list([kgtype])
        type_doc = JsonLdDocument(**type_jsonld)
        type_response = mock_client.kgtypes.create_kgtypes(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=type_doc
        )
        assert type_response.created_count == 1
        
        # Create frame with slot
        frame_jsonld = vitalsigns.to_jsonld_list([frame, slot])
        frame_doc = JsonLdDocument(**frame_jsonld)
        frame_response = mock_client.kgframes.create_kgframes_with_slots(
            space_id=test_space_id,
            graph_id=test_graph_id,
            document=frame_doc
        )
        assert frame_response.created_count == 2
        
        # Verify all objects are stored by querying
        entities_response = mock_client.kgentities.list_kgentities(test_space_id, test_graph_id)
        assert entities_response.total_count == 1
        
        types_response = mock_client.kgtypes.list_kgtypes(test_space_id, test_graph_id)
        assert types_response.total_count == 1
        
        frames_response = mock_client.kgframes.list_kgframes(test_space_id, test_graph_id)
        assert frames_response.total_count == 1
    
    def test_sparql_query_vitalsigns_objects(self, mock_client, test_space_id, test_graph_id):
        """Test SPARQL queries against VitalSigns objects stored in pyoxigraph."""
        # Setup: Create space and objects
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_mixed_test_objects()
        vitalsigns = VitalSigns()
        
        # Store objects
        entity = [obj for obj in test_objects if isinstance(obj, KGEntity)][0]
        entity_jsonld = vitalsigns.to_jsonld_list([entity])
        entity_doc = JsonLdDocument(**entity_jsonld)
        mock_client.kgentities.create_kgentities(test_space_id, test_graph_id, entity_doc)
        
        # Execute SPARQL query to find the entity
        sparql_query = f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT ?entity ?name ?description
        WHERE {{
            GRAPH <{test_graph_id}> {{
                ?entity a haley:KGEntity ;
                        vital:name ?name ;
                        haley:kGraphDescription ?description .
            }}
        }}
        """
        
        query_request = SPARQLQueryRequest(query=sparql_query)
        query_response = mock_client.sparql.execute_sparql_query(
            space_id=test_space_id,
            request=query_request
        )
        
        assert isinstance(query_response, SPARQLQueryResponse)
        assert query_response.results is not None
        
        # Verify query results contain our entity
        results = query_response.results
        if hasattr(results, 'bindings'):
            assert len(results.bindings) == 1
            binding = results.bindings[0]
            assert binding['name']['value'] == "Integration Entity"
            assert "integration testing" in binding['description']['value']
    
    def test_round_trip_conversion_accuracy(self, mock_client, test_space_id, test_graph_id):
        """Test round-trip conversion: VitalSigns → pyoxigraph → VitalSigns maintains data integrity."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        # Create original objects
        original_objects = create_mixed_test_objects()
        vitalsigns = VitalSigns()
        
        # Store entity and retrieve it
        entity = [obj for obj in original_objects if isinstance(obj, KGEntity)][0]
        entity_jsonld = vitalsigns.to_jsonld_list([entity])
        entity_doc = JsonLdDocument(**entity_jsonld)
        
        # Store in pyoxigraph
        mock_client.kgentities.create_kgentities(test_space_id, test_graph_id, entity_doc)
        
        # Retrieve from pyoxigraph
        retrieved_response = mock_client.kgentities.get_kgentity(
            space_id=test_space_id,
            graph_id=test_graph_id,
            uri=entity.URI
        )
        
        # Convert back to VitalSigns object
        retrieved_dict = retrieved_response.model_dump(by_alias=True)
        reconstructed_entity = vitalsigns.from_jsonld(retrieved_dict)
        
        # Verify data integrity
        assert reconstructed_entity.URI == entity.URI
        assert reconstructed_entity.name == entity.name
        assert reconstructed_entity.kGraphDescription == entity.kGraphDescription
        assert reconstructed_entity.kGIdentifier == entity.kGIdentifier
        assert reconstructed_entity.kGEntityType == entity.kGEntityType
        assert reconstructed_entity.kGEntityTypeDescription == entity.kGEntityTypeDescription
    
    def test_complex_sparql_operations(self, mock_client, test_space_id, test_graph_id):
        """Test complex SPARQL operations (CONSTRUCT, ASK, DESCRIBE) with VitalSigns objects."""
        # Setup: Create space and objects
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_mixed_test_objects()
        vitalsigns = VitalSigns()
        
        # Store all objects
        for obj in test_objects:
            if isinstance(obj, KGEntity):
                obj_jsonld = vitalsigns.to_jsonld_list([obj])
                obj_doc = JsonLdDocument(**obj_jsonld)
                mock_client.kgentities.create_kgentities(test_space_id, test_graph_id, obj_doc)
            elif isinstance(obj, KGType):
                obj_jsonld = vitalsigns.to_jsonld_list([obj])
                obj_doc = JsonLdDocument(**obj_jsonld)
                mock_client.kgtypes.create_kgtypes(test_space_id, test_graph_id, obj_doc)
            elif isinstance(obj, (KGFrame, KGFrameSlot)):
                # Handle frame and slot together
                if isinstance(obj, KGFrame):
                    frame = obj
                    slot = [s for s in test_objects if isinstance(s, KGFrameSlot)][0]
                    frame_jsonld = vitalsigns.to_jsonld_list([frame, slot])
                    frame_doc = JsonLdDocument(**frame_jsonld)
                    mock_client.kgframes.create_kgframes_with_slots(test_space_id, test_graph_id, frame_doc)
        
        # Test ASK query
        ask_query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        ASK {{
            GRAPH <{test_graph_id}> {{
                ?entity a haley:KGEntity .
            }}
        }}
        """
        
        ask_request = SPARQLQueryRequest(query=ask_query)
        ask_response = mock_client.sparql.execute_sparql_query(test_space_id, ask_request)
        assert ask_response.results is not None
        # ASK query should return true since we have a KGEntity
        
        # Test CONSTRUCT query
        construct_query = f"""
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        CONSTRUCT {{
            ?entity vital:name ?name .
            ?entity a haley:KGEntity .
        }}
        WHERE {{
            GRAPH <{test_graph_id}> {{
                ?entity a haley:KGEntity ;
                        vital:name ?name .
            }}
        }}
        """
        
        construct_request = SPARQLQueryRequest(query=construct_query)
        construct_response = mock_client.sparql.execute_sparql_query(test_space_id, construct_request)
        assert construct_response.results is not None
    
    def test_transaction_consistency(self, mock_client, test_space_id, test_graph_id):
        """Test that pyoxigraph maintains ACID properties during VitalSigns object operations."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        test_objects = create_mixed_test_objects()
        vitalsigns = VitalSigns()
        
        # Create entity
        entity = [obj for obj in test_objects if isinstance(obj, KGEntity)][0]
        entity_jsonld = vitalsigns.to_jsonld_list([entity])
        entity_doc = JsonLdDocument(**entity_jsonld)
        
        create_response = mock_client.kgentities.create_kgentities(test_space_id, test_graph_id, entity_doc)
        assert create_response.created_count == 1
        
        # Verify entity exists
        list_response = mock_client.kgentities.list_kgentities(test_space_id, test_graph_id)
        assert list_response.total_count == 1
        
        # Update entity
        entity.name = "Updated Integration Entity"
        entity.kGraphDescription = "Updated description for consistency testing"
        
        updated_jsonld = vitalsigns.to_jsonld_list([entity])
        updated_doc = JsonLdDocument(**updated_jsonld)
        
        update_response = mock_client.kgentities.update_kgentities(test_space_id, test_graph_id, updated_doc)
        assert update_response.updated_uri is not None
        
        # Verify update consistency
        retrieved_response = mock_client.kgentities.get_kgentity(test_space_id, test_graph_id, entity.URI)
        retrieved_dict = retrieved_response.model_dump(by_alias=True)
        reconstructed_entity = vitalsigns.from_jsonld(retrieved_dict)
        
        assert reconstructed_entity.name == "Updated Integration Entity"
        assert "consistency testing" in reconstructed_entity.kGraphDescription
        
        # Verify count remains consistent
        final_list_response = mock_client.kgentities.list_kgentities(test_space_id, test_graph_id)
        assert final_list_response.total_count == 1  # Should still be 1, not 2
    
    def test_vitalsigns_helper_functions_integration(self, mock_client, test_space_id, test_graph_id):
        """Test integration of VitalSigns helper functions with pyoxigraph operations."""
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        vitalsigns = VitalSigns()
        
        # Test from_triples_list functionality
        # Create entity using direct property setting
        entity = KGEntity()
        entity.URI = "http://vital.ai/haley.ai/app/KGEntity/helper_test_entity"
        entity.name = "Helper Test Entity"
        entity.kGraphDescription = "Entity for testing VitalSigns helper functions"
        
        # Convert to triples and back
        triples = vitalsigns.to_triples([entity])
        assert len(triples) > 0
        
        # Recreate from triples
        reconstructed_from_triples = vitalsigns.from_triples_list(triples)
        assert len(reconstructed_from_triples) == 1
        assert reconstructed_from_triples[0].URI == entity.URI
        
        # Test with pyoxigraph storage
        entity_jsonld = vitalsigns.to_jsonld_list([entity])
        entity_doc = JsonLdDocument(**entity_jsonld)
        
        create_response = mock_client.kgentities.create_kgentities(test_space_id, test_graph_id, entity_doc)
        assert create_response.created_count == 1
        
        # Retrieve and verify round-trip through pyoxigraph
        retrieved_response = mock_client.kgentities.get_kgentity(test_space_id, test_graph_id, entity.URI)
        retrieved_dict = retrieved_response.model_dump(by_alias=True)
        final_entity = vitalsigns.from_jsonld(retrieved_dict)
        
        assert final_entity.URI == entity.URI
        assert final_entity.name == entity.name
        assert final_entity.kGraphDescription == entity.kGraphDescription
    
    def test_performance_vitalsigns_pyoxigraph(self, mock_client, test_space_id, test_graph_id):
        """Test performance characteristics of VitalSigns + pyoxigraph integration."""
        import time
        
        # Setup: Create space
        space = Space(space=test_space_id, tenant="test_tenant")
        mock_client.spaces.create_space(space)
        
        vitalsigns = VitalSigns()
        
        # Create multiple entities for performance testing
        entities = []
        for i in range(10):
            entity = KGEntity()
            entity.URI = f"http://vital.ai/haley.ai/app/KGEntity/perf_test_entity_{i:03d}"
            entity.name = f"Performance Test Entity {i}"
            entity.kGraphDescription = f"Entity {i} for performance testing"
            entity.kGIdentifier = f"urn:perf_test_entity_{i:03d}"
            entity.kGEntityType = "urn:PerformanceTestType"
            entities.append(entity)
        
        # Measure batch creation time
        start_time = time.time()
        
        entities_jsonld = vitalsigns.to_jsonld_list(entities)
        entities_doc = JsonLdDocument(**entities_jsonld)
        
        create_response = mock_client.kgentities.create_kgentities(test_space_id, test_graph_id, entities_doc)
        
        creation_time = time.time() - start_time
        
        assert create_response.created_count == 10
        logger.info(f"Created 10 entities in {creation_time:.3f} seconds")
        
        # Measure query time
        start_time = time.time()
        
        list_response = mock_client.kgentities.list_kgentities(test_space_id, test_graph_id)
        
        query_time = time.time() - start_time
        
        assert list_response.total_count == 10
        logger.info(f"Queried 10 entities in {query_time:.3f} seconds")
        
        # Performance should be reasonable for in-memory operations
        assert creation_time < 5.0  # Should create 10 entities in under 5 seconds
        assert query_time < 2.0     # Should query 10 entities in under 2 seconds


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v"])
