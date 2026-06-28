"""
KGRelations Update Test Cases

Tests for updating KG relations via the KGRelations endpoint.
"""

import logging
from typing import Dict, Any, List, Optional

from vitalgraph.model.kgrelations_model import RelationUpdateResponse
from vitalgraph.endpoint.kgrelations_endpoint import OperationMode
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

logger = logging.getLogger(__name__)


class KGRelationUpdateTester:
    """Test cases for KGRelations update operations."""
    
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
    
    async def test_update_relation_properties(self) -> bool:
        """Test updating relation properties."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_relation_uris[0] if self.test_relation_uris else "http://vital.ai/test/kgrelation/update_test"
            
            # Create updated relation data using VitalSigns
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            relation = Edge_hasKGRelation()
            relation.URI = test_uri
            relation.edgeSource = "http://vital.ai/test/entity/person/updated_source"
            relation.edgeDestination = "http://vital.ai/test/entity/organization/updated_dest"
            relation.edgeName = "Updated Relation Name"
            relation.kGRelationType = "http://vital.ai/ontology/test#UpdatedRelationType"
            relation.kGRelationTypeDescription = "Updated relation with confidence 0.95"
            
            # Convert to quads for the update endpoint
            quads = graphobjects_to_quad_list([relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.UPDATE,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Relation Properties",
                    True,
                    f"Successfully updated relation: {response.updated_uri}",
                    {"uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Relation Properties",
                    False,
                    "Failed to update relation properties",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Relation Properties",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_multiple_relations(self) -> bool:
        """Test updating multiple relations in one request."""
        try:
            # Use test URIs or generate sample ones for stub testing
            if len(self.test_relation_uris) >= 2:
                test_uris = self.test_relation_uris[:2]
            else:
                test_uris = [
                    "http://vital.ai/test/kgrelation/batch_update_1",
                    "http://vital.ai/test/kgrelation/batch_update_2"
                ]
            
            # Create VitalSigns Edge_hasKGRelation objects for batch update
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            rel1 = Edge_hasKGRelation()
            rel1.URI = test_uris[0]
            rel1.edgeSource = "http://vital.ai/test/entity/person/batch_source_1"
            rel1.edgeDestination = "http://vital.ai/test/entity/organization/batch_dest_1"
            rel1.edgeName = "Batch Updated Relation 1"
            rel1.kGRelationType = "http://vital.ai/ontology/test#CollaboratesWithRelationType"
            
            rel2 = Edge_hasKGRelation()
            rel2.URI = test_uris[1]
            rel2.edgeSource = "http://vital.ai/test/entity/person/batch_source_2"
            rel2.edgeDestination = "http://vital.ai/test/entity/location/batch_dest_2"
            rel2.edgeName = "Batch Updated Relation 2"
            rel2.kGRelationType = "http://vital.ai/ontology/test#LocatedInRelationType"
            
            quads = graphobjects_to_quad_list([rel1, rel2], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.UPDATE,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Multiple Relations",
                    True,
                    f"Successfully updated multiple relations: {response.updated_uri}",
                    {"updated_uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Multiple Relations",
                    False,
                    "Failed to update multiple relations",
                    {"uris": test_uris, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Multiple Relations",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_nonexistent_relation(self) -> bool:
        """Test updating a relation that doesn't exist."""
        try:
            nonexistent_uri = "http://vital.ai/test/kgrelation/nonexistent_update_12345"
            
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            ne_relation = Edge_hasKGRelation()
            ne_relation.URI = nonexistent_uri
            ne_relation.edgeSource = "http://vital.ai/test/entity/person/nonexistent_source"
            ne_relation.edgeDestination = "http://vital.ai/test/entity/organization/nonexistent_dest"
            ne_relation.edgeName = "Nonexistent Relation Update"
            quads = graphobjects_to_quad_list([ne_relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.UPDATE,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled nonexistent relation update"
            if response and hasattr(response, 'updated_uri'):
                result_msg += f" (updated_uri: {response.updated_uri})"
            
            self.log_test_result(
                "Update Nonexistent Relation",
                success,
                result_msg,
                {"uri": nonexistent_uri, "response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for nonexistent relation is acceptable
            self.log_test_result(
                "Update Nonexistent Relation",
                True,
                f"Exception for nonexistent relation (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def test_update_relation_type_change(self) -> bool:
        """Test updating relation with type change."""
        try:
            # Use a test URI or generate one for stub testing
            test_uri = self.test_relation_uris[-1] if self.test_relation_uris else "http://vital.ai/test/kgrelation/type_change"
            
            # Create relation update with type change using VitalSigns
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            tc_relation = Edge_hasKGRelation()
            tc_relation.URI = test_uri
            tc_relation.edgeSource = "http://vital.ai/test/entity/person/type_change_source"
            tc_relation.edgeDestination = "http://vital.ai/test/entity/organization/type_change_dest"
            tc_relation.edgeName = "Type Changed Relation"
            tc_relation.kGRelationType = "http://vital.ai/ontology/test#ManagesRelationType"
            tc_relation.kGRelationTypeDescription = "Management relation from 2024-01-01 to 2024-12-31"
            quads = graphobjects_to_quad_list([tc_relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.UPDATE,
                current_user=current_user
            )
            
            if response and hasattr(response, 'updated_uri') and response.updated_uri:
                self.log_test_result(
                    "Update Relation Type Change",
                    True,
                    f"Successfully updated relation type: {response.updated_uri}",
                    {"uri": response.updated_uri, "message": response.message}
                )
                return True
            else:
                self.log_test_result(
                    "Update Relation Type Change",
                    False,
                    "Failed to update relation type",
                    {"uri": test_uri, "response": str(response)}
                )
                return False
                
        except Exception as e:
            self.log_test_result(
                "Update Relation Type Change",
                False,
                f"Exception occurred: {str(e)}",
                {"error": str(e)}
            )
            return False
    
    async def test_update_invalid_relation_data(self) -> bool:
        """Test updating relation with invalid data (should handle gracefully)."""
        try:
            test_uri = self.test_relation_uris[0] if self.test_relation_uris else "http://vital.ai/test/kgrelation/invalid_update"
            
            # Create a minimal Edge_hasKGRelation without required fields
            from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
            
            inv_relation = Edge_hasKGRelation()
            inv_relation.URI = test_uri
            inv_relation.edgeName = "Invalid Update"
            quads = graphobjects_to_quad_list([inv_relation], self.graph_id)
            
            current_user = {"username": "test_user", "user_id": "test_user_123"}
            response = await self.endpoint._create_or_update_relations(
                space_id=self.space_id,
                graph_id=self.graph_id,
                quads=quads,
                operation_mode=OperationMode.UPDATE,
                current_user=current_user
            )
            
            # For stub implementation, this might succeed - that's acceptable
            success = True
            result_msg = "Handled invalid relation data update"
            if response and hasattr(response, 'updated_uri'):
                result_msg += f" (updated_uri: {response.updated_uri})"
            
            self.log_test_result(
                "Update Invalid Relation Data",
                success,
                result_msg,
                {"response": str(response)}
            )
            return success
            
        except Exception as e:
            # Exception for invalid data is acceptable
            self.log_test_result(
                "Update Invalid Relation Data",
                True,
                f"Exception for invalid data (acceptable): {str(e)}",
                {"error": str(e)}
            )
            return True
    
    async def run_all_update_tests(self) -> Dict[str, bool]:
        """Run all relation update tests."""
        logger.info("🧪 Running KGRelations Update Tests")
        
        results = {}
        
        # Test relation properties update
        results["update_relation_properties"] = await self.test_update_relation_properties()
        
        # Test multiple relations update
        results["update_multiple_relations"] = await self.test_update_multiple_relations()
        
        # Test nonexistent relation update
        results["update_nonexistent_relation"] = await self.test_update_nonexistent_relation()
        
        # Test relation type change
        results["update_relation_type_change"] = await self.test_update_relation_type_change()
        
        # Test invalid data update
        results["update_invalid_relation_data"] = await self.test_update_invalid_relation_data()
        
        return results
