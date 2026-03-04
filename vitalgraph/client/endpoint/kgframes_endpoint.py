"""
VitalGraph Client KGFrames Endpoint - Refactored with Standardized Responses

Client-side implementation for KGFrames operations.
All responses contain VitalSigns GraphObjects, hiding wire format complexity.
"""

import httpx
import time
import logging
from typing import Dict, Any, Optional, Union, List

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.vitalsigns import VitalSigns

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..utils.format_helpers import (
    ClientWireFormat,
    serialize_graphobjects_for_request,
    deserialize_response_to_graphobjects,
    extract_pagination_from_json_quads,
    is_json_quads_response,
)
from ..response.client_response import (
    FrameResponse,
    FrameGraphResponse,
    PaginatedGraphObjectResponse,
    MultiFrameGraphResponse,
    CreateEntityResponse,
    UpdateEntityResponse,
    DeleteResponse,
    FrameGraph,
)
from ..response.response_builder import (
    build_success_response,
    build_error_response,
    build_frame_graph,
    count_object_types,
    extract_pagination_metadata,
)
from ...model.kgframes_model import (
    FrameQueryRequest, FrameQueryResponse,
)

logger = logging.getLogger(__name__)


class KGFramesEndpoint(BaseEndpoint):
    """Client endpoint for KGFrames operations with standardized responses."""
    
    @property
    def vs(self):
        """Lazy VitalSigns instance."""
        if not hasattr(self, '_vs'):
            self._vs = VitalSigns()
        return self._vs
    
    async def _make_request(self, method: str, url: str, params=None, json=None, headers=None, content=None):
        """
        Make authenticated HTTP request with automatic token refresh.
        Uses base endpoint's authenticated request method.
        """
        try:
            start_time = time.time()
            
            kwargs = {}
            if params:
                kwargs['params'] = params
            if json is not None:
                kwargs['json'] = json
            if headers:
                kwargs['headers'] = headers
            if content is not None:
                kwargs['content'] = content
            
            response = await self._make_authenticated_request(method, url, **kwargs)
            
            duration = time.time() - start_time
            url_parts = url.split('/')
            operation = url_parts[-1] if url_parts else 'request'
            logger.info(f"⏱️  {method} {operation}: {duration:.3f}s")
            
            return response
            
        except httpx.HTTPError as e:
            raise VitalGraphClientError(f"Request failed: {str(e)}")
    
    async def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, search: Optional[str] = None) -> PaginatedGraphObjectResponse:
        """
        List KGFrames with pagination and optional search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            entity_uri: Optional entity URI for filtering frames
            parent_uri: Optional parent URI for filtering frames
            search: Optional search term
            
        Returns:
            PaginatedGraphObjectResponse containing KGFrame GraphObjects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                entity_uri=entity_uri,
                parent_uri=parent_uri,
                search=search
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            
            objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS, self.vs)
            pagination = extract_pagination_from_json_quads(response_data)
            
            return build_success_response(
                PaginatedGraphObjectResponse,
                objects=objects,
                status_code=response.status_code,
                message=f"Retrieved {len(objects)} frames",
                space_id=space_id, graph_id=graph_id,
                **pagination,
                metadata={'object_types': count_object_types(objects)}
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error listing frames: {e}")
            return build_error_response(
                PaginatedGraphObjectResponse,
                error_code=1, error_message=str(e), status_code=500,
                space_id=space_id, graph_id=graph_id
            )
    
    async def get_kgframe(self, space_id: str, graph_id: str, uri: str, include_frame_graph: bool = False) -> FrameGraphResponse:
        """
        Get a specific KGFrame by URI with optional complete graph.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI
            include_frame_graph: If True, include complete frame graph (frames + slots + frame-to-frame edges)
            
        Returns:
            FrameGraphResponse containing KGFrame data and optional complete graph
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                uri=uri,
                include_frame_graph=include_frame_graph
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            
            objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS, self.vs)
            frame_graph = build_frame_graph(uri, objects) if objects else None
            
            return build_success_response(
                FrameGraphResponse,
                frame_graph=frame_graph,
                status_code=response.status_code,
                message=f"Retrieved frame with {len(objects)} objects",
                space_id=space_id, graph_id=graph_id,
                requested_frame_uri=uri,
                metadata={'object_types': count_object_types(objects)}
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting frame: {e}")
            return build_error_response(
                FrameGraphResponse,
                error_code=2, error_message=str(e), status_code=500,
                space_id=space_id, graph_id=graph_id,
                requested_frame_uri=uri
            )
    
    async def create_kgframes(self, space_id: str, graph_id: str, objects: List[GraphObject],
                       entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "create") -> CreateEntityResponse:
        """
        Create KGFrames from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (frames, slots, edges)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            operation_mode: Operation mode (create, update, upsert)
            
        Returns:
            CreateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                parent_uri=parent_uri,
                operation_mode=operation_mode
            )
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            
            created_count = response_data.get('created_count', 0)
            created_uris = response_data.get('created_uris', [])
            
            return build_success_response(
                CreateEntityResponse,
                status_code=response.status_code,
                message=response_data.get('message', f"Created {created_count} frames"),
                created_count=created_count,
                created_uris=created_uris
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating frames: {e}")
            return build_error_response(
                CreateEntityResponse,
                error_code=3, error_message=str(e), status_code=500
            )
    
    async def update_kgframes(self, space_id: str, graph_id: str, objects: List[GraphObject],
                       entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> UpdateEntityResponse:
        """
        Update KGFrames from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (frames, slots, edges)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            
        Returns:
            UpdateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                operation_mode="update",
                entity_uri=entity_uri,
                parent_uri=parent_uri
            )
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            
            updated_uri = response_data.get('updated_uri') or response_data.get('updated_uris', [None])[0]
            
            return build_success_response(
                UpdateEntityResponse,
                status_code=response.status_code,
                message=response_data.get('message', 'Frames updated'),
                updated_uri=updated_uri
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating frames: {e}")
            return build_error_response(
                UpdateEntityResponse,
                error_code=4, error_message=str(e), status_code=500
            )
    
    async def delete_kgframe(self, space_id: str, graph_id: str, uri: str) -> DeleteResponse:
        """
        Delete a KGFrame by URI.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGFrame URI to delete
            
        Returns:
            DeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(space_id=space_id, graph_id=graph_id, uri=uri)
            
            response = await self._make_request('DELETE', url, params=params)
            response_data = response.json()
            
            deleted_count = response_data.get('deleted_count', response_data.get('affected_count', 0))
            deleted_uris = response_data.get('deleted_uris', [uri] if deleted_count else [])
            
            return build_success_response(
                DeleteResponse,
                status_code=response.status_code,
                message=response_data.get('message', f"Deleted {deleted_count} frames"),
                deleted_count=deleted_count,
                deleted_uris=deleted_uris,
                space_id=space_id, graph_id=graph_id,
                requested_uris=[uri]
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error deleting frame: {e}")
            return build_error_response(
                DeleteResponse, error_code=5, error_message=str(e), status_code=500,
                space_id=space_id, graph_id=graph_id, requested_uris=[uri]
            )
    
    async def delete_kgframes_batch(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
        """
        Delete multiple KGFrames by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGFrame URIs
            
        Returns:
            DeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)
            
            response = await self._make_request('DELETE', url, params=params)
            response_data = response.json()
            
            deleted_count = response_data.get('deleted_count', response_data.get('affected_count', 0))
            deleted_uris = response_data.get('deleted_uris', [])
            
            return build_success_response(
                DeleteResponse,
                status_code=response.status_code,
                message=response_data.get('message', f"Deleted {deleted_count} frames"),
                deleted_count=deleted_count,
                deleted_uris=deleted_uris,
                space_id=space_id, graph_id=graph_id,
                requested_uris=uri_list.split(',')
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error deleting frames batch: {e}")
            return build_error_response(
                DeleteResponse, error_code=5, error_message=str(e), status_code=500,
                space_id=space_id, graph_id=graph_id
            )
    
    # KGFrames with Slots operations
    # Note: Server-side implementation may not be complete yet
    
    async def get_kgframes_with_slots(self, space_id: str, graph_id: str, frame_uri: Optional[str] = None, page_size: int = 10, offset: int = 0, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, search: Optional[str] = None) -> PaginatedGraphObjectResponse:
        """
        Get KGFrames with their associated slots.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            entity_uri: Optional entity URI for filtering frames
            parent_uri: Optional parent URI for filtering frames
            search: Optional search term
            
        Returns:
            PaginatedGraphObjectResponse containing KGFrames with slots as GraphObjects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, frame_uri=frame_uri,
                page_size=page_size, offset=offset, entity_uri=entity_uri,
                parent_uri=parent_uri, search=search
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS, self.vs)
            pagination = extract_pagination_from_json_quads(response_data)
            
            return build_success_response(
                PaginatedGraphObjectResponse, objects=objects,
                status_code=response.status_code,
                message=f"Retrieved {len(objects)} frame slots",
                space_id=space_id, graph_id=graph_id, **pagination,
                metadata={'object_types': count_object_types(objects)}
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting frames with slots: {e}")
            return build_error_response(
                PaginatedGraphObjectResponse, error_code=1, error_message=str(e), status_code=500
            )
    
    async def create_kgframes_with_slots(self, space_id: str, graph_id: str, objects: List[GraphObject],
                                  entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "create") -> CreateEntityResponse:
        """
        Create KGFrames with their associated slots from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (frames, slots, edges)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            operation_mode: Operation mode (create, update, upsert)
            
        Returns:
            CreateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_uri=parent_uri, operation_mode=operation_mode
            )
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            created_count = response_data.get('created_count', 0)
            created_uris = response_data.get('created_uris', [])
            
            return build_success_response(
                CreateEntityResponse, status_code=response.status_code,
                message=response_data.get('message', f"Created {created_count} frames with slots"),
                created_count=created_count, created_uris=created_uris
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating frames with slots: {e}")
            return build_error_response(CreateEntityResponse, error_code=3, error_message=str(e), status_code=500)
    
    async def update_kgframes_with_slots(self, space_id: str, graph_id: str, objects: List[GraphObject],
                                  entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> UpdateEntityResponse:
        """
        Update KGFrames with their associated slots from GraphObjects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of GraphObject instances (frames, slots, edges)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            
        Returns:
            UpdateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, entity_uri=entity_uri,
                parent_uri=parent_uri, operation_mode='update'
            )
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            updated_uri = response_data.get('updated_uri') or response_data.get('updated_uris', [None])[0]
            
            return build_success_response(
                UpdateEntityResponse, status_code=response.status_code,
                message=response_data.get('message', 'Frames with slots updated'),
                updated_uri=updated_uri
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating frames with slots: {e}")
            return build_error_response(UpdateEntityResponse, error_code=4, error_message=str(e), status_code=500)
    
    async def delete_kgframes_with_slots(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
        """
        Delete KGFrames with their associated slots by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGFrame URIs
            
        Returns:
            DeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return await self.delete_kgframes_batch(space_id, graph_id, uri_list)
    
    async def delete_kgframes(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
        """
        Delete KGFrames by URI list.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGFrame URIs
            
        Returns:
            DeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return await self.delete_kgframes_batch(space_id, graph_id, uri_list)

    # Frame-Slot Sub-Endpoint Operations
    
    async def create_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, objects: List[GraphObject], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "create") -> CreateEntityResponse:
        """
        Create slots for a specific frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to create slots for
            objects: List of GraphObject instances (slots, edges)
            entity_uri: Optional entity URI for setting hasKGGraphURI property
            parent_uri: Optional parent URI for slot relationships
            operation_mode: Operation mode (create, update, upsert)
            
        Returns:
            CreateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, frame_uri=frame_uri,
                entity_uri=entity_uri, parent_uri=parent_uri, operation_mode=operation_mode
            )
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            created_count = response_data.get('created_count', 0)
            created_uris = response_data.get('created_uris', [])
            
            return build_success_response(
                CreateEntityResponse, status_code=response.status_code,
                message=response_data.get('message', f"Created {created_count} slots"),
                created_count=created_count, created_uris=created_uris
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating frame slots: {e}")
            return build_error_response(CreateEntityResponse, error_code=3, error_message=str(e), status_code=500)
    
    async def update_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, objects: List[GraphObject], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> UpdateEntityResponse:
        """
        Update slots for a specific frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to update slots for
            objects: List of GraphObject instances (slots, edges)
            entity_uri: Optional entity URI for setting hasKGGraphURI property
            parent_uri: Optional parent URI for slot relationships
            
        Returns:
            UpdateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, frame_uri=frame_uri,
                entity_uri=entity_uri, parent_uri=parent_uri, operation_mode="update"
            )
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            updated_uri = response_data.get('updated_uri') or response_data.get('updated_uris', [None])[0]
            
            return build_success_response(
                UpdateEntityResponse, status_code=response.status_code,
                message=response_data.get('message', 'Slots updated'),
                updated_uri=updated_uri
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating frame slots: {e}")
            return build_error_response(UpdateEntityResponse, error_code=4, error_message=str(e), status_code=500)
    
    async def delete_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_uris: list[str]) -> DeleteResponse:
        """
        Delete specific slots from a frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to delete slots from
            slot_uris: List of slot URIs to delete
            
        Returns:
            DeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri, slot_uris=slot_uris)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, frame_uri=frame_uri,
                slot_uris=','.join(slot_uris)
            )
            
            response = await self._make_request('DELETE', url, params=params)
            response_data = response.json()
            deleted_count = response_data.get('deleted_count', response_data.get('affected_count', 0))
            deleted_uris = response_data.get('deleted_uris', [])
            
            return build_success_response(
                DeleteResponse, status_code=response.status_code,
                message=response_data.get('message', f"Deleted {deleted_count} slots"),
                deleted_count=deleted_count, deleted_uris=deleted_uris,
                space_id=space_id, graph_id=graph_id, requested_uris=slot_uris
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error deleting frame slots: {e}")
            return build_error_response(
                DeleteResponse, error_code=5, error_message=str(e), status_code=500,
                space_id=space_id, graph_id=graph_id, requested_uris=slot_uris
            )
    
    async def get_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_type: Optional[str] = None) -> PaginatedGraphObjectResponse:
        """
        Get slots for a specific frame, optionally filtered by slot type.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to get slots for
            slot_type: Optional slot type URN for filtering by kGSlotType property
            
        Returns:
            PaginatedGraphObjectResponse containing frame's slots as GraphObjects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, frame_uri=frame_uri, slot_type=slot_type
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS, self.vs)
            pagination = extract_pagination_from_json_quads(response_data)
            
            return build_success_response(
                PaginatedGraphObjectResponse, objects=objects,
                status_code=response.status_code,
                message=f"Retrieved {len(objects)} slots",
                space_id=space_id, graph_id=graph_id, **pagination,
                metadata={'object_types': count_object_types(objects)}
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting frame slots: {e}")
            return build_error_response(
                PaginatedGraphObjectResponse, error_code=1, error_message=str(e), status_code=500
            )
    
    # Frame-to-Frame Sub-Endpoint Operations
    
    async def create_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, objects: List[GraphObject]) -> CreateEntityResponse:
        """
        Create child frames for a parent frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            objects: List of GraphObject instances (child frames, slots, edges)
            
        Returns:
            CreateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(space_id=space_id, graph_id=graph_id, parent_uri=parent_frame_uri)
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            created_count = response_data.get('created_count', 0)
            created_uris = response_data.get('created_uris', [])
            
            return build_success_response(
                CreateEntityResponse, status_code=response.status_code,
                message=response_data.get('message', f"Created {created_count} child frames"),
                created_count=created_count, created_uris=created_uris
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating child frames: {e}")
            return build_error_response(CreateEntityResponse, error_code=3, error_message=str(e), status_code=500)
    
    async def update_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, objects: List[GraphObject]) -> UpdateEntityResponse:
        """
        Update child frames for a parent frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            objects: List of GraphObject instances (child frames, slots, edges)
            
        Returns:
            UpdateEntityResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id,
                parent_uri=parent_frame_uri, operation_mode='update'
            )
            
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            response = await self._make_request('POST', url, params=params, json=body,
                                                headers={'Content-Type': content_type})
            response_data = response.json()
            updated_uri = response_data.get('updated_uri') or response_data.get('updated_uris', [None])[0]
            
            return build_success_response(
                UpdateEntityResponse, status_code=response.status_code,
                message=response_data.get('message', 'Child frames updated'),
                updated_uri=updated_uri
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating child frames: {e}")
            return build_error_response(UpdateEntityResponse, error_code=4, error_message=str(e), status_code=500)
    
    async def delete_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, frame_uris: list[str]) -> DeleteResponse:
        """
        Delete child frames from a parent frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            frame_uris: List of child frame URIs to delete
            
        Returns:
            DeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return await self.delete_kgframes_batch(space_id, graph_id, ','.join(frame_uris))
    
    async def get_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, frame_type: Optional[str] = None) -> PaginatedGraphObjectResponse:
        """
        Get child frames for a parent frame, optionally filtered by frame type.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            frame_type: Optional frame type URI for filtering
            
        Returns:
            PaginatedGraphObjectResponse containing child frames as GraphObjects
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes/kgframes"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id,
                parent_frame_uri=parent_frame_uri, frame_type=frame_type
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS, self.vs)
            pagination = extract_pagination_from_json_quads(response_data)
            
            return build_success_response(
                PaginatedGraphObjectResponse, objects=objects,
                status_code=response.status_code,
                message=f"Retrieved {len(objects)} child frames",
                space_id=space_id, graph_id=graph_id, **pagination,
                metadata={'object_types': count_object_types(objects)}
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting child frames: {e}")
            return build_error_response(
                PaginatedGraphObjectResponse, error_code=1, error_message=str(e), status_code=500
            )
    
    async def list_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, frame_type: Optional[str] = None, 
                         page_size: int = 10, offset: int = 0) -> PaginatedGraphObjectResponse:
        """
        List child frames for a parent frame with pagination.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            frame_type: Optional frame type URI for filtering
            page_size: Number of items per page
            offset: Offset for pagination
            
        Returns:
            PaginatedGraphObjectResponse containing child frames and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes/kgframes"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id,
                parent_frame_uri=parent_frame_uri, frame_type=frame_type,
                page_size=page_size, offset=offset
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS, self.vs)
            pagination = extract_pagination_from_json_quads(response_data)
            
            return build_success_response(
                PaginatedGraphObjectResponse, objects=objects,
                status_code=response.status_code,
                message=f"Retrieved {len(objects)} child frames",
                space_id=space_id, graph_id=graph_id, **pagination,
                metadata={'object_types': count_object_types(objects)}
            )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error listing child frames: {e}")
            return build_error_response(
                PaginatedGraphObjectResponse, error_code=1, error_message=str(e), status_code=500
            )
    
    # Enhanced Graph Operations
    
    async def query_frames(self, space_id: str, graph_id: str, query_request: FrameQueryRequest) -> FrameQueryResponse:
        """
        Query KGFrames using criteria-based search.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            query_request: FrameQueryRequest containing search criteria and pagination
            
        Returns:
            FrameQueryResponse containing list of matching frame URIs and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, query_request=query_request)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/query"
        params = build_query_params(space_id=space_id, graph_id=graph_id)
        
        return await self._make_typed_request('POST', url, FrameQueryResponse, params=params, json=query_request.model_dump())
    
    async def list_kgframes_with_graphs(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                                 search: Optional[str] = None, include_frame_graphs: bool = False) -> MultiFrameGraphResponse:
        """
        List KGFrames with optional complete graphs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            include_frame_graphs: If True, include complete frame graphs for all frames
            
        Returns:
            MultiFrameGraphResponse containing frames and optional complete graphs
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        try:
            url = f"{self._get_server_url()}/api/graphs/kgframes"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id,
                page_size=page_size, offset=offset,
                search=search, include_frame_graphs=include_frame_graphs
            )
            
            response = await self._make_request('GET', url, params=params)
            response_data = response.json()
            
            if include_frame_graphs:
                complete_graphs_dict = response_data.get('complete_graphs', {})
                frame_graphs = []
                for frame_uri, graph_data in complete_graphs_dict.items():
                    objects = deserialize_response_to_graphobjects(graph_data, ClientWireFormat.JSON_QUADS, self.vs)
                    frame_graphs.append(build_frame_graph(frame_uri, objects))
                
                return build_success_response(
                    MultiFrameGraphResponse,
                    frame_graph_list=frame_graphs,
                    status_code=response.status_code,
                    message=f"Retrieved {len(frame_graphs)} frame graphs",
                    space_id=space_id, graph_id=graph_id,
                    metadata={'total_graphs': len(frame_graphs)}
                )
            else:
                objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS, self.vs)
                frame_graphs = []
                for obj in objects:
                    if hasattr(obj, 'URI'):
                        frame_graphs.append(build_frame_graph(str(obj.URI), [obj]))
                
                return build_success_response(
                    MultiFrameGraphResponse,
                    frame_graph_list=frame_graphs,
                    status_code=response.status_code,
                    message=f"Retrieved {len(frame_graphs)} frames",
                    space_id=space_id, graph_id=graph_id,
                    metadata={'total_frames': len(frame_graphs)}
                )
        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error listing frames with graphs: {e}")
            return build_error_response(
                MultiFrameGraphResponse, error_code=1, error_message=str(e), status_code=500,
                space_id=space_id, graph_id=graph_id
            )
    
    async def get_kgframe_graph(self, space_id: str, graph_id: str, uri: str) -> FrameGraphResponse:
        """
        Get complete graph for a specific KGFrame including all connected objects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Frame URI to get graph for
            
        Returns:
            FrameGraphResponse containing the frame and its complete graph
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return await self.get_kgframe(space_id, graph_id, uri, include_frame_graph=True)
    
    async def delete_kgframe_graph(self, space_id: str, graph_id: str, uri: str) -> DeleteResponse:
        """
        Delete a KGFrame and its complete graph including all connected objects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Frame URI to delete graph for
            
        Returns:
            DeleteResponse containing deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return await self.delete_kgframe(space_id, graph_id, uri)
    
    async def delete_kgframe_graphs(self, space_id: str, graph_id: str, uri_list: str) -> DeleteResponse:
        """
        Delete multiple KGFrames and their complete graphs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of frame URIs to delete graphs for
            
        Returns:
            DeleteResponse containing deletion result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        return await self.delete_kgframes_batch(space_id, graph_id, uri_list)
