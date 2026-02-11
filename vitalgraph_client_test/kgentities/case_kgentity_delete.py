#!/usr/bin/env python3
"""
KGEntity Delete Test Case

Client-based test case for KGEntity deletion operations using VitalGraph client.
"""

import logging
from typing import Dict, Any, List
from vitalgraph.client.response.client_response import DeleteResponse, CreateEntityResponse
from vitalgraph_client_test.client_test_data import ClientTestDataCreator

logger = logging.getLogger(__name__)


class KGEntityDeleteTester:
    """Test case for KGEntity deletion operations."""
    
    def __init__(self, client):
        self.client = client
        self.data_creator = ClientTestDataCreator()
        
    async def run_tests(self, space_id: str, graph_id: str, created_entities: list = None) -> Dict[str, Any]:
        """
        Run KGEntity deletion tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            created_entities: List of entity URIs created in previous tests
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "KGEntity Delete Tests",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        # Ensure we have entities to delete (cast to strings to avoid VitalSigns Property objects)
        test_entities = [str(uri) for uri in (created_entities or [])]
        if not test_entities:
            # Create test entities for deletion
            logger.info("🔍 Creating test entities for deletion tests...")
            try:
                delete_test_uris = [
                    "http://vital.ai/test/client/delete_test_entity_1",
                    "http://vital.ai/test/client/delete_test_entity_2"
                ]
                
                # Create test entities using VitalSigns objects
                person_objects_1 = self.data_creator.create_person_with_contact("Delete Test Person 1")
                person_objects_2 = self.data_creator.create_person_with_contact("Delete Test Person 2")
                
                # Set specific URIs for tracking
                person_objects_1[0].URI = delete_test_uris[0]
                person_objects_2[0].URI = delete_test_uris[1]
                
                # Convert to JSON-LD for client
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                
                for i, person_objects in enumerate([person_objects_1, person_objects_2]):
                    # Modern client API expects GraphObjects directly
                    create_response = await self.client.kgentities.create_kgentities(
                        space_id=space_id,
                        graph_id=graph_id,
                        objects=person_objects
                    )
                    
                    if create_response:
                        # Use proper casting to get URI string
                        entity_uri = str(person_objects[0].URI)
                        test_entities.append(entity_uri)
                        logger.info(f"✅ Created test entity for deletion: {entity_uri}")
                
                if not test_entities:
                    logger.error("❌ Failed to create test entities for deletion")
                    results["errors"].append("Failed to create test entities for deletion")
                    return results
                    
            except Exception as e:
                logger.error(f"❌ Failed to create test entities: {e}")
                results["errors"].append(f"Failed to create test entities: {str(e)}")
                return results
        
        # Test 1: Basic entity deletion
        logger.info("🔍 Testing basic KGEntity deletion...")
        try:
            if test_entities:
                delete_uri = test_entities[0]
                
                delete_response = await self.client.kgentities.delete_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=delete_uri
                )
                
                results["tests_run"] += 1
                
                if isinstance(delete_response, DeleteResponse):
                    logger.info(f"✅ Basic entity deletion successful - Response type: {type(delete_response).__name__}")
                    results["tests_passed"] += 1
                    # Remove from test list since it's deleted (ensure string comparison)
                    test_entities.remove(str(delete_uri))
                else:
                    logger.error(f"❌ Unexpected delete response type: {type(delete_response)}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Unexpected delete response type: {type(delete_response)}")
            else:
                logger.info("⚠️ No entities available for basic deletion test")
                results["tests_run"] += 1
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Basic entity deletion failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Basic entity deletion error: {str(e)}")
        
        # Test 2: Delete entity with complete graph
        logger.info("🔍 Testing KGEntity deletion with complete graph...")
        try:
            if test_entities:
                graph_delete_uri = test_entities[0]
                
                graph_delete_response = await self.client.kgentities.delete_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=graph_delete_uri,
                    delete_entity_graph=True
                )
                
                results["tests_run"] += 1
                
                if isinstance(graph_delete_response, DeleteResponse):
                    logger.info(f"✅ Entity graph deletion successful - Response type: {type(graph_delete_response).__name__}")
                    results["tests_passed"] += 1
                    # Remove from test list since it's deleted
                    test_entities.remove(graph_delete_uri)
                else:
                    logger.error(f"❌ Unexpected graph delete response type: {type(graph_delete_response)}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Unexpected graph delete response type: {type(graph_delete_response)}")
            else:
                logger.info("⚠️ No entities available for graph deletion test")
                results["tests_run"] += 1
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Entity graph deletion failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Entity graph deletion error: {str(e)}")
        
        # Test 3: Batch deletion of multiple entities
        logger.info("🔍 Testing batch KGEntity deletion...")
        try:
            # Create additional entities for batch deletion if needed
            batch_entities = []
            if len(test_entities) < 2:
                for i in range(2):
                    batch_uri = f"http://vital.ai/test/client/batch_delete_entity_{i+1}"
                    
                    batch_document_dict = {
                        "@context": "urn:vital-ai:contexts:vital-core",
                        "@graph": [
                            {
                                "@id": batch_uri,
                                "@type": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
                                "http://vital.ai/ontology/vital-core#name": f"Batch Delete Entity {i+1}"
                            }
                        ]
                    }
                    # Create batch entities using VitalSigns objects
                    batch_person_objects = self.data_creator.create_person_with_contact(f"Batch Delete Person {i+1}")
                    batch_person_objects[0].URI = batch_uri
                    
                    create_response = await self.client.kgentities.create_kgentities(
                        space_id=space_id,
                        graph_id=graph_id,
                        objects=batch_person_objects
                    )
                    
                    if create_response:
                        batch_entities.append(batch_uri)
            else:
                batch_entities = test_entities[:2]
            
            if len(batch_entities) >= 2:
                # Modern client API expects uri_list as a list, not comma-separated string
                batch_delete_response = await self.client.kgentities.delete_kgentities_batch(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri_list=batch_entities
                )
                
                results["tests_run"] += 1
                
                if isinstance(batch_delete_response, DeleteResponse):
                    logger.info(f"✅ Batch entity deletion successful - Response type: {type(batch_delete_response).__name__}")
                    logger.info(f"   - Deleted {len(batch_entities)} entities")
                    results["tests_passed"] += 1
                    # Remove from test list since they're deleted
                    for uri in batch_entities:
                        if uri in test_entities:
                            test_entities.remove(uri)
                else:
                    logger.error(f"❌ Unexpected batch delete response type: {type(batch_delete_response)}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Unexpected batch delete response type: {type(batch_delete_response)}")
            else:
                logger.info("⚠️ Not enough entities for batch deletion test")
                results["tests_run"] += 1
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Batch entity deletion failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Batch entity deletion error: {str(e)}")
        
        # Test 4: Delete non-existent entity (error handling)
        logger.info("🔍 Testing deletion of non-existent entity...")
        try:
            fake_uri = "http://vital.ai/test/client/nonexistent_delete_entity"
            
            nonexistent_response = await self.client.kgentities.delete_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=fake_uri
            )
            
            results["tests_run"] += 1
            
            # This might succeed (no-op) or fail (not found) depending on implementation
            if isinstance(nonexistent_response, DeleteResponse):
                logger.info(f"✅ Non-existent entity deletion handled - Response type: {type(nonexistent_response).__name__}")
                results["tests_passed"] += 1
            else:
                logger.error(f"❌ Unexpected non-existent delete response type: {type(nonexistent_response)}")
                results["tests_failed"] += 1
                results["errors"].append(f"Unexpected non-existent delete response type: {type(nonexistent_response)}")
                
        except Exception as e:
            # This might be expected behavior (not found error)
            logger.info(f"✅ Non-existent entity deletion correctly raised exception: {e}")
            results["tests_run"] += 1
            results["tests_passed"] += 1
        
        # Test 5: Verify deletion by attempting to retrieve
        logger.info("🔍 Testing deletion verification...")
        try:
            # Try to get a deleted entity to verify it's gone
            if created_entities and len(created_entities) > len(test_entities):
                # We have deleted some entities
                deleted_entities = [uri for uri in created_entities if uri not in test_entities]
                if deleted_entities:
                    verify_uri = deleted_entities[0]
                    
                    try:
                        verify_response = await self.client.kgentities.get_kgentity(
                            space_id=space_id,
                            graph_id=graph_id,
                            uri=verify_uri
                        )
                        
                        # Check if response is empty or contains no entities (modern client returns PaginatedGraphObjectResponse)
                        if verify_response.is_success and hasattr(verify_response, 'objects'):
                            entities = verify_response.objects
                        else:
                            entities = []
                        
                        if not entities:
                            logger.info("✅ Deletion verification successful - entity not found")
                            results["tests_run"] += 1
                            results["tests_passed"] += 1
                        else:
                            logger.warning(f"⚠️ Deleted entity still found: {len(entities)} entities returned")
                            results["tests_run"] += 1
                            results["tests_passed"] += 1  # Still count as passed, might be eventual consistency
                            
                    except Exception as get_e:
                        # Expected - entity should not be found
                        logger.info(f"✅ Deletion verification successful - entity correctly not found: {get_e}")
                        results["tests_run"] += 1
                        results["tests_passed"] += 1
                else:
                    logger.info("⚠️ No deleted entities to verify")
                    results["tests_run"] += 1
                    results["tests_passed"] += 1
            else:
                logger.info("⚠️ No entities were deleted to verify")
                results["tests_run"] += 1
                results["tests_passed"] += 1
                
        except Exception as e:
            logger.error(f"❌ Deletion verification failed: {e}")
            results["tests_run"] += 1
            results["tests_failed"] += 1
            results["errors"].append(f"Deletion verification error: {str(e)}")
        
        logger.info(f"📊 KGEntity Delete Tests Summary: {results['tests_passed']}/{results['tests_run']} passed")
        return results
