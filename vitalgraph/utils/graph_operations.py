"""
Graph Operations Utilities for VitalGraph Mock Endpoints

This module provides common graph operations including grouping URI management,
edge relationship handling, and graph structure utilities.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from vitalgraph.utils.sparql_helpers import execute_sparql_query_safe, build_grouping_uri_query


def set_grouping_uris(objects: List[Any], grouping_uri: str, grouping_property: str = "kGGraphURI",
                     logger: Optional[logging.Logger] = None) -> None:
    """
    Set grouping URIs on a list of VitalSigns objects.
    
    Args:
        objects: List of VitalSigns objects to update
        grouping_uri: The grouping URI to set
        grouping_property: Property name for grouping URI (default: "kGGraphURI")
        logger: Optional logger for debugging
    """
    try:
        for obj in objects:
            if hasattr(obj, grouping_property):
                setattr(obj, grouping_property, grouping_uri)
                if logger:
                    logger.debug(f"Set {grouping_property}={grouping_uri} on {getattr(obj, 'URI', 'unknown')}")
            else:
                if logger:
                    logger.warning(f"Object {getattr(obj, 'URI', 'unknown')} missing {grouping_property} property")
                    
    except Exception as e:
        if logger:
            logger.error(f"Error setting grouping URIs: {e}")


def set_entity_grouping_uris(objects: List[Any], entity_uri: str, logger: Optional[logging.Logger] = None) -> None:
    """
    Set entity-level grouping URIs on objects.
    
    Args:
        objects: List of VitalSigns objects to update
        entity_uri: The entity URI to use as grouping URI
        logger: Optional logger for debugging
    """
    set_grouping_uris(objects, entity_uri, "kGGraphURI", logger)


def set_frame_grouping_uris(objects: List[Any], frame_uri: str, logger: Optional[logging.Logger] = None) -> None:
    """
    Set frame-level grouping URIs on objects.
    
    Args:
        objects: List of VitalSigns objects to update
        frame_uri: The frame URI to use as grouping URI
        logger: Optional logger for debugging
    """
    set_grouping_uris(objects, frame_uri, "frameGraphURI", logger)


def set_dual_grouping_uris(objects: List[Any], entity_uri: str, frame_structure: Dict[str, List[Any]] = None,
                          logger: Optional[logging.Logger] = None) -> None:
    """
    Set both entity-level and frame-level grouping URIs for dual grouping support.
    
    Args:
        objects: List of VitalSigns objects to update
        entity_uri: The entity URI for entity-level grouping
        frame_structure: Optional mapping of frame URIs to their component objects
        logger: Optional logger for debugging
    """
    try:
        # Set entity-level grouping for all objects
        set_entity_grouping_uris(objects, entity_uri, logger)
        
        # Set frame-level grouping if frame structure is provided
        if frame_structure:
            for frame_uri, frame_components in frame_structure.items():
                set_frame_grouping_uris(frame_components, frame_uri, logger)
        else:
            # Analyze frame structure automatically
            frame_structure = analyze_frame_structure_for_grouping(objects, logger)
            for frame_uri, frame_components in frame_structure.items():
                set_frame_grouping_uris(frame_components, frame_uri, logger)
                
    except Exception as e:
        if logger:
            logger.error(f"Error setting dual grouping URIs: {e}")


def analyze_frame_structure_for_grouping(objects: List[Any], logger: Optional[logging.Logger] = None) -> Dict[str, List[Any]]:
    """
    Analyze objects to determine frame membership for grouping URI assignment.
    
    Args:
        objects: List of VitalSigns objects to analyze
        logger: Optional logger for debugging
        
    Returns:
        Dict[str, List[Any]]: Mapping of frame URIs to their component objects
    """
    frame_structure = {}
    
    try:
        # Find all frames
        frames = []
        for obj in objects:
            if hasattr(obj, 'vitaltype') and 'KGFrame' in str(obj.vitaltype):
                frames.append(obj)
        
        # For each frame, find its components (slots and edges)
        for frame in frames:
            frame_uri = str(frame.URI)
            frame_components = [frame]  # Include the frame itself
            
            # Find slots connected to this frame
            for obj in objects:
                if hasattr(obj, 'vitaltype'):
                    obj_type = str(obj.vitaltype)
                    
                    # Check if this is a slot
                    if 'Slot' in obj_type:
                        frame_components.append(obj)
                    
                    # Check if this is an edge connecting to this frame
                    elif 'Edge' in obj_type:
                        if (hasattr(obj, 'edgeSource') and str(obj.edgeSource) == frame_uri) or \
                           (hasattr(obj, 'edgeDestination') and str(obj.edgeDestination) == frame_uri) or \
                           (hasattr(obj, 'hasEdgeSource') and str(obj.hasEdgeSource) == frame_uri) or \
                           (hasattr(obj, 'hasEdgeDestination') and str(obj.hasEdgeDestination) == frame_uri):
                            frame_components.append(obj)
            
            frame_structure[frame_uri] = frame_components
            
            if logger:
                logger.debug(f"Frame {frame_uri} has {len(frame_components)} components")
        
        return frame_structure
        
    except Exception as e:
        logger.error(f"Error in SPARQL query execution: {e}")
        return []


def create_edge_relationship(edge_class, source_uri: str, destination_uri: str, 
                           edge_uri: str = None, additional_properties: Dict[str, Any] = None,
                           logger: Optional[logging.Logger] = None) -> Any:
    """
    Create an edge relationship object between two entities/frames/slots.
    
    Args:
        edge_class: The VitalSigns edge class to instantiate
        source_uri: URI of the source object
        destination_uri: URI of the destination object
        edge_uri: Optional specific URI for the edge (auto-generated if None)
        additional_properties: Optional additional properties to set on the edge
        logger: Optional logger for debugging
        
    Returns:
        Any: The created edge object
    """
    try:
        # Create the edge object
        edge = edge_class()
        
        # Set the URI
        if edge_uri:
            edge.URI = edge_uri
        else:
            # Auto-generate edge URI
            import uuid
            edge_id = str(uuid.uuid4())
            edge.URI = f"http://vital.ai/haley.ai/app/{edge_class.__name__}/{edge_id}"
        
        # Set source and destination
        edge.edgeSource = source_uri
        edge.edgeDestination = destination_uri
        
        # Set additional properties if provided
        if additional_properties:
            for prop_name, prop_value in additional_properties.items():
                if hasattr(edge, prop_name):
                    setattr(edge, prop_name, prop_value)
                else:
                    if logger:
                        logger.warning(f"Edge property {prop_name} not found on {edge_class.__name__}")
        
        if logger:
            logger.debug(f"Created edge {edge.URI}: {source_uri} -> {destination_uri}")
        
        return edge
        
    except Exception as e:
        if logger:
            logger.error(f"Error creating edge relationship: {e}")
        return None


def get_objects_by_grouping_uri(space, grouping_uri: str, graph_id: str, 
                               grouping_property: str = "hasKGGraphURI",
                               logger: Optional[logging.Logger] = None) -> List[Dict[str, str]]:
    """
    Retrieve all objects with a specific grouping URI as RDF triples.
    
    Args:
        space: Mock space instance with pyoxigraph
        grouping_uri: The grouping URI to filter by
        graph_id: Graph ID to search in
        grouping_property: Property name for grouping URI (default: "hasKGGraphURI")
        logger: Optional logger for debugging
        
    Returns:
        List[Dict[str, str]]: List of RDF triples as dictionaries
    """
    try:
        if graph_id:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?subject ?predicate ?object WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject haley:{grouping_property} <{grouping_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
            ORDER BY ?subject ?predicate
            """
        else:
            query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            SELECT ?subject ?predicate ?object WHERE {{
                ?subject haley:{grouping_property} <{grouping_uri}> .
                ?subject ?predicate ?object .
            }}
            ORDER BY ?subject ?predicate
            """
        
        results = execute_sparql_query_safe(space, query, logger)
        
        triples = []
        for binding in results.get("bindings", []):
            subject = binding.get("subject", {}).get("value", "")
            predicate = binding.get("predicate", {}).get("value", "")
            obj = binding.get("object", {}).get("value", "")
            
            from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
            triples.append({
                "subject": f"<{subject}>",
                "predicate": f"<{predicate}>",
                "object": f"<{obj}>" if validate_rfc3986(str(obj), rule='URI') else f'"{obj}"'
            })
        
        if logger:
            logger.debug(f"Retrieved {len(triples)} triples for grouping URI {grouping_uri}")
        
        return triples
        
    except Exception as e:
        if logger:
            logger.error(f"Error retrieving objects by grouping URI: {e}")
        return []


def delete_objects_by_grouping_uri(space, grouping_uri: str, graph_id: str,
                                  grouping_property: str = "hasKGGraphURI",
                                  logger: Optional[logging.Logger] = None) -> bool:
    """
    Delete all objects with a specific grouping URI.
    
    Args:
        space: Mock space instance with pyoxigraph
        grouping_uri: The grouping URI to filter by
        graph_id: Graph ID to delete from
        grouping_property: Property name for grouping URI (default: "hasKGGraphURI")
        logger: Optional logger for debugging
        
    Returns:
        bool: True if deletion successful, False otherwise
    """
    try:
        if graph_id:
            delete_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    ?subject haley:{grouping_property} <{grouping_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
            """
        else:
            delete_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            
            DELETE WHERE {{
                ?subject haley:{grouping_property} <{grouping_uri}> .
                ?subject ?predicate ?object .
            }}
            """
        
        space.update_sparql(delete_query)
        
        if logger:
            logger.info(f"Deleted objects with grouping URI {grouping_uri}")
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Error deleting objects by grouping URI: {e}")
        return False


def backup_objects_by_grouping_uri(space, grouping_uri: str, graph_id: str,
                                  grouping_property: str = "hasKGGraphURI",
                                  logger: Optional[logging.Logger] = None) -> List[Dict[str, str]]:
    """
    Backup all objects with a specific grouping URI for potential rollback.
    
    Args:
        space: Mock space instance with pyoxigraph
        grouping_uri: The grouping URI to backup
        graph_id: Graph ID to backup from
        grouping_property: Property name for grouping URI (default: "hasKGGraphURI")
        logger: Optional logger for debugging
        
    Returns:
        List[Dict[str, str]]: Backup of RDF triples
    """
    backup_triples = get_objects_by_grouping_uri(space, grouping_uri, graph_id, grouping_property, logger)
    
    if logger:
        logger.info(f"Backed up {len(backup_triples)} triples for grouping URI {grouping_uri}")
    
    return backup_triples


def restore_objects_from_backup(space, backup_triples: List[Dict[str, str]], graph_id: str,
                               logger: Optional[logging.Logger] = None) -> bool:
    """
    Restore objects from a backup of RDF triples.
    
    Args:
        space: Mock space instance with pyoxigraph
        backup_triples: List of RDF triples to restore
        graph_id: Graph ID to restore to
        logger: Optional logger for debugging
        
    Returns:
        bool: True if restoration successful, False otherwise
    """
    try:
        if not backup_triples:
            if logger:
                logger.info("No backup triples to restore")
            return True
        
        # Convert triples to N-Triples format
        rdf_lines = []
        for triple in backup_triples:
            subject = triple['subject']
            predicate = triple['predicate']
            obj = triple['object']
            rdf_lines.append(f"{subject} {predicate} {obj} .")
        
        rdf_data = '\n'.join(rdf_lines)
        
        # Insert the RDF data
        if graph_id:
            insert_query = f"""
            INSERT DATA {{
                GRAPH <{graph_id}> {{
                    {rdf_data}
                }}
            }}
            """
        else:
            insert_query = f"""
            INSERT DATA {{
                {rdf_data}
            }}
            """
        
        space.update_sparql(insert_query)
        
        if logger:
            logger.info(f"Restored {len(backup_triples)} triples from backup")
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Error restoring objects from backup: {e}")
        return False


def set_dual_grouping_uris(objects: List[Any], entity_uri: str, logger) -> None:
    """Set both entity-level and frame-level grouping URIs for proper graph retrieval.
    
    This method implements the solution for Task #5: Frame-Level Grouping URI Implementation.
    It sets both hasKGGraphURI (entity-level) and hasFrameGraphURI (frame-level) appropriately.
    
    Args:
        objects: List of VitalSigns objects to set grouping URIs on
        entity_uri: The parent entity URI for entity-level grouping
        logger: Logger instance for debugging
    """
    try:
        from vitalgraph.utils.validation_utils import analyze_frame_structure_for_grouping
        
        # Step 1: Set entity-level grouping for all objects
        for obj in objects:
            try:
                obj.kGGraphURI = entity_uri
                logger.debug(f"Set kGGraphURI={entity_uri} on object {obj.URI}")
            except Exception as e:
                logger.error(f"Failed to set kGGraphURI on object {obj.URI}: {e}")
        
        # Step 2: Analyze frame structure to identify frame memberships
        frame_structure = analyze_frame_structure_for_grouping(objects)
        
        # Step 3: Set frame-level grouping for frame components
        for frame_uri, frame_components in frame_structure.items():
            for component in frame_components:
                try:
                    # Use short name property access - hasFrameGraphURI short name is 'frameGraphURI'
                    component.frameGraphURI = frame_uri
                    logger.debug(f"Set frameGraphURI={frame_uri} on object {component.URI}")
                except Exception as e:
                    logger.error(f"Failed to set frameGraphURI on object {component.URI}: {e}")
        
        logger.info(f"Set dual grouping URIs: entity-level ({entity_uri}) and frame-level ({len(frame_structure)} frames)")
        
    except Exception as e:
        logger.error(f"Error setting dual grouping URIs: {e}")
        # Fallback to entity-level grouping only
        set_entity_grouping_uris(objects, entity_uri, logger)


def set_entity_grouping_uris(objects: List[Any], entity_uri: str, logger) -> None:
    """Set entity-level grouping URIs only (fallback method).
    
    Args:
        objects: List of VitalSigns objects to set grouping URIs on
        entity_uri: The parent entity URI for entity-level grouping
        logger: Logger instance for debugging
    """
    try:
        for obj in objects:
            try:
                obj.kGGraphURI = entity_uri
                logger.debug(f"Set kGGraphURI={entity_uri} on object {obj.URI}")
            except Exception as e:
                logger.error(f"Failed to set kGGraphURI on object {obj.URI}: {e}")
        
        logger.info(f"Set entity-level grouping URIs for {len(objects)} objects")
        
    except Exception as e:
        logger.error(f"Error setting entity grouping URIs: {e}")
