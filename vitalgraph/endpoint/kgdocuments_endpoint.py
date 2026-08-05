"""
KGDocument REST API Endpoint.

Provides CRUD endpoints for KGDocuments plus segmentation management.

Routes:
    GET    /api/kgdocuments                          — list/get KGDocuments
    POST   /api/kgdocuments                          — create KGDocuments
    PUT    /api/kgdocuments                          — update KGDocuments
    DELETE /api/kgdocuments                          — delete KGDocuments
    GET    /api/kgdocuments/segments                  — list segments for a parent
    POST   /api/kgdocuments/segment                  — segment a document
    GET    /api/kgdocuments/segmentation-configs      — list configs
    POST   /api/kgdocuments/segmentation-configs      — create config
    PUT    /api/kgdocuments/segmentation-configs/{id} — update config
    DELETE /api/kgdocuments/segmentation-configs/{id} — delete config
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from ..model.kgdocuments_model import (
    SegmentDocumentRequest,
    SegmentDocumentResponse,
    SegmentationConfigRequest,
    SegmentationConfigResponse,
    SegmentationConfigListResponse,
    SegmentationConfigDeleteResponse,
    SegmentationJobStatusResponse,
    SegmentationStatusSummaryResponse,
    SegmentationWorkerStatus,
    KGDocumentUploadResponse,
)
from vitalgraph.document.segment_deletion import delete_segmentation
from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse, QuadResultsResponse
from vitalgraph.model.result_status import OperationStatus
from vitalgraph.utils.quad_format_utils import (
    _escape_nquads_string,
    graphobjects_to_quad_list,
    parse_nquads_object,
    parse_nquads_uri,
    quad_list_to_graphobjects,
)
from ..kg_impl.kgdocuments_read_impl import KGDocumentsReadProcessor
from ..kg_impl.kg_backend_utils import create_backend_adapter
from ..auth.role_dependencies import require_space_read, require_space_write

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoint class
# ---------------------------------------------------------------------------

VITAL_CORE = "http://vital.ai/ontology/vital-core#"
# FileNode and its hasFile* properties live in the vital# domain namespace, NOT
# vital-core# — using the wrong one fails at store time with
# "No VitalSigns class registered for URI".
VITAL_DOMAIN = "http://vital.ai/ontology/vital#"
HALEY_KG = "http://vital.ai/ontology/haley-ai-kg#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
HAS_NAME = f"{VITAL_CORE}hasName"


def _uri_term(uri: str) -> str:
    """N-Quads URI term: angle-bracketed."""
    return f"<{uri}>"


def _literal_term(value: str) -> str:
    """
    N-Quads literal term: quoted and escaped.

    Quads carry N-Quads-encoded terms (see Quad in quad_model.py), so a literal
    MUST be quoted. Passing a bare string mostly works by accident — the parser
    falls through to "plain string" — but a value that starts with '<' and ends
    with '>' is then read back as a URI and silently loses both characters.
    Every HTML document looks exactly like that, so unquoted HTML round-trips as
    `p>alpha</p`. Always encode.
    """
    return f'"{_escape_nquads_string(value)}"'


class KGDocumentsEndpoint:
    """KGDocument CRUD and segmentation management endpoint."""

    def __init__(self, space_manager, auth_dependency, segmentation_worker=None, config=None):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self._segmentation_worker = segmentation_worker
        self.logger = logging.getLogger(f"{__name__}.KGDocumentsEndpoint")
        self.router = APIRouter()

        # Object storage for uploaded originals. Optional: without it, uploads
        # still work and the converted Markdown is stored — only the original
        # bytes are not retained. Same construction as FilesEndpoint.
        self.file_manager = None
        if config:
            try:
                from ..storage.s3_file_manager import create_s3_file_manager_from_config
                self.file_manager = create_s3_file_manager_from_config(config)
            except Exception as e:
                self.logger.warning(f"Object storage unavailable for document uploads: {e}")

        # Read processor (same pattern as KGTypes)
        self.read_processor = KGDocumentsReadProcessor()

        self._setup_routes()

    # ------------------------------------------------------------------
    # Helper to get backend adapter from space
    # ------------------------------------------------------------------

    async def _get_backend(self, space_id: str):
        """Get backend adapter for a space."""
        if not self.space_manager:
            raise HTTPException(status_code=503, detail="Space manager not available")
        space_record = await self.space_manager.get_space_or_load(space_id)
        if not space_record:
            raise HTTPException(status_code=503, detail=f"Space {space_id} not available")
        space_impl = space_record.space_impl
        backend = space_impl.get_db_space_impl()
        if not backend:
            raise HTTPException(status_code=503, detail="Backend not available")
        return create_backend_adapter(backend), space_impl

    def _setup_routes(self):
        auth = self.auth_dependency

        # ------------------------------------------------------------------
        # CRUD routes
        # ------------------------------------------------------------------

        @self.router.get(
            "/kgdocuments",
            response_model=None,
            tags=["KG Documents"],
            summary="List or Get KG Documents",
            description="List KGDocuments with pagination/search, or get a single document by URI.",
        )
        async def list_kgdocuments(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=100, description="Items per page"),
            offset: int = Query(0, ge=0, description="Pagination offset"),
            search: Optional[str] = Query(None, description="Search text"),
            uri: Optional[str] = Query(None, description="Get specific document by URI"),
            include_segments: bool = Query(False, description="Include segment objects"),
            document_type_uri: Optional[str] = Query(None, description="Filter by document type"),
            current_user: Dict = Depends(auth),
        ):
            require_space_read(current_user, space_id)
            if uri:
                return await self._get_by_uri(space_id, graph_id, uri, include_segments=include_segments)
            return await self._list(
                space_id, graph_id, page_size, offset,
                search=search, include_segments=include_segments,
                document_type_uri=document_type_uri,
            )

        @self.router.post(
            "/kgdocuments",
            response_model=QuadResultsResponse,
            tags=["KG Documents"],
            summary="Create KG Documents",
            description="Create KGDocument objects from quad payload.",
        )
        async def create_kgdocuments(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            body: QuadRequest = Body(..., description="KGDocument quads"),
            current_user: Dict = Depends(auth),
        ):
            require_space_write(current_user, space_id)
            return await self._create(space_id, graph_id, body.quads)

        @self.router.post(
            "/kgdocuments/upload",
            response_model=KGDocumentUploadResponse,
            tags=["KG Documents"],
            summary="Upload a document file and create a KGDocument",
            description=(
                "Accepts a file (HTML, DOCX, PDF, Markdown, plain text), converts it to "
                "Markdown server-side, stores the original in object storage, and creates "
                "a KGDocument whose extracted content is the Markdown."
            ),
        )
        async def upload_kgdocument(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            file: UploadFile = File(..., description="Document file to ingest"),
            headline: Optional[str] = Form(None, description="Document title (defaults to filename)"),
            source_url: Optional[str] = Form(None, description="Original source URL"),
            store_original: bool = Form(True, description="Keep the uploaded bytes in object storage"),
            current_user: Dict = Depends(auth),
        ):
            require_space_write(current_user, space_id)
            return await self._upload_document(
                space_id, graph_id, file, headline, source_url, store_original
            )

        @self.router.put(
            "/kgdocuments",
            response_model=QuadResultsResponse,
            tags=["KG Documents"],
            summary="Update KG Documents",
            description="Update existing KGDocument objects from quad payload.",
        )
        async def update_kgdocuments(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            body: QuadRequest = Body(..., description="KGDocument quads"),
            current_user: Dict = Depends(auth),
        ):
            require_space_write(current_user, space_id)
            return await self._update(space_id, graph_id, body.quads)

        @self.router.delete(
            "/kgdocuments",
            response_model=QuadResultsResponse,
            tags=["KG Documents"],
            summary="Delete KG Documents",
            description="Delete KGDocument(s) by URI. Cascades to segments.",
        )
        async def delete_kgdocuments(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            uri: Optional[str] = Query(None, description="Document URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated URIs"),
            current_user: Dict = Depends(auth),
        ):
            require_space_write(current_user, space_id)
            return await self._delete(space_id, graph_id, uri, uri_list)

        @self.router.get(
            "/kgdocuments/segments",
            response_model=None,
            tags=["KG Documents"],
            summary="List segments for a document",
            description="List segments for a parent copy or original document.",
        )
        async def list_segments(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            parent_uri: str = Query(..., description="Parent copy or original document URI"),
            current_user: Dict = Depends(auth),
        ):
            require_space_read(current_user, space_id)
            return await self._list_segments(space_id, graph_id, parent_uri)

        # ------------------------------------------------------------------
        # Segmentation trigger
        # ------------------------------------------------------------------

        @self.router.post(
            "/kgdocuments/segment",
            response_model=SegmentDocumentResponse,
            tags=["KG Documents"],
            summary="Segment a KGDocument",
            description="Trigger segmentation of a KGDocument into chunks.",
        )
        async def segment_document(
            body: SegmentDocumentRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self._handle_segment(space_id, graph_id, body)

        # ------------------------------------------------------------------
        # Segmentation status
        # ------------------------------------------------------------------

        @self.router.get(
            "/kgdocuments/segmentation-status",
            response_model=SegmentationStatusSummaryResponse,
            tags=["KG Documents"],
            summary="Get segmentation job status",
            description="Get status of segmentation jobs. Optionally filter by document_uri.",
        )
        async def segmentation_status(
            space_id: str = Query(..., description="Space ID"),
            document_uri: Optional[str] = Query(None, description="Filter by document URI"),
            status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
            limit: int = Query(50, ge=1, le=200),
            offset: int = Query(0, ge=0),
            current_user: Dict = Depends(auth),
        ):
            require_space_read(current_user, space_id)
            return await self._handle_segmentation_status(
                space_id, document_uri, status_filter, limit, offset
            )

        # ------------------------------------------------------------------
        # Segmentation config CRUD
        # ------------------------------------------------------------------

        @self.router.get(
            "/kgdocuments/segmentation-configs",
            response_model=SegmentationConfigListResponse,
            tags=["KG Documents"],
            summary="List segmentation configs",
        )
        async def list_configs(
            space_id: str = Query(..., description="Space ID"),
            enabled_only: bool = Query(False),
            current_user: Dict = Depends(auth),
        ):
            return await self._handle_list_configs(space_id, enabled_only)

        @self.router.post(
            "/kgdocuments/segmentation-configs",
            response_model=SegmentationConfigResponse,
            tags=["KG Documents"],
            summary="Create segmentation config",
        )
        async def create_config(
            body: SegmentationConfigRequest,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self._handle_create_config(space_id, body)

        @self.router.put(
            "/kgdocuments/segmentation-configs",
            response_model=SegmentationConfigResponse,
            tags=["KG Documents"],
            summary="Update segmentation config",
        )
        async def update_config(
            body: SegmentationConfigRequest,
            space_id: str = Query(..., description="Space ID"),
            config_id: int = Query(..., description="Config ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self._handle_update_config(space_id, config_id, body)

        @self.router.delete(
            "/kgdocuments/segmentation-configs",
            response_model=SegmentationConfigDeleteResponse,
            tags=["KG Documents"],
            summary="Delete segmentation config",
        )
        async def delete_config(
            space_id: str = Query(..., description="Space ID"),
            config_id: int = Query(..., description="Config ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self._handle_delete_config(space_id, config_id)

    # ------------------------------------------------------------------
    # Segmentation status handler
    # ------------------------------------------------------------------

    def _get_worker_status(self) -> Optional[SegmentationWorkerStatus]:
        """Get worker health info if the worker is available."""
        worker = self._segmentation_worker
        if worker is None:
            return None
        try:
            health = worker.get_health()
            return SegmentationWorkerStatus(**health)
        except Exception as e:
            self.logger.warning(f"Could not get worker health: {e}")
            return SegmentationWorkerStatus(running=False)

    async def _handle_segmentation_status(
        self, space_id: str, document_uri: Optional[str],
        status_filter: Optional[str], limit: int, offset: int,
    ) -> SegmentationStatusSummaryResponse:
        """Handle segmentation status query."""
        from vitalgraph.document.segmentation_job_manager import SegmentationJobManager

        worker_status = self._get_worker_status()

        manager, pool, conn = await self._get_job_manager(space_id)
        if not manager:
            return SegmentationStatusSummaryResponse(worker_status=worker_status)

        try:
            # If querying for a specific document, return its latest job
            if document_uri:
                job = await manager.get_job_status(document_uri)
                if not job:
                    return SegmentationStatusSummaryResponse(worker_status=worker_status)
                job_resp = SegmentationJobStatusResponse(
                    job_id=job.job_id,
                    document_uri=job.document_uri,
                    status=job.status,
                    attempt_count=job.attempt_count,
                    segment_count=job.segment_count,
                    segment_method_uri=job.segment_method_uri,
                    error_message=job.error_message,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                )
                return SegmentationStatusSummaryResponse(
                    **{job.status: 1},
                    jobs=[job_resp],
                    worker_status=worker_status,
                )

            # Space-level summary
            summary = await manager.get_space_summary()
            jobs = await manager.list_jobs(status=status_filter, limit=limit, offset=offset)
            job_responses = [
                SegmentationJobStatusResponse(
                    job_id=j.job_id,
                    document_uri=j.document_uri,
                    status=j.status,
                    attempt_count=j.attempt_count,
                    segment_count=j.segment_count,
                    segment_method_uri=j.segment_method_uri,
                    error_message=j.error_message,
                    created_at=j.created_at,
                    updated_at=j.updated_at,
                )
                for j in jobs
            ]
            return SegmentationStatusSummaryResponse(
                pending=summary.get("pending", 0),
                in_progress=summary.get("in_progress", 0),
                vectorizing=summary.get("vectorizing", 0),
                completed=summary.get("completed", 0),
                failed=summary.get("failed", 0),
                cancelled=summary.get("cancelled", 0),
                jobs=job_responses,
                worker_status=worker_status,
            )
        finally:
            if pool and conn:
                await pool.release(conn)

    async def _get_job_manager(self, space_id: str):
        """Get SegmentationJobManager for a space.

        Returns (manager, pool, conn) so callers can release the connection.
        Returns (None, None, None) on failure.
        """
        from vitalgraph.document.segmentation_job_manager import SegmentationJobManager

        try:
            backend_adapter, space_impl = await self._get_backend(space_id)
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return None, None, None
            conn, pool = await self._get_connection(backend_impl)
            if not conn:
                return None, None, None
            manager = SegmentationJobManager(conn, space_id)
            await manager.ensure_table()
            return manager, pool, conn
        except Exception as e:
            self.logger.error(f"Error getting job manager for {space_id}: {e}")
            return None, None, None

    async def _enqueue_segmentation_job(
        self, space_id: str, graph_id: str, document_uri: str,
        segment_method_uri: Optional[str] = None,
        max_segment_tokens: Optional[int] = None,
    ) -> Optional[int]:
        """Enqueue a background segmentation job. Returns job_id or None."""
        manager, pool, conn = await self._get_job_manager(space_id)
        if not manager:
            self.logger.warning(f"Could not enqueue segmentation job for {document_uri}")
            return None
        try:
            job_id = await manager.enqueue(
                graph_id=graph_id,
                document_uri=document_uri,
                segment_method_uri=segment_method_uri,
                max_segment_tokens=max_segment_tokens,
            )
            return job_id
        except Exception as e:
            self.logger.error(f"Error enqueuing segmentation job: {e}")
            return None
        finally:
            if pool and conn:
                await pool.release(conn)

    # ------------------------------------------------------------------
    # Segmentation handler
    # ------------------------------------------------------------------

    async def _handle_segment(
        self, space_id: str, graph_id: str, body: SegmentDocumentRequest
    ) -> SegmentDocumentResponse:
        """Handle document segmentation request.

        Enqueues a background job and returns immediately.
        Falls back to synchronous processing if the job queue is unavailable.
        """
        try:
            # Try to enqueue as a background job
            job_id = await self._enqueue_segmentation_job(
                space_id=space_id,
                graph_id=graph_id,
                document_uri=body.document_uri,
                segment_method_uri=body.segment_method_uri,
                max_segment_tokens=body.max_segment_tokens,
            )
            if job_id is not None:
                return SegmentDocumentResponse(
                    status=OperationStatus.CREATED,
                    message="Segmentation job enqueued",
                    document_uri=body.document_uri,
                    job_id=job_id,
                    async_mode=True,
                )

            # Job queue unavailable — return error instead of blocking with sync fallback
            logger.warning(f"Job queue unavailable for {body.document_uri}")
            return SegmentDocumentResponse(
                status=OperationStatus.ERROR,
                message="Segmentation job queue unavailable; cannot process request",
                document_uri=body.document_uri,
            )

        except Exception as e:
            logger.error(f"Error segmenting document {body.document_uri}: {e}")
            return SegmentDocumentResponse(
                status=OperationStatus.ERROR,
                message=f"Segmentation failed: {str(e)}",
                document_uri=body.document_uri,
            )

    async def _handle_segment_sync(
        self, space_id: str, graph_id: str, body: SegmentDocumentRequest
    ) -> SegmentDocumentResponse:
        """Synchronous fallback for document segmentation."""
        from vitalgraph.document import (
            KGDocumentSegmentationProcessor,
            MarkdownSegmentConfig,
            PlainSplitConfig,
        )

        # Get space and backend
        space_manager = self.space_manager
        if not space_manager:
            return SegmentDocumentResponse(
                status=OperationStatus.ERROR, message="Space manager not available"
            )

        space_record = await space_manager.get_space_or_load(space_id)
        if not space_record:
            return SegmentDocumentResponse(
                status=OperationStatus.NOT_FOUND, message=f"Space {space_id} not found"
            )

        space_impl = space_record.space_impl
        backend_impl = space_impl.get_db_space_impl()
        if not backend_impl:
            return SegmentDocumentResponse(
                status=OperationStatus.ERROR, message="Backend not available"
            )

        # Fetch original document properties
        doc_properties = await self._fetch_document_properties(
            backend_impl, space_id, graph_id, body.document_uri
        )
        if doc_properties is None:
            return SegmentDocumentResponse(
                status=OperationStatus.NOT_FOUND,
                message=f"Document {body.document_uri} not found",
                document_uri=body.document_uri,
            )

        # Build config
        config = self._build_config(body)

        # Acquire advisory lock on document URI
        lock_manager = getattr(space_impl.backend, "entity_lock_manager", None)
        if lock_manager:
            async with lock_manager.lock(body.document_uri):
                result = await self._execute_segmentation(
                    backend_impl, space_id, graph_id,
                    body.document_uri, doc_properties, config
                )
        else:
            result = await self._execute_segmentation(
                backend_impl, space_id, graph_id,
                body.document_uri, doc_properties, config
            )

        return result

    async def _execute_segmentation(
        self, backend_impl, space_id: str, graph_id: str,
        document_uri: str, doc_properties: dict, config
    ) -> SegmentDocumentResponse:
        """Execute the segmentation pipeline under lock."""
        from vitalgraph.document import KGDocumentSegmentationProcessor

        # Get tokenizer from vector provider if available
        tokenizer = self._get_tokenizer()

        processor = KGDocumentSegmentationProcessor(
            tokenizer=tokenizer, max_input_tokens=self._get_max_input_tokens(),
        )
        output = processor.process(
            original_uri=document_uri,
            original_properties=doc_properties,
            config=config,
        )

        # Delete existing segmentation for this method (if any)
        await self._delete_existing_segmentation(
            backend_impl, space_id, graph_id,
            document_uri, output.method_uri
        )

        # Store parent copy + segments + edges
        await self._store_segmentation_output(
            backend_impl, space_id, graph_id, output
        )

        segment_uris = [seg["URI"] for seg in output.segment_properties_list]

        logger.info(
            f"Segmented {document_uri}: {output.segment_count} segments "
            f"(method={output.method_uri})"
        )

        return SegmentDocumentResponse(
            status=OperationStatus.CREATED,
            message=f"Created {output.segment_count} segments",
            document_uri=document_uri,
            parent_copy_uri=output.parent_copy_properties["URI"],
            method_uri=output.method_uri,
            segment_count=output.segment_count,
            segment_uris=segment_uris,
        )

    def _build_config(self, body: SegmentDocumentRequest):
        """Build segmentation config from request body."""
        from vitalgraph.document import MarkdownSegmentConfig, PlainSplitConfig

        if body.segment_method_uri == "urn:segmethod:plain_recursive_split":
            return PlainSplitConfig(
                max_segment_tokens=body.max_segment_tokens,
                min_segment_tokens=body.min_segment_tokens,
                overlap_tokens=body.overlap_tokens,
            )
        elif body.segment_method_uri == "urn:segmethod:markdown_heading_split":
            return MarkdownSegmentConfig(
                max_segment_tokens=body.max_segment_tokens,
                min_segment_tokens=body.min_segment_tokens,
                overlap_tokens=body.overlap_tokens,
            )
        else:
            # Auto-detect (config=None triggers auto-detection in processor)
            return None

    def _get_tokenizer(self):
        """
        Token counter from the shared local embedding model, or None.

        Uses the process-wide cached provider. The previous version called
        `get_provider("vitalsigns_onnx")` with no cache key, which built a fresh
        tokenizer and ONNX InferenceSession on EVERY call — hundreds of ms to
        seconds — and then looked for a `_tokenizer` attribute the provider does
        not have, so it discarded the model and returned None anyway. That load
        landed inside each segmentation request.
        """
        try:
            from vitalgraph.vectorization import get_local_provider
            provider = get_local_provider()
            embedder = getattr(provider, "_embedder", None) if provider else None
            tokenizer = getattr(embedder, "tokenizer", None) if embedder else None
            if tokenizer is not None:
                return lambda text: len(tokenizer.encode(text))
        except Exception as e:
            logger.debug("Model tokenizer unavailable, using whitespace count: %s", e)
        return None  # Falls back to whitespace tokenizer

    def _get_max_input_tokens(self):
        """
        The embedding model's input ceiling, or None if unknown.

        Segments longer than this are truncated at embed time, so the segmenter
        clamps to it. Reads the shared cached provider — no model load.
        """
        try:
            from vitalgraph.vectorization import get_local_provider
            provider = get_local_provider()
            return provider.max_input_tokens if provider else None
        except Exception:
            return None

    async def _fetch_document_properties(
        self, backend_impl, space_id: str, graph_id: str, document_uri: str
    ) -> Optional[dict]:
        """Fetch document properties from the backend."""
        # Use SPARQL to get document properties
        try:
            sparql = f"""
                PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
                PREFIX vital: <http://vital.ai/ontology/vital-core#>
                
                SELECT ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        <{document_uri}> ?p ?o .
                    }}
                }}
            """
            results = await backend_impl.execute_sparql_select(space_id, sparql)
            if not results:
                return None

            # Convert to property dict
            props = {"URI": document_uri}
            for row in results:
                pred = str(row.get("p", ""))
                obj_val = row.get("o", "")

                # Map full URIs to short property names
                if "hasKGDocumentContent" in pred:
                    props["kGDocumentContent"] = str(obj_val)
                elif "hasKGDocumentExtractedContent" in pred:
                    props["kGDocumentExtractedContent"] = str(obj_val)
                elif "hasKGDocumentHTMLContent" in pred:
                    props["kGDocumentHTMLContent"] = str(obj_val)
                elif "hasKGDocumentHeadline" in pred:
                    props["kGDocumentHeadline"] = str(obj_val)
                elif "hasKGDocumentSummary" in pred:
                    props["kGDocumentSummary"] = str(obj_val)
                elif "hasKGDocumentURL" in pred:
                    props["kGDocumentURL"] = str(obj_val)
                elif "hasKGDocumentType" in pred:
                    props["kGDocumentType"] = str(obj_val)
                elif "hasPrimaryLanguageType" in pred:
                    props["primaryLanguageType"] = str(obj_val)
                elif "hasKGGraphURI" in pred or "kGGraphURI" in pred:
                    props["kGGraphURI"] = str(obj_val)
                elif "hasName" in pred:
                    props["name"] = str(obj_val)

            return props if len(props) > 1 else None

        except Exception as e:
            logger.error(f"Error fetching document properties for {document_uri}: {e}")
            return None

    async def _delete_existing_segmentation(
        self, backend_impl, space_id: str, graph_id: str,
        original_uri: str, method_uri: str
    ) -> None:
        """Delete existing parent copy + segments for this method.

        Scoped to this method, so re-running one segmentation method leaves
        other methods' output intact.
        """
        try:
            deleted = await delete_segmentation(
                backend_impl, space_id, graph_id, original_uri, method_uri
            )
            logger.debug(
                f"Deleted {deleted} existing segmentation object(s) for "
                f"{original_uri} method={method_uri}"
            )
        except Exception as e:
            logger.warning(f"Error deleting existing segmentation: {e}")

    async def _store_segmentation_output(
        self, backend_impl, space_id: str, graph_id: str, output
    ) -> None:
        """Store the segmentation output (parent copy + segments + edges) in quad store."""
        # This is a placeholder — actual implementation would convert
        # the property dicts to VitalSigns KGDocument objects and store as quads.
        # For now, use direct triple insertion.
        from vitalgraph.document.kgdocument_segmentation_processor import SegmentationOutput

        all_objects = []
        # Parent copy
        all_objects.append(("KGDocument", output.parent_copy_properties))
        # Segments
        for seg_props in output.segment_properties_list:
            all_objects.append(("KGDocument", seg_props))
        # Edge: original → parent
        all_objects.append(("Edge_hasKGDocumentSegment", output.edge_original_to_parent))
        # Edges: parent → segments
        for edge_props in output.edge_parent_to_segments:
            all_objects.append(("Edge_hasKGDocumentSegment", edge_props))

        # Convert to quads and store
        quads = self._properties_to_quads(all_objects, graph_id)
        if quads:
            await backend_impl.add_rdf_quads_batch_bulk(space_id, quads)
            logger.info(f"Stored {len(quads)} quads for segmentation output")

    def _properties_to_quads(self, objects: list, graph_id: str) -> list:
        """
        Convert property dicts to RDF quads for storage.

        This uses VitalSigns for proper object creation and serialization.
        """
        try:
            from ai_haley_kg_domain.model.KGDocument import KGDocument
            from ai_haley_kg_domain.model.Edge_hasKGDocumentSegment import Edge_hasKGDocumentSegment

            vs_objects = []
            for obj_type, props in objects:
                if obj_type == "KGDocument":
                    obj = KGDocument()
                    obj.URI = props.get("URI", "")
                    if props.get("name"):
                        obj.name = props["name"]
                    if props.get("kGDocumentContent"):
                        obj.kGDocumentContent = props["kGDocumentContent"]
                    if props.get("kGraphDescription"):
                        obj.kGraphDescription = props["kGraphDescription"]
                    if props.get("kGDocumentType"):
                        obj.kGDocumentType = props["kGDocumentType"]
                    if props.get("kGDocumentSegmentMethodURI"):
                        obj.kGDocumentSegmentMethodURI = props["kGDocumentSegmentMethodURI"]
                    if props.get("kGDocumentSegmentTypeURI"):
                        obj.kGDocumentSegmentTypeURI = props["kGDocumentSegmentTypeURI"]
                    if props.get("kGDocumentSegmentIndex") is not None:
                        obj.kGDocumentSegmentIndex = props["kGDocumentSegmentIndex"]
                    if props.get("kGDocumentSegmentTokenLength"):
                        obj.kGDocumentSegmentTokenLength = props["kGDocumentSegmentTokenLength"]
                    if props.get("kGDocumentHeadline"):
                        obj.kGDocumentHeadline = props["kGDocumentHeadline"]
                    if props.get("kGDocumentURL"):
                        obj.kGDocumentURL = props["kGDocumentURL"]
                    if props.get("primaryLanguageType"):
                        obj.primaryLanguageType = props["primaryLanguageType"]
                    if props.get("kGGraphURI"):
                        obj.kGGraphURI = props["kGGraphURI"]
                    vs_objects.append(obj)

                elif obj_type == "Edge_hasKGDocumentSegment":
                    edge = Edge_hasKGDocumentSegment()
                    edge.URI = props.get("URI", "")
                    edge.edgeSource = props.get("edgeSource", "")
                    edge.edgeDestination = props.get("edgeDestination", "")
                    if props.get("kGGraphURI"):
                        edge.kGGraphURI = props["kGGraphURI"]
                    vs_objects.append(edge)

            # Convert to triples then quads
            from rdflib import URIRef
            graph_uri_ref = URIRef(graph_id)
            all_quads = []

            if vs_objects:
                if len(vs_objects) == 1:
                    triples = vs_objects[0].to_triples()
                else:
                    triples = vs_objects[0].to_triples_list(vs_objects)

                for s, p, o in triples:
                    all_quads.append((s, p, o, graph_uri_ref))

            return all_quads

        except ImportError as e:
            logger.error(f"VitalSigns import error during quad conversion: {e}")
            return []
        except Exception as e:
            logger.error(f"Error converting properties to quads: {e}")
            return []

    # ------------------------------------------------------------------
    # Config handlers
    # ------------------------------------------------------------------

    async def _handle_list_configs(
        self, space_id: str, enabled_only: bool
    ) -> SegmentationConfigListResponse:
        """List segmentation configs."""
        manager, pool, conn = await self._get_config_manager(space_id)
        try:
            configs = await manager.list_configs(enabled_only=enabled_only)
            return SegmentationConfigListResponse(
                configs=[self._dto_to_response(c) for c in configs],
                total_count=len(configs),
            )
        finally:
            if pool and conn:
                await pool.release(conn)

    async def _handle_create_config(
        self, space_id: str, body: SegmentationConfigRequest
    ) -> SegmentationConfigResponse:
        """Create a new segmentation config."""
        manager, pool, conn = await self._get_config_manager(space_id)
        try:
            config_id = await manager.create_config(
                document_type_uri=body.document_type_uri,
                segment_method_uri=body.segment_method_uri,
                max_segment_tokens=body.max_segment_tokens,
                min_segment_tokens=body.min_segment_tokens,
                overlap_tokens=body.overlap_tokens,
                enabled=body.enabled,
                auto_vectorize=body.auto_vectorize,
            )

            config = await manager.get_config(config_id)
            if not config:
                raise HTTPException(status_code=500, detail="Failed to retrieve created config")
            return self._dto_to_response(config, status=OperationStatus.CREATED)
        finally:
            if pool and conn:
                await pool.release(conn)

    async def _handle_update_config(
        self, space_id: str, config_id: int, body: SegmentationConfigRequest
    ) -> SegmentationConfigResponse:
        """Update an existing segmentation config."""
        manager, pool, conn = await self._get_config_manager(space_id)
        try:
            await manager.update_config(
                config_id,
                max_segment_tokens=body.max_segment_tokens,
                min_segment_tokens=body.min_segment_tokens,
                overlap_tokens=body.overlap_tokens,
                enabled=body.enabled,
                auto_vectorize=body.auto_vectorize,
            )

            config = await manager.get_config(config_id)
            if not config:
                return SegmentationConfigResponse(
                    status=OperationStatus.NOT_FOUND,
                    message=f"Segmentation config {config_id} not found",
                    config_id=config_id,
                    document_type_uri=body.document_type_uri,
                    segment_method_uri=body.segment_method_uri,
                )
            return self._dto_to_response(config, status=OperationStatus.UPDATED)
        finally:
            if pool and conn:
                await pool.release(conn)

    async def _handle_delete_config(self, space_id: str, config_id: int):
        """Delete a segmentation config."""
        manager, pool, conn = await self._get_config_manager(space_id)
        try:
            deleted = await manager.delete_config(config_id)
            if not deleted:
                return SegmentationConfigDeleteResponse(
                    status=OperationStatus.NOT_FOUND,
                    message=f"Segmentation config {config_id} not found",
                    config_id=config_id,
                )
            return SegmentationConfigDeleteResponse(
                status=OperationStatus.DELETED,
                message=f"Deleted config {config_id}",
                config_id=config_id,
            )
        finally:
            if pool and conn:
                await pool.release(conn)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_config_manager(self, space_id: str):
        """Get SegmentationConfigManager for a space.

        Uses _get_backend to ensure the space is properly loaded/initialised,
        then obtains a DB connection for the config manager.

        Returns (manager, pool, conn) so callers can release the connection.
        """
        from vitalgraph.document.segmentation_config_manager import SegmentationConfigManager

        # _get_backend raises HTTPException on failure — let it propagate
        _adapter, space_impl = await self._get_backend(space_id)
        backend_impl = space_impl.get_db_space_impl()
        if not backend_impl:
            raise HTTPException(status_code=503, detail="DB backend not available for space")

        conn, pool = await self._get_connection(backend_impl)
        if not conn:
            raise HTTPException(status_code=503, detail="Could not obtain DB connection")

        manager = SegmentationConfigManager(conn, space_id)
        await manager.ensure_table()
        return manager, pool, conn

    async def _get_connection(self, backend_impl):
        """Get a database connection from the backend.

        Returns (conn, pool) tuple so callers can release the connection.

        Supports both backend types:
          - SparqlSQLSpaceImpl  → pool at backend_impl.db_impl._pool
          - FusekiPostgreSQLSpaceImpl → pool at backend_impl.postgresql_impl.connection_pool
        """
        try:
            # SparqlSQLSpaceImpl path
            db = getattr(backend_impl, "db_impl", None)
            if db is not None:
                pool = getattr(db, "_pool", None) or getattr(db, "connection_pool", None)
                if pool is not None:
                    conn = await pool.acquire()
                    return conn, pool

            # FusekiPostgreSQLSpaceImpl path
            pg = getattr(backend_impl, "postgresql_impl", None)
            if pg is not None:
                pool = getattr(pg, "connection_pool", None)
                if pool is not None:
                    conn = await pool.acquire()
                    return conn, pool

            # Fallback: direct attributes
            if hasattr(backend_impl, "_pool"):
                pool = backend_impl._pool
                conn = await pool.acquire()
                return conn, pool
            if hasattr(backend_impl, "connection_pool"):
                pool = backend_impl.connection_pool
                conn = await pool.acquire()
                return conn, pool
        except Exception as e:
            logger.error(f"Error getting DB connection: {e}")
        return None, None

    @staticmethod
    def _dto_to_response(
        dto, status: OperationStatus = OperationStatus.OK
    ) -> SegmentationConfigResponse:
        """Convert DTO to response model."""
        return SegmentationConfigResponse(
            status=status,
            config_id=dto.config_id,
            document_type_uri=dto.document_type_uri,
            segment_method_uri=dto.segment_method_uri,
            max_segment_tokens=dto.max_segment_tokens,
            min_segment_tokens=dto.min_segment_tokens,
            overlap_tokens=dto.overlap_tokens,
            enabled=dto.enabled,
            auto_vectorize=dto.auto_vectorize,
            created_time=dto.created_time,
        )


    # ------------------------------------------------------------------
    # CRUD handlers
    # ------------------------------------------------------------------

    # Managed segment types that cannot be externally created/updated/deleted
    _MANAGED_SEGMENT_TYPES = frozenset([
        "urn:segtype:segmentation_parent",
        "urn:segtype:markdown_section",
        "urn:segtype:text_chunk",
        "urn:segtype:paragraph",
    ])

    _HAS_SEGMENT_TYPE_PRED = "http://vital.ai/ontology/haley-ai-kg#hasKGDocumentSegmentTypeURI"

    async def _get_by_uri(
        self, space_id: str, graph_id: str, uri: str,
        include_segments: bool = False,
    ) -> QuadResultsResponse:
        """Get a single KGDocument by URI.

        When include_segments=True, returns the full document graph:
        original, parent copy, all segment KGDocuments, and connecting edges.
        """
        try:
            backend_adapter, _ = await self._get_backend(space_id)

            if include_segments:
                graph_objects = await self.read_processor.get_document_graph(
                    backend_adapter, space_id, graph_id, uri
                )
                if not graph_objects:
                    return QuadResultsResponse(
                        status=OperationStatus.NOT_FOUND,
                        message=f"KGDocument '{uri}' not found",
                        total_count=0,
                        results=[],
                    )
                quads = await asyncio.to_thread(graphobjects_to_quad_list, graph_objects, graph_id)
                return QuadResultsResponse(
                    message=f"Document graph for '{uri}' ({len(graph_objects)} objects)",
                    total_count=len(graph_objects),
                    results=quads,
                )

            graph_object = await self.read_processor.get_kgdocument_by_uri(
                backend_adapter, space_id, graph_id, uri
            )
            if not graph_object:
                return QuadResultsResponse(
                    status=OperationStatus.NOT_FOUND,
                    message=f"KGDocument '{uri}' not found",
                    total_count=0,
                    results=[],
                )
            quads = await asyncio.to_thread(graphobjects_to_quad_list, [graph_object], graph_id)
            return QuadResultsResponse(
                message=f"Found KGDocument '{uri}'",
                total_count=1,
                results=quads,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGDocument {uri}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def _list(
        self, space_id: str, graph_id: str, page_size: int, offset: int,
        search: Optional[str] = None, include_segments: bool = False,
        document_type_uri: Optional[str] = None,
    ) -> QuadResponse:
        """List KGDocuments with pagination."""
        try:
            backend_adapter, _ = await self._get_backend(space_id)
            triples, total_count = await self.read_processor.list_kgdocuments(
                backend_adapter, space_id, graph_id,
                page_size=page_size, offset=offset,
                search=search, include_segments=include_segments,
                document_type_uri=document_type_uri,
            )
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            graph_objects = (await asyncio.to_thread(GraphObject.from_triples_list, triples)) if triples else []
            quads = await asyncio.to_thread(graphobjects_to_quad_list, graph_objects, graph_id)
            return QuadResponse(
                total_count=total_count,
                page_size=page_size,
                offset=offset,
                results=quads,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing KGDocuments: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # Upload + convert (issue 018 item 4)
    # ------------------------------------------------------------------

    # Conversion needs the whole file in memory — pdfplumber and mammoth both
    # want a seekable buffer, so this path cannot stream the way
    # /files/stream/upload does. Bound it explicitly rather than letting a large
    # upload decide how much memory the server uses.
    MAX_UPLOAD_BYTES = 64 * 1024 * 1024

    async def _upload_document(
        self,
        space_id: str,
        graph_id: str,
        file: "UploadFile",
        headline: Optional[str],
        source_url: Optional[str],
        store_original: bool,
    ) -> KGDocumentUploadResponse:
        """Convert an uploaded file to Markdown and create a KGDocument from it."""
        from vitalgraph.document.document_converter import (
            ConversionError,
            EXT_HTML,
            convert_to_markdown,
        )

        filename = file.filename or "upload"

        data = await file.read()
        if len(data) > self.MAX_UPLOAD_BYTES:
            return KGDocumentUploadResponse(
                status=OperationStatus.INVALID_REQUEST,
                message=(
                    f"File is {len(data)} bytes, over the "
                    f"{self.MAX_UPLOAD_BYTES} byte limit for converted uploads"
                ),
            )
        if not data:
            return KGDocumentUploadResponse(
                status=OperationStatus.INVALID_REQUEST,
                message="Uploaded file is empty",
            )

        # Unsupported type and unreadable file are DOMAIN outcomes: HTTP 200
        # with a non-success status, per the project convention (issues/034).
        try:
            conversion = await asyncio.to_thread(convert_to_markdown, data, filename)
        except ConversionError as e:
            self.logger.info(f"Upload conversion rejected for '{filename}': {e}")
            return KGDocumentUploadResponse(
                status=OperationStatus.INVALID_REQUEST,
                message=str(e),
            )

        title = (headline or "").strip() or filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        safe_name = re.sub(r"[^a-zA-Z0-9]", "_", filename)
        doc_uri = f"urn:kgdocument:{timestamp}:{safe_name}"

        # Preserve the original bytes so the conversion is never the only copy.
        file_node_uri = None
        if store_original:
            file_node_uri = await self._store_original_file(
                space_id, graph_id, doc_uri, filename, data, file.content_type
            )

        quads = self._build_document_quads(
            doc_uri=doc_uri,
            title=title,
            conversion=conversion,
            source_url=source_url,
            file_node_uri=file_node_uri,
            html_extensions=EXT_HTML,
        )

        create_result = await self._create(space_id, graph_id, quads)
        if not create_result.success:
            return KGDocumentUploadResponse(
                status=create_result.status,
                message=create_result.message or "Failed to store the converted document",
            )

        return KGDocumentUploadResponse(
            status=OperationStatus.CREATED,
            message=(
                f"Created '{title}' from {conversion.source_format or 'file'}"
                + (" (converted to Markdown)" if conversion.converted else "")
            ),
            document_uri=doc_uri,
            file_node_uri=file_node_uri,
            source_format=conversion.source_format,
            converted=conversion.converted,
            heading_count=conversion.heading_count,
            content_length=len(conversion.markdown),
        )

    async def _store_original_file(
        self,
        space_id: str,
        graph_id: str,
        doc_uri: str,
        filename: str,
        data: bytes,
        content_type: Optional[str],
    ) -> Optional[str]:
        """
        Put the uploaded bytes in object storage and create a FileNode for them.

        Returns the FileNode URI, or None when object storage is unavailable —
        losing the original copy must not fail the upload, since the converted
        Markdown (the thing users actually search) was produced successfully.
        """
        if not self.file_manager:
            self.logger.info("No object storage configured — original bytes not retained")
            return None

        import io
        import mimetypes

        file_uri = f"{doc_uri}:source"
        object_key = file_uri.replace(":", "_").replace("/", "_")
        resolved_type = (
            content_type
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )

        try:
            await asyncio.to_thread(
                self.file_manager.upload_file,
                io.BytesIO(data),
                object_key,
                resolved_type,
                {
                    "file_uri": file_uri,
                    "space_id": space_id,
                    "graph_id": graph_id or "",
                    "original_filename": filename,
                },
            )
        except Exception as e:
            self.logger.warning(f"Could not store original upload '{filename}': {e}")
            return None

        try:
            file_url = self.file_manager.get_file_url(object_key)
        except Exception:
            file_url = ""

        file_quads = [
            Quad(s=_uri_term(file_uri), p=_uri_term(RDF_TYPE), o=_uri_term(f"{VITAL_DOMAIN}FileNode")),
            Quad(s=_uri_term(file_uri), p=_uri_term(HAS_NAME), o=_literal_term(filename)),
            Quad(s=_uri_term(file_uri), p=_uri_term(f"{VITAL_DOMAIN}hasFileName"), o=_literal_term(filename)),
            Quad(s=_uri_term(file_uri), p=_uri_term(f"{VITAL_DOMAIN}hasFileType"), o=_literal_term(resolved_type)),
            Quad(s=_uri_term(file_uri), p=_uri_term(f"{VITAL_DOMAIN}hasFileLength"), o=_literal_term(str(len(data)))),
        ]
        if file_url:
            file_quads.append(
                Quad(s=_uri_term(file_uri), p=_uri_term(f"{VITAL_DOMAIN}hasFileURL"), o=_literal_term(file_url))
            )

        # _create raises HTTPException on a store failure. Retaining the original
        # is best-effort: the converted Markdown is what users search, so a
        # FileNode problem must degrade to "no original kept", never fail the
        # upload the caller asked for.
        try:
            stored = await self._create(space_id, graph_id, file_quads)
        except Exception as e:
            self.logger.warning(f"FileNode metadata not stored for '{filename}': {e}")
            return None
        if not stored.success:
            self.logger.warning(f"FileNode metadata not stored for '{filename}': {stored.message}")
            return None
        return file_uri

    def _build_document_quads(
        self,
        *,
        doc_uri: str,
        title: str,
        conversion,
        source_url: Optional[str],
        file_node_uri: Optional[str],
        html_extensions,
    ) -> List[Quad]:
        """
        Build the KGDocument quads for a converted upload.

        Property choice follows the priority order `extract_content` already
        implements (kgdocument_segmentation_processor.py:52) — the segmenter
        needs no changes:

          hasKGDocumentExtractedContent  ← the Markdown (preferred by the reader)
          hasKGDocumentHTMLContent       ← the original HTML, when the source was HTML
          hasKGDocumentContent           ← the raw text, when the source was already text
        """
        quads = [
            Quad(s=_uri_term(doc_uri), p=_uri_term(RDF_TYPE), o=_uri_term(f"{HALEY_KG}KGDocument")),
            Quad(s=_uri_term(doc_uri), p=_uri_term(HAS_NAME), o=_literal_term(title)),
            Quad(s=_uri_term(doc_uri), p=_uri_term(f"{HALEY_KG}hasKGDocumentHeadline"), o=_literal_term(title)),
            Quad(
                s=_uri_term(doc_uri),
                p=_uri_term(f"{HALEY_KG}hasKGDocumentExtractedContent"),
                o=_literal_term(conversion.markdown),
            ),
        ]

        if conversion.original_html and conversion.source_format in html_extensions:
            quads.append(
                Quad(
                    s=_uri_term(doc_uri),
                    p=_uri_term(f"{HALEY_KG}hasKGDocumentHTMLContent"),
                    o=_literal_term(conversion.original_html),
                )
            )
        elif not conversion.converted:
            # Already text — Content and ExtractedContent are the same string.
            # Binary sources deliberately get no Content: the original lives in
            # the FileNode, not as an RDF literal.
            quads.append(
                Quad(
                    s=_uri_term(doc_uri),
                    p=_uri_term(f"{HALEY_KG}hasKGDocumentContent"),
                    o=_literal_term(conversion.markdown),
                )
            )

        if source_url:
            quads.append(
                Quad(s=_uri_term(doc_uri), p=_uri_term(f"{HALEY_KG}hasKGDocumentURL"), o=_literal_term(source_url))
            )
        if file_node_uri:
            # hasKGDocumentFileNode is an EDGE class, not a datatype property on
            # KGDocument. Writing it as a plain predicate is accepted by the API
            # and then silently dropped at store time, so the link vanishes with
            # no error anywhere. Model it as a real edge object.
            edge_uri = f"{doc_uri}:filenode_edge"
            quads.extend([
                Quad(
                    s=_uri_term(edge_uri),
                    p=_uri_term(RDF_TYPE),
                    o=_uri_term(f"{HALEY_KG}Edge_hasKGDocumentFileNode"),
                ),
                Quad(
                    s=_uri_term(edge_uri),
                    p=_uri_term(f"{VITAL_CORE}hasEdgeSource"),
                    o=_uri_term(doc_uri),
                ),
                Quad(
                    s=_uri_term(edge_uri),
                    p=_uri_term(f"{VITAL_CORE}hasEdgeDestination"),
                    o=_uri_term(file_node_uri),
                ),
            ])
        return quads

    async def _create(self, space_id: str, graph_id: str, quads: List[Quad]) -> QuadResultsResponse:
        """Create KGDocument(s) from quad payload, with write protection for managed segments."""
        try:
            # Check for managed segment types in incoming quads
            protection_error = self._check_write_protection(quads)
            if protection_error:
                return QuadResultsResponse(
                    status=OperationStatus.INVALID_REQUEST,
                    message=protection_error,
                    total_count=0, results=[],
                )

            backend_adapter, space_impl = await self._get_backend(space_id)

            # Convert quads to GraphObjects
            graph_objects = await asyncio.to_thread(quad_list_to_graphobjects, quads)
            if not graph_objects:
                return QuadResultsResponse(
                    status=OperationStatus.INVALID_REQUEST,
                    message="No valid objects in payload",
                    total_count=0, results=[],
                )

            # Store objects
            result = await backend_adapter.store_objects(space_id, graph_id, graph_objects)
            if not result.success:
                raise HTTPException(status_code=500, detail=result.message)

            # Schedule auto-sync (vectorization + segmentation)
            created_uris = [str(getattr(obj, 'URI', '')) for obj in graph_objects if getattr(obj, 'URI', None)]
            self._schedule_auto_sync(space_impl, space_id, graph_id, created_uris, "upsert")

            return QuadResultsResponse(
                status=OperationStatus.CREATED,
                message=f"Created {len(graph_objects)} KGDocument(s)",
                total_count=len(graph_objects),
                results=quads,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating KGDocuments: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def _update(self, space_id: str, graph_id: str, quads: List[Quad]) -> QuadResultsResponse:
        """Update KGDocument(s) from quad payload, with write protection for managed segments."""
        try:
            # Check for managed segment types in incoming quads
            protection_error = self._check_write_protection(quads)
            if protection_error:
                return QuadResultsResponse(
                    status=OperationStatus.INVALID_REQUEST,
                    message=protection_error,
                    total_count=0, results=[],
                )

            backend_adapter, space_impl = await self._get_backend(space_id)

            # Convert quads to GraphObjects
            graph_objects = await asyncio.to_thread(quad_list_to_graphobjects, quads)
            if not graph_objects:
                return QuadResultsResponse(
                    status=OperationStatus.INVALID_REQUEST,
                    message="No valid objects in payload",
                    total_count=0, results=[],
                )

            # Build delete + insert quads for atomic update
            updated_uris = []
            for obj in graph_objects:
                obj_uri = str(getattr(obj, 'URI', ''))
                if not obj_uri:
                    continue
                updated_uris.append(obj_uri)

                # Delete existing triples for this subject, then insert new ones
                from rdflib import URIRef
                triples = obj.to_triples()
                insert_quads = [(s, p, o, URIRef(graph_id)) for s, p, o in triples]
                delete_quads_for_subj = []  # Will be replaced atomically

                await backend_adapter.update_quads(
                    space_id=space_id,
                    graph_id=graph_id,
                    delete_quads=delete_quads_for_subj,
                    insert_quads=insert_quads,
                )

            # Schedule auto-sync (vectorization + re-segmentation)
            self._schedule_auto_sync(space_impl, space_id, graph_id, updated_uris, "upsert")

            return QuadResultsResponse(
                status=OperationStatus.UPDATED,
                message=f"Updated {len(updated_uris)} KGDocument(s)",
                total_count=len(updated_uris),
                results=quads,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating KGDocuments: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def _delete(
        self, space_id: str, graph_id: str,
        uri: Optional[str], uri_list: Optional[str]
    ) -> QuadResultsResponse:
        """Delete KGDocument(s) with cascade to segments."""
        try:
            # Collect URIs to delete
            uris_to_delete = []
            if uri:
                uris_to_delete.append(uri)
            if uri_list:
                uris_to_delete.extend([u.strip() for u in uri_list.split(",") if u.strip()])

            if not uris_to_delete:
                return QuadResultsResponse(
                    status=OperationStatus.INVALID_REQUEST,
                    message="No URIs provided for deletion",
                    total_count=0, results=[],
                )

            backend_adapter, space_impl = await self._get_backend(space_id)

            deleted_count = 0
            for doc_uri in uris_to_delete:
                # Check write protection: don't allow deleting managed segments directly
                protection_error = await self._check_delete_protection(
                    backend_adapter, space_id, graph_id, doc_uri
                )
                if protection_error:
                    return QuadResultsResponse(
                        status=OperationStatus.INVALID_REQUEST,
                        message=protection_error,
                        total_count=0, results=[],
                    )

                # Delete the document itself
                await backend_adapter.delete_object(space_id, graph_id, doc_uri)

                # Cascade: delete all parent copies and segments (by URI prefix pattern)
                await self._cascade_delete_segments(backend_adapter, space_id, graph_id, doc_uri)

                deleted_count += 1

            # Schedule auto-sync (delete vectors)
            self._schedule_auto_sync(space_impl, space_id, graph_id, uris_to_delete, "delete")

            return QuadResultsResponse(
                status=OperationStatus.DELETED,
                message=f"Deleted {deleted_count} KGDocument(s) with cascade",
                total_count=deleted_count,
                results=[],
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting KGDocuments: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def _list_segments(self, space_id: str, graph_id: str, parent_uri: str) -> QuadResponse:
        """List segments for a parent document."""
        try:
            backend_adapter, _ = await self._get_backend(space_id)
            segments = await self.read_processor.list_segments(
                backend_adapter, space_id, graph_id, parent_uri
            )
            quads = await asyncio.to_thread(graphobjects_to_quad_list, segments, graph_id) if segments else []
            return QuadResponse(
                total_count=len(segments),
                page_size=len(segments),
                offset=0,
                results=quads,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing segments for {parent_uri}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # Write protection helpers
    # ------------------------------------------------------------------

    def _check_write_protection(self, quads: List[Quad]) -> Optional[str]:
        """Reject writes that target managed segment/parent objects.

        Returns an error message (domain validation failure) or None if OK.
        """
        for q in quads:
            # Check if any quad sets a managed segment type. Quad fields carry
            # N-Quads term encoding, so use the real parsers — an escaped quote,
            # a datatype suffix or a language tag all defeat a naive split.
            pred = parse_nquads_uri(q.p)
            obj_val = parse_nquads_object(q.o)
            if isinstance(obj_val, dict):  # language-tagged literal
                obj_val = obj_val.get("value")
            if pred == self._HAS_SEGMENT_TYPE_PRED and obj_val in self._MANAGED_SEGMENT_TYPES:
                return (
                    "Cannot directly create/modify segmentation-managed documents. "
                    "Update the original document instead."
                )
        return None

    async def _check_delete_protection(
        self, backend_adapter, space_id: str, graph_id: str, uri: str
    ) -> Optional[str]:
        """Check if a URI is a managed segment (reject direct deletion).

        Asks the graph what the object *is* — a document is protected because it
        carries a managed hasKGDocumentSegmentTypeURI, not because of how it is
        named. A user document called 'urn:doc:report_seg_2024' is deletable.

        Returns an error message (domain validation failure) or None if OK.
        """
        values = " ".join(f"<{t}>" for t in sorted(self._MANAGED_SEGMENT_TYPES))
        sparql = f"""
            ASK {{
                GRAPH <{graph_id}> {{
                    VALUES ?managed {{ {values} }}
                    <{uri}> <{self._HAS_SEGMENT_TYPE_PRED}> ?managed .
                }}
            }}
        """
        try:
            result = await backend_adapter.execute_sparql_query(space_id, sparql)
        except Exception as e:
            # Fail open: a protection lookup failure must not block an ordinary
            # delete. The cascade is relationship-scoped either way.
            self.logger.warning(f"Segment protection check failed for {uri}: {e}")
            return None

        if result.get("boolean", False):
            return (
                f"Cannot directly delete managed segment '{uri}'. "
                "Delete the original document to cascade."
            )
        return None

    async def _cascade_delete_segments(
        self, backend_adapter, space_id: str, graph_id: str, original_uri: str
    ) -> None:
        """Delete all parent copies, segments, and edges for an original document.

        Unscoped by method — the original is going away, so every method's
        output goes with it.
        """
        try:
            deleted = await delete_segmentation(
                backend_adapter, space_id, graph_id, original_uri, method_uri=None
            )
            self.logger.debug(
                f"Cascade deleted {deleted} segmentation object(s) for {original_uri}"
            )
        except Exception as e:
            self.logger.warning(f"Error cascade-deleting segments for {original_uri}: {e}")

    # ------------------------------------------------------------------
    # Auto-sync helper
    # ------------------------------------------------------------------

    def _schedule_auto_sync(
        self, space_impl, space_id: str, graph_id: str,
        subject_uris: List[str], operation: Literal["upsert", "delete"]
    ) -> None:
        """Schedule background vectorization + segmentation sync."""
        try:
            backend_impl = getattr(space_impl, 'backend', None)
            db_impl = getattr(backend_impl, 'db_impl', None) if backend_impl else None
            if db_impl and subject_uris:
                from ..vectorization.auto_sync import schedule_sync
                schedule_sync(
                    db_impl=db_impl,
                    space_id=space_id,
                    subject_uris=subject_uris,
                    graph_uri=graph_id,
                    operation=operation,
                )
        except Exception as e:
            self.logger.warning(f"auto_sync scheduling failed: {e}")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_kgdocuments_router(space_manager, auth_dependency, segmentation_worker=None, config=None) -> APIRouter:
    """Factory function to create the KGDocuments router."""
    endpoint = KGDocumentsEndpoint(
        space_manager, auth_dependency, segmentation_worker=segmentation_worker, config=config
    )
    return endpoint.router
