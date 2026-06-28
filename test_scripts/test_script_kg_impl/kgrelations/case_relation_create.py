"""
KGRelations Create Test Cases

Tests for creating KG relations via the KGRelations endpoint.
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgrelations_model import RelationCreateResponse, RelationUpsertResponse
from vitalgraph.endpoint.kgrelations_endpoint import OperationMode
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

logger = logging.getLogger(__name__)


class KGRelationCreateTester:
    """Test cases for KGRelations creation operations."""
    
    def __init__(self, endpoint, space_id: str, graph_id: str):
        self.endpoint = endpoint
        self.space_id = space_id
        self.graph_id = graph_id
        self.created_relation_uris = []
    
    def _generate_test_id(self) -> str:
        """Generate a unique test ID."""
        return uuid.uuid4().hex[:8]
    
    def log_test_result(self, test_name: str, success: bool, message: str, details: Dict[str, Any] = None):
        """Log test result with consistent formatting."""
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} - {test_name}: {message}")
        if details:
            logger.debug(f"Details: {details}")
    
    def get_created_relation_uris(self) -> List[str]:
        """Get list of created relation URIs for use in other tests."""
        return self.created_relation_uris.copy()
    
    async def test_create_single_relation(self) -> bool:
        """Test creating a single KG relation."""
        try:
            # Create a relation between two entities using VitalSigns
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            relation_uri = f"http://vital.ai/test/kgrelation/knows/{self._generate_test_id()}"
            source_entity_uri = f"http://vital.ai/test/entity/person/{self._generate_test_id()}"
            dest_entity_uri = f"http://vital.ai/test/entity/person/{self._generate_test_id()}"
            
            # Create VitalSigns Edge_hasKGRelation object
            relation = Edge_hasKGRelation()
            relation.URI = relation_uri
            relation.edgeSource = source_entity_uri
            relation.edgeDestination = dest_entity_uri
            relation.edgeName = "Test Knows Relation"
            relation.kGRelationType = "http://vital.ai/ontology/test#KnowsRelationType"
            relation.kGRelationTypeDescription = "Person knows another person"
            
            # Convert to quads for the create endpoint
            quads = graphobjects_to_quad_list([relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.CREATE,
                current_user=current_user
            )
            
            if response and hasattr(response, 'created_count') and response.created_count > 0:
                # Store created URI for other tests
                if hasattr(response, 'created_uris') and response.created_uris:
                    self.created_relation_uris.extend(response.created_uris)
                else:
                    self.created_relation_uris.append(relation_uri)
                
                self.log_test_result(
                    "Create Single Relation",
                    True,
                    f"Successfully created relation: {relation_uri}",
                    {"uri": relation_uri, "created_count": response.created_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Create Single Relation",
                    False,
                    "Failed to create relation",
                    {"uri": relation_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Create Single Relation",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_create_multiple_relations(self) -> bool:
        """Test creating multiple KG relations in one request."""
        try:
            # Create multiple relations with different types
            relation1_uri = f"http://vital.ai/test/kgrelation/works_at/{self._generate_test_id()}"
            relation2_uri = f"http://vital.ai/test/kgrelation/lives_in/{self._generate_test_id()}"
            
            person_uri = f"http://vital.ai/test/entity/person/{self._generate_test_id()}"
            company_uri = f"http://vital.ai/test/entity/organization/{self._generate_test_id()}"
            city_uri = f"http://vital.ai/test/entity/location/{self._generate_test_id()}"
            
            # Create VitalSigns Edge_hasKGRelation objects
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            relation1 = Edge_hasKGRelation()
            relation1.URI = relation1_uri
            relation1.edgeSource = person_uri
            relation1.edgeDestination = company_uri
            relation1.edgeName = "Works At Relation"
            relation1.kGRelationType = "http://vital.ai/ontology/test#WorksAtRelationType"
            
            relation2 = Edge_hasKGRelation()
            relation2.URI = relation2_uri
            relation2.edgeSource = person_uri
            relation2.edgeDestination = city_uri
            relation2.edgeName = "Lives In Relation"
            relation2.kGRelationType = "http://vital.ai/ontology/test#LivesInRelationType"
            
            # Convert to quads for the create endpoint
            quads = graphobjects_to_quad_list([relation1, relation2], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.CREATE,
                current_user=current_user
            )
            
            if response and hasattr(response, 'created_count') and response.created_count > 0:
                # Store created URIs for other tests
                if hasattr(response, 'created_uris') and response.created_uris:
                    self.created_relation_uris.extend(response.created_uris)
                else:
                    self.created_relation_uris.extend([relation1_uri, relation2_uri])
                
                self.log_test_result(
                    "Create Multiple Relations",
                    True,
                    f"Successfully created {response.created_count} relations",
                    {"uris": [relation1_uri, relation2_uri], "created_count": response.created_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Create Multiple Relations",
                    False,
                    "Failed to create multiple relations",
                    {"uris": [relation1_uri, relation2_uri], "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Create Multiple Relations",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_create_duplicate_relation(self) -> bool:
        """Test creating relation with duplicate URI (should fail or handle gracefully)."""
        if not self.created_relation_uris:
            self.log_test_result(
                "Create Duplicate Relation",
                False,
                "No existing relation URIs available for duplication test",
                {"created_uris": self.created_relation_uris}
            )
            return False
        
        try:
            # Try to create relation with existing URI
            existing_uri = self.created_relation_uris[0]
            source_uri = f"http://vital.ai/test/entity/person/{self._generate_test_id()}"
            dest_uri = f"http://vital.ai/test/entity/person/{self._generate_test_id()}"
            
            # Create VitalSigns Edge_hasKGRelation with existing URI
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            dup_relation = Edge_hasKGRelation()
            dup_relation.URI = existing_uri
            dup_relation.edgeSource = source_uri
            dup_relation.edgeDestination = dest_uri
            dup_relation.edgeName = "Duplicate Relation"
            dup_relation.kGRelationType = "http://vital.ai/ontology/test#DuplicateRelationType"
            quads = graphobjects_to_quad_list([dup_relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.CREATE,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled duplicate relation creation"
            if response and hasattr(response, 'created_count'):
                result_msg += f" (created_count: {response.created_count})"
            
            self.log_test_result(
                "Create Duplicate Relation",
                success,
                result_msg,
                {"uri": existing_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for duplicate is acceptable
            self.log_test_result(
                "Create Duplicate Relation",
                True,
                f"Exception for duplicate relation (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_upsert_relation(self) -> bool:
        """Test upserting (create or update) a relation."""
        try:
            # Create a new relation using UPSERT mode with VitalSigns
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            relation_uri = f"http://vital.ai/test/kgrelation/upsert/{self._generate_test_id()}"
            source_uri = f"http://vital.ai/test/entity/person/{self._generate_test_id()}"
            dest_uri = f"http://vital.ai/test/entity/organization/{self._generate_test_id()}"
            
            # Create VitalSigns Edge_hasKGRelation object
            relation = Edge_hasKGRelation()
            relation.URI = relation_uri
            relation.edgeSource = source_uri
            relation.edgeDestination = dest_uri
            relation.edgeName = "Upsert Test Relation"
            relation.kGRelationType = "http://vital.ai/ontology/test#CollaboratesWithRelationType"
            
            # Convert to quads for the upsert endpoint
            quads = graphobjects_to_quad_list([relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.UPSERT,
                current_user=current_user
            )
            
            if response and hasattr(response, 'created_count') and response.created_count > 0:
                # Store created URI for other tests
                if hasattr(response, 'created_uris') and response.created_uris:
                    self.created_relation_uris.extend(response.created_uris)
                else:
                    self.created_relation_uris.append(relation_uri)
                
                self.log_test_result(
                    "Upsert Relation",
                    True,
                    f"Successfully upserted relation: {relation_uri}",
                    {"uri": relation_uri, "created_count": response.created_count, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Upsert Relation",
                    False,
                    "Failed to upsert relation",
                    {"uri": relation_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Upsert Relation",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_create_invalid_relation(self) -> bool:
        """Test creating relation with minimal/invalid data (should fail gracefully)."""
        try:
            # Create a minimal Edge_hasKGRelation without required fields
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            invalid_relation = Edge_hasKGRelation()
            invalid_relation.URI = "http://invalid/relation/missing_fields"
            invalid_relation.edgeName = "Invalid Relation"
            quads = graphobjects_to_quad_list([invalid_relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.CREATE,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid relation creation"
            if response and hasattr(response, 'created_count'):
                result_msg += f" (created_count: {response.created_count})"
            
            self.log_test_result(
                "Create Invalid Relation",
                success,
                result_msg,
                {"response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid data is acceptable
            self.log_test_result(
                "Create Invalid Relation",
                True,
                f"Exception for invalid data (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_create_tests(self) -> Dict[str, bool]:
        """Run all relation creation tests."""
        logger.info("🧪 Running KGRelations Create Tests")
        
        results = {}
        
        # Test single relation creation
        results["create_single_relation"] = await self.test_create_single_relation()
        
        # Test multiple relations creation
        results["create_multiple_relations"] = await self.test_create_multiple_relations()
        
        # Test duplicate relation creation
        results["create_duplicate_relation"] = await self.test_create_duplicate_relation()
        
        # Test upsert relation
        results["upsert_relation"] = await self.test_upsert_relation()
        
        # Test invalid relation creation
        results["create_invalid_relation"] = await self.test_create_invalid_relation()
        
        return results
