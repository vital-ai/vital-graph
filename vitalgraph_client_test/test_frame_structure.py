"""
Test script to load a lead entity graph and visualize its frame structure.

This script:
1. Loads one lead N-Triples file
2. Converts to VitalSigns graph objects
3. Uses graph_utils to pretty print the hierarchical frame structure
"""

import sys
import logging
from pathlib import Path
from rdflib import Graph
from vital_ai_vitalsigns.vitalsigns import VitalSigns

# Add vitalgraph to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.utils.graph_utils import (
    sort_objects_into_dag,
    pretty_print_dag,
    is_dag
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_and_visualize_frame_structure():
    """Load a lead entity graph and visualize its frame structure."""
    
    # Initialize VitalSigns
    vs = VitalSigns()
    
    # Path to lead data file
    data_dir = Path(__file__).parent.parent / "lead_test_data"
    lead_file = data_dir / "lead_00QUg00000Xzjy8MAB.nt"
    
    if not lead_file.exists():
        logger.error(f"Lead file not found: {lead_file}")
        return
    
    logger.info(f"Loading lead file: {lead_file}")
    
    # Load N-Triples file using RDFLib
    rdf_graph = Graph()
    rdf_graph.parse(str(lead_file), format='nt')
    
    logger.info(f"Loaded {len(rdf_graph)} triples from N-Triples file")
    
    # Convert RDFLib graph to VitalSigns objects
    logger.info("Converting triples to VitalSigns objects...")
    graph_objects = vs.from_triples_list(list(rdf_graph))
    
    logger.info(f"Converted to {len(graph_objects)} VitalSigns objects")
    
    # Check if objects form a DAG
    logger.info("\nChecking if objects form a DAG...")
    if is_dag(graph_objects):
        logger.info("✅ Objects form a valid DAG (no cycles)")
    else:
        logger.error("❌ Objects do not form a DAG (contains cycles)")
        return
    
    # Sort objects into DAG structure
    logger.info("\nSorting objects into DAG structure...")
    dag_structure = sort_objects_into_dag(graph_objects)
    
    # Pretty print the DAG structure
    logger.info("\n" + pretty_print_dag(dag_structure, show_properties=True))
    
    # Additional frame-specific analysis
    logger.info("\n" + "="*80)
    logger.info("FRAME-SPECIFIC ANALYSIS")
    logger.info("="*80)
    
    # Count frame types, slots, and edges
    frame_types = {}
    entity_frame_edges = []
    frame_frame_edges = []
    frame_slot_edges = []
    slots = []
    frames_by_uri = {}
    
    for obj in graph_objects:
        obj_type = type(obj).__name__
        if obj_type == 'KGFrame':
            if hasattr(obj, 'kGFrameType'):
                frame_type = str(obj.kGFrameType).split(':')[-1]
                frame_types[frame_type] = frame_types.get(frame_type, 0) + 1
            frames_by_uri[str(obj.URI)] = obj
        elif obj_type == 'Edge_hasEntityKGFrame':
            entity_frame_edges.append(obj)
        elif obj_type == 'Edge_hasKGFrame':
            frame_frame_edges.append(obj)
        elif obj_type == 'Edge_hasKGSlot':
            frame_slot_edges.append(obj)
        elif 'Slot' in obj_type:
            slots.append(obj)
    
    logger.info(f"\nFrame Types:")
    for frame_type, count in sorted(frame_types.items()):
        logger.info(f"  {frame_type}: {count}")
    
    logger.info(f"\nEdge Counts:")
    logger.info(f"  Entity → Frame edges: {len(entity_frame_edges)}")
    logger.info(f"  Frame → Frame edges: {len(frame_frame_edges)}")
    logger.info(f"  Frame → Slot edges: {len(frame_slot_edges)}")
    
    logger.info(f"\nSlot Counts:")
    logger.info(f"  Total slots: {len(slots)}")
    
    # Analyze slot types
    slot_types = {}
    for slot in slots:
        slot_type = type(slot).__name__
        slot_types[slot_type] = slot_types.get(slot_type, 0) + 1
    
    logger.info(f"\nSlot Types:")
    for slot_type, count in sorted(slot_types.items()):
        logger.info(f"  {slot_type}: {count}")
    
    # Analyze which frames have slots
    frame_to_slots = {}
    for edge in frame_slot_edges:
        if hasattr(edge, 'edgeSource') and hasattr(edge, 'edgeDestination'):
            frame_uri = str(edge.edgeSource)
            slot_uri = str(edge.edgeDestination)
            if frame_uri not in frame_to_slots:
                frame_to_slots[frame_uri] = []
            frame_to_slots[frame_uri].append(slot_uri)
    
    logger.info(f"\nFrames with Slots:")
    logger.info(f"  Frames that have slots: {len(frame_to_slots)}")
    if frame_to_slots:
        logger.info(f"\nDetailed Frame-Slot Mapping:")
        for frame_uri, slot_uris in sorted(frame_to_slots.items()):
            frame_name = frame_uri.split(':')[-2] if ':' in frame_uri else frame_uri
            logger.info(f"  {frame_name} ({len(slot_uris)} slots)")
    
    # Analyze parent-child relationships
    parent_to_children = {}
    logger.info(f"\nDebug: Analyzing {len(frame_frame_edges)} Edge_hasKGFrame edges...")
    for i, edge in enumerate(frame_frame_edges[:2]):  # Debug first 2 edges
        logger.info(f"  Edge {i+1}:")
        logger.info(f"    Type: {type(edge).__name__}")
        logger.info(f"    URI: {edge.URI}")
        logger.info(f"    All attributes: {[attr for attr in dir(edge) if not attr.startswith('_')][:20]}")
        
        # Try different property names
        for prop_name in ['hasEdgeSource', 'edgeSource', 'source', 'hasSource']:
            if hasattr(edge, prop_name):
                logger.info(f"    Found source property: {prop_name} = {getattr(edge, prop_name)}")
        
        for prop_name in ['hasEdgeDestination', 'edgeDestination', 'destination', 'hasDestination']:
            if hasattr(edge, prop_name):
                logger.info(f"    Found dest property: {prop_name} = {getattr(edge, prop_name)}")
    
    for edge in frame_frame_edges:
        if hasattr(edge, 'edgeSource') and hasattr(edge, 'edgeDestination'):
            parent_uri = str(edge.edgeSource)
            child_uri = str(edge.edgeDestination)
            if parent_uri not in parent_to_children:
                parent_to_children[parent_uri] = []
            parent_to_children[parent_uri].append(child_uri)
    
    logger.info(f"\nParent-Child Relationships:")
    logger.info(f"  Frames with children: {len(parent_to_children)}")
    logger.info(f"  Total parent-child edges: {len(frame_frame_edges)}")
    
    if parent_to_children:
        logger.info(f"\nDetailed Parent-Child Mapping:")
        for parent_uri, children in sorted(parent_to_children.items()):
            # Extract meaningful frame name from URI
            # URI format: urn:cardiff:lead:LEADID:frame:FRAMETYPE:INDEX
            parts = parent_uri.split(':frame:')
            parent_name = parts[-1] if len(parts) > 1 else parent_uri
            logger.info(f"  {parent_name} ({len(children)} children):")
            for child_uri in children:
                parts = child_uri.split(':frame:')
                child_name = parts[-1] if len(parts) > 1 else child_uri
                logger.info(f"    └─ {child_name}")


if __name__ == "__main__":
    try:
        load_and_visualize_frame_structure()
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())
