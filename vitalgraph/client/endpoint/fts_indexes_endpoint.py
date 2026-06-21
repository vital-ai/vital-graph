"""
VitalGraph Client - FTS Indexes Endpoint

Client-side endpoint for FTS Index REST API operations.
"""

import logging
from typing import Any, Dict, List, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.fts_index_model import (
    FtsIndexOut, FtsIndexListResponse, FtsIndexStatsResponse,
    CreateFtsIndexRequest, UpdateFtsLanguagesRequest,
    PopulateFtsRequest, PopulateFtsResponse,
    DeleteResponse,
)

logger = logging.getLogger(__name__)


class FtsIndexesClientEndpoint(BaseEndpoint):
    """Client endpoint for FTS index management."""

    def __init__(self, client):
        super().__init__(client)

    def _base_url(self) -> str:
        return f"{self._get_server_url()}/api/fts-indexes"

    async def list_indexes(self, space_id: str) -> FtsIndexListResponse:
        """List all FTS indexes for a space.

        Args:
            space_id: Space ID

        Returns:
            FtsIndexListResponse with indexes and total count
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "GET", self._base_url(), FtsIndexListResponse, params=params,
        )

    async def create_index(
        self,
        space_id: str,
        index_name: str,
        languages: Optional[List[str]] = None,
    ) -> FtsIndexOut:
        """Create a new FTS index.

        Args:
            space_id: Space ID
            index_name: Lowercase alphanumeric + underscores
            languages: PostgreSQL text search languages (default: ['english'])

        Returns:
            FtsIndexOut with created index details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        request = CreateFtsIndexRequest(
            index_name=index_name,
            languages=languages or ["english"],
        )
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "POST", self._base_url(), FtsIndexOut,
            json=request.model_dump(), params=params,
        )

    async def delete_index(
        self, space_id: str, index_name: str,
    ) -> DeleteResponse:
        """Delete an FTS index, its data table, and trigger.

        Args:
            space_id: Space ID
            index_name: Index name

        Returns:
            DeleteResponse with confirmation
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        params = build_query_params(space_id=space_id, index_name=index_name)
        return await self._make_typed_request(
            "DELETE", self._base_url(), DeleteResponse, params=params,
        )

    async def get_stats(
        self, space_id: str, index_name: str,
    ) -> FtsIndexStatsResponse:
        """Get statistics for an FTS data table.

        Args:
            space_id: Space ID
            index_name: Index name

        Returns:
            FtsIndexStatsResponse with row counts
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        params = build_query_params(space_id=space_id, index_name=index_name)
        return await self._make_typed_request(
            "GET", f"{self._base_url()}/stats",
            FtsIndexStatsResponse, params=params,
        )

    async def update_languages(
        self,
        space_id: str,
        index_name: str,
        languages: List[str],
        refresh_tsv: bool = True,
    ) -> FtsIndexOut:
        """Update the languages for an FTS index.

        Args:
            space_id: Space ID
            index_name: Index name
            languages: New language list
            refresh_tsv: Re-compute tsvector values for existing rows

        Returns:
            FtsIndexOut with updated index details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        request = UpdateFtsLanguagesRequest(
            languages=languages, refresh_tsv=refresh_tsv,
        )
        params = build_query_params(space_id=space_id, index_name=index_name)
        return await self._make_typed_request(
            "PUT", f"{self._base_url()}/languages", FtsIndexOut,
            json=request.model_dump(), params=params,
        )

    async def populate(
        self,
        space_id: str,
        index_name: str,
        graph_uri: str,
        mapping_type: Optional[str] = None,
        type_uri: Optional[str] = None,
        batch_size: int = 100,
    ) -> PopulateFtsResponse:
        """Populate FTS data table from entity properties.

        Args:
            space_id: Space ID
            index_name: Index name
            graph_uri: Graph URI to populate from
            mapping_type: Filter: kgentity | kgdocument | kgframe | kgslot
            type_uri: Filter: specific KG Type URI
            batch_size: Batch size for processing

        Returns:
            PopulateFtsResponse with population stats
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name, graph_uri=graph_uri)
        request = PopulateFtsRequest(
            graph_uri=graph_uri, mapping_type=mapping_type,
            type_uri=type_uri, batch_size=batch_size,
        )
        params = build_query_params(space_id=space_id, index_name=index_name)
        return await self._make_typed_request(
            "POST", f"{self._base_url()}/populate", PopulateFtsResponse,
            json=request.model_dump(exclude_none=True), params=params,
        )
