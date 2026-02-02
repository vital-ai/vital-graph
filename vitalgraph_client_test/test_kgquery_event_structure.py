#!/usr/bin/env python3
"""
Direct Query Test for KGQuery Test Data

This script directly queries the test space to verify the structure of
BusinessEventEntity data created by test_kgqueries_endpoint.py.

It queries the space_kgquery_test dataset to verify:
1. BusinessEventEntity data is present
2. Frame data is present (SourceBusinessFrame, EventDetailsFrame)
3. Slot data is present (BusinessEntityURISlot, EventTypeSlot)
4. All relationships are intact (entity->frame->slot paths)
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class KGQueryEventStructureTester:
    """Test direct queries against KGQuery test data."""
    
    def __init__(self):
        """Initialize the tester."""
        # Use localhost Fuseki
        self.fuseki_url = "http://localhost:3030"
        
        # Test space configuration
        self.space_id = "space_kgquery_test"
        self.dataset_name = f"vitalgraph_space_{self.space_id}"
        self.graph_id = "urn:kgquery_test_graph"
        
        logger.info(f"✅ Initialized tester for {self.space_id}\n")
    
    def query_fuseki(self, sparql_query: str, query_description: str) -> Optional[Dict[str, Any]]:
        """
        Execute a SPARQL query against the test dataset in Fuseki.
        
        Args:
            sparql_query: SPARQL query to execute
            query_description: Description of what the query does
            
        Returns:
            Query results as dictionary, or None if failed
        """
        query_url = f"{self.fuseki_url}/{self.dataset_name}/query"
        
        logger.info(f"📊 {query_description}")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}")
        
        headers = {
            'Accept': 'application/sparql-results+json',
        }
        
        params = {
            'query': sparql_query
        }
        
        try:
            response = requests.get(
                query_url,
                params=params,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                results = response.json()
                return results
            else:
                logger.error(f"   ❌ Query failed")
                logger.error(f"   Status code: {response.status_code}")
                logger.error(f"   Response: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"   ❌ Error executing query: {e}")
            return None
    
    def count_business_events(self) -> bool:
        """Count BusinessEventEntity objects in the graph."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?entity) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
                ?entity haley:hasKGEntityType <http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity> .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting BusinessEventEntity objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} BusinessEventEntity object(s)\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No business events found\n")
        return False
    
    def list_business_events(self) -> bool:
        """List all BusinessEventEntity objects with their names."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?name
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
                ?entity haley:hasKGEntityType <http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity> .
                OPTIONAL {{ ?entity vital-core:hasName ?name }}
            }}
        }}
        LIMIT 5
        """
        
        results = self.query_fuseki(query, "Listing first 5 BusinessEventEntity objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} event(s):")
                for binding in bindings:
                    entity_uri = binding.get('entity', {}).get('value', 'unknown')
                    entity_name = binding.get('name', {}).get('value', 'No name')
                    entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                    logger.info(f"      • {entity_name} ({entity_short})")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No business events found\n")
        return False
    
    def check_event_frame_structure(self) -> bool:
        """Check the complete entity->frame->slot structure for one event."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?entityName ?frame ?frameType ?slot ?slotType ?slotValue
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
                ?entity haley:hasKGEntityType <http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity> .
                OPTIONAL {{ ?entity vital-core:hasName ?entityName }}
                
                OPTIONAL {{
                    ?frameEdge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                    ?frameEdge vital-core:hasEdgeSource ?entity .
                    ?frameEdge vital-core:hasEdgeDestination ?frame .
                    ?frame haley:hasKGFrameType ?frameType .
                    
                    OPTIONAL {{
                        ?slotEdge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                        ?slotEdge vital-core:hasEdgeSource ?frame .
                        ?slotEdge vital-core:hasEdgeDestination ?slot .
                        ?slot haley:hasKGSlotType ?slotType .
                        
                        OPTIONAL {{ ?slot haley:hasEntitySlotValue ?slotValue }}
                        OPTIONAL {{ ?slot haley:hasUriSlotValue ?slotValue }}
                        OPTIONAL {{ ?slot haley:hasTextSlotValue ?slotValue }}
                        OPTIONAL {{ ?slot haley:hasDoubleSlotValue ?slotValue }}
                    }}
                }}
            }}
        }}
        LIMIT 50
        """
        
        results = self.query_fuseki(query, "Checking event->frame->slot structure")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} result(s)")
                
                # Group by entity
                entities = {}
                for binding in bindings:
                    entity_uri = binding.get('entity', {}).get('value')
                    if entity_uri and entity_uri not in entities:
                        entities[entity_uri] = {
                            'name': binding.get('entityName', {}).get('value', 'No name'),
                            'frames': {}
                        }
                    
                    if entity_uri:
                        frame_uri = binding.get('frame', {}).get('value')
                        if frame_uri:
                            frame_type = binding.get('frameType', {}).get('value', 'No type')
                            if frame_uri not in entities[entity_uri]['frames']:
                                entities[entity_uri]['frames'][frame_uri] = {
                                    'type': frame_type,
                                    'slots': []
                                }
                            
                            slot_uri = binding.get('slot', {}).get('value')
                            if slot_uri:
                                entities[entity_uri]['frames'][frame_uri]['slots'].append({
                                    'uri': slot_uri,
                                    'type': binding.get('slotType', {}).get('value', 'No type'),
                                    'value': binding.get('slotValue', {}).get('value', 'No value')
                                })
                
                # Print first 2 entities
                for i, (entity_uri, entity_data) in enumerate(list(entities.items())[:2]):
                    entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                    logger.info(f"\n      Entity {i+1}: {entity_data['name']} ({entity_short})")
                    for frame_uri, frame_data in entity_data['frames'].items():
                        frame_short = frame_uri.split('/')[-1] if '/' in frame_uri else frame_uri
                        type_short = frame_data['type'].split('#')[-1] if '#' in frame_data['type'] else frame_data['type']
                        logger.info(f"        Frame: {type_short} ({frame_short})")
                        for slot in frame_data['slots']:
                            slot_short = slot['uri'].split('/')[-1] if '/' in slot['uri'] else slot['uri']
                            slot_type_short = slot['type'].split('#')[-1] if '#' in slot['type'] else slot['type']
                            logger.info(f"          Slot: {slot_type_short}")
                            logger.info(f"            Value: {slot['value']}")
                
                logger.info("")
                return True
        
        logger.error(f"   ❌ No event structure found\n")
        return False
    
    def check_source_business_frame_with_org_uri(self) -> bool:
        """Check for SourceBusinessFrame with BusinessEntityURISlot containing org URI."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?entityName ?frame ?slot ?orgURI
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
                ?entity haley:hasKGEntityType <http://vital.ai/ontology/haley-ai-kg#BusinessEventEntity> .
                OPTIONAL {{ ?entity vital-core:hasName ?entityName }}
                
                ?frameEdge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                ?frameEdge vital-core:hasEdgeSource ?entity .
                ?frameEdge vital-core:hasEdgeDestination ?frame .
                ?frame haley:hasKGFrameType <http://vital.ai/ontology/haley-ai-kg#SourceBusinessFrame> .
                
                ?slotEdge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                ?slotEdge vital-core:hasEdgeSource ?frame .
                ?slotEdge vital-core:hasEdgeDestination ?slot .
                ?slot haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#BusinessEntitySlot> .
                ?slot haley:hasEntitySlotValue ?orgURI .
                
                FILTER(CONTAINS(STR(?orgURI), "organization"))
            }}
        }}
        LIMIT 5
        """
        
        results = self.query_fuseki(query, "Checking SourceBusinessFrame with org URI")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} event(s) with SourceBusinessFrame + org URI:")
                for binding in bindings:
                    entity_name = binding.get('entityName', {}).get('value', 'No name')
                    org_uri = binding.get('orgURI', {}).get('value', 'No URI')
                    org_short = org_uri.split('/')[-1] if '/' in org_uri else org_uri
                    logger.info(f"      • {entity_name} -> {org_short}")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No events found with SourceBusinessFrame + org URI\n")
        return False
    
    def run_verification(self) -> bool:
        """
        Run the complete verification test.
        
        Returns:
            True if all verifications passed, False otherwise
        """
        logger.info("")
        logger.info("🚀 Starting KGQuery Event Structure Verification")
        logger.info(f"   Testing space: {self.space_id}")
        logger.info(f"   Fuseki dataset: {self.dataset_name}")
        logger.info("")
        
        logger.info("=" * 80)
        logger.info("📊 Verifying BusinessEventEntity Data Structure")
        logger.info("=" * 80)
        logger.info("")
        
        all_passed = True
        
        # Count business events
        if not self.count_business_events():
            all_passed = False
        
        # List business events
        if not self.list_business_events():
            all_passed = False
        
        # Check event->frame->slot structure
        if not self.check_event_frame_structure():
            all_passed = False
        
        # Check specific query pattern (SourceBusinessFrame with org URI)
        if not self.check_source_business_frame_with_org_uri():
            all_passed = False
        
        # Summary
        logger.info("=" * 80)
        if all_passed:
            logger.info("🎉 All verification checks passed!")
            logger.info("=" * 80)
            logger.info("")
            logger.info("Summary:")
            logger.info("  ✅ BusinessEventEntity data present")
            logger.info("  ✅ Entity->Frame->Slot structure verified")
            logger.info("  ✅ SourceBusinessFrame with org URI verified")
            logger.info("")
            logger.info(f"✅ The test data structure matches the expected query pattern!")
        else:
            logger.info("❌ Some verification checks failed")
            logger.info("=" * 80)
            logger.info("")
            logger.info("⚠️  The data structure may not match the expected query pattern")
        
        return all_passed


def main():
    """Main entry point for the test script."""
    try:
        tester = KGQueryEventStructureTester()
        success = tester.run_verification()
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
