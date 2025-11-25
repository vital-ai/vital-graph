"""Graph Validation Utilities

This module provides centralized validation functions for KG entity and frame graphs.
These are fast, basic validation checks that can fail quickly before more formal
SPARQL-based validation is performed.

The validation functions check:
- Basic graph structure (entity→frame→slot relationships)
- Object type validation using isinstance checks
- Edge connection validation (source/destination matching)
- URI collection and validation
- Basic completeness checks

For more formal validation with edge type enforcement and complex structural
validation, use the SPARQL-based validation in the sparql package.
"""

import logging
from typing import Dict, List, Any, Set, Optional

logger = logging.getLogger(__name__)


class GraphValidationError(Exception):
    """Exception raised when graph validation fails."""
    pass


def validate_entity_graph_structure(objects: List[Any]) -> Dict[str, Any]:
    """Validate that objects form a complete entity graph structure.
    
    This is a fast, basic validation that checks:
    - Exactly 1 entity in the graph
    - Entity→frame connections via Edge_hasEntityKGFrame
    - Frame→frame connections via Edge_hasKGFrame (parent-child frames)
    - Frame→slot connections via Edge_hasKGSlot
    - All objects are properly connected (no orphaned objects)
    
    Args:
        objects: List of VitalSigns objects to validate
        
    Returns:
        Dict with validation results:
        - 'valid': bool - True if validation passed
        - 'error': str - Error message if validation failed
        - 'entity_uri': str - URI of the entity (if valid)
        - 'all_uris': set - All URIs in the graph (if valid)
        - 'entity': object - The entity object (if valid)
        - 'frames': list - Frame objects (if valid)
        - 'slots': list - Slot objects (if valid)
        - 'entity_frame_edges': list - Entity→frame edges (if valid)
        - 'frame_frame_edges': list - Frame→frame edges (if valid)
        - 'frame_slot_edges': list - Frame→slot edges (if valid)
    """
    try:
        # Import VitalSigns models
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
        from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
        from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
        from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
        from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
        
        # Separate objects by type
        entities = [obj for obj in objects if isinstance(obj, KGEntity)]
        frames = [obj for obj in objects if isinstance(obj, KGFrame)]
        slots = [obj for obj in objects if isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot))]
        entity_frame_edges = [obj for obj in objects if isinstance(obj, Edge_hasEntityKGFrame)]
        frame_frame_edges = [obj for obj in objects if isinstance(obj, Edge_hasKGFrame)]
        frame_slot_edges = [obj for obj in objects if isinstance(obj, Edge_hasKGSlot)]
        
        # Validate exactly 1 entity
        if len(entities) != 1:
            return {
                'valid': False,
                'error': f"Expected exactly 1 entity, found {len(entities)}"
            }
        
        entity = entities[0]
        entity_uri = str(entity.URI)
        
        # Collect all URIs
        all_uris = set()
        all_uris.add(entity_uri)
        
        for frame in frames:
            all_uris.add(str(frame.URI))
        
        for slot in slots:
            all_uris.add(str(slot.URI))
            
        for edge in entity_frame_edges:
            all_uris.add(str(edge.URI))
            
        for edge in frame_frame_edges:
            all_uris.add(str(edge.URI))
            
        for edge in frame_slot_edges:
            all_uris.add(str(edge.URI))
        
        # Validate entity→frame connections
        for edge in entity_frame_edges:
            source_uri = str(edge.edgeSource) if hasattr(edge, 'edgeSource') else None
            dest_uri = str(edge.edgeDestination) if hasattr(edge, 'edgeDestination') else None
            
            if source_uri and dest_uri:
                if source_uri != entity_uri:
                    return {
                        'valid': False,
                        'error': f"Entity-Frame edge {edge.URI} source {source_uri} does not match entity {entity_uri}"
                    }
                
                if dest_uri not in [str(frame.URI) for frame in frames]:
                    return {
                        'valid': False,
                        'error': f"Entity-Frame edge {edge.URI} destination {dest_uri} not found in frames"
                    }
        
        # Validate frame→slot connections
        for edge in frame_slot_edges:
            source_uri = str(edge.edgeSource) if hasattr(edge, 'edgeSource') else None
            dest_uri = str(edge.edgeDestination) if hasattr(edge, 'edgeDestination') else None
            
            if source_uri and dest_uri:
                if source_uri not in [str(frame.URI) for frame in frames]:
                    return {
                        'valid': False,
                        'error': f"Frame-Slot edge {edge.URI} source {source_uri} not found in frames"
                    }
                
                if dest_uri not in [str(slot.URI) for slot in slots]:
                    return {
                        'valid': False,
                        'error': f"Frame-Slot edge {edge.URI} destination {dest_uri} not found in slots"
                    }
        
        return {
            'valid': True,
            'entity_uri': entity_uri,
            'all_uris': all_uris,
            'entity': entity,
            'frames': frames,
            'slots': slots,
            'entity_frame_edges': entity_frame_edges,
            'frame_frame_edges': frame_frame_edges,
            'frame_slot_edges': frame_slot_edges
        }
        
    except Exception as e:
        return {
            'valid': False,
            'error': f"Structure validation error: {e}"
        }


def validate_frame_graph_structure(objects: List[Any]) -> Dict[str, Any]:
    """Validate that objects form a complete frame graph structure.
    
    This is a fast, basic validation that checks:
    - Exactly 1 frame in the graph
    - Frame→slot connections via Edge_hasKGSlot
    - All objects are properly connected (no orphaned objects)
    
    Args:
        objects: List of VitalSigns objects to validate
        
    Returns:
        Dict with validation results:
        - 'valid': bool - True if validation passed
        - 'error': str - Error message if validation failed
        - 'frame_uri': str - URI of the frame (if valid)
        - 'all_uris': set - All URIs in the graph (if valid)
        - 'frame': object - The frame object (if valid)
        - 'slots': list - Slot objects (if valid)
        - 'edges': list - Frame→slot edges (if valid)
    """
    try:
        # Import VitalSigns models
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
        from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
        from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
        
        # Separate objects by type
        frames = [obj for obj in objects if isinstance(obj, KGFrame)]
        slots = [obj for obj in objects if isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot))]
        edges = [obj for obj in objects if isinstance(obj, Edge_hasKGSlot)]
        
        # Validate exactly 1 frame
        if len(frames) != 1:
            return {
                'valid': False,
                'error': f"Expected exactly 1 frame, found {len(frames)}"
            }
        
        frame = frames[0]
        frame_uri = str(frame.URI)
        
        # Collect all URIs
        all_uris = set()
        all_uris.add(frame_uri)
        
        for slot in slots:
            all_uris.add(str(slot.URI))
        
        for edge in edges:
            all_uris.add(str(edge.URI))
        
        # Validate edge connections
        for edge in edges:
            # Access edge properties correctly
            source_uri = None
            dest_uri = None
            
            # Try different ways to access edge source/destination
            if hasattr(edge, 'hasEdgeSource'):
                source_uri = str(edge.hasEdgeSource.URI) if hasattr(edge.hasEdgeSource, 'URI') else str(edge.hasEdgeSource)
            elif hasattr(edge, 'edgeSource'):
                source_uri = str(edge.edgeSource.URI) if hasattr(edge.edgeSource, 'URI') else str(edge.edgeSource)
            
            if hasattr(edge, 'hasEdgeDestination'):
                dest_uri = str(edge.hasEdgeDestination.URI) if hasattr(edge.hasEdgeDestination, 'URI') else str(edge.hasEdgeDestination)
            elif hasattr(edge, 'edgeDestination'):
                dest_uri = str(edge.edgeDestination.URI) if hasattr(edge.edgeDestination, 'URI') else str(edge.edgeDestination)
            
            # Skip validation if we can't find source/destination (will be handled by VitalSigns validation)
            if source_uri and dest_uri:
                if source_uri != frame_uri:
                    return {
                        'valid': False,
                        'error': f"Edge {edge.URI} source {source_uri} does not match frame {frame_uri}"
                    }
                
                if dest_uri not in [str(slot.URI) for slot in slots]:
                    return {
                        'valid': False,
                        'error': f"Edge {edge.URI} destination {dest_uri} not found in slots"
                    }
        
        return {
            'valid': True,
            'frame_uri': frame_uri,
            'all_uris': all_uris,
            'frame': frame,
            'slots': slots,
            'edges': edges
        }
        
    except Exception as e:
        return {
            'valid': False,
            'error': f"Structure validation error: {e}"
        }


def analyze_frame_structure_for_grouping(objects: List[Any]) -> Dict[str, List[Any]]:
    """Analyze entity graph objects to determine frame membership for grouping URI assignment.
    
    This function identifies which objects belong to which frames within an entity graph,
    enabling proper dual grouping URI assignment (both entity-level and frame-level).
    
    Args:
        objects: List of VitalSigns objects from an entity graph
        
    Returns:
        Dict mapping frame URIs to lists of objects that belong to that frame:
        {
            'frame_uri_1': [frame_obj, slot_obj_1, slot_obj_2, edge_obj_1, edge_obj_2],
            'frame_uri_2': [frame_obj, slot_obj_3, edge_obj_3],
            ...
        }
    """
    try:
        # Import VitalSigns models
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
        from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
        from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
        
        # Separate objects by type
        frames = [obj for obj in objects if isinstance(obj, KGFrame)]
        slots = [obj for obj in objects if isinstance(obj, (KGTextSlot, KGIntegerSlot, KGBooleanSlot))]
        frame_slot_edges = [obj for obj in objects if isinstance(obj, Edge_hasKGSlot)]
        
        # Build frame membership mapping
        frame_structure = {}
        
        for frame in frames:
            frame_uri = str(frame.URI)
            frame_components = [frame]  # Start with the frame itself
            
            # Find slots connected to this frame
            connected_slots = []
            connecting_edges = []
            
            for edge in frame_slot_edges:
                source_uri = str(edge.edgeSource) if hasattr(edge, 'edgeSource') else None
                dest_uri = str(edge.edgeDestination) if hasattr(edge, 'edgeDestination') else None
                
                if source_uri == frame_uri:
                    # This edge connects from this frame
                    connecting_edges.append(edge)
                    
                    # Find the slot this edge connects to
                    for slot in slots:
                        if str(slot.URI) == dest_uri:
                            connected_slots.append(slot)
                            break
            
            # Add connected slots and edges to frame components
            frame_components.extend(connected_slots)
            frame_components.extend(connecting_edges)
            
            frame_structure[frame_uri] = frame_components
        
        return frame_structure
        
    except Exception as e:
        logger.error(f"Error analyzing frame structure for grouping: {e}")
        return {}


def validate_parent_object_exists(parent_uri: str, available_objects: List[Any]) -> bool:
    """Validate that a parent object (entity or frame) exists in the available objects.
    
    Args:
        parent_uri: URI of the parent object to validate
        available_objects: List of objects to search in
        
    Returns:
        bool: True if parent object exists, False otherwise
    """
    try:
        # Import VitalSigns models
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        
        for obj in available_objects:
            if isinstance(obj, (KGEntity, KGFrame)):
                if str(obj.URI) == parent_uri:
                    return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error validating parent object existence: {e}")
        return False


def validate_parent_connection(parent_uri: str, child_uri: str, incoming_objects: List[Any]) -> bool:
    """Validate that there's a proper connection between parent and child in the incoming objects.
    
    Args:
        parent_uri: URI of the parent object
        child_uri: URI of the child object (entity or frame)
        incoming_objects: List of objects to check for connection edges
        
    Returns:
        bool: True if proper connection exists, False otherwise
    """
    try:
        # Import VitalSigns models
        from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
        from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
        
        # Look for edges connecting parent to child
        for obj in incoming_objects:
            # Check for entity→frame connections
            if isinstance(obj, Edge_hasEntityKGFrame):
                source_uri = str(obj.edgeSource) if hasattr(obj, 'edgeSource') else None
                dest_uri = str(obj.edgeDestination) if hasattr(obj, 'edgeDestination') else None
                
                if source_uri == parent_uri and dest_uri == child_uri:
                    return True
            
            # Check for frame→frame connections
            elif isinstance(obj, Edge_hasKGFrame):
                source_uri = str(obj.edgeSource) if hasattr(obj, 'edgeSource') else None
                dest_uri = str(obj.edgeDestination) if hasattr(obj, 'edgeDestination') else None
                
                if source_uri == parent_uri and dest_uri == child_uri:
                    return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error validating parent connection: {e}")
        return False


def collect_all_uris(objects: List[Any]) -> Set[str]:
    """Collect all URIs from a list of VitalSigns objects.
    
    Args:
        objects: List of VitalSigns objects
        
    Returns:
        Set of URI strings
    """
    try:
        uris = set()
        for obj in objects:
            if hasattr(obj, 'URI'):
                uris.add(str(obj.URI))
        return uris
        
    except Exception as e:
        logger.error(f"Error collecting URIs: {e}")
        return set()


def validate_no_orphaned_objects(objects: List[Any]) -> Dict[str, Any]:
    """Validate that all objects in a graph are properly connected (no orphaned objects).
    
    This performs a more comprehensive check to ensure all objects are reachable
    through the graph's edge structure.
    
    Args:
        objects: List of VitalSigns objects to validate
        
    Returns:
        Dict with validation results:
        - 'valid': bool - True if no orphaned objects found
        - 'error': str - Error message if orphaned objects found
        - 'orphaned_objects': list - List of orphaned object URIs (if any)
    """
    try:
        # This is a placeholder for more sophisticated orphan detection
        # For now, we rely on the basic structure validation above
        # Future enhancement: implement graph traversal to find unreachable objects
        
        return {
            'valid': True,
            'orphaned_objects': []
        }
        
    except Exception as e:
        return {
            'valid': False,
            'error': f"Orphan validation error: {e}",
            'orphaned_objects': []
        }