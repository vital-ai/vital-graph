"""
VitalGraph Client KGFrames Endpoint

Client-side implementation for KGFrames operations.
"""

import requests
from typing import Dict, Any, Optional, Union

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.kgframes_model import (
    FramesResponse, FrameCreateResponse, FrameUpdateResponse, FrameDeleteResponse,
    FrameQueryRequest, FrameQueryResponse, FrameGraphResponse, FrameGraphDeleteResponse,
    FramesGraphResponse, SlotCreateResponse, SlotUpdateResponse, SlotDeleteResponse
)
from ...model.jsonld_model import JsonLdDocument, JsonLdObject


class KGFramesEndpoint(BaseEndpoint):
    """Client endpoint for KGFrames operations."""
    
    def _make_request(self, method: str, url: str, params=None, json=None):
        """
        Make HTTP request and return response object.
        Helper method for handling Union response types.
        """
        try:
            if method == 'GET':
                response = self.client.session.get(url, params=params)
            elif method == 'POST':
                response = self.client.session.post(url, params=params, json=json)
            elif method == 'DELETE':
                response = self.client.session.delete(url, params=params)
            else:
                raise VitalGraphClientError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            raise VitalGraphClientError(f"Request failed: {str(e)}")
    
    def list_kgframes(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, search: Optional[str] = None) -> FramesResponse:
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
            entity_uri=entity_uri,
            parent_uri=parent_uri,
            search=search
        )
        
        return self._make_typed_request('GET', url, FramesResponse, params=params)
    
    def get_kgframe(self, space_id: str, graph_id: str, uri: str, include_frame_graph: bool = False) -> FrameGraphResponse:
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
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri,
            include_frame_graph=include_frame_graph
        )
        
        return self._make_typed_request('GET', url, FrameGraphResponse, params=params)
    
    def create_kgframes(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument],
                       entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "create") -> FrameCreateResponse:
        """
        Create KGFrames from JSON-LD document or object with automatic grouping URI assignment.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD document (multiple frames) or object (single frame)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            operation_mode: Operation mode (create, update, upsert)
            
        Returns:
            FrameCreateResponse containing operation result
            
        Note:
            Server automatically strips any existing hasKGGraphURI and hasFrameGraphURI values from the input.
            Sets hasKGGraphURI to entity_uri for all components (frames + slots + hasSlot edges).
            Sets hasFrameGraphURI to the frame URI for all frame-specific components (frame + its slots + hasSlot edges).
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            parent_uri=parent_uri,
            operation_mode=operation_mode
        )
        
        payload = data.model_dump(by_alias=True)
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=payload)
    
    def update_kgframes(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument],
                       entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> FrameUpdateResponse:
        """
        Update KGFrames from JSON-LD document or object with grouping URI management.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD document (multiple frames) or object (single frame)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            
        Returns:
            FrameUpdateResponse containing operation result
            
        Note:
            Server automatically strips any existing hasKGGraphURI and hasFrameGraphURI values from the document.
            Sets hasKGGraphURI to entity_uri for all components (frames + slots + hasSlot edges).
            Sets hasFrameGraphURI to the frame URI for all frame-specific components (frame + its slots + hasSlot edges).
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            operation_mode="update",
            entity_uri=entity_uri,
            parent_uri=parent_uri
        )
        
        payload = data.model_dump(by_alias=True)
        return self._make_typed_request('POST', url, FrameUpdateResponse, params=params, json=payload)
    
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
    
    def get_kgframes_with_slots(self, space_id: str, graph_id: str, frame_uri: Optional[str] = None, page_size: int = 10, offset: int = 0, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, search: Optional[str] = None) -> FramesResponse:
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
            frame_uri=frame_uri,
            page_size=page_size,
            offset=offset,
            entity_uri=entity_uri,
            parent_uri=parent_uri,
            search=search
        )
        
        return self._make_typed_request('GET', url, FramesResponse, params=params)
    
    def create_kgframes_with_slots(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument],
                                  entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "create") -> FrameCreateResponse:
        """
        Create KGFrames with their associated slots from JSON-LD document or object with automatic grouping URI assignment.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD document (multiple frames with slots) or object (single frame with slots)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            operation_mode: Operation mode (create, update, upsert)
            
        Returns:
            FrameCreateResponse containing operation result
            
        Note:
            Server automatically strips any existing hasKGGraphURI and hasFrameGraphURI values from the input.
            Sets hasKGGraphURI to entity_uri for all components (frames + slots + hasSlot edges).
            Sets hasFrameGraphURI to the frame URI for all frame-specific components (frame + its slots + hasSlot edges).
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            parent_uri=parent_uri,
            operation_mode=operation_mode
        )
        
        payload = data.model_dump(by_alias=True)
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=payload)
    
    def update_kgframes_with_slots(self, space_id: str, graph_id: str, data: Union[JsonLdObject, JsonLdDocument],
                                  entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> FrameUpdateResponse:
        """
        Update KGFrames with their associated slots from JSON-LD document or object with grouping URI management.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            data: JSON-LD document (multiple frames with slots) or object (single frame with slots)
            entity_uri: Optional entity URI for setting hasKGGraphURI property on frames
            parent_uri: Optional parent URI for frame relationships
            
        Returns:
            FrameUpdateResponse containing operation result
            
        Note:
            Server automatically strips any existing hasKGGraphURI and hasFrameGraphURI values from the document.
            Sets hasKGGraphURI to entity_uri for all components (frames + slots + hasSlot edges).
            Sets hasFrameGraphURI to the frame URI for all frame-specific components (frame + its slots + hasSlot edges).
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            entity_uri=entity_uri,
            parent_uri=parent_uri,
            operation_mode='update'
        )
        
        payload = data.model_dump(by_alias=True)
        return self._make_typed_request('POST', url, FrameUpdateResponse, params=params, json=payload)
    
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
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=uri_list
        )
        
        return self._make_typed_request('DELETE', url, FrameDeleteResponse, params=params)
    
    def delete_kgframes(self, space_id: str, graph_id: str, uri_list: str) -> FrameDeleteResponse:
        """
        Delete KGFrames by URI list.
        
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

    # Frame-Slot Sub-Endpoint Operations
    
    def create_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, data: Union[JsonLdObject, JsonLdDocument], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None, operation_mode: str = "create") -> SlotCreateResponse:
        """
        Create slots for a specific frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to create slots for
            data: JSON-LD document (multiple slots) or object (single slot)
            entity_uri: Optional entity URI for setting hasKGGraphURI property
            parent_uri: Optional parent URI for slot relationships
            operation_mode: Operation mode (create, update, upsert)
            
        Returns:
            SlotCreateResponse containing operation result
            
        Note:
            Server automatically sets hasKGGraphURI and hasFrameGraphURI for all slot components.
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            entity_uri=entity_uri,
            parent_uri=parent_uri,
            operation_mode=operation_mode
        )
        
        payload = data.model_dump(by_alias=True)
        response = self._make_request('POST', url, params=params, json=payload)
        return SlotCreateResponse(**response.json())
    
    def update_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, data: Union[JsonLdObject, JsonLdDocument], entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> SlotUpdateResponse:
        """
        Update slots for a specific frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to update slots for
            data: JSON-LD document (multiple slots) or object (single slot)
            entity_uri: Optional entity URI for setting hasKGGraphURI property
            parent_uri: Optional parent URI for slot relationships
            
        Returns:
            SlotUpdateResponse containing operation result
            
        Note:
            Server automatically manages hasKGGraphURI and hasFrameGraphURI for all slot components.
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            entity_uri=entity_uri,
            parent_uri=parent_uri,
            operation_mode="update"
        )
        
        payload = data.model_dump(by_alias=True)
        return self._make_typed_request('POST', url, SlotUpdateResponse, params=params, json=payload)
    
    def delete_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_uris: list[str]) -> SlotDeleteResponse:
        """
        Delete specific slots from a frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to delete slots from
            slot_uris: List of slot URIs to delete
            
        Returns:
            SlotDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri, slot_uris=slot_uris)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            slot_uris=','.join(slot_uris)
        )
        
        return self._make_typed_request('DELETE', url, SlotDeleteResponse, params=params)
    
    def get_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_type: Optional[str] = None) -> JsonLdDocument:
        """
        Get slots for a specific frame, optionally filtered by slot type.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            frame_uri: Frame URI to get slots for
            slot_type: Optional slot type URN for filtering by kGSlotType property
                      Examples:
                      - "urn:EnhancedTextSlotType"
                      - "urn:EnhancedIntegerSlotType"
                      - "urn:EnhancedBooleanSlotType"
            
        Returns:
            JsonLdDocument containing frame's slots
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, frame_uri=frame_uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgslots"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            frame_uri=frame_uri,
            slot_type=slot_type
        )
        
        return self._make_typed_request('GET', url, JsonLdDocument, params=params)
    
    # Frame-to-Frame Sub-Endpoint Operations
    
    def create_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, data: Union[JsonLdObject, JsonLdDocument]) -> FrameCreateResponse:
        """
        Create child frames for a parent frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            data: JSON-LD document (multiple child frames) or object (single child frame)
            
        Returns:
            FrameCreateResponse containing operation result
            
        Note:
            Server automatically sets hasKGGraphURI and hasFrameGraphURI for all frame components.
            Creates Edge_hasKGFrame relationships between parent and child frames.
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            parent_uri=parent_frame_uri
        )
        
        return self._make_typed_request('POST', url, FrameCreateResponse, params=params, json=data.model_dump(by_alias=True))
    
    def update_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, data: Union[JsonLdObject, JsonLdDocument]) -> FrameUpdateResponse:
        """
        Update child frames for a parent frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            data: JSON-LD document (multiple child frames) or object (single child frame)
            
        Returns:
            FrameUpdateResponse containing operation result
            
        Note:
            Automatically sets jsonld_type discriminator field.
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        # Set discriminator field based on type
        if isinstance(data, JsonLdObject):
            data.jsonld_type = "object"
        elif isinstance(data, JsonLdDocument):
            data.jsonld_type = "document"
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            parent_uri=parent_frame_uri,
            operation_mode='update'
        )
        
        return self._make_typed_request('POST', url, FrameUpdateResponse, params=params, json=data.model_dump(by_alias=True))
    
    def delete_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, frame_uris: list[str]) -> FrameDeleteResponse:
        """
        Delete child frames from a parent frame.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            frame_uris: List of child frame URIs to delete
            
        Returns:
            FrameDeleteResponse containing operation result
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri, frame_uris=frame_uris)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri_list=','.join(frame_uris)
        )
        
        return self._make_typed_request('DELETE', url, FrameDeleteResponse, params=params)
    
    def get_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, frame_type: Optional[str] = None) -> JsonLdDocument:
        """
        Get child frames for a parent frame, optionally filtered by frame type.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_frame_uri: Parent frame URI
            frame_type: Optional frame type URI for filtering
            
        Returns:
            JsonLdDocument containing child frames
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            parent_frame_uri=parent_frame_uri,
            frame_type=frame_type
        )
        
        return self._make_typed_request('GET', url, JsonLdDocument, params=params)
    
    def list_child_frames(self, space_id: str, graph_id: str, parent_frame_uri: str, frame_type: Optional[str] = None, 
                         page_size: int = 10, offset: int = 0) -> FramesResponse:
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
            FramesResponse containing child frames and pagination info
            
        Raises:
            VitalGraphClientError: If request fails
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_frame_uri=parent_frame_uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            parent_frame_uri=parent_frame_uri,
            frame_type=frame_type,
            page_size=page_size,
            offset=offset
        )
        
        return self._make_typed_request('GET', url, FramesResponse, params=params)
    
    # Enhanced Graph Operations
    
    def query_frames(self, space_id: str, graph_id: str, query_request: FrameQueryRequest) -> FrameQueryResponse:
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
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id
        )
        
        return self._make_typed_request('POST', url, FrameQueryResponse, params=params, json=query_request.model_dump())
    
    def list_kgframes_with_graphs(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                                 search: Optional[str] = None, include_frame_graphs: bool = False) -> FramesGraphResponse:
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
            FramesGraphResponse containing frames and optional complete graphs
            
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
            search=search,
            include_frame_graphs=include_frame_graphs
        )
        
        return self._make_typed_request('GET', url, FramesGraphResponse, params=params)
    
    def get_kgframe_graph(self, space_id: str, graph_id: str, uri: str) -> FrameGraphResponse:
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
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)
        
        url = f"{self._get_server_url()}/api/graphs/kgframes"
        params = build_query_params(
            space_id=space_id,
            graph_id=graph_id,
            uri=uri,
            include_frame_graph=True
        )
        
        return self._make_typed_request('GET', url, FrameGraphResponse, params=params)
    
    def delete_kgframe_graph(self, space_id: str, graph_id: str, uri: str) -> FrameDeleteResponse:
        """
        Delete a KGFrame and its complete graph including all connected objects.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: Frame URI to delete graph for
            
        Returns:
            FrameDeleteResponse containing deletion result
            
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
    
    def delete_kgframe_graphs(self, space_id: str, graph_id: str, uri_list: str) -> FrameDeleteResponse:
        """
        Delete multiple KGFrames and their complete graphs.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of frame URIs to delete graphs for
            
        Returns:
            FrameDeleteResponse containing deletion result
            
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
