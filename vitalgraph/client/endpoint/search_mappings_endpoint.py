"""
VitalGraph Client - Search Mappings Endpoint

Client-side endpoint for Search Mapping REST API operations.
"""

import logging
from typing import Any, Dict, List, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.search_mappings_model import (
    SearchMappingOut, SearchMappingPropertyOut, SearchMappingIndexOut,
    SearchMappingListResponse,
    CreateSearchMappingRequest, UpdateSearchMappingRequest,
    AddIndexRequest, AddPropertyRequest, DeleteResponse,
)

logger = logging.getLogger(__name__)


class SearchMappingsClientEndpoint(BaseEndpoint):
    """Client endpoint for shared search mapping management."""

    def __init__(self, client):
        super().__init__(client)

    def _base_url(self) -> str:
        return f"{self._get_server_url()}/api/search-mappings"

    async def list_mappings(
        self,
        space_id: str,
        index_name: Optional[str] = None,
        mapping_type: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> SearchMappingListResponse:
        """List search mappings with optional filters.

        Args:
            space_id: Space ID
            index_name: Filter by index name
            mapping_type: Filter by mapping type
            enabled: Filter by enabled status

        Returns:
            SearchMappingListResponse with mappings and total count
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(
            space_id=space_id, index_name=index_name,
            mapping_type=mapping_type, enabled=enabled,
        )
        return await self._make_typed_request(
            "GET", self._base_url(), SearchMappingListResponse, params=params,
        )

    async def get_mapping(
        self, space_id: str, mapping_id: int,
    ) -> SearchMappingOut:
        """Get a single search mapping with its properties.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            SearchMappingOut with mapping details and properties
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "GET", f"{self._base_url()}/{mapping_id}",
            SearchMappingOut, params=params,
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
    ) -> SearchMappingOut:
        """Create a new search mapping.

        Args:
            space_id: Space ID
            index_name: Target index name
            mapping_type: Mapping type (e.g. 'kgentity')
            type_uri: Optional RDF type URI filter
            enabled: Whether mapping is active
            source_type: Source type (type_description, properties, properties_type, default)
            separator: Separator between property values
            include_pred_name: Include predicate names in search text

        Returns:
            SearchMappingOut with created mapping details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name, mapping_type=mapping_type)
        request = CreateSearchMappingRequest(
            index_name=index_name, mapping_type=mapping_type,
            type_uri=type_uri, enabled=enabled, source_type=source_type,
            separator=separator, include_pred_name=include_pred_name,
        )
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "POST", self._base_url(), SearchMappingOut,
            json=request.model_dump(exclude_none=True), params=params,
        )

    async def update_mapping(
        self,
        space_id: str,
        mapping_id: int,
        enabled: Optional[bool] = None,
        source_type: Optional[str] = None,
        separator: Optional[str] = None,
        include_pred_name: Optional[bool] = None,
    ) -> SearchMappingOut:
        """Update a search mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID
            enabled: New enabled status
            source_type: New source type
            separator: New separator
            include_pred_name: New include_pred_name flag

        Returns:
            SearchMappingOut with updated mapping details
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        request = UpdateSearchMappingRequest(
            enabled=enabled, source_type=source_type, separator=separator,
            include_pred_name=include_pred_name,
        )
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "PUT", f"{self._base_url()}/{mapping_id}", SearchMappingOut,
            json=request.model_dump(exclude_none=True), params=params,
        )

    async def delete_mapping(
        self, space_id: str, mapping_id: int,
    ) -> DeleteResponse:
        """Delete a search mapping (CASCADE deletes child properties).

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            DeleteResponse with confirmation
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "DELETE", f"{self._base_url()}/{mapping_id}",
            DeleteResponse, params=params,
        )

    async def add_property(
        self,
        space_id: str,
        mapping_id: int,
        property_uri: str,
        property_role: str = "include",
        ordinal: int = 0,
    ) -> SearchMappingPropertyOut:
        """Add a child property to a mapping.

        Args:
            space_id: Space ID
            mapping_id: Parent mapping ID
            property_uri: Property URI
            property_role: Role: 'include' or 'exclude'
            ordinal: Sort order

        Returns:
            SearchMappingPropertyOut with created property details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, property_uri=property_uri)
        request = AddPropertyRequest(
            property_uri=property_uri,
            property_role=property_role,
            ordinal=ordinal,
        )
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "POST", f"{self._base_url()}/{mapping_id}/properties",
            SearchMappingPropertyOut,
            json=request.model_dump(), params=params,
        )

    async def remove_property(
        self,
        space_id: str,
        mapping_id: int,
        property_id: int,
    ) -> DeleteResponse:
        """Remove a child property from a mapping.

        Args:
            space_id: Space ID
            mapping_id: Parent mapping ID
            property_id: Property ID to remove

        Returns:
            DeleteResponse with confirmation
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "DELETE",
            f"{self._base_url()}/{mapping_id}/properties/{property_id}",
            DeleteResponse, params=params,
        )

    async def add_index(
        self,
        space_id: str,
        mapping_id: int,
        index_type: str,
        index_name: str,
    ) -> SearchMappingIndexOut:
        """Associate an index with a mapping.

        Args:
            space_id: Space ID
            mapping_id: Parent mapping ID
            index_type: 'vector' or 'fts'
            index_name: Name of the concrete index to associate

        Returns:
            SearchMappingIndexOut with the junction row details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_type=index_type, index_name=index_name)
        request = AddIndexRequest(index_type=index_type, index_name=index_name)
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "POST", f"{self._base_url()}/{mapping_id}/indexes",
            SearchMappingIndexOut,
            json=request.model_dump(), params=params,
        )

    async def remove_index(
        self,
        space_id: str,
        mapping_id: int,
        junction_id: int,
    ) -> DeleteResponse:
        """Remove an index association from a mapping.

        Args:
            space_id: Space ID
            mapping_id: Parent mapping ID
            junction_id: Junction row ID to remove

        Returns:
            DeleteResponse with confirmation
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "DELETE",
            f"{self._base_url()}/{mapping_id}/indexes/{junction_id}",
            DeleteResponse, params=params,
        )
