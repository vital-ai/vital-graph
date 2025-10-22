#!/usr/bin/env python3
"""
Simple example of using VitalGraph Mock Client.

This script shows how to use the mock client for development and testing
without needing a running VitalGraph server.
"""

import os
import sys
import logging
from pathlib import Path

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.sparql_model import SPARQLQueryRequest
from vitalgraph.model.kgtypes_model import KGTypeListResponse
from vitalgraph.model.jsonld_model import JsonLdDocument

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def create_mock_config() -> VitalGraphClientConfig:
    """Create a config object with mock client enabled."""
    # Create config object with built-in defaults
    config = VitalGraphClientConfig()
    
    # Override the config data to enable mock client
    config.config_data = {
        'server': {
            'url': 'http://localhost:8001',
            'api_base_path': '/api/v1'
        },
        'auth': {
            'username': 'admin',
            'password': 'admin'
        },
        'client': {
            'timeout': 30,
            'max_retries': 3,
            'retry_delay': 1,
            'use_mock_client': True,  # This enables the mock client
            'mock': {
                'filePath': '/Users/hadfield/Local/vital-git/vital-graph/minioFiles'  # MinIO base path
            }
        }
    }
    config.config_path = "<programmatically created>"
    
    return config


def main():
    """Main example function."""
    print("🤖 VitalGraph Mock Client Example")
    print("=" * 40)
    
    # Create config object with mock enabled
    config = create_mock_config()
    
    try:
        # Create client using factory with config object (will be mock client due to config)
        print("Creating VitalGraph client...")
        client = create_vitalgraph_client(config=config)
        print(f"✅ Created client: {type(client).__name__}")
        
        # Use client as context manager
        with client:
            print("\n📡 Testing connection...")
            print(f"Connected: {client.is_connected()}")
            
            # Get server info
            print("\n🔍 Getting server info...")
            server_info = client.get_server_info()
            print(f"Server: {server_info.get('name', 'Mock Server')}")
            print(f"Version: {server_info.get('version', '1.0.0')}")
            
            # List spaces
            print("\n📁 Listing spaces...")
            spaces = client.list_spaces()
            print(f"Found {spaces.total_count} spaces")
            
            # Create a test space
            print("\n➕ Creating test space...")
            test_space = Space(
                space="example_space",
                space_name="Example Space",
                space_description="An example space for testing"
            )
            create_result = client.add_space(test_space)
            print(f"✅ {create_result.message}")
            
            # Add some test data first
            print("\n📝 Adding test data...")
            
            # Add some KGTypes (ontology classes)
            print("  Adding KGTypes...")
            kgtypes_data = JsonLdDocument(
                context={
                    "@vocab": "http://vital.ai/ontology/haley-ai-kg#",
                    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                },
                graph=[
                    {
                        "@id": "http://vital.ai/ontology/haley-ai-kg#Person",
                        "@type": "http://www.w3.org/2000/01/rdf-schema#Class",
                        "rdfs:label": "Person",
                        "rdfs:comment": "A human being"
                    },
                    {
                        "@id": "http://vital.ai/ontology/haley-ai-kg#Organization",
                        "@type": "http://www.w3.org/2000/01/rdf-schema#Class", 
                        "rdfs:label": "Organization",
                        "rdfs:comment": "A business or institutional entity"
                    }
                ]
            )
            
            try:
                kgtypes_create = client.create_kgtypes("example_space", "http://example.org/default_graph", kgtypes_data)
                print(f"  ✅ Created {kgtypes_create.created_count} KGTypes")
            except Exception as e:
                print(f"  ⚠️  KGTypes creation: {e}")
            
            # Add some objects (instances)
            print("  Adding objects...")
            objects_data = JsonLdDocument(
                context={
                    "@vocab": "http://vital.ai/ontology/haley-ai-kg#",
                    "rdfs": "http://www.w3.org/2000/01/rdf-schema#"
                },
                graph=[
                    {
                        "@id": "http://example.org/person/john",
                        "@type": "http://vital.ai/ontology/haley-ai-kg#Person",
                        "rdfs:label": "John Doe",
                        "http://vital.ai/ontology/haley-ai-kg#hasAge": 30,
                        "http://vital.ai/ontology/haley-ai-kg#hasEmail": "john@example.com"
                    },
                    {
                        "@id": "http://example.org/org/acme",
                        "@type": "http://vital.ai/ontology/haley-ai-kg#Organization",
                        "rdfs:label": "ACME Corp",
                        "http://vital.ai/ontology/haley-ai-kg#hasWebsite": "https://acme.com"
                    }
                ]
            )
            
            try:
                objects_create = client.create_objects("example_space", "http://example.org/default_graph", objects_data)
                print(f"  ✅ Created {objects_create.created_count} objects")
            except Exception as e:
                print(f"  ⚠️  Objects creation: {e}")
            
            # Add some triples directly
            print("  Adding triples...")
            triples_data = JsonLdDocument(
                context={
                    "@vocab": "http://vital.ai/ontology/haley-ai-kg#",
                    "foaf": "http://xmlns.com/foaf/0.1/"
                },
                graph=[
                    {
                        "@id": "http://example.org/person/jane",
                        "@type": "http://xmlns.com/foaf/0.1/Person",
                        "http://xmlns.com/foaf/0.1/name": "Jane Smith",
                        "http://xmlns.com/foaf/0.1/knows": {"@id": "http://example.org/person/john"}
                    }
                ]
            )
            
            try:
                triples_create = client.add_triples("example_space", "http://example.org/default_graph", triples_data)
                print(f"  ✅ Added triples successfully")
            except Exception as e:
                print(f"  ⚠️  Triples creation: {e}")
            
            # Execute SPARQL query to see all triples
            print("\n🔍 Executing SPARQL query...")
            query = SPARQLQueryRequest(
                query="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"
            )
            results = client.execute_sparql_query("example_space", query)
            
            # Also try a specific query for classes
            print("\n🔍 Checking for RDF classes...")
            class_query = SPARQLQueryRequest(
                query="SELECT ?s WHERE { ?s a <http://www.w3.org/2000/01/rdf-schema#Class> }"
            )
            class_results = client.execute_sparql_query("example_space", class_query)
            
            # Check the actual structure of results
            results_count = 0
            if hasattr(results, 'results'):
                if hasattr(results.results, 'bindings'):
                    results_count = len(results.results.bindings) if results.results.bindings else 0
                elif isinstance(results.results, list):
                    results_count = len(results.results)
                elif hasattr(results.results, '__len__'):
                    results_count = len(results.results)
            
            print(f"Query returned {results_count} results")
            
            # Check class query results
            class_count = 0
            if hasattr(class_results, 'results'):
                if hasattr(class_results.results, 'bindings'):
                    class_count = len(class_results.results.bindings) if class_results.results.bindings else 0
                elif isinstance(class_results.results, dict) and 'bindings' in class_results.results:
                    class_count = len(class_results.results['bindings'])
            print(f"Found {class_count} RDF classes")
            
            # Debug: Show what types are actually stored
            print("\n🔍 Checking what types are stored...")
            type_query = SPARQLQueryRequest(
                query="SELECT ?s ?o WHERE { ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?o }"
            )
            type_results = client.execute_sparql_query("example_space", type_query)
            
            # Debug: Print the actual structure of type_results
            print(f"Type results structure: {type(type_results)}")
            if hasattr(type_results, 'results'):
                print(f"  results type: {type(type_results.results)}")
                if isinstance(type_results.results, dict):
                    print(f"  results keys: {list(type_results.results.keys())}")
                    if 'bindings' in type_results.results:
                        print(f"  bindings length: {len(type_results.results['bindings'])}")
                        if type_results.results['bindings']:
                            print(f"  first binding: {type_results.results['bindings'][0]}")
            
            type_count = 0
            if hasattr(type_results, 'results') and isinstance(type_results.results, dict) and 'bindings' in type_results.results:
                type_count = len(type_results.results['bindings'])
                print(f"Found {type_count} type triples:")
                for i, binding in enumerate(type_results.results['bindings'][:5]):
                    subj = binding.get('s', {}).get('value', 'N/A')
                    obj = binding.get('o', {}).get('value', 'N/A')
                    print(f"  {i+1}. {subj} -> {obj}")
            else:
                print("No type triples found")
            
            # Show some results if available
            if hasattr(results, 'results') and results.results:
                print("  Sample results:")
                try:
                    # Handle different result formats
                    if hasattr(results.results, 'bindings') and results.results.bindings:
                        # SPARQL JSON format
                        bindings_list = results.results.bindings[:3]
                        for i, result in enumerate(bindings_list):
                            if isinstance(result, dict):
                                # Format the binding nicely
                                bindings = []
                                for var, value in result.items():
                                    if isinstance(value, dict) and 'value' in value:
                                        bindings.append(f"{var}={value['value']}")
                                    else:
                                        bindings.append(f"{var}={value}")
                                print(f"    {i+1}. {', '.join(bindings)}")
                            else:
                                print(f"    {i+1}. {result}")
                    elif isinstance(results.results, list) and results.results:
                        # Direct list format
                        for i, result in enumerate(results.results[:3]):
                            if isinstance(result, dict):
                                bindings = []
                                for var, value in result.items():
                                    if isinstance(value, dict) and 'value' in value:
                                        bindings.append(f"{var}={value['value']}")
                                    else:
                                        bindings.append(f"{var}={value}")
                                print(f"    {i+1}. {', '.join(bindings)}")
                            else:
                                print(f"    {i+1}. {result}")
                    else:
                        # Handle dict structure directly
                        if isinstance(results.results, dict):
                            if 'bindings' in results.results:
                                bindings_list = results.results['bindings'][:3]
                                for i, result in enumerate(bindings_list):
                                    if isinstance(result, dict):
                                        bindings = []
                                        for var, value in result.items():
                                            if isinstance(value, dict) and 'value' in value:
                                                bindings.append(f"{var}={value['value']}")
                                            else:
                                                bindings.append(f"{var}={value}")
                                        print(f"    {i+1}. {', '.join(bindings)}")
                                    else:
                                        print(f"    {i+1}. {result}")
                            else:
                                print(f"    Results structure: {type(results.results)}")
                                print(f"    Available keys: {list(results.results.keys()) if isinstance(results.results, dict) else 'Not a dict'}")
                        else:
                            print(f"    Results structure: {type(results.results)}")
                            if hasattr(results.results, '__dict__'):
                                print(f"    Available attributes: {list(results.results.__dict__.keys())}")
                        
                except Exception as e:
                    print(f"    Error displaying results: {e}")
                    print(f"    Results type: {type(results.results)}")
            else:
                print("  No results to display")
            
            # List KGTypes
            print("\n🏷️  Listing KGTypes...")
            kgtypes = client.list_kgtypes("example_space", "http://example.org/default_graph")
            print(f"Found {kgtypes.total_count} KGTypes")
            
            # List objects
            print("\n📦 Listing objects...")
            objects = client.list_objects("example_space", "http://example.org/default_graph")
            print(f"Found {objects.total_count} objects")
            
        print(f"\n✅ Disconnected: {not client.is_connected()}")
        print("\n🎉 Mock client example completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
