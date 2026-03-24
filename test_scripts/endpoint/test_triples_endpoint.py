#!/usr/bin/env python3
"""
Test script for the Triples endpoints implementation.

Tests the newly implemented database integration for:
- GET /api/graphs/triples - List/Search Triples
- POST /api/graphs/triples - Add Triples  
- DELETE /api/graphs/triples - Delete Triples
"""

import asyncio
import json
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.endpoint.triples_endpoint import TriplesEndpoint, TripleListRequest
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
from unittest.mock import AsyncMock, MagicMock
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MockSpaceManager:
    """Mock space manager for testing."""
    
    def has_space(self, space_id: str) -> bool:
        return space_id == "test_space"
    
    def get_space(self, space_id: str):
        if space_id == "test_space":
            mock_space = MagicMock()
            mock_space.space_impl = MagicMock()
            mock_db_impl = MagicMock()
            
            # Mock the queries.quads method to return test data
            async def mock_quads(space_id, quad_pattern):
                from rdflib import URIRef, Literal
                # Return some test quads
                test_quads = [
                    (
                        (URIRef("http://example.org/person1"), 
                         URIRef("http://schema.org/name"), 
                         Literal("John Doe"), 
                         URIRef("http://example.org/graph1")),
                        lambda: [URIRef("http://example.org/graph1")]
                    ),
                    (
                        (URIRef("http://example.org/person1"), 
                         URIRef("http://schema.org/age"), 
                         Literal("30", datatype=URIRef("http://www.w3.org/2001/XMLSchema#integer")), 
                         URIRef("http://example.org/graph1")),
                        lambda: [URIRef("http://example.org/graph1")]
                    )
                ]
                for quad, context_iter in test_quads:
                    yield quad, context_iter
            
            mock_db_impl.queries = MagicMock()
            mock_db_impl.queries.quads = mock_quads
            
            # Mock add/remove batch methods
            mock_db_impl.add_rdf_quads_batch = AsyncMock(return_value=2)
            mock_db_impl.remove_rdf_quads_batch = AsyncMock(return_value=1)
            
            mock_space.space_impl.get_db_space_impl.return_value = mock_db_impl
            return mock_space
        return None

def mock_auth_dependency():
    """Mock authentication dependency."""
    return {"username": "test_user", "user_id": "123"}

async def test_list_triples():
    """Test the GET /triples endpoint."""
    logger.info("Testing GET /triples endpoint...")
    
    # Create endpoint with mock dependencies
    space_manager = MockSpaceManager()
    endpoint = TriplesEndpoint(space_manager, mock_auth_dependency)
    
    # Test listing triples
    result = await endpoint._list_triples(
        space_id="test_space",
        graph_id="http://example.org/graph1",
        page_size=10,
        offset=0,
        subject=None,
        predicate=None,
        object=None,
        object_filter=None,
        current_user={"username": "test_user"}
    )
    
    logger.info(f"✅ List triples result: {result.pagination}")
    logger.info(f"✅ Found {len(result.data.graph or [])} triples")
    assert result.pagination["total"] >= 0
    assert result.meta["space_id"] == "test_space"
    assert result.meta["graph_id"] == "http://example.org/graph1"

async def test_add_triples():
    """Test the POST /triples endpoint."""
    logger.info("Testing POST /triples endpoint...")
    
    # Create endpoint with mock dependencies
    space_manager = MockSpaceManager()
    endpoint = TriplesEndpoint(space_manager, mock_auth_dependency)
    
    # Create test GraphObjects
    node = VITAL_Node()
    node.URI = "http://example.org/person3"
    node.name = "Alice Smith"
    test_objects = [node]
    
    # Test adding triples
    result = await endpoint._add_triples(
        space_id="test_space",
        graph_id="http://example.org/graph1",
        objects=test_objects,
        current_user={"username": "test_user"}
    )
    
    logger.info(f"✅ Add triples result: {result.message}")
    assert result.success == True
    assert result.affected_count >= 0

async def test_delete_triples():
    """Test the DELETE /triples endpoint."""
    logger.info("Testing DELETE /triples endpoint...")
    
    # Create endpoint with mock dependencies
    space_manager = MockSpaceManager()
    endpoint = TriplesEndpoint(space_manager, mock_auth_dependency)
    
    # Create test GraphObjects for deletion
    node = VITAL_Node()
    node.URI = "http://example.org/person1"
    node.name = "John Doe"
    test_objects = [node]
    
    # Test deleting triples
    result = await endpoint._delete_triples(
        space_id="test_space",
        graph_id="http://example.org/graph1",
        objects=test_objects,
        current_user={"username": "test_user"}
    )
    
    logger.info(f"✅ Delete triples result: {result.message}")
    assert result.success == True
    assert result.affected_count >= 0

async def test_graphobjects_to_quads_conversion():
    """Test GraphObjects to quads conversion."""
    logger.info("Testing GraphObjects to quads conversion...")
    
    # Create endpoint with mock dependencies
    space_manager = MockSpaceManager()
    endpoint = TriplesEndpoint(space_manager, mock_auth_dependency)
    
    # Create test GraphObjects
    node = VITAL_Node()
    node.URI = "http://example.org/person1"
    node.name = "John Doe"
    test_objects = [node]
    
    # Test conversion
    quads = await endpoint._graphobjects_to_quads(test_objects, "http://example.org/graph1")
    
    logger.info(f"✅ Converted to {len(quads)} quads")
    assert len(quads) > 0
    
    # Check quad structure
    for quad in quads:
        assert len(quad) == 4  # subject, predicate, object, graph
        logger.info(f"  Quad: {quad[0]} {quad[1]} {quad[2]} {quad[3]}")

async def main():
    """Run all tests."""
    logger.info("🚀 Starting Triples endpoint tests...")
    
    try:
        await test_list_triples()
        await test_add_triples() 
        await test_delete_triples()
        await test_graphobjects_to_quads_conversion()
        
        logger.info("🎉 All Triples endpoint tests passed!")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
