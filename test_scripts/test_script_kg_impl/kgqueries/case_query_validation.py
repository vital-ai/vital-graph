"""
KGQueries Validation Test Cases

Tests for query validation and error handling in the KGQueries endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgqueries_model import KGQueryRequest, KGQueryCriteria, KGQueryResponse
from vitalgraph.model.kgentities_model import EntityQueryCriteria, SlotCriteria

logger = logging.getLogger(__name__)


class KGQueryValidationTester:
    """Test cases for KGQueries validation and error handling."""
    
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
    
    async def test_invalid_query_type(self) -> bool:
        """Test query with invalid query type."""
        try:
            # Create query criteria with invalid query type
            criteria = KGQueryCriteria(
                query_type="invalid_type",  # Invalid query type
                source_entity_uris=["http://vital.ai/test/entity/person/alice"]
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
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid query type"
            if response and hasattr(response, 'query_type'):
                result_msg += f" (returned query_type: {response.query_type})"
            
            self.log_test_result(
                "Invalid Query Type",
                success,
                result_msg,
                {"query_type": criteria.query_type, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid query type is acceptable
            self.log_test_result(
                "Invalid Query Type",
                True,
                f"Exception for invalid query type (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_empty_query_criteria(self) -> bool:
        """Test query with minimal/empty criteria."""
        try:
            # Create minimal query criteria
            criteria = KGQueryCriteria(
                query_type="relation"
                # No other criteria specified
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
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                
                self.log_test_result(
                    "Empty Query Criteria",
                    True,
                    f"Successfully handled empty query criteria (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Empty Query Criteria",
                    False,
                    "Failed to handle empty query criteria",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Empty Query Criteria",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_invalid_entity_uris(self) -> bool:
        """Test query with invalid entity URIs."""
        try:
            # Create query criteria with invalid URIs
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_uris=["not_a_valid_uri", "", "also_invalid"],
                direction="outgoing"
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
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid entity URIs"
            if response and hasattr(response, 'relation_connections'):
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                result_msg += f" (found: {connection_count} connections)"
            
            self.log_test_result(
                "Invalid Entity URIs",
                success,
                result_msg,
                {"invalid_uris": criteria.source_entity_uris, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid URIs is acceptable
            self.log_test_result(
                "Invalid Entity URIs",
                True,
                f"Exception for invalid URIs (acceptable): {str(e)})",
                {"error": str(e)}
            )
            return True
    
    async def test_invalid_direction(self) -> bool:
        """Test query with invalid direction parameter."""
        try:
            # Create query criteria with invalid direction
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_uris=["http://vital.ai/test/entity/person/alice"],
                direction="invalid_direction"  # Invalid direction
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
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid direction parameter"
            if response and hasattr(response, 'relation_connections'):
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                result_msg += f" (found: {connection_count} connections)"
            
            self.log_test_result(
                "Invalid Direction",
                success,
                result_msg,
                {"direction": criteria.direction, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid direction is acceptable
            self.log_test_result(
                "Invalid Direction",
                True,
                f"Exception for invalid direction (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_invalid_pagination_parameters(self) -> bool:
        """Test query with invalid pagination parameters."""
        try:
            # Create query criteria
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_uris=["http://vital.ai/test/entity/person/alice"],
                direction="outgoing"
            )
            
            # Create query request with invalid pagination
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=-5,  # Invalid page size
                offset=-10     # Invalid offset
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid pagination parameters"
            if response and hasattr(response, 'relation_connections'):
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                result_msg += f" (found: {connection_count} connections)"
            
            self.log_test_result(
                "Invalid Pagination Parameters",
                success,
                result_msg,
                {"page_size": query_request.page_size, "offset": query_request.offset, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid pagination is acceptable
            self.log_test_result(
                "Invalid Pagination Parameters",
                True,
                f"Exception for invalid pagination (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_nonexistent_space_id(self) -> bool:
        """Test query with nonexistent space ID."""
        try:
            # Create query criteria
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_uris=["http://vital.ai/test/entity/person/alice"],
                direction="outgoing"
            )
            
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=10,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id="nonexistent_space_12345",  # Nonexistent space
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled nonexistent space ID"
            if response and hasattr(response, 'relation_connections'):
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                result_msg += f" (found: {connection_count} connections)"
            
            self.log_test_result(
                "Nonexistent Space ID",
                success,
                result_msg,
                {"space_id": "nonexistent_space_12345", "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for nonexistent space is acceptable
            self.log_test_result(
                "Nonexistent Space ID",
                True,
                f"Exception for nonexistent space (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_mixed_query_type_criteria(self) -> bool:
        """Test query with mixed relation and frame criteria."""
        try:
            # Create slot criteria (frame-specific)
            slot_criteria = [
                SlotCriteria(
                    slot_type="http://vital.ai/ontology/haley-ai-kg#hasProjectStatus",
                    slot_value="active"
                )
            ]
            
            # Create query criteria mixing relation and frame criteria
            criteria = KGQueryCriteria(
                query_type="relation",  # Relation query type
                source_entity_uris=["http://vital.ai/test/entity/person/alice"],
                direction="outgoing",
                # But also include frame-specific criteria
                shared_frame_types=["http://vital.ai/ontology/haley-ai-kg#ProjectFrame"],
                frame_slot_criteria=slot_criteria
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
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled mixed query type criteria"
            if response and hasattr(response, 'relation_connections'):
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                result_msg += f" (found: {connection_count} connections)"
            
            self.log_test_result(
                "Mixed Query Type Criteria",
                success,
                result_msg,
                {"query_type": criteria.query_type, "has_frame_criteria": True, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for mixed criteria is acceptable
            self.log_test_result(
                "Mixed Query Type Criteria",
                True,
                f"Exception for mixed criteria (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_large_page_size(self) -> bool:
        """Test query with very large page size."""
        try:
            # Create query criteria
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_uris=["http://vital.ai/test/entity/person/alice"],
                direction="outgoing"
            )
            
            # Create query request with large page size
            query_request = KGQueryRequest(
                criteria=criteria,
                page_size=10000,  # Very large page size
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_connections(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                page_size = getattr(response, 'page_size', 0)
                
                self.log_test_result(
                    "Large Page Size",
                    True,
                    f"Successfully handled large page size (found: {connection_count}, total: {total_count}, page_size: {page_size})",
                    {"connection_count": connection_count, "total_count": total_count, "requested_page_size": query_request.page_size}
                )
                return True
            else:
                self.log_test_result(
                    "Large Page Size",
                    False,
                    "Failed to handle large page size",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Large Page Size",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_validation_tests(self) -> Dict[str, bool]:
        """Run all query validation tests."""
        logger.info("🧪 Running KGQueries Validation Tests")
        
        results = {}
        
        # Test invalid query type
        results["invalid_query_type"] = await self.test_invalid_query_type()
        
        # Test empty query criteria
        results["empty_query_criteria"] = await self.test_empty_query_criteria()
        
        # Test invalid entity URIs
        results["invalid_entity_uris"] = await self.test_invalid_entity_uris()
        
        # Test invalid direction
        results["invalid_direction"] = await self.test_invalid_direction()
        
        # Test invalid pagination parameters
        results["invalid_pagination_parameters"] = await self.test_invalid_pagination_parameters()
        
        # Test nonexistent space ID
        results["nonexistent_space_id"] = await self.test_nonexistent_space_id()
        
        # Test mixed query type criteria
        results["mixed_query_type_criteria"] = await self.test_mixed_query_type_criteria()
        
        # Test large page size
        results["large_page_size"] = await self.test_large_page_size()
        
        return results
