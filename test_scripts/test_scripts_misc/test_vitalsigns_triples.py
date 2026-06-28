#!/usr/bin/env python3

import json
import sys
import os
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vital_ai_vitalsigns.vitalsigns import VitalSigns
from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
from rdflib import Graph, Dataset


def test_triples_generation():
    """Test triples generation from GraphObject."""
    print("=" * 60)
    print("Testing Triples Generation")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create a test VITAL_Node object
    node = VITAL_Node()
    node.URI = "http://example.com/test-node-1"
    node.name = "Test Node 1"
    
    print(f"Created VITAL_Node:")
    print(f"  URI: {node.URI}")
    print(f"  Name: {node.name}")
    print(f"  Class: {node.get_class_uri()}")
    
    # Test add_to_list (triples to list)
    try:
        triple_list = []
        node.add_to_list(triple_list)
        print(f"\n✅ add_to_list() successful!")
        print(f"Generated {len(triple_list)} triples:")
        for i, triple in enumerate(triple_list[:5]):  # Show first 5 triples
            print(f"  {i+1}. {triple}")
        if len(triple_list) > 5:
            print(f"  ... and {len(triple_list) - 5} more triples")
            
    except Exception as e:
        print(f"\n❌ add_to_list() failed: {e}")
        import traceback
        traceback.print_exc()


def test_triples_to_dataset():
    """Test adding triples to RDF dataset."""
    print("\n" + "=" * 60)
    print("Testing Triples to Dataset")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create multiple test objects
    nodes = []
    for i in range(3):
        node = VITAL_Node()
        node.URI = f"http://example.com/test-node-{i+1}"
        node.name = f"Test Node {i+1}"
        nodes.append(node)
    
    print(f"Created {len(nodes)} VITAL_Node objects:")
    for node in nodes:
        print(f"  - URI: {node.URI}, Name: {node.name}")
    
    # Test add_to_dataset
    try:
        dataset = Dataset()
        graph_uri = "http://example.com/test-graph"
        
        for node in nodes:
            node.add_to_dataset(dataset, graph_uri)
        
        print(f"\n✅ add_to_dataset() successful!")
        print(f"Dataset contains {len(dataset)} graphs")
        
        # Check the specific graph
        graph = dataset.graph(graph_uri)
        print(f"Test graph contains {len(graph)} triples")
        
        # Show some triples from the graph
        triples = list(graph)
        for i, triple in enumerate(triples[:5]):  # Show first 5 triples
            print(f"  {i+1}. {triple}")
        if len(triples) > 5:
            print(f"  ... and {len(triples) - 5} more triples")
            
    except Exception as e:
        print(f"\n❌ add_to_dataset() failed: {e}")
        import traceback
        traceback.print_exc()


def test_from_triples():
    """Test creating GraphObject from triples."""
    print("\n" + "=" * 60)
    print("Testing From Triples Conversion")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create a test node to generate triples
    original_node = VITAL_Node()
    original_node.URI = "http://example.com/original-node"
    original_node.name = "Original Node"
    
    print(f"Original Node:")
    print(f"  URI: {original_node.URI}")
    print(f"  Name: {original_node.name}")
    
    # Generate triples
    try:
        triple_list = []
        original_node.add_to_list(triple_list)
        
        # Convert list to generator (as expected by from_triples)
        def triple_generator():
            for triple in triple_list:
                yield triple
        
        print(f"\nGenerated {len(triple_list)} triples from original node")
        
        # Test from_triples
        try:
            reconstructed_node = VITAL_Node.from_triples(triple_generator())
            print(f"\n✅ from_triples() successful!")
            print(f"Reconstructed Node:")
            print(f"  URI: {reconstructed_node.URI}")
            print(f"  Name: {reconstructed_node.name}")
            print(f"  Class: {reconstructed_node.get_class_uri()}")
            
            # Verify round-trip
            if (original_node.URI == reconstructed_node.URI and 
                original_node.name == reconstructed_node.name and
                original_node.get_class_uri() == reconstructed_node.get_class_uri()):
                print(f"\n✅ Round-trip conversion successful!")
            else:
                print(f"\n❌ Round-trip conversion failed - data mismatch")
                
        except Exception as e:
            print(f"\n❌ from_triples() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ Triple generation failed: {e}")


def test_from_triples_list():
    """Test creating multiple GraphObjects from triples."""
    print("\n" + "=" * 60)
    print("Testing From Triples List Conversion")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create multiple test nodes
    original_nodes = []
    for i in range(2):
        node = VITAL_Node()
        node.URI = f"http://example.com/list-node-{i+1}"
        node.name = f"List Node {i+1}"
        original_nodes.append(node)
    
    print(f"Original Nodes:")
    for node in original_nodes:
        print(f"  - URI: {node.URI}, Name: {node.name}")
    
    # Generate combined triples
    try:
        all_triples = []
        for node in original_nodes:
            triple_list = []
            node.add_to_list(triple_list)
            all_triples.extend(triple_list)
        
        # Convert to generator
        def triples_generator():
            for triple in all_triples:
                yield triple
        
        print(f"\nGenerated {len(all_triples)} total triples from {len(original_nodes)} nodes")
        
        # Test from_triples_list
        try:
            reconstructed_nodes = VITAL_Node.from_triples_list(triples_generator())
            print(f"\n✅ from_triples_list() successful!")
            print(f"Reconstructed {len(reconstructed_nodes)} nodes:")
            for node in reconstructed_nodes:
                print(f"  - URI: {node.URI}, Name: {node.name}")
            
            # Verify count
            if len(original_nodes) == len(reconstructed_nodes):
                print(f"\n✅ Node count matches!")
            else:
                print(f"\n❌ Node count mismatch: {len(original_nodes)} vs {len(reconstructed_nodes)}")
                
        except Exception as e:
            print(f"\n❌ from_triples_list() failed: {e}")
            import traceback
            traceback.print_exc()
            
    except Exception as e:
        print(f"\n❌ Combined triples generation failed: {e}")


def test_json_triples_conversion():
    """Test JSON object to triples conversion."""
    print("\n" + "=" * 60)
    print("Testing JSON Object to Triples Conversion")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create test JSON object (this would typically come from external source)
    json_triples_str = """{
        "URI": "http://example.com/json-node",
        "type": "http://vital.ai/ontology/vital-core#VITAL_Node",
        "http://vital.ai/ontology/vital-core#hasName": "JSON Test Node"
    }"""
    
    print(f"Test JSON object:")
    print(json_triples_str)
    
    # Test from_json_triples
    try:
        triples_list = VITAL_Node.from_json_triples(json_triples_str)
        print(f"\n✅ from_json_triples() successful!")
        print(f"Parsed {len(triples_list)} triples:")
        for i, triple in enumerate(triples_list):
            print(f"  {i+1}. {triple}")
            
    except Exception as e:
        print(f"\n❌ from_json_triples() failed: {e}")
        import traceback
        traceback.print_exc()


def test_vitalsigns_triples_methods():
    """Test triples methods through VitalSigns interface."""
    print("\n" + "=" * 60)
    print("Testing VitalSigns Triples Methods")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create a test node to generate triples
    node = VITAL_Node()
    node.URI = "http://example.com/vs-triples-node"
    node.name = "VitalSigns Triples Node"
    
    print(f"Test Node:")
    print(f"  URI: {node.URI}")
    print(f"  Name: {node.name}")
    
    # Generate triples
    try:
        triple_list = []
        node.add_to_list(triple_list)
        
        def triple_generator():
            for triple in triple_list:
                yield triple
        
        print(f"\nGenerated {len(triple_list)} triples")
        
        # Test VitalSigns from_triples
        try:
            reconstructed_node = vs.from_triples(triple_generator())
            print(f"\n✅ VitalSigns.from_triples() successful!")
            print(f"Reconstructed Node:")
            print(f"  URI: {reconstructed_node.URI}")
            print(f"  Name: {reconstructed_node.name}")
            
            # Test VitalSigns from_triples_list
            try:
                def triple_generator2():
                    for triple in triple_list:
                        yield triple
                
                node_list = vs.from_triples_list(triple_generator2())
                print(f"\n✅ VitalSigns.from_triples_list() successful!")
                print(f"Created {len(node_list)} nodes from triples")
                
            except Exception as e:
                print(f"\n❌ VitalSigns.from_triples_list() failed: {e}")
                
        except Exception as e:
            print(f"\n❌ VitalSigns.from_triples() failed: {e}")
            import traceback
            traceback.print_exc()
    except Exception as e:
        print(f"\n❌ to_triples() failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Test to_triples_list method - COMMENTED OUT UNTIL IMPLEMENTATION IS FIXED
    # try:
    #     node2 = VITAL_Node()
    #     node2.URI = "http://example.com/to-triples-test-node-2"
    #     node2.name = "To Triples Test Node 2"
    #     
    #     node_list = [node, node2]
    #     all_triples = VITAL_Node.to_triples_list(node_list)
    #     
    #     print(f"\n✅ to_triples_list() successful!")
    #     print(f"Generated {len(all_triples)} total triples from {len(node_list)} objects")
    #     print(f"Average {len(all_triples) // len(node_list)} triples per object")
    #     
    # except Exception as e:
    #     print(f"\n❌ to_triples_list() failed: {e}")
    #     import traceback
    #     traceback.print_exc()
    #     return
    
    # Compare with add_to_list - COMMENTED OUT UNTIL to_triples() IS IMPLEMENTED
    try:
        manual_triples = []
        node.add_to_list(manual_triples)
        
        print(f"\n✅ Comparison with add_to_list():")
        print(f"add_to_list() generated: {len(manual_triples)} triples")
        # print(f"to_triples() generated: {len(triples)} triples")  # Commented out until to_triples() works
        
        # if len(manual_triples) == len(triples):
        #     print("✅ Triple counts match!")
        # else:
        #     print("❌ Triple counts differ!")
            
    except Exception as e:
        print(f"\n❌ Comparison failed: {e}")
        import traceback
        traceback.print_exc()


def test_to_triples_methods():
    """Test the new to_triples and to_triples_list methods."""
    print("\n" + "=" * 60)
    print("Testing to_triples and to_triples_list Methods")
    print("=" * 60)
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Create a test node
    node = VITAL_Node()
    node.URI = "http://example.com/to-triples-test-node"
    node.name = "To Triples Test Node"
    
    print(f"Created test node:")
    print(f"  URI: {node.URI}")
    print(f"  Name: {node.name}")
    
    # Test to_triples method
    try:
        triples = node.to_triples()
        print(f"\n✅ to_triples() successful!")
        print(f"Generated {len(triples)} triples:")
        for i, triple in enumerate(triples):
            print(f"  {i+1}. {triple}")
    except Exception as e:
        print(f"\n❌ to_triples() failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Test to_triples_list method
    try:
        node2 = VITAL_Node()
        node2.URI = "http://example.com/to-triples-test-node-2"
        node2.name = "To Triples Test Node 2"
        
        node_list = [node, node2]
        all_triples = VITAL_Node.to_triples_list(node_list)
        
        print(f"\n✅ to_triples_list() successful!")
        print(f"Generated {len(all_triples)} total triples from {len(node_list)} objects")
        print(f"Average {len(all_triples) // len(node_list)} triples per object")
        
    except Exception as e:
        print(f"\n❌ to_triples_list() failed: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Compare with add_to_list
    try:
        manual_triples = []
        node.add_to_list(manual_triples)
        
        print(f"\n✅ Comparison with add_to_list():")
        print(f"add_to_list() generated: {len(manual_triples)} triples")
        print(f"to_triples() generated: {len(triples)} triples")
        
        if len(manual_triples) == len(triples):
            print("✅ Triple counts match!")
            
            # Check if contents match
            manual_set = set(manual_triples)
            triples_set = set(triples)
            
            if manual_set == triples_set:
                print("✅ Triple contents match perfectly!")
            else:
                print("❌ Triple contents differ!")
        else:
            print("❌ Triple counts differ!")
            
    except Exception as e:
        print(f"\n❌ Comparison failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all triples tests."""
    print("Triples Functionality Test Suite")
    print("Using vital-core ontology only")
    
    test_triples_generation()
    test_triples_to_dataset()
    test_from_triples()
    test_from_triples_list()
    test_json_triples_conversion()
    test_vitalsigns_triples_methods()
    test_to_triples_methods()
    
    print("\n" + "=" * 60)
    print("✅ All triples tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
