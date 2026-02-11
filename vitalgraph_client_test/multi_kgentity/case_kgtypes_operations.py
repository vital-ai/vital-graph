#!/usr/bin/env python3
"""
KGTypes Operations Test Case

Test case for creating and listing KGTypes used in entity graph data,
including entity types, frame types, and slot types.
"""

import logging
from typing import Dict, Any, List

from ai_haley_kg_domain.model.KGType import KGType
from vital_ai_vitalsigns.model.GraphObject import GraphObject

logger = logging.getLogger(__name__)


class KGTypesOperationsTester:
    """Test case for KGTypes operations before entity graph creation."""
    
    def __init__(self, client):
        self.client = client
        
    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run KGTypes operations tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            
        Returns:
            Test results dictionary
        """
        logger.info("📋 Testing KGTypes operations...")
        
        results = []
        errors = []
        
        # Define KGTypes for entity types, frame types, and slot types
        kgtypes_to_create = self._create_test_kgtypes()
        
        # Test 1: Create KGTypes
        create_result = await self._test_create_kgtypes(space_id, graph_id, kgtypes_to_create)
        results.append(create_result)
        if not create_result['passed']:
            errors.append(create_result.get('error', 'KGType creation failed'))
        
        # Test 2: List all KGTypes
        list_result = await self._test_list_kgtypes(space_id, graph_id, expected_count=len(kgtypes_to_create))
        results.append(list_result)
        if not list_result['passed']:
            errors.append(list_result.get('error', 'KGType listing failed'))
        
        # Test 3: Verify specific KGTypes exist
        verify_result = await self._test_verify_kgtypes(space_id, graph_id, kgtypes_to_create)
        results.append(verify_result)
        if not verify_result['passed']:
            errors.append(verify_result.get('error', 'KGType verification failed'))
        
        passed_tests = sum(1 for r in results if r['passed'])
        logger.info(f"✅ KGTypes operations tests completed: {passed_tests}/{len(results)} passed")
        
        return {
            'test_name': 'KGTypes Operations',
            'tests_run': len(results),
            'tests_passed': passed_tests,
            'tests_failed': len(results) - passed_tests,
            'errors': errors,
            'results': results
        }
    
    def _create_test_kgtypes(self) -> List[KGType]:
        """Create test KGTypes for entity types, frame types, and slot types."""
        from ai_haley_kg_domain.model.KGEntityType import KGEntityType
        from ai_haley_kg_domain.model.KGFrameType import KGFrameType
        from ai_haley_kg_domain.model.KGSlotType import KGSlotType
        import uuid
        
        kgtypes = []
        
        # Define KGType definitions: (name, description, version, model_version, class)
        kgtype_definitions = [
            # Entity Types (for KGEntity objects)
            ("OrganizationEntity", "Entity type for organization entities", "1.0", "2024.1", KGEntityType),
            ("BusinessEventEntity", "Entity type for business event entities", "1.0", "2024.1", KGEntityType),
            
            # Frame Types (for KGFrame objects)
            ("AddressFrame", "Frame type for address information", "1.0", "2024.1", KGFrameType),
            ("ContactFrame", "Frame type for contact information", "1.0", "2024.1", KGFrameType),
            ("BusinessContractFrame", "Frame type for business contract documents", "1.0", "2024.1", KGFrameType),
            ("FinancialDocumentFrame", "Frame type for financial documents and reports", "1.0", "2024.1", KGFrameType),
            ("MarketingMaterialFrame", "Frame type for marketing materials and collateral", "1.0", "2024.1", KGFrameType),
            ("TechnicalDocumentFrame", "Frame type for technical specifications and documentation", "1.0", "2024.1", KGFrameType),
            ("LegalDocumentFrame", "Frame type for legal documents and agreements", "1.0", "2024.1", KGFrameType),
            
            # Slot Types (for KGSlot objects)
            ("EmailSlot", "Slot type for email properties", "1.0", "2024.1", KGSlotType),
            ("PhoneSlot", "Slot type for phone properties", "1.0", "2024.1", KGSlotType),
            ("DocumentFileURISlot", "Slot type for document file URI reference", "1.0", "2024.1", KGSlotType),
            ("DocumentTypeSlot", "Slot type for document type/category", "1.0", "2024.1", KGSlotType),
            ("DocumentDateSlot", "Slot type for document date", "1.0", "2024.1", KGSlotType),
            ("DocumentTitleSlot", "Slot type for document title", "1.0", "2024.1", KGSlotType),
        ]
        
        # Create KGType objects with appropriate subclasses
        for name, description, version, model_version, kgtype_class in kgtype_definitions:
            kgtype = kgtype_class()
            kgtype.URI = f"http://vital.ai/test/kgtype/{name}_{uuid.uuid4().hex[:8]}"
            kgtype.name = name
            kgtype.kGraphDescription = description
            kgtype.kGTypeVersion = version
            kgtype.kGModelVersion = model_version
            kgtypes.append(kgtype)
        
        return kgtypes
    
    async def _test_create_kgtypes(self, space_id: str, graph_id: str, kgtypes: List[KGType]) -> Dict[str, Any]:
        """Test creating KGTypes."""
        logger.info(f"  Testing create {len(kgtypes)} KGTypes...")
        
        try:
            # Create using client - pass GraphObjects directly
            response = await self.client.kgtypes.create_kgtypes(space_id, graph_id, kgtypes)
            
            if response.is_success:
                logger.info(f"    ✅ Created {response.created_count} KGTypes")
                return {
                    'name': 'Create KGTypes',
                    'passed': True,
                    'details': f"Successfully created {response.created_count} KGTypes",
                    'created_count': response.created_count
                }
            else:
                return {
                    'name': 'Create KGTypes',
                    'passed': False,
                    'error': f"KGType creation failed: {response.error_message}"
                }
                
        except Exception as e:
            return {
                'name': 'Create KGTypes',
                'passed': False,
                'error': f"Exception during KGType creation: {e}"
            }
    
    async def _test_list_kgtypes(self, space_id: str, graph_id: str, expected_count: int) -> Dict[str, Any]:
        """Test listing all KGTypes."""
        logger.info(f"  Testing list KGTypes (expecting {expected_count})...")
        
        try:
            response = await self.client.kgtypes.list_kgtypes(space_id, graph_id, page_size=100)
            
            if response.is_success:
                actual_count = response.count
                logger.info(f"    ✅ Listed {actual_count} KGTypes")
                
                # Log KGType names
                for kgtype in response.types[:5]:  # Show first 5
                    if isinstance(kgtype, dict):
                        name = kgtype.get('name', kgtype.get('http://vital.ai/ontology/vital-core#hasName', 'Unknown'))
                        logger.info(f"      - {name}")
                
                if actual_count >= expected_count:
                    return {
                        'name': 'List KGTypes',
                        'passed': True,
                        'details': f"Successfully listed {actual_count} KGTypes (expected at least {expected_count})",
                        'count': actual_count
                    }
                else:
                    return {
                        'name': 'List KGTypes',
                        'passed': False,
                        'error': f"Expected at least {expected_count} KGTypes, found {actual_count}"
                    }
            else:
                return {
                    'name': 'List KGTypes',
                    'passed': False,
                    'error': f"KGType listing failed: {response.error_message}"
                }
                
        except Exception as e:
            return {
                'name': 'List KGTypes',
                'passed': False,
                'error': f"Exception during KGType listing: {e}"
            }
    
    async def _test_verify_kgtypes(self, space_id: str, graph_id: str, kgtypes: List[KGType]) -> Dict[str, Any]:
        """Test verifying specific KGTypes exist."""
        logger.info(f"  Testing verify specific KGTypes...")
        
        try:
            # Get first KGType to verify
            test_kgtype = kgtypes[0]
            test_uri = str(test_kgtype.URI)
            
            response = await self.client.kgtypes.get_kgtype(space_id, graph_id, test_uri)
            
            if response.is_success and response.type:
                logger.info(f"    ✅ Verified KGType exists: {test_uri}")
                return {
                    'name': 'Verify KGTypes',
                    'passed': True,
                    'details': f"Successfully verified KGType: {test_uri}"
                }
            else:
                return {
                    'name': 'Verify KGTypes',
                    'passed': False,
                    'error': f"KGType not found: {test_uri}"
                }
                
        except Exception as e:
            return {
                'name': 'Verify KGTypes',
                'passed': False,
                'error': f"Exception during KGType verification: {e}"
            }
