"""
VitalGraph Client KGFrames Endpoint

Client-side implementation for KGFrames operations.
"""

import requests
from typing import Dict, Any, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse
)
from ...model.jsonld_model import JsonLdDocument


class KGFramesEndpoint(BaseEndpoint):
    """Client endpoint for KGFrames operations."""
    
    def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> FramesResponse:
        """
        List KGFrames with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            FramesResponse containing KGFrames data and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            search=search
        )
        
        return self._make_typed_request('GET', url, FramesResponse, params=params)
    
    def get_kgframe(self, space_id: str, graph_id: str, uri: str) -> FramesResponse:
        """
        Get a specific KGFrame by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI
            
        Returns:
            FramesResponse containing KGFrame data
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('GET', url, FramesResponse, params=params)
    
    def create_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
        """
        Create KGFrames from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames
            
        Returns:
            FrameCreateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=document.model_dump())
    
    def update_kgframes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameUpdateResponse:
        """
        Update KGFrames from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames
            
        Returns:
            FrameUpdateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('PUT', url, FrameUpdateResponse, params=params, json=document.model_dump())
    
    def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> FrameDeleteResponse:
        """
        Delete a KGFrame by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI to delete
            
        Returns:
            FrameDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('DELETE', url, FrameDeleteResponse, params=params)
    
    def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> FrameDeleteResponse:
        """
        Delete multiple KGFrames by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGFrame URIs
            
        Returns:
            FrameDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        return self._make_typed_request('DELETE', url, FrameDeleteResponse, params=params)
    
    # KGFrames with Slots operations
    # Note: Server-side implementation may not be complete yet
    
    def get_kgframes_with_slots(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> FramesResponse:
        """
        Get KGFrames with their associated slots.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            FramesResponse containing KGFrames with slots data and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            search=search
        )
        
        return self._make_typed_request('GET', url, FramesResponse, params=params)
    
    def create_kgframes_with_slots(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameCreateResponse:
        """
        Create KGFrames with their associated slots from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames with slots
            
        Returns:
            FrameCreateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=document.model_dump())
    
    def update_kgframes_with_slots(self, space_id: str, graph_id: str, document: JsonLdDocument) -> FrameUpdateResponse:
        """
        Update KGFrames with their associated slots from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGFrames with slots
            
        Returns:
            FrameUpdateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('PUT', url, FrameUpdateResponse, params=params, json=document.model_dump())
    
    def delete_kgframes_with_slots(self, space_id: str, graph_id: str, uri_list: str) -> FrameDeleteResponse:
        """
        Delete KGFrames with their associated slots by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGFrame URIs
            
        Returns:
            FrameDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        return self._make_typed_request('DELETE', url, FrameDeleteResponse, params=params)
