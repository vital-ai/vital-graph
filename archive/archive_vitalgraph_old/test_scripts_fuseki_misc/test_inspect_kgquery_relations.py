#!/usr/bin/env python3
"""
Direct Fuseki Query Test for KGQuery Relations Data

This script directly queries the Fuseki instance to inspect the relations
created in the space_kgquery_test space to debug why relation queries return 0 results.
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class KGQueryRelationsInspector:
    """Inspect KGQuery relations data directly in Fuseki."""
    
    def __init__(self):
        """Initialize the inspector by loading configuration from .env file."""
        # Load .env from project root
        project_root = Path(__file__).parent.parent
        env_path = project_root / '.env'
        
        if not env_path.exists():
            raise FileNotFoundError(f"No .env file found at {env_path}")
        
        load_dotenv(env_path)
        logger.info(f"✅ Loaded configuration from {env_path}\n")
        
        # Fuseki configuration
        self.fuseki_url = os.getenv('FUSEKI_URL', 'http://localhost:3030')
        
        # Test space configuration
        self.space_id = "space_kgquery_test"
        self.dataset_name = f"vitalgraph_space_{self.space_id}"
        self.graph_id = "urn:kgquery_test_graph"
        
        logger.info(f"Fuseki URL: {self.fuseki_url}")
        logger.info(f"Dataset: {self.dataset_name}")
        logger.info(f"Graph: {self.graph_id}\n")
    
    def query_fuseki(self, sparql_query: str, query_description: str) -> Optional[Dict[str, Any]]:
        """Execute a SPARQL query against the test dataset in Fuseki."""
        query_url = f"{self.fuseki_url}/{self.dataset_name}/query"
        
        logger.info(f"📊 {query_description}")
        
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
    
    def count_all_triples(self) -> bool:
        """Count all triples in the test graph."""
        query = f"""
        SELECT (COUNT(*) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?s ?p ?o .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting all triples in graph")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Total triples: {count}\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No triples found\n")
        return False
    
    def count_relations_rdf_type(self) -> bool:
        """Count relations using RDF type (a haley:Edge_hasKGRelation)."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        
        SELECT (COUNT(?rel) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?rel a haley:Edge_hasKGRelation .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting relations using RDF type (a haley:Edge_hasKGRelation)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} relation(s) using RDF type\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No relations found using RDF type\n")
        return False
    
    def count_relations_vitaltype(self) -> bool:
        """Count relations using vitaltype property."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?rel) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?rel vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting relations using vitaltype property")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} relation(s) using vitaltype\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No relations found using vitaltype\n")
        return False
    
    def list_relation_properties(self) -> bool:
        """List all properties of relation objects to see what's actually stored."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?rel ?p ?o
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?rel vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
                ?rel ?p ?o .
            }}
        }}
        LIMIT 50
        """
        
        results = self.query_fuseki(query, "Listing relation properties (first 50 triples)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} triple(s):")
                
                # Group by relation URI
                relations = {}
                for binding in bindings:
                    rel_uri = binding.get('rel', {}).get('value', 'unknown')
                    prop = binding.get('p', {}).get('value', 'unknown')
                    obj = binding.get('o', {}).get('value', 'unknown')
                    
                    if rel_uri not in relations:
                        relations[rel_uri] = []
                    relations[rel_uri].append((prop, obj))
                
                # Print first 3 relations
                for i, (rel_uri, props) in enumerate(list(relations.items())[:3], 1):
                    rel_short = rel_uri.split('/')[-1] if '/' in rel_uri else rel_uri
                    logger.info(f"\n      Relation {i}: {rel_short}")
                    for prop, obj in props[:10]:  # First 10 properties
                        prop_short = prop.split('#')[-1] if '#' in prop else prop.split('/')[-1]
                        obj_short = obj.split('#')[-1] if '#' in obj else (obj.split('/')[-1] if '/' in obj else obj)
                        if len(obj_short) > 60:
                            obj_short = obj_short[:60] + "..."
                        logger.info(f"         {prop_short}: {obj_short}")
                
                logger.info("")
                return True
        
        logger.error(f"   ❌ No relation properties found\n")
        return False
    
    def test_kgquery_sparql(self) -> bool:
        """Test the exact SPARQL query that KGQueries uses."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        
        SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?source_entity vital:vitaltype ?source_vitaltype .
                ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
                ?relation_edge vital:hasEdgeSource ?source_entity .
                ?relation_edge vital:hasEdgeDestination ?destination_entity .
                ?relation_edge haley:hasKGRelationType ?relation_type .
                VALUES ?relation_type {{ <http://vital.ai/test/kgtype/MakesProductRelation> }}
                ?destination_entity vital:vitaltype ?dest_vitaltype .
                FILTER(?source_entity != ?destination_entity)
            }}
        }}
        ORDER BY ?source_entity ?destination_entity
        """
        
        results = self.query_fuseki(query, "Testing exact KGQuery SPARQL (MakesProductRelation)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            count = len(bindings)
            logger.info(f"   ✅ Found {count} result(s)")
            
            if bindings:
                for i, binding in enumerate(bindings[:5], 1):  # Show first 5
                    source = binding.get('source_entity', {}).get('value', 'N/A')
                    dest = binding.get('destination_entity', {}).get('value', 'N/A')
                    rel_type = binding.get('relation_type', {}).get('value', 'N/A')
                    
                    source_short = source.split('/')[-1] if '/' in source else source
                    dest_short = dest.split('/')[-1] if '/' in dest else dest
                    type_short = rel_type.split('/')[-1] if '/' in rel_type else rel_type
                    
                    logger.info(f"      {i}. {source_short} → {dest_short} ({type_short})")
            
            logger.info("")
            return count > 0
        
        logger.error(f"   ❌ Query returned no results\n")
        return False
    
    def check_entity_frames(self) -> bool:
        """Check what frames are attached to entities."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?entity ?entity_name ?frame ?frame_type
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital:vitaltype haley:KGEntity .
                OPTIONAL {{ ?entity vital:hasName ?entity_name }}
                
                ?frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                ?frame_edge vital:hasEdgeSource ?entity .
                ?frame_edge vital:hasEdgeDestination ?frame .
                
                OPTIONAL {{ ?frame haley:hasKGFrameType ?frame_type }}
            }}
        }}
        LIMIT 20
        """
        
        results = self.query_fuseki(query, "Checking entity frames")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            logger.info(f"   ✅ Found {len(bindings)} entity-frame connections:")
            
            for i, binding in enumerate(bindings[:10], 1):
                entity_name = binding.get('entity_name', {}).get('value', 'N/A')
                frame_type = binding.get('frame_type', {}).get('value', 'N/A')
                frame_type_short = frame_type.split('#')[-1] if '#' in frame_type else frame_type
                
                logger.info(f"      {i}. {entity_name} → {frame_type_short}")
            
            logger.info("")
            return len(bindings) > 0
        
        logger.error(f"   ❌ No entity frames found\n")
        return False
    
    def check_frame_slots(self) -> bool:
        """Check what slots exist in frames."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?frame ?frame_type ?slot ?slot_type ?slot_value
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?frame vital:vitaltype haley:KGFrame .
                OPTIONAL {{ ?frame haley:hasKGFrameType ?frame_type }}
                
                ?slot_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                ?slot_edge vital:hasEdgeSource ?frame .
                ?slot_edge vital:hasEdgeDestination ?slot .
                
                OPTIONAL {{ ?slot haley:hasKGSlotType ?slot_type }}
                OPTIONAL {{ ?slot haley:hasTextSlotValue ?slot_value }}
            }}
        }}
        LIMIT 20
        """
        
        results = self.query_fuseki(query, "Checking frame slots")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            logger.info(f"   ✅ Found {len(bindings)} frame-slot connections:")
            
            for i, binding in enumerate(bindings[:10], 1):
                frame_type = binding.get('frame_type', {}).get('value', 'N/A')
                slot_type = binding.get('slot_type', {}).get('value', 'N/A')
                slot_value = binding.get('slot_value', {}).get('value', 'N/A')
                
                frame_type_short = frame_type.split('#')[-1] if '#' in frame_type else frame_type
                slot_type_short = slot_type.split('#')[-1] if '#' in slot_type else slot_type
                
                logger.info(f"      {i}. {frame_type_short} → {slot_type_short}: {slot_value}")
            
            logger.info("")
            return len(bindings) > 0
        
        logger.error(f"   ❌ No frame slots found\n")
        return False
    
    def test_phase6_query_with_frames(self) -> bool:
        """Test Phase 6 query with frame/slot filtering."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
        WHERE {{
            GRAPH <{self.graph_id}> {{
                # Base relation patterns
                ?source_entity vital:vitaltype ?source_vitaltype .
                ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
                ?relation_edge vital:hasEdgeSource ?source_entity .
                ?relation_edge vital:hasEdgeDestination ?destination_entity .
                ?relation_edge haley:hasKGRelationType ?relation_type .
                VALUES ?relation_type {{ <http://vital.ai/test/kgtype/MakesProductRelation> }}
                ?destination_entity vital:vitaltype ?dest_vitaltype .
                
                # Source entity frame filtering
                ?source_frame_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
                ?source_frame_edge vital:hasEdgeSource ?source_entity .
                ?source_frame_edge vital:hasEdgeDestination ?source_frame .
                ?source_frame haley:hasKGFrameType <http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame> .
                
                # Source entity slot filtering
                ?source_slot_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                ?source_slot_edge vital:hasEdgeSource ?source_frame .
                ?source_slot_edge vital:hasEdgeDestination ?source_slot .
                ?source_slot haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#IndustrySlot> .
                ?source_slot haley:hasTextSlotValue ?source_industry_value .
                FILTER(?source_industry_value = 'Technology')
                
                FILTER(?source_entity != ?destination_entity)
            }}
        }}
        ORDER BY ?source_entity ?destination_entity
        """
        
        results = self.query_fuseki(query, "Testing Phase 6 query with frame/slot filtering")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            count = len(bindings)
            logger.info(f"   ✅ Found {count} result(s) with frame filtering")
            
            if bindings:
                for i, binding in enumerate(bindings[:5], 1):
                    source = binding.get('source_entity', {}).get('value', 'N/A')
                    dest = binding.get('destination_entity', {}).get('value', 'N/A')
                    
                    source_short = source.split('/')[-1] if '/' in source else source
                    dest_short = dest.split('/')[-1] if '/' in dest else dest
                    
                    logger.info(f"      {i}. {source_short} → {dest_short}")
            
            logger.info("")
            return count > 0
        
        logger.error(f"   ❌ Query with frame filtering returned no results\n")
        return False
    
    def run_inspection(self) -> bool:
        """Run the complete inspection."""
        logger.info("")
        logger.info("🔍 Starting KGQuery Relations Data Inspection")
        logger.info("=" * 80)
        logger.info("")
        
        all_passed = True
        
        # Count all triples
        if not self.count_all_triples():
            all_passed = False
        
        # Count relations using RDF type
        if not self.count_relations_rdf_type():
            all_passed = False
        
        # Count relations using vitaltype
        if not self.count_relations_vitaltype():
            all_passed = False
        
        # List relation properties
        if not self.list_relation_properties():
            all_passed = False
        
        # Test KGQuery SPARQL
        if not self.test_kgquery_sparql():
            all_passed = False
        
        # NEW: Check entity frames
        logger.info("=" * 80)
        logger.info("Phase 6: Checking Frame/Slot Data")
        logger.info("=" * 80)
        logger.info("")
        
        if not self.check_entity_frames():
            all_passed = False
        
        # NEW: Check frame slots
        if not self.check_frame_slots():
            all_passed = False
        
        # NEW: Test Phase 6 query with frames
        if not self.test_phase6_query_with_frames():
            all_passed = False
        
        # Summary
        logger.info("=" * 80)
        if all_passed:
            logger.info("🎉 All inspection checks passed!")
            logger.info("   Relations are properly stored and queryable")
            logger.info("   Frame/slot filtering is working correctly")
        else:
            logger.info("❌ Some inspection checks failed")
            logger.info("   Check the output above to see what's missing")
        logger.info("=" * 80)
        
        return all_passed


def main():
    """Main entry point for the inspection script."""
    try:
        inspector = KGQueryRelationsInspector()
        success = inspector.run_inspection()
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Inspection failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
