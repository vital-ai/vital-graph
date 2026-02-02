#!/usr/bin/env python3
"""
Reference ID Operations Test Case

Tests retrieving entities by reference ID (single and multiple).
"""

import logging
from typing import Dict, Any, List
from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


class ReferenceIdOperationsTester:
    """Test case for reference ID operations."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, entity_uris: List[str], 
                  entity_names: List[str], reference_ids: List[str]) -> Dict[str, Any]:
        """
        Run reference ID retrieval tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uris: List of entity URIs (for verification)
            entity_names: List of entity names (for display)
            reference_ids: List of reference IDs assigned to entities
            
        Returns:
            Dict containing test results
        """
        results = {
            "test_name": "Reference ID Operations",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": []
        }
        
        logger.info("=" * 80)
        logger.info("  Reference ID Operations")
        logger.info("=" * 80)
        
        # Test 1: Get single entity by reference ID
        results["tests_run"] += 1
        try:
            logger.info(f"\nTest 1: Get entity by single reference ID...")
            ref_id = reference_ids[0]
            expected_name = entity_names[0]
            
            logger.info(f"   Getting entity with reference ID: {ref_id}")
            
            response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                reference_id=ref_id,
                include_entity_graph=False
            )
            
            # Verify response - direct GraphObject access
            entity_retrieved = False
            retrieved_name = None
            
            if response.is_success and response.objects:
                # Find the KGEntity in the response objects
                for obj in response.objects:
                    if isinstance(obj, KGEntity):
                        entity_retrieved = True
                        retrieved_name = str(obj.name) if obj.name else 'Unknown'
                        break
            
            if entity_retrieved and retrieved_name == expected_name:
                logger.info(f"   ✅ Retrieved entity: {retrieved_name}")
                logger.info(f"✅ PASS: Get entity by reference ID")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Failed: Expected '{expected_name}', got '{retrieved_name}'")
                logger.error(f"❌ FAIL: Get entity by reference ID")
                results["tests_failed"] += 1
                results["errors"].append(f"Get by reference ID failed: expected {expected_name}")
                
        except Exception as e:
            logger.error(f"   ❌ Error: {e}")
            logger.error(f"❌ FAIL: Get entity by reference ID")
            results["tests_failed"] += 1
            results["errors"].append(f"Error getting by reference ID: {str(e)}")
        
        # Test 2: Get multiple entities by reference ID list
        results["tests_run"] += 1
        try:
            logger.info(f"\nTest 2: Get entities by reference ID list...")
            ref_ids = reference_ids[:3]  # First 3 reference IDs
            expected_names = set(entity_names[:3])
            
            logger.info(f"   Getting entities with reference IDs: {ref_ids}")
            
            response = self.client.kgentities.get_kgentities_by_reference_ids(
                space_id=space_id,
                graph_id=graph_id,
                reference_ids=ref_ids,
                include_entity_graph=False
            )
            
            # Verify response - direct GraphObject access
            retrieved_names = set()
            
            if response.is_success and response.objects:
                for obj in response.objects:
                    if isinstance(obj, KGEntity) and obj.name:
                        retrieved_names.add(str(obj.name))
            
            if retrieved_names == expected_names:
                logger.info(f"   ✅ Retrieved {len(retrieved_names)} entities: {retrieved_names}")
                logger.info(f"✅ PASS: Get entities by reference ID list")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Failed: Expected {expected_names}, got {retrieved_names}")
                logger.error(f"❌ FAIL: Get entities by reference ID list")
                results["tests_failed"] += 1
                results["errors"].append(f"Get by reference ID list failed: mismatch in retrieved entities")
                
        except Exception as e:
            logger.error(f"   ❌ Error: {e}")
            logger.error(f"❌ FAIL: Get entities by reference ID list")
            results["tests_failed"] += 1
            results["errors"].append(f"Error getting by reference ID list: {str(e)}")
        
        # Test 3: Get entity with entity graph by reference ID
        results["tests_run"] += 1
        try:
            logger.info(f"\nTest 3: Get entity with complete graph by reference ID...")
            ref_id = reference_ids[1]
            expected_name = entity_names[1]
            
            logger.info(f"   Getting entity graph with reference ID: {ref_id}")
            
            response = self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                reference_id=ref_id,
                include_entity_graph=True
            )
            
            # Verify response includes entity and frames/slots - direct access via EntityGraph
            entity_found = False
            has_frames = False
            retrieved_name = None
            object_count = 0
            
            if response.is_success and response.objects:
                entity_graph = response.objects  # EntityGraph container
                object_count = entity_graph.count
                for obj in entity_graph.objects:
                    if isinstance(obj, KGEntity):
                        entity_found = True
                        retrieved_name = str(obj.name) if obj.name else 'Unknown'
                    elif hasattr(obj, '__class__') and 'KGFrame' in obj.__class__.__name__:
                        has_frames = True
            
            if entity_found and retrieved_name == expected_name and has_frames and object_count > 1:
                logger.info(f"   ✅ Retrieved entity graph: {retrieved_name} ({object_count} objects)")
                logger.info(f"✅ PASS: Get entity graph by reference ID")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Failed: entity={entity_found}, name={retrieved_name}, frames={has_frames}, objects={object_count}")
                logger.error(f"❌ FAIL: Get entity graph by reference ID")
                results["tests_failed"] += 1
                results["errors"].append(f"Get entity graph by reference ID incomplete")
                
        except Exception as e:
            logger.error(f"   ❌ Error: {e}")
            logger.error(f"❌ FAIL: Get entity graph by reference ID")
            results["tests_failed"] += 1
            results["errors"].append(f"Error getting entity graph by reference ID: {str(e)}")
        
        # Test 4: Verify mutual exclusivity (cannot use both URI and reference ID)
        results["tests_run"] += 1
        try:
            logger.info(f"\nTest 4: Verify mutual exclusivity of URI and reference ID...")
            
            # This should raise an error
            error_raised = False
            try:
                self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    uri=entity_uris[0],
                    reference_id=reference_ids[0],
                    include_entity_graph=False
                )
            except Exception as e:
                error_raised = True
                error_message = str(e)
            
            if error_raised and ("both" in error_message.lower() or "mutually exclusive" in error_message.lower()):
                logger.info(f"   ✅ Correctly rejected request with both URI and reference ID")
                logger.info(f"✅ PASS: Mutual exclusivity validation")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Failed: Should have raised error for both URI and reference ID")
                logger.error(f"❌ FAIL: Mutual exclusivity validation")
                results["tests_failed"] += 1
                results["errors"].append(f"Mutual exclusivity not enforced")
                
        except Exception as e:
            logger.error(f"   ❌ Unexpected error: {e}")
            logger.error(f"❌ FAIL: Mutual exclusivity validation")
            results["tests_failed"] += 1
            results["errors"].append(f"Unexpected error in mutual exclusivity test: {str(e)}")
        
        # Test 5: Verify error handling for non-existent reference ID
        results["tests_run"] += 1
        try:
            logger.info(f"\nTest 5: Verify error handling for non-existent reference ID...")
            
            non_existent_ref_id = "REF-NONEXISTENT-999"
            logger.info(f"   Attempting to get entity with non-existent reference ID: {non_existent_ref_id}")
            
            # This should return empty or raise an error
            error_or_empty = False
            try:
                get_response = self.client.kgentities.get_kgentity(
                    space_id=space_id,
                    graph_id=graph_id,
                    reference_id=non_existent_ref_id,
                    include_entity_graph=False
                )
                
                # Check if response is empty - response.objects contains GraphObjects
                if get_response is None or not get_response.is_success:
                    error_or_empty = True
                elif not hasattr(get_response, 'objects') or not get_response.objects or len(get_response.objects) == 0:
                    error_or_empty = True
                    
            except Exception as e:
                # Error is acceptable for non-existent reference ID
                error_or_empty = True
                logger.info(f"   Raised error (acceptable): {e}")
            
            if error_or_empty:
                logger.info(f"   ✅ Correctly handled non-existent reference ID")
                logger.info(f"✅ PASS: Non-existent reference ID handling")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ Failed: Should have returned empty or raised error")
                logger.error(f"❌ FAIL: Non-existent reference ID handling")
                results["tests_failed"] += 1
                results["errors"].append(f"Non-existent reference ID not handled correctly")
                
        except Exception as e:
            logger.error(f"   ❌ Unexpected error: {e}")
            logger.error(f"❌ FAIL: Non-existent reference ID handling")
            results["tests_failed"] += 1
            results["errors"].append(f"Unexpected error in non-existent reference ID test: {str(e)}")
        
        return results
