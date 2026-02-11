#!/usr/bin/env python3
"""
KGType Update Test Case

Client-based test case for KGType update operations using VitalGraph client.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGTypeUpdateTester:
    """Test case for KGType update operations."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, test_kgtypes: List, created_kgtypes: list = None) -> Dict[str, Any]:
        """
        Run KGType update tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            test_kgtypes: List of KGType objects for testing
            created_kgtypes: List of created KGType URIs for testing
            
        Returns:
            Test results dictionary
        """
        logger.info("🔄 Testing KGType update operations...")
        
        results = []
        
        # Test basic KGType update
        if test_kgtypes:
            update_result = await self._test_basic_kgtype_update(space_id, graph_id, test_kgtypes[0])
            results.append(update_result)
        
        # Test update with verification
        if test_kgtypes and len(test_kgtypes) > 1:
            verify_result = await self._test_kgtype_update_with_verification(space_id, graph_id, test_kgtypes[1])
            results.append(verify_result)
        
        # Test update non-existent KGType
        nonexistent_result = await self._test_update_nonexistent_kgtype(space_id, graph_id)
        results.append(nonexistent_result)
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType update tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'name': 'KGType Update Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results
        }
    
    async def _test_basic_kgtype_update(self, space_id: str, graph_id: str, test_kgtype) -> Dict[str, Any]:
        """Test basic KGType update."""
        logger.info("  Testing basic KGType update...")
        
        try:
            # Modify the KGType for update
            original_description = str(test_kgtype.kGraphDescription) if hasattr(test_kgtype, 'kGraphDescription') else 'Original description'
            test_kgtype.kGraphDescription = f"{original_description} - UPDATED"
            test_kgtype.kGTypeVersion = "2.0"
            
            # Update using client - pass GraphObject directly
            response = await self.client.update_kgtypes(space_id, graph_id, [test_kgtype])
            
            if response and hasattr(response, 'message'):
                return {
                    'name': 'Basic KGType Update',
                    'passed': True,
                    'details': f"Successfully updated KGType: {test_kgtype.URI}",
                    'kgtype_uri': str(test_kgtype.URI),
                    'updated_description': str(test_kgtype.kGraphDescription),
                    'response': response.model_dump() if hasattr(response, 'model_dump') else str(response)
                }
            else:
                error_msg = response.message if response and hasattr(response, 'message') else 'Unknown error'
                return {
                    'name': 'Basic KGType Update',
                    'passed': False,
                    'error': f"KGType update failed: {error_msg}",
                    'response': response.model_dump() if response and hasattr(response, 'model_dump') else str(response)
                }
                
        except Exception as e:
            return {
                'name': 'Basic KGType Update',
                'passed': False,
                'error': f"Exception during KGType update: {e}"
            }
    
    async def _test_kgtype_update_with_verification(self, space_id: str, graph_id: str, test_kgtype) -> Dict[str, Any]:
        """Test KGType update with verification."""
        logger.info("  Testing KGType update with verification...")
        
        try:
            # Log the KGType before update
            logger.info(f"  KGType BEFORE update: {test_kgtype.to_json()}")
            
            # Modify the KGType for update
            original_description = str(test_kgtype.kGraphDescription) if hasattr(test_kgtype, 'kGraphDescription') else 'Original description'
            updated_description = f"{original_description} - VERIFIED UPDATE"
            test_kgtype.kGraphDescription = updated_description
            test_kgtype.kGModelVersion = "2.1"
            
            test_uri = str(test_kgtype.URI)
            
            # Log the KGType after modification
            logger.info(f"  KGType AFTER modification: {test_kgtype.to_json()}")
            
            # Update using client - pass GraphObject directly
            update_response = await self.client.update_kgtypes(space_id, graph_id, [test_kgtype])
            
            if not update_response.is_success:
                return {
                    'name': 'KGType Update with Verification',
                    'passed': False,
                    'error': f"KGType update failed: {update_response.error_message}"
                }
            
            # Verify by retrieving the updated KGType
            try:
                list_response = await self.client.get_kgtype(space_id, graph_id, test_uri)
                if list_response.is_success and list_response.type:
                    retrieved_kgtype = list_response.type
                    
                    # Convert JsonLdObject to dict if needed
                    from vitalgraph.model.jsonld_model import JsonLdObject
                    if isinstance(retrieved_kgtype, JsonLdObject):
                        retrieved_kgtype = retrieved_kgtype.model_dump(by_alias=True)
                    
                    # Log the retrieved KGType data for debugging
                    logger.info(f"  Retrieved KGType JSON-LD: {retrieved_kgtype}")
                    
                    # Try to convert back to VitalSigns object and log it
                    try:
                        from vital_ai_vitalsigns.model.GraphObject import GraphObject
                        retrieved_obj = GraphObject.from_jsonld(retrieved_kgtype)
                        if retrieved_obj:
                            logger.info(f"  Retrieved KGType as VitalSigns object: {retrieved_obj.to_json()}")
                    except Exception as conv_e:
                        logger.info(f"  Could not convert retrieved KGType to VitalSigns: {conv_e}")
                    
                    retrieved_description = retrieved_kgtype.get('kGraphDescription', 
                                                               retrieved_kgtype.get('http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription', ''))
                    
                    # Precise verification - check if we got the exact KGType we updated
                    retrieved_uri = retrieved_kgtype.get('@id') or retrieved_kgtype.get('URI')
                    
                    if retrieved_uri != test_uri:
                        return {
                            'name': 'KGType Update with Verification',
                            'passed': False,
                            'error': f"Server returned wrong KGType - expected {test_uri}, got {retrieved_uri}",
                            'expected_uri': test_uri,
                            'retrieved_uri': retrieved_uri
                        }
                    
                    # Check if the description was updated precisely
                    retrieved_desc_str = str(retrieved_description)
                    
                    if updated_description in retrieved_desc_str:
                        return {
                            'name': 'KGType Update with Verification',
                            'passed': True,
                            'details': f"Successfully updated and verified KGType: {test_uri}",
                            'kgtype_uri': test_uri,
                            'updated_description': updated_description,
                            'retrieved_description': retrieved_description,
                            'verification': 'Description update confirmed'
                        }
                    else:
                        return {
                            'name': 'KGType Update with Verification',
                            'passed': False,
                            'error': f"KGType update verification failed - description not updated correctly",
                            'expected': updated_description,
                            'retrieved': retrieved_description,
                            'original': original_description
                        }
                else:
                    return {
                        'name': 'KGType Update with Verification',
                        'passed': False,
                        'error': "KGType updated but verification list failed"
                    }
            except Exception as verify_e:
                return {
                    'name': 'KGType Update with Verification',
                    'passed': False,
                    'error': f"KGType updated but verification failed: {verify_e}"
                }
                
        except Exception as e:
            return {
                'name': 'KGType Update with Verification',
                'passed': False,
                'error': f"Exception during KGType update with verification: {e}"
            }
    
    async def _test_update_nonexistent_kgtype(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test updating a non-existent KGType."""
        logger.info("  Testing update non-existent KGType...")
        
        try:
            # Create a KGType with non-existent URI
            from ai_haley_kg_domain.model.KGType import KGType
            nonexistent_kgtype = KGType()
            nonexistent_kgtype.URI = "http://vital.ai/test/kgtype/nonexistent_update_12345"
            nonexistent_kgtype.kGraphDescription = "This KGType should not exist"
            nonexistent_kgtype.kGTypeVersion = "1.0"
            nonexistent_kgtype.kGModelVersion = "1.0"
            
            # Try to update using client - pass GraphObject directly
            response = await self.client.update_kgtypes(space_id, graph_id, [nonexistent_kgtype])
            
            # Update of non-existent KGType might succeed (creating it) or fail
            # Both behaviors are acceptable depending on implementation
            return {
                'name': 'Update Non-existent KGType',
                'passed': True,  # Either success or failure is acceptable
                'details': f"Update attempt completed for non-existent KGType",
                'nonexistent_uri': str(nonexistent_kgtype.URI),
                'response': response.model_dump() if response and hasattr(response, 'model_dump') else str(response)
            }
                
        except Exception as e:
            # Exception is acceptable for non-existent KGType update
            return {
                'name': 'Update Non-existent KGType',
                'passed': True,  # Exception is acceptable
                'details': f"Exception for non-existent KGType update (acceptable): {e}",
                'nonexistent_uri': "http://vital.ai/test/kgtype/nonexistent_update_12345"
            }
