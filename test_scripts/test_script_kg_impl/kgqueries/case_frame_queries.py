"""
KGQueries Frame Query Test Cases

Tests for querying entity-to-entity connections via shared frames (KGFrames).
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgqueries_model import KGQueryRequest, KGQueryCriteria, KGQueryResponse
from vitalgraph.model.kgentities_model import EntityQueryCriteria, SlotCriteria

logger = logging.getLogger(__name__)


class KGFrameQueriesTester:
    """Test cases for KGQueries frame-based connection queries."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name}: {message}")
        if details:
            logger.debug(f"Details: {details}")
    
    async def test_query_shared_frames_basic(self) -> bool:
        """Test basic querying of entities connected via shared frames."""
        try:
            # Create query criteria for frame connections
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_uris=["http://vital.ai/test/entity/person/alice"],
                exclude_self_connections=True
            )
            
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=10,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'frame_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                
                self.log_test_result(
                    "Query Shared Frames Basic",
                    True,
                    f"Successfully queried shared frame connections (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count, "query_type": response.query_type}
                )
                return True
            else:
                self.log_test_result(
                    "Query Shared Frames Basic",
                    False,
                    "Failed to query shared frame connections",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Shared Frames Basic",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_frames_by_type(self) -> bool:
        """Test querying frame connections filtered by frame type."""
        try:
            # Create query criteria for specific frame types
            criteria = KGQueryCriteria(
                query_type="frame",
                shared_frame_types=["http://vital.ai/ontology/haley-ai-kg#ProjectFrame"],
                exclude_self_connections=True
            )
            
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=15,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'frame_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                
                # Validate that returned connections have the expected frame type
                valid_types = True
                if response.frame_connections:
                    for conn in response.frame_connections:
                        if hasattr(conn, 'frame_type_uri') and conn.frame_type_uri not in criteria.shared_frame_types:
                            valid_types = False
                            break
                
                self.log_test_result(
                    "Query Frames By Type",
                    True,
                    f"Successfully queried frame connections by type (found: {connection_count}, total: {total_count}, valid_types: {valid_types})",
                    {"connection_count": connection_count, "total_count": total_count, "frame_types": criteria.shared_frame_types}
                )
                return True
            else:
                self.log_test_result(
                    "Query Frames By Type",
                    False,
                    "Failed to query frame connections by type",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Frames By Type",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_frames_with_slot_criteria(self) -> bool:
        """Test querying frame connections with slot criteria."""
        try:
            # Create slot criteria for frame filtering
            slot_criteria = [
                SlotCriteria(
                    slot_type="http://vital.ai/ontology/haley-ai-kg#hasProjectStatus",
                    slot_value="active"
                )
            ]
            
            # Create query criteria with slot criteria
            criteria = KGQueryCriteria(
                query_type="frame",
                shared_frame_types=["http://vital.ai/ontology/haley-ai-kg#ProjectFrame"],
                frame_slot_criteria=slot_criteria,
                exclude_self_connections=True
            )
            
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=10,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'frame_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                
                self.log_test_result(
                    "Query Frames With Slot Criteria",
                    True,
                    f"Successfully queried frame connections with slot criteria (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count, "slot_criteria": "hasProjectStatus=active"}
                )
                return True
            else:
                self.log_test_result(
                    "Query Frames With Slot Criteria",
                    False,
                    "Failed to query frame connections with slot criteria",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Frames With Slot Criteria",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_frames_with_entity_criteria(self) -> bool:
        """Test querying frame connections with entity criteria filters."""
        try:
            # Create entity criteria for source entities
            source_criteria = EntityQueryCriteria(
                entity_types=["http://vital.ai/ontology/haley-ai-kg#KGEntity"],
                property_constraints=[
                    {"property_uri": "http://vital.ai/ontology/vital-core#name", "property_value": "Bob"}
                ]
            )
            
            # Create destination entity criteria
            dest_criteria = EntityQueryCriteria(
                entity_types=["http://vital.ai/ontology/haley-ai-kg#KGEntity"]
            )
            
            # Create query criteria with entity criteria
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_criteria=source_criteria,
                destination_entity_criteria=dest_criteria,
                exclude_self_connections=True
            )
            
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=10,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'frame_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                
                self.log_test_result(
                    "Query Frames With Entity Criteria",
                    True,
                    f"Successfully queried frame connections with entity criteria (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count, "entity_criteria": "source_name=Bob"}
                )
                return True
            else:
                self.log_test_result(
                    "Query Frames With Entity Criteria",
                    False,
                    "Failed to query frame connections with entity criteria",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Frames With Entity Criteria",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_frames_multiple_entities(self) -> bool:
        """Test querying frame connections for multiple source entities."""
        try:
            # Create query criteria for multiple source entities
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_uris=[
                    "http://vital.ai/test/entity/person/alice",
                    "http://vital.ai/test/entity/person/bob",
                    "http://vital.ai/test/entity/person/charlie"
                ],
                exclude_self_connections=True
            )
            
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=20,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'frame_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                
                # Count unique source entities in results
                unique_sources = set()
                if response.frame_connections:
                    for conn in response.frame_connections:
                        if hasattr(conn, 'source_entity_uri'):
                            unique_sources.add(conn.source_entity_uri)
                
                self.log_test_result(
                    "Query Frames Multiple Entities",
                    True,
                    f"Successfully queried frame connections for multiple entities (found: {connection_count}, total: {total_count}, unique_sources: {len(unique_sources)})",
                    {"connection_count": connection_count, "total_count": total_count, "unique_sources": len(unique_sources)}
                )
                return True
            else:
                self.log_test_result(
                    "Query Frames Multiple Entities",
                    False,
                    "Failed to query frame connections for multiple entities",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Frames Multiple Entities",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_frames_with_pagination(self) -> bool:
        """Test querying frame connections with pagination."""
        try:
            # Create query criteria
            criteria = KGQueryCriteria(
                query_type="frame",
                exclude_self_connections=True
            )
            
            # First page
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=5,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response1 = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            # Second page
            query_request.offset = 5
            response2 = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response1 and hasattr(response1, 'frame_connections') and response2 and hasattr(response2, 'frame_connections'):
                page1_count = len(response1.frame_connections) if response1.frame_connections else 0
                page2_count = len(response2.frame_connections) if response2.frame_connections else 0
                total_count = getattr(response1, 'total_count', 0)
                
                self.log_test_result(
                    "Query Frames With Pagination",
                    True,
                    f"Successfully queried frame connections with pagination (page1: {page1_count}, page2: {page2_count}, total: {total_count})",
                    {"page1_count": page1_count, "page2_count": page2_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Query Frames With Pagination",
                    False,
                    "Failed to query frame connections with pagination",
                    {"response1": str(response1), "response2": str(response2)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Frames With Pagination",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_frames_complex_criteria(self) -> bool:
        """Test querying frame connections with complex criteria combination."""
        try:
            # Create complex slot criteria
            slot_criteria = [
                SlotCriteria(
                    slot_type="http://vital.ai/ontology/haley-ai-kg#hasProjectStatus",
                    slot_value="active"
                ),
                SlotCriteria(
                    slot_type="http://vital.ai/ontology/haley-ai-kg#hasPriority",
                    slot_value="high"
                )
            ]
            
            # Create entity criteria
            source_criteria = EntityQueryCriteria(
                entity_types=["http://vital.ai/ontology/haley-ai-kg#KGEntity"]
            )
            
            # Create complex query criteria
            criteria = KGQueryCriteria(
                query_type="frame",
                source_entity_criteria=source_criteria,
                shared_frame_types=["http://vital.ai/ontology/haley-ai-kg#ProjectFrame"],
                frame_slot_criteria=slot_criteria,
                exclude_self_connections=True
            )
            
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=10,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'frame_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.frame_connections) if response.frame_connections else 0
                
                self.log_test_result(
                    "Query Frames Complex Criteria",
                    True,
                    f"Successfully queried frame connections with complex criteria (found: {connection_count}, total: {total_count})",
                    {
                        "connection_count": connection_count,
                        "total_count": total_count,
                        "frame_types": criteria.shared_frame_types,
                        "slot_criteria_count": len(slot_criteria)
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Query Frames Complex Criteria",
                    False,
                    "Failed to query frame connections with complex criteria",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Frames Complex Criteria",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_frame_query_tests(self) -> Dict[str, bool]:
        """Run all frame query tests."""
        logger.info("🧪 Running KGQueries Frame Query Tests")
        
        results = {}
        
        # Test basic shared frames
        results["query_shared_frames_basic"] = await self.test_query_shared_frames_basic()
        
        # Test frames by type
        results["query_frames_by_type"] = await self.test_query_frames_by_type()
        
        # Test frames with slot criteria
        results["query_frames_with_slot_criteria"] = await self.test_query_frames_with_slot_criteria()
        
        # Test frames with entity criteria
        results["query_frames_with_entity_criteria"] = await self.test_query_frames_with_entity_criteria()
        
        # Test frames for multiple entities
        results["query_frames_multiple_entities"] = await self.test_query_frames_multiple_entities()
        
        # Test frames with pagination
        results["query_frames_with_pagination"] = await self.test_query_frames_with_pagination()
        
        # Test frames with complex criteria
        results["query_frames_complex_criteria"] = await self.test_query_frames_complex_criteria()
        
        return results
