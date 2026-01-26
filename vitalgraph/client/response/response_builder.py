"""
Response Builder Utilities

Utilities for converting JSON-LD to VitalSigns GraphObjects and building
standardized response objects.
"""

from typing import List, Dict, Any, Optional, Type, TypeVar
import logging

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

from .client_response import (
    VitalGraphResponse,
    GraphObjectResponse,
    PaginatedGraphObjectResponse,
    EntityGraph,
    FrameGraph,
    EntityResponse,
    EntityGraphResponse,
    FrameResponse,
    FrameGraphResponse,
    MultiEntityGraphResponse,
    MultiFrameGraphResponse,
    DeleteResponse,
    QueryResponse,
    # Files response classes
    FileResponse,
    FilesListResponse,
    FileCreateResponse,
    FileUpdateResponse,
    FileDeleteResponse,
    FileUploadResponse,
    FileDownloadResponse,
    # Spaces response classes
    SpaceResponse,
    SpaceInfoResponse,
    SpacesListResponse,
    SpaceCreateResponse,
    SpaceUpdateResponse,
    SpaceDeleteResponse,
    # Graphs response classes
    GraphResponse,
    GraphsListResponse,
    GraphCreateResponse,
    GraphDeleteResponse,
    GraphClearResponse,
    # KGTypes response classes
    KGTypeResponse,
    KGTypesListResponse,
    KGTypeCreateResponse,
    KGTypeUpdateResponse,
    KGTypeDeleteResponse,
    # Objects response classes
    ObjectResponse,
    ObjectsListResponse,
    ObjectCreateResponse,
    ObjectUpdateResponse,
    ObjectDeleteResponse,
)

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=VitalGraphResponse)


def jsonld_to_graph_objects(jsonld_data: Dict[str, Any], vs: VitalSigns) -> List[GraphObject]:
    """
    Convert JSON-LD data to VitalSigns GraphObjects.
    
    Args:
        jsonld_data: JSON-LD document or graph data
        vs: VitalSigns instance for deserialization
        
    Returns:
        List of GraphObject instances
        
    Raises:
        Exception: If JSON-LD parsing fails
    """
    try:
        if not jsonld_data:
            return []
        
        graph_data = jsonld_data.get('@graph', [])
        if not graph_data:
            if '@id' in jsonld_data:
                graph_data = [jsonld_data]
            else:
                return []
        
        # Use from_jsonld_list for batch conversion
        try:
            objects = vs.from_jsonld_list(jsonld_data)
            return objects if objects else []
        except Exception as e:
            logger.warning(f"Batch deserialization failed, trying individual: {e}")
            # Fallback to individual deserialization
            objects = []
            for item in graph_data:
                try:
                    obj = vs.from_jsonld(item)
                    if obj:
                        objects.append(obj)
                except Exception as item_error:
                    logger.warning(f"Failed to deserialize object {item.get('@id', 'unknown')}: {item_error}")
                    continue
            return objects
        
    except Exception as e:
        logger.error(f"Failed to convert JSON-LD to GraphObjects: {e}")
        raise


def count_object_types(objects: List[GraphObject]) -> Dict[str, int]:
    """
    Count objects by type for metadata.
    
    Args:
        objects: List of GraphObject instances
        
    Returns:
        Dictionary mapping type names to counts
    """
    type_counts = {}
    for obj in objects:
        type_name = type(obj).__name__
        type_counts[type_name] = type_counts.get(type_name, 0) + 1
    return type_counts


def build_success_response(
    response_class: Type[T],
    objects: Optional[Any] = None,
    status_code: int = 200,
    message: Optional[str] = None,
    **kwargs
) -> T:
    """
    Build a success response.
    
    Args:
        response_class: Response class to instantiate
        objects: Response objects (type depends on response class)
        status_code: HTTP status code
        message: Optional success message
        **kwargs: Additional fields for the response class
        
    Returns:
        Response instance
    """
    response_data = {
        'error_code': 0,
        'error_message': None,
        'status_code': status_code,
        'message': message,
        'objects': objects,
        **kwargs
    }
    
    return response_class(**response_data)


def build_error_response(
    response_class: Type[T],
    error_code: int,
    error_message: str,
    status_code: int = 500,
    **kwargs
) -> T:
    """
    Build an error response.
    
    Args:
        response_class: Response class to instantiate
        error_code: Error code (non-zero)
        error_message: Error message
        status_code: HTTP status code
        **kwargs: Additional fields for the response class
        
    Returns:
        Response instance
    """
    response_data = {
        'error_code': error_code,
        'error_message': error_message,
        'status_code': status_code,
        'message': None,
        **kwargs
    }
    
    if hasattr(response_class, 'objects'):
        response_data['objects'] = None
    
    return response_class(**response_data)


def extract_pagination_metadata(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract pagination metadata from server response.
    
    Args:
        response_data: Server response data
        
    Returns:
        Dictionary with pagination fields
    """
    return {
        'total_count': response_data.get('total_count', 0),
        'page_size': response_data.get('page_size', 10),
        'offset': response_data.get('offset', 0),
        'has_more': response_data.get('has_more', False)
    }


def build_entity_graph(entity_uri: str, objects: List[GraphObject]) -> EntityGraph:
    """
    Build an EntityGraph container.
    
    Args:
        entity_uri: URI of the entity
        objects: List of GraphObjects in the entity graph
        
    Returns:
        EntityGraph instance
    """
    return EntityGraph(entity_uri=entity_uri, objects=objects)


def build_frame_graph(frame_uri: str, objects: List[GraphObject]) -> FrameGraph:
    """
    Build a FrameGraph container.
    
    Args:
        frame_uri: URI of the frame
        objects: List of GraphObjects in the frame graph
        
    Returns:
        FrameGraph instance
    """
    return FrameGraph(frame_uri=frame_uri, objects=objects)


def group_objects_by_entity(objects: List[GraphObject]) -> Dict[str, List[GraphObject]]:
    """
    Group objects by their entity URI for multi-entity-graph responses.
    
    Args:
        objects: List of all GraphObjects
        
    Returns:
        Dictionary mapping entity URIs to their objects
    """
    from vital_ai_vitalsigns.model.VITAL_Node import VITAL_Node
    
    entity_groups = {}
    
    for obj in objects:
        if hasattr(obj, 'URI'):
            entity_uri = obj.URI
            if entity_uri not in entity_groups:
                entity_groups[entity_uri] = []
            entity_groups[entity_uri].append(obj)
    
    return entity_groups


def group_objects_by_frame(objects: List[GraphObject]) -> Dict[str, List[GraphObject]]:
    """
    Group objects by their frame URI for multi-frame-graph responses.
    
    Args:
        objects: List of all GraphObjects
        
    Returns:
        Dictionary mapping frame URIs to their objects
    """
    frame_groups = {}
    
    for obj in objects:
        if hasattr(obj, 'URI'):
            frame_uri = obj.URI
            if frame_uri not in frame_groups:
                frame_groups[frame_uri] = []
            frame_groups[frame_uri].append(obj)
    
    return frame_groups
