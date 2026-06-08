"""
VitalGraph Client - Vector Mappings Endpoint

Client-side endpoint for Vector Mapping REST API operations.
"""

import logging
from typing import Dict, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.vector_mappings_model import (
    MappingPropertyOut, MappingOut, MappingListResponse,
    CreateMappingRequest, UpdateMappingRequest, AddPropertyRequest,
)

logger = logging.getLogger(__name__)


class VectorMappingsClientEndpoint(BaseEndpoint):
    """Client endpoint for Vector Mapping management operations."""

    def __init__(self, client):
        super().__init__(client)

    def _url(self, space_id: str, path: str = "") -> str:
        return f"{self._get_server_url()}/api/spaces/{space_id}/vector-mappings{path}"

    async def list_mappings(
        self,
        space_id: str,
        index_name: Optional[str] = None,
        mapping_type: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> MappingListResponse:
        """List vector mappings for a space.

        Args:
            space_id: Space ID
            index_name: Filter by vector index name
            mapping_type: Filter by mapping type (kgentity|kgdocument|kgframe|kgslot)
            enabled: Filter by enabled status

        Returns:
            MappingListResponse with mappings and total count
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(
            index_name=index_name, mapping_type=mapping_type, enabled=enabled,
        )
        return await self._make_typed_request(
            "GET", self._url(space_id), MappingListResponse, params=params,
        )

    async def create_mapping(
        self,
        space_id: str,
        index_name: str,
        mapping_type: str,
        type_uri: Optional[str] = None,
        enabled: bool = True,
        source_type: str = "default",
        separator: str = ". ",
        include_pred_name: bool = False,
        include_type_desc: bool = True,
    ) -> MappingOut:
        """Create a new vector mapping.

        Args:
            space_id: Space ID
            index_name: Target vector index name
            mapping_type: kgentity | kgdocument | kgframe | kgslot
            type_uri: Specific KG Type URI (None = class-level)
            enabled: Enable vectorization
            source_type: default | properties | slots
            separator: Separator for concatenated text
            include_pred_name: Include predicate local name in text
            include_type_desc: Include KG Type description in text

        Returns:
            MappingOut with created mapping details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name, mapping_type=mapping_type)
        request = CreateMappingRequest(
            mapping_type=mapping_type, type_uri=type_uri, index_name=index_name,
            enabled=enabled, source_type=source_type, separator=separator,
            include_pred_name=include_pred_name, include_type_desc=include_type_desc,
        )
        return await self._make_typed_request(
            "POST", self._url(space_id), MappingOut,
            json=request.model_dump(exclude_none=True),
        )

    async def get_mapping(self, space_id: str, mapping_id: int) -> MappingOut:
        """Get a single vector mapping by ID.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            MappingOut with mapping details and properties
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        return await self._make_typed_request(
            "GET", self._url(space_id, f"/{mapping_id}"), MappingOut,
        )

    async def update_mapping(
        self,
        space_id: str,
        mapping_id: int,
        enabled: Optional[bool] = None,
        source_type: Optional[str] = None,
        separator: Optional[str] = None,
        include_pred_name: Optional[bool] = None,
        include_type_desc: Optional[bool] = None,
    ) -> MappingOut:
        """Update a vector mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID
            enabled: Enable/disable vectorization
            source_type: default | properties | slots
            separator: Separator for concatenated text
            include_pred_name: Include predicate local name
            include_type_desc: Include KG Type description

        Returns:
            MappingOut with updated mapping details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        request = UpdateMappingRequest(
            enabled=enabled, source_type=source_type, separator=separator,
            include_pred_name=include_pred_name, include_type_desc=include_type_desc,
        )
        return await self._make_typed_request(
            "PUT", self._url(space_id, f"/{mapping_id}"), MappingOut,
            json=request.model_dump(exclude_none=True),
        )

    async def delete_mapping(self, space_id: str, mapping_id: int) -> Dict:
        """Delete a vector mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        response = await self._make_authenticated_request(
            "DELETE", self._url(space_id, f"/{mapping_id}"),
        )
        return response.json()

    async def add_property(
        self,
        space_id: str,
        mapping_id: int,
        property_uri: str,
        property_role: str = "include",
        ordinal: int = 0,
    ) -> MappingPropertyOut:
        """Add a property to a vector mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID
            property_uri: Predicate URI or slot type URI
            property_role: include | exclude
            ordinal: Controls concatenation order

        Returns:
            MappingPropertyOut with created property details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id, property_uri=property_uri)
        request = AddPropertyRequest(
            property_uri=property_uri, property_role=property_role, ordinal=ordinal,
        )
        return await self._make_typed_request(
            "POST", self._url(space_id, f"/{mapping_id}/properties"), MappingPropertyOut,
            json=request.model_dump(),
        )

    async def remove_property(
        self, space_id: str, mapping_id: int, property_id: int,
    ) -> Dict:
        """Remove a property from a vector mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID
            property_id: Property ID

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id, property_id=property_id)
        response = await self._make_authenticated_request(
            "DELETE", self._url(space_id, f"/{mapping_id}/properties/{property_id}"),
        )
        return response.json()
