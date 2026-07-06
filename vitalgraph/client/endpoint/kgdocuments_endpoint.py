"""
VitalGraph Client KGDocuments Endpoint

Client-side implementation for KGDocuments CRUD operations and segment listing.
Follows the same pattern as KGTypesEndpoint.
"""

import logging
from typing import Dict, Any, Optional, List

from .base_endpoint import BaseEndpoint
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ..utils.format_helpers import (
    ClientWireFormat,
    serialize_graphobjects_for_request,
    deserialize_response_to_graphobjects,
    extract_pagination_from_json_quads,
)
from ..response.client_response import (
    KGDocumentResponse,
    KGDocumentsListResponse,
    KGDocumentCreateResponse,
    KGDocumentUpdateResponse,
    KGDocumentDeleteResponse,
    KGDocumentSegmentsResponse,
    SegmentDocumentClientResponse,
    SegmentationStatusClientResponse,
    SegmentationConfigClientResponse,
    SegmentationConfigListClientResponse,
    SegmentationConfigDeleteClientResponse,
)
from ..response.response_builder import build_success_response, build_error_response

logger = logging.getLogger(__name__)


class KGDocumentsEndpoint(BaseEndpoint):
    """Client endpoint for KGDocuments CRUD operations."""

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_kgdocuments(
        self,
        space_id: str,
        graph_id: str,
        page_size: int = 10,
        offset: int = 0,
        search: Optional[str] = None,
        include_segments: bool = False,
        document_type_uri: Optional[str] = None,
    ) -> KGDocumentsListResponse:
        """
        List KGDocuments with pagination and optional filtering.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            page_size: Number of items per page
            offset: Offset for pagination
            search: Optional search term
            include_segments: Include managed segment children (default False)
            document_type_uri: Filter by document type URI

        Returns:
            KGDocumentsListResponse with .is_success property
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments"
            params = build_query_params(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                search=search,
                include_segments=include_segments,
                document_type_uri=document_type_uri,
            )

            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            graph_objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS)
            pagination = extract_pagination_from_json_quads(response_data)
            return build_success_response(
                KGDocumentsListResponse,
                status_code=200,
                message=f"Retrieved {len(graph_objects)} KGDocuments",
                documents=graph_objects,
                count=pagination.get('total_count', len(graph_objects)),
                page_size=pagination.get('page_size', page_size),
                offset=pagination.get('offset', offset),
            )

        except VitalGraphClientError as e:
            return build_error_response(
                KGDocumentsListResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500,
            )
        except Exception as e:
            logger.error(f"Error listing KGDocuments: {e}")
            return build_error_response(
                KGDocumentsListResponse,
                error_code=500,
                error_message=str(e),
                status_code=500,
            )

    async def get_kgdocument(
        self, space_id: str, graph_id: str, uri: str
    ) -> KGDocumentResponse:
        """
        Get a single KGDocument by URI.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGDocument URI

        Returns:
            KGDocumentResponse with .is_success property
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments"
            params = build_query_params(space_id=space_id, graph_id=graph_id, uri=uri)

            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            graph_objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS)
            if graph_objects:
                return build_success_response(
                    KGDocumentResponse,
                    status_code=200,
                    message=f"Retrieved KGDocument: {uri}",
                    document=graph_objects[0],
                )
            else:
                return build_error_response(
                    KGDocumentResponse,
                    error_code=404,
                    error_message=f"KGDocument not found: {uri}",
                    status_code=404,
                )

        except VitalGraphClientError as e:
            return build_error_response(
                KGDocumentResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500,
            )
        except Exception as e:
            logger.error(f"Error getting KGDocument: {e}")
            return build_error_response(
                KGDocumentResponse,
                error_code=500,
                error_message=str(e),
                status_code=500,
            )

    async def list_segments(
        self, space_id: str, graph_id: str, parent_uri: str
    ) -> KGDocumentSegmentsResponse:
        """
        List segments for a parent KGDocument.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            parent_uri: Parent document URI

        Returns:
            KGDocumentSegmentsResponse with .is_success property
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, parent_uri=parent_uri)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments/segments"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, parent_uri=parent_uri
            )

            response = await self._make_authenticated_request('GET', url, params=params)
            response_data = response.json()
            graph_objects = deserialize_response_to_graphobjects(response_data, ClientWireFormat.JSON_QUADS)
            return build_success_response(
                KGDocumentSegmentsResponse,
                status_code=200,
                message=f"Retrieved {len(graph_objects)} segments for {parent_uri}",
                segments=graph_objects,
                count=len(graph_objects),
                parent_uri=parent_uri,
            )

        except VitalGraphClientError as e:
            return build_error_response(
                KGDocumentSegmentsResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500,
            )
        except Exception as e:
            logger.error(f"Error listing segments: {e}")
            return build_error_response(
                KGDocumentSegmentsResponse,
                error_code=500,
                error_message=str(e),
                status_code=500,
            )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_kgdocuments(
        self, space_id: str, graph_id: str, objects: List[GraphObject]
    ) -> KGDocumentCreateResponse:
        """
        Create KGDocuments from GraphObjects.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of KGDocument GraphObject instances to create

        Returns:
            KGDocumentCreateResponse with .is_success property
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, objects=objects)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments"
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            params = build_query_params(space_id=space_id, graph_id=graph_id)

            response = await self._make_authenticated_request(
                'POST', url, params=params, json=body,
                headers={'Content-Type': content_type},
            )
            response_data = response.json()

            server_success = response_data.get('success', False)
            created_count = response_data.get('total_count', 0)
            if not server_success:
                return build_error_response(
                    KGDocumentCreateResponse,
                    error_code=response.status_code,
                    error_message=response_data.get('message', 'Server reported failure'),
                    status_code=response.status_code,
                )
            return build_success_response(
                KGDocumentCreateResponse,
                status_code=200,
                message=f"Created {created_count} KGDocuments",
                created=True,
                created_count=created_count,
                created_uris=[str(getattr(o, 'URI', '')) for o in objects if getattr(o, 'URI', None)],
            )

        except VitalGraphClientError as e:
            return build_error_response(
                KGDocumentCreateResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500,
            )
        except Exception as e:
            logger.error(f"Error creating KGDocuments: {e}")
            return build_error_response(
                KGDocumentCreateResponse,
                error_code=500,
                error_message=str(e),
                status_code=500,
            )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_kgdocuments(
        self, space_id: str, graph_id: str, objects: List[GraphObject]
    ) -> KGDocumentUpdateResponse:
        """
        Update KGDocuments from GraphObjects.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            objects: List of KGDocument GraphObject instances to update

        Returns:
            KGDocumentUpdateResponse with .is_success property
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, objects=objects)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments"
            body, content_type = serialize_graphobjects_for_request(objects, self.wire_format)
            params = build_query_params(space_id=space_id, graph_id=graph_id)

            response = await self._make_authenticated_request(
                'PUT', url, params=params, json=body,
                headers={'Content-Type': content_type},
            )
            response_data = response.json()

            updated_count = response_data.get('total_count', 0)
            updated_uris = [str(getattr(o, 'URI', '')) for o in objects if getattr(o, 'URI', None)]
            return build_success_response(
                KGDocumentUpdateResponse,
                status_code=200,
                message=f"Updated {updated_count} KGDocuments",
                updated=True,
                updated_count=updated_count,
                updated_uris=updated_uris,
            )

        except VitalGraphClientError as e:
            return build_error_response(
                KGDocumentUpdateResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500,
            )
        except Exception as e:
            logger.error(f"Error updating KGDocuments: {e}")
            return build_error_response(
                KGDocumentUpdateResponse,
                error_code=500,
                error_message=str(e),
                status_code=500,
            )

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_kgdocument(
        self, space_id: str, graph_id: str, uri: str
    ) -> KGDocumentDeleteResponse:
        """
        Delete a KGDocument by URI (cascades to segments).

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri: KGDocument URI to delete

        Returns:
            KGDocumentDeleteResponse with .is_success property
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri=uri)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments"
            params = build_query_params(space_id=space_id, graph_id=graph_id, uri=uri)

            response = await self._make_authenticated_request('DELETE', url, params=params)
            response_data = response.json()

            return build_success_response(
                KGDocumentDeleteResponse,
                status_code=200,
                message=f"Deleted KGDocument: {uri}",
                deleted=True,
                deleted_count=response_data.get('total_count', 1),
                deleted_uris=[uri],
            )

        except VitalGraphClientError as e:
            return build_error_response(
                KGDocumentDeleteResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500,
            )
        except Exception as e:
            logger.error(f"Error deleting KGDocument: {e}")
            return build_error_response(
                KGDocumentDeleteResponse,
                error_code=500,
                error_message=str(e),
                status_code=500,
            )

    async def delete_kgdocuments_batch(
        self, space_id: str, graph_id: str, uri_list: str
    ) -> KGDocumentDeleteResponse:
        """
        Delete multiple KGDocuments by URI list (cascades to segments).

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            uri_list: Comma-separated list of KGDocument URIs

        Returns:
            KGDocumentDeleteResponse with .is_success property
        """
        self._check_connection()
        validate_required_params(space_id=space_id, graph_id=graph_id, uri_list=uri_list)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments"
            params = build_query_params(
                space_id=space_id, graph_id=graph_id, uri_list=uri_list
            )

            response = await self._make_authenticated_request('DELETE', url, params=params)
            response_data = response.json()

            deleted_uris = [u.strip() for u in uri_list.split(',') if u.strip()]
            return build_success_response(
                KGDocumentDeleteResponse,
                status_code=200,
                message=f"Deleted {len(deleted_uris)} KGDocuments",
                deleted=True,
                deleted_count=response_data.get('total_count', len(deleted_uris)),
                deleted_uris=deleted_uris,
            )

        except VitalGraphClientError as e:
            return build_error_response(
                KGDocumentDeleteResponse,
                error_code=e.status_code or 500,
                error_message=str(e),
                status_code=e.status_code or 500,
            )
        except Exception as e:
            logger.error(f"Error deleting KGDocuments batch: {e}")
            return build_error_response(
                KGDocumentDeleteResponse,
                error_code=500,
                error_message=str(e),
                status_code=500,
            )

    # ------------------------------------------------------------------
    # Segmentation trigger
    # ------------------------------------------------------------------

    async def segment_document(
        self,
        space_id: str,
        graph_id: str,
        document_uri: str,
        segment_method_uri: Optional[str] = None,
        max_segment_tokens: Optional[int] = None,
    ) -> SegmentDocumentClientResponse:
        """
        Trigger segmentation for a KGDocument.

        Args:
            space_id: Space identifier
            graph_id: Graph identifier
            document_uri: URI of the document to segment
            segment_method_uri: Optional segmentation method override
            max_segment_tokens: Optional max tokens per segment override

        Returns:
            SegmentDocumentClientResponse with segmentation results
        """
        self._check_connection()
        validate_required_params(
            space_id=space_id, graph_id=graph_id, document_uri=document_uri
        )

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments/segment"
            params = build_query_params(space_id=space_id, graph_id=graph_id)
            body: Dict[str, Any] = {"document_uri": document_uri}
            if segment_method_uri:
                body["segment_method_uri"] = segment_method_uri
            if max_segment_tokens is not None:
                body["max_segment_tokens"] = max_segment_tokens

            response = await self._make_authenticated_request(
                'POST', url, params=params, json=body
            )
            data = response.json()
            data.setdefault("error_code", 0)
            data.setdefault("status_code", response.status_code)
            return SegmentDocumentClientResponse(**data)

        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error segmenting document: {e}")
            raise VitalGraphClientError(f"Segmentation failed: {e}")

    # ------------------------------------------------------------------
    # Segmentation status
    # ------------------------------------------------------------------

    async def get_segmentation_status(
        self,
        space_id: str,
        document_uri: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SegmentationStatusClientResponse:
        """
        Get segmentation job status for a space or specific document.

        Args:
            space_id: Space identifier
            document_uri: Optional document URI to filter by
            status: Optional status filter (pending/in_progress/completed/failed)
            limit: Max jobs to return
            offset: Pagination offset

        Returns:
            SegmentationStatusClientResponse with summary counts and job list
        """
        self._check_connection()
        validate_required_params(space_id=space_id)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments/segmentation-status"
            params: Dict[str, Any] = {"space_id": space_id, "limit": limit, "offset": offset}
            if document_uri:
                params["document_uri"] = document_uri
            if status:
                params["status"] = status

            response = await self._make_authenticated_request('GET', url, params=params)
            data = response.json()
            data.setdefault("error_code", 0)
            data.setdefault("status_code", response.status_code)
            return SegmentationStatusClientResponse(**data)

        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error getting segmentation status: {e}")
            raise VitalGraphClientError(f"Failed to get segmentation status: {e}")

    # ------------------------------------------------------------------
    # Segmentation config CRUD
    # ------------------------------------------------------------------

    async def list_segmentation_configs(
        self,
        space_id: str,
        enabled_only: bool = False,
    ) -> SegmentationConfigListClientResponse:
        """
        List segmentation configs for a space.

        Args:
            space_id: Space identifier
            enabled_only: If True, return only enabled configs

        Returns:
            SegmentationConfigListClientResponse with configs list and total_count
        """
        self._check_connection()
        validate_required_params(space_id=space_id)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments/segmentation-configs"
            params: Dict[str, Any] = {"space_id": space_id}
            if enabled_only:
                params["enabled_only"] = True

            response = await self._make_authenticated_request('GET', url, params=params)
            data = response.json()
            data.setdefault("error_code", 0)
            data.setdefault("status_code", response.status_code)
            return SegmentationConfigListClientResponse(**data)

        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error listing segmentation configs: {e}")
            raise VitalGraphClientError(f"Failed to list segmentation configs: {e}")

    async def create_segmentation_config(
        self,
        space_id: str,
        document_type_uri: str,
        segment_method_uri: str,
        max_segment_tokens: int = 1024,
        min_segment_tokens: int = 50,
        overlap_tokens: int = 0,
        enabled: bool = True,
        auto_vectorize: bool = True,
    ) -> SegmentationConfigClientResponse:
        """
        Create a segmentation config.

        Args:
            space_id: Space identifier
            document_type_uri: KGDocumentType URI to match
            segment_method_uri: Segmentation method URI to apply
            max_segment_tokens: Maximum tokens per segment (default 1024 for OpenAI)
            min_segment_tokens: Minimum tokens per segment
            overlap_tokens: Token overlap between segments
            enabled: Enable the config immediately
            auto_vectorize: Auto-vectorize segments after creation

        Returns:
            SegmentationConfigClientResponse with created config details
        """
        self._check_connection()
        validate_required_params(
            space_id=space_id,
            document_type_uri=document_type_uri,
            segment_method_uri=segment_method_uri,
        )

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments/segmentation-configs"
            params = build_query_params(space_id=space_id)
            body = {
                "document_type_uri": document_type_uri,
                "segment_method_uri": segment_method_uri,
                "max_segment_tokens": max_segment_tokens,
                "min_segment_tokens": min_segment_tokens,
                "overlap_tokens": overlap_tokens,
                "enabled": enabled,
                "auto_vectorize": auto_vectorize,
            }

            response = await self._make_authenticated_request(
                'POST', url, params=params, json=body
            )
            data = response.json()
            data.setdefault("error_code", 0)
            data.setdefault("status_code", response.status_code)
            return SegmentationConfigClientResponse(**data)

        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error creating segmentation config: {e}")
            raise VitalGraphClientError(f"Failed to create segmentation config: {e}")

    async def update_segmentation_config(
        self,
        space_id: str,
        config_id: int,
        document_type_uri: str,
        segment_method_uri: str,
        max_segment_tokens: int = 1024,
        min_segment_tokens: int = 50,
        overlap_tokens: int = 0,
        enabled: bool = True,
        auto_vectorize: bool = True,
    ) -> SegmentationConfigClientResponse:
        """
        Update an existing segmentation config.

        Args:
            space_id: Space identifier
            config_id: Config ID to update
            document_type_uri: KGDocumentType URI to match
            segment_method_uri: Segmentation method URI to apply
            max_segment_tokens: Maximum tokens per segment (default 1024 for OpenAI)
            min_segment_tokens: Minimum tokens per segment
            overlap_tokens: Token overlap between segments
            enabled: Enable/disable the config
            auto_vectorize: Auto-vectorize segments after creation

        Returns:
            SegmentationConfigClientResponse with updated config details
        """
        self._check_connection()
        validate_required_params(space_id=space_id, config_id=config_id)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments/segmentation-configs"
            params = build_query_params(space_id=space_id, config_id=config_id)
            body = {
                "document_type_uri": document_type_uri,
                "segment_method_uri": segment_method_uri,
                "max_segment_tokens": max_segment_tokens,
                "min_segment_tokens": min_segment_tokens,
                "overlap_tokens": overlap_tokens,
                "enabled": enabled,
                "auto_vectorize": auto_vectorize,
            }

            response = await self._make_authenticated_request(
                'PUT', url, params=params, json=body
            )
            data = response.json()
            data.setdefault("error_code", 0)
            data.setdefault("status_code", response.status_code)
            return SegmentationConfigClientResponse(**data)

        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error updating segmentation config: {e}")
            raise VitalGraphClientError(f"Failed to update segmentation config: {e}")

    async def delete_segmentation_config(
        self,
        space_id: str,
        config_id: int,
    ) -> SegmentationConfigDeleteClientResponse:
        """
        Delete a segmentation config.

        Args:
            space_id: Space identifier
            config_id: Config ID to delete

        Returns:
            SegmentationConfigDeleteClientResponse with deletion confirmation
        """
        self._check_connection()
        validate_required_params(space_id=space_id, config_id=config_id)

        try:
            url = f"{self._get_server_url()}/api/graphs/kgdocuments/segmentation-configs"
            params = build_query_params(space_id=space_id, config_id=config_id)

            response = await self._make_authenticated_request('DELETE', url, params=params)
            data = response.json()
            return SegmentationConfigDeleteClientResponse(
                deleted=data.get("deleted", True),
                config_id=config_id,
                error_code=0,
                status_code=response.status_code,
                message=data.get("message", "Segmentation config deleted"),
            )

        except VitalGraphClientError:
            raise
        except Exception as e:
            logger.error(f"Error deleting segmentation config: {e}")
            raise VitalGraphClientError(f"Failed to delete segmentation config: {e}")

    # ------------------------------------------------------------------
    # Vector index / mapping convenience wrappers
    # ------------------------------------------------------------------

    async def setup_document_segments_index(
        self,
        space_id: str,
        dimensions: int = 1536,
        distance_metric: str = "cosine",
        provider: str = "openai",
        model_name: Optional[str] = "text-embedding-3-small",
        description: Optional[str] = "Document segment embeddings for chunk retrieval",
    ):
        """
        Create the ``document_segments`` vector index for a space.

        Convenience wrapper around ``client.vector_indexes.create_index()``.
        Uses sensible defaults for document segmentation (OpenAI).

        Args:
            space_id: Space identifier
            dimensions: Embedding dimensions (default 1536 for text-embedding-3-small)
            distance_metric: cosine | l2 | inner_product
            provider: Vectorization provider name
            model_name: Embedding model name
            description: Human-readable description
        """
        self._check_connection()
        return await self.client.vector_indexes.create_index(
            space_id=space_id,
            index_name="document_segments",
            dimensions=dimensions,
            distance_metric=distance_metric,
            provider=provider,
            model_name=model_name,
            description=description,
        )

    async def setup_document_segments_mapping(
        self,
        space_id: str,
        type_uri: Optional[str] = None,
        enabled: bool = True,
    ):
        """
        Create a vector mapping that routes KGDocument segments to the
        ``document_segments`` index.

        Convenience wrapper around ``client.search_mappings.create_mapping()``.

        Args:
            space_id: Space identifier
            type_uri: Specific document type URI to map (None = all KGDocuments)
            enabled: Enable vectorization immediately
        """
        self._check_connection()
        return await self.client.search_mappings.create_mapping(
            space_id=space_id,
            index_name="document_segments",
            mapping_type="kgdocument",
            type_uri=type_uri,
            enabled=enabled,
        )

    async def reindex_document_segments(
        self,
        space_id: str,
        graph_uri: str,
        type_uri: Optional[str] = None,
        batch_size: int = 100,
    ):
        """
        Re-populate the ``document_segments`` vector index from a graph.

        Convenience wrapper around ``client.vector_indexes.reindex()``.

        Args:
            space_id: Space identifier
            graph_uri: Graph URI to re-index
            type_uri: Filter by specific KGDocument type URI
            batch_size: Batch size for processing
        """
        self._check_connection()
        return await self.client.vector_indexes.reindex(
            space_id=space_id,
            index_name="document_segments",
            graph_uri=graph_uri,
            mapping_type="kgdocument",
            type_uri=type_uri,
            batch_size=batch_size,
        )
