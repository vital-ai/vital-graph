"""
VitalGraph Client Objects Endpoint

Client-side implementation for Objects operations.
"""

import requests
from typing import Dict, Any, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.objects_model import (
    ObjectsResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse
)
from ...model.jsonld_model import JsonLdDocument


class ObjectsEndpoint(BaseEndpoint):
    """Client endpoint for Objects operations."""
    
    def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> ObjectsResponse:
        """
        List Objects with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            ObjectsResponse containing Objects data and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/objects"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            search=search
        )
        
        return self._make_typed_request('GET', url, ObjectsResponse, params=params)
    
    def get_object(self, space_id: str, graph_id: str, uri: str) -> ObjectsResponse:
        """
        Get a specific Object by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI
            
        Returns:
            ObjectsResponse containing Object data
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/objects"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('GET', url, ObjectsResponse, params=params)
    
    def create_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectCreateResponse:
        """
        Create Objects from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing Objects
            
        Returns:
            ObjectCreateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/objects"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('POST', url, ObjectCreateResponse, params=params, json=document.model_dump())
    
    def update_objects(self, space_id: str, graph_id: str, document: JsonLdDocument) -> ObjectUpdateResponse:
        """
        Update Objects from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing Objects
            
        Returns:
            ObjectUpdateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/objects"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('PUT', url, ObjectUpdateResponse, params=params, json=document.model_dump())
    
    def delete_object(self, space_id: str, graph_id: str, uri: str) -> ObjectDeleteResponse:
        """
        Delete an Object by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI to delete
            
        Returns:
            ObjectDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/objects"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('DELETE', url, ObjectDeleteResponse, params=params)
    
    def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> ObjectDeleteResponse:
        """
        Delete multiple Objects by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of Object URIs
            
        Returns:
            ObjectDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        url = f"{self._get_server_url()}/api/graphs/objects"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        return self._make_typed_request('DELETE', url, ObjectDeleteResponse, params=params)
