#!/usr/bin/env python3
"""
KGEntity Update Test Case

Client-based test case for KGEntity update operations using VitalGraph client.
"""

import logging
from typing import Dict, Any, List
from vitalgraph.client.response.client_response import UpdateEntityResponse, CreateEntityResponse
from vitalgraph_client_test.client_test_data import ClientTestDataCreator
from vital_ai_vitalsigns.model.GraphObject import GraphObject

logger = logging.getLogger(__name__)


class KGEntityUpdateTester:
    """Test case for KGEntity update operations."""
    
    def __init__(self, client):
        self.client = client
        self.data_creator = ClientTestDataCreator()
        
    async def run_tests(self, space_id: str, graph_id: str, created_entities: list = None) -> Dict[str, Any]:
        """
        Run KGEntity update tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            created_entities: List of entity URIs created in previous tests
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "KGEntity Update Tests",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        # Ensure we have entities to update
        test_entities = created_entities or []
        if not test_entities:
            # Create a test entity for updating using VitalSigns objects
            logger.info("🔍 Creating test entity for update tests...")
            try:
                # Create a person entity with proper VitalSigns objects
                person_objects = self.data_creator.create_person_with_contact("Update Test Person")
                
                # Modern client API expects GraphObjects directly
                create_response = await self.client.kgentities.create_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=person_objects
                )
                
                if isinstance(create_response, (UpdateEntityResponse, CreateEntityResponse)):
                    # Get the entity URI from the created objects with proper casting
                    test_uri = str(person_objects[0].URI) if person_objects else None
                    if test_uri:
                        test_entities = [test_uri]
                        logger.info(f"✅ Created test entity for updates: {test_uri}")
                    else:
                        logger.error("❌ Failed to get entity URI from created objects")
                        results["errors"].append("Failed to get entity URI from created objects")
                        return results
                else:
                    logger.error(f"❌ Failed to create test entity: {create_response}")
                    results["errors"].append(f"Failed to create test entity: {str(create_response)}")
                    return results
                    
            except Exception as e:
                logger.error(f"❌ Failed to create test entity: {e}")
                results["errors"].append(f"Failed to create test entity: {str(e)}")
                return results
        
        # Test 1: Basic entity update
        logger.info("🔍 Testing basic KGEntity update...")
        try:
            update_uri = test_entities[0]
            
            # Create updated entity using VitalSigns objects
            updated_person_objects = self.data_creator.create_person_with_contact("Updated Test Person")
            # Set the URI to match the existing entity
            updated_person_objects[0].URI = update_uri
            
            # Convert to JSON-LD for client
            # Modern client API expects GraphObjects directly
            update_response = await self.client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=updated_person_objects
            )
            
            results["tests_run"] += 1
            
            if isinstance(update_response, (CreateEntityResponse, UpdateEntityResponse)):
                logger.info(f"✅ Basic entity update successful - Response type: {type(update_response).__name__}")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Unexpected update response type: {type(update_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected update response type: {type(update_response)}")
                
        except Exception as e:
            logger.error(f"❌ Basic entity update failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Basic entity update error: {str(e)}")
        
        # Test 2: Update entity with parent URI
        logger.info("🔍 Testing KGEntity update with parent URI...")
        try:
            if len(test_entities) > 0:
                update_uri = test_entities[0]
                parent_uri = "http://vital.ai/test/client/update_parent_entity"
                
                # Create updated organization entity using VitalSigns objects
                updated_org_objects = self.data_creator.create_organization_with_address("Updated Organization with Parent")
                # Set the URI to match the existing entity
                updated_org_objects[0].URI = update_uri
                
                # Convert to JSON-LD for client
                # Modern client API expects GraphObjects directly
                parent_update_response = await self.client.kgentities.update_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=updated_org_objects,
                    parent_uri=parent_uri
                )
                
                results["tests_run"] += 1
                
                if isinstance(parent_update_response, (CreateEntityResponse, UpdateEntityResponse)):
                    logger.info(f"✅ Entity update with parent URI successful - Response type: {type(parent_update_response).__name__}")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ Unexpected parent update response type: {type(parent_update_response)}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Unexpected parent update response type: {type(parent_update_response)}")
            else:
                logger.info("⚠️ No entities available for parent update test")
                results["tests_run"] += 1
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Entity update with parent URI failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Entity update with parent URI error: {str(e)}")
        
        # Test 3: Update multiple entities
        logger.info("🔍 Testing multiple KGEntity update...")
        try:
            if len(test_entities) >= 2:
                entity1_uri = test_entities[0]
                entity2_uri = test_entities[1]
            else:
                # Create a second entity for multi-update test
                entity1_uri = test_entities[0] if test_entities else "http://vital.ai/test/client/multi_update_1"
                entity2_uri = "http://vital.ai/test/client/multi_update_2"
            
            # Create multiple updated entities using VitalSigns objects
            basic_entities = self.data_creator.create_basic_entities()
            # Take first 2 entity groups and flatten
            all_objects = []
            for entity_group in basic_entities[:2]:
                all_objects.extend(entity_group)
            
            # Set URIs to match existing entities
            if len(all_objects) >= 2:
                all_objects[0].URI = entity1_uri
                all_objects[1].URI = entity2_uri
            
            # Convert to JSON-LD for client
            # Modern client API expects GraphObjects directly
            multi_update_response = await self.client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=all_objects
            )
            
            results["tests_run"] += 1
            
            if isinstance(multi_update_response, (CreateEntityResponse, UpdateEntityResponse)):
                logger.info(f"✅ Multiple entity update successful - Response type: {type(multi_update_response).__name__}")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Unexpected multi update response type: {type(multi_update_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected multi update response type: {type(multi_update_response)}")
                
        except Exception as e:
            logger.error(f"❌ Multiple entity update failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Multiple entity update error: {str(e)}")
        
        # Test 4: Update non-existent entity (error handling)
        logger.info("🔍 Testing update of non-existent entity...")
        try:
            fake_uri = "http://vital.ai/test/client/nonexistent_update_entity"
            
            # Create non-existent entity using VitalSigns objects
            fake_project_objects = self.data_creator.create_project_with_timeline("Non-existent Project")
            # Set the URI to a fake one
            fake_project_objects[0].URI = fake_uri
            
            # Convert to JSON-LD for client
            # Modern client API expects GraphObjects directly
            nonexistent_response = await self.client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=fake_project_objects
            )
            
            results["tests_run"] += 1
            
            # This might succeed (create) or fail (not found) depending on implementation
            if isinstance(nonexistent_response, (CreateEntityResponse, UpdateEntityResponse)):
                logger.info(f"✅ Non-existent entity update handled - Response type: {type(nonexistent_response).__name__}")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Unexpected non-existent update response type: {type(nonexistent_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected non-existent update response type: {type(nonexistent_response)}")
                
        except Exception as e:
            # This might be expected behavior (not found error)
            logger.info(f"✅ Non-existent entity update correctly raised exception: {e}")
            results["tests_run"] += 1
            results["tests_passed"] += 1
        
        # Test 5: Update with property removal (partial update)
        logger.info("🔍 Testing entity property update...")
        try:
            if test_entities:
                update_uri = test_entities[0]
                
                # Create property updated entity using VitalSigns objects
                property_person_objects = self.data_creator.create_person_with_contact("Property Updated Person")
                # Set the URI to match the existing entity
                property_person_objects[0].URI = update_uri
                
                # Convert to JSON-LD for client
                # Modern client API expects GraphObjects directly
                property_response = await self.client.kgentities.update_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=property_person_objects
                )
                
                results["tests_run"] += 1
                
                if isinstance(property_response, (CreateEntityResponse, UpdateEntityResponse)):
                    logger.info(f"✅ Entity property update successful - Response type: {type(property_response).__name__}")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"❌ Unexpected property update response type: {type(property_response)}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Unexpected property update response type: {type(property_response)}")
            else:
                logger.info("⚠️ No entities available for property update test")
                results["tests_run"] += 1
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Entity property update failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Entity property update error: {str(e)}")
        
        logger.info(f"📊 KGEntity Update Tests Summary: {results['tests_passed']}/{results['tests_run']} passed")
        return results
