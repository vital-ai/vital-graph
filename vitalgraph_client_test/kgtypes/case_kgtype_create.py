#!/usr/bin/env python3
"""
KGType Creation Test Case

Client-based test case for KGType creation operations using VitalGraph client.
"""

import logging
import uuid
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class KGTypeCreateTester:
    """Test case for KGType creation operations."""
    
    def __init__(self, client):
        self.client = client
        
    def run_tests(self, space_id: str, graph_id: str, test_kgtypes: List) -> Dict[str, Any]:
        """
        Run KGType creation tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier  
            test_kgtypes: List of KGType objects to create
            
        Returns:
            Test results dictionary
        """
        logger.info("🔧 Testing KGType creation operations...")
        
        results = []
        
        # Test basic KGType creation
        basic_result = self._test_basic_kgtype_creation(space_id, graph_id, test_kgtypes)
        results.append(basic_result)
        
        # Test batch KGType creation
        batch_result = self._test_batch_kgtype_creation(space_id, graph_id, test_kgtypes)
        results.append(batch_result)
        
        # Skip verification test since all KGTypes are now created in batch test
        # verify_result = self._test_kgtype_creation_with_verification(space_id, graph_id, test_kgtypes)
        # results.append(verify_result)
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType creation tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'name': 'KGType Creation Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results
        }
    
    def _test_basic_kgtype_creation(self, space_id: str, graph_id: str, test_kgtypes: List) -> Dict[str, Any]:
        """Test basic KGType creation."""
        logger.info("  Testing basic KGType creation...")
        
        try:
            # Log the request details
            logger.info(f"    📤 REQUEST: CREATE KGTypes")
            logger.info(f"      - Space ID: {space_id}")
            logger.info(f"      - Graph ID: {graph_id}")
            logger.info(f"      - KGTypes count: {len(test_kgtypes)}")
            for i, kgtype in enumerate(test_kgtypes[:3]):  # Log first 3 for brevity
                logger.info(f"      - KGType {i+1}: {str(kgtype.URI)} ({type(kgtype).__name__})")
            if len(test_kgtypes) > 3:
                logger.info(f"      - ... and {len(test_kgtypes) - 3} more KGTypes")
            
            # Use first test KGType for basic creation
            if not test_kgtypes:
                return {
                    'name': 'Basic KGType Creation',
                    'passed': False,
                    'error': 'No test KGTypes provided'
                }
            
            # Create using client - pass GraphObject directly
            response = self.client.create_kgtypes(space_id, graph_id, [test_kgtypes[0]])
            
            # Log the response details
            logger.info(f"    📥 RESPONSE: CREATE KGTypes")
            logger.info(f"      - Response type: {type(response).__name__}")
            logger.info(f"      - Has success attr: {hasattr(response, 'success')}")
            if hasattr(response, 'success'):
                logger.info(f"      - Success: {response.success}")
            logger.info(f"      - Has created_count attr: {hasattr(response, 'created_count')}")
            if hasattr(response, 'created_count'):
                logger.info(f"      - Created count: {response.created_count}")
            if hasattr(response, 'message'):
                logger.info(f"      - Message: {response.message}")
            if hasattr(response, 'created_uris'):
                logger.info(f"      - Created URIs count: {len(response.created_uris) if response.created_uris else 0}")
                if response.created_uris:
                    for i, uri in enumerate(response.created_uris[:3]):  # Log first 3
                        logger.info(f"        - URI {i+1}: {uri}")
                    if len(response.created_uris) > 3:
                        logger.info(f"        - ... and {len(response.created_uris) - 3} more URIs")
            
            if response.is_success:
                return {
                    'name': 'Basic KGType Creation',
                    'passed': True,
                    'details': f"Successfully created {response.created_count} KGType(s)",
                    'created_count': response.created_count,
                    'response': response.model_dump() if hasattr(response, 'model_dump') else str(response)
                }
            else:
                error_msg = response.error_message or 'Unknown error'
                return {
                    'name': 'Basic KGType Creation',
                    'passed': False,
                    'error': f"KGType creation failed: {error_msg}",
                    'response': response.model_dump() if response and hasattr(response, 'model_dump') else str(response)
                }
                
        except Exception as e:
            return {
                'name': 'Basic KGType Creation',
                'passed': False,
                'error': f"Exception during KGType creation: {e}"
            }
    
    def _test_batch_kgtype_creation(self, space_id: str, graph_id: str, test_kgtypes: List) -> Dict[str, Any]:
        """Test batch KGType creation."""
        logger.info("  Testing batch KGType creation...")
        
        try:
            if len(test_kgtypes) < 2:
                return {
                    'name': 'Batch KGType Creation',
                    'passed': False,
                    'error': 'Need at least 2 test KGTypes for batch creation'
                }
            
            # Use ALL remaining test KGTypes for batch creation to ensure all 20 are created
            batch_kgtypes = test_kgtypes[1:]  # Use all KGTypes except the first one (already created in basic test)
            
            # Create using client - pass GraphObjects directly
            response = self.client.create_kgtypes(space_id, graph_id, batch_kgtypes)
            
            if response.is_success and response.created_count >= len(batch_kgtypes):
                return {
                    'name': 'Batch KGType Creation',
                    'passed': True,
                    'details': f"Successfully created {response.created_count} KGTypes in batch",
                    'created_count': response.created_count,
                    'expected_count': len(batch_kgtypes),
                    'response': response.model_dump() if hasattr(response, 'model_dump') else str(response)
                }
            else:
                error_msg = response.error_message or 'Unknown error'
                return {
                    'name': 'Batch KGType Creation',
                    'passed': False,
                    'error': f"Batch KGType creation failed: {error_msg}",
                    'response': response.model_dump() if response and hasattr(response, 'model_dump') else str(response)
                }
                
        except Exception as e:
            return {
                'name': 'Batch KGType Creation',
                'passed': False,
                'error': f"Exception during batch KGType creation: {e}"
            }
    
    def _test_kgtype_creation_with_verification(self, space_id: str, graph_id: str, test_kgtypes: List) -> Dict[str, Any]:
        """Test KGType creation with verification."""
        logger.info("  Testing KGType creation with verification...")
        
        try:
            if not test_kgtypes:
                return {
                    'name': 'KGType Creation with Verification',
                    'passed': False,
                    'error': 'No test KGTypes provided'
                }
            
            # Create a unique KGType for verification
            test_kgtype = test_kgtypes[-1]  # Use last KGType
            test_uri = str(test_kgtype.URI)
            
            # Convert to JSON-LD using VitalSigns
            jsonld_data = test_kgtype.to_jsonld()
            
            # Create using client - use JsonLdObject for single KGType
            from vitalgraph.model.jsonld_model import JsonLdObject
            jsonld_obj = JsonLdObject(**jsonld_data)
            create_response = self.client.create_kgtypes(space_id, graph_id, jsonld_obj)
            
            if not create_response or not (hasattr(create_response, 'created_count') and create_response.created_count > 0):
                error_msg = create_response.message if create_response and hasattr(create_response, 'message') else 'Unknown error'
                return {
                    'name': 'KGType Creation with Verification',
                    'passed': False,
                    'error': f"KGType creation failed: {error_msg}"
                }
            
            # Verify by listing KGTypes and checking if our KGType exists
            try:
                list_response = self.client.list_kgtypes(space_id, graph_id, page_size=100)
                if list_response and hasattr(list_response, 'data') and list_response.data:
                    # Handle both JsonLdObject (single) and JsonLdDocument (multiple)
                    from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
                    if isinstance(list_response.data, JsonLdObject):
                        kgtypes_data = [list_response.data]
                    elif isinstance(list_response.data, JsonLdDocument):
                        kgtypes_data = list_response.data.graph if list_response.data.graph else []
                    else:
                        kgtypes_data = []
                    
                    # Check if our KGType URI is in the response
                    found_kgtype = any(
                        kgtype.get('@id') == test_uri or kgtype.get('URI') == test_uri 
                        for kgtype in kgtypes_data
                    )
                    
                    if found_kgtype:
                        return {
                            'name': 'KGType Creation with Verification',
                            'passed': True,
                            'details': f"Successfully created and verified KGType: {test_uri}",
                            'kgtype_uri': test_uri,
                            'verification': 'Found in list response'
                        }
                    else:
                        return {
                            'name': 'KGType Creation with Verification',
                            'passed': False,
                            'error': f"KGType created but not found in list: {test_uri}"
                        }
                else:
                    return {
                        'name': 'KGType Creation with Verification',
                        'passed': False,
                        'error': "KGType created but verification list failed"
                    }
            except Exception as verify_e:
                return {
                    'name': 'KGType Creation with Verification',
                    'passed': False,
                    'error': f"KGType created but verification failed: {verify_e}"
                }
                
        except Exception as e:
            return {
                'name': 'KGType Creation with Verification',
                'passed': False,
                'error': f"Exception during KGType creation with verification: {e}"
            }
