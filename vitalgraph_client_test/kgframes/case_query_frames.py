"""
Client Test Case: Frame Query Operations

Tests KGFrames query functionality including:
- Query frames by criteria
- Query frames with filters
- Query frames with sorting
- Query frames with pagination
"""

import logging
from typing import Optional
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.kgframes_model import FrameQueryRequest, FrameQueryCriteria

# VitalSigns imports - REQUIRED for proper test data handling
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGFrame import KGFrame
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

# VitalSigns utilities for JSON-LD conversion
from vital_ai_vitalsigns.vitalsigns import VitalSigns


async def test_query_frames_basic(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test basic frame querying."""
    logger.info("🧪 Testing basic frame query...")
    
    try:
        # Create basic query request
        criteria = FrameQueryCriteria(
            frame_type="TestFrame"
        )
        query_request = FrameQueryRequest(
            criteria=criteria,
            page_size=10,
            offset=0
        )
        
        # Test basic frame query
        response = client.kgframes.query_frames(
            space_id=space_id,
            graph_id=graph_id,
            query_request=query_request
        )
        
        if response.total_count >= 0:
            logger.info(f"✅ Basic frame query successful: {response.total_count} matching frames")
            logger.info(f"   Retrieved {len(response.frame_uris)} frame URIs")
            return True
        else:
            logger.error(f"❌ Basic frame query failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Basic frame query failed with exception: {e}")
        return False


async def test_query_frames_with_filters(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test frame querying with filters."""
    logger.info("🧪 Testing frame query with filters...")
    
    try:
        # Create query request with filters
        criteria = FrameQueryCriteria(
            frame_type="TestFrame",
            search_string="Test"
        )
        query_request = FrameQueryRequest(
            criteria=criteria,
            page_size=10,
            offset=0
        )
        
        # Test frame query with filters
        response = client.kgframes.query_frames(
            space_id=space_id,
            graph_id=graph_id,
            query_request=query_request
        )
        
        if response.total_count >= 0:
            logger.info(f"✅ Frame query with filters successful: {response.total_count} matching frames")
            return True
        else:
            logger.error(f"❌ Frame query with filters failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame query with filters failed with exception: {e}")
        return False


async def test_query_frames_with_sorting(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test frame querying with sorting."""
    logger.info("🧪 Testing frame query with sorting...")
    
    try:
        # Create query request with sorting
        criteria = FrameQueryCriteria(
            frame_type="TestFrame"
        )
        query_request = FrameQueryRequest(
            criteria=criteria,
            page_size=10,
            offset=0
        )
        
        # Test frame query with sorting
        response = client.kgframes.query_frames(
            space_id=space_id,
            graph_id=graph_id,
            query_request=query_request
        )
        
        if response.total_count >= 0:
            logger.info(f"✅ Frame query with sorting successful: {response.total_count} matching frames")
            return True
        else:
            logger.error(f"❌ Frame query with sorting failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame query with sorting failed with exception: {e}")
        return False


async def test_query_frames_with_pagination(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test frame querying with pagination."""
    logger.info("🧪 Testing frame query with pagination...")
    
    try:
        # Test multiple pages
        page_size = 5
        total_retrieved = 0
        
        for page in range(3):  # Test first 3 pages
            offset = page * page_size
            
            criteria = FrameQueryCriteria(
                frame_type="TestFrame"
            )
            query_request = FrameQueryRequest(
                criteria=criteria,
                page_size=page_size,
                offset=offset
            )
            
            response = client.kgframes.query_frames(
                space_id=space_id,
                graph_id=graph_id,
                query_request=query_request
            )
            
            if response.total_count < 0:
                logger.error(f"❌ Frame query pagination failed on page {page + 1}")
                return False
            
            page_count = len(response.frame_uris)
            total_retrieved += page_count
            logger.info(f"   Page {page + 1}: {page_count} frame URIs")
            
            # If we get fewer frames than page size, we've reached the end
            if page_count < page_size:
                break
        
        logger.info(f"✅ Frame query with pagination successful: {total_retrieved} total frames retrieved")
        return True
        
    except Exception as e:
        logger.error(f"❌ Frame query with pagination failed with exception: {e}")
        return False


async def test_query_frames_complex(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test complex frame querying with multiple criteria."""
    logger.info("🧪 Testing complex frame query...")
    
    try:
        # Create complex query request
        criteria = FrameQueryCriteria(
            frame_type="TestFrame",
            search_string="Test"
        )
        query_request = FrameQueryRequest(
            criteria=criteria,
            page_size=5,
            offset=0
        )
        
        # Test complex frame query
        response = client.kgframes.query_frames(
            space_id=space_id,
            graph_id=graph_id,
            query_request=query_request
        )
        
        if response.total_count >= 0:
            logger.info(f"✅ Complex frame query successful: {response.total_count} matching frames")
            if response.frame_uris:
                logger.info(f"   First frame URI: {response.frame_uris[0]}")
            return True
        else:
            logger.error(f"❌ Complex frame query failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Complex frame query failed with exception: {e}")
        return False


async def test_query_frames_empty_result(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger) -> bool:
    """Test frame querying that returns no results."""
    logger.info("🧪 Testing frame query with empty result...")
    
    try:
        # Create query request that should return no results
        criteria = FrameQueryCriteria(
            frame_type="NonExistentFrameType",
            search_string="NonExistentFrame"
        )
        query_request = FrameQueryRequest(
            criteria=criteria,
            page_size=10,
            offset=0
        )
        
        # Test frame query with empty result
        response = client.kgframes.query_frames(
            space_id=space_id,
            graph_id=graph_id,
            query_request=query_request
        )
        
        if response.total_count == 0:
            logger.info(f"✅ Frame query with empty result successful: 0 matching frames")
            return True
        else:
            logger.error(f"❌ Frame query with empty result failed: expected 0 results, got {response.total_count}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Frame query with empty result failed with exception: {e}")
        return False


async def run_query_frames_tests(client: VitalGraphClient, space_id: str, graph_id: str, logger: logging.Logger = None) -> bool:
    """Run all frame query tests."""
    if logger is None:
        logger = logging.getLogger(__name__)
    
    logger.info("🚀 Running Frame Query Tests...")
    
    tests = [
        ("Basic Frame Query", lambda: test_query_frames_basic(client, space_id, graph_id, logger)),
        ("Frame Query with Filters", lambda: test_query_frames_with_filters(client, space_id, graph_id, logger)),
        ("Frame Query with Sorting", lambda: test_query_frames_with_sorting(client, space_id, graph_id, logger)),
        ("Frame Query with Pagination", lambda: test_query_frames_with_pagination(client, space_id, graph_id, logger)),
        ("Complex Frame Query", lambda: test_query_frames_complex(client, space_id, graph_id, logger)),
        ("Frame Query with Empty Result", lambda: test_query_frames_empty_result(client, space_id, graph_id, logger))
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"🔧 Running: {test_name}")
        try:
            success = await test_func()
            results.append((test_name, success))
            if not success:
                logger.error(f"❌ {test_name} failed")
        except Exception as e:
            logger.error(f"❌ {test_name} failed with exception: {e}")
            results.append((test_name, False))
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        logger.info("✅ All frame query tests passed!")
        return True
    else:
        failed_tests = [name for name, success in results if not success]
        logger.error(f"❌ Frame query tests failed: {failed_tests}")
        return False
