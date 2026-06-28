"""
KGRelations List Test Cases

Tests for listing KG relations via the KGRelations endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgrelations_model import RelationsResponse

logger = logging.getLogger(__name__)


class KGRelationListTester:
    """Test cases for KGRelations listing operations."""
    
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
    
    async def test_list_empty_relations(self) -> bool:
        """Test listing relations when no relations exist (or stub returns sample data)."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                entity_source_uri=None,
                entity_destination_uri=None,
                relation_type_uri=None,
                direction="all",
                page_size=100,
                offset=0,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relations'):
                # For stub implementation, this will return sample relations or empty
                total_count = getattr(response, 'total_count', 0)
                self.log_test_result(
                    "List Empty Relations",
                    True,
                    f"Successfully listed relations (total: {total_count})",
                    {"total_count": total_count, "page_size": response.page_size, "offset": response.offset}
                )
                return True
            else:
                self.log_test_result(
                    "List Empty Relations",
                    False,
                    "Failed to list relations",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Empty Relations",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_relations_with_pagination(self) -> bool:
        """Test listing relations with pagination parameters."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                entity_source_uri=None,
                entity_destination_uri=None,
                relation_type_uri=None,
                direction="all",
                page_size=5,  # Small page size to test pagination
                offset=0,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relations'):
                total_count = getattr(response, 'total_count', 0)
                page_size = getattr(response, 'page_size', 0)
                offset = getattr(response, 'offset', 0)
                
                self.log_test_result(
                    "List Relations With Pagination",
                    True,
                    f"Successfully listed relations with pagination (total: {total_count}, page_size: {page_size}, offset: {offset})",
                    {"total_count": total_count, "page_size": page_size, "offset": offset}
                )
                return True
            else:
                self.log_test_result(
                    "List Relations With Pagination",
                    False,
                    "Failed to list relations with pagination",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Relations With Pagination",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_relations_by_source_entity(self) -> bool:
        """Test listing relations filtered by source entity."""
        try:
            source_entity_uri = "http://vital.ai/test/entity/person/test_source"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                entity_source_uri=source_entity_uri,
                entity_destination_uri=None,
                relation_type_uri=None,
                direction="all",
                page_size=100,
                offset=0,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relations'):
                total_count = getattr(response, 'total_count', 0)
                self.log_test_result(
                    "List Relations By Source Entity",
                    True,
                    f"Successfully listed relations by source entity (total: {total_count})",
                    {"total_count": total_count, "source_entity": source_entity_uri}
                )
                return True
            else:
                self.log_test_result(
                    "List Relations By Source Entity",
                    False,
                    "Failed to list relations by source entity",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Relations By Source Entity",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_relations_by_destination_entity(self) -> bool:
        """Test listing relations filtered by destination entity."""
        try:
            dest_entity_uri = "http://vital.ai/test/entity/organization/test_dest"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                entity_source_uri=None,
                entity_destination_uri=dest_entity_uri,
                relation_type_uri=None,
                direction="all",
                page_size=100,
                offset=0,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relations'):
                total_count = getattr(response, 'total_count', 0)
                self.log_test_result(
                    "List Relations By Destination Entity",
                    True,
                    f"Successfully listed relations by destination entity (total: {total_count})",
                    {"total_count": total_count, "destination_entity": dest_entity_uri}
                )
                return True
            else:
                self.log_test_result(
                    "List Relations By Destination Entity",
                    False,
                    "Failed to list relations by destination entity",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Relations By Destination Entity",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_relations_by_type(self) -> bool:
        """Test listing relations filtered by relation type."""
        try:
            relation_type_uri = "http://vital.ai/ontology/haley-ai-kg#knows"
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                entity_source_uri=None,
                entity_destination_uri=None,
                relation_type_uri=relation_type_uri,
                direction="all",
                page_size=100,
                offset=0,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relations'):
                total_count = getattr(response, 'total_count', 0)
                self.log_test_result(
                    "List Relations By Type",
                    True,
                    f"Successfully listed relations by type (total: {total_count})",
                    {"total_count": total_count, "relation_type": relation_type_uri}
                )
                return True
            else:
                self.log_test_result(
                    "List Relations By Type",
                    False,
                    "Failed to list relations by type",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Relations By Type",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_relations_by_direction(self) -> bool:
        """Test listing relations filtered by direction."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            
            # Test outgoing direction
            response = await self.endpoint._list_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                entity_source_uri=None,
                entity_destination_uri=None,
                relation_type_uri=None,
                direction="outgoing",
                page_size=100,
                offset=0,
                current_user=current_user
            )
            
            if response and hasattr(response, 'relations'):
                total_count = getattr(response, 'total_count', 0)
                self.log_test_result(
                    "List Relations By Direction",
                    True,
                    f"Successfully listed relations by direction (total: {total_count})",
                    {"total_count": total_count, "direction": "outgoing"}
                )
                return True
            else:
                self.log_test_result(
                    "List Relations By Direction",
                    False,
                    "Failed to list relations by direction",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Relations By Direction",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_list_relations_large_offset(self) -> bool:
        """Test listing relations with large offset (edge case)."""
        try:
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._list_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                entity_source_uri=None,
                entity_destination_uri=None,
                relation_type_uri=None,
                direction="all",
                page_size=10,
                offset=1000,  # Large offset beyond available data
                current_user=current_user
            )
            
            if response and hasattr(response, 'relations'):
                total_count = getattr(response, 'total_count', 0)
                offset = getattr(response, 'offset', 0)
                
                self.log_test_result(
                    "List Relations Large Offset",
                    True,
                    f"Successfully handled large offset (total: {total_count}, offset: {offset})",
                    {"total_count": total_count, "offset": offset}
                )
                return True
            else:
                self.log_test_result(
                    "List Relations Large Offset",
                    False,
                    "Failed to handle large offset",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "List Relations Large Offset",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def run_all_list_tests(self) -> Dict[str, bool]:
        """Run all relation listing tests."""
        logger.info("🧪 Running KGRelations List Tests")
        
        results = {}
        
        # Test empty relations listing
        results["list_empty_relations"] = await self.test_list_empty_relations()
        
        # Test pagination
        results["list_relations_with_pagination"] = await self.test_list_relations_with_pagination()
        
        # Test filtering by source entity
        results["list_relations_by_source_entity"] = await self.test_list_relations_by_source_entity()
        
        # Test filtering by destination entity
        results["list_relations_by_destination_entity"] = await self.test_list_relations_by_destination_entity()
        
        # Test filtering by relation type
        results["list_relations_by_type"] = await self.test_list_relations_by_type()
        
        # Test filtering by direction
        results["list_relations_by_direction"] = await self.test_list_relations_by_direction()
        
        # Test large offset
        results["list_relations_large_offset"] = await self.test_list_relations_large_offset()
        
        return results
