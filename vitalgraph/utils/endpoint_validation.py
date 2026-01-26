"""
Endpoint Validation Utilities for VitalGraph Mock Endpoints

This module provides common validation functions used across multiple mock endpoints
to reduce code duplication and standardize validation patterns.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from vitalgraph.utils.sparql_helpers import check_object_exists_in_graph, execute_sparql_query_safe


def validate_parent_object(space, parent_uri: str, graph_id: str, logger: Optional[logging.Logger] = None) -> bool:
    """
    Validate that a parent object exists (entity or frame).
    
    Args:
        space: Mock space instance with pyoxigraph
        parent_uri: URI of the parent object to validate
        graph_id: Graph ID to search in
        logger: Optional logger for error reporting
        
    Returns:
        bool: True if parent object exists, False otherwise
    """
    try:
        # Check if parent is an entity
        if graph_id:
            entity_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{parent_uri}> a haley:KGEntity .
                }}
            }} LIMIT 1
            """
        else:
            entity_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?s WHERE {{
                <{parent_uri}> a haley:KGEntity .
            }} LIMIT 1
            """
        
        entity_results = execute_sparql_query_safe(space, entity_query, logger)
        if len(entity_results.get("bindings", [])) > 0:
            return True
        
        # Check if parent is a frame
        if graph_id:
            frame_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{parent_uri}> a haley:KGFrame .
                }}
            }} LIMIT 1
            """
        else:
            frame_query = f"""
            PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
            SELECT ?s WHERE {{
                <{parent_uri}> a haley:KGFrame .
            }} LIMIT 1
            """
        
        frame_results = execute_sparql_query_safe(space, frame_query, logger)
        return len(frame_results.get("bindings", [])) > 0
        
    except Exception as e:
        if logger:
            logger.error(f"Error validating parent object {parent_uri}: {e}")
        return False


def validate_parent_connection(space, parent_uri: str, child_uri: str, graph_id: str, 
                             incoming_objects: List[Any], edge_type: str = "Edge_hasEntityKGFrame",
                             logger: Optional[logging.Logger] = None) -> bool:
    """
    Validate that there's a proper connection between parent and child in the incoming objects.
    
    Args:
        space: Mock space instance with pyoxigraph
        parent_uri: URI of the parent object
        child_uri: URI of the child object
        graph_id: Graph ID to search in
        incoming_objects: List of incoming objects to check for edge relationships
        edge_type: Type of edge to look for (Edge_hasEntityKGFrame, Edge_hasKGFrame, Edge_hasKGSlot)
        logger: Optional logger for error reporting
        
    Returns:
        bool: True if proper connection exists, False otherwise
    """
    try:
        # Look for edges connecting parent to child in incoming objects
        for obj in incoming_objects:
            # Check if this is an edge of the correct type
            if hasattr(obj, 'vitaltype') and edge_type in str(obj.vitaltype):
                # Check if edge connects parent to child
                if (hasattr(obj, 'edgeSource') and str(obj.edgeSource) == parent_uri and
                    hasattr(obj, 'edgeDestination') and str(obj.edgeDestination) == child_uri):
                    return True
                elif (hasattr(obj, 'hasEdgeSource') and str(obj.hasEdgeSource) == parent_uri and
                      hasattr(obj, 'hasEdgeDestination') and str(obj.hasEdgeDestination) == child_uri):
                    return True
        
        if logger:
            logger.warning(f"No {edge_type} edge found connecting {parent_uri} to {child_uri}")
        return False
        
    except Exception as e:
        if logger:
            logger.error(f"Error validating parent connection: {e}")
        return False


def validate_operation_mode(operation_mode: str, valid_modes: List[str] = None) -> bool:
    """
    Validate that the operation mode is one of the allowed values.
    
    Args:
        operation_mode: The operation mode to validate
        valid_modes: List of valid operation modes (default: ["create", "update", "upsert"])
        
    Returns:
        bool: True if operation mode is valid, False otherwise
    """
    if valid_modes is None:
        valid_modes = ["create", "update", "upsert"]
    
    return operation_mode.lower() in [mode.lower() for mode in valid_modes]


def check_objects_exist_in_store(space, uris: Set[str], graph_id: str, 
                                logger: Optional[logging.Logger] = None) -> Dict[str, bool]:
    """
    Check which objects from a set of URIs exist in the store.
    
    Args:
        space: Mock space instance with pyoxigraph
        uris: Set of URIs to check
        graph_id: Graph ID to search in
        logger: Optional logger for error reporting
        
    Returns:
        Dict[str, bool]: Mapping of URI to existence status
    """
    existence_map = {}
    
    for uri in uris:
        exists = check_object_exists_in_graph(space, uri, graph_id)
        existence_map[uri] = exists
        
        if logger:
            logger.debug(f"Object {uri} exists: {exists}")
    
    return existence_map


def validate_required_objects_exist(space, required_uris: Set[str], graph_id: str,
                                  logger: Optional[logging.Logger] = None) -> tuple[bool, List[str]]:
    """
    Validate that all required objects exist in the store.
    
    Args:
        space: Mock space instance with pyoxigraph
        required_uris: Set of URIs that must exist
        graph_id: Graph ID to search in
        logger: Optional logger for error reporting
        
    Returns:
        tuple[bool, List[str]]: (all_exist, list_of_missing_uris)
    """
    existence_map = check_objects_exist_in_store(space, required_uris, graph_id, logger)
    missing_uris = [uri for uri, exists in existence_map.items() if not exists]
    
    all_exist = len(missing_uris) == 0
    
    if not all_exist and logger:
        logger.warning(f"Missing required objects: {missing_uris}")
    
    return all_exist, missing_uris


def validate_no_objects_exist(space, uris: Set[str], graph_id: str,
                            logger: Optional[logging.Logger] = None) -> tuple[bool, List[str]]:
    """
    Validate that none of the specified objects exist in the store (for CREATE mode).
    
    Args:
        space: Mock space instance with pyoxigraph
        uris: Set of URIs that should not exist
        graph_id: Graph ID to search in
        logger: Optional logger for error reporting
        
    Returns:
        tuple[bool, List[str]]: (none_exist, list_of_existing_uris)
    """
    existence_map = check_objects_exist_in_store(space, uris, graph_id, logger)
    existing_uris = [uri for uri, exists in existence_map.items() if exists]
    
    none_exist = len(existing_uris) == 0
    
    if not none_exist and logger:
        logger.warning(f"Objects already exist (CREATE mode violation): {existing_uris}")
    
    return none_exist, existing_uris


def is_frame_parent(space, parent_uri: str, graph_id: str, logger: Optional[logging.Logger] = None) -> bool:
    """
    Check if parent is a frame (vs entity).
    
    Args:
        space: Mock space instance with pyoxigraph
        parent_uri: URI of the parent to check
        graph_id: Graph ID to search in
        logger: Optional logger for error reporting
        
    Returns:
        bool: True if parent is a frame, False otherwise
    """
    try:
        query = f"""
        PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
        SELECT ?s WHERE {{
            GRAPH <{graph_id}> {{
                <{parent_uri}> a haley:KGFrame .
            }}
        }} LIMIT 1
        """
        
        results = execute_sparql_query_safe(space, query, logger)
        return len(results.get("bindings", [])) > 0
        
    except Exception as e:
        if logger:
            logger.error(f"Error checking if {parent_uri} is frame: {e}")
        return False


def extract_uris_from_objects(objects: List[Any]) -> Set[str]:
    """
    Extract URIs from a list of VitalSigns objects.
    
    Args:
        objects: List of VitalSigns objects
        
    Returns:
        Set[str]: Set of URIs found in the objects
    """
    uris = set()
    
    for obj in objects:
        if hasattr(obj, 'URI'):
            uri_value = str(obj.URI)
            if uri_value and uri_value != 'None':
                uris.add(uri_value)
    
    return uris


def validate_uri_consistency(objects: List[Any], expected_primary_uri: str, 
                           primary_type: str, logger: Optional[logging.Logger] = None) -> bool:
    """
    Validate that objects contain exactly one object of the primary type with the expected URI.
    
    Args:
        objects: List of VitalSigns objects to validate
        expected_primary_uri: The expected URI of the primary object
        primary_type: The expected type of the primary object (e.g., "KGEntity", "KGFrame")
        logger: Optional logger for error reporting
        
    Returns:
        bool: True if validation passes, False otherwise
    """
    try:
        primary_objects = []
        
        for obj in objects:
            if hasattr(obj, 'vitaltype') and primary_type in str(obj.vitaltype):
                primary_objects.append(obj)
        
        # Should have exactly one primary object
        if len(primary_objects) != 1:
            if logger:
                logger.error(f"Expected exactly 1 {primary_type}, found {len(primary_objects)}")
            return False
        
        # Primary object should have the expected URI
        primary_obj = primary_objects[0]
        if str(primary_obj.URI) != expected_primary_uri:
            if logger:
                logger.error(f"Primary {primary_type} URI mismatch: expected {expected_primary_uri}, found {primary_obj.URI}")
            return False
        
        return True
        
    except Exception as e:
        if logger:
            logger.error(f"Error validating URI consistency: {e}")
        return False


def format_validation_error_response(error_message: str, error_details: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Format a standardized validation error response.
    
    Args:
        error_message: Main error message
        error_details: Optional dictionary of additional error details
        
    Returns:
        Dict[str, Any]: Formatted error response
    """
    response = {
        "success": False,
        "error": error_message,
        "error_type": "validation_error"
    }
    
    if error_details:
        response["details"] = error_details
    
    return response
