"""
KGEntity Test Data Creator

Creates comprehensive test data for KGEntity endpoint testing using correct VitalSigns properties.
This module provides test data for:
- Basic entities (Person, Organization, Project) with frames and slots
- Complex entity graphs with multiple frames and connecting edges
- Grouping URI test data for performance validation
- Edge relationships and hierarchical structures
"""

import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot


class KGEntityTestDataCreator:
    """Creates comprehensive test data for KGEntity endpoint testing."""
    
    def __init__(self):
        self.base_uri = "http://vital.ai/test/kgentity"
        self.test_timestamp = datetime.now().isoformat()
        
    def generate_test_uri(self, entity_type: str, identifier: str = None) -> str:
        """Generate a test URI for entities, frames, slots, or edges."""
        if identifier is None:
            identifier = str(uuid.uuid4())
        return f"{self.base_uri}/{entity_type}/{identifier}"
    
    # ============================================================================
    # Basic Entity Creation Methods
    # ============================================================================
    
    def create_person_with_contact(self, name: str = "Alice Johnson") -> List[GraphObject]:
        """Create person entity with multiple frames and slots."""
        objects = []
        
        # Create the person entity
        person = KGEntity()
        person.URI = self.generate_test_uri("person", name.lower().replace(" ", "_"))
        person.name = name
        person.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#PersonEntity"
        objects.append(person)
        
        # ========== Contact Frame ==========
        contact_frame = KGFrame()
        contact_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_contact")
        contact_frame.name = f"{name} Contact Info"
        contact_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ContactFrame"
        objects.append(contact_frame)
        
        # Contact frame slots
        email_slot = KGTextSlot()
        email_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_email")
        email_slot.name = f"{name} Email"
        email_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EmailSlot"
        email_slot.textSlotValue = f"{name.lower().replace(' ', '.')}@example.com"
        objects.append(email_slot)
        
        phone_slot = KGTextSlot()
        phone_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_phone")
        phone_slot.name = f"{name} Phone"
        phone_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#PhoneSlot"
        phone_slot.textSlotValue = "+1-555-0123"
        objects.append(phone_slot)
        
        linkedin_slot = KGTextSlot()
        linkedin_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_linkedin")
        linkedin_slot.name = f"{name} LinkedIn"
        linkedin_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#SocialMediaSlot"
        linkedin_slot.textSlotValue = f"linkedin.com/in/{name.lower().replace(' ', '')}"
        objects.append(linkedin_slot)
        
        # Contact frame edges
        entity_contact_edge = Edge_hasEntityKGFrame()
        entity_contact_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_contact")
        entity_contact_edge.edgeSource = person.URI
        entity_contact_edge.edgeDestination = contact_frame.URI
        objects.append(entity_contact_edge)
        
        contact_email_edge = Edge_hasKGSlot()
        contact_email_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_contact_email")
        contact_email_edge.edgeSource = contact_frame.URI
        contact_email_edge.edgeDestination = email_slot.URI
        objects.append(contact_email_edge)
        
        contact_phone_edge = Edge_hasKGSlot()
        contact_phone_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_contact_phone")
        contact_phone_edge.edgeSource = contact_frame.URI
        contact_phone_edge.edgeDestination = phone_slot.URI
        objects.append(contact_phone_edge)
        
        contact_linkedin_edge = Edge_hasKGSlot()
        contact_linkedin_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_contact_linkedin")
        contact_linkedin_edge.edgeSource = contact_frame.URI
        contact_linkedin_edge.edgeDestination = linkedin_slot.URI
        objects.append(contact_linkedin_edge)
        
        # ========== Personal Info Frame ==========
        personal_frame = KGFrame()
        personal_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_personal")
        personal_frame.name = f"{name} Personal Info"
        personal_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#PersonalInfoFrame"
        objects.append(personal_frame)
        
        # Personal frame slots
        age_slot = KGIntegerSlot()
        age_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_age")
        age_slot.name = f"{name} Age"
        age_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#AgeSlot"
        age_slot.integerSlotValue = 35
        objects.append(age_slot)
        
        birthdate_slot = KGDateTimeSlot()
        birthdate_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_birthdate")
        birthdate_slot.name = f"{name} Birth Date"
        birthdate_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#BirthDateSlot"
        birthdate_slot.dateTimeSlotValue = datetime(1989, 5, 15)
        objects.append(birthdate_slot)
        
        nationality_slot = KGTextSlot()
        nationality_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_nationality")
        nationality_slot.name = f"{name} Nationality"
        nationality_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#NationalitySlot"
        nationality_slot.textSlotValue = "American"
        objects.append(nationality_slot)
        
        # Personal frame edges
        entity_personal_edge = Edge_hasEntityKGFrame()
        entity_personal_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_personal")
        entity_personal_edge.edgeSource = person.URI
        entity_personal_edge.edgeDestination = personal_frame.URI
        objects.append(entity_personal_edge)
        
        personal_age_edge = Edge_hasKGSlot()
        personal_age_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_personal_age")
        personal_age_edge.edgeSource = personal_frame.URI
        personal_age_edge.edgeDestination = age_slot.URI
        objects.append(personal_age_edge)
        
        personal_birthdate_edge = Edge_hasKGSlot()
        personal_birthdate_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_personal_birthdate")
        personal_birthdate_edge.edgeSource = personal_frame.URI
        personal_birthdate_edge.edgeDestination = birthdate_slot.URI
        objects.append(personal_birthdate_edge)
        
        personal_nationality_edge = Edge_hasKGSlot()
        personal_nationality_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_personal_nationality")
        personal_nationality_edge.edgeSource = personal_frame.URI
        personal_nationality_edge.edgeDestination = nationality_slot.URI
        objects.append(personal_nationality_edge)
        
        # ========== Employment Frame ==========
        employment_frame = KGFrame()
        employment_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_employment")
        employment_frame.name = f"{name} Employment Info"
        employment_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#EmploymentFrame"
        objects.append(employment_frame)
        
        # Employment frame slots
        job_title_slot = KGTextSlot()
        job_title_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_job_title")
        job_title_slot.name = f"{name} Job Title"
        job_title_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#JobTitleSlot"
        job_title_slot.textSlotValue = "Software Engineer"
        objects.append(job_title_slot)
        
        company_slot = KGTextSlot()
        company_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_company")
        company_slot.name = f"{name} Company"
        company_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#CompanySlot"
        company_slot.textSlotValue = "Tech Corp"
        objects.append(company_slot)
        
        start_date_slot = KGDateTimeSlot()
        start_date_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_start_date")
        start_date_slot.name = f"{name} Start Date"
        start_date_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#StartDateSlot"
        start_date_slot.dateTimeSlotValue = datetime(2020, 3, 1)
        objects.append(start_date_slot)
        
        # Employment frame edges
        entity_employment_edge = Edge_hasEntityKGFrame()
        entity_employment_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_employment")
        entity_employment_edge.edgeSource = person.URI
        entity_employment_edge.edgeDestination = employment_frame.URI
        objects.append(entity_employment_edge)
        
        employment_title_edge = Edge_hasKGSlot()
        employment_title_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_employment_title")
        employment_title_edge.edgeSource = employment_frame.URI
        employment_title_edge.edgeDestination = job_title_slot.URI
        objects.append(employment_title_edge)
        
        employment_company_edge = Edge_hasKGSlot()
        employment_company_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_employment_company")
        employment_company_edge.edgeSource = employment_frame.URI
        employment_company_edge.edgeDestination = company_slot.URI
        objects.append(employment_company_edge)
        
        employment_start_edge = Edge_hasKGSlot()
        employment_start_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_employment_start")
        employment_start_edge.edgeSource = employment_frame.URI
        employment_start_edge.edgeDestination = start_date_slot.URI
        objects.append(employment_start_edge)
        
        return objects
    
    def create_organization_with_address(self, name: str = "Global Tech Corp") -> List[GraphObject]:
        """Create organization entity with multiple frames and slots."""
        objects = []
        
        # Create the organization entity
        org = KGEntity()
        org.URI = self.generate_test_uri("organization", name.lower().replace(" ", "_"))
        org.name = name
        org.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
        objects.append(org)
        
        # ========== Address Frame ==========
        address_frame = KGFrame()
        address_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_address")
        address_frame.name = f"{name} Address"
        address_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#AddressFrame"
        objects.append(address_frame)
        
        # Address frame slots
        street_slot = KGTextSlot()
        street_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_street")
        street_slot.name = f"{name} Street"
        street_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#StreetSlot"
        street_slot.textSlotValue = "123 Business Ave"
        objects.append(street_slot)
        
        city_slot = KGTextSlot()
        city_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_city")
        city_slot.name = f"{name} City"
        city_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#CitySlot"
        city_slot.textSlotValue = "San Francisco"
        objects.append(city_slot)
        
        state_slot = KGTextSlot()
        state_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_state")
        state_slot.name = f"{name} State"
        state_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#StateSlot"
        state_slot.textSlotValue = "California"
        objects.append(state_slot)
        
        zipcode_slot = KGTextSlot()
        zipcode_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_zipcode")
        zipcode_slot.name = f"{name} Zip Code"
        zipcode_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#ZipCodeSlot"
        zipcode_slot.textSlotValue = "94102"
        objects.append(zipcode_slot)
        
        # Address frame edges
        entity_address_edge = Edge_hasEntityKGFrame()
        entity_address_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_address")
        entity_address_edge.edgeSource = org.URI
        entity_address_edge.edgeDestination = address_frame.URI
        objects.append(entity_address_edge)
        
        address_street_edge = Edge_hasKGSlot()
        address_street_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_address_street")
        address_street_edge.edgeSource = address_frame.URI
        address_street_edge.edgeDestination = street_slot.URI
        objects.append(address_street_edge)
        
        address_city_edge = Edge_hasKGSlot()
        address_city_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_address_city")
        address_city_edge.edgeSource = address_frame.URI
        address_city_edge.edgeDestination = city_slot.URI
        objects.append(address_city_edge)
        
        address_state_edge = Edge_hasKGSlot()
        address_state_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_address_state")
        address_state_edge.edgeSource = address_frame.URI
        address_state_edge.edgeDestination = state_slot.URI
        objects.append(address_state_edge)
        
        address_zipcode_edge = Edge_hasKGSlot()
        address_zipcode_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_address_zipcode")
        address_zipcode_edge.edgeSource = address_frame.URI
        address_zipcode_edge.edgeDestination = zipcode_slot.URI
        objects.append(address_zipcode_edge)
        
        # ========== Company Info Frame ==========
        company_frame = KGFrame()
        company_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_company")
        company_frame.name = f"{name} Company Info"
        company_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame"
        objects.append(company_frame)
        
        # Company frame slots
        industry_slot = KGTextSlot()
        industry_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_industry")
        industry_slot.name = f"{name} Industry"
        industry_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#IndustrySlot"
        industry_slot.textSlotValue = "Technology"
        objects.append(industry_slot)
        
        founded_slot = KGDateTimeSlot()
        founded_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_founded")
        founded_slot.name = f"{name} Founded Date"
        founded_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#FoundedDateSlot"
        founded_slot.dateTimeSlotValue = datetime(2010, 1, 15)
        objects.append(founded_slot)
        
        employees_slot = KGIntegerSlot()
        employees_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_employees")
        employees_slot.name = f"{name} Employee Count"
        employees_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EmployeeCountSlot"
        employees_slot.integerSlotValue = 500
        objects.append(employees_slot)
        
        # Company frame edges
        entity_company_edge = Edge_hasEntityKGFrame()
        entity_company_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_company")
        entity_company_edge.edgeSource = org.URI
        entity_company_edge.edgeDestination = company_frame.URI
        objects.append(entity_company_edge)
        
        company_industry_edge = Edge_hasKGSlot()
        company_industry_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_company_industry")
        company_industry_edge.edgeSource = company_frame.URI
        company_industry_edge.edgeDestination = industry_slot.URI
        objects.append(company_industry_edge)
        
        company_founded_edge = Edge_hasKGSlot()
        company_founded_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_company_founded")
        company_founded_edge.edgeSource = company_frame.URI
        company_founded_edge.edgeDestination = founded_slot.URI
        objects.append(company_founded_edge)
        
        company_employees_edge = Edge_hasKGSlot()
        company_employees_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_company_employees")
        company_employees_edge.edgeSource = company_frame.URI
        company_employees_edge.edgeDestination = employees_slot.URI
        objects.append(company_employees_edge)
        
        # ========== Management Frame (Hierarchical) ==========
        management_frame = KGFrame()
        management_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_management")
        management_frame.name = f"{name} Management Team"
        management_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#ManagementFrame"
        objects.append(management_frame)
        
        # Entity to Management Frame edge
        entity_management_edge = Edge_hasEntityKGFrame()
        entity_management_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_management")
        entity_management_edge.edgeSource = org.URI
        entity_management_edge.edgeDestination = management_frame.URI
        objects.append(entity_management_edge)
        
        # ========== CEO Officer Frame ==========
        ceo_frame = KGFrame()
        ceo_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_ceo")
        ceo_frame.name = f"{name} CEO"
        ceo_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#OfficerFrame"
        objects.append(ceo_frame)
        
        # CEO slots
        ceo_name_slot = KGTextSlot()
        ceo_name_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_ceo_name")
        ceo_name_slot.name = f"{name} CEO Name"
        ceo_name_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerNameSlot"
        ceo_name_slot.textSlotValue = "John Smith"
        objects.append(ceo_name_slot)
        
        ceo_role_slot = KGTextSlot()
        ceo_role_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_ceo_role")
        ceo_role_slot.name = f"{name} CEO Role"
        ceo_role_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerRoleSlot"
        ceo_role_slot.textSlotValue = "Chief Executive Officer"
        objects.append(ceo_role_slot)
        
        ceo_start_slot = KGDateTimeSlot()
        ceo_start_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_ceo_start")
        ceo_start_slot.name = f"{name} CEO Start Date"
        ceo_start_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerStartDateSlot"
        ceo_start_slot.dateTimeSlotValue = datetime(2018, 1, 15)
        objects.append(ceo_start_slot)
        
        # Management to CEO Frame edge (Frame-to-Frame)
        management_ceo_edge = Edge_hasKGFrame()
        management_ceo_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_management_ceo")
        management_ceo_edge.edgeSource = management_frame.URI
        management_ceo_edge.edgeDestination = ceo_frame.URI
        objects.append(management_ceo_edge)
        
        # CEO Frame to Slot edges
        ceo_name_edge = Edge_hasKGSlot()
        ceo_name_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_ceo_name")
        ceo_name_edge.edgeSource = ceo_frame.URI
        ceo_name_edge.edgeDestination = ceo_name_slot.URI
        objects.append(ceo_name_edge)
        
        ceo_role_edge = Edge_hasKGSlot()
        ceo_role_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_ceo_role")
        ceo_role_edge.edgeSource = ceo_frame.URI
        ceo_role_edge.edgeDestination = ceo_role_slot.URI
        objects.append(ceo_role_edge)
        
        ceo_start_edge = Edge_hasKGSlot()
        ceo_start_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_ceo_start")
        ceo_start_edge.edgeSource = ceo_frame.URI
        ceo_start_edge.edgeDestination = ceo_start_slot.URI
        objects.append(ceo_start_edge)
        
        # ========== CTO Officer Frame ==========
        cto_frame = KGFrame()
        cto_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_cto")
        cto_frame.name = f"{name} CTO"
        cto_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#OfficerFrame"
        objects.append(cto_frame)
        
        # CTO slots
        cto_name_slot = KGTextSlot()
        cto_name_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_cto_name")
        cto_name_slot.name = f"{name} CTO Name"
        cto_name_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerNameSlot"
        cto_name_slot.textSlotValue = "Sarah Johnson"
        objects.append(cto_name_slot)
        
        cto_role_slot = KGTextSlot()
        cto_role_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_cto_role")
        cto_role_slot.name = f"{name} CTO Role"
        cto_role_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerRoleSlot"
        cto_role_slot.textSlotValue = "Chief Technology Officer"
        objects.append(cto_role_slot)
        
        cto_start_slot = KGDateTimeSlot()
        cto_start_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_cto_start")
        cto_start_slot.name = f"{name} CTO Start Date"
        cto_start_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerStartDateSlot"
        cto_start_slot.dateTimeSlotValue = datetime(2019, 3, 1)
        objects.append(cto_start_slot)
        
        # Management to CTO Frame edge (Frame-to-Frame)
        management_cto_edge = Edge_hasKGFrame()
        management_cto_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_management_cto")
        management_cto_edge.edgeSource = management_frame.URI
        management_cto_edge.edgeDestination = cto_frame.URI
        objects.append(management_cto_edge)
        
        # CTO Frame to Slot edges
        cto_name_edge = Edge_hasKGSlot()
        cto_name_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_cto_name")
        cto_name_edge.edgeSource = cto_frame.URI
        cto_name_edge.edgeDestination = cto_name_slot.URI
        objects.append(cto_name_edge)
        
        cto_role_edge = Edge_hasKGSlot()
        cto_role_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_cto_role")
        cto_role_edge.edgeSource = cto_frame.URI
        cto_role_edge.edgeDestination = cto_role_slot.URI
        objects.append(cto_role_edge)
        
        cto_start_edge = Edge_hasKGSlot()
        cto_start_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_cto_start")
        cto_start_edge.edgeSource = cto_frame.URI
        cto_start_edge.edgeDestination = cto_start_slot.URI
        objects.append(cto_start_edge)
        
        # ========== CFO Officer Frame ==========
        cfo_frame = KGFrame()
        cfo_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_cfo")
        cfo_frame.name = f"{name} CFO"
        cfo_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#OfficerFrame"
        objects.append(cfo_frame)
        
        # CFO slots
        cfo_name_slot = KGTextSlot()
        cfo_name_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_cfo_name")
        cfo_name_slot.name = f"{name} CFO Name"
        cfo_name_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerNameSlot"
        cfo_name_slot.textSlotValue = "Michael Brown"
        objects.append(cfo_name_slot)
        
        cfo_role_slot = KGTextSlot()
        cfo_role_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_cfo_role")
        cfo_role_slot.name = f"{name} CFO Role"
        cfo_role_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerRoleSlot"
        cfo_role_slot.textSlotValue = "Chief Financial Officer"
        objects.append(cfo_role_slot)
        
        cfo_start_slot = KGDateTimeSlot()
        cfo_start_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_cfo_start")
        cfo_start_slot.name = f"{name} CFO Start Date"
        cfo_start_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#OfficerStartDateSlot"
        cfo_start_slot.dateTimeSlotValue = datetime(2020, 6, 15)
        objects.append(cfo_start_slot)
        
        # Management to CFO Frame edge (Frame-to-Frame)
        management_cfo_edge = Edge_hasKGFrame()
        management_cfo_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_management_cfo")
        management_cfo_edge.edgeSource = management_frame.URI
        management_cfo_edge.edgeDestination = cfo_frame.URI
        objects.append(management_cfo_edge)
        
        # CFO Frame to Slot edges
        cfo_name_edge = Edge_hasKGSlot()
        cfo_name_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_cfo_name")
        cfo_name_edge.edgeSource = cfo_frame.URI
        cfo_name_edge.edgeDestination = cfo_name_slot.URI
        objects.append(cfo_name_edge)
        
        cfo_role_edge = Edge_hasKGSlot()
        cfo_role_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_cfo_role")
        cfo_role_edge.edgeSource = cfo_frame.URI
        cfo_role_edge.edgeDestination = cfo_role_slot.URI
        objects.append(cfo_role_edge)
        
        cfo_start_edge = Edge_hasKGSlot()
        cfo_start_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_cfo_start")
        cfo_start_edge.edgeSource = cfo_frame.URI
        cfo_start_edge.edgeDestination = cfo_start_slot.URI
        objects.append(cfo_start_edge)
        
        return objects
    
    def create_project_with_timeline(self, name: str = "AI Research Project") -> List[GraphObject]:
        """Create project entity with multiple frames and slots."""
        objects = []
        
        # Create the project entity
        project = KGEntity()
        project.URI = self.generate_test_uri("project", name.lower().replace(" ", "_"))
        project.name = name
        project.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#ProjectEntity"
        objects.append(project)
        
        # ========== Timeline Frame ==========
        timeline_frame = KGFrame()
        timeline_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_timeline")
        timeline_frame.name = f"{name} Timeline"
        timeline_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TimelineFrame"
        objects.append(timeline_frame)
        
        # Timeline frame slots
        start_slot = KGDateTimeSlot()
        start_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_start")
        start_slot.name = f"{name} Start Date"
        start_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#StartDateSlot"
        start_slot.dateTimeSlotValue = datetime(2024, 1, 1)
        objects.append(start_slot)
        
        end_slot = KGDateTimeSlot()
        end_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_end")
        end_slot.name = f"{name} End Date"
        end_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#EndDateSlot"
        end_slot.dateTimeSlotValue = datetime(2024, 12, 31)
        objects.append(end_slot)
        
        milestone_slot = KGTextSlot()
        milestone_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_milestone")
        milestone_slot.name = f"{name} Next Milestone"
        milestone_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#MilestoneSlot"
        milestone_slot.textSlotValue = "Phase 1 Completion"
        objects.append(milestone_slot)
        
        # Timeline frame edges
        entity_timeline_edge = Edge_hasEntityKGFrame()
        entity_timeline_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_timeline")
        entity_timeline_edge.edgeSource = project.URI
        entity_timeline_edge.edgeDestination = timeline_frame.URI
        objects.append(entity_timeline_edge)
        
        timeline_start_edge = Edge_hasKGSlot()
        timeline_start_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_timeline_start")
        timeline_start_edge.edgeSource = timeline_frame.URI
        timeline_start_edge.edgeDestination = start_slot.URI
        objects.append(timeline_start_edge)
        
        timeline_end_edge = Edge_hasKGSlot()
        timeline_end_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_timeline_end")
        timeline_end_edge.edgeSource = timeline_frame.URI
        timeline_end_edge.edgeDestination = end_slot.URI
        objects.append(timeline_end_edge)
        
        timeline_milestone_edge = Edge_hasKGSlot()
        timeline_milestone_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_timeline_milestone")
        timeline_milestone_edge.edgeSource = timeline_frame.URI
        timeline_milestone_edge.edgeDestination = milestone_slot.URI
        objects.append(timeline_milestone_edge)
        
        # ========== Budget Frame ==========
        budget_frame = KGFrame()
        budget_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_budget")
        budget_frame.name = f"{name} Budget"
        budget_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#BudgetFrame"
        objects.append(budget_frame)
        
        # Budget frame slots
        total_budget_slot = KGTextSlot()
        total_budget_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_total_budget")
        total_budget_slot.name = f"{name} Total Budget"
        total_budget_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#BudgetSlot"
        total_budget_slot.textSlotValue = "$2.5M"
        objects.append(total_budget_slot)
        
        spent_slot = KGTextSlot()
        spent_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_spent")
        spent_slot.name = f"{name} Amount Spent"
        spent_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#SpentSlot"
        spent_slot.textSlotValue = "$800K"
        objects.append(spent_slot)
        
        # Budget frame edges
        entity_budget_edge = Edge_hasEntityKGFrame()
        entity_budget_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_budget")
        entity_budget_edge.edgeSource = project.URI
        entity_budget_edge.edgeDestination = budget_frame.URI
        objects.append(entity_budget_edge)
        
        budget_total_edge = Edge_hasKGSlot()
        budget_total_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_budget_total")
        budget_total_edge.edgeSource = budget_frame.URI
        budget_total_edge.edgeDestination = total_budget_slot.URI
        objects.append(budget_total_edge)
        
        budget_spent_edge = Edge_hasKGSlot()
        budget_spent_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_budget_spent")
        budget_spent_edge.edgeSource = budget_frame.URI
        budget_spent_edge.edgeDestination = spent_slot.URI
        objects.append(budget_spent_edge)
        
        # ========== Team Frame ==========
        team_frame = KGFrame()
        team_frame.URI = self.generate_test_uri("frame", f"{name.lower().replace(' ', '_')}_team")
        team_frame.name = f"{name} Team"
        team_frame.kGFrameType = "http://vital.ai/ontology/haley-ai-kg#TeamFrame"
        objects.append(team_frame)
        
        # Team frame slots
        lead_slot = KGTextSlot()
        lead_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_lead")
        lead_slot.name = f"{name} Project Lead"
        lead_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#ProjectLeadSlot"
        lead_slot.textSlotValue = "Dr. Sarah Johnson"
        objects.append(lead_slot)
        
        team_size_slot = KGIntegerSlot()
        team_size_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_team_size")
        team_size_slot.name = f"{name} Team Size"
        team_size_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#TeamSizeSlot"
        team_size_slot.integerSlotValue = 12
        objects.append(team_size_slot)
        
        department_slot = KGTextSlot()
        department_slot.URI = self.generate_test_uri("slot", f"{name.lower().replace(' ', '_')}_department")
        department_slot.name = f"{name} Department"
        department_slot.kGSlotType = "http://vital.ai/ontology/haley-ai-kg#DepartmentSlot"
        department_slot.textSlotValue = "Research & Development"
        objects.append(department_slot)
        
        # Team frame edges
        entity_team_edge = Edge_hasEntityKGFrame()
        entity_team_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_entity_team")
        entity_team_edge.edgeSource = project.URI
        entity_team_edge.edgeDestination = team_frame.URI
        objects.append(entity_team_edge)
        
        team_lead_edge = Edge_hasKGSlot()
        team_lead_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_team_lead")
        team_lead_edge.edgeSource = team_frame.URI
        team_lead_edge.edgeDestination = lead_slot.URI
        objects.append(team_lead_edge)
        
        team_size_edge = Edge_hasKGSlot()
        team_size_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_team_size")
        team_size_edge.edgeSource = team_frame.URI
        team_size_edge.edgeDestination = team_size_slot.URI
        objects.append(team_size_edge)
        
        team_department_edge = Edge_hasKGSlot()
        team_department_edge.URI = self.generate_test_uri("edge", f"{name.lower().replace(' ', '_')}_team_department")
        team_department_edge.edgeSource = team_frame.URI
        team_department_edge.edgeDestination = department_slot.URI
        objects.append(team_department_edge)
        
        return objects
    
    # ============================================================================
    # Convenience Methods for Test Data Generation
    # ============================================================================
    
    def create_basic_entities(self) -> List[List[GraphObject]]:
        """Create basic entity test data."""
        return [
            self.create_person_with_contact("John Doe"),
            self.create_person_with_contact("Jane Smith"),
            self.create_organization_with_address("Tech Corp"),
            self.create_organization_with_address("Global Industries"),
            self.create_project_with_timeline("AI Project"),
            self.create_project_with_timeline("Data Migration")
        ]
    
    def create_complex_entity_graphs(self) -> List[List[GraphObject]]:
        """Create complex entity graphs with multiple frames."""
        # For now, return the same as basic entities
        # This can be expanded later with more complex structures
        return self.create_basic_entities()
    
    def create_grouping_uri_test_data(self) -> List[List[GraphObject]]:
        """Create test data specifically for grouping URI functionality."""
        # For now, return the same as basic entities
        # This can be expanded later with specific grouping URI test cases
        return self.create_basic_entities()
