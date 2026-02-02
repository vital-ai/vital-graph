#!/usr/bin/env python3
"""
Business Events Create Test Case

Creates business event entities that reference existing organization entities.
Business events include: new customer, business transaction, customer cancellation, etc.
"""

import logging
from typing import Dict, Any, List

from vitalgraph_client_test.client_test_data import ClientTestDataCreator
from vital_ai_vitalsigns.model.GraphObject import GraphObject

from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


# Business event data templates
BUSINESS_EVENTS = [
    {
        "event_type": "NewCustomer",
        "event_name": "TechCorp New Enterprise Client",
        "org_index": 0  # References TechCorp Industries
    },
    {
        "event_type": "Transaction",
        "event_name": "Global Finance Q4 Deal",
        "org_index": 1  # References Global Finance Group
    },
    {
        "event_type": "NewCustomer",
        "event_name": "Healthcare Solutions Hospital Contract",
        "org_index": 2  # References Healthcare Solutions Inc
    },
    {
        "event_type": "Transaction",
        "event_name": "Energy Innovations Solar Project",
        "org_index": 3  # References Energy Innovations LLC
    },
    {
        "event_type": "Cancellation",
        "event_name": "Retail Dynamics Store Closure",
        "org_index": 4  # References Retail Dynamics Corp
    },
    {
        "event_type": "NewCustomer",
        "event_name": "Manufacturing Excellence OEM Partnership",
        "org_index": 5  # References Manufacturing Excellence
    },
    {
        "event_type": "Transaction",
        "event_name": "Education Systems Campus License",
        "org_index": 6  # References Education Systems Ltd
    },
    {
        "event_type": "NewCustomer",
        "event_name": "Transportation Networks Fleet Contract",
        "org_index": 7  # References Transportation Networks
    },
    {
        "event_type": "Transaction",
        "event_name": "Media & Entertainment Streaming Deal",
        "org_index": 8  # References Media & Entertainment Co
    },
    {
        "event_type": "Cancellation",
        "event_name": "Biotech Research Labs Trial Termination",
        "org_index": 9  # References Biotech Research Labs
    }
]


class CreateBusinessEventsTester:
    """Test case for creating business event entities that reference organizations."""
    
    def __init__(self, client):
        self.client = client
        self.data_creator = ClientTestDataCreator()
        
    def run_tests(self, space_id: str, graph_id: str, organization_uris: List[str]) -> Dict[str, Any]:
        """
        Run business event creation tests.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            organization_uris: List of organization entity URIs to reference
            
        Returns:
            Dict containing test results and created event URIs
        """
        results = {
            "test_name": "Create 10 Business Events",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
            "created_event_uris": [],
            "event_reference_ids": []
        }
        
        logger.info("=" * 80)
        logger.info("  Creating 10 Business Event Entities")
        logger.info("=" * 80)
        
        if len(organization_uris) < 10:
            error_msg = f"Not enough organization URIs provided. Expected 10, got {len(organization_uris)}"
            logger.error(f"❌ {error_msg}")
            results["errors"].append(error_msg)
            return results
        
        for i, event_data in enumerate(BUSINESS_EVENTS, 1):
            results["tests_run"] += 1
            
            try:
                # Get the organization URI to reference
                org_uri = organization_uris[event_data["org_index"]]
                
                # Generate reference ID for this event
                event_reference_id = f"EVENT-{i:04d}"
                
                logger.info(f"Creating business event {i}/10: {event_data['event_name']}...")
                logger.info(f"   Event Type: {event_data['event_type']}")
                logger.info(f"   Reference ID: {event_reference_id}")
                logger.info(f"   Source Business: {org_uri}")
                
                # Create business event entity graph
                event_objects = self.data_creator.create_business_event(
                    event_type=event_data["event_type"],
                    source_business_uri=org_uri,
                    event_name=event_data["event_name"],
                    reference_id=event_reference_id
                )
                
                # Extract event URI
                event_entity = [obj for obj in event_objects if isinstance(obj, KGEntity)][0]
                event_entity_uri = str(event_entity.URI)
                
                # Create all business events
                logger.info(f"Creating {len(event_objects)} business events...")
                
                # Log the VitalSigns objects to see exact structure
                import json
                objects_json = [json.loads(obj.to_json()) for obj in event_objects]
                logger.info(f"Event VitalSigns objects structure:")
                logger.info(json.dumps(objects_json, indent=2))
                
                response = self.client.kgentities.create_kgentities(
                    space_id=space_id,
                    graph_id=graph_id,
                    objects=event_objects
                )
                
                if response.is_success:
                    logger.info(f"   ✅ Created: {event_data['event_name']}")
                    logger.info(f"      URI: {event_entity_uri}")
                    logger.info(f"      Objects created: {response.count}")
                    results["tests_passed"] += 1
                    results["created_event_uris"].append(event_entity_uri)
                    results["event_reference_ids"].append(event_reference_id)
                else:
                    logger.error(f"   ❌ Failed (error {response.error_code}): {response.error_message}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Failed to create {event_data['event_name']}: {response.error_message}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error creating {event_data['event_name']}: {e}")
                results["tests_failed"] += 1
                results["errors"].append(f"Error creating {event_data['event_name']}: {str(e)}")
        
        logger.info(f"\n✅ Successfully created {results['tests_passed']}/{len(BUSINESS_EVENTS)} business events")
        
        return results
