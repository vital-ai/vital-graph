"""
VitalGraph Client Objects Endpoint

Client-side implementation for Objects operations.
"""

import httpx
from typing import Dict, Any, Optional, List
import logging

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.objects_model import (
    ObjectsResponse as ServerObjectsResponse,
    ObjectCreateResponse as ServerObjectCreateResponse,
    ObjectUpdateResponse as ServerObjectUpdateResponse,
    ObjectDeleteResponse as ServerObjectDeleteResponse
)
from ...model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from ..response.client_response import (
    ObjectResponse,
    ObjectsListResponse,
    ObjectCreateResponse,
    ObjectUpdateResponse,
    ObjectDeleteResponse
)
from ..response.response_builder import build_success_response, build_error_response

logger = logging.getLogger(__name__)


class ObjectsEndpoint(BaseEndpoint):
    """Client endpoint for Objects operations."""
    
    async def list_objects(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, search: Optional[str] = None) -> ObjectsListResponse:
        """
        List Objects with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            
        Returns:
            ObjectsListResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/objects"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                search=search
            )
            
            server_response = await self._make_typed_request('GET', url, ServerObjectsResponse, params=params)
            
            # Extract objects from server response - handle Union[JsonLdObject, JsonLdDocument]
            objects = []
            if hasattr(server_response, 'objects'):
                if isinstance(server_response.objects, JsonLdObject):
                    objects = [server_response.objects]
                elif isinstance(server_response.objects, JsonLdDocument):
                    objects = server_response.objects.graph if server_response.objects.graph else []
            count = len(objects)
            
            return build_success_response(
                ObjectsListResponse,
                status_code=200,
                message=f"Retrieved {count} objects",
                objects=objects,
                count=count,
                page_size=page_size,
                offset=offset
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                ObjectsListResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error listing objects: {e}")
            return build_error_response(
                ObjectsListResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    async def get_object(self, space_id: str, graph_id: str, uri: str) -> ObjectResponse:
        """
        Get a specific Object by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI
            
        Returns:
            ObjectResponse with .object property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/objects"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            server_response = await self._make_typed_request('GET', url, ServerObjectsResponse, params=params)
            
            # Extract single object from server response
            object_data = None
            if hasattr(server_response, 'objects'):
                if isinstance(server_response.objects, JsonLdObject):
                    object_data = server_response.objects
                elif isinstance(server_response.objects, JsonLdDocument):
                    objects = server_response.objects.graph if server_response.objects.graph else []
                    object_data = objects[0] if objects else None
            
            if object_data:
                return build_success_response(
                    ObjectResponse,
                    status_code=200,
                    message=f"Retrieved object: {uri}",
                    object=object_data
                )
            else:
                return build_error_response(
                    ObjectResponse,
                    error_code=404,
                    error_message=f"Object not found: {uri}",
                    status_code=404
                )
            
        except VitalGraphClientError as e:
            return build_error_response(
                ObjectResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error getting object: {e}")
            return build_error_response(
                ObjectResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    async def create_objects(self, space_id: str, graph_id: str, document: JsonLdRequest) -> ObjectCreateResponse:
        """
        Create Objects from JSON-LD request.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD request (JsonLdObject for single object or JsonLdDocument for multiple objects)
            
        Returns:
            ObjectCreateResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/objects"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            server_response = await self._make_typed_request('POST', url, ServerObjectCreateResponse, params=params, json=document.model_dump(by_alias=True))
            
            # Extract created URIs from server response
            created_uris = []
            if hasattr(server_response, 'created_uris'):
                created_uris = server_response.created_uris if isinstance(server_response.created_uris, list) else [server_response.created_uris]
            
            created_count = len(created_uris)
            
            return build_success_response(
                ObjectCreateResponse,
                status_code=200,
                message=f"Created {created_count} objects",
                created=True,
                created_count=created_count,
                created_uris=created_uris
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                ObjectCreateResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error creating objects: {e}")
            return build_error_response(
                ObjectCreateResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    async def update_objects(self, space_id: str, graph_id: str, document: JsonLdRequest) -> ObjectUpdateResponse:
        """
        Update Objects from JSON-LD request.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document: JSON-LD request (JsonLdObject for single object or JsonLdDocument for multiple objects)
            
        Returns:
            ObjectUpdateResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, document=document)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/objects"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id
            )
            
            server_response = await self._make_typed_request('PUT', url, ServerObjectUpdateResponse, params=params, json=document.model_dump(by_alias=True))
            
            # Extract updated URIs from server response
            updated_uris = []
            if hasattr(server_response, 'updated_uris'):
                updated_uris = server_response.updated_uris if isinstance(server_response.updated_uris, list) else [server_response.updated_uris]
            elif hasattr(server_response, 'updated_uri') and server_response.updated_uri:
                updated_uris = [server_response.updated_uri]
            
            updated_count = len(updated_uris)
            
            return build_success_response(
                ObjectUpdateResponse,
                status_code=200,
                message=f"Updated {updated_count} objects",
                updated=True,
                updated_count=updated_count,
                updated_uris=updated_uris
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                ObjectUpdateResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error updating objects: {e}")
            return build_error_response(
                ObjectUpdateResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    async def delete_object(self, space_id: str, graph_id: str, uri: str) -> ObjectDeleteResponse:
        """
        Delete an Object by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Object URI to delete
            
        Returns:
            ObjectDeleteResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/objects"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri
            )
            
            server_response = await self._make_typed_request('DELETE', url, ServerObjectDeleteResponse, params=params)
            
            return build_success_response(
                ObjectDeleteResponse,
                status_code=200,
                message=f"Deleted object: {uri}",
                deleted=True,
                deleted_count=1,
                deleted_uris=[uri]
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                ObjectDeleteResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error deleting object: {e}")
            return build_error_response(
                ObjectDeleteResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
    
    async def delete_objects_batch(self, space_id: str, graph_id: str, uri_list: str) -> ObjectDeleteResponse:
        """
        Delete multiple Objects by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of Object URIs
            
        Returns:
            ObjectDeleteResponse with .is_success property
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/objects"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri_list=uri_list
            )
            
            server_response = await self._make_typed_request('DELETE', url, ServerObjectDeleteResponse, params=params)
            
            # Extract deletion info from server response
            deleted_uris = uri_list.split(',') if uri_list else []
            deleted_count = len(deleted_uris)
            
            return build_success_response(
                ObjectDeleteResponse,
                status_code=200,
                message=f"Deleted {deleted_count} objects",
                deleted=True,
                deleted_count=deleted_count,
                deleted_uris=deleted_uris
            )
            
        except VitalGraphClientError as e:
            return build_error_response(
                ObjectDeleteResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500
            )
        except Exception as e:
            logger.error(f"Error deleting objects batch: {e}")
            return build_error_response(
                ObjectDeleteResponse,
                error_code=500,
                error_message=str(e),
                status_code=500
            )
