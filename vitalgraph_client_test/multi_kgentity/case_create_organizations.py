#!/usr/bin/env python3
"""
Multiple Organizations Create Test Case

Creates 10 separate organization entities with complete entity graphs.
"""

import logging
from typing import Dict, Any, List
from datetime import datetime

from vitalgraph_client_test.client_test_data import ClientTestDataCreator
from vital_ai_vitalsigns.model.GraphObject import GraphObject

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot

logger = logging.getLogger(__name__)


# Organization data for 10 companies
ORGANIZATIONS = [
    {
        "name": "TechCorp Industries",
        "street": "100 Silicon Valley Blvd",
        "city": "San Francisco",
        "state": "California",
        "zipcode": "94105",
        "industry": "Technology",
        "founded": 2010,
        "employees": 500
    },
    {
        "name": "Global Finance Group",
        "street": "200 Wall Street",
        "city": "New York",
        "state": "New York",
        "zipcode": "10005",
        "industry": "Finance",
        "founded": 2005,
        "employees": 1200
    },
    {
        "name": "Healthcare Solutions Inc",
        "street": "300 Medical Center Dr",
        "city": "Boston",
        "state": "Massachusetts",
        "zipcode": "02115",
        "industry": "Healthcare",
        "founded": 2015,
        "employees": 800
    },
    {
        "name": "Energy Innovations LLC",
        "street": "400 Green Energy Way",
        "city": "Austin",
        "state": "Texas",
        "zipcode": "78701",
        "industry": "Energy",
        "founded": 2018,
        "employees": 350
    },
    {
        "name": "Retail Dynamics Corp",
        "street": "500 Commerce Plaza",
        "city": "Chicago",
        "state": "Illinois",
        "zipcode": "60601",
        "industry": "Retail",
        "founded": 2008,
        "employees": 2500
    },
    {
        "name": "Manufacturing Excellence",
        "street": "600 Industrial Parkway",
        "city": "Detroit",
        "state": "Michigan",
        "zipcode": "48201",
        "industry": "Manufacturing",
        "founded": 2000,
        "employees": 1800
    },
    {
        "name": "Education Systems Ltd",
        "street": "700 University Ave",
        "city": "Seattle",
        "state": "Washington",
        "zipcode": "98101",
        "industry": "Education",
        "founded": 2012,
        "employees": 450
    },
    {
        "name": "Transportation Networks",
        "street": "800 Logistics Center",
        "city": "Atlanta",
        "state": "Georgia",
        "zipcode": "30301",
        "industry": "Transportation",
        "founded": 2016,
        "employees": 950
    },
    {
        "name": "Media & Entertainment Co",
        "street": "900 Hollywood Blvd",
        "city": "Los Angeles",
        "state": "California",
        "zipcode": "90028",
        "industry": "Media",
        "founded": 2011,
        "employees": 650
    },
    {
        "name": "Biotech Research Labs",
        "street": "1000 Research Park Dr",
        "city": "San Diego",
        "state": "California",
        "zipcode": "92121",
        "industry": "Biotechnology",
        "founded": 2019,
        "employees": 280
    }
]


class CreateOrganizationsTester:
    """Test case for creating multiple organization entities."""
    
    def __init__(self, client):
        self.client = client
        self.data_creator = ClientTestDataCreator()
        
    def create_organization_entity_graph(self, org_data: dict, reference_id: str = None, 
                                        file_uris: Dict[str, str] = None, org_index: int = 0) -> List[GraphObject]:
        """Create a complete organization entity graph with frames and slots, including file references."""
        objects = self.data_creator.create_organization_with_address(org_data["name"])
        
        # Add reference ID to the entity if provided
        for obj in objects:
            if isinstance(obj, KGEntity) and reference_id:
                obj.referenceIdentifier = reference_id
        
        # Update the slots with custom data
        for obj in objects:
            if isinstance(obj, KGTextSlot):
                slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                
                if 'StreetSlot' in slot_type:
                    obj.textSlotValue = org_data["street"]
                elif 'CitySlot' in slot_type:
                    obj.textSlotValue = org_data["city"]
                elif 'StateSlot' in slot_type:
                    obj.textSlotValue = org_data["state"]
                elif 'ZipCodeSlot' in slot_type:
                    obj.textSlotValue = org_data["zipcode"]
                elif 'IndustrySlot' in slot_type:
                    obj.textSlotValue = org_data["industry"]
            
            elif isinstance(obj, KGIntegerSlot):
                slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                
                if 'EmployeeCountSlot' in slot_type:
                    obj.integerSlotValue = org_data["employees"]
            
            elif isinstance(obj, KGDateTimeSlot):
                slot_type = str(obj.kGSlotType) if obj.kGSlotType else ''
                
                if 'FoundedDateSlot' in slot_type:
                    obj.dateTimeSlotValue = datetime(org_data["founded"], 1, 1)
        
        # Add file reference frames if file_uris provided
        if file_uris:
            file_objects = self._create_file_reference_frames(org_data["name"], org_index, file_uris)
            objects.extend(file_objects)
        
        return objects
    
    def _create_file_reference_frames(self, org_name: str, org_index: int, 
                                     file_uris: Dict[str, str]) -> List[GraphObject]:
        """Create file reference frames for an organization based on its index."""
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGURISlot import KGURISlot
        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
        import uuid
        
        file_objects = []
        
        # File mapping based on organization index (0-9)
        # Org 0 (TechCorp): Contract + Technical
        # Org 1 (Global Finance): Contract + Financial
        # Org 2 (Healthcare): Contract + Legal
        # Org 3 (Energy): Technical + Financial
        # Org 4 (Retail): Marketing
        # Org 5 (Manufacturing): Technical
        # Org 6 (Education): Contract
        # Org 7 (Transportation): Contract
        # Org 8 (Media): Marketing
        # Org 9 (Biotech): Legal + Technical
        
        file_mappings = [
            [("contract_1", "BusinessContractFrame", "Service Agreement"), 
             ("technical_1", "TechnicalDocumentFrame", "Technical Specifications")],  # TechCorp
            [("contract_2", "BusinessContractFrame", "Partnership Agreement"), 
             ("financial_1", "FinancialDocumentFrame", "Q1 Financial Report")],  # Global Finance
            [("contract_3", "BusinessContractFrame", "Service Contract"), 
             ("legal_1", "LegalDocumentFrame", "Legal Agreement")],  # Healthcare
            [("technical_2", "TechnicalDocumentFrame", "System Architecture"), 
             ("financial_2", "FinancialDocumentFrame", "Q2 Financial Report")],  # Energy
            [("marketing_1", "MarketingMaterialFrame", "Product Brochure")],  # Retail
            [("technical_1", "TechnicalDocumentFrame", "Manufacturing Specs")],  # Manufacturing
            [("contract_1", "BusinessContractFrame", "Education Services Agreement")],  # Education
            [("contract_2", "BusinessContractFrame", "Transportation Contract")],  # Transportation
            [("marketing_2", "MarketingMaterialFrame", "Media Kit")],  # Media
            [("legal_1", "LegalDocumentFrame", "Research Agreement"), 
             ("technical_2", "TechnicalDocumentFrame", "Lab Protocols")]  # Biotech
        ]
        
        if org_index >= len(file_mappings):
            return file_objects
        
        org_file_mappings = file_mappings[org_index]
        
        for file_key, frame_type_name, doc_title in org_file_mappings:
            if file_key not in file_uris:
                continue
            
            # Create frame
            frame = KGFrame()
            frame.URI = f"urn:frame:{uuid.uuid4()}"
            frame.kGFrameType = f"http://vital.ai/test/kgtype/{frame_type_name}"
            file_objects.append(frame)
            
            # Create DocumentFileURISlot
            uri_slot = KGURISlot()
            uri_slot.URI = f"urn:slot:{uuid.uuid4()}"
            uri_slot.kGSlotType = "http://vital.ai/test/kgtype/DocumentFileURISlot"
            uri_slot.uriSlotValue = file_uris[file_key]
            file_objects.append(uri_slot)
            
            # Create edge from frame to URI slot
            uri_edge = Edge_hasKGSlot()
            uri_edge.URI = f"urn:edge:{uuid.uuid4()}"
            uri_edge.edgeSource = frame.URI
            uri_edge.edgeDestination = uri_slot.URI
            file_objects.append(uri_edge)
            
            # Create DocumentTitleSlot
            title_slot = KGTextSlot()
            title_slot.URI = f"urn:slot:{uuid.uuid4()}"
            title_slot.kGSlotType = "http://vital.ai/test/kgtype/DocumentTitleSlot"
            title_slot.textSlotValue = doc_title
            file_objects.append(title_slot)
            
            # Create edge from frame to title slot
            title_edge = Edge_hasKGSlot()
            title_edge.URI = f"urn:edge:{uuid.uuid4()}"
            title_edge.edgeSource = frame.URI
            title_edge.edgeDestination = title_slot.URI
            file_objects.append(title_edge)
        
        return file_objects
        
    async def run_tests(self, space_id: str, graph_id: str, file_uris: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Run organization creation tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            file_uris: Optional dictionary of file URIs for file reference frames
            
        Returns:
            Dict containing test results, created entity URIs, and reference IDs
        """
        results = {
            "test_name": "Create 10 Organizations",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "created_entity_uris": [],
            "reference_ids": []
        }
        
        logger.info("=" * 80)
        logger.info("  Creating 10 Organization Entities")
        if file_uris:
            logger.info("  (with file reference frames)")
        logger.info("=" * 80)
        
        for i, org_data in enumerate(ORGANIZATIONS, 1):
            results["tests_run"] += 1
            
            try:
                # Generate reference ID for this organization
                reference_id = f"ORG-{i:04d}"
                
                logger.info(f"Creating organization {i}/10: {org_data['name']}...")
                logger.info(f"   Reference ID: {reference_id}")
                
                # Create entity graph with reference ID and file URIs
                org_objects = self.create_organization_entity_graph(
                    org_data, 
                    reference_id, 
                    file_uris=file_uris,
                    org_index=i-1  # 0-indexed
                )
                
                # Extract entity URI
                org_entity = [obj for obj in org_objects if isinstance(obj, KGEntity)][0]
                org_entity_uri = str(org_entity.URI)
                
                # Create entity - pass GraphObjects directly
                response = await self.client.kgentities.create_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=org_objects
                )
                
                if response.is_success:
                    logger.info(f"   ✅ Created: {org_data['name']}")
                    logger.info(f"      URI: {org_entity_uri}")
                    logger.info(f"      Objects created: {response.count}")
                    results["tests_passed"] += 1
                    results["created_entity_uris"].append(org_entity_uri)
                    results["reference_ids"].append(reference_id)
                else:
                    logger.error(f"   ❌ Failed (error {response.error_code}): {response.error_message}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Failed to create {org_data['name']}: {response.error_message}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error creating {org_data['name']}: {e}")
                results["tests_failed"] += 1
                results["errors"].append(f"Error creating {org_data['name']}: {str(e)}")
        
        logger.info(f"\n✅ Successfully created {results['tests_passed']}/{len(ORGANIZATIONS)} organizations")
        
        return results
