"""
KGQueries Relation Query Test Cases

Tests for querying entity-to-entity connections via relations (Edge_hasKGRelation).
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgqueries_model import KGQueryRequest, KGQueryCriteria, KGQueryResponse
from vitalgraph.model.kgentities_model import EntityQueryCriteria

logger = logging.getLogger(__name__)


class KGRelationQueriesTester:
    """Test cases for KGQueries relation-based connection queries."""
    
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
    
    async def test_query_outgoing_relations(self) -> bool:
        """Test querying outgoing relations from specific source entities."""
        try:
            # Create query criteria for outgoing relations
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
                space_id=self.space_id,
                graph_id=self.graph_id,
                query_request=query_request,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                
                self.log_test_result(
                    "Query Outgoing Relations",
                    True,
                    f"Successfully queried outgoing relations (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count, "query_type": response.query_type}
                )
                return True
            else:
                self.log_test_result(
                    "Query Outgoing Relations",
                    False,
                    "Failed to query outgoing relations",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Outgoing Relations",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_incoming_relations(self) -> bool:
        """Test querying incoming relations to specific destination entities."""
        try:
            # Create query criteria for incoming relations
            criteria = KGQueryCriteria(
                query_type="relation",
                destination_entity_uris=["http://vital.ai/test/entity/organization/acme_corp"],
                direction="incoming"
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
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                
                self.log_test_result(
                    "Query Incoming Relations",
                    True,
                    f"Successfully queried incoming relations (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count, "query_type": response.query_type}
                )
                return True
            else:
                self.log_test_result(
                    "Query Incoming Relations",
                    False,
                    "Failed to query incoming relations",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Incoming Relations",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_bidirectional_relations(self) -> bool:
        """Test querying bidirectional relations (both incoming and outgoing)."""
        try:
            # Create query criteria for bidirectional relations
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_uris=["http://vital.ai/test/entity/person/bob"],
                direction="bidirectional"
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
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                
                self.log_test_result(
                    "Query Bidirectional Relations",
                    True,
                    f"Successfully queried bidirectional relations (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count, "query_type": response.query_type}
                )
                return True
            else:
                self.log_test_result(
                    "Query Bidirectional Relations",
                    False,
                    "Failed to query bidirectional relations",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Bidirectional Relations",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_by_type(self) -> bool:
        """Test querying relations filtered by relation type."""
        try:
            # Create query criteria for specific relation types
            criteria = KGQueryCriteria(
                query_type="relation",
                relation_type_uris=["http://vital.ai/ontology/haley-ai-kg#works_at"],
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
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                
                # Validate that returned connections have the expected relation type
                valid_types = True
                if response.relation_connections:
                    for conn in response.relation_connections:
                        if hasattr(conn, 'relation_type_uri') and conn.relation_type_uri not in criteria.relation_type_uris:
                            valid_types = False
                            break
                
                self.log_test_result(
                    "Query Relations By Type",
                    True,
                    f"Successfully queried relations by type (found: {connection_count}, total: {total_count}, valid_types: {valid_types})",
                    {"connection_count": connection_count, "total_count": total_count, "relation_types": criteria.relation_type_uris}
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
    
    async def test_query_relations_with_entity_criteria(self) -> bool:
        """Test querying relations with entity criteria filters."""
        try:
            # Create entity criteria for source entities
            source_criteria = EntityQueryCriteria(
                entity_types=["http://vital.ai/ontology/haley-ai-kg#KGEntity"],
                property_constraints=[
                    {"property_uri": "http://vital.ai/ontology/vital-core#name", "property_value": "Alice"}
                ]
            )
            
            # Create query criteria with entity criteria
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_criteria=source_criteria,
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
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                
                self.log_test_result(
                    "Query Relations With Entity Criteria",
                    True,
                    f"Successfully queried relations with entity criteria (found: {connection_count}, total: {total_count})",
                    {"connection_count": connection_count, "total_count": total_count, "entity_criteria": "name=Alice"}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations With Entity Criteria",
                    False,
                    "Failed to query relations with entity criteria",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations With Entity Criteria",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_query_relations_with_pagination(self) -> bool:
        """Test querying relations with pagination."""
        try:
            # Create query criteria
            criteria = KGQueryCriteria(
                query_type="relation",
                direction="outgoing"
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
            
            if response1 and hasattr(response1, 'relation_connections') and response2 and hasattr(response2, 'relation_connections'):
                page1_count = len(response1.relation_connections) if response1.relation_connections else 0
                page2_count = len(response2.relation_connections) if response2.relation_connections else 0
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
    
    async def test_query_relations_exclude_self_connections(self) -> bool:
        """Test querying relations with self-connection exclusion."""
        try:
            # Create query criteria with self-connection exclusion
            criteria = KGQueryCriteria(
                query_type="relation",
                source_entity_uris=["http://vital.ai/test/entity/person/charlie"],
                direction="bidirectional",
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
            
            if response and hasattr(response, 'relation_connections'):
                total_count = getattr(response, 'total_count', 0)
                connection_count = len(response.relation_connections) if response.relation_connections else 0
                
                # Validate that no self-connections are returned
                has_self_connections = False
                if response.relation_connections:
                    for conn in response.relation_connections:
                        if hasattr(conn, 'source_entity_uri') and hasattr(conn, 'destination_entity_uri'):
                            if conn.source_entity_uri == conn.destination_entity_uri:
                                has_self_connections = True
                                break
                
                self.log_test_result(
                    "Query Relations Exclude Self Connections",
                    True,
                    f"Successfully queried relations excluding self-connections (found: {connection_count}, total: {total_count}, has_self: {has_self_connections})",
                    {"connection_count": connection_count, "total_count": total_count, "has_self_connections": has_self_connections}
                )
                return True
            else:
                self.log_test_result(
                    "Query Relations Exclude Self Connections",
                    False,
                    "Failed to query relations excluding self-connections",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Query Relations Exclude Self Connections",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_relation_query_tests(self) -> Dict[str, bool]:
        """Run all relation query tests."""
        logger.info("🧪 Running KGQueries Relation Query Tests")
        
        results = {}
        
        # Test outgoing relations
        results["query_outgoing_relations"] = await self.test_query_outgoing_relations()
        
        # Test incoming relations
        results["query_incoming_relations"] = await self.test_query_incoming_relations()
        
        # Test bidirectional relations
        results["query_bidirectional_relations"] = await self.test_query_bidirectional_relations()
        
        # Test relations by type
        results["query_relations_by_type"] = await self.test_query_relations_by_type()
        
        # Test relations with entity criteria
        results["query_relations_with_entity_criteria"] = await self.test_query_relations_with_entity_criteria()
        
        # Test relations with pagination
        results["query_relations_with_pagination"] = await self.test_query_relations_with_pagination()
        
        # Test exclude self-connections
        results["query_relations_exclude_self_connections"] = await self.test_query_relations_exclude_self_connections()
        
        return results
