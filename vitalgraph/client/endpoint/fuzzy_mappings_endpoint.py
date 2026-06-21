"""
VitalGraph Client - Fuzzy Mappings Endpoint

Client-side endpoint for Fuzzy Mapping REST API operations.
"""

import logging
from typing import Dict, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.fuzzy_mappings_model import (
    FuzzyMappingPropertyOut, FuzzyMappingOut, FuzzyMappingListResponse,
    FuzzyMappingStatsResponse,
    CreateFuzzyMappingRequest, UpdateFuzzyMappingRequest, AddFuzzyPropertyRequest,
)

logger = logging.getLogger(__name__)


class FuzzyMappingsClientEndpoint(BaseEndpoint):
    """Client endpoint for Fuzzy Mapping management operations."""

    def __init__(self, client):
        super().__init__(client)

    def _base_url(self) -> str:
        return f"{self._get_server_url()}/api/fuzzy-mappings"

    async def list_mappings(
        self,
        space_id: str,
        index_name: Optional[str] = None,
        mapping_type: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> FuzzyMappingListResponse:
        """List fuzzy mappings for a space.

        Args:
            space_id: Space ID
            index_name: Filter by fuzzy index name
            mapping_type: Filter by mapping type (kgentity|kgdocument|kgframe|kgslot)
            enabled: Filter by enabled status

        Returns:
            FuzzyMappingListResponse with mappings and total count
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(
            space_id=space_id, index_name=index_name, mapping_type=mapping_type, enabled=enabled,
        )
        return await self._make_typed_request(
            "GET", self._base_url(), FuzzyMappingListResponse, params=params,
        )

    async def create_mapping(
        self,
        space_id: str,
        index_name: str,
        mapping_type: str,
        type_uri: Optional[str] = None,
        enabled: bool = True,
        shingle_k: int = 3,
        num_perm: int = 64,
        lsh_threshold: float = 0.3,
        phonetic_bonus: float = 10.0,
    ) -> FuzzyMappingOut:
        """Create a new fuzzy mapping.

        Args:
            space_id: Space ID
            index_name: Target fuzzy index name
            mapping_type: kgentity | kgdocument | kgframe | kgslot
            type_uri: Specific KG Type URI (None = class-level)
            enabled: Enable fuzzy indexing
            shingle_k: Character n-gram size
            num_perm: MinHash permutations
            lsh_threshold: Jaccard similarity threshold for LSH
            phonetic_bonus: Score bonus for phonetic matches

        Returns:
            FuzzyMappingOut with created mapping details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name, mapping_type=mapping_type)
        request = CreateFuzzyMappingRequest(
            mapping_type=mapping_type, type_uri=type_uri, index_name=index_name,
            enabled=enabled, shingle_k=shingle_k, num_perm=num_perm,
            lsh_threshold=lsh_threshold, phonetic_bonus=phonetic_bonus,
        )
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "POST", self._base_url(), FuzzyMappingOut,
            json=request.model_dump(exclude_none=True), params=params,
        )

    async def get_mapping(self, space_id: str, mapping_id: int) -> FuzzyMappingOut:
        """Get a single fuzzy mapping by ID.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            FuzzyMappingOut with mapping details and properties
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        params = build_query_params(space_id=space_id, mapping_id=mapping_id)
        return await self._make_typed_request(
            "GET", self._base_url(), FuzzyMappingOut, params=params,
        )

    async def update_mapping(
        self,
        space_id: str,
        mapping_id: int,
        enabled: Optional[bool] = None,
        shingle_k: Optional[int] = None,
        num_perm: Optional[int] = None,
        lsh_threshold: Optional[float] = None,
        phonetic_bonus: Optional[float] = None,
    ) -> FuzzyMappingOut:
        """Update a fuzzy mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID
            enabled: Enable/disable fuzzy indexing
            shingle_k: Character n-gram size
            num_perm: MinHash permutations
            lsh_threshold: Jaccard similarity threshold
            phonetic_bonus: Score bonus for phonetic matches

        Returns:
            FuzzyMappingOut with updated mapping details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        request = UpdateFuzzyMappingRequest(
            enabled=enabled, shingle_k=shingle_k, num_perm=num_perm,
            lsh_threshold=lsh_threshold, phonetic_bonus=phonetic_bonus,
        )
        params = build_query_params(space_id=space_id, mapping_id=mapping_id)
        return await self._make_typed_request(
            "PUT", self._base_url(), FuzzyMappingOut,
            json=request.model_dump(exclude_none=True), params=params,
        )

    async def delete_mapping(self, space_id: str, mapping_id: int) -> Dict:
        """Delete a fuzzy mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        params = build_query_params(space_id=space_id, mapping_id=mapping_id)
        response = await self._make_authenticated_request(
            "DELETE", self._base_url(), params=params,
        )
        return response.json()

    async def add_property(
        self,
        space_id: str,
        mapping_id: int,
        property_uri: str,
        property_role: str = "include",
        ordinal: int = 0,
    ) -> FuzzyMappingPropertyOut:
        """Add a property to a fuzzy mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID
            property_uri: Predicate URI to include in fuzzy index
            property_role: primary | alias | include
            ordinal: Controls concatenation order

        Returns:
            FuzzyMappingPropertyOut with created property details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id, property_uri=property_uri)
        request = AddFuzzyPropertyRequest(
            property_uri=property_uri, property_role=property_role, ordinal=ordinal,
        )
        params = build_query_params(space_id=space_id, mapping_id=mapping_id)
        return await self._make_typed_request(
            "POST", f"{self._base_url()}/properties", FuzzyMappingPropertyOut,
            json=request.model_dump(), params=params,
        )

    async def remove_property(
        self, space_id: str, mapping_id: int, property_id: int,
    ) -> Dict:
        """Remove a property from a fuzzy mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID
            property_id: Property ID

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id, property_id=property_id)
        params = build_query_params(space_id=space_id, mapping_id=mapping_id, property_id=property_id)
        response = await self._make_authenticated_request(
            "DELETE", f"{self._base_url()}/properties", params=params,
        )
        return response.json()

    async def get_stats(self, space_id: str, mapping_id: int) -> FuzzyMappingStatsResponse:
        """Get index statistics for a fuzzy mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            FuzzyMappingStatsResponse with band_count, entity_count, phonetic_band_count
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        params = build_query_params(space_id=space_id, mapping_id=mapping_id)
        return await self._make_typed_request(
            "GET", f"{self._base_url()}/stats", FuzzyMappingStatsResponse, params=params,
        )

    async def populate(self, space_id: str, mapping_id: int) -> Dict:
        """Trigger full population of fuzzy bands for a mapping.

        Args:
            space_id: Space ID
            mapping_id: Mapping ID

        Returns:
            Dict with population result (entities_indexed count)
        """
        self._check_connection()
        validate_required_params(space_id=space_id, mapping_id=mapping_id)
        params = build_query_params(space_id=space_id, mapping_id=mapping_id)
        response = await self._make_authenticated_request(
            "POST", f"{self._base_url()}/populate", params=params,
        )
        return response.json()
