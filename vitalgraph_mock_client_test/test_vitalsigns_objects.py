#!/usr/bin/env python3
"""VitalSigns Objects Test Script

Test script demonstrating the mock client with real VitalSigns objects:
- KGFrame, KGEntity, KGEntitySlot
- Edge_hasKGSlot connections
- Object instantiation, storage, and retrieval
- JSON-LD and RDF triple conversion
- Complete CRUD lifecycle testing
"""

import sys
import logging
from pathlib import Path
from urllib.parse import urlparse

# Add the parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.client_factory import create_vitalgraph_client
from vitalgraph.client.config.client_config_loader import VitalGraphClientConfig
from vitalgraph.model.spaces_model import Space
from vitalgraph.model.sparql_model import SPARQLQueryRequest
from vitalgraph.model.jsonld_model import JsonLdDocument

# Import real VitalSigns objects
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot
from ai_haley_kg_domain.model.KGFrame import KGFrame
from vital_ai_vitalsigns.utils.uri_generator import URIGenerator
from vital_ai_vitalsigns.vitalsigns import VitalSigns

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
        'client': {
            'use_mock_client': True,
            'timeout': 30,
            'max_retries': 3,
            'retry_delay': 1,
            'mock': {
                'filePath': '/Users/hadfield/Local/vital-git/vital-graph/minioFiles'  # MinIO base path
            }
        },
        'auth': {
            'username': 'admin',
            'password': 'admin'
        }
    }
    config.config_path = "<programmatically created for VitalSigns test>"
    
    return config

def create_test_objects():
    """Create a set of test objects following the VitalSigns pattern."""
    objects = []
    # Create source KGEntity (representing a WordNet concept)
    source_kgentity = KGEntity()
    source_kgentity.URI = "http://vital.ai/haley.ai/app/KGEntity/dog_n_01"
    source_kgentity.name = "dog"
    source_kgentity.kGraphDescription = "a domesticated carnivorous mammal"
    source_kgentity.kGIdentifier = "urn:wordnet_dog.n.01"
    source_kgentity.kGEntityType = "urn:Noun"
    source_kgentity.kGEntityTypeDescription = "Noun"
    objects.append(source_kgentity)
    
    # Create destination KGEntity
    destination_kgentity = KGEntity()
    destination_kgentity.URI = "http://vital.ai/haley.ai/app/KGEntity/animal_n_01"
    destination_kgentity.name = "animal"
    destination_kgentity.kGraphDescription = "a living organism characterized by voluntary movement"
    destination_kgentity.kGIdentifier = "urn:wordnet_animal.n.01"
    destination_kgentity.kGEntityType = "urn:Noun"
    destination_kgentity.kGEntityTypeDescription = "Noun"
    objects.append(destination_kgentity)
    
    # Create KGFrame (representing the relationship)
    kgframe = KGFrame()
    kgframe.URI = "http://vital.ai/haley.ai/app/KGFrame/hypernym_relation_001"
    kgframe.kGFrameType = "urn:Hypernym"
    kgframe.kGFrameTypeDescription = "Hypernym relationship"
    objects.append(kgframe)
    
    # Create source entity slot
    source_slot = KGEntitySlot()
    source_slot.URI = URIGenerator.generate_uri()
    source_slot.kGSlotType = "urn:hasSourceEntity"
    source_slot.kGSlotTypeDescription = "hasSourceEntity"
    source_slot.entitySlotValue = source_kgentity.URI
    objects.append(source_slot)
    
    # Create destination entity slot
    destination_slot = KGEntitySlot()
    destination_slot.URI = URIGenerator.generate_uri()
    destination_slot.kGSlotType = "urn:hasDestinationEntity"
    destination_slot.kGSlotTypeDescription = "hasDestinationEntity"
    destination_slot.entitySlotValue = destination_kgentity.URI
    objects.append(destination_slot)
    
    # Create edge from frame to source slot
    source_slot_edge = Edge_hasKGSlot()
    source_slot_edge.URI = URIGenerator.generate_uri()
    source_slot_edge.edgeSource = kgframe.URI
    source_slot_edge.edgeDestination = source_slot.URI
    objects.append(source_slot_edge)
    
    # Create edge from frame to destination slot
    destination_slot_edge = Edge_hasKGSlot()
    destination_slot_edge.URI = URIGenerator.generate_uri()
    destination_slot_edge.edgeSource = kgframe.URI
    destination_slot_edge.edgeDestination = destination_slot.URI
    objects.append(destination_slot_edge)
    
    return objects


def objects_to_jsonld_document(objects):
    """Convert a list of VitalSigns objects to a JSON-LD document."""
    import json
    graph = []
    for obj in objects:
        # Use the real VitalSigns to_json() method and parse the JSON string
        json_str = obj.to_json()
        vitalsigns_dict = json.loads(json_str)
        
        # Convert VitalSigns format to JSON-LD format
        jsonld_dict = {
            "@id": vitalsigns_dict.get("URI"),
            "@type": vitalsigns_dict.get("type")
        }
        
        # Add all other properties, excluding VitalSigns metadata
        for key, value in vitalsigns_dict.items():
            if key not in ["URI", "type", "types", "http://vital.ai/ontology/vital-core#vitaltype"]:
                jsonld_dict[key] = value
        
        graph.append(jsonld_dict)
    
    return JsonLdDocument(
        context={
            "@vocab": "http://vital.ai/ontology/haley-ai-kg#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        },
        graph=graph
    )


def verify_object_equality(original_obj, retrieved_data):
    """Verify that a retrieved object matches the original."""
    import json
    
    if not retrieved_data:
        return False, "No retrieved data"
    
    # Check URI
    if retrieved_data.get("@id") != str(original_obj.URI):
        return False, f"URI mismatch: {retrieved_data.get('@id')} != {original_obj.URI}"
    
    # Check type
    expected_type = original_obj.get_class_uri()
    retrieved_type = retrieved_data.get("@type")
    if retrieved_type != expected_type:
        return False, f"Type mismatch: {retrieved_type} != {expected_type}"
    
    # For real VitalSigns objects, get all properties from the object
    original_json_str = original_obj.to_json()
    original_vitalsigns = json.loads(original_json_str)
    
    # Check properties from the original VitalSigns JSON representation
    for prop_key, prop_value in original_vitalsigns.items():
        if prop_key not in ["URI", "type", "types", "http://vital.ai/ontology/vital-core#vitaltype"]:
            # Try both full URI and compacted property name
            retrieved_value = retrieved_data.get(prop_key)
            
            # If not found with full URI, try compacted form
            if retrieved_value is None and prop_key.startswith("http://vital.ai/ontology/"):
                # Extract the property name from the URI
                if "#" in prop_key:
                    short_prop = prop_key.split("#")[-1]
                    retrieved_value = retrieved_data.get(short_prop)
            
            # Handle quoted strings from RDF literals
            if retrieved_value and isinstance(retrieved_value, str):
                retrieved_value = retrieved_value.strip('"')
            
            if retrieved_value != str(prop_value):
                return False, f"Property {prop_key} mismatch: {retrieved_value} != {prop_value}"
    
    return True, "Objects match"


def main():
    """Main test function."""
    print("🧠 VitalSigns Objects Mock Client Test")
    print("=" * 50)
    
    vs = VitalSigns()

    # Create mock client with config object
    config = create_mock_config()
    try:
        print("Creating VitalGraph client...")
        client = create_vitalgraph_client(config=config)
        print(f"✅ Created client: {client.__class__.__name__}")
        
        # Connect to client
        client.open()
        print("📡 Connected to mock client")
        
        # Create test space
        print("\n📁 Creating test space...")
        space = Space(
            space="vitalsigns_test_space",
            space_name="VitalSigns Test Space",
            space_description="Test space for VitalSigns objects"
        )
        
        space_response = client.add_space(space)
        print("✅ Created test space")
        
        # Create a named graph
        print("\n📊 Creating named graph...")
        graph_uri = "http://vital.ai/haley.ai/test/vitalsigns_graph"
        print(f"Graph URI: {graph_uri}")
        
        # Create test objects
        print("\n🧠 Creating VitalSigns test objects...")
        test_objects = create_test_objects()
        print(f"Created {len(test_objects)} objects:")
        for obj in test_objects:
            print(f"  - {obj.__class__.__name__}: {obj.URI}")
        
        # Convert objects to JSON-LD document
        print("\n📝 Converting objects to JSON-LD...")
        jsonld_doc = objects_to_jsonld_document(test_objects)
        print(f"Created JSON-LD document with {len(jsonld_doc.graph)} objects")
        
        # Store objects using create_objects
        print("\n💾 Storing objects in VitalGraph...")
        create_response = client.create_objects("vitalsigns_test_space", graph_uri, jsonld_doc)
        print(f"✅ Stored {create_response.created_count} objects")
        
        # Query for all triples in the named graph
        print("\n🔍 Querying all triples...")
        sparql_query = SPARQLQueryRequest(
            query=f"SELECT ?s ?p ?o WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }} LIMIT 50"
        )
        query_results = client.execute_sparql_query("vitalsigns_test_space", sparql_query)
        
        if hasattr(query_results, 'results') and isinstance(query_results.results, dict):
            bindings = query_results.results.get('bindings', [])
            print(f"Found {len(bindings)} triples:")
            for i, binding in enumerate(bindings[:10]):  # Show first 10
                s = binding.get('s', {}).get('value', 'N/A')
                p = binding.get('p', {}).get('value', 'N/A')
                o = binding.get('o', {}).get('value', 'N/A')
                print(f"  {i+1}. {s} -> {p} -> {o}")
            if len(bindings) > 10:
                print(f"  ... and {len(bindings) - 10} more")
        
        # List objects by type
        print("\n📦 Listing objects by type...")
        objects_response = client.list_objects("vitalsigns_test_space", graph_uri, page_size=20)
        print(f"Found {objects_response.total_count} total objects")
        
        if hasattr(objects_response, 'objects') and hasattr(objects_response.objects, 'graph'):
            retrieved_objects = objects_response.objects.graph
            print(f"Retrieved {len(retrieved_objects)} objects in current page:")
            
            # Group by type
            by_type = {}
            for obj in retrieved_objects:
                obj_type = obj.get('@type', 'Unknown')
                if obj_type not in by_type:
                    by_type[obj_type] = []
                by_type[obj_type].append(obj)
            
            for obj_type, objs in by_type.items():
                print(f"  - {obj_type}: {len(objs)} objects")
        
        # Verify object integrity
        print("\n✅ Verifying object integrity...")
        verification_results = []
        
        if hasattr(objects_response, 'objects') and hasattr(objects_response.objects, 'graph'):
            retrieved_objects = objects_response.objects.graph
            
            # Create a map of retrieved objects by URI
            retrieved_by_uri = {obj.get('@id'): obj for obj in retrieved_objects}
            
            # Verify each original object
            for original_obj in test_objects:
                original_uri = str(original_obj.URI)
                retrieved_obj = retrieved_by_uri.get(original_uri)
                
                # Debug: show first retrieved object structure
                if original_obj == test_objects[0] and retrieved_obj:
                    print(f"  Debug - First retrieved object keys: {list(retrieved_obj.keys())}")
                
                is_match, message = verify_object_equality(original_obj, retrieved_obj)
                verification_results.append((original_obj.__class__.__name__, original_uri, is_match, message))
                
                if is_match:
                    print(f"  ✅ {original_obj.__class__.__name__} ({original_uri}): {message}")
                else:
                    print(f"  ❌ {original_obj.__class__.__name__} ({original_uri}): {message}")
        
        # Query specific relationships
        print("\n🔗 Querying specific relationships...")
        
        # Find all KGFrames and their slots (using VitalSigns property names)
        frame_query = SPARQLQueryRequest(
            query=f"""
            SELECT ?frame ?slot WHERE {{
                GRAPH <{graph_uri}> {{
                    ?frame a <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?slot .
                    ?slot a <http://vital.ai/ontology/haley-ai-kg#KGEntitySlot> .
                }}
            }}
            """
        )
        
        frame_results = client.execute_sparql_query("vitalsigns_test_space", frame_query)
        if hasattr(frame_results, 'results') and isinstance(frame_results.results, dict):
            frame_bindings = frame_results.results.get('bindings', [])
            print(f"Found {len(frame_bindings)} frame-slot relationships:")
            for binding in frame_bindings:
                frame = binding.get('frame', {}).get('value', 'N/A')
                slot = binding.get('slot', {}).get('value', 'N/A')
                print(f"  Frame: {frame}")
                print(f"  Slot:  {slot}")
        
        # Test MinIO file operations
        print("\n📁 Testing MinIO File Operations...")
        test_file_path = "/Users/hadfield/Local/vital-git/vital-graph/localTestFiles/2510.04871v1.pdf"
        test_file_uri = "http://vital.ai/test/file/research_paper_001"
        download_path = "/Users/hadfield/Local/vital-git/vital-graph/localTestFiles/downloaded_paper.pdf"
        
        try:
            # Test file upload
            print(f"\n📤 Uploading file: {test_file_path}")
            upload_response = client.upload_file_content(
                space_id="vitalsigns_test_space",
                uri=test_file_uri,
                file_path=test_file_path,
                graph_id=graph_uri
            )
            print(f"✅ Upload successful: {upload_response.message}")
            print(f"   File URI: {upload_response.file_uri}")
            print(f"   File size: {upload_response.file_size} bytes")
            print(f"   Content type: {upload_response.content_type}")
            
            # Test file download
            print(f"\n📥 Downloading file to: {download_path}")
            download_success = client.download_file_content(
                space_id="vitalsigns_test_space",
                uri=test_file_uri,
                output_path=download_path,
                graph_id=graph_uri
            )
            
            if download_success:
                print("✅ Download successful")
                
                # Verify downloaded file
                from pathlib import Path
                original_file = Path(test_file_path)
                downloaded_file = Path(download_path)
                
                if downloaded_file.exists():
                    original_size = original_file.stat().st_size
                    downloaded_size = downloaded_file.stat().st_size
                    print(f"   Original file size: {original_size} bytes")
                    print(f"   Downloaded file size: {downloaded_size} bytes")
                    
                    if original_size == downloaded_size:
                        print("✅ File sizes match - upload/download working correctly!")
                    else:
                        print("❌ File sizes don't match")
                else:
                    print("❌ Downloaded file not found")
            else:
                print("❌ Download failed")
                
        except Exception as e:
            print(f"❌ MinIO test failed: {e}")
        
        # Summary
        print("\n📊 Test Summary:")
        total_objects = len(test_objects)
        successful_verifications = sum(1 for _, _, is_match, _ in verification_results if is_match)
        
        print(f"  - Objects created: {total_objects}")
        print(f"  - Objects stored: {create_response.created_count}")
        print(f"  - Objects retrieved: {objects_response.total_count}")
        print(f"  - Verification success: {successful_verifications}/{total_objects}")
        
        if successful_verifications == total_objects:
            print("🎉 All tests passed! VitalSigns object storage and retrieval working perfectly!")
        else:
            print("⚠️  Some verifications failed. Check the details above.")
        
        # Check MinIO directory structure
        print("\n📂 Checking MinIO directory structure...")
        minio_path = Path("/Users/hadfield/Local/vital-git/vital-graph/minioFiles")
        if minio_path.exists():
            print(f"MinIO base directory: {minio_path}")
            for item in minio_path.rglob("*"):
                if item.is_file():
                    print(f"  📄 {item.relative_to(minio_path)} ({item.stat().st_size} bytes)")
                elif item.is_dir() and item != minio_path:
                    print(f"  📁 {item.relative_to(minio_path)}/")
        
        # Close client
        client.close()
        print("\n✅ Disconnected from client")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise


if __name__ == "__main__":
    main()
