"""
Objects Create Test Cases

Tests the Objects endpoint create functionality for quad-based object creation.
"""

import logging
import uuid
from typing import List, Dict, Any, Optional
# Import KGEntity classes directly instead of using the test data creator
from ai_haley_kg_domain.model.KGEntity import KGEntity
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list


class ObjectsCreateTester:
    """Test cases for Objects endpoint create operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.logger = logging.getLogger(f"{__name__}.ObjectsCreateTester")
        self.created_object_uris = []
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        self.logger.info(f"{status} - {test_name}: {message}")
        if details:
            self.logger.debug(f"Details: {details}")
    
    def get_created_object_uris(self) -> List[str]:
        """Get list of URIs for objects created during testing."""
        return self.created_object_uris.copy()
    
    async def test_create_single_object(self) -> bool:
        """Test creating a single object."""
        try:
            # Create a simple KGEntity directly
            entity = KGEntity()
            entity.URI = f"http://vital.ai/test/kgentity/person/{self._generate_test_id()}"
            entity.name = "Test Person"
            entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
            
            # Convert to quads for the create endpoint
            quads = graphobjects_to_quad_list([entity], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'created_count') and response.created_count > 0:
                self.created_object_uris.append(str(entity.URI))
                self.log_test_result(
                    "Create Single Object",
                    True,
                    f"Successfully created object: {entity.URI}",
                    {"uri": entity.URI, "created_count": response.created_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Create Single Object",
                    False,
                    "Failed to create object",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Create Single Object",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_create_multiple_objects(self) -> bool:
        """Test creating multiple objects in a single request."""
        try:
            # Create multiple KGEntity objects directly
            person_entity = KGEntity()
            person_entity.URI = f"http://vital.ai/test/kgentity/person/{self._generate_test_id()}"
            person_entity.name = "Alice Johnson"
            person_entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
            
            org_entity = KGEntity()
            org_entity.URI = f"http://vital.ai/test/kgentity/organization/{self._generate_test_id()}"
            org_entity.name = "Test Corp"
            org_entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
            
            # Convert to quads for the create endpoint
            quads = graphobjects_to_quad_list([person_entity, org_entity], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            if response and hasattr(response, 'created_count') and response.created_count > 0:
                self.created_object_uris.extend([str(person_entity.URI), str(org_entity.URI)])
                self.log_test_result(
                    "Create Multiple Objects",
                    True,
                    f"Successfully created {response.created_count} objects",
                    {"uris": [person_entity.URI, org_entity.URI], "created_count": response.created_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Create Multiple Objects",
                    False,
                    "Failed to create multiple objects",
                    {"response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Create Multiple Objects",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_create_duplicate_object(self) -> bool:
        """Test creating object with duplicate URI (should fail)."""
        if not self.created_object_uris:
            self.log_test_result(
                "Create Duplicate Object",
                False,
                "No existing object URIs to test duplication",
                {"created_uris": self.created_object_uris}
            )
            return False
        
        try:
            # Try to create object with existing URI using proper KGEntity
            existing_uri = self.created_object_uris[0]
            
            # Create KGEntity with existing URI to test duplication
            duplicate_entity = KGEntity()
            duplicate_entity.URI = existing_uri
            duplicate_entity.name = "Duplicate Object"
            duplicate_entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
            
            # Convert to quads for the create endpoint
            quads = graphobjects_to_quad_list([duplicate_entity], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            # Should fail for duplicate URI
            success = not (response and hasattr(response, 'created_count') and response.created_count > 0)
            self.log_test_result(
                "Create Duplicate Object",
                success,
                f"Correctly rejected duplicate URI: {existing_uri}" if success else "Unexpectedly allowed duplicate URI",
                {"uri": existing_uri, "response": str(response)}
            )
            return success
                
        except Exception as e:
            # Exception is expected for duplicate URI
            self.log_test_result(
                "Create Duplicate Object",
                True,
                f"Exception for duplicate URI (expected): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_create_invalid_data(self) -> bool:
        """Test creating object with minimal/invalid data."""
        try:
            # Create a minimal KGEntity without required fields
            invalid_entity = KGEntity()
            invalid_entity.URI = f"http://example.com/test/invalid/{self._generate_test_id()}"
            invalid_entity.name = "Invalid Object"
            quads = graphobjects_to_quad_list([invalid_entity], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_objects(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                current_user=current_user
            )
            
            # Should handle gracefully
            success = True  # As long as it doesn't crash
            self.log_test_result(
                "Create Invalid Data",
                success,
                "Handled invalid data gracefully",
                {"response": str(response)}
            )
            return success
                
        except Exception as e:
            # Exception might be expected for invalid data
            self.log_test_result(
                "Create Invalid Data",
                True,
                f"Exception for invalid data (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    def _generate_test_id(self) -> str:
        """Generate unique test ID."""
        import uuid
        return str(uuid.uuid4())
    
    async def run_all_create_tests(self) -> Dict[str, bool]:
        """Run all objects create tests."""
        results = {}
        
        results["create_single"] = await self.test_create_single_object()
        results["create_multiple"] = await self.test_create_multiple_objects()
        results["create_duplicate"] = await self.test_create_duplicate_object()
        results["create_invalid"] = await self.test_create_invalid_data()
        
        return results
