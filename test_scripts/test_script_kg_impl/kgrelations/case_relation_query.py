"""
KGRelations Query Test Cases

Tests for querying KG relations via the KGRelations endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgrelations_model import RelationQueryRequest, RelationQueryCriteria, RelationQueryResponse

logger = logging.getLogger(__name__)


class KGRelationQueryTester:
    """Test cases for KGRelations query operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.test_relation_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name}: {message}")
        if details:
            logger.debug(f"Details: {details}")
    
    def set_test_relation_uris(self, uris: List[str]):
        """Set test relation URIs from create tests."""
        self.test_relation_uris = uris.copy()
    
    async def test_query_relations_by_source_entity(self) -> bool:
        """Test querying relations by source entity."""
        try:
            # Create query criteria for source entity
            criteria = RelationQueryCriteria(
                entity_source_uri="http://vital.ai/test/entity/person/query_source",
                direction="outgoing"
            )
            
            query_request = RelationQueryRequest(
                criteria=criteria,
                page_size=10,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_uris'):
                total_count = getattr(response, 'total_count', 0)
                relation_count = len(response.relation_uris)
                
                self.log_test_result(
                    "Query Relations By Source Entity",
                    True,
                    f"Successfully queried relations by source entity (found: {relation_count}, total: {total_count})",
                    {"source_entity": criteria.entity_source_uri, "relation_count": relation_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations By Source Entity",
                    False,
                    "Failed to query relations by source entity",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations By Source Entity",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_by_destination_entity(self) -> bool:
        """Test querying relations by destination entity."""
        try:
            # Create query criteria for destination entity
            criteria = RelationQueryCriteria(
                entity_destination_uri="http://vital.ai/test/entity/organization/query_dest",
                direction="incoming"
            )
            
            query_request = RelationQueryRequest(
                criteria=criteria,
                page_size=10,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_uris'):
                total_count = getattr(response, 'total_count', 0)
                relation_count = len(response.relation_uris)
                
                self.log_test_result(
                    "Query Relations By Destination Entity",
                    True,
                    f"Successfully queried relations by destination entity (found: {relation_count}, total: {total_count})",
                    {"destination_entity": criteria.entity_destination_uri, "relation_count": relation_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations By Destination Entity",
                    False,
                    "Failed to query relations by destination entity",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations By Destination Entity",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_by_type(self) -> bool:
        """Test querying relations by relation type."""
        try:
            # Create query criteria for relation type
            criteria = RelationQueryCriteria(
                relation_type_uri="http://vital.ai/ontology/haley-ai-kg#knows",
                direction="all"
            )
            
            query_request = RelationQueryRequest(
                criteria=criteria,
                page_size=20,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_uris'):
                total_count = getattr(response, 'total_count', 0)
                relation_count = len(response.relation_uris)
                
                self.log_test_result(
                    "Query Relations By Type",
                    True,
                    f"Successfully queried relations by type (found: {relation_count}, total: {total_count})",
                    {"relation_type": criteria.relation_type_uri, "relation_count": relation_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations By Type",
                    False,
                    "Failed to query relations by type",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations By Type",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_with_search_string(self) -> bool:
        """Test querying relations with search string."""
        try:
            # Create query criteria with search string
            criteria = RelationQueryCriteria(
                search_string="collaboration",
                direction="all"
            )
            
            query_request = RelationQueryRequest(
                criteria=criteria,
                page_size=15,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_uris'):
                total_count = getattr(response, 'total_count', 0)
                relation_count = len(response.relation_uris)
                
                self.log_test_result(
                    "Query Relations With Search String",
                    True,
                    f"Successfully queried relations with search string (found: {relation_count}, total: {total_count})",
                    {"search_string": criteria.search_string, "relation_count": relation_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations With Search String",
                    False,
                    "Failed to query relations with search string",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations With Search String",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_complex_criteria(self) -> bool:
        """Test querying relations with complex criteria (multiple filters)."""
        try:
            # Create complex query criteria
            criteria = RelationQueryCriteria(
                entity_source_uri="http://vital.ai/test/entity/person/complex_source",
                relation_type_uri="http://vital.ai/ontology/haley-ai-kg#works_at",
                direction="outgoing",
                search_string="employment"
            )
            
            query_request = RelationQueryRequest(
                criteria=criteria,
                page_size=5,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_uris'):
                total_count = getattr(response, 'total_count', 0)
                relation_count = len(response.relation_uris)
                
                self.log_test_result(
                    "Query Relations Complex Criteria",
                    True,
                    f"Successfully queried relations with complex criteria (found: {relation_count}, total: {total_count})",
                    {
                        "source_entity": criteria.entity_source_uri,
                        "relation_type": criteria.relation_type_uri,
                        "search_string": criteria.search_string,
                        "direction": criteria.direction,
                        "relation_count": relation_count,
                        "total_count": total_count
                    }
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations Complex Criteria",
                    False,
                    "Failed to query relations with complex criteria",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations Complex Criteria",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_with_pagination(self) -> bool:
        """Test querying relations with pagination."""
        try:
            # Create query criteria with pagination
            criteria = RelationQueryCriteria(
                direction="all"
            )
            
            # First page
            query_request = RelationQueryRequest(
                criteria=criteria,
                page_size=3,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response1 = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            # Second page
            query_request.offset = 3
            response2 = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response1 and hasattr(response1, 'relation_uris') and response2 and hasattr(response2, 'relation_uris'):
                page1_count = len(response1.relation_uris)
                page2_count = len(response2.relation_uris)
                total_count = getattr(response1, 'total_count', 0)
                
                self.log_test_result(
                    "Query Relations With Pagination",
                    True,
                    f"Successfully queried relations with pagination (page1: {page1_count}, page2: {page2_count}, total: {total_count})",
                    {"page1_count": page1_count, "page2_count": page2_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations With Pagination",
                    False,
                    "Failed to query relations with pagination",
                    {"response1": str(response1), "response2": str(response2)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations With Pagination",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_empty_criteria(self) -> bool:
        """Test querying relations with minimal/empty criteria."""
        try:
            # Create minimal query criteria
            criteria = RelationQueryCriteria(
                direction="all"
            )
            
            query_request = RelationQueryRequest(
                criteria=criteria,
                page_size=100,
                offset=0
            )
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._query_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_uris'):
                total_count = getattr(response, 'total_count', 0)
                relation_count = len(response.relation_uris)
                
                self.log_test_result(
                    "Query Relations Empty Criteria",
                    True,
                    f"Successfully queried relations with minimal criteria (found: {relation_count}, total: {total_count})",
                    {"relation_count": relation_count, "total_count": total_count}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations Empty Criteria",
                    False,
                    "Failed to query relations with minimal criteria",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations Empty Criteria",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_query_tests(self) -> Dict[str, bool]:
        """Run all relation query tests."""
        logger.info("🧪 Running KGRelations Query Tests")
        
        results = {}
        
        # Test query by source entity
        results["query_relations_by_source_entity"] = await self.test_query_relations_by_source_entity()
        
        # Test query by destination entity
        results["query_relations_by_destination_entity"] = await self.test_query_relations_by_destination_entity()
        
        # Test query by relation type
        results["query_relations_by_type"] = await self.test_query_relations_by_type()
        
        # Test query with search string
        results["query_relations_with_search_string"] = await self.test_query_relations_with_search_string()
        
        # Test query with complex criteria
        results["query_relations_complex_criteria"] = await self.test_query_relations_complex_criteria()
        
        # Test query with pagination
        results["query_relations_with_pagination"] = await self.test_query_relations_with_pagination()
        
        # Test query with empty criteria
        results["query_relations_empty_criteria"] = await self.test_query_relations_empty_criteria()
        
        return results
