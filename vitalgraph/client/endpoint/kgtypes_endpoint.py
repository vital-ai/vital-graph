"""
VitalGraph Client KGTypes Endpoint

Client-side implementation for KGTypes operations.
"""

import requests
from typing import Dict, Any, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgtypes_model import (
    KGTypeListResponse, KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse,
    KGTypeListRequest
)
from ...model.jsonld_model import JsonLdDocument


class KGTypesEndpoint(BaseEndpoint):
    """Client endpoint for KGTypes operations."""
    
    def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> KGTypeListResponse:
        """
        List KGTypes with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            KGTypeListResponse containing KGTypes data and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        url = f"{self._get_server_url()}/api/graphs/kgtypes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            page_size=page_size,
            offset=offset,
            search=search
        )
        
        return self._make_typed_request('GET', url, KGTypeListResponse, params=params)
    
    def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeListResponse:
        """
        Get a specific KGType by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGType URI
            
        Returns:
            KGTypeListResponse containing KGType data
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgtypes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('GET', url, KGTypeListResponse, params=params)
    
    def create_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> KGTypeCreateResponse:
        """
        Create KGTypes from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGTypes
            
        Returns:
            KGTypeCreateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgtypes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        # Wrap the document in KGTypeListRequest as expected by server
        request_data = KGTypeListRequest(document=document)
        return self._make_typed_request('POST', url, KGTypeCreateResponse, params=params, json=request_data.model_dump())
    
    def update_kgtypes(self, space_id: str, graph_id: str, document: JsonLdDocument) -> KGTypeUpdateResponse:
        """
        Update KGTypes from JSON-LD document.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD document containing KGTypes
            
        Returns:
            KGTypeUpdateResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        url = f"{self._get_server_url()}/api/graphs/kgtypes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        # Wrap the document in KGTypeListRequest as expected by server
        request_data = KGTypeListRequest(document=document)
        return self._make_typed_request('PUT', url, KGTypeUpdateResponse, params=params, json=request_data.model_dump())
    
    def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeDeleteResponse:
        """
        Delete a KGType by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGType URI to delete
            
        Returns:
            KGTypeDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgtypes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri
        )
        
        return self._make_typed_request('DELETE', url, KGTypeDeleteResponse, params=params)
    
    def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> KGTypeDeleteResponse:
        """
        Delete multiple KGTypes by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGType URIs
            
        Returns:
            KGTypeDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        url = f"{self._get_server_url()}/api/graphs/kgtypes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        return self._make_typed_request('DELETE', url, KGTypeDeleteResponse, params=params)
