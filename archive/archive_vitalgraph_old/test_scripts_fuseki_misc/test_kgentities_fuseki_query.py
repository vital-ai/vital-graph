#!/usr/bin/env python3
"""
Direct Fuseki Query Test for KGEntities Test Data

This script directly queries the Fuseki instance to inspect
the data created by test_kgentities_endpoint.py.

It queries the space_client_kgentities_test dataset to verify:
1. Entity data is present
2. Entity properties (especially hasName vs rdfs:label)
3. Frame data is present
4. Slot data is present
5. All relationships are intact
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class KGEntitiesFusekiQueryTester:
    """Test direct Fuseki queries for KGEntities test data."""
    
    def __init__(self):
        """Initialize the tester by loading configuration from .env file."""
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
        self.space_id = "space_client_kgentities_test"
        self.dataset_name = f"vitalgraph_space_{self.space_id}"
        self.graph_id = "urn:test_kgentities"
        
        logger.info(f"📊 Configuration:")
        logger.info(f"   Fuseki URL: {self.fuseki_url}")
        logger.info(f"   Space ID: {self.space_id}")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}\n")
    
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
    
    def count_entities(self) -> bool:
        """Count KGEntity objects in the graph."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT (COUNT(?entity) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Counting KGEntity objects")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings and 'count' in bindings[0]:
                count = bindings[0]['count']['value']
                logger.info(f"   ✅ Found {count} KGEntity object(s)\n")
                return int(count) > 0
        
        logger.error(f"   ❌ No entities found\n")
        return False
    
    def list_entities_with_properties(self) -> bool:
        """List all entities with their name properties (both hasName and rdfs:label)."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT ?entity ?hasName ?label ?entityType
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
                OPTIONAL {{ ?entity vital-core:hasName ?hasName }}
                OPTIONAL {{ ?entity rdfs:label ?label }}
                OPTIONAL {{ ?entity haley:kGEntityType ?entityType }}
            }}
        }}
        ORDER BY ?entity
        """
        
        results = self.query_fuseki(query, "Listing entities with name properties")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} entity/entities:")
                for binding in bindings:
                    entity_uri = binding.get('entity', {}).get('value', 'unknown')
                    has_name = binding.get('hasName', {}).get('value', None)
                    label = binding.get('label', {}).get('value', None)
                    entity_type = binding.get('entityType', {}).get('value', 'N/A')
                    
                    entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                    type_short = entity_type.split('#')[-1] if '#' in entity_type else entity_type
                    
                    logger.info(f"      • URI: {entity_short}")
                    logger.info(f"        Type: {type_short}")
                    logger.info(f"        vital-core:hasName: {has_name if has_name else '❌ NOT SET'}")
                    logger.info(f"        rdfs:label: {label if label else '❌ NOT SET'}")
                    logger.info("")
                return True
        
        logger.error(f"   ❌ No entities found\n")
        return False
    
    def check_name_property_usage(self) -> bool:
        """Check which name property is being used (hasName vs rdfs:label)."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT 
            (COUNT(?hasName) as ?hasNameCount)
            (COUNT(?label) as ?labelCount)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?entity vital-core:vitaltype haley:KGEntity .
                OPTIONAL {{ ?entity vital-core:hasName ?hasName }}
                OPTIONAL {{ ?entity rdfs:label ?label }}
            }}
        }}
        """
        
        results = self.query_fuseki(query, "Checking name property usage")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                has_name_count = int(bindings[0].get('hasNameCount', {}).get('value', 0))
                label_count = int(bindings[0].get('labelCount', {}).get('value', 0))
                
                logger.info(f"   📊 Name property usage:")
                logger.info(f"      vital-core:hasName: {has_name_count} entities")
                logger.info(f"      rdfs:label: {label_count} entities")
                
                if has_name_count > 0 and label_count == 0:
                    logger.info(f"   ✅ Using vital-core:hasName (correct)")
                elif label_count > 0 and has_name_count == 0:
                    logger.info(f"   ⚠️  Using rdfs:label instead of vital-core:hasName")
                elif has_name_count > 0 and label_count > 0:
                    logger.info(f"   ℹ️  Using BOTH properties")
                else:
                    logger.info(f"   ❌ No name properties found")
                
                logger.info("")
                return True
        
        logger.error(f"   ❌ Could not check name property usage\n")
        return False
    
    def test_filter_query(self) -> bool:
        """Test the filter query that's failing in the tests."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?entity WHERE {{
            GRAPH <{self.graph_id}> {{
                {{
                    ?entity vital-core:vitaltype haley:KGEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley:KGNewsEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley:KGProductEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley:KGWebEntity .
                }}
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?filter_value_0 .
                FILTER(CONTAINS(LCASE(STR(?filter_value_0)), LCASE("Test")))
            }}
        }}
        ORDER BY ?entity
        LIMIT 5
        """
        
        results = self.query_fuseki(query, "Testing filter query (vital-core:hasName)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            logger.info(f"   📊 Filter query returned {len(bindings)} result(s)")
            
            if bindings:
                logger.info(f"   ✅ Found entities:")
                for binding in bindings:
                    entity_uri = binding.get('entity', {}).get('value', 'unknown')
                    entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                    logger.info(f"      • {entity_short}")
            else:
                logger.info(f"   ⚠️  No entities found with vital-core:hasName containing 'Test'")
            
            logger.info("")
            return len(bindings) > 0
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def test_label_filter_query(self) -> bool:
        """Test filter query using rdfs:label instead."""
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        
        SELECT DISTINCT ?entity WHERE {{
            GRAPH <{self.graph_id}> {{
                {{
                    ?entity vital-core:vitaltype haley:KGEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley:KGNewsEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley:KGProductEntity .
                }} UNION {{
                    ?entity vital-core:vitaltype haley:KGWebEntity .
                }}
                ?entity rdfs:label ?filter_value_0 .
                FILTER(CONTAINS(LCASE(STR(?filter_value_0)), LCASE("Test")))
            }}
        }}
        ORDER BY ?entity
        LIMIT 5
        """
        
        results = self.query_fuseki(query, "Testing filter query (rdfs:label)")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            logger.info(f"   📊 Filter query returned {len(bindings)} result(s)")
            
            if bindings:
                logger.info(f"   ✅ Found entities:")
                for binding in bindings:
                    entity_uri = binding.get('entity', {}).get('value', 'unknown')
                    entity_short = entity_uri.split('/')[-1] if '/' in entity_uri else entity_uri
                    logger.info(f"      • {entity_short}")
            else:
                logger.info(f"   ⚠️  No entities found with rdfs:label containing 'Test'")
            
            logger.info("")
            return len(bindings) > 0
        
        logger.error(f"   ❌ Query failed\n")
        return False
    
    def list_all_vitaltypes(self) -> bool:
        """List all vital-core:vitaltype values in the graph."""
        query = f"""
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT DISTINCT ?vitaltype (COUNT(?s) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?s vital-core:vitaltype ?vitaltype .
            }}
        }}
        GROUP BY ?vitaltype
        ORDER BY DESC(?count)
        """
        
        results = self.query_fuseki(query, "Listing all vital-core:vitaltype values")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} distinct vitaltype(s):")
                for binding in bindings:
                    type_uri = binding.get('vitaltype', {}).get('value', 'unknown')
                    count = binding.get('count', {}).get('value', '0')
                    type_short = type_uri.split('#')[-1] if '#' in type_uri else type_uri
                    logger.info(f"      • {type_short}: {count} instances")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No vitaltypes found\n")
        return False
    
    def list_all_types(self) -> bool:
        """List all rdf:type values in the graph."""
        query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        
        SELECT DISTINCT ?type (COUNT(?s) as ?count)
        WHERE {{
            GRAPH <{self.graph_id}> {{
                ?s rdf:type ?type .
            }}
        }}
        GROUP BY ?type
        ORDER BY DESC(?count)
        """
        
        results = self.query_fuseki(query, "Listing all rdf:type values")
        
        if results and 'results' in results and 'bindings' in results['results']:
            bindings = results['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} distinct type(s):")
                for binding in bindings:
                    type_uri = binding.get('type', {}).get('value', 'unknown')
                    count = binding.get('count', {}).get('value', '0')
                    type_short = type_uri.split('#')[-1] if '#' in type_uri else type_uri
                    logger.info(f"      • {type_short}: {count} instances")
                logger.info("")
                return True
        
        logger.error(f"   ❌ No types found\n")
        return False
    
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
    
    def check_kggraphuri_references(self) -> bool:
        """Check for kgGraphURI properties referencing deleted entities."""
        logger.info("📊 Checking for kgGraphURI references to deleted entities")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}")
        
        # Specific entity we're looking for
        test_org_uri = "http://vital.ai/test/kgentity/organization/test_organization"
        
        # Query to find all objects with hasKGGraphURI property
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?subject ?type ?kgGraphURI WHERE {{
            GRAPH <{self.graph_id}> {{
                ?subject haley:hasKGGraphURI ?kgGraphURI .
                ?subject vital-core:vitaltype ?type .
            }}
        }}
        """
        
        result = self.query_fuseki(query, "Find hasKGGraphURI properties")
        
        if result and 'results' in result and 'bindings' in result['results']:
            bindings = result['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} object(s) with kgGraphURI property")
                
                # Check which ones reference the deleted test_organization
                test_org_refs = []
                for binding in bindings:
                    subject_uri = binding.get('subject', {}).get('value', 'N/A')
                    obj_type = binding.get('type', {}).get('value', 'N/A')
                    kg_graph_uri = binding.get('kgGraphURI', {}).get('value', 'N/A')
                    
                    if kg_graph_uri == test_org_uri:
                        test_org_refs.append({
                            'subject': subject_uri,
                            'type': obj_type
                        })
                
                if test_org_refs:
                    logger.info(f"   ❌ Found {len(test_org_refs)} object(s) with kgGraphURI referencing DELETED entity:")
                    logger.info(f"      Deleted entity: {test_org_uri}")
                    for ref in test_org_refs[:10]:  # Show first 10
                        type_name = ref['type'].split('#')[-1] if '#' in ref['type'] else ref['type']
                        logger.info(f"      • {type_name}: {ref['subject']}")
                else:
                    logger.info(f"   ✅ No objects reference the deleted test_organization entity")
                    
                # Show what entities ARE being referenced
                logger.info(f"\n   📊 All hasKGGraphURI values found:")
                entity_refs = {}
                for binding in bindings:
                    kg_graph_uri = binding.get('kgGraphURI', {}).get('value', 'N/A')
                    if kg_graph_uri not in entity_refs:
                        entity_refs[kg_graph_uri] = 0
                    entity_refs[kg_graph_uri] += 1
                
                for entity_uri, count in sorted(entity_refs.items(), key=lambda x: x[1], reverse=True):
                    logger.info(f"      • {entity_uri}: {count} objects")
                
                return True
            else:
                logger.info(f"   ✅ No objects with kgGraphURI property found")
                return True
        else:
            logger.error(f"   ❌ Query failed\n")
            return False
    
    def check_orphaned_frames(self) -> bool:
        """Check if there are orphaned frames/edges referencing deleted entities."""
        logger.info("📊 Checking for orphaned frames and edges")
        logger.info(f"   Dataset: {self.dataset_name}")
        logger.info(f"   Graph: {self.graph_id}")
        
        # Query to find all Edge_hasEntityKGFrame edges and what entities they reference
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
        
        SELECT ?edge ?entity ?frame WHERE {{
            GRAPH <{self.graph_id}> {{
                ?edge a haley:Edge_hasEntityKGFrame .
                ?edge vital-core:hasEdgeSource ?entity .
                ?edge vital-core:hasEdgeDestination ?frame .
            }}
        }}
        """
        
        result = self.query_fuseki(query, "Find Edge_hasEntityKGFrame edges")
        
        if result and 'results' in result and 'bindings' in result['results']:
            bindings = result['results']['bindings']
            if bindings:
                logger.info(f"   ✅ Found {len(bindings)} Edge_hasEntityKGFrame edge(s)")
                
                # Check if the referenced entities still exist
                for binding in bindings[:5]:  # Show first 5
                    edge_uri = binding.get('edge', {}).get('value', 'N/A')
                    entity_uri = binding.get('entity', {}).get('value', 'N/A')
                    frame_uri = binding.get('frame', {}).get('value', 'N/A')
                    
                    # Check if entity exists
                    entity_exists_query = f"""
                    PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
                    
                    ASK {{
                        GRAPH <{self.graph_id}> {{
                            <{entity_uri}> vital-core:vitaltype haley:KGEntity .
                        }}
                    }}
                    """
                    
                    entity_result = self.query_fuseki(entity_exists_query, "Check if entity exists")
                    entity_exists = entity_result.get('boolean', False) if entity_result else False
                    
                    status = "✅ EXISTS" if entity_exists else "❌ DELETED (ORPHANED)"
                    logger.info(f"      • Edge references entity: {entity_uri}")
                    logger.info(f"        Entity status: {status}")
                    logger.info(f"        Frame: {frame_uri}")
                
                return True
            else:
                logger.info(f"   ✅ No Edge_hasEntityKGFrame edges found")
                return True
        else:
            logger.error(f"   ❌ Query failed\n")
            return False
    
    def run_inspection(self) -> bool:
        """
        Run the complete inspection.
        
        Returns:
            True if data is present, False otherwise
        """
        logger.info("")
        logger.info("🔍 Starting KGEntities Test Data Inspection")
        logger.info(f"   Inspecting space: {self.space_id}")
        logger.info(f"   Fuseki dataset: {self.dataset_name}")
        logger.info("")
        
        logger.info("=" * 80)
        logger.info("📊 Data Inspection")
        logger.info("=" * 80)
        logger.info("")
        
        all_passed = True
        
        # Count triples
        if not self.count_all_triples():
            all_passed = False
        
        # List all types
        if not self.list_all_types():
            all_passed = False
        
        # List all vitaltypes
        if not self.list_all_vitaltypes():
            all_passed = False
        
        # Count entities
        if not self.count_entities():
            all_passed = False
        
        # Check name property usage
        if not self.check_name_property_usage():
            all_passed = False
        
        # List entities with properties
        if not self.list_entities_with_properties():
            all_passed = False
        
        # Check for kgGraphURI references
        logger.info("")
        if not self.check_kggraphuri_references():
            all_passed = False
        
        # Check for orphaned frames
        logger.info("")
        if not self.check_orphaned_frames():
            all_passed = False
        
        # Test filter queries
        logger.info("=" * 80)
        logger.info("🧪 Testing Filter Queries")
        logger.info("=" * 80)
        logger.info("")
        
        hasname_works = self.test_filter_query()
        label_works = self.test_label_filter_query()
        
        # Summary
        logger.info("=" * 80)
        logger.info("📋 Summary")
        logger.info("=" * 80)
        logger.info("")
        
        if hasname_works and not label_works:
            logger.info("✅ Entities use vital-core:hasName (correct)")
            logger.info("   Filter queries should work with 'name' property")
        elif label_works and not hasname_works:
            logger.info("⚠️  Entities use rdfs:label instead of vital-core:hasName")
            logger.info("   This is why filter queries are failing!")
            logger.info("   The query builder needs to search rdfs:label as fallback")
        elif hasname_works and label_works:
            logger.info("ℹ️  Entities have BOTH vital-core:hasName and rdfs:label")
            logger.info("   Filter queries should work")
        else:
            logger.info("❌ Entities have neither vital-core:hasName nor rdfs:label")
            logger.info("   This is a serious data issue")
        
        logger.info("")
        return all_passed


def main():
    """Main entry point for the inspection script."""
    try:
        tester = KGEntitiesFusekiQueryTester()
        success = tester.run_inspection()
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"❌ Inspection failed with exception: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
