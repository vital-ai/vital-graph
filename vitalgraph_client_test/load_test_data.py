#!/usr/bin/env python3
"""
Entity Registry Test Data Loader.

Creates test entities via the REST API and writes a manifest file
that the test script and cleanup script use.

Usage:
    python vitalgraph_client_test/load_test_data.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.entity_registry_model import (
    AliasCreateRequest,
    CategoryCreateRequest,
    EntityCreateRequest,
    EntityTypeCreateRequest,
    IdentifierCreateRequest,
    LocationCategoryRequest,
    LocationCreateRequest,
    RelationshipCreateRequest,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).parent / 'test_data_manifest.json'
CREATED_BY = 'test_runner'


async def load_data():
    client = VitalGraphClient()
    manifest = {'entities': {}, 'entity_type_key': None}

    try:
        await client.open()
        logger.info("Client connected")
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return False

    try:
        reg = client.entity_registry

        # ---------------------------------------------------------------
        # Entity type
        # ---------------------------------------------------------------
        type_key = 'vendor_test'
        try:
            et = await reg.create_entity_type(EntityTypeCreateRequest(
                type_key=type_key,
                type_label='Vendor Test',
                type_description='Test vendor type for automated testing',
            ))
            logger.info(f"Created entity type: {type_key} (type_id={et.type_id})")
        except Exception as e:
            if '409' in str(e) or 'already exists' in str(e).lower() or 'duplicate' in str(e).lower():
                logger.info(f"Entity type '{type_key}' already exists, skipping")
            else:
                raise
        manifest['entity_type_key'] = type_key

        # ---------------------------------------------------------------
        # Entities
        # ---------------------------------------------------------------

        # 1. Acme Corporation — full entity with aliases, identifiers, coords, locations
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='business',
            primary_name='Acme Corporation',
            description='A manufacturing company',
            country='US',
            region='California',
            locality='San Francisco',
            latitude=37.7749,
            longitude=-122.4194,
            website='https://acme.example.com',
            metadata={'founding_year': 1985, 'employee_count': 450, 'sic_code': '3599'},
            created_by=CREATED_BY,
            aliases=[
                AliasCreateRequest(alias_name='Acme Corp', alias_type='abbreviation'),
                AliasCreateRequest(alias_name='ACME', alias_type='dba'),
            ],
            identifiers=[
                IdentifierCreateRequest(identifier_namespace='DUNS', identifier_value='DUNS-TEST-001'),
                IdentifierCreateRequest(identifier_namespace='EIN', identifier_value='47-TEST-001'),
            ],
            locations=[
                LocationCreateRequest(
                    location_type_key='headquarters',
                    location_name='Acme HQ',
                    address_line_1='100 Market Street',
                    address_line_2='Suite 3200',
                    locality='San Francisco',
                    admin_area_2='San Francisco County',
                    admin_area_1='California',
                    country='United States',
                    country_code='US',
                    postal_code='94105',
                    formatted_address='100 Market St, Suite 3200, San Francisco, CA 94105, US',
                    latitude=37.7936,
                    longitude=-122.3950,
                    timezone='America/Los_Angeles',
                    is_primary=True,
                ),
                LocationCreateRequest(
                    location_type_key='warehouse',
                    location_name='West Coast Distribution Center',
                    address_line_1='8500 Industrial Blvd',
                    locality='Oakland',
                    admin_area_1='California',
                    country='United States',
                    country_code='US',
                    postal_code='94621',
                    formatted_address='8500 Industrial Blvd, Oakland, CA 94621, US',
                    latitude=37.7516,
                    longitude=-122.1968,
                    timezone='America/Los_Angeles',
                ),
            ],
        ))
        manifest['entities']['acme_corp'] = resp.entity_id
        logger.info(f"  acme_corp: {resp.entity_id}")

        # 2. Alice Johnson — person, no coords
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='person',
            primary_name='Alice Johnson',
            country='US',
            created_by=CREATED_BY,
        ))
        manifest['entities']['alice_johnson'] = resp.entity_id
        logger.info(f"  alice_johnson: {resp.entity_id}")

        # 3. Bob Martinez — person with coords (Chicago) and office location
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='person',
            primary_name='Bob Martinez',
            description='Regional sales director',
            country='US',
            region='Illinois',
            locality='Chicago',
            latitude=41.8781,
            longitude=-87.6298,
            created_by=CREATED_BY,
            aliases=[
                AliasCreateRequest(alias_name='Robert Martinez', alias_type='legal'),
            ],
            locations=[
                LocationCreateRequest(
                    location_type_key='branch',
                    location_name='Bob Martinez Chicago Office',
                    address_line_1='233 S Wacker Drive',
                    address_line_2='Floor 40',
                    locality='Chicago',
                    admin_area_1='Illinois',
                    country='United States',
                    country_code='US',
                    postal_code='60606',
                    formatted_address='233 S Wacker Dr, Floor 40, Chicago, IL 60606, US',
                    latitude=41.8789,
                    longitude=-87.6359,
                    timezone='America/Chicago',
                    is_primary=True,
                ),
            ],
        ))
        manifest['entities']['bob_martinez'] = resp.entity_id
        logger.info(f"  bob_martinez: {resp.entity_id}")

        # 4. Carol Chen — person with coords (San Francisco) and office location
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='person',
            primary_name='Carol Chen',
            description='Software architect and consultant',
            country='US',
            region='California',
            locality='San Francisco',
            latitude=37.7749,
            longitude=-122.4194,
            created_by=CREATED_BY,
            locations=[
                LocationCreateRequest(
                    location_type_key='branch',
                    location_name='Carol Chen SF Office',
                    address_line_1='555 Mission Street',
                    address_line_2='Suite 2800',
                    locality='San Francisco',
                    admin_area_1='California',
                    country='United States',
                    country_code='US',
                    postal_code='94105',
                    formatted_address='555 Mission St, Suite 2800, San Francisco, CA 94105, US',
                    latitude=37.7873,
                    longitude=-122.3986,
                    timezone='America/Los_Angeles',
                    is_primary=True,
                ),
            ],
        ))
        manifest['entities']['carol_chen'] = resp.entity_id
        logger.info(f"  carol_chen: {resp.entity_id}")

        # 5. David Okafor — person, New York based with office location
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='person',
            primary_name='David Okafor',
            description='International trade compliance officer',
            country='US',
            region='New York',
            locality='New York',
            latitude=40.7128,
            longitude=-74.0060,
            created_by=CREATED_BY,
            locations=[
                LocationCreateRequest(
                    location_type_key='branch',
                    location_name='David Okafor NYC Office',
                    address_line_1='375 Park Avenue',
                    address_line_2='Floor 22',
                    locality='New York',
                    admin_area_1='New York',
                    country='United States',
                    country_code='US',
                    postal_code='10152',
                    formatted_address='375 Park Ave, Floor 22, New York, NY 10152, US',
                    latitude=40.7614,
                    longitude=-73.9718,
                    timezone='America/New_York',
                    is_primary=True,
                ),
            ],
        ))
        manifest['entities']['david_okafor'] = resp.entity_id
        logger.info(f"  david_okafor: {resp.entity_id}")

        # 6. Acme Inc — for same-as testing
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='business',
            primary_name='Acme Inc',
            country='US',
            created_by=CREATED_BY,
        ))
        manifest['entities']['acme_inc'] = resp.entity_id
        logger.info(f"  acme_inc: {resp.entity_id}")

        # 7. GeoTest Corp — entity with geo coordinates and multiple locations
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='business',
            primary_name='GeoTest Corp',
            description='Geospatial analytics company',
            country='US',
            region='New Jersey',
            locality='Newark',
            latitude=40.7357,
            longitude=-74.1724,
            metadata={'industry': 'technology', 'sub_industry': 'geospatial'},
            created_by=CREATED_BY,
            locations=[
                LocationCreateRequest(
                    location_type_key='headquarters',
                    location_name='GeoTest Newark HQ',
                    address_line_1='1 Gateway Center',
                    address_line_2='Floor 18',
                    locality='Newark',
                    admin_area_2='Essex County',
                    admin_area_1='New Jersey',
                    country='United States',
                    country_code='US',
                    postal_code='07102',
                    formatted_address='1 Gateway Center, Floor 18, Newark, NJ 07102, US',
                    latitude=40.7357,
                    longitude=-74.1724,
                    timezone='America/New_York',
                    is_primary=True,
                ),
                LocationCreateRequest(
                    location_type_key='branch',
                    location_name='GeoTest Austin Office',
                    address_line_1='300 W 6th Street',
                    address_line_2='Suite 1500',
                    locality='Austin',
                    admin_area_2='Travis County',
                    admin_area_1='Texas',
                    country='United States',
                    country_code='US',
                    postal_code='78701',
                    formatted_address='300 W 6th St, Suite 1500, Austin, TX 78701, US',
                    latitude=30.2700,
                    longitude=-97.7468,
                    timezone='America/Chicago',
                ),
                LocationCreateRequest(
                    location_type_key='mailing',
                    location_name='GeoTest Mailing',
                    address_line_1='PO Box 4521',
                    locality='Newark',
                    admin_area_1='New Jersey',
                    country='United States',
                    country_code='US',
                    postal_code='07101',
                ),
            ],
        ))
        manifest['entities']['geo_test'] = resp.entity_id
        logger.info(f"  geo_test: {resp.entity_id}")

        # 8. NoGeo Corp — entity without coordinates
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='business',
            primary_name='NoGeo Corp',
            country='US',
            created_by=CREATED_BY,
        ))
        manifest['entities']['no_geo'] = resp.entity_id
        logger.info(f"  no_geo: {resp.entity_id}")

        # 9. Pinnacle Consulting Group — US entity with full addresses
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='business',
            primary_name='Pinnacle Consulting Group',
            description='Management consulting and advisory services',
            country='US',
            region='Massachusetts',
            locality='Boston',
            latitude=42.3601,
            longitude=-71.0589,
            website='https://pinnacle-consulting.example.com',
            metadata={'founding_year': 2003, 'employee_count': 120},
            created_by=CREATED_BY,
            aliases=[
                AliasCreateRequest(alias_name='Pinnacle Group', alias_type='abbreviation'),
                AliasCreateRequest(alias_name='PCG', alias_type='abbreviation'),
            ],
            identifiers=[
                IdentifierCreateRequest(identifier_namespace='EIN', identifier_value='04-TEST-002'),
            ],
            locations=[
                LocationCreateRequest(
                    location_type_key='headquarters',
                    location_name='Pinnacle Boston HQ',
                    address_line_1='200 Clarendon Street',
                    address_line_2='Floor 52',
                    locality='Boston',
                    admin_area_2='Suffolk County',
                    admin_area_1='Massachusetts',
                    country='United States',
                    country_code='US',
                    postal_code='02116',
                    formatted_address='200 Clarendon St, Floor 52, Boston, MA 02116, US',
                    latitude=42.3490,
                    longitude=-71.0764,
                    timezone='America/New_York',
                    is_primary=True,
                ),
                LocationCreateRequest(
                    location_type_key='branch',
                    location_name='Pinnacle NYC Office',
                    address_line_1='1 World Trade Center',
                    address_line_2='Floor 85',
                    locality='New York',
                    admin_area_2='New York County',
                    admin_area_1='New York',
                    country='United States',
                    country_code='US',
                    postal_code='10007',
                    formatted_address='1 World Trade Center, Floor 85, New York, NY 10007, US',
                    latitude=40.7127,
                    longitude=-74.0134,
                    timezone='America/New_York',
                ),
            ],
        ))
        manifest['entities']['pinnacle_consulting'] = resp.entity_id
        logger.info(f"  pinnacle_consulting: {resp.entity_id}")

        # 10. Elena Vasquez — person with residence location
        resp = await reg.create_entity(EntityCreateRequest(
            type_key='person',
            primary_name='Elena Vasquez',
            description='Supply chain operations manager',
            country='US',
            region='Texas',
            locality='Austin',
            latitude=30.2672,
            longitude=-97.7431,
            created_by=CREATED_BY,
            aliases=[
                AliasCreateRequest(alias_name='E. Vasquez', alias_type='abbreviation'),
            ],
            locations=[
                LocationCreateRequest(
                    location_type_key='residence',
                    location_name='Home',
                    locality='Austin',
                    admin_area_1='Texas',
                    country='United States',
                    country_code='US',
                    postal_code='78704',
                    latitude=30.2500,
                    longitude=-97.7600,
                    timezone='America/Chicago',
                    is_primary=True,
                ),
            ],
        ))
        manifest['entities']['elena_vasquez'] = resp.entity_id
        logger.info(f"  elena_vasquez: {resp.entity_id}")

        # ---------------------------------------------------------------
        # Bulk entities for dedup / phonetic / typo testing
        # ---------------------------------------------------------------
        logger.info("\nCreating bulk dedup test entities...")

        BULK_ENTITIES = [
            # ---- Phonetic cluster: Schneider / Snyder / Schnider ----
            {'key': 'hans_schneider', 'type': 'person', 'name': 'Hans Schneider', 'country': 'DE',
             'description': 'Manufacturing engineer'},
            {'key': 'john_snyder', 'type': 'person', 'name': 'John Snyder', 'country': 'US',
             'description': 'Civil engineer'},
            {'key': 'karl_schnider', 'type': 'person', 'name': 'Karl Schnider', 'country': 'DE',
             'description': 'Electrical engineer'},
            {'key': 'schneider_industries', 'type': 'business', 'name': 'Schneider Industries', 'country': 'DE'},

            # ---- Phonetic cluster: Schmidt / Schmitt / Schmid ----
            {'key': 'erik_schmidt', 'type': 'person', 'name': 'Erik Schmidt', 'country': 'DE',
             'description': 'Automotive executive'},
            {'key': 'eric_schmitt', 'type': 'person', 'name': 'Eric Schmitt', 'country': 'DE',
             'description': 'Financial analyst'},
            {'key': 'erich_schmid', 'type': 'person', 'name': 'Erich Schmid', 'country': 'AT',
             'description': 'Art historian'},
            {'key': 'schmidt_electronics', 'type': 'business', 'name': 'Schmidt Electronics GmbH', 'country': 'DE'},

            # ---- Phonetic cluster: Meyer / Meier / Mayer ----
            {'key': 'klaus_meyer', 'type': 'person', 'name': 'Klaus Meyer', 'country': 'DE'},
            {'key': 'klaus_meier', 'type': 'person', 'name': 'Klaus Meier', 'country': 'CH'},
            {'key': 'klaus_mayer', 'type': 'person', 'name': 'Klaus Mayer', 'country': 'DE'},

            # ---- Phonetic cluster: Johnson / Johanson / Johansson ----
            {'key': 'robert_johnson', 'type': 'person', 'name': 'Robert Johnson', 'country': 'US'},
            {'key': 'robert_johanson', 'type': 'person', 'name': 'Robert Johanson', 'country': 'SE'},
            {'key': 'robert_johansson', 'type': 'person', 'name': 'Robert Johansson', 'country': 'SE'},

            # ---- Phonetic cluster: Stephen / Steven ----
            {'key': 'stephen_phillips', 'type': 'person', 'name': 'Stephen Phillips', 'country': 'US'},
            {'key': 'steven_phillips', 'type': 'person', 'name': 'Steven Phillips', 'country': 'US'},

            # ---- Phonetic cluster: Fischer / Fisher ----
            {'key': 'fischer_tech', 'type': 'business', 'name': 'Fischer Technologies', 'country': 'DE'},
            {'key': 'fisher_tech', 'type': 'business', 'name': 'Fisher Technologies', 'country': 'US'},

            # ---- Phonetic cluster: Thompson / Thomson ----
            {'key': 'thompson_consulting', 'type': 'business', 'name': 'Thompson Consulting', 'country': 'US'},
            {'key': 'thomson_consulting', 'type': 'business', 'name': 'Thomson Consulting', 'country': 'GB'},

            # ---- Phonetic cluster: Catherine / Kathryn ----
            {'key': 'catherine_williams', 'type': 'person', 'name': 'Catherine Williams', 'country': 'US'},
            {'key': 'kathryn_williams', 'type': 'person', 'name': 'Kathryn Williams', 'country': 'US'},

            # ---- Typo targets: clean names for query-time typo testing ----
            {'key': 'smith_associates', 'type': 'business', 'name': 'Smith & Associates', 'country': 'US'},
            {'key': 'anderson_consulting', 'type': 'business', 'name': 'Anderson Consulting Group', 'country': 'US'},
            {'key': 'williams_engineering', 'type': 'business', 'name': 'Williams Engineering', 'country': 'US'},
            {'key': 'microsoft_corp', 'type': 'business', 'name': 'Microsoft Corporation', 'country': 'US'},
            {'key': 'deutsche_bank', 'type': 'business', 'name': 'Deutsche Bank AG', 'country': 'DE'},
            {'key': 'goldman_sachs', 'type': 'business', 'name': 'Goldman Sachs Group', 'country': 'US'},
            {'key': 'morgan_stanley', 'type': 'business', 'name': 'Morgan Stanley Financial', 'country': 'US'},
            {'key': 'jpmorgan_chase', 'type': 'business', 'name': 'JPMorgan Chase & Co', 'country': 'US'},
            {'key': 'bank_of_america', 'type': 'business', 'name': 'Bank of America', 'country': 'US'},
            {'key': 'wells_fargo', 'type': 'business', 'name': 'Wells Fargo Financial', 'country': 'US'},
            {'key': 'general_electric', 'type': 'business', 'name': 'General Electric Company', 'country': 'US',
             'aliases': [{'name': 'GE', 'type': 'abbreviation'}]},
            {'key': 'johnson_johnson', 'type': 'business', 'name': 'Johnson & Johnson', 'country': 'US',
             'aliases': [{'name': 'J&J', 'type': 'abbreviation'}]},
            {'key': 'procter_gamble', 'type': 'business', 'name': 'Procter & Gamble', 'country': 'US',
             'aliases': [{'name': 'P&G', 'type': 'abbreviation'}]},
            {'key': 'berkshire_hathaway', 'type': 'business', 'name': 'Berkshire Hathaway Inc', 'country': 'US'},
            {'key': 'citigroup', 'type': 'business', 'name': 'Citigroup Inc', 'country': 'US',
             'aliases': [{'name': 'Citi', 'type': 'abbreviation'}]},

            # ---- Near-duplicate business clusters ----
            {'key': 'acme_intl', 'type': 'business', 'name': 'Acme International Holdings', 'country': 'US'},
            {'key': 'global_acme', 'type': 'business', 'name': 'Global Acme Systems', 'country': 'US'},
            {'key': 'johnson_mfg', 'type': 'business', 'name': 'Johnson Manufacturing', 'country': 'US'},
            {'key': 'johnson_mfg_inc', 'type': 'business', 'name': 'Johnson Manufacturing Inc', 'country': 'US'},
            {'key': 'johnson_mfg_llc', 'type': 'business', 'name': 'Johnson Manufacturing LLC', 'country': 'US'},
            {'key': 'pacific_rim_trading', 'type': 'business', 'name': 'Pacific Rim Trading Co', 'country': 'US'},
            {'key': 'pacific_rim_intl', 'type': 'business', 'name': 'Pacific Rim International', 'country': 'US'},
            {'key': 'globaltech_solutions', 'type': 'business', 'name': 'GlobalTech Solutions', 'country': 'US'},
            {'key': 'global_tech_inc', 'type': 'business', 'name': 'Global Tech Inc', 'country': 'US'},
            {'key': 'globaltech_systems', 'type': 'business', 'name': 'GlobalTech Systems', 'country': 'US'},

            # ---- Alias-heavy entities ----
            {'key': 'ibm', 'type': 'business', 'name': 'International Business Machines', 'country': 'US',
             'aliases': [{'name': 'IBM', 'type': 'abbreviation'}, {'name': 'Big Blue', 'type': 'nickname'}]},
            {'key': 'att', 'type': 'business', 'name': 'American Telephone and Telegraph', 'country': 'US',
             'aliases': [{'name': 'AT&T', 'type': 'abbreviation'}, {'name': 'ATT', 'type': 'abbreviation'}]},
            {'key': 'nasa', 'type': 'organization', 'name': 'National Aeronautics and Space Administration',
             'country': 'US', 'aliases': [{'name': 'NASA', 'type': 'abbreviation'}]},
            {'key': 'fbi', 'type': 'government', 'name': 'Federal Bureau of Investigation', 'country': 'US',
             'aliases': [{'name': 'FBI', 'type': 'abbreviation'}]},

            # ---- International / diverse names ----
            {'key': 'muenchen_tech', 'type': 'business', 'name': 'München Technologies GmbH', 'country': 'DE'},
            {'key': 'sao_paulo_trading', 'type': 'business', 'name': 'São Paulo Trading Corp', 'country': 'BR'},
            {'key': 'zurich_financial', 'type': 'business', 'name': 'Zürich Financial Services', 'country': 'CH'},
            {'key': 'beijing_electronics', 'type': 'business', 'name': 'Beijing Electronics Co Ltd', 'country': 'CN'},
            {'key': 'tokyo_precision', 'type': 'business', 'name': 'Tokyo Precision Instruments', 'country': 'JP'},
            {'key': 'seoul_semiconductor', 'type': 'business', 'name': 'Seoul Semiconductor Ltd', 'country': 'KR'},
            {'key': 'paris_luxe', 'type': 'business', 'name': 'Paris Luxe Holdings SA', 'country': 'FR'},
            {'key': 'dubai_logistics', 'type': 'business', 'name': 'Dubai Logistics International', 'country': 'AE'},
            {'key': 'singapore_shipping', 'type': 'business', 'name': 'Singapore Shipping Lines', 'country': 'SG'},
            {'key': 'london_capital', 'type': 'business', 'name': 'London Capital Markets', 'country': 'GB'},

            # ---- Additional persons: near-match and diverse names ----
            {'key': 'james_williams', 'type': 'person', 'name': 'James Williams', 'country': 'US'},
            {'key': 'james_wilson', 'type': 'person', 'name': 'James Wilson', 'country': 'US'},
            {'key': 'michael_brown', 'type': 'person', 'name': 'Michael Brown', 'country': 'US'},
            {'key': 'michael_braun', 'type': 'person', 'name': 'Michael Braun', 'country': 'DE'},
            {'key': 'sarah_connor', 'type': 'person', 'name': 'Sarah Connor', 'country': 'US'},
            {'key': 'sara_oconnor', 'type': 'person', 'name': "Sara O'Connor", 'country': 'IE'},
            {'key': 'william_smith', 'type': 'person', 'name': 'William Smith', 'country': 'US'},
            {'key': 'wilhelm_schmidt', 'type': 'person', 'name': 'Wilhelm Schmidt', 'country': 'DE'},
            {'key': 'maria_garcia', 'type': 'person', 'name': 'Maria Garcia', 'country': 'ES'},
            {'key': 'marie_garcia', 'type': 'person', 'name': 'Marie Garcia', 'country': 'FR'},
            {'key': 'peter_mueller', 'type': 'person', 'name': 'Peter Mueller', 'country': 'DE'},
            {'key': 'peter_muller', 'type': 'person', 'name': 'Peter Müller', 'country': 'DE'},
            {'key': 'anna_petrov', 'type': 'person', 'name': 'Anna Petrov', 'country': 'RU'},
            {'key': 'anna_petrova', 'type': 'person', 'name': 'Anna Petrova', 'country': 'RU'},
            {'key': 'chen_wei', 'type': 'person', 'name': 'Chen Wei', 'country': 'CN'},
            {'key': 'wei_chen', 'type': 'person', 'name': 'Wei Chen', 'country': 'CN'},
            {'key': 'takeshi_yamamoto', 'type': 'person', 'name': 'Takeshi Yamamoto', 'country': 'JP'},
            {'key': 'ahmed_hassan', 'type': 'person', 'name': 'Ahmed Hassan', 'country': 'EG'},
            {'key': 'ahmed_hasan', 'type': 'person', 'name': 'Ahmed Hasan', 'country': 'SA'},

            # ---- Additional near-duplicate business pairs ----
            {'key': 'apex_solutions', 'type': 'business', 'name': 'Apex Solutions Inc', 'country': 'US'},
            {'key': 'apex_systems', 'type': 'business', 'name': 'Apex Systems LLC', 'country': 'US'},
            {'key': 'summit_capital', 'type': 'business', 'name': 'Summit Capital Partners', 'country': 'US'},
            {'key': 'summit_group', 'type': 'business', 'name': 'Summit Group Holdings', 'country': 'US'},
            {'key': 'pioneer_energy', 'type': 'business', 'name': 'Pioneer Energy Corp', 'country': 'US'},
            {'key': 'pioneer_resources', 'type': 'business', 'name': 'Pioneer Resources Inc', 'country': 'US'},
            {'key': 'atlas_logistics', 'type': 'business', 'name': 'Atlas Logistics International', 'country': 'US'},
            {'key': 'atlas_shipping', 'type': 'business', 'name': 'Atlas Shipping Co', 'country': 'US'},
            {'key': 'nexus_pharma', 'type': 'business', 'name': 'Nexus Pharmaceuticals', 'country': 'US'},
            {'key': 'nexus_biotech', 'type': 'business', 'name': 'Nexus Biotechnology Inc', 'country': 'US'},
            {'key': 'horizon_media', 'type': 'business', 'name': 'Horizon Media Group', 'country': 'US'},
            {'key': 'horizon_digital', 'type': 'business', 'name': 'Horizon Digital Solutions', 'country': 'US'},
        ]

        for ent in BULK_ENTITIES:
            try:
                aliases_list = None
                if 'aliases' in ent:
                    aliases_list = [
                        AliasCreateRequest(alias_name=a['name'], alias_type=a['type'])
                        for a in ent['aliases']
                    ]
                resp = await reg.create_entity(EntityCreateRequest(
                    type_key=ent['type'],
                    primary_name=ent['name'],
                    country=ent.get('country', 'US'),
                    description=ent.get('description', ''),
                    created_by=CREATED_BY,
                    aliases=aliases_list,
                ))
                manifest['entities'][ent['key']] = resp.entity_id
                logger.info(f"  {ent['key']}: {resp.entity_id}")
            except Exception as e:
                logger.warning(f"  {ent['key']} skipped: {e}")

        # ---------------------------------------------------------------
        # Relationships
        # ---------------------------------------------------------------
        logger.info("\nCreating relationships...")

        # Bob Martinez employed by Acme Corporation
        try:
            rel = await reg.create_relationship(RelationshipCreateRequest(
                entity_source=manifest['entities']['acme_corp'],
                entity_destination=manifest['entities']['bob_martinez'],
                relationship_type_key='employer_of',
                description='Regional sales director at Acme Corporation',
                created_by=CREATED_BY,
            ))
            manifest.setdefault('relationships', []).append(rel.relationship_id)
            logger.info(f"  acme_corp -> bob_martinez (employer_of): {rel.relationship_id}")
        except Exception as e:
            logger.warning(f"  relationship acme_corp->bob_martinez skipped: {e}")

        # Carol Chen is an advisor to Acme Corporation
        try:
            rel = await reg.create_relationship(RelationshipCreateRequest(
                entity_source=manifest['entities']['carol_chen'],
                entity_destination=manifest['entities']['acme_corp'],
                relationship_type_key='advisor_to',
                description='Technical architecture advisor',
                created_by=CREATED_BY,
            ))
            manifest.setdefault('relationships', []).append(rel.relationship_id)
            logger.info(f"  carol_chen -> acme_corp (advisor_to): {rel.relationship_id}")
        except Exception as e:
            logger.warning(f"  relationship carol_chen->acme_corp skipped: {e}")

        # David Okafor employed by Pinnacle Consulting
        try:
            rel = await reg.create_relationship(RelationshipCreateRequest(
                entity_source=manifest['entities']['pinnacle_consulting'],
                entity_destination=manifest['entities']['david_okafor'],
                relationship_type_key='employer_of',
                description='Trade compliance officer at Pinnacle Consulting Group',
                created_by=CREATED_BY,
            ))
            manifest.setdefault('relationships', []).append(rel.relationship_id)
            logger.info(f"  pinnacle_consulting -> david_okafor (employer_of): {rel.relationship_id}")
        except Exception as e:
            logger.warning(f"  relationship pinnacle->david_okafor skipped: {e}")

        # Acme Corporation is a customer of GeoTest Corp
        try:
            rel = await reg.create_relationship(RelationshipCreateRequest(
                entity_source=manifest['entities']['acme_corp'],
                entity_destination=manifest['entities']['geo_test'],
                relationship_type_key='customer_of',
                description='Acme uses GeoTest geospatial analytics platform',
                created_by=CREATED_BY,
            ))
            manifest.setdefault('relationships', []).append(rel.relationship_id)
            logger.info(f"  acme_corp -> geo_test (customer_of): {rel.relationship_id}")
        except Exception as e:
            logger.warning(f"  relationship acme_corp->geo_test skipped: {e}")

        # Elena Vasquez employed by GeoTest Corp
        try:
            rel = await reg.create_relationship(RelationshipCreateRequest(
                entity_source=manifest['entities']['geo_test'],
                entity_destination=manifest['entities']['elena_vasquez'],
                relationship_type_key='employer_of',
                description='Supply chain operations manager at GeoTest Corp',
                created_by=CREATED_BY,
            ))
            manifest.setdefault('relationships', []).append(rel.relationship_id)
            logger.info(f"  geo_test -> elena_vasquez (employer_of): {rel.relationship_id}")
        except Exception as e:
            logger.warning(f"  relationship geo_test->elena_vasquez skipped: {e}")

        # ---------------------------------------------------------------
        # Write manifest
        # ---------------------------------------------------------------
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
        logger.info(f"\nManifest written to {MANIFEST_PATH}")
        logger.info(f"Created {len(manifest['entities'])} entities")
        rel_count = len(manifest.get('relationships', []))
        if rel_count:
            logger.info(f"Created {rel_count} relationships")
        return True

    except Exception as e:
        logger.error(f"Failed to load test data: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await client.close()


if __name__ == '__main__':
    success = asyncio.run(load_data())
    sys.exit(0 if success else 1)
