#!/usr/bin/env python3
"""
Quad Storage Test Script

This script tests the storage of KGEntity properties as quads in the pyoxigraph store
to determine if all properties are being correctly stored and can be retrieved.
"""

import logging
from datetime import datetime
import pyoxigraph as px

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def test_quad_storage():
    """Test KGEntity property storage as quads in pyoxigraph store."""
    
    print("=" * 80)
    print("Quad Storage Test for KGEntity Properties")
    print("=" * 80)
    
    try:
        # Initialize VitalSigns and create KGEntity
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from vital_ai_vitalsigns.model.GraphObject import GraphObject
        
        vs = VitalSigns()
        
        print("\n1. Creating KGEntity with all test properties...")
        
        # Create KGEntity with all properties (same as in mock client test)
        entity = KGEntity()
        entity.URI = "http://vital.ai/haley.ai/app/KGEntity/test_entity_01"
        entity.name = "Alice Johnson"
        entity.kGraphDescription = "A knowledge graph entity representing a person"
        entity.kGIdentifier = "urn:entity_alice_johnson"
        entity.kGEntityType = "urn:PersonEntity"
        entity.kGEntityTypeDescription = "Person Entity"
        entity.kGIndexDateTime = datetime.now().isoformat()
        entity.kGGraphAssertionDateTime = datetime.now().isoformat()
        entity.kGNodeCacheDateTime = datetime.now().isoformat()
        entity.certainty = 0.94
        entity.pageRank = 0.81
        
        print(f"✅ Created entity with URI: {entity.URI}")
        
        print(f"\n2. Properties set on entity (via JSON serialization):")
        
        # Use JSON serialization to show all properties that were actually set
        import json
        entity_json = entity.to_json()
        entity_dict = json.loads(entity_json)
        
        print(f"Total properties in JSON: {len(entity_dict)}")
        
        # Show all properties from JSON
        for key, value in entity_dict.items():
            if key == 'URI':
                print(f"   ✅ {key}: {value}")
            elif key.startswith('http://'):
                # Extract short name from URI
                short_name = key.split('#')[-1] if '#' in key else key.split('/')[-1]
                print(f"   ✅ {short_name} ({key}): {value}")
            else:
                print(f"   ✅ {key}: {value}")
        
        # Extract properties for later comparison
        properties_set = list(entity_dict.keys())
        
        print(f"\n3. Converting KGEntity to RDF/Quads...")
        
        # Convert to RDF using VitalSigns
        from vital_ai_vitalsigns.model.utils.graphobject_rdf_utils import GraphObjectRdfUtils
        
        # Get RDF representation
        rdf_string = GraphObjectRdfUtils.to_rdf_impl(entity, format='ntriples')
        print(f"✅ RDF conversion successful")
        print(f"RDF length: {len(rdf_string)} characters")
        
        # Show first few lines of RDF
        rdf_lines = rdf_string.strip().split('\n')
        print(f"\nFirst 10 RDF triples:")
        for i, line in enumerate(rdf_lines[:10]):
            print(f"   {i+1:2d}: {line}")
        if len(rdf_lines) > 10:
            print(f"   ... and {len(rdf_lines) - 10} more triples")
        
        print(f"\n4. Creating MockSpace and adding graph...")
        
        # Import and create MockSpace
        import sys
        sys.path.append('/Users/hadfield/Local/vital-git/vital-graph')
        from vitalgraph.mock.client.space.mock_space import MockSpace
        
        # Create MockSpace (this will create the pyoxigraph store internally)
        mock_space = MockSpace(space_id=1, name="test_space")
        print(f"✅ Created MockSpace")
        
        # Add a graph to the MockSpace
        graph_uri = "http://example.org/test_graph"
        mock_graph = mock_space.add_graph(graph_uri, name="test_graph")
        print(f"✅ Added graph: {graph_uri}")
        
        print(f"\n5. Using MockSpace interface like the mock client does...")
        
        # Convert entity to triples using VitalSigns method (same as mock client)
        triples = entity.to_triples()
        print(f"✅ Converted entity to {len(triples)} triples using VitalSigns")
        
        # Show first few triples
        print(f"\nFirst 5 triples:")
        for i, (s, p, o) in enumerate(triples[:5]):
            print(f"   {i+1}: {s} {p} {o}")
        if len(triples) > 5:
            print(f"   ... and {len(triples) - 5} more triples")
        
        # Convert triples to quads with graph_id (same as mock client does)
        quads_to_add = []
        for s, p, o in triples:
            # Clean URIs (same as mock client)
            clean_s = str(s).strip('<>')
            clean_p = str(p).strip('<>')
            clean_o = str(o).strip('<>')
            
            # Determine object type using VitalSigns URI validation
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            
            if validate_rfc3986(clean_o, rule='URI'):
                # It's a valid URI
                object_type = "uri"
            else:
                # It's a literal
                object_type = "literal"
            
            quad_dict = {
                'subject': clean_s,
                'predicate': clean_p,
                'object': clean_o,  # MockSpace expects 'object', not 'object_value'
                'object_type': object_type,
                'graph_id': mock_graph.graph_id
            }
            quads_to_add.append(quad_dict)
        
        print(f"✅ Converted to {len(quads_to_add)} quads for storage")
        
        # Debug: Show first few quads
        print(f"\nFirst 3 quads to add:")
        for i, quad in enumerate(quads_to_add[:3]):
            print(f"   {i+1}: {quad}")
        
        # Use MockSpace's add_quads_batch method (same as mock client)
        batch_result = mock_space.add_quads_batch(quads_to_add)
        print(f"✅ Added quads using MockSpace batch interface")
        print(f"Batch result: {batch_result}")
        
        print(f"\n6. Querying MockSpace for all quads using API...")
        
        # Use MockSpace API to query all quads
        all_quads_result = mock_space.query_quads_pattern()
        print(f"✅ Found {len(all_quads_result)} quads using MockSpace API")
        
        # Group quads by property URI for analysis
        property_quads = {}
        subject_uri = None
        
        for quad_dict in all_quads_result:
            subject = quad_dict.get('subject', '')
            predicate = quad_dict.get('predicate', '')
            object_val = quad_dict.get('object_value', quad_dict.get('object', ''))
            graph = quad_dict.get('graph_id', 'default')
            
            if subject_uri is None:
                subject_uri = subject
            
            if predicate not in property_quads:
                property_quads[predicate] = []
            property_quads[predicate].append({
                'subject': subject,
                'object': object_val,
                'graph': graph
            })
        
        print(f"\n6. Analysis of stored properties:")
        print(f"Subject URI: {subject_uri}")
        print(f"Properties found: {len(property_quads)}")
        
        # Check for our specific properties
        expected_properties = {
            'http://vital.ai/ontology/vital-core#hasName': 'name',
            'http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription': 'kGraphDescription',
            'http://vital.ai/ontology/haley-ai-kg#hasKGIdentifier': 'kGIdentifier',
            'http://vital.ai/ontology/haley-ai-kg#hasKGEntityType': 'kGEntityType',
            'http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription': 'kGEntityTypeDescription',
            'http://vital.ai/ontology/haley-ai-kg#hasKGIndexDateTime': 'kGIndexDateTime',
            'http://vital.ai/ontology/haley-ai-kg#hasKGGraphAssertionDateTime': 'kGGraphAssertionDateTime',
            'http://vital.ai/ontology/haley-ai-kg#hasKGNodeCacheDateTime': 'kGNodeCacheDateTime',
            'http://vital.ai/ontology/vital#hasCertainty': 'certainty',
            'http://vital.ai/ontology/vital#hasPageRank': 'pageRank'
        }
        
        print(f"\n7. Checking for expected properties in store:")
        found_properties = 0
        missing_properties = []
        
        for uri, prop_name in expected_properties.items():
            if uri in property_quads:
                quads = property_quads[uri]
                print(f"   ✅ {prop_name} ({uri})")
                for quad in quads:
                    print(f"      Object: {quad['object']}")
                found_properties += 1
            else:
                print(f"   ❌ {prop_name} ({uri}) - NOT FOUND")
                missing_properties.append(prop_name)
        
        print(f"\n8. Storage Summary:")
        print(f"   Total quads stored: {len(all_quads_result)}")
        print(f"   Expected properties: {len(expected_properties)}")
        print(f"   Found properties: {found_properties}")
        print(f"   Missing properties: {len(missing_properties)}")
        
        if missing_properties:
            print(f"   Missing: {', '.join(missing_properties)}")
        
        print(f"\n9. All properties found in store:")
        for predicate, quads in property_quads.items():
            # Get short name for readability
            short_name = predicate.split('#')[-1] if '#' in predicate else predicate.split('/')[-1]
            print(f"   {short_name}: {predicate}")
            for quad in quads:
                print(f"      → {quad['object']}")
        
        print(f"\n10. Testing retrieval by reconstructing entity...")
        
        # Try to reconstruct the entity from the stored quads
        try:
            # Convert back to RDF string
            reconstructed_rdf = ""
            for quad_dict in all_quads_result:
                subject = f"<{quad_dict.get('subject', '')}>"
                predicate = f"<{quad_dict.get('predicate', '')}>"
                obj_val = quad_dict.get('object_value', quad_dict.get('object', ''))
                
                # Handle object formatting - simplified since we don't have pyoxigraph objects here
                if quad_dict.get('object_type') == 'uri':
                    # URI
                    object_val = f"<{obj_val}>"
                else:
                    # Simple literal (we don't have type info from the query result)
                    object_val = f'"{obj_val}"'
                
                reconstructed_rdf += f"{subject} {predicate} {object_val} .\n"
            
            print(f"✅ Reconstructed RDF from quads ({len(reconstructed_rdf)} chars)")
            
            # Try to create entity from reconstructed RDF
            reconstructed_entity = GraphObjectRdfUtils.from_rdf_impl(KGEntity, reconstructed_rdf)
            print(f"✅ Successfully reconstructed KGEntity from stored quads")
            print(f"   Reconstructed URI: {reconstructed_entity.URI}")
            
            # Compare properties
            print(f"\n11. Comparing original vs reconstructed properties:")
            for prop in properties_set:
                try:
                    orig_val = getattr(entity, prop, None)
                    recon_val = getattr(reconstructed_entity, prop, None)
                    if orig_val == recon_val:
                        print(f"   ✅ {prop}: {orig_val}")
                    else:
                        print(f"   ❌ {prop}: Original='{orig_val}' vs Reconstructed='{recon_val}'")
                except Exception as e:
                    print(f"   ❌ {prop}: Error comparing - {e}")
            
        except Exception as e:
            print(f"❌ Failed to reconstruct entity from quads: {e}")
            import traceback
            traceback.print_exc()
        
        print("\n" + "=" * 80)
        print("Quad Storage Test Completed!")
        print("=" * 80)
        
        # Return summary
        return {
            'total_quads': len(all_quads_result),
            'expected_properties': len(expected_properties),
            'found_properties': found_properties,
            'missing_properties': missing_properties,
            'success': len(missing_properties) == 0
        }
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}

if __name__ == "__main__":
    result = test_quad_storage()
    if result.get('success'):
        print(f"\n🎉 SUCCESS: All {result['found_properties']} properties stored and retrieved correctly!")
    else:
        print(f"\n❌ FAILURE: {len(result.get('missing_properties', []))} properties missing from storage")
