#!/usr/bin/env python3
"""
KGTypes Create Test Module

Modular test implementation for KG type creation operations.
Used by the main KGTypes endpoint test orchestrator.

Focuses on:
- KGType creation with VitalSigns objects
- Quad-based endpoint communication
- Batch creation operations
- Response validation
- URI tracking for cleanup
"""

import logging
import uuid
from typing import Dict, Any, List, Optional

# Import VitalSigns for KGType objects
from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGEntityType import KGEntityType
from ai_haley_kg_domain.model.KGFrameType import KGFrameType
from ai_haley_kg_domain.model.KGRelationType import KGRelationType
from ai_haley_kg_domain.model.KGSlotType import KGSlotType

# Import models
from vitalgraph.model.kgtypes_model import KGTypeCreateResponse
from vitalgraph.utils.quad_format_utils import graphobjects_to_quad_list

logger = logging.getLogger(__name__)


class KGTypesCreateTester:
    """
    Modular test implementation for KG type creation operations.
    
    Handles:
    - KGType creation with VitalSigns objects
    - Quad-based document processing
    - Batch creation operations
    - Response validation
    - URI tracking for cleanup
    """
    
    def __init__(self, endpoint):
        """
        Initialize the KGTypes create tester.
        
        Args:
            endpoint: KGTypesEndpoint instance
        """
        self.endpoint = endpoint
        self.vitalsigns = VitalSigns()
        
    def create_test_kgtype_objects(self) -> List[KGType]:
        """Create 20 unique test KGType objects using VitalSigns for comprehensive testing."""
        kgtypes = []
        
        # Define diverse KGType categories with different properties and subclass types
        kgtype_definitions = [
            # Base KGType objects
            ("Person", "Represents a person entity in the knowledge graph", "1.0", "2024.1", KGType),
            ("Organization", "Represents an organization entity in the knowledge graph", "1.1", "2024.1", KGType),
            ("Product", "Represents a product entity in the knowledge graph", "2.0", "2024.2", KGType),
            ("Location", "Represents a geographical location in the knowledge graph", "1.5", "2024.1", KGType),
            ("Event", "Represents an event or occurrence in the knowledge graph", "1.2", "2024.2", KGType),
            
            # KGEntityType objects (used by KGEntities endpoint)
            ("CustomerEntity", "Entity type for customer entities", "1.0", "2024.1", KGEntityType),
            ("EmployeeEntity", "Entity type for employee entities", "1.1", "2024.1", KGEntityType),
            ("ProductEntity", "Entity type for product entities", "2.0", "2024.2", KGEntityType),
            ("CompanyEntity", "Entity type for company entities", "1.5", "2024.1", KGEntityType),
            ("ProjectEntity", "Entity type for project entities", "1.2", "2024.2", KGEntityType),
            
            # KGFrameType objects (used by KGFrames endpoint)
            ("AddressFrame", "Frame type for address information", "1.8", "2024.1", KGFrameType),
            ("ContactFrame", "Frame type for contact information", "2.1", "2024.2", KGFrameType),
            ("ProfileFrame", "Frame type for profile information", "1.4", "2024.1", KGFrameType),
            ("PreferencesFrame", "Frame type for user preferences", "1.7", "2024.2", KGFrameType),
            
            # KGRelationType objects (used by KGRelations endpoint)
            ("WorksFor", "Relation type for employment relationships", "1.3", "2024.1", KGRelationType),
            ("LocatedIn", "Relation type for location relationships", "2.2", "2024.2", KGRelationType),
            ("PartOf", "Relation type for part-whole relationships", "1.6", "2024.1", KGRelationType),
            
            # KGSlotType objects (used by KGFrames endpoint)
            ("NameSlot", "Slot type for name properties", "1.9", "2024.2", KGSlotType),
            ("EmailSlot", "Slot type for email properties", "1.1", "2024.1", KGSlotType),
            ("PhoneSlot", "Slot type for phone properties", "1.0", "2024.2", KGSlotType)
        ]
        
        # Create 20 unique KGType objects with appropriate subclasses
        for i, (name, description, version, model_version, kgtype_class) in enumerate(kgtype_definitions):
            # Instantiate the appropriate subclass
            kgtype = kgtype_class()
            kgtype.URI = f"http://vital.ai/test/kgtype/{name}_{uuid.uuid4().hex[:8]}"
            kgtype.name = name  # hasName -> name (inherited from VITAL_Node)
            kgtype.kGraphDescription = description  # hasKGraphDescription -> kGraphDescription
            kgtype.kGTypeVersion = version  # hasKGTypeVersion -> kGTypeVersion
            kgtype.kGModelVersion = model_version  # hasKGModelVersion -> kGModelVersion
            
            # Set subclass-specific properties (only use properties that are actually accessible)
            if isinstance(kgtype, KGEntityType):
                try:
                    kgtype.kGEntityTypeExternIdentifier = f"ext_{name.lower()}_{uuid.uuid4().hex[:6]}"
                except AttributeError:
                    pass  # Skip if property not accessible
            elif isinstance(kgtype, KGFrameType):
                try:
                    kgtype.kGFrameTypeExternIdentifier = f"frame_{name.lower()}_{uuid.uuid4().hex[:6]}"
                except AttributeError:
                    pass  # Skip if property not accessible
            elif isinstance(kgtype, KGRelationType):
                try:
                    kgtype.kGRelationTypeExternIdentifier = f"rel_{name.lower()}_{uuid.uuid4().hex[:6]}"
                except AttributeError:
                    pass  # Skip if property not accessible
            elif isinstance(kgtype, KGSlotType):
                try:
                    kgtype.kGSlotTypeExternIdentifier = f"slot_{name.lower()}_{uuid.uuid4().hex[:6]}"
                except AttributeError:
                    pass  # Skip if property not accessible
            
            kgtypes.append(kgtype)
        
        logger.info("Created 20 unique KGType objects with subclasses for comprehensive testing")
        logger.info("Subclass distribution: 5 KGType, 5 KGEntityType, 4 KGFrameType, 3 KGRelationType, 3 KGSlotType")
        
        return kgtypes
    
    
    async def test_create_kgtypes(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Test KGType creation with VitalSigns objects."""
        try:
            logger.info("🧪 Testing KGType creation...")
            
            # Create test KGType objects
            test_kgtypes = self.create_test_kgtype_objects()
            logger.info(f"Created {len(test_kgtypes)} test KGType objects")
            
            # Convert GraphObjects to quads for endpoint
            quads = graphobjects_to_quad_list(test_kgtypes)
            
            response = await self.endpoint._create_kgtypes(
                space_id,
                graph_id,
                quads,
                {"username": "test_user", "user_id": "test_user_123"}
            )
            
            if response and hasattr(response, 'success') and response.success:
                # Extract created KGType IDs for cleanup - use the original test_kgtypes URIs
                # Since creation was successful, we can use the original URIs
                created_uris = [str(obj.URI) for obj in test_kgtypes]
                
                logger.info(f"✅ Successfully created {len(test_kgtypes)} KGTypes")
                
                return {
                    "success": True,
                    "created_count": len(test_kgtypes),
                    "created_uris": created_uris,
                    "response": response,
                    "test_kgtypes": test_kgtypes
                }
            else:
                logger.error(f"❌ Failed to create KGTypes: {response}")
                return {
                    "success": False,
                    "created_count": 0,
                    "created_uris": [],
                    "response": response,
                    "test_kgtypes": test_kgtypes
                }
                
        except Exception as e:
            logger.error(f"❌ KGType creation test failed: {e}")
            return {
                "success": False,
                "created_count": 0,
                "created_uris": [],
                "error": str(e),
                "test_kgtypes": []
            }
