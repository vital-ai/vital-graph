"""
VitalGraph Client KGEntities Endpoint

Client-side implementation for KGEntities operations.
"""

import requests
from typing import Dict, Any, Optional, Union, List

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgentities_model import (
    EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse,
    EntityFramesResponse, EntityFramesMultiResponse,
    EntityQueryRequest, EntityQueryResponse, EntityGraphResponse, EntityGraphDeleteResponse,
    EntitiesGraphResponse
)
from ...model.kgframes_model import FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
from ...model.jsonld_model import JsonLdDocument, JsonLdObject


class KGEntitiesEndpoint(BaseEndpoint):
    """Client endpoint for KGEntities operations."""
    
    def _make_request(self, method: str, url: str, params=None, json=None):
        """
        Make HTTP request and return response object.
        Helper method for handling Union response types.
        """
        import time
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Extract operation name from URL for logging
            url_parts = url.split('/')
            operation = url_parts[-1] if url_parts else 'request'
            
            start_time = time.time()
            if method == 'GET':
                response = self.client.session.get(url, params=params)
            elif method == 'POST':
                response = self.client.session.post(url, params=params, json=json)
            elif method == 'DELETE':
                response = self.client.session.delete(url, params=params)
            else:
                raise VitalGraphClientError(f"Unsupported HTTP method: {method}")
            
            duration = time.time() - start_time
            logger.info(f"⏱️  {method} {operation}: {duration:.3f}s")
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Request failed: {str(e)}")
    
    def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                       entity_type_uri: Optional[str] = None, search: Optional[str] = None, 
                       include_entity_graph: bool = False) -> Union[EntitiesResponse, JsonLdDocument]:
        """
        List KGEntities with pagination and optional filtering.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            entity_type_uri: Optional entity type URI to filter by
            search: Optional search term
            include_entity_graph: If True, include complete entity graphs
            
        Returns:
            Union[EntitiesResponse, JsonLdDocument] depending on include_entity_graph parameter
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            entity_type_uri=entity_type_uri,
            search=search,
            include_entity_graph=include_entity_graph
        )
        
        # Handle Union response type
        response = self._make_request('GET', url, params=params)
        response_data = response.json()
        
        if include_entity_graph:
            # Server always returns EntitiesResponse, but when include_entity_graph=True,
            # the entities field contains the JsonLdDocument we want
            entities_response = EntitiesResponse(**response_data)
            return entities_response.entities  # This is the JsonLdDocument
        else:
            return EntitiesResponse(**response_data)
    
    def get_kgentity(self, space_id: str, graph_id: str, uri: Optional[str] = None, 
                    reference_id: Optional[str] = None, include_entity_graph: bool = False) -> Union[EntitiesResponse, JsonLdDocument, JsonLdObject]:
        """
        Get a specific KGEntity by URI or reference ID with optional complete graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGEntity URI (mutually exclusive with reference_id)
            reference_id: Reference ID (mutually exclusive with uri)
            include_entity_graph: If True, include complete entity graph (entity + frames + slots + edges)
            
        Returns:
            Union[EntitiesResponse, JsonLdDocument, JsonLdObject] depending on response structure
            
        Raises:
            VitalGraphClientError: If request fails or both uri and reference_id are provided
        """
        self._check_connection()
        
        # Validate mutually exclusive parameters
        if uri and reference_id:
            raise VitalGraphClientError("Cannot specify both uri and reference_id")
        if not uri and not reference_id:
            raise VitalGraphClientError("Must specify either uri or reference_id")
        
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        
        # Build params with either uri or reference_id
        params_dict = {
            'space_id': space_id,
            'graph_id': graph_id,
            'include_entity_graph': include_entity_graph
        }
        
        if uri:
            params_dict['uri'] = uri
        else:
            params_dict['id'] = reference_id
        
        params = build_query_params(**params_dict)
        
        # Handle Union response type
        response = self._make_request('GET', url, params=params)
        response_data = response.json()
        
        # Check if response is a JsonLdObject (single entity) or JsonLdDocument (multiple/graph)
        if '@id' in response_data and '@type' in response_data:
            # Single entity response as JsonLdObject
            return JsonLdObject(**response_data)
        elif '@graph' in response_data:
            # Multiple entities or entity graph as JsonLdDocument
            return JsonLdDocument(**response_data)
        else:
            # Fallback to EntitiesResponse for pagination responses
            return EntitiesResponse(**response_data)
    
    def get_kgentities_by_reference_ids(self, space_id: str, graph_id: str, reference_ids: List[str], 
                                        include_entity_graph: bool = False) -> Union[JsonLdDocument, EntitiesGraphResponse]:
        """
        Get multiple KGEntities by reference ID list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            reference_ids: List of reference IDs
            include_entity_graph: If True, include complete entity graphs
            
        Returns:
            Union[JsonLdDocument, EntitiesGraphResponse] depending on include_entity_graph parameter
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, reference_ids=reference_ids)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            id_list=",".join(reference_ids),
            include_entity_graph=include_entity_graph
        )
        
        # Handle Union response type
        response = self._make_request('GET', url, params=params)
        response_data = response.json()
        
        # Check if response contains entity graphs
        if include_entity_graph and 'entity_graphs' in response_data:
            return EntitiesGraphResponse(**response_data)
        elif '@graph' in response_data:
            return JsonLdDocument(**response_data)
        else:
            # Fallback - convert to JsonLdDocument
            return JsonLdDocument(graph=response_data.get('entities', []))
    
    def upsert_kgentities(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument], 
                         parent_uri: Optional[str] = None) -> Union[EntityCreateResponse, EntityUpdateResponse]:
        """
        Create or update KGEntities (UPSERT operation).
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD data - either single object or document with @graph array
            parent_uri: Optional parent URI for relationships
            
        Returns:
            Union[EntityCreateResponse, EntityUpdateResponse] depending on whether entities existed
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, data=data)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        
        # Set discriminator field based on type before sending
        if isinstance(data, JsonLdObject):
            data.jsonld_type = 'object'
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = 'document'
        
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            operation_mode="upsert",
            parent_uri=parent_uri
        )
        
        response = self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
        response_data = response.json()
        
        # Try to determine if it was create or update based on response structure
        try:
            return EntityCreateResponse(**response_data)
        except:
            return EntityUpdateResponse(**response_data)
    
    def create_kgentities(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument], 
                         parent_uri: Optional[str] = None) -> Union[EntityCreateResponse, EntityUpdateResponse]:
        """
        Create KGEntities from JSON-LD data with automatic hasKGGraphURI assignment.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD data - either single object or document with @graph array
            parent_uri: Optional parent URI for relationships
            
        Returns:
            Union[EntityCreateResponse, EntityUpdateResponse] from server
            
        Note:
            Server automatically strips any existing hasKGGraphURI values from the data and sets
            hasKGGraphURI to the entity URI for all members of the entity graph (entity + frames + slots + hasSlot edges + other edges).
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, data=data)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        
        # Set discriminator field based on type before sending
        if isinstance(data, JsonLdObject):
            data.jsonld_type = 'object'
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = 'document'
        
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            operation_mode="create",
            parent_uri=parent_uri
        )
        
        # Server returns Union type, but for create operation it will be EntityCreateResponse
        response = self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
        return EntityCreateResponse(**response.json())
    
    def update_kgentities(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument], 
                         parent_uri: Optional[str] = None) -> Union[EntityCreateResponse, EntityUpdateResponse]:
        """
        Update KGEntities from JSON-LD data with automatic hasKGGraphURI management.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD data - either single object or document with @graph array
            parent_uri: Optional parent URI for relationships
            
        Returns:
            Union[EntityCreateResponse, EntityUpdateResponse] from server
            
        Note:
            Server automatically strips any existing hasKGGraphURI values from the data and sets
            hasKGGraphURI to the entity URI for all members of the entity graph (entity + frames + slots + hasSlot edges + other edges).
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, data=data)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        
        # Set discriminator field based on type before sending
        if isinstance(data, JsonLdObject):
            data.jsonld_type = 'object'
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = 'document'
        
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            operation_mode="update",
            parent_uri=parent_uri
        )
        
        # Changed from PUT to POST to match server implementation
        response = self._make_request('POST', url, params=params, json=data.model_dump(by_alias=True))
        return EntityUpdateResponse(**response.json())
    
    def delete_kgentity(self, space_id: str, graph_id: str, uri: str, delete_entity_graph: bool = False) -> EntityGraphDeleteResponse:
        """
        Delete a KGEntity by URI with optional complete graph deletion.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGEntity URI to delete
            delete_entity_graph: If True, delete entire entity graph (entity + frames + slots + edges)
            
        Returns:
            EntityGraphDeleteResponse containing operation result and deleted components info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri,
            delete_entity_graph=delete_entity_graph
        )
        
        return self._make_typed_request('DELETE', url, EntityGraphDeleteResponse, params=params)
    
    def delete_kgentities_batch(self, space_id: str, graph_id: str, uri_list: str) -> EntityDeleteResponse:
        """
        Delete multiple KGEntities by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGEntity URIs
            
        Returns:
            EntityDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        return self._make_typed_request('DELETE', url, EntityDeleteResponse, params=params)
    
    # KGEntities with Frames operations
    # Note: Server-side implementation may not be complete yet
    
    def get_kgentity_frames(self, space_id: str, graph_id: str, entity_uri: Optional[str] = None, 
                           frame_uris: Optional[List[str]] = None, parent_frame_uri: Optional[str] = None,
                           page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> Union[EntityFramesResponse, 'FrameGraphsResponse']:
        """
        Get frames associated with KGEntities.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Specific entity URI to get frames for (optional)
            frame_uris: Specific frame URIs to retrieve (optional) - returns FrameGraphsResponse
            parent_frame_uri: Parent frame URI for hierarchical filtering (optional)
                - If None: Returns top-level frames (children of entity via Edge_hasEntityKGFrame)
                - If provided: Returns only frames that are children of the specified parent frame
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            EntityFramesResponse for listing frames (when frame_uris not provided)
            FrameGraphsResponse for specific frames (when frame_uris provided)
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            frame_uris=frame_uris,
            parent_frame_uri=parent_frame_uri,
            page_size=page_size,
            offset=offset,
            search=search
        )
        
        # Server returns different response type based on frame_uris parameter
        if frame_uris:
            from ...model.kgframes_model import FrameGraphsResponse
            return self._make_typed_request('GET', url, FrameGraphsResponse, params=params)
        else:
            return self._make_typed_request('GET', url, EntityFramesResponse, params=params)
    
    # Entity-Frame Sub-Endpoint Operations
    
    def create_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument, 
                            parent_frame_uri: Optional[str] = None) -> FrameCreateResponse:
        """
        Create frames for a specific entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to create frames for
            document: JsonLdDocument containing KGFrames and slots
            parent_frame_uri: Optional parent frame URI for hierarchical frame relationships
            
        Returns:
            FrameCreateResponse containing operation result
            
        Note:
            Server automatically sets hasKGGraphURI to entity_uri for all components.
            Server automatically sets hasFrameGraphURI to frame URI for frame-specific components.
            If parent_frame_uri is provided, creates hierarchical frame relationship.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            parent_frame_uri=parent_frame_uri
        )
        
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=document.dict())
    
    def update_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument,
                            parent_frame_uri: Optional[str] = None) -> FrameUpdateResponse:
        """
        Update frames for a specific entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to update frames for
            document: JsonLdDocument containing updated KGFrames and slots
            parent_frame_uri: Parent frame URI for scoped updates (optional)
                - If None: Updates top-level frames (children of entity via Edge_hasEntityKGFrame)
                - If provided: Only updates frames that are children of the specified parent frame
            
        Returns:
            FrameUpdateResponse containing operation result
            
        Note:
            Server automatically sets hasKGGraphURI to entity_uri for all components.
            Server preserves existing hasFrameGraphURI values unless explicitly provided.
            Validates frame ownership before updating when parent_frame_uri is provided.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            parent_frame_uri=parent_frame_uri,
            operation_mode="update"
        )
        
        return self._make_typed_request('POST', url, FrameUpdateResponse, params=params, json=document.dict())
    
    def delete_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: list[str],
                            parent_frame_uri: Optional[str] = None) -> FrameDeleteResponse:
        """
        Delete specific frames from an entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to delete frames from
            frame_uris: List of frame URIs to delete
            parent_frame_uri: Parent frame URI for validation (optional)
                - If None: Deletes specified top-level frames (children of entity via Edge_hasEntityKGFrame)
                - If provided: Validates frames are children of parent frame before deletion
            
        Returns:
            FrameDeleteResponse containing operation result
            
        Note:
            Provides safety check against accidental deletion of wrong frames when parent_frame_uri is provided.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, frame_uris=frame_uris)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            frame_uris=','.join(frame_uris),
            parent_frame_uri=parent_frame_uri
        )
        
        return self._make_typed_request('DELETE', url, FrameDeleteResponse, params=params)
    
    def get_entity_frames(self, space_id: str, graph_id: str, entity_uri: str) -> JsonLdDocument:
        """
        Get all frames for a specific entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to get frames for
            
        Returns:
            JsonLdDocument containing entity's frames and slots
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri
        )
        
        # Server returns nested structure with JsonLdDocument in 'frames' field
        response = self._make_authenticated_request('GET', url, params=params)
        response_data = response.json()
        
        # Extract the frames field which contains the actual JsonLdDocument
        if 'frames' in response_data:
            frames_data = response_data['frames']
            return self._parse_response(frames_data, JsonLdDocument)
        else:
            raise VitalGraphClientError(f"Server response missing 'frames' field: {response_data}")
        
    
    # Enhanced Graph Operations
    
    def query_entities(self, space_id: str, graph_id: str, query_request: EntityQueryRequest) -> EntityQueryResponse:
        """
        Query KGEntities using criteria-based search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            query_request: EntityQueryRequest containing search criteria and pagination
            
        Returns:
            EntityQueryResponse containing list of matching entity URIs and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, query_request=query_request)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/query"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('POST', url, EntityQueryResponse, params=params, json=query_request.dict())
    
    def list_kgentities_with_graphs(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, 
                                   search: Optional[str] = None, include_entity_graphs: bool = False) -> EntitiesGraphResponse:
        """
        List KGEntities with optional complete graphs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            include_entity_graphs: If True, include complete entity graphs for all entities
            
        Returns:
            EntitiesGraphResponse containing entities and optional complete graphs
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            search=search,
            include_entity_graphs=include_entity_graphs
        )
        
        return self._make_typed_request('GET', url, EntitiesGraphResponse, params=params)
