"""
Graph utilities for analyzing and visualizing VitalSigns graph object structures.

This module provides functionality to:
1. Analyze VitalSigns graph objects to determine if they form a DAG (Directed Acyclic Graph)
2. Sort graph objects into a topological DAG structure
3. Pretty print DAG structures for visualization and testing
4. Compare DAG structures for equality verification

Used primarily for testing KGEntity graphs with frames, slots, and connecting edges.
"""

from typing import List, Dict, Set, Tuple, Any, Optional
from collections import defaultdict, deque
import logging

# VitalSigns imports
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

logger = logging.getLogger(__name__)


class DAGNode:
    """Represents a node in the DAG structure with metadata."""
    
    def __init__(self, graph_object: GraphObject, level: int = 0):
        self.graph_object = graph_object
        self.uri = str(graph_object.URI)
        self.level = level
        self.children: List['DAGNode'] = []
        self.parents: List['DAGNode'] = []
        self.object_type = type(graph_object).__name__
        
    def add_child(self, child: 'DAGNode'):
        """Add a child node."""
        if child not in self.children:
            self.children.append(child)
        if self not in child.parents:
            child.parents.append(self)
    
    def __str__(self):
        return f"DAGNode({self.object_type}: {self.uri})"
    
    def __repr__(self):
        return self.__str__()


class DAGStructure:
    """Represents a complete DAG structure with nodes organized by levels."""
    
    def __init__(self):
        self.nodes: Dict[str, DAGNode] = {}
        self.levels: Dict[int, List[DAGNode]] = defaultdict(list)
        self.root_nodes: List[DAGNode] = []
        self.leaf_nodes: List[DAGNode] = []
        self.max_level = 0
        
    def add_node(self, node: DAGNode):
        """Add a node to the DAG structure."""
        self.nodes[node.uri] = node
        self.levels[node.level].append(node)
        self.max_level = max(self.max_level, node.level)
        
        # Update root and leaf node lists
        if not node.parents:
            if node not in self.root_nodes:
                self.root_nodes.append(node)
        elif node in self.root_nodes:
            self.root_nodes.remove(node)
            
        if not node.children:
            if node not in self.leaf_nodes:
                self.leaf_nodes.append(node)
        elif node in self.leaf_nodes:
            self.leaf_nodes.remove(node)
    
    def get_node_count(self) -> int:
        """Get total number of nodes in the DAG."""
        return len(self.nodes)
    
    def get_edge_count(self) -> int:
        """Get total number of edges in the DAG."""
        return sum(len(node.children) for node in self.nodes.values())


def extract_edges_from_objects(graph_objects: List[GraphObject]) -> List[Tuple[str, str, GraphObject]]:
    """
    Extract edge relationships from VitalSigns graph objects.
    
    Args:
        graph_objects: List of VitalSigns graph objects
        
    Returns:
        List of tuples (source_uri, destination_uri, edge_object)
    """
    edges = []
    
    for obj in graph_objects:
        if isinstance(obj, VITAL_Edge):
            # Check for different edge property patterns
            source_uri = None
            dest_uri = None
            
            # Try different property names for source
            for prop in ['hasEdgeSource', 'edgeSource', 'source']:
                if hasattr(obj, prop):
                    source_uri = str(getattr(obj, prop))
                    break
            
            # Try different property names for destination
            for prop in ['hasEdgeDestination', 'edgeDestination', 'destination']:
                if hasattr(obj, prop):
                    dest_uri = str(getattr(obj, prop))
                    break
            
            if source_uri and dest_uri:
                edges.append((source_uri, dest_uri, obj))
                logger.debug(f"Found edge: {source_uri} -> {dest_uri} ({type(obj).__name__})")
    
    return edges


def build_adjacency_graph(graph_objects: List[GraphObject]) -> Tuple[Dict[str, GraphObject], Dict[str, List[str]], Dict[str, int]]:
    """
    Build adjacency representation from VitalSigns graph objects.
    
    Args:
        graph_objects: List of VitalSigns graph objects
        
    Returns:
        Tuple of (uri_to_object_map, adjacency_list, in_degree_count)
    """
    # Create URI to object mapping
    uri_to_object = {}
    for obj in graph_objects:
        uri_to_object[str(obj.URI)] = obj
    
    # Build adjacency list and in-degree count
    adjacency = defaultdict(list)
    in_degree = defaultdict(int)
    
    # Initialize in-degree for all nodes
    for uri in uri_to_object.keys():
        in_degree[uri] = 0
    
    # Extract edges and build graph
    edges = extract_edges_from_objects(graph_objects)
    
    for source_uri, dest_uri, edge_obj in edges:
        if source_uri in uri_to_object and dest_uri in uri_to_object:
            adjacency[source_uri].append(dest_uri)
            in_degree[dest_uri] += 1
    
    return uri_to_object, dict(adjacency), dict(in_degree)


def is_dag(graph_objects: List[GraphObject]) -> bool:
    """
    Check if the graph objects form a Directed Acyclic Graph (DAG).
    
    Args:
        graph_objects: List of VitalSigns graph objects
        
    Returns:
        True if the objects form a DAG, False otherwise
    """
    try:
        uri_to_object, adjacency, in_degree = build_adjacency_graph(graph_objects)
        
        # Kahn's algorithm for cycle detection
        queue = deque([uri for uri, degree in in_degree.items() if degree == 0])
        processed_count = 0
        
        while queue:
            current_uri = queue.popleft()
            processed_count += 1
            
            for neighbor_uri in adjacency.get(current_uri, []):
                in_degree[neighbor_uri] -= 1
                if in_degree[neighbor_uri] == 0:
                    queue.append(neighbor_uri)
        
        # If we processed all nodes, it's a DAG
        return processed_count == len(uri_to_object)
        
    except Exception as e:
        logger.error(f"Error checking if graph is DAG: {e}")
        return False


def sort_objects_into_dag(graph_objects: List[GraphObject]) -> DAGStructure:
    """
    Sort VitalSigns graph objects into a DAG structure with topological ordering.
    
    Args:
        graph_objects: List of VitalSigns graph objects
        
    Returns:
        DAGStructure containing the organized nodes
        
    Raises:
        ValueError: If the objects do not form a DAG
    """
    if not is_dag(graph_objects):
        raise ValueError("Graph objects do not form a DAG - contains cycles")
    
    uri_to_object, adjacency, in_degree = build_adjacency_graph(graph_objects)
    
    # Separate edge objects from non-edge objects
    from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
    edges = extract_edges_from_objects(graph_objects)
    edge_objects = {str(edge_obj.URI): edge_obj for _, _, edge_obj in edges}
    
    # Create mapping of edge source to edge objects
    source_to_edges = defaultdict(list)
    for source_uri, dest_uri, edge_obj in edges:
        source_to_edges[source_uri].append(edge_obj)
    
    # Topological sort with level assignment (only for non-edge objects)
    dag_structure = DAGStructure()
    uri_to_node = {}
    
    # Create nodes for non-edge objects only
    for uri, obj in uri_to_object.items():
        if not isinstance(obj, VITAL_Edge):
            node = DAGNode(obj)
            uri_to_node[uri] = node
    
    # Kahn's algorithm with level tracking (only for non-edge objects)
    queue = deque([(uri, 0) for uri, degree in in_degree.items() 
                   if degree == 0 and not isinstance(uri_to_object[uri], VITAL_Edge)])
    
    while queue:
        current_uri, level = queue.popleft()
        current_node = uri_to_node[current_uri]
        current_node.level = level
        
        # Add the main node to DAG structure first
        dag_structure.add_node(current_node)
        
        # Then add associated edge objects to this node at the same level
        for edge_obj in source_to_edges.get(current_uri, []):
            edge_node = DAGNode(edge_obj)
            edge_node.level = level
            uri_to_node[str(edge_obj.URI)] = edge_node
            dag_structure.add_node(edge_node)
        
        # Process children (only non-edge objects)
        for neighbor_uri in adjacency.get(current_uri, []):
            if neighbor_uri in uri_to_node:  # Only process non-edge objects
                neighbor_node = uri_to_node[neighbor_uri]
                current_node.add_child(neighbor_node)
                
                in_degree[neighbor_uri] -= 1
                if in_degree[neighbor_uri] == 0:
                    queue.append((neighbor_uri, level + 1))
    
    logger.info(f"Created DAG structure with {dag_structure.get_node_count()} nodes and {dag_structure.get_edge_count()} edges")
    return dag_structure


def pretty_print_dag(dag_structure: DAGStructure, show_properties: bool = False, max_property_length: int = 50) -> str:
    """
    Pretty print a DAG structure as a tree hierarchy.
    
    Args:
        dag_structure: The DAG structure to print
        show_properties: Whether to show object properties
        max_property_length: Maximum length for property values
        
    Returns:
        Formatted string representation of the DAG as a tree
    """
    from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
    
    output = []
    output.append("=" * 80)
    output.append("ENTITY GRAPH TREE STRUCTURE")
    output.append("=" * 80)
    output.append(f"Total Nodes: {dag_structure.get_node_count()}")
    output.append(f"Total Edges: {dag_structure.get_edge_count()}")
    output.append(f"Max Depth: {dag_structure.max_level}")
    output.append("-" * 80)
    output.append("")
    
    # Find root entities (Level 0 non-edge objects)
    root_entities = []
    for node in dag_structure.levels.get(0, []):
        if not isinstance(node.graph_object, VITAL_Edge):
            root_entities.append(node)
    
    # Print each entity tree
    for entity_node in root_entities:
        _print_node_tree(entity_node, output, 0, show_properties, max_property_length, dag_structure)
        output.append("")
    
    # Add relationship summary
    output.append("RELATIONSHIP SUMMARY:")
    output.append("-" * 40)
    
    # Count relationships by type
    relationships = defaultdict(int)
    for level_nodes in dag_structure.levels.values():
        for node in level_nodes:
            if node.children:
                parent_type = type(node.graph_object).__name__
                for child in node.children:
                    child_type = type(child.graph_object).__name__
                    relationships[f"{parent_type} → {child_type}"] += 1
    
    for relationship, count in sorted(relationships.items()):
        output.append(f"  {relationship}: {count}")
    
    output.append("=" * 80)
    
    return "\n".join(output)


def _print_node_tree(node: DAGNode, output: list, indent_level: int, show_properties: bool, max_property_length: int, dag_structure: DAGStructure):
    """
    Recursively print a node and its children as a tree structure.
    
    Args:
        node: The node to print
        output: List to append output lines to
        indent_level: Current indentation level
        show_properties: Whether to show object properties
        max_property_length: Maximum length for property values
        dag_structure: The DAG structure for finding associated edges
    """
    from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
    
    indent = "  " * indent_level
    obj = node.graph_object
    obj_type = type(obj).__name__
    
    # Print the main node
    output.append(f"{indent}📦 {obj_type}")
    
    # Show URI
    if hasattr(obj, 'URI'):
        output.append(f"{indent}   URI: {obj.URI}")
    
    # Show properties if requested
    if show_properties:
        if hasattr(obj, 'name') and obj.name:
            output.append(f"{indent}   Name: {obj.name}")
        
        # Show slot values for slot objects
        if 'Slot' in obj_type:
            # Map slot type to its value property
            slot_type_to_property = {
                'KGAudioSlot': 'audioSlotValue',
                'KGBooleanSlot': 'booleanSlotValue',
                'KGChoiceOptionSlot': 'choiceSlotOptionValues',
                'KGChoiceSlot': 'choiceSlotValue',
                'KGCodeSlot': 'codeSlotValue',
                'KGCurrencySlot': 'currencySlotValue',
                'KGDateSlot': 'dateSlotValue',
                'KGDateTimeSlot': 'dateTimeSlotValue',
                'KGDoubleSlot': 'doubleSlotValue',
                'KGEntitySlot': 'entitySlotValue',
                'KGFileUploadSlot': 'fileUploadSlotValue',
                'KGGeoLocationSlot': 'geoLocationSlotValue',
                'KGImageSlot': 'imageSlotValue',
                'KGIntegerSlot': 'integerSlotValue',
                'KGJsonSlot': 'jsonSlotValue',
                'KGLongSlot': 'longSlotValue',
                'KGLongTextSlot': 'longTextSlotValue',
                'KGMultiChoiceSlot': 'multiChoiceSlotValues',
                'KGMultiChoiceOptionSlot': 'multiChoiceSlotValues',
                'KGMultiTaxonomySlot': 'multiTaxonomySlotValues',
                'KGPropertyNameSlot': 'kGPropertyNameSlotValue',
                'KGPropertySlot': 'propertyFrameTypeSlotValue',
                'KGTaxonomySlot': 'taxonomySlotValue',
                'KGTextSlot': 'textSlotValue',
                'KGEntitySlot': 'entitySlotValue',
                'KGURISlot': 'uRISlotValue',
                'KGVideoSlot': 'videoSlotValue'
            }
            
            # Get the correct property for this slot type
            value_property = slot_type_to_property.get(obj_type)
            if value_property and hasattr(obj, value_property):
                value = getattr(obj, value_property)
                if value is not None:
                    if isinstance(value, list):
                        output.append(f"{indent}   Multi-value property with {len(value)} items:")
                        for v in value:
                            output.append(f"{indent}     - {v}")
                    else:
                        output.append(f"{indent}   Single-value property: {value}")
    
    # Find and print associated edges from this node
    node_uri = str(obj.URI)
    edges_from_node = []
    
    # Look through all levels for edges that have this node as source
    for level_nodes in dag_structure.levels.values():
        for level_node in level_nodes:
            if isinstance(level_node.graph_object, VITAL_Edge):
                edge_obj = level_node.graph_object
                # Check if this edge originates from current node
                source_uri = None
                for prop in ['hasEdgeSource', 'edgeSource', 'source']:
                    if hasattr(edge_obj, prop):
                        source_uri = str(getattr(edge_obj, prop))
                        break
                
                if source_uri == node_uri:
                    edges_from_node.append(level_node)
    
    # Print edges from this node
    for edge_node in edges_from_node:
        edge_obj = edge_node.graph_object
        edge_type = type(edge_obj).__name__
        output.append(f"{indent}  ├─ {edge_type}")
        if hasattr(edge_obj, 'URI'):
            output.append(f"{indent}     URI: {edge_obj.URI}")
    
    # Recursively print children (non-edge objects only)
    non_edge_children = [child for child in node.children if not isinstance(child.graph_object, VITAL_Edge)]
    for i, child in enumerate(non_edge_children):
        if i == len(non_edge_children) - 1:
            output.append(f"{indent}  └─")
        else:
            output.append(f"{indent}  ├─")
        _print_node_tree(child, output, indent_level + 1, show_properties, max_property_length, dag_structure)


def compare_dag_structures(dag1: DAGStructure, dag2: DAGStructure) -> Dict[str, Any]:
    """
    Compare two DAG structures for equality and differences.
    
    Args:
        dag1: First DAG structure
        dag2: Second DAG structure
        
    Returns:
        Dictionary containing comparison results
    """
    result = {
        'equal': True,
        'differences': [],
        'dag1_stats': {
            'node_count': dag1.get_node_count(),
            'edge_count': dag1.get_edge_count(),
            'max_level': dag1.max_level
        },
        'dag2_stats': {
            'node_count': dag2.get_node_count(),
            'edge_count': dag2.get_edge_count(),
            'max_level': dag2.max_level
        }
    }
    
    # Compare basic statistics
    if dag1.get_node_count() != dag2.get_node_count():
        result['equal'] = False
        result['differences'].append(f"Node count differs: {dag1.get_node_count()} vs {dag2.get_node_count()}")
    
    if dag1.get_edge_count() != dag2.get_edge_count():
        result['equal'] = False
        result['differences'].append(f"Edge count differs: {dag1.get_edge_count()} vs {dag2.get_edge_count()}")
    
    # Compare node URIs
    uris1 = set(dag1.nodes.keys())
    uris2 = set(dag2.nodes.keys())
    
    missing_in_dag2 = uris1 - uris2
    missing_in_dag1 = uris2 - uris1
    
    if missing_in_dag2:
        result['equal'] = False
        result['differences'].append(f"URIs in DAG1 but not DAG2: {missing_in_dag2}")
    
    if missing_in_dag1:
        result['equal'] = False
        result['differences'].append(f"URIs in DAG2 but not DAG1: {missing_in_dag1}")
    
    # Compare relationships for common nodes
    common_uris = uris1 & uris2
    for uri in common_uris:
        node1 = dag1.nodes[uri]
        node2 = dag2.nodes[uri]
        
        children1 = set(child.uri for child in node1.children)
        children2 = set(child.uri for child in node2.children)
        
        if children1 != children2:
            result['equal'] = False
            result['differences'].append(f"Different children for {uri}: {children1} vs {children2}")
    
    return result
