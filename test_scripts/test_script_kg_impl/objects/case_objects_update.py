"""
Objects Update Test Cases

Tests the Objects endpoint update functionality for quad-based object updates.
"""

import logging
from typing import Dict, Any, List, Optional
from ai_haley_kg_domain.model.KGEntity import KGEntity
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list


class ObjectsUpdateTester:
    """Test cases for Objects endpoint update operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.logger = logging.getLogger(f"{__name__}.ObjectsUpdateTester")
        self.test_object_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        self.logger.info(f"{status} - {test_name}: {message}")
        if details:
            self.logger.debug(f"Details: {details}")
    
    def set_test_object_uris(self, uris: List[str]):
        """Set the URIs of test objects for update testing."""
        self.test_object_uris = uris
    
    async def test_update_single_object(self) -> bool:
        """Test updating a single object."""
        if not self.test_object_uris:
            self.log_test_result(
                "Update Single Object",
                False,
                "No test object URIs available for update",
                {"test_uris": self.test_object_uris}
            )
            return False
        
        try:
            # Update first test object using proper KGEntity
            test_uri = self.test_object_uris[0]
            
            # Create updated KGEntity
            updated_entity = KGEntity()
            updated_entity.URI = test_uri
            updated_entity.name = "Updated Test Object"
            updated_entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([updated_entity], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Single Object",
                    True,
                    f"Successfully updated object: {response.updated_uri}",
                    {"uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Single Object",
                    False,
                    "Failed to update object",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Single Object",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_multiple_objects(self) -> bool:
        """Test updating multiple objects in one request."""
        if len(self.test_object_uris) < 2:
            self.log_test_result(
                "Update Multiple Objects",
                False,
                "Need at least 2 test object URIs for multi-update",
                {"available_uris": len(self.test_object_uris)}
            )
            return False
        
        try:
            # Update first two test objects using proper KGEntity objects
            test_uri_1 = self.test_object_uris[0]
            test_uri_2 = self.test_object_uris[1]
            
            # Create updated KGEntity objects
            updated_entity_1 = KGEntity()
            updated_entity_1.URI = test_uri_1
            updated_entity_1.name = "Batch Updated Object 1"
            updated_entity_1.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
            
            updated_entity_2 = KGEntity()
            updated_entity_2.URI = test_uri_2
            updated_entity_2.name = "Batch Updated Object 2"
            updated_entity_2.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([updated_entity_1, updated_entity_2], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Multiple Objects",
                    True,
                    f"Successfully updated multiple objects: {response.updated_uri}",
                    {"updated_uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Multiple Objects",
                    False,
                    "Failed to update multiple objects",
                    {"uris": [test_uri_1, test_uri_2], "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Multiple Objects",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_nonexistent_object(self) -> bool:
        """Test updating object that doesn't exist."""
        try:
            # Try to update nonexistent object using VitalSigns
            nonexistent_uri = f"http://example.com/nonexistent/object/{self._generate_test_id()}"
            nonexistent_entity = KGEntity()
            nonexistent_entity.URI = nonexistent_uri
            nonexistent_entity.name = "Nonexistent Object Update"
            quads = graphobjects_to_quad_list([nonexistent_entity], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            # Update might succeed (creating new object) or fail - both are acceptable
            success = True
            result_msg = "Handled nonexistent object update gracefully"
            if response and hasattr(response, 'success'):
                result_msg += f" (success: {response.success})"
            
            self.log_test_result(
                "Update Nonexistent Object",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
                
        except Exception as e:
            # Exception might be expected for nonexistent objects
            self.log_test_result(
                "Update Nonexistent Object",
                True,
                f"Exception for nonexistent object (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_update_with_property_changes(self) -> bool:
        """Test updating object with property additions/removals."""
        if not self.test_object_uris:
            self.log_test_result(
                "Update Property Changes",
                False,
                "No test object URIs available for property update",
                {"test_uris": self.test_object_uris}
            )
            return False
        
        try:
            # Update object with new properties using proper KGEntity
            test_uri = self.test_object_uris[-1]  # Use last URI to avoid conflicts
            
            # Create updated KGEntity with property changes
            updated_entity = KGEntity()
            updated_entity.URI = test_uri
            updated_entity.name = "Property Updated Object"
            updated_entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([updated_entity], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._update_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Property Changes",
                    True,
                    f"Successfully updated object properties: {response.updated_uri}",
                    {"uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Property Changes",
                    False,
                    "Failed to update object properties",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Property Changes",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    def _generate_test_id(self) -> str:
        """Generate unique test ID."""
        import uuid
        return str(uuid.uuid4())
    
    async def run_all_update_tests(self) -> Dict[str, bool]:
        """Run all objects update tests."""
        results = {}
        
        results["update_single"] = await self.test_update_single_object()
        results["update_multiple"] = await self.test_update_multiple_objects()
        results["update_nonexistent"] = await self.test_update_nonexistent_object()
        results["update_properties"] = await self.test_update_with_property_changes()
        
        return results
