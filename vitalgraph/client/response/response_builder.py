"""
Response Builder Utilities

Utilities for converting server responses to VitalSigns GraphObjects and building
standardized response objects.
"""

from typing import List, Dict, Any, Optional, Type, TypeVar
import logging

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

from .client_response import (
    _SUCCESS_STATUS_VALUES,
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
    status: Optional[str] = None,
    **kwargs
) -> T:
    """
    Build a success response.

    Args:
        response_class: Response class to instantiate
        objects: Response objects (type depends on response class)
        status_code: HTTP status code
        message: Optional success message
        status: Optional server domain outcome (OperationStatus value). When the
            server body carries a `status`, pass it so is_success/raise_for_error
            reflect the domain outcome (e.g. already_exists is NOT a success).
        **kwargs: Additional fields for the response class

    Returns:
        Response instance
    """
    response_data = {
        'error_code': 0,
        'error_message': None,
        'status_code': status_code,
        'message': message,
        'status': status,
        'objects': objects,
        **kwargs
    }

    return response_class(**response_data)


def build_response_from_server(
    response_class: Type[T],
    response_data: Dict[str, Any],
    status_code: int = 200,
    objects: Optional[Any] = None,
    **kwargs
) -> T:
    """
    Build a client response from a server response body that follows the unified
    result-status contract (success / status / message in the body).

    Reads `status`, `success`, and `message` from the server body and derives the
    client `error_code` (0 when the domain outcome succeeded, non-zero otherwise)
    so is_success / raise_for_error reflect the DOMAIN outcome rather than the HTTP
    code (which is 200 for every domain outcome).

    Args:
        response_class: Client response class to instantiate
        response_data: Parsed server JSON body
        status_code: HTTP status code of the response
        objects: Optional deserialized objects payload
        **kwargs: Additional fields for the response class

    Returns:
        Response instance
    """
    server_status = response_data.get('status')
    server_success = response_data.get('success')
    message = response_data.get('message')

    if server_status is not None:
        succeeded = server_status in _SUCCESS_STATUS_VALUES
    elif server_success is not None:
        succeeded = bool(server_success)
    else:
        succeeded = True

    data = {
        'error_code': 0 if succeeded else 1,
        'error_message': None if succeeded else message,
        'status_code': status_code,
        'message': message,
        'status': server_status,
        **kwargs,
    }
    if objects is not None or hasattr(response_class, 'objects'):
        data['objects'] = objects

    return response_class(**data)


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
    """Deprecated alias for `format_helpers.extract_pagination_from_json_quads`.

    This was a SECOND copy of the same rule with different answers: `page_size`
    defaulted to 10 rather than 0, and `has_more` defaulted to **False** — the
    defect fixed in the other copy on 2026-08-16, still live here.

    Nothing calls it (it is imported by `kgentities_endpoint` and
    `kgframes_endpoint` and used by neither), so no caller was getting the wrong
    answer — but a dormant second implementation is worse than a used one. It is
    the version the next person copies, and two copies of a rule is how a
    performance heuristic ended up changing regex semantics elsewhere in this
    codebase. Delegating rather than deleting so any out-of-tree caller keeps
    working, with one implementation behind both names.
    """
    from ..utils.format_helpers import extract_pagination_from_json_quads
    return extract_pagination_from_json_quads(response_data)


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


def group_objects_by_frame_graph(
        frame_uris: List[str],
        objects: List[GraphObject]) -> Dict[str, List[GraphObject]]:
    """Split a MERGED object list into one list per frame.

    `issues/240`. The `uris=` endpoint answers N frames in ONE query and returns
    a single flat, de-duplicated object list, so per-frame attribution has to be
    recovered here. `build_frame_graph(uri, objects)` handed EVERY frame the
    WHOLE list — which was invisible while the server returned no graph objects
    at all (each frame got the frames and no slots), and becomes every frame
    claiming every other frame's slots the moment the server starts working.

    `FrameGraph.objects` is documented as "GraphObjects in THIS frame graph", so
    the whole list is a contract violation, not a rounding error.

    THE FOUR LINKAGES MIRROR THE SERVER QUERY, and must stay in step with it:

        the frame itself
        attribute    an object naming the frame in `hasFrameGraphURI`
        connection   an edge whose source IS the frame
        connection   the destination of such an edge (the slot)

    Duplicating them here is the cost of a flat response. The alternative is for
    the endpoint to return the grouping it already computes — which is the
    better end state and a response-shape change, so it is not done here.

    An object may belong to SEVERAL frames (a shared slot); it appears in each,
    matching what a per-frame fetch would have returned.
    """
    wanted = list(dict.fromkeys(frame_uris))
    groups: Dict[str, List[GraphObject]] = {u: [] for u in wanted}
    by_uri = {}
    for o in objects:
        u = str(getattr(o, 'URI', '') or '')
        if u:
            by_uri[u] = o

    # Pass 1 — the frame itself, and anything naming it.
    edges_by_frame: Dict[str, List[str]] = {u: [] for u in wanted}
    for o in objects:
        o_uri = str(getattr(o, 'URI', '') or '')
        if o_uri in groups:
            groups[o_uri].append(o)

        for prop in ('hasFrameGraphURI', 'frameGraphURI'):
            if hasattr(o, prop):
                fg = str(getattr(o, prop) or '')
                if fg in groups and o_uri != fg:
                    groups[fg].append(o)
                break

        # An edge out of a frame belongs to it, and so does what it points at.
        src = dst = None
        for prop in ('hasEdgeSource', 'edgeSource', 'source'):
            if hasattr(o, prop):
                src = str(getattr(o, prop) or '')
                break
        for prop in ('hasEdgeDestination', 'edgeDestination', 'destination'):
            if hasattr(o, prop):
                dst = str(getattr(o, prop) or '')
                break
        if src and src in groups:
            if o_uri != src:
                groups[src].append(o)
            if dst:
                edges_by_frame[src].append(dst)

    # Pass 2 — the slots those edges point at, now that every edge is known.
    for frame_uri, dests in edges_by_frame.items():
        for d in dests:
            obj = by_uri.get(d)
            if obj is not None:
                groups[frame_uri].append(obj)

    # De-dupe per frame, preserving order: a slot reachable by two linkages is
    # one object, not two.
    for frame_uri, objs in groups.items():
        seen = set()
        deduped = []
        for o in objs:
            u = str(getattr(o, 'URI', '') or id(o))
            if u not in seen:
                seen.add(u)
                deduped.append(o)
        groups[frame_uri] = deduped

    return groups


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
