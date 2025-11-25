"""
VitalGraph Client KGEntities Endpoint

Client-side implementation for KGEntities operations.
"""

import requests
from typing import Dict, Any, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgentities_model import (
    EntitiesResponse, EntityCreateResponse, EntityUpdateResponse, EntityDeleteResponse,
    EntityFramesResponse, EntityFramesMultiResponse,
    EntityQueryRequest, EntityQueryResponse, EntityGraphResponse, EntityGraphDeleteResponse,
    EntitiesGraphResponse
)
from ...model.kgframes_model import FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
from ...model.jsonld_model import JsonLdDocument


class KGEntitiesEndpoint(BaseEndpoint):
    """Client endpoint for KGEntities operations."""
    
    def list_kgentities(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> EntitiesResponse:
        """
        List KGEntities with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            EntitiesResponse containing KGEntities data and pagination info
            
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
            search=search
        )
        
        return self._make_typed_request('GET', url, EntitiesResponse, params=params)
    
    def get_kgentity(self, space_id: str, graph_id: str, uri: str, include_entity_graph: bool = False) -> EntityGraphResponse:
        """
        Get a specific KGEntity by URI with optional complete graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGEntity URI
            include_entity_graph: If True, include complete entity graph (entity + frames + slots + edges)
            
        Returns:
            EntityGraphResponse containing KGEntity data and optional complete graph
            
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
            include_entity_graph=include_entity_graph
        )
        
        return self._make_typed_request('GET', url, EntityGraphResponse, params=params)
    
    def create_kgentities(self, space_id: str, graph_id: str, document: Dict[str, Any]) -> EntityCreateResponse:
        """
        Create KGEntities from JSON-LD document with automatic hasKGGraphURI assignment.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGEntities
            
        Returns:
            EntityCreateResponse containing operation result
            
        Note:
            Server automatically strips any existing hasKGGraphURI values from the document and sets
            hasKGGraphURI to the entity URI for all members of the entity graph (entity + frames + slots + hasSlot edges + other edges).
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('POST', url, EntityCreateResponse, params=params, json=document)
    
    def update_kgentities(self, space_id: str, graph_id: str, document: Dict[str, Any]) -> EntityUpdateResponse:
        """
        Update KGEntities from JSON-LD document with automatic hasKGGraphURI management.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGEntities
            
        Returns:
            EntityUpdateResponse containing operation result
            
        Note:
            Server automatically strips any existing hasKGGraphURI values from the document and sets
            hasKGGraphURI to the entity URI for all members of the entity graph (entity + frames + slots + hasSlot edges + other edges).
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('PUT', url, EntityUpdateResponse, params=params, json=document)
    
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
                           page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> EntityFramesResponse:
        """
        Get frames associated with KGEntities.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Specific entity URI to get frames for (optional)
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            EntityFramesResponse containing entity frames data and pagination info
            
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
            page_size=page_size,
            offset=offset,
            search=search
        )
        
        return self._make_typed_request('GET', url, EntityFramesResponse, params=params)
    
    # Entity-Frame Sub-Endpoint Operations
    
    def create_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument) -> FrameCreateResponse:
        """
        Create frames for a specific entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to create frames for
            document: JsonLdDocument containing KGFrames and slots
            
        Returns:
            FrameCreateResponse containing operation result
            
        Note:
            Server automatically sets hasKGGraphURI to entity_uri for all components.
            Server automatically sets hasFrameGraphURI to frame URI for frame-specific components.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri
        )
        
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=document.dict())
    
    def update_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument) -> FrameUpdateResponse:
        """
        Update frames for a specific entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to update frames for
            document: JsonLdDocument containing updated KGFrames and slots
            
        Returns:
            FrameUpdateResponse containing operation result
            
        Note:
            Server automatically sets hasKGGraphURI to entity_uri for all components.
            Server preserves existing hasFrameGraphURI values unless explicitly provided.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, entity_uri=entity_uri, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgentities/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri
        )
        
        return self._make_typed_request('PUT', url, FrameUpdateResponse, params=params, json=document.dict())
    
    def delete_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: list[str]) -> FrameDeleteResponse:
        """
        Delete specific frames from an entity.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            entity_uri: Entity URI to delete frames from
            frame_uris: List of frame URIs to delete
            
        Returns:
            FrameDeleteResponse containing operation result
            
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
            frame_uris=','.join(frame_uris)
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
        
        return self._make_typed_request('GET', url, JsonLdDocument, params=params)
    
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
