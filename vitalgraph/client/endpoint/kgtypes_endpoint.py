"""
VitalGraph Client KGTypes Endpoint

Client-side implementation for KGTypes operations.
"""

import httpx
from typing import Dict, Any, Optional, Union, List
import logging

from .base_endpoint import BaseEndpoint
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..utils.format_helpers import (
    ClientWireFormat,
    serialize_graphobjects_for_request,
    deserialize_response_to_graphobjects,
    extract_pagination_from_json_quads,
    is_json_quads_response,
)
from ...model.kgtypes_model import (
    KGTypeCreateResponse as ServerKGTypeCreateResponse,
    KGTypeUpdateResponse as ServerKGTypeUpdateResponse,
    KGTypeDeleteResponse as ServerKGTypeDeleteResponse,
)
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
    
    async def list_kgtypes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> KGTypesListResponse:
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
            
            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            graph_objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS)
            pagination = extract_pagination_from_json_quads(response_data)
            return build_success_response(
                KGTypesListResponse,
                status_code=200,
                message=f"Retrieved {len(graph_objects)} KGTypes",
                types=graph_objects,
                count=pagination.get('total_count', len(graph_objects)),
                page_size=pagination.get('page_size', page_size),
                offset=pagination.get('offset', offset)
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
    
    async def get_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeResponse:
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
            
            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            graph_objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS)
            if graph_objects:
                return build_success_response(
                    KGTypeResponse,
                    status_code=200,
                    message=f"Retrieved KGType: {uri}",
                    type=graph_objects[0]
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
    
    async def get_kgtypes_by_uris(self, space_id: str, graph_id: str, uri_list: str) -> KGTypesListResponse:
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
            
            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            graph_objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS)
            return build_success_response(
                KGTypesListResponse,
                status_code=200,
                message=f"Retrieved {len(graph_objects)} KGTypes",
                types=graph_objects,
                count=len(graph_objects)
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
    
    async def create_kgtypes(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> KGTypeCreateResponse:
        """
        Create KGTypes from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of KGType GraphObject instances to create
            
        Returns:
            KGTypeCreateResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, objects=objects)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            params = build_query_params(space_id=space_id, graph_id=graph_id)
            response = await self._make_authenticated_request('POST', url, params=params, json=body, headers={'Content-Type': content_type})
            server_response = ServerKGTypeCreateResponse.model_validate(response.json())
            
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
    
    async def update_kgtypes(self, space_id: str, graph_id: str, objects: List[GraphObject]) -> KGTypeUpdateResponse:
        """
        Update KGTypes from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of KGType GraphObject instances to update
            
        Returns:
            KGTypeUpdateResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, objects=objects)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgtypes"
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            params = build_query_params(space_id=space_id, graph_id=graph_id)
            response = await self._make_authenticated_request('PUT', url, params=params, json=body, headers={'Content-Type': content_type})
            server_response = ServerKGTypeUpdateResponse.model_validate(response.json())
            
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
    
    async def delete_kgtype(self, space_id: str, graph_id: str, uri: str) -> KGTypeDeleteResponse:
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
            
            server_response = await self._make_typed_request('DELETE', url, ServerKGTypeDeleteResponse, params=params)
            
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
    
    async def delete_kgtypes_batch(self, space_id: str, graph_id: str, uri_list: str) -> KGTypeDeleteResponse:
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
            
            server_response = await self._make_typed_request('DELETE', url, ServerKGTypeDeleteResponse, params=params)
            
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
