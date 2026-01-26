"""
VitalGraph Client KGTypes Endpoint

Client-side implementation for KGTypes operations.
"""

import requests
from typing import Dict, Any, Optional, Union, List
import logging

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgtypes_model import (
    KGTypeListResponse as ServerKGTypeListResponse,
    KGTypeCreateResponse as ServerKGTypeCreateResponse,
    KGTypeUpdateResponse as ServerKGTypeUpdateResponse,
    KGTypeDeleteResponse as ServerKGTypeDeleteResponse,
    KGTypeGetResponse as ServerKGTypeGetResponse
)
from ...model.jsonld_model import JsonLdDocument, JsonLdObject
from ..response.client_response import (
    KGTypeResponse,
    KGTypesListResponse,
    KGTypeCreateResponse,
    KGTypeUpdateResponse,
    KGTypeDeleteResponse
)
from ..response.response_builder import build_success_response, build_error_response

logger = logging.getLogger(__name__)


class KGTypesEndpoint(BaseEndpoint):
    """Client endpoint for KGTypes operations."""
    
    def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> KGTypesListResponse:
        """
        List KGTypes with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            KGTypesListResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                search=search
            )
            
            server_response = self._make_typed_request('GET', url, ServerKGTypeListResponse, params=params)
            
            # Extract types from server response - handle data field from server
            types = []
            if hasattr(server_response, 'data'):
                from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
                if isinstance(server_response.data, JsonLdObject):
                    types = [server_response.data]
                elif isinstance(server_response.data, JsonLdDocument):
                    types = server_response.data.graph if server_response.data.graph else []
            count = len(types)
            
            return build_success_response(
                KGTypesListResponse,
                status_code=200,
                message=f"Retrieved {count} KGTypes",
                types=types,
                count=count,
                page_size=page_size,
                offset=offset
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                KGTypesListResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error listing KGTypes: {e}")
            return build_error_response(
                KGTypesListResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeResponse:
        """
        Get a specific KGType by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGType URI
            
        Returns:
            KGTypeResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            # Try KGTypeGetResponse first, fall back to KGTypeListResponse (exactly like original)
            kgtype_data = None
            try:
                server_response = self._make_typed_request('GET', url, ServerKGTypeGetResponse, params=params)
                # Extract from data field
                if hasattr(server_response, 'data'):
                    kgtype_data = server_response.data
            except Exception:
                # Fallback to list response
                server_response = self._make_typed_request('GET', url, ServerKGTypeListResponse, params=params)
                if hasattr(server_response, 'data'):
                    from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
                    if isinstance(server_response.data, JsonLdObject):
                        kgtype_data = server_response.data
                    elif isinstance(server_response.data, JsonLdDocument):
                        types = server_response.data.graph if server_response.data.graph else []
                        kgtype_data = types[0] if types else None
            
            if kgtype_data:
                return build_success_response(
                    KGTypeResponse,
                    status_code=200,
                    message=f"Retrieved KGType: {uri}",
                    type=kgtype_data
                )
            else:
                return build_error_response(
                    KGTypeResponse,
                    error_code=404,
                    error_message=f"KGType not found: {uri}",
                    status_code=404
                )
            
        except VitalGraphClientError as e:
            return build_error_response(
                KGTypeResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error getting KGType: {e}")
            return build_error_response(
                KGTypeResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    def get_kgtypes_by_uris(self, space_id: str, graph_id: str, uri_list: str) -> KGTypesListResponse:
        """
        Get multiple KGTypes by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGType URIs
            
        Returns:
            KGTypesListResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri_list=uri_list
            )
            
            server_response = self._make_typed_request('GET', url, ServerKGTypeListResponse, params=params)
            
            # Extract types from server response - handle data field from server
            types = []
            if hasattr(server_response, 'data'):
                from vitalgraph.model.jsonld_model import JsonLdObject, JsonLdDocument
                if isinstance(server_response.data, JsonLdObject):
                    types = [server_response.data]
                elif isinstance(server_response.data, JsonLdDocument):
                    types = server_response.data.graph if server_response.data.graph else []
            count = len(types)
            
            return build_success_response(
                KGTypesListResponse,
                status_code=200,
                message=f"Retrieved {count} KGTypes",
                types=types,
                count=count
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                KGTypesListResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error getting KGTypes by URIs: {e}")
            return build_error_response(
                KGTypesListResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    def create_kgtypes(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument]) -> KGTypeCreateResponse:
        """
        Create KGTypes from JSON-LD data.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD data - either single object or document with @graph array
            
        Returns:
            KGTypeCreateResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, data=data)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            
            # Set discriminator field based on type before wrapping in request
            if isinstance(data, JsonLdObject):
                data.jsonld_type = 'object'
            elif isinstance(data, JsonLdDocument):
                data.jsonld_type = 'document'
            
            # Build request body with space_id, graph_id, and data
            request_body = {
                'space_id': space_id,
                'graph_id': graph_id,
                'data': data.model_dump(by_alias=True)
            }
            
            server_response = self._make_typed_request('POST', url, ServerKGTypeCreateResponse, json=request_body)
            
            # Extract created URIs from server response
            created_uris = []
            if hasattr(server_response, 'created_uris'):
                created_uris = server_response.created_uris if isinstance(server_response.created_uris, list) else [server_response.created_uris]
            elif hasattr(server_response, 'message'):
                # Try to extract URIs from message if available
                pass
            
            created_count = len(created_uris)
            
            return build_success_response(
                KGTypeCreateResponse,
                status_code=200,
                message=f"Created {created_count} KGTypes",
                created=True,
                created_count=created_count,
                created_uris=created_uris
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                KGTypeCreateResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error creating KGTypes: {e}")
            return build_error_response(
                KGTypeCreateResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    def update_kgtypes(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument]) -> KGTypeUpdateResponse:
        """
        Update KGTypes from JSON-LD data.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD data - either single object or document with @graph array
            
        Returns:
            KGTypeUpdateResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, data=data)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            
            # Set discriminator field based on type before wrapping in request
            if isinstance(data, JsonLdObject):
                data.jsonld_type = 'object'
            elif isinstance(data, JsonLdDocument):
                data.jsonld_type = 'document'
            
            # Build request body with space_id, graph_id, and data
            request_body = {
                'space_id': space_id,
                'graph_id': graph_id,
                'data': data.model_dump(by_alias=True)
            }
            
            server_response = self._make_typed_request('PUT', url, ServerKGTypeUpdateResponse, json=request_body)
            
            # Extract updated URIs from server response
            updated_uris = []
            if hasattr(server_response, 'updated_uris'):
                updated_uris = server_response.updated_uris if isinstance(server_response.updated_uris, list) else [server_response.updated_uris]
            elif hasattr(server_response, 'updated_uri') and server_response.updated_uri:
                updated_uris = [server_response.updated_uri]
            
            updated_count = len(updated_uris)
            
            return build_success_response(
                KGTypeUpdateResponse,
                status_code=200,
                message=f"Updated {updated_count} KGTypes",
                updated=True,
                updated_count=updated_count,
                updated_uris=updated_uris
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                KGTypeUpdateResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error updating KGTypes: {e}")
            return build_error_response(
                KGTypeUpdateResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeDeleteResponse:
        """
        Delete a KGType by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGType URI to delete
            
        Returns:
            KGTypeDeleteResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            server_response = self._make_typed_request('DELETE', url, ServerKGTypeDeleteResponse, params=params)
            
            # Extract deletion info from server response
            deleted = True
            deleted_count = 1
            deleted_uris = [uri]
            
            return build_success_response(
                KGTypeDeleteResponse,
                status_code=200,
                message=f"Deleted KGType: {uri}",
                deleted=deleted,
                deleted_count=deleted_count,
                deleted_uris=deleted_uris
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                KGTypeDeleteResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error deleting KGType: {e}")
            return build_error_response(
                KGTypeDeleteResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> KGTypeDeleteResponse:
        """
        Delete multiple KGTypes by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGType URIs
            
        Returns:
            KGTypeDeleteResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri_list=uri_list
            )
            
            server_response = self._make_typed_request('DELETE', url, ServerKGTypeDeleteResponse, params=params)
            
            # Extract deletion info from server response
            deleted_uris = uri_list.split(',') if uri_list else []
            deleted_count = len(deleted_uris)
            
            return build_success_response(
                KGTypeDeleteResponse,
                status_code=200,
                message=f"Deleted {deleted_count} KGTypes",
                deleted=True,
                deleted_count=deleted_count,
                deleted_uris=deleted_uris
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                KGTypeDeleteResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error deleting KGTypes batch: {e}")
            return build_error_response(
                KGTypeDeleteResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
