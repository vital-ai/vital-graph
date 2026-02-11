#!/usr/bin/env python3
"""
KGType Get Test Case

Client-based test case for KGType retrieval operations using VitalGraph client.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class KGTypeGetTester:
    """Test case for KGType retrieval operations."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str, created_kgtypes: list = None) -> Dict[str, Any]:
        """
        Run KGType retrieval tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            created_kgtypes: List of created KGType URIs for testing
            
        Returns:
            Test results dictionary
        """
        logger.info("🔍 Testing KGType retrieval operations...")
        
        results = []
        
        # Test get existing KGType - use a separate list to avoid interference with delete tests
        if created_kgtypes:
            # Create a copy of the first 2 KGTypes for get testing
            test_kgtypes = created_kgtypes[:2].copy()
            for i, kgtype_uri in enumerate(test_kgtypes):
                get_result = await self._test_get_existing_kgtype(space_id, graph_id, kgtype_uri, i+1)
                results.append(get_result)
        
        # Test get non-existent KGType
        nonexistent_result = await self._test_get_nonexistent_kgtype(space_id, graph_id)
        results.append(nonexistent_result)
        
        # Test get with invalid URI
        invalid_result = await self._test_get_invalid_kgtype(space_id, graph_id)
        results.append(invalid_result)
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGType retrieval tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'name': 'KGType Retrieval Tests',
            'passed': passed_tests == len(results),
            'total_tests': len(results),
            'passed_tests': passed_tests,
            'results': results
        }
    
    async def _test_get_existing_kgtype(self, space_id: str, graph_id: str, kgtype_uri: str, index: int) -> Dict[str, Any]:
        """Test getting an existing KGType."""
        logger.info(f"  Testing get existing KGType: {kgtype_uri}")
        
        try:
            # Log the request details
            logger.info(f"    📤 REQUEST: GET KGType")
            logger.info(f"      - Space ID: {space_id}")
            logger.info(f"      - Graph ID: {graph_id}")
            logger.info(f"      - KGType URI: {kgtype_uri}")
            
            # Use get_kgtype to get specific KGType by URI
            response = await self.client.get_kgtype(space_id, graph_id, kgtype_uri)
            
            # Log the response details
            logger.info(f"    📥 RESPONSE: GET KGType")
            logger.info(f"      - Response type: {type(response).__name__}")
            logger.info(f"      - Has success attr: {hasattr(response, 'success')}")
            if hasattr(response, 'success'):
                logger.info(f"      - Success: {response.success}")
            logger.info(f"      - Has data attr: {hasattr(response, 'data')}")
            if hasattr(response, 'data'):
                logger.info(f"      - Data is None: {response.data is None}")
                if response.data:
                    logger.info(f"      - Data type: {type(response.data).__name__}")
                    if hasattr(response.data, 'graph'):
                        logger.info(f"      - Data has graph: {len(response.data.graph) if response.data.graph else 0} items")
            if hasattr(response, 'message'):
                logger.info(f"      - Message: {response.message}")
            
            if response.is_success:
                # Extract KGType data from response
                kgtype = response.type
                if kgtype:
                    retrieved_uri = kgtype.get('@id') or kgtype.get('URI') if isinstance(kgtype, dict) else str(kgtype)
                    return {
                        'name': f'Get Existing KGType #{index}',
                        'passed': True,
                        'details': f"Successfully retrieved KGType: {retrieved_uri}",
                        'kgtype_uri': kgtype_uri,
                        'retrieved_uri': retrieved_uri,
                        'kgtype_data': kgtype
                    }
                else:
                    return {
                        'name': f'Get Existing KGType #{index}',
                        'passed': False,
                        'error': f"KGType not found: {kgtype_uri}"
                    }
            else:
                return {
                    'name': f'Get Existing KGType #{index}',
                    'passed': False,
                    'error': response.error_message or f"Failed to get KGType: {kgtype_uri}"
                }
                
        except Exception as e:
            return {
                'name': f'Get Existing KGType #{index}',
                'passed': False,
                'error': f"Exception getting KGType {kgtype_uri}: {e}"
            }
    
    async def _test_get_nonexistent_kgtype(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test getting a non-existent KGType."""
        logger.info("  Testing get non-existent KGType...")
        
        nonexistent_uri = "http://vital.ai/test/kgtype/nonexistent_12345"
        
        try:
            response = await self.client.get_kgtype(space_id, graph_id, nonexistent_uri)
            
            # For non-existent KGTypes, we expect is_success to be False or type to be None
            if not response.is_success or response.type is None:
                return {
                    'name': 'Get Non-existent KGType',
                    'passed': True,
                    'details': f"Correctly returned empty result for non-existent KGType",
                    'nonexistent_uri': nonexistent_uri
                }
            else:
                return {
                    'name': 'Get Non-existent KGType',
                    'passed': False,
                    'error': f"Unexpectedly found data for non-existent KGType: {nonexistent_uri}"
                }
                
        except Exception as e:
            # Exception might be expected for non-existent KGTypes
            return {
                'name': 'Get Non-existent KGType',
                'passed': True,  # Exception is acceptable for non-existent resources
                'details': f"Exception for non-existent KGType (acceptable): {e}",
                'nonexistent_uri': nonexistent_uri
            }
    
    async def _test_get_invalid_kgtype(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test getting a KGType with invalid URI."""
        logger.info("  Testing get KGType with invalid URI...")
        
        invalid_uri = "invalid-uri-format"
        
        try:
            response = await self.client.get_kgtype(space_id, graph_id, invalid_uri)
            
            # For invalid URIs, we expect either no response or empty data
            if response and hasattr(response, 'data') and response.data:
                kgtypes_data = response.data.graph if hasattr(response.data, 'graph') else []
                
                if not kgtypes_data or len(kgtypes_data) == 0:
                    return {
                        'name': 'Get Invalid KGType URI',
                        'passed': True,
                        'details': f"Correctly handled invalid URI format",
                        'invalid_uri': invalid_uri
                    }
                else:
                    # Check if the returned data is actually for our invalid URI
                    found_uris = [item.get('@id') or item.get('URI') for item in kgtypes_data]
                    if invalid_uri in found_uris:
                        return {
                            'name': 'Get Invalid KGType URI',
                            'passed': False,
                            'error': f"Unexpectedly found data for invalid URI: {invalid_uri}",
                            'found_data': kgtypes_data
                        }
                    else:
                        # Data exists but not for our invalid URI - this is acceptable
                        return {
                            'name': 'Get Invalid KGType URI',
                            'passed': True,
                            'details': f"No data found for invalid URI (other data present)",
                            'invalid_uri': invalid_uri
                        }
            else:
                return {
                    'name': 'Get Invalid KGType URI',
                    'passed': True,  # Empty response is acceptable
                    'details': f"Empty response for invalid URI (acceptable)",
                    'invalid_uri': invalid_uri
                }
                
        except Exception as e:
            # Exception might be expected for invalid URIs
            return {
                'name': 'Get Invalid KGType URI',
                'passed': True,  # Exception is acceptable for invalid URIs
                'details': f"Exception for invalid URI (acceptable): {e}",
                'invalid_uri': invalid_uri
            }
