"""
VitalGraph Client - Vector Indexes Endpoint

Client-side endpoint for Vector Index REST API operations.
"""

import logging
from typing import Any, Dict, List, Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.vector_indexes_model import (
    VectorIndexOut, VectorIndexListResponse,
    CreateVectorIndexRequest, ReindexRequest, ReindexResponse,
    VectorUpsertRequest, VectorUpsertResponse, VectorGetResponse,
    ReindexJobListResponse,
)

logger = logging.getLogger(__name__)


class VectorIndexesClientEndpoint(BaseEndpoint):
    """Client endpoint for Vector Index management operations."""

    def __init__(self, client):
        super().__init__(client)

    def _base_url(self) -> str:
        return f"{self._get_server_url()}/api/vector-indexes"

    async def list_indexes(self, space_id: str) -> VectorIndexListResponse:
        """List all vector indexes for a space.

        Args:
            space_id: Space ID

        Returns:
            VectorIndexListResponse with indexes and total count
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "GET", self._base_url(), VectorIndexListResponse, params=params,
        )

    async def create_index(
        self,
        space_id: str,
        index_name: str,
        dimensions: int,
        distance_metric: str = "cosine",
        provider: str = "vitalsigns",
        model_name: Optional[str] = None,
        provider_config: Optional[Dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> VectorIndexOut:
        """Create a new vector index.

        Args:
            space_id: Space ID
            index_name: Lowercase alphanumeric + underscores
            dimensions: Embedding dimensions
            distance_metric: cosine | l2 | inner_product
            provider: Vectorization provider name
            model_name: Optional model name
            provider_config: Optional provider-specific config
            description: Human-readable description

        Returns:
            VectorIndexOut with created index details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        request = CreateVectorIndexRequest(
            index_name=index_name, dimensions=dimensions,
            distance_metric=distance_metric, provider=provider,
            model_name=model_name, provider_config=provider_config,
            description=description,
        )
        params = build_query_params(space_id=space_id)
        return await self._make_typed_request(
            "POST", self._base_url(), VectorIndexOut,
            json=request.model_dump(exclude_none=True), params=params,
        )

    async def get_index(self, space_id: str, index_name: str) -> VectorIndexOut:
        """Get details for a specific vector index.

        Args:
            space_id: Space ID
            index_name: Index name

        Returns:
            VectorIndexOut with index details and embedding count
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        params = build_query_params(space_id=space_id, index_name=index_name)
        # Server wraps single-index response in VectorIndexListResponse
        resp = await self._make_typed_request(
            "GET", self._base_url(), VectorIndexListResponse, params=params,
        )
        if not resp.indexes:
            from ..utils.client_utils import VitalGraphClientError
            raise VitalGraphClientError(f"Vector index '{index_name}' not found")
        return resp.indexes[0]

    async def delete_index(self, space_id: str, index_name: str) -> Dict:
        """Delete a vector index, its data table, and dependent mappings.

        Args:
            space_id: Space ID
            index_name: Index name

        Returns:
            Dict with confirmation message
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        params = build_query_params(space_id=space_id, index_name=index_name)
        response = await self._make_authenticated_request(
            "DELETE", self._base_url(), params=params,
        )
        return response.json()

    async def reindex(
        self,
        space_id: str,
        index_name: str,
        graph_uri: str,
        mapping_type: Optional[str] = None,
        type_uri: Optional[str] = None,
        batch_size: int = 100,
    ) -> ReindexResponse:
        """Trigger full re-population of a vector index from a graph.

        Args:
            space_id: Space ID
            index_name: Index name
            graph_uri: Graph URI to re-index
            mapping_type: Filter: kgentity | kgdocument | kgframe | kgslot
            type_uri: Filter: specific KG Type URI
            batch_size: Batch size for processing (1-1000)

        Returns:
            ReindexResponse with processing stats
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name, graph_uri=graph_uri)
        request = ReindexRequest(
            graph_uri=graph_uri, mapping_type=mapping_type,
            type_uri=type_uri, batch_size=batch_size,
        )
        params = build_query_params(space_id=space_id, index_name=index_name)
        return await self._make_typed_request(
            "POST", f"{self._base_url()}/reindex", ReindexResponse,
            json=request.model_dump(exclude_none=True), params=params,
        )

    async def get_reindex_status(
        self,
        space_id: str,
        job_id: Optional[str] = None,
        index_name: Optional[str] = None,
    ) -> ReindexJobListResponse:
        """Get status of background reindex tasks.

        Args:
            space_id: Space ID
            job_id: Optional specific job ID to look up
            index_name: Optional filter by index name

        Returns:
            ReindexJobListResponse with list of job statuses
        """
        self._check_connection()
        validate_required_params(space_id=space_id)
        params = build_query_params(space_id=space_id)
        if job_id:
            params["job_id"] = job_id
        if index_name:
            params["index_name"] = index_name
        return await self._make_typed_request(
            "GET", f"{self._base_url()}/reindex/status",
            ReindexJobListResponse, params=params,
        )

    async def upsert_vectors(
        self,
        space_id: str,
        index_name: str,
        vectors: List[Dict[str, Any]],
    ) -> VectorUpsertResponse:
        """Upsert pre-computed vectors into a vector index.

        Args:
            space_id: Space ID
            index_name: Target index name
            vectors: List of dicts with keys: subject_uri, graph_uri, embedding, search_text (optional)

        Returns:
            VectorUpsertResponse with upsert count and errors
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        params = build_query_params(space_id=space_id, index_name=index_name)
        return await self._make_typed_request(
            "POST", f"{self._base_url()}/vectors", VectorUpsertResponse,
            json={"vectors": vectors}, params=params,
        )

    async def get_vectors(
        self,
        space_id: str,
        index_name: str,
        subject_uri: Optional[str] = None,
        graph_uri: Optional[str] = None,
    ) -> VectorGetResponse:
        """Get stored vectors by subject URI and/or graph URI.

        Args:
            space_id: Space ID
            index_name: Index name
            subject_uri: Subject URI to look up
            graph_uri: Graph URI filter

        Returns:
            VectorGetResponse with vectors and total count
        """
        self._check_connection()
        validate_required_params(space_id=space_id, index_name=index_name)
        params = build_query_params(
            space_id=space_id, index_name=index_name,
            subject_uri=subject_uri, graph_uri=graph_uri,
        )
        return await self._make_typed_request(
            "GET", f"{self._base_url()}/vectors", VectorGetResponse, params=params,
        )
