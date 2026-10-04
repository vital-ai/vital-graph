"""
KG Frames REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing KG frames and their slots.
KG frames represent structured knowledge frames with connected slot nodes and values.

Follows MockKGFramesEndpoint patterns with proper VitalSigns integration:
- Backend interface usage via SpaceBackendInterface
- VitalSigns graph objects conversion (KGFrame, KGSlot, Edge_hasKGSlot)
- Grouping URI management (frameGraphURI)
- Operation modes (CREATE, UPDATE, UPSERT)
- Complete sub-endpoint support
"""

import asyncio
import logging
from typing import Dict, List, Literal, Optional, Union, Any
from fastapi import APIRouter, Query, Depends, Request, Response, Body, HTTPException
from pydantic import BaseModel, Field, TypeAdapter
from enum import Enum

from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse, QuadResultsResponse
from vitalgraph.model.result_status import OperationStatus
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects, graphobjects_to_quad_list
from ..model.kgframes_model import (
    FrameGraphResponse,
    FrameCreateResponse,
    FrameUpdateResponse,
    FrameDeleteResponse,
    SlotCreateResponse,
    SlotUpdateResponse,
    SlotDeleteResponse,
    FrameQueryRequest,
    FrameQueryResponse,
)
from ..kg_impl.kg_sparql_utils import KGSparqlUtils

# VitalSigns imports for proper graph object handling
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGSlot import KGSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGBooleanSlot import KGBooleanSlot
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge
from vital_ai_vitalsigns.model.GraphObject import GraphObject
import vital_ai_vitalsigns as vitalsigns

# KGFrames endpoint is independent of entity processors - uses direct backend storage

# Import new frame processors
from ..kg_impl.kgframe_graph_impl import KGFrameGraphProcessor

# Import backend utilities
from ..kg_impl.kg_backend_utils import (
    all_prechecks, create_backend_adapter, create_refuses_existing,
    refuse_existing_precheck, standalone_precheck)
from ..cache.count_cache import _count_cache
from ..auth.role_dependencies import require_space_read, require_space_write
from .impl.impl_utils import SubjectWriteFailed
from ..kg_impl.kg_backend_utils import (
    AmbiguousPrecondition, GuardUnsatisfiable, StaleWrite)
from ..kg_impl.frame_grouping import UngroupableSlot, assign_frame_groupings
from functools import partial
from ..utils.bounded_gather import bounded_gather
from ..kg_impl.refusals import RequestRefused



class OperationMode(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"
    REPLACE = "replace"


class KGFramesEndpoint:
    """KG Frames endpoint handler with VitalSigns integration and backend interface usage."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.KGFramesEndpoint")
        self.router = APIRouter()
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
        
        # Initialize VitalSigns integration components (following MockKGFramesEndpoint patterns)
        from ..sparql.grouping_uri_queries import GroupingURIQueryBuilder, GroupingURIGraphRetriever
        from ..sparql.graph_validation import FrameGraphValidator
        
        self.grouping_uri_builder = GroupingURIQueryBuilder()
        self.graph_retriever = GroupingURIGraphRetriever(self.grouping_uri_builder)
        self.frame_validator = FrameGraphValidator()
        
        # Initialize frame processors (these don't require backend in __init__)
        self.frame_graph_processor = KGFrameGraphProcessor()

        # Standalone frame processor (initialized when needed, no entity dependency)
        self.frame_processor = None
        
        self._setup_routes()
    
    async def _get_backend_adapter(self, space_id: str):
        """Get backend adapter for the space."""
        space_record = await self.space_manager.get_space_or_load(space_id)
        if not space_record:
            raise ValueError(f"Space not found: {space_id}")
        
        space_impl = space_record.space_impl
        
        # KGFrames endpoint uses direct backend storage - no processors needed
        backend = space_impl.get_db_space_impl()
        if not backend:
            raise ValueError(f"Backend not available for space: {space_id}")
        
        return create_backend_adapter(backend)

    def _schedule_auto_sync(self, backend_impl, space_id: str, graph_id: str,
                            subject_uris: List[str], operation: Literal["upsert", "delete"] = "upsert") -> None:
        """Schedule background auto-sync for vector and geo data."""
        db_impl = getattr(backend_impl, 'db_impl', None)
        if db_impl and subject_uris:
            from ..vectorization.auto_sync import schedule_sync
            schedule_sync(
                db_impl=db_impl,
                space_id=space_id,
                subject_uris=subject_uris,
                graph_uri=graph_id,
                operation=operation,
            )

    async def _create_frames(
        self, space_id: str, graph_id: str, quads: List[Quad],
        operation_mode: str, entity_uri: Optional[str] = None,
        parent_uri: Optional[str] = None, current_user: Dict = None,
        if_unmodified_since: Optional[str] = None,
    ):
        """Create or update standalone frames from quads.

        Applies the validation pipeline:
        1. Convert quads to GraphObjects
        2. Extract KGFrame instances from the object list
        3. Set frameGraphURI grouping (no kGGraphURI — entity-scoped concept)
        4. Validate frame structure (at least one frame, valid types)
        5. Handle parent relationships and create edges
        6. Dispatch to mode-specific handler (create / update / upsert / replace)

        Note: entity_uri is accepted for backward compatibility but is NOT used.
        Standalone frames have no entity dependency.
        """
        vitalsigns_objects = quad_list_to_graphobjects(quads)
        # AN UNKNOWN MODE IS REFUSED (`issues/256` item 5). It became CREATE, so
        # a misspelt `upsert` silently wrote a create.
        try:
            op_mode = OperationMode(str(operation_mode).lower())
        except ValueError:
            return FrameCreateResponse(
                status=OperationStatus.INVALID_REQUEST,
                message=(f"Unknown operation_mode {operation_mode!r}: expected "
                         f"create, update, upsert or replace"),
                created_count=0, created_uris=[], slots_created=0)

        def _fail_create(msg, status=OperationStatus.ERROR):
            return FrameCreateResponse(status=status, message=msg, created_count=0, created_uris=[], slots_created=0)

        def _fail_update(msg, status=OperationStatus.ERROR):
            return FrameUpdateResponse(status=status, message=msg, updated_uri="", updated_count=0)

        def _fail(msg, status=OperationStatus.ERROR):
            return _fail_update(msg, status) if op_mode == OperationMode.UPDATE else _fail_create(msg, status)

        try:
            # --- backend ---
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return _fail(f"Space {space_id} not found", OperationStatus.NOT_FOUND)
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=503, detail="Backend implementation not available")
            backend = create_backend_adapter(backend_impl)

            # --- type filtering ---
            frames = [obj for obj in vitalsigns_objects if isinstance(obj, KGFrame)]
            if not frames:
                return _fail("No valid KGFrame objects found in request", OperationStatus.INVALID_REQUEST)

            # --- grouping URIs ---
            # Standalone frames use only frameGraphURI (no kGGraphURI, no entity_uri)
            self._set_frame_grouping_uris(frames, graph_id)

            # --- structure validation ---
            validation_result = self._validate_frame_structure(vitalsigns_objects)
            if not validation_result.get("valid", False):
                return _fail(f"Frame validation failed: {validation_result.get('error')}", OperationStatus.INVALID_REQUEST)

            # --- no entity's frame, as target or parent (`issues/256`, decision 3) ---
            # An ENTITY as the parent is refused here: this route would attach the
            # frame with an `Edge_hasEntityKGFrame` without the entity's lock. An
            # entity's FRAME, as target or parent, is refused by `precheck` inside
            # the write's transaction, after its lock.
            if parent_uri:
                _parent = await self._validate_parent_object(backend, space_id, graph_id, parent_uri)
                if _parent.get("type") == "entity":
                    return _fail(
                        f"parent_uri {parent_uri} is an entity: an entity's frames are "
                        f"written through /kgentities/kgframes, which takes its lock",
                        OperationStatus.INVALID_REQUEST)
            # `update` refuses a missing frame with NOT_FOUND instead of
            # creating it (`issues/256` item 3) — decided under the lock too.
            precheck = standalone_precheck(
                space_id, graph_id, [str(f.URI) for f in frames], parent_uri,
                require_existing=(op_mode == OperationMode.UPDATE))
            # `create` refuses an existing frame (`issues/256` item 3), when
            # switched on: anything the CLIENT sent, not the parent links added
            # below.
            if op_mode == OperationMode.CREATE and create_refuses_existing():
                precheck = all_prechecks(precheck, refuse_existing_precheck(
                    space_id, graph_id,
                    [str(o.URI) for o in vitalsigns_objects if getattr(o, 'URI', None)]))

            # --- parent / entity relationships ---
            enhanced_objects = await self._handle_parent_relationships(
                backend, space_id, graph_id, frames, vitalsigns_objects, parent_uri
            )

            # --- dispatch by mode ---
            if op_mode == OperationMode.CREATE:
                _result = await self._handle_create_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri,
                                                         if_unmodified_since=if_unmodified_since, precheck=precheck)
            elif op_mode == OperationMode.UPDATE:
                _result = await self._handle_update_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri,
                                                         if_unmodified_since=if_unmodified_since, precheck=precheck)
            elif op_mode == OperationMode.UPSERT:
                _result = await self._handle_upsert_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri,
                                                         if_unmodified_since=if_unmodified_since, precheck=precheck)
            elif op_mode == OperationMode.REPLACE:
                _result = await self._handle_replace_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri,
                                                         if_unmodified_since=if_unmodified_since, precheck=precheck)
            else:
                return _fail(f"Invalid operation_mode: {op_mode}", OperationStatus.INVALID_REQUEST)

            # Auto-sync vector/geo data for changed subjects
            _sync_uris = [str(o.URI) for o in enhanced_objects if hasattr(o, 'URI') and o.URI]
            self._schedule_auto_sync(backend_impl, space_id, graph_id, _sync_uris)

            return _result

        except HTTPException:
            raise
        except RequestRefused as e:
            # A caller error in a 200 (`issues/257`): the request did not say
            # which frame a slot belongs to, so nothing was written.
            if str(operation_mode).lower() == "update":
                return FrameUpdateResponse(
                    status=OperationStatus(e.status), message=str(e),
                    updated_uri="", updated_count=0)
            return FrameCreateResponse(
                status=OperationStatus(e.status), message=str(e),
                created_count=0, created_uris=[], slots_created=0)
        except StaleWrite as e:
            # REFUSED because the FRAME moved (`issues/253`). A domain outcome in
            # a 200 body, per this codebase's convention: the caller re-reads,
            # re-merges and retries. Nothing is broken and nothing was written.
            self.logger.warning("Frame write refused as stale: %s", e)
            if str(operation_mode).lower() == "update":
                return FrameUpdateResponse(
                    status=OperationStatus.CONFLICT, message=str(e),
                    updated_uri="", updated_count=0)
            return FrameCreateResponse(
                status=OperationStatus.CONFLICT, message=str(e),
                created_count=0, created_uris=[], slots_created=0)
        except GuardUnsatisfiable as e:
            # A DESCRIBABLE DATA REASON, so STORE_FAILED in a 200 — not the
            # 500 that an unhandled exception becomes (`issues/253`; see
            # `GuardUnsatisfiable` and `model/result_status.py`). `str(e)` is
            # the point: it names the subjects, or the conflicting stamps.
            self.logger.error("Frame write undecidable: %s", e)
            if str(operation_mode).lower() == "update":
                return FrameUpdateResponse(
                    status=OperationStatus.STORE_FAILED, message=str(e),
                    updated_uri="", updated_count=0)
            return FrameCreateResponse(
                status=OperationStatus.STORE_FAILED, message=str(e),
                created_count=0, created_uris=[], slots_created=0)
        except AmbiguousPrecondition as e:
            # The caller's request, not the data: one stamp cannot cover several
            # frames. INVALID_REQUEST so it is not mistaken for a conflict and
            # retried unchanged.
            # NO local import of the response models in this function: one made
            # the names LOCAL to all of it, so `_fail` above raised "cannot access
            # free variable" on every early return, and each became a 500. The
            # module imports them.
            self.logger.warning("Frame write precondition is ambiguous: %s", e)
            if str(operation_mode).lower() == "update":
                return FrameUpdateResponse(
                    status=OperationStatus.INVALID_REQUEST, message=str(e),
                    updated_uri="", updated_count=0)
            return FrameCreateResponse(
                status=OperationStatus.INVALID_REQUEST, message=str(e),
                created_count=0, created_uris=[], slots_created=0)
        except Exception as e:
            self.logger.error(f"Frame operation from objects failed: {e}")
            raise HTTPException(status_code=500, detail=f"Frame operation failed: {e}")

    # `_delete_frames`, `_get_frames`, `_get_entity_frames` and `_delete_entities`
    # were DELETED here 2026-10-02 (`issues/256`). Nothing in the service called
    # them; the routes use `_delete_frames_by_uris` and `_list_frames`.
    # `_delete_frames` reported DELETED whatever happened. `_delete_frame_by_uri`
    # went 2026-10-04: single and batch are one locked delete now.
    
    # Slot endpoint methods for /api/graphs/kgframes/kgslots
    
    def _setup_routes(self):
        """Setup FastAPI routes for KG frames management."""
        
        @self.router.get("/kgframes", tags=["KG Frames"])
        async def list_or_get_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of frames per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            search: Optional[str] = Query(None, description="Search text to find in frame properties"),
            parent_uri: Optional[str] = Query(None, description="Return only the CHILD frames of this parent frame (reached by Edge_hasKGFrame)"),
            uri: Optional[str] = Query(None, description="Single frame URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs"),
            include_frame_graph: bool = Query(False, description="If True, include complete frame graph with slots"),
            sort_by: Optional[str] = Query(None, description="Property URI to sort by (e.g. vital-core:hasName). Must be one of the allowed sortable properties."),
            sort_order: str = Query("asc", description="Sort order: 'asc' or 'desc'"),
            form_type: Optional[str] = Query(None, description="Filter by hasKGFormType: 'Assertion', 'Aspect', or full URI"),
            frame_type_uri: Optional[str] = Query(None, description="Filter by hasKGFrameType (the frame's KGFrameType URI)"),
            status: Optional[str] = Query(None, description="Filter by status URI (exact match on hasObjectStatusType)"),
            exclude_status: Optional[str] = Query(None, description="Exclude frames with this status URI"),
            created_after: Optional[str] = Query(None, description="Frames created after this ISO 8601 datetime"),
            created_before: Optional[str] = Query(None, description="Frames created before this ISO 8601 datetime"),
            modified_after: Optional[str] = Query(None, description="Frames modified after this ISO 8601 datetime"),
            modified_before: Optional[str] = Query(None, description="Frames modified before this ISO 8601 datetime"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """
            List KG frames with pagination, filtering, and sorting — or get specific frames by URI(s).

            **Retrieval modes:**
            - `uri` provided → returns single frame
            - `uri_list` provided → returns multiple frames
            - Otherwise → paginated list with optional filters

            **Form Type Classification (`form_type`):**

            Every KGFrame is automatically classified via `hasKGFormType`:

            | Value | URI | Meaning |
            |---|---|---|
            | `Assertion` | `haley-ai-kg#KGFormType_Assertion` | Standalone top-level frame — an independent fact |
            | `Aspect` | `haley-ai-kg#KGFormType_Aspect` | A frame enclosed by an entity |

            Pass the short label (`Assertion`, `Aspect`) or the full URI.

            **Sorting (`sort_by`):**

            Must be one of the allowed property URIs:
            - `http://vital.ai/ontology/vital-core#hasName`
            - `http://vital.ai/ontology/vital#hasObjectModificationDateTime`
            - `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
            - `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
            - `http://vital.ai/ontology/haley-ai-kg#hasKGFormType`
            - `http://vital.ai/ontology/haley-ai-kg#hasKGFrameType`
            - `http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription`
            """
            
            require_space_read(current_user, space_id)
            # A search needle under MIN_CONTAINS_LENGTH cannot use the text
            # index and scans the whole term table — twice, because the estimate
            # pays it too (issues/070). Guarded on the KGQuery path since
            # 2026-08-11 and nowhere else, so a UI search box still paid it.
            from ..model.kgentities_model import validate_search_text
            search_err = validate_search_text(search)
            if search_err:
                return QuadResponse(
                    status=OperationStatus.INVALID_REQUEST, message=search_err,
                    results=[], total_count=0, page_size=page_size, offset=offset,
                )
            
            # Handle single URI retrieval
            if uri:
                return await self._get_frame_by_uri(space_id, graph_id, uri, include_frame_graph, current_user)
            
            # Handle multiple URI retrieval
            if uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._get_frames_by_uris(space_id, graph_id, uris, include_frame_graph, current_user)
            
            # Validate sort_by against property registry
            if sort_by:
                from ..model.kgframes_model import _FRAME_SORT_PROPERTIES
                if sort_by not in _FRAME_SORT_PROPERTIES:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=400,
                        detail=f"sort_by '{sort_by}' is not a sortable property. Allowed: {', '.join(sorted(_FRAME_SORT_PROPERTIES))}"
                    )
            if sort_order not in ("asc", "desc"):
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

            # Resolve form_type short label to full URI
            resolved_form_type = None
            if form_type:
                from ..model.kgframes_model import resolve_form_type
                resolved_form_type = resolve_form_type(form_type)

            # Handle paginated list of all frames
            return await self._list_frames(
                space_id, graph_id, page_size, offset, search, current_user,
                sort_by=sort_by, sort_order=sort_order,
                form_type=resolved_form_type, frame_type_uri=frame_type_uri,
                status=status, exclude_status=exclude_status,
                created_after=created_after, created_before=created_before,
                modified_after=modified_after, modified_before=modified_before,
                parent_uri=parent_uri,
            )

        @self.router.post("/kgframes", response_model=None, tags=["KG Frames"])
        async def create_or_update_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            operation_mode: str = Query("create", description="Operation mode: create, update, or upsert"),
            parent_uri: Optional[str] = Query(None, description="Parent URI for hierarchical relationships"),
            entity_uri: Optional[str] = Query(None, description="Entity URI for frame association"),
            if_unmodified_since: Optional[str] = Query(
                None,
                description=(
                    "The frame's hasObjectModificationDateTime as the "
                    "caller read it. When supplied, the write is REFUSED with "
                    "status=conflict if the frame has changed since — so a "
                    "slower save cannot overwrite a newer one. Keyed on the "
                    "FRAME: these routes have no owning entity. Omit for the "
                    "previous last-writer-wins behaviour.")),
            body: QuadRequest = Body(..., description="GraphObjects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """
            Create or update KG frames from JSON Quads.
            """
            require_space_write(current_user, space_id)
            self.logger.info(f"🔍 ROUTE: POST /kgframes called with space_id={space_id}, graph_id={graph_id}, operation_mode={operation_mode}")
            
            try:
                quads = body.quads
                return await self._create_frames(
                    space_id, graph_id, quads, operation_mode,
                    entity_uri=entity_uri, parent_uri=parent_uri, current_user=current_user,
                    if_unmodified_since=if_unmodified_since,
                )
            except Exception as e:
                self.logger.error(f"❌ ROUTE: Exception in create_or_update_frames: {type(e).__name__}: {str(e)}")
                import traceback
                self.logger.error(f"❌ ROUTE: Traceback: {traceback.format_exc()}")
                raise
        
        @self.router.post("/kgframes/query", response_model=FrameQueryResponse, tags=["KG Frames"])
        async def query_frames(
            query_request: FrameQueryRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Query KG frames using enhanced criteria-based search with sorting support.
            """
            require_space_read(current_user, space_id)
            return await self._query_frames(space_id, graph_id, query_request, current_user)
        
        @self.router.delete("/kgframes", response_model=FrameDeleteResponse, tags=["KG Frames"])
        async def delete_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            uri: Optional[str] = Query(None, description="Single frame URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs to delete"),
            recursive: bool = Query(False, description="If true, recursively delete all descendant frames. If false (default), fail if any frame has children."),
            if_unmodified_since: Optional[str] = Query(
                None,
                description=(
                    "Delete only if the ROOT frame's hasObjectModificationDateTime "
                    "still equals this value; otherwise status=conflict and nothing "
                    "is deleted. One root frame per request.")),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete standalone frames by URI or URI list.
            
            Args:
                recursive: If true, cascade-delete all descendant frames. If false, fail if children exist.
            """
            require_space_write(current_user, space_id)
            if uri:
                return await self._delete_frames_by_uris(
                    space_id, graph_id, [uri], current_user, recursive=recursive,
                    if_unmodified_since=if_unmodified_since)
            elif uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._delete_frames_by_uris(
                    space_id, graph_id, uris, current_user, recursive=recursive,
                    if_unmodified_since=if_unmodified_since)
            else:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    status=OperationStatus.INVALID_REQUEST,
                    message="Either 'uri' or 'uri_list' parameter is required",
                    deleted_count=0,
                    deleted_uris=[]
                )
        
        # Frame-Slot Sub-Endpoint Operations (matching MockKGFramesEndpoint)
        
        @self.router.get("/kgframes/kgslots", response_model=QuadResponse, tags=["KG Frame Slots"])
        async def get_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            frame_uri: Optional[str] = Query(None, description="Frame URI to get slots for"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of items per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            entity_uri: Optional[str] = Query(None, description="Optional entity URI for filtering"),
            parent_uri: Optional[str] = Query(None, description="Optional parent URI for filtering"),
            search: Optional[str] = Query(None, description="Optional search term"),
            kGSlotType: Optional[str] = Query(None, description="Filter by slot type"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Get frames with their associated slots using pagination.

            NOTE: no sort_by here yet. This query returns a flat DISTINCT list
            of subjects UNIONing frames and their slots, so a single ORDER BY
            cannot express "frames by sequence, slots by sequence" — and the
            page boundary can already split a frame from its slots. Sorting
            arrives with the nested slot_pagination restructure (step 3 of
            planning/planning_sequence/frame_slot_sequence_sort_paging_plan.md).
            Ordering IS stable here (step 1 added ORDER BY ?subject).
            """
            require_space_read(current_user, space_id)
            # A search needle under MIN_CONTAINS_LENGTH cannot use the text
            # index and scans the whole term table — twice, because the estimate
            # pays it too (issues/070). Guarded on the KGQuery path since
            # 2026-08-11 and nowhere else, so a UI search box still paid it.
            from ..model.kgentities_model import validate_search_text
            search_err = validate_search_text(search)
            if search_err:
                return QuadResponse(
                    status=OperationStatus.INVALID_REQUEST, message=search_err,
                    results=[], total_count=0, page_size=page_size, offset=offset,
                )
            return await self._get_kgframes_with_slots(space_id, graph_id, frame_uri, page_size, offset, entity_uri, parent_uri, search, kGSlotType, current_user)
        
        # SLOT WRITES ON AN ENTITY'S FRAME (`issues/256`, decided 2026-10-04).
        # `/kgframes/kgslots` refuses an entity's frame, as `/kgframes` does for
        # frames; these are its entity-scoped counterparts, locked, guarded and
        # stamped on the ENTITY — the key every entity-frame write takes.
        @self.router.post("/kgentities/kgframes/kgslots", response_model=None, tags=["KG Frame Slots"])
        async def write_entity_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            entity_uri: str = Query(..., description="The entity that owns the frame"),
            frame_uri: str = Query(..., description="Frame URI whose slots are written"),
            operation_mode: str = Query("create", description="Operation mode: create, update, or upsert"),
            if_unmodified_since: Optional[str] = Query(
                None,
                description=(
                    "The ENTITY's hasObjectModificationDateTime as read; if it has "
                    "moved the write is refused with status=conflict.")),
            body: QuadRequest = Body(..., description="GraphObjects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Create, update or upsert slots of one of an entity's frames."""
            require_space_write(current_user, space_id)
            return await self._write_frame_slots(
                space_id, graph_id, frame_uri, body.quads, str(operation_mode).lower(),
                if_unmodified_since=if_unmodified_since, entity_uri=entity_uri)

        @self.router.delete("/kgentities/kgframes/kgslots", response_model=SlotDeleteResponse, tags=["KG Frame Slots"])
        async def delete_entity_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            entity_uri: str = Query(..., description="The entity that owns the frame"),
            frame_uri: str = Query(..., description="Frame URI to delete slots from"),
            slot_uris: str = Query(..., description="Comma-separated list of slot URIs to delete"),
            if_unmodified_since: Optional[str] = Query(
                None, description="The ENTITY's hasObjectModificationDateTime as read."),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Delete slots of one of an entity's frames, in one transaction under the entity lock."""
            require_space_write(current_user, space_id)
            slot_uri_list = [u.strip() for u in slot_uris.split(',') if u.strip()]
            return await self._delete_frame_slots(
                space_id, graph_id, frame_uri, slot_uri_list, current_user,
                if_unmodified_since=if_unmodified_since, entity_uri=entity_uri)

        # Registered on the KGFrames router but served under /kgentities/... so
        # it mirrors GET /kgentities/kgframes: page frames of an entity, then
        # page the slots of one of those frames. Both routers mount under
        # /api/graphs, so the path is independent of the file; the slot query
        # builder and converters all live here.
        @self.router.get("/kgentities/kgframes/kgslots", response_model=QuadResponse, tags=["KG Frame Slots"])
        async def get_entity_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            frame_uri: str = Query(..., description="Frame URI to get slots for"),
            entity_uri: Optional[str] = Query(None, description="Owning entity URI (scoping/consistency with /kgentities/kgframes)"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of slots per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            kGSlotType: Optional[str] = Query(None, description="Filter by slot type"),
            sort_by: Optional[str] = Query(None, description="Property URI to sort slots by (e.g. haley-ai-kg:hasSlotSequence). Must be an allowed sortable property."),
            sort_order: str = Query("asc", description="Sort order: 'asc' or 'desc'"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Slots of a single frame, sorted and paged.

            Sorting by hasSlotSequence orders slots numerically, with
            unsequenced slots last in both directions.
            """
            require_space_read(current_user, space_id)
            from ..model.kgframes_model import _SLOT_SORT_PROPERTIES, validate_sort_params
            err = validate_sort_params(sort_by, sort_order, _SLOT_SORT_PROPERTIES)
            if err:
                return QuadResponse(
                    status=OperationStatus.INVALID_REQUEST, message=err,
                    results=[], total_count=0, page_size=page_size, offset=offset,
                )
            return await self._list_frame_slots_paged(
                space_id, graph_id, frame_uri, page_size, offset,
                kGSlotType=kGSlotType, sort_by=sort_by, sort_order=sort_order)

        @self.router.post("/kgframes/kgslots", response_model=None, tags=["KG Frame Slots"])
        async def create_or_update_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            frame_uri: str = Query(..., description="Frame URI to create/update slots for"),
            entity_uri: Optional[str] = Query(None, description="Entity URI for slot context"),
            parent_uri: Optional[str] = Query(None, description="Parent URI for slot hierarchy"),
            operation_mode: str = Query("create", description="Operation mode: create, update, or upsert"),
            if_unmodified_since: Optional[str] = Query(
                None,
                description=(
                    "The frame's hasObjectModificationDateTime as the "
                    "caller read it. When supplied, the write is REFUSED with "
                    "status=conflict if the frame has changed since — so a "
                    "slower save cannot overwrite a newer one. Keyed on the "
                    "FRAME: these routes have no owning entity. Omit for the "
                    "previous last-writer-wins behaviour.")),
            body: QuadRequest = Body(..., description="GraphObjects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """
            Create or update slots for a specific frame from JSON Quads.
            Operation mode determines behavior: 'create' (fail if exists), 'update' (fail if not exists), 'upsert' (create or update).
            """
            require_space_write(current_user, space_id)
            return await self._write_frame_slots(
                space_id, graph_id, frame_uri, body.quads, str(operation_mode).lower(),
                if_unmodified_since=if_unmodified_since)
        
        @self.router.delete("/kgframes/kgslots", response_model=SlotDeleteResponse, tags=["KG Frame Slots"])
        async def delete_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            frame_uri: str = Query(..., description="Frame URI to delete slots from"),
            slot_uris: str = Query(..., description="Comma-separated list of slot URIs to delete"),
            if_unmodified_since: Optional[str] = Query(
                None,
                description=(
                    "Delete only if the frame's owner — the ENTITY for an entity's "
                    "frame, else the frame — still has this "
                    "hasObjectModificationDateTime; otherwise status=conflict.")),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete specific slots from a frame, with their Edge_hasKGSlot, in one locked transaction.
            """
            require_space_write(current_user, space_id)
            slot_uri_list = [uri.strip() for uri in slot_uris.split(',') if uri.strip()]
            return await self._delete_frame_slots(
                space_id, graph_id, frame_uri, slot_uri_list, current_user,
                if_unmodified_since=if_unmodified_since)
    
    # Implementation methods following MockKGFramesEndpoint patterns with VitalSigns integration

    async def _list_frames(self, space_id: str, graph_id: str, page_size: int, offset: int,
                           search: Optional[str], current_user: Dict,
                           sort_by: Optional[str] = None, sort_order: str = "asc",
                           form_type: Optional[str] = None,
                           frame_type_uri: Optional[str] = None,
                           status: Optional[str] = None,
                           exclude_status: Optional[str] = None,
                           created_after: Optional[str] = None,
                           created_before: Optional[str] = None,
                           modified_after: Optional[str] = None,
                           modified_before: Optional[str] = None,
                           parent_uri: Optional[str] = None) -> QuadResponse:
        """List KG frames with pagination using backend interface."""
        try:
            self.logger.info(f"Listing KGFrames in space {space_id}, graph {graph_id}")

            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return QuadResponse(status=OperationStatus.NOT_FOUND, results=[], total_count=0, page_size=page_size, offset=offset)

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=503, detail="Backend implementation not available")

            # --- Fast default path: page frames by subject_uuid (vitaltype=KGFrame),
            # like KGEntities. Avoids the ORDER BY ?frame full-URI resolution.
            # Engages only for the plain default listing (no filters/search/sort);
            # anything else falls back to the SPARQL path below. ---
            from ..kg_impl.kg_backend_utils import (
                fast_typed_subject_page, fast_typed_subject_count, VITALTYPE_URI)
            _KGFRAME_TYPE_URIS = ['http://vital.ai/ontology/haley-ai-kg#KGFrame']
            _no_filters = not any([
                search, form_type, frame_type_uri, status, exclude_status,
                created_after, created_before, modified_after, modified_before,
                sort_by,
                # `parent_uri` BELONGS IN THIS LIST. It is a filter, and this
                # path pages every frame in the graph by subject_uuid — it has
                # no notion of a parent. Leaving it out would return the whole
                # graph for a request that asked for one frame's children,
                # which is the failure the parameter was added to end.
                parent_uri,
            ])
            fast_uris = None
            if _no_filters:
                fast_uris = await fast_typed_subject_page(
                    backend, space_id, graph_id, VITALTYPE_URI,
                    _KGFRAME_TYPE_URIS, page_size, offset)
            if fast_uris is not None:
                fake_results = {"bindings": [{"frame": {"value": u}} for u in fast_uris]}
                frames = await self._sparql_results_to_frames(
                    backend, graph_id, fake_results, space_id)
                # Preserve the subject_uuid page order.
                _order = {u: i for i, u in enumerate(fast_uris)}
                frames = sorted(frames or [], key=lambda fr: _order.get(str(fr.URI), len(fast_uris)))
                fc = await fast_typed_subject_count(
                    backend, space_id, graph_id, VITALTYPE_URI, _KGFRAME_TYPE_URIS)
                total_count = fc if fc is not None else len(frames)
                quads = await asyncio.to_thread(graphobjects_to_quad_list, frames, graph_id)
                return QuadResponse(
                    status=OperationStatus.FOUND if frames else OperationStatus.EMPTY,
                    results=quads, total_count=total_count,
                    page_size=page_size, offset=offset)

            # --- Sorted / filtered ASSERTION listing, from
            # `{space}_frame_prop_sort`. Declines anything else, including the
            # All and Aspect tabs: that table holds Assertions, so serving
            # another tab from it would silently return the Assertion subset
            # (on `sp_lead_dup`, 1,000 of 5,500 frames). A search declines too,
            # for the reason the entity path does. ---
            # Served for EVERY form-type tab, and for a parent-scoped listing
            # regardless of tab. The parent -> child hop is general traversal
            # over the edge table -- `idx_{space}_edge_type_src` is
            # `(edge_type_uuid, source_node_uuid)`, so it is a seek -- and
            # `frame_prop_sort` now holds every frame with the resolved form
            # type in a column, so the two can actually meet. While that table
            # was Assertion-only it could only answer traversals whose results
            # happened to be Assertions.
            if not search and (
                    sort_by or frame_type_uri or status or parent_uri
                    or form_type
                    or created_after or created_before
                    or modified_after or modified_before):
                from ..db.sparql_sql.fast_frame_prop_sort import fast_frame_prop_page
                fp_uris = await fast_frame_prop_page(
                    space_impl, space_id, graph_id, page_size, offset,
                    form_type=form_type, frame_type_uri=frame_type_uri,
                    filters={"status": status, "created_after": created_after,
                             "created_before": created_before,
                             "modified_after": modified_after,
                             "modified_before": modified_before},
                    sort_by=sort_by, sort_order=sort_order,
                    parent_uri=parent_uri)
                if fp_uris is not None:
                    fake = {"bindings": [{"frame": {"value": u}} for u in fp_uris]}
                    frames = await self._sparql_results_to_frames(
                        backend, graph_id, fake, space_id)
                    # Preserve the page order the index produced; the object
                    # fetch above returns them in whatever order it likes, and
                    # using that directly would discard the sort.
                    _o = {u: i for i, u in enumerate(fp_uris)}
                    frames = sorted(frames or [],
                                    key=lambda fr: _o.get(str(fr.URI), len(fp_uris)))
                    quads = await asyncio.to_thread(
                        graphobjects_to_quad_list, frames, graph_id)
                    # The SAME count the SPARQL path uses, through the SAME
                    # cache. `len(frames)` would be the PAGE size, which the
                    # pager would read as the total — every list one page long.
                    _cq = self._build_count_frames_query(
                        backend, space_id, graph_id, search,
                        form_type=form_type, frame_type_uri=frame_type_uri,
                        status=status, exclude_status=exclude_status,
                        created_after=created_after, created_before=created_before,
                        modified_after=modified_after, modified_before=modified_before,
                    )
                    _ch = _count_cache.query_hash(_cq)
                    total_count = _count_cache.get(space_id, graph_id, _ch)
                    if total_count is None:
                        _cr = await backend.execute_sparql_query(space_id, _cq)
                        total_count = self._extract_count_from_results(_cr)
                        if _cr is not None and not (
                                isinstance(_cr, dict) and _cr.get("success") is False):
                            _count_cache.put(space_id, graph_id, _ch, total_count)
                    return QuadResponse(
                        status=OperationStatus.FOUND if frames else OperationStatus.EMPTY,
                        results=quads, total_count=total_count,
                        page_size=page_size, offset=offset)

            # Build SPARQL query for listing frames
            sparql_query = self._build_list_frames_query(
                backend, space_id, graph_id, search, page_size, offset,
                sort_by=sort_by, sort_order=sort_order,
                form_type=form_type, frame_type_uri=frame_type_uri,
                status=status, exclude_status=exclude_status,
                created_after=created_after, created_before=created_before,
                modified_after=modified_after, modified_before=modified_before,
                parent_uri=parent_uri,
            )
            
            # Execute query via backend interface
            results = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Convert results to VitalSigns frame objects
            frames = await self._sparql_results_to_frames(backend, graph_id, results, space_id)
            
            count_query = self._build_count_frames_query(
                backend, space_id, graph_id, search,
                form_type=form_type, frame_type_uri=frame_type_uri,
                status=status, exclude_status=exclude_status,
                created_after=created_after, created_before=created_before,
                modified_after=modified_after, modified_before=modified_before,
                parent_uri=parent_uri,
            )
            # This count is GRAPH-scoped and re-run on every page load and every
            # page change. On a 1.1M-frame graph the Assertion filter puts it at
            # ~2.9 s, which was the whole remaining cost of that tab. The entity-
            # scoped count is 0.1 ms, and timing THAT one is how this was audited
            # as "fine" and left uncached while kgentities/kgquery/graphs all use
            # the cache.
            #
            # Keyed by the query hash, so each filter combination is its own
            # entry — an Assertion count and an unfiltered count are different
            # questions about the same graph. Invalidation needs no work here:
            # the write paths already call invalidate_graph/invalidate_space.
            count_hash = _count_cache.query_hash(count_query)
            total_count = _count_cache.get(space_id, graph_id, count_hash)
            if total_count is None:
                count_results = await backend.execute_sparql_query(space_id, count_query)
                total_count = self._extract_count_from_results(count_results)
                # A failed count returns 0, and a cached 0 is indistinguishable
                # from a genuinely empty graph — issues/082 on a page whose job
                # is to report size. Only cache a count that came from a query
                # that actually ran.
                if count_results is not None and not (
                        isinstance(count_results, dict)
                        and count_results.get("success") is False):
                    _count_cache.put(space_id, graph_id, count_hash, total_count)
            quads = await asyncio.to_thread(graphobjects_to_quad_list, frames or [], graph_id)
            return QuadResponse(
                status=OperationStatus.FOUND if frames else OperationStatus.EMPTY,
                results=quads,
                total_count=total_count,
                page_size=page_size,
                offset=offset,
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing KGFrames: {e}")
            raise HTTPException(status_code=500, detail=f"Error listing KGFrames: {e}")
    
    @staticmethod
    def _dedupe_by_uri(objects: List[Any]) -> List[Any]:
        """First occurrence of each URI wins, input order preserved.

        Order is preserved because a stable payload is easier to read and diff,
        NOT because anything may depend on it. This response is a set of graph
        objects; a consumer wanting a particular one selects it by URI, which is
        the identity it has. A frame-details view that rendered whichever object
        happened to come first would be wrong the moment the query changed shape.

        An object with no readable URI is kept as-is rather than dropped —
        losing data to a defensive filter is worse than a duplicate.
        """
        seen = set()
        out = []
        for o in objects:
            uri = getattr(o, "URI", None)
            key = str(uri) if uri else None
            if key is None:
                out.append(o)
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(o)
        return out

    async def _get_frame_by_uri(self, space_id: str, graph_id: str, uri: str, include_frame_graph: bool, current_user: Dict) -> QuadResultsResponse:
        """Get single frame by URI with optional complete graph."""
        try:
            self.logger.info(f"🔍 Getting KGFrame {uri} from space {space_id}, graph {graph_id}, include_frame_graph={include_frame_graph}")
            
            # Get backend implementation via generic interface
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                self.logger.warning(f"❌ Space not found: {space_id}")
                return QuadResultsResponse(status=OperationStatus.NOT_FOUND, results=[], total_count=0)

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                self.logger.warning(f"❌ Backend not found for space: {space_id}")
                raise HTTPException(status_code=503, detail="Backend implementation not available")
            
            # Build SPARQL query for getting specific frame using grouping URI pattern
            self.logger.debug(f"🔧 Building SPARQL query for frame {uri}")
            sparql_query = self._build_get_frame_query(graph_id, uri, include_frame_graph)
            self.logger.debug(f"📝 SPARQL query: {sparql_query}")
            
            # Execute query via backend interface
            self.logger.debug(f"⚡ Executing SPARQL query")
            results = await backend.execute_sparql_query(space_id, sparql_query)
            self.logger.debug(f"📊 Query results: {len(results) if results else 0} rows")
            self.logger.debug(f"📊 Query results type: {type(results)}")
            self.logger.debug(f"📊 Query results content: {results}")
            
            # Convert results to VitalSigns frame objects
            self.logger.debug(f"🔄 Converting results to frames")
            frames = await self._sparql_results_to_frames(backend, graph_id, results, space_id)
            self.logger.debug(f"🎯 Converted frames: {len(frames) if frames else 0} frames")
            
            all_objects = list(frames) if frames else []
            if include_frame_graph and frames:
                frame_graph = await self._get_frame_graph(space_id=space_id, graph_id=graph_id, frame_uri=uri, current_user=current_user)
                if frame_graph and hasattr(frame_graph, 'graph_objects') and frame_graph.graph_objects:
                    all_objects.extend(frame_graph.graph_objects)
                elif frame_graph and hasattr(frame_graph, 'graph') and frame_graph.graph:
                    # Legacy path: frame_graph.graph contains GraphObjects directly
                    all_objects.extend(frame_graph.graph)
                # The frame is in BOTH lists — `frames` from the lookup above and
                # the frame graph, which includes the frame by design — so every
                # one of its quads would be emitted twice. This was invisible
                # while the frame graph returned None for a frame with no
                # attribute-linked slots; it appears the moment the graph
                # actually contains something.
                all_objects = self._dedupe_by_uri(all_objects)
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, all_objects, graph_id)
            return QuadResultsResponse(
                status=OperationStatus.FOUND if all_objects else OperationStatus.NOT_FOUND,
                results=quads,
                total_count=len(all_objects),
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"❌ Error getting KGFrame {uri}: {e}")
            import traceback
            self.logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Error getting KGFrame {uri}: {e}")
    
    async def _get_kgframes_with_slots(self, space_id: str, graph_id: str, frame_uri: Optional[str], page_size: int, offset: int, entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str], current_user: Dict):
        """Get frames with their associated slots using pagination."""
        try:
            self.logger.info(f"Getting KGFrames with slots in space {space_id}, graph {graph_id}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return QuadResponse(status=OperationStatus.NOT_FOUND, results=[], total_count=0, page_size=page_size, offset=offset)

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=503, detail="Backend implementation not available")

            sparql_query = self._build_frames_with_slots_query(backend, space_id, graph_id, frame_uri, entity_uri, parent_uri, search, kGSlotType, page_size, offset)
            results = await backend.execute_sparql_query(space_id, sparql_query)
            frames = await self._sparql_results_to_frames_with_slots(backend, graph_id, results, space_id)

            count_query = self._build_count_frames_with_slots_query(backend, space_id, graph_id, frame_uri, entity_uri, parent_uri, search, kGSlotType)
            count_results = await backend.execute_sparql_query(space_id, count_query)
            total_count = self._extract_count_from_results(count_results)

            quads = await asyncio.to_thread(graphobjects_to_quad_list, frames or [], graph_id)
            return QuadResponse(
                status=OperationStatus.FOUND if frames else OperationStatus.EMPTY,
                results=quads, total_count=total_count, page_size=page_size, offset=offset)

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGFrames with slots: {e}")
            raise HTTPException(status_code=500, detail=f"Error getting KGFrames with slots: {e}")
    
    def _build_frames_with_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str], entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str], page_size: int, offset: int) -> str:
        """Build SPARQL query for frames with slots.

        Returns DISTINCT ?subject where ?subject is either a frame or a slot
        reachable from it via Edge_hasKGSlot.

        ORDER BY ?subject is required, not cosmetic: without it the LIMIT/OFFSET
        below page over an unordered result set, so successive pages can repeat
        or skip subjects.

        ``search`` narrows by the FRAME (name / description / URI) in both UNION
        branches, so a match returns that frame together with its slots. It was
        previously accepted and threaded all the way here but never used, so the
        parameter silently did nothing.

        Note: the count companion counts matching *frames*, while this returns
        frames AND slots as subjects — a pre-existing mismatch in what
        ``total_count`` means for this endpoint, not introduced here.

        THE SLOT EDGE IS OPTIONAL IN BRANCH 1, and used to be required. A frame
        with no slots was therefore COUNTED by the companion query and never
        LISTED by this one: the endpoint answered `total_count: 3, objects: []`,
        which reads as "three results" above an empty table. A newly created
        frame has no slots yet, so it was invisible in the list it had just been
        added to.

        Branch 1 never projects `?slot` — it selects `?subject`, the frame — so
        the pattern was only ever reachability, and requiring it silently made
        "has at least one slot" part of the search. Branch 2 still requires the
        edge, because there `?subject` IS the slot and without the edge there is
        nothing to return.
        """
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id

        frame_filter = ""
        if frame_uri:
            frame_filter = f"FILTER(?frame = <{frame_uri}>)"

        slot_type_filter = ""
        if kGSlotType:
            slot_type_filter = f"?subject <{self.haley_prefix}hasKGSlotType> <{kGSlotType}> ."

        def _search_clause(frame_var: str) -> str:
            """Frame text search, bound to whichever variable holds the frame."""
            if not search:
                return ""
            # Escape so a quote in the term cannot terminate the SPARQL literal.
            term = search.replace("\\", "\\\\").replace('"', '\\"')
            v = frame_var.lstrip("?")
            return f"""
                    OPTIONAL {{ ?{v} <{self.vital_prefix}hasName> ?_name_{v} }}
                    OPTIONAL {{ ?{v} <{self.haley_prefix}hasKGraphDescription> ?_desc_{v} }}
                    FILTER(
                        CONTAINS(LCASE(STR(?_name_{v})), LCASE("{term}")) ||
                        CONTAINS(LCASE(STR(?_desc_{v})), LCASE("{term}")) ||
                        CONTAINS(LCASE(STR(?{v})), LCASE("{term}"))
                    )"""

        frame_search = _search_clause("?subject")   # branch 1: subject IS the frame
        slot_search = _search_clause("?frame")      # branch 2: frame is separate

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>

        SELECT DISTINCT ?subject WHERE {{
            {{
                GRAPH <{full_graph_uri}> {{
                    ?subject a haley:KGFrame .
                    {frame_filter.replace('?frame', '?subject') if frame_filter else ''}
                    OPTIONAL {{
                        ?slot_edge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                        ?slot_edge vital-core:hasEdgeSource ?subject .
                        ?slot_edge vital-core:hasEdgeDestination ?slot .
                    }}
                    {frame_search}
                }}
            }} UNION {{
                GRAPH <{full_graph_uri}> {{
                    ?frame a haley:KGFrame .
                    {frame_filter}
                    ?slot_edge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                    ?slot_edge vital-core:hasEdgeSource ?frame .
                    ?slot_edge vital-core:hasEdgeDestination ?subject .
                    {slot_type_filter}
                    {slot_search}
                }}
            }}
        }}
        ORDER BY ?subject
        LIMIT {page_size}
        OFFSET {offset}
        """
    
    def _build_count_frames_with_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str], entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str]) -> str:
        """Build SPARQL count query for frames with slots."""
        if frame_uri:
            # When filtering by a specific frame, count slots for that frame
            if hasattr(backend, '_get_space_graph_uri'):
                full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
            else:
                full_graph_uri = graph_id
            return f"""
            PREFIX haley: <{self.haley_prefix}>
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            SELECT (COUNT(DISTINCT ?slot) AS ?count) WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?slot_edge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                    ?slot_edge vital-core:hasEdgeSource <{frame_uri}> .
                    ?slot_edge vital-core:hasEdgeDestination ?slot .
                }}
            }}
            """
        return self._build_count_frames_query(backend, space_id, graph_id, search)
    
    async def _sparql_results_to_frames_with_slots(self, backend, graph_id: str, results, space_id: str):
        """Convert SPARQL results to VitalSigns objects (frames AND slots).

        Unlike ``_sparql_results_to_frames`` which filters for KGFrame only,
        this returns *all* GraphObjects produced from the subject URIs so that
        both KGFrame and KGSlot instances are included in the response.
        """
        try:
            if not results:
                return []

            bindings = results.get("bindings") or results.get("results", {}).get("bindings")
            if not bindings:
                return []

            subject_uris = []
            for binding in bindings:
                uri = (
                    binding.get("subject", {}).get("value")
                    or binding.get("frame", {}).get("value")
                )
                if uri:
                    subject_uris.append(uri)

            if not subject_uris:
                return []

            triples = await self._get_all_triples_for_subjects(backend, graph_id, subject_uris, space_id)
            if not triples:
                return []

            # Convert to VitalSigns objects — return ALL types, not just KGFrame
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            from rdflib import URIRef, Literal
            vs = VitalSigns()

            def triples_generator():
                for t in triples:
                    s = URIRef(t["subject"])
                    p = URIRef(t["predicate"])
                    o_val = t["object"]
                    if o_val.startswith(("http://", "https://", "urn:")):
                        o = URIRef(o_val)
                    else:
                        o = Literal(o_val)
                    yield (s, p, o)

            all_objects = await asyncio.to_thread(vs.from_triples_list, list(triples_generator()))
            return list(all_objects)

        except Exception as e:
            self.logger.error(f"Error converting SPARQL results to frames with slots: {e}", exc_info=True)
            return []
        
    async def _get_frames_by_uris(self, space_id: str, graph_id: str, frame_uris: List[str], include_frame_graph: bool = False, current_user: Dict = None) -> QuadResponse:
        """Get multiple frames by URI list, with their graphs when asked.

        `issues/240`. `include_frame_graph` was in the signature and NOWHERE in
        the body, so this returned frames without their graphs — HTTP 200,
        `status=FOUND`, nothing to say a parameter had been ignored. The
        single-URI sibling `_get_frame_by_uri` implemented it all along, which is
        what made this a drop rather than an unbuilt feature.

        BATCHED: one SELECT for every frame, via
        `frame_graph_processor.get_frame_graphs`, which binds `?frame` from a
        VALUES clause instead of interpolating a literal. A 25-URI request makes
        ONE graph query, matching the shape the entity side already uses
        (`_fetch_entity_graphs`). The first fix here was per-URI — correct but 25
        round trips — and `issues/210`/`issues/226` need this same query, so it
        is written once, in the processor, and they can call it too.

        The frame appears in BOTH its lookup result and its own graph, so
        `_dedupe_by_uri` is not optional — without it every quad of every frame
        emits twice. That trap is documented at the sibling (`:1119`) and was
        invisible there until the graph actually contained something.
        """
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Retrieve all frames concurrently
            async def _fetch_frame(frame_uri):
                try:
                    return await backend_adapter.get_object(space_id, graph_id, frame_uri)
                except Exception as e:
                    self.logger.warning(f"Failed to retrieve frame {frame_uri}: {e}")
                    return None
            
            # BOUNDED (`issues/231`): `frame_uris` is caller-supplied.
            results = await bounded_gather(
                [partial(_fetch_frame, uri) for uri in frame_uris])
            
            all_objects = []
            for result in results:
                if result and hasattr(result, 'objects') and result.objects:
                    all_objects.extend(result.objects)

            if include_frame_graph and frame_uris:
                # ONE query for every frame, not one per frame. See the
                # docstring: this is the `_fetch_entity_graphs` shape the entity
                # side already uses.
                try:
                    graphs = await self.frame_graph_processor.get_frame_graphs(
                        backend_adapter=backend_adapter,
                        space_id=space_id, graph_id=graph_id,
                        frame_uris=list(frame_uris))
                except Exception as e:
                    # ERROR, not warning: the caller ASKED for graphs, and
                    # dropping them silently is the defect this function had.
                    self.logger.error(
                        "Frame graphs failed for %d uri(s) in %s: %s",
                        len(frame_uris), space_id, e)
                    graphs = {}
                for objs in graphs.values():
                    if objs:
                        all_objects.extend(objs)
                # NOT optional — the frame is in both lists. See the docstring.
                all_objects = self._dedupe_by_uri(all_objects)
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, all_objects, graph_id)

            return QuadResponse(
                status=OperationStatus.FOUND if all_objects else OperationStatus.EMPTY,
                results=quads,
                total_count=len(all_objects),
                page_size=len(frame_uris),
                offset=0,
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Frame retrieval by URIs failed: {e}")
            raise HTTPException(status_code=500, detail=f"Frame retrieval by URIs failed: {e}")
    
    async def _query_frames(self, space_id: str, graph_id: str, query_request: FrameQueryRequest, current_user: Dict) -> FrameQueryResponse:
        """Query frames using enhanced criteria-based search with sorting support."""
        from ..model.kgframes_model import FrameQueryResponse
        
        try:
            self.logger.info(f"Querying frames in space {space_id}, graph {graph_id} with criteria: {query_request}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return FrameQueryResponse(
                    status=OperationStatus.NOT_FOUND,
                    frame_uris=[],
                    total_count=0,
                    page_size=query_request.page_size,
                    offset=query_request.offset,
                    has_more=False
                )

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=503, detail="Backend implementation not available")
            
            # Build SPARQL query based on criteria
            sparql_query = self._build_frame_query_sparql(graph_id, query_request)
            
            # Execute query via backend interface
            results = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Convert results to VitalSigns frame objects
            frames = await self._sparql_results_to_frames(backend, graph_id, results, space_id)
            
            # Apply sorting if specified in criteria
            sort_by = None
            sort_order = None
            if query_request.criteria.sort_criteria and len(query_request.criteria.sort_criteria) > 0:
                # Use first sort criterion
                first_sort = query_request.criteria.sort_criteria[0]
                sort_by = first_sort.field if hasattr(first_sort, 'field') else None
                sort_order = first_sort.order if hasattr(first_sort, 'order') else None
            
            sorted_frames = self._apply_frame_sorting(frames, sort_by, sort_order)
            
            # Apply pagination
            paginated_frames = self._apply_frame_pagination(sorted_frames, query_request.page_size, query_request.offset)
            
            # Extract frame URIs for response
            frame_uris = [str(frame.URI) for frame in paginated_frames]
            
            return FrameQueryResponse(
                status=OperationStatus.FOUND if frame_uris else OperationStatus.EMPTY,
                frame_uris=frame_uris,
                total_count=len(frames),
                page_size=query_request.page_size,
                offset=query_request.offset,
                has_more=len(frames) > (query_request.offset + query_request.page_size)
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error querying frames: {e}")
            raise HTTPException(status_code=500, detail=f"Error querying frames: {e}")
    
    async def _delete_frames_by_uris(self, space_id: str, graph_id: str, uris: List[str], current_user: Dict, recursive: bool = False,
                                     if_unmodified_since: Optional[str] = None) -> FrameDeleteResponse:
        """Delete standalone frames, and everything they own, in one locked transaction.

        `issues/256`. This was five separate SPARQL updates per frame, frame by
        frame, with no transaction and no lock: a failure part-way through a
        recursive delete left half a subtree. It also deleted ENTITY frames with
        none of the entity route's handling, so the frame stayed in the cached
        entity graph and the entity's version did not move. Those are now
        refused (use `/kgentities/kgframes`); see `delete_frame_subtrees`. An
        absent frame is NO_OP, where the single form said NOT_FOUND.

        Args:
            recursive: If True, recursively delete all descendant frames.
                       If False (default), fail if any frame has children.
            if_unmodified_since: Refuse (CONFLICT) if the one root frame moved.
        """
        from ..model.kgframes_model import FrameDeleteResponse
        
        try:
            self.logger.info(f"Deleting {len(uris)} frames from space {space_id}, graph {graph_id}, recursive={recursive}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return FrameDeleteResponse(
                    status=OperationStatus.NOT_FOUND,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )

            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=503, detail="Backend implementation not available")

            backend = create_backend_adapter(backend_impl)

            from ..kg_impl.frame_delete import delete_frames
            response, removed = await delete_frames(
                backend, space_id, graph_id, uris, recursive=recursive,
                if_unmodified_since=if_unmodified_since)
            if removed:
                self._schedule_auto_sync(backend_impl, space_id, graph_id, removed, "delete")
            return response

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting frames: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete frames: {e}")
    
    # Frame-slot sub-endpoint implementations
    
    async def _get_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, kGSlotType: Optional[str], current_user: Dict) -> List:
        """Get slots for a specific frame using Edge_hasKGSlot relationships. Returns List[GraphObject]."""
        try:
            self.logger.info(f"Getting slots for frame {frame_uri} in space {space_id}, graph {graph_id}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return []
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return []
            
            sparql_query = self._build_get_frame_slots_query(graph_id, frame_uri, kGSlotType)
            results = await backend.execute_sparql_query(space_id, sparql_query)
            slots = await self._sparql_results_to_slots(backend, graph_id, results, space_id)
            
            return slots or []
            
        except Exception as e:
            self.logger.error(f"Error getting frame slots: {e}")
            return []
    
    async def _write_frame_slots(self, space_id: str, graph_id: str, frame_uri: str,
                                 quads: List[Quad], mode: str,
                                 if_unmodified_since: Optional[str] = None,
                                 entity_uri: Optional[str] = None):
        """Write slots of one frame: create, update or upsert (`issues/256`).

        TWO ROUTES, one contract (decided 2026-10-04). `/kgframes/kgslots`
        (`entity_uri` None) writes a STANDALONE frame's slots, locked, guarded
        and stamped on the frame, and refuses an entity's frame.
        `/kgentities/kgframes/kgslots` writes an entity's frame's slots, locked,
        guarded and stamped on the ENTITY, and the frame must be the entity's.

        Decided under the lock (`slot_write_precheck`):
        - the frame side above;
        - a slot of another frame is refused — `update` rewrote it and moved it;
        - `create` refuses an existing slot, `update` a missing one, `upsert`
          takes either;
        - an `Edge_hasKGSlot` is minted only for a NEW slot. An existing slot
          has its edge, possibly written by the entity route under another URI,
          and minting a second one duplicated it.
        An unknown mode is refused.
        """
        from ..model.kgframes_model import SlotCreateResponse, SlotUpdateResponse
        from ..kg_impl.kg_backend_utils import slot_write_precheck

        def _answer(status, message, uris=()):
            uris = list(uris)
            if mode == "update":
                return SlotUpdateResponse(status=status, message=message,
                                          updated_count=len(uris), updated_uris=uris)
            return SlotCreateResponse(status=status, message=message,
                                      created_count=len(uris), created_uris=uris)

        if mode not in ("create", "update", "upsert"):
            return _answer(OperationStatus.INVALID_REQUEST,
                           f"Unknown operation_mode {mode!r}: expected create, update or upsert")
        vitalsigns_objects = quad_list_to_graphobjects(quads)
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return _answer(OperationStatus.NOT_FOUND, f"Space {space_id} not found")
            backend_impl = space_record.space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=503, detail="Backend implementation not available")
            backend = create_backend_adapter(backend_impl)

            slots = [o for o in vitalsigns_objects if isinstance(o, KGSlot)]
            if not slots:
                return _answer(OperationStatus.INVALID_REQUEST,
                               "No valid KGSlot objects found in request")
            slot_uris = [str(sl.URI) for sl in slots]

            key = entity_uri or frame_uri
            objects = list(vitalsigns_objects)
            if mode != "update":
                existing = await backend.existing_subjects(space_id, graph_id, slot_uris)
                objects = self._create_frame_slot_edges(
                    frame_uri, [sl for sl in slots if str(sl.URI) not in existing], objects)
            # The URL's frame owns every slot (`issues/257`).
            assign_frame_groupings(objects, owning_frame_uri=frame_uri)
            # And the ENTITY owns them on the entity route: `hasKGGraphURI` is
            # what makes an object part of the entity graph — what reads return
            # and what the entity's graph delete removes. Decided here, not by
            # the client, as the groupings are. The slot route never set it
            # (only a handler nothing called did), so a slot added this way was
            # missing from the entity graph and would outlive the entity. On the
            # standalone route a client-sent value is dropped: a standalone
            # frame's slots belong to no entity.
            for o in objects:
                if hasattr(o, 'kGGraphURI'):
                    o.kGGraphURI = entity_uri if entity_uri else None

            triples = await asyncio.to_thread(GraphObject.to_triples_list, objects)
            insert_quads = [(str(a), str(b), c, graph_id) for a, b, c in triples]
            subject_uris = list(dict.fromkeys(str(o.URI) for o in objects
                                              if getattr(o, 'URI', None)))
            if not await backend.update_subjects_graph(
                    space_id, graph_id, subject_uris, insert_quads,
                    lock_uris=[key], if_unmodified_since=if_unmodified_since,
                    guard_subject=key, stamp_subjects=[key],
                    precheck=slot_write_precheck(space_id, graph_id, frame_uri,
                                                 slot_uris, mode, entity_uri)):
                raise SubjectWriteFailed(f"slot {mode}", len(subject_uris))

            if entity_uri:
                await self._invalidate_entity_graph(space_id, graph_id, entity_uri)
            self._schedule_auto_sync(backend_impl, space_id, graph_id, subject_uris)
            status = {"create": OperationStatus.CREATED, "update": OperationStatus.UPDATED,
                      "upsert": OperationStatus.UPSERTED}[mode]
            verb = {"create": "created", "update": "updated", "upsert": "upserted"}[mode]
            return _answer(status, f"Successfully {verb} {len(slot_uris)} slot(s) of frame {frame_uri}",
                           slot_uris)

        except HTTPException:
            raise
        except StaleWrite as e:
            # The owner moved (`issues/253`): re-read, re-merge, retry.
            self.logger.warning("Slot %s refused as stale: %s", mode, e)
            return _answer(OperationStatus.CONFLICT, message=str(e))
        except RequestRefused as e:
            # The caller's to fix, with the refusal's own status: ALREADY_EXISTS,
            # NOT_FOUND, or INVALID_REQUEST (`issues/256`).
            return _answer(OperationStatus(e.status), message=str(e))
        except (SubjectWriteFailed, GuardUnsatisfiable) as e:
            # A describable failure: STORE_FAILED in a 200 (`issues/253`).
            self.logger.error("Slot %s did not happen: %s", mode, e)
            return _answer(OperationStatus.STORE_FAILED, message=str(e))
        except Exception as e:
            self.logger.error(f"Error writing frame slots: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to write frame slots: {e}")

    async def _invalidate_entity_graph(self, space_id: str, graph_id: str,
                                       entity_uri: str) -> None:
        """Drop the cached entity graph after a slot write on one of its frames.

        The same invalidation `KGEntitiesEndpoint._invalidate_entity_cache`
        does — local cache, count cache, and the cross-instance NOTIFY — which
        this router needs now that it writes entity frames' slots. Never raises.
        """
        from ..cache.entity_graph_cache import _entity_graph_cache
        _g = graph_id or "default"
        try:
            _entity_graph_cache.invalidate(space_id, _g, entity_uri)
            _count_cache.invalidate_graph(space_id, _g)
        except Exception as e:
            self.logger.warning("entity cache invalidation failed: %s", e)
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            backend = space_record.space_impl.get_db_space_impl() if space_record else None
            sm = getattr(backend, 'get_signal_manager', lambda: None)() if backend else None
            if sm:
                await sm.notify_entity_graph_changed(space_id, _g, entity_uri, "updated")
        except Exception as e:
            self.logger.warning("entity cache NOTIFY failed: %s", e)

    async def _delete_frame_slots(self, space_id: str, graph_id: str, frame_uri: str,
                                  slot_uris: List[str], current_user: Dict,
                                  if_unmodified_since: Optional[str] = None,
                                  entity_uri: Optional[str] = None) -> SlotDeleteResponse:
        """Delete slots of one frame in one locked transaction (`issues/256`).

        See `delete_frame_slots`: the owner's lock, guard and stamp; a slot of
        another frame refuses the request; a slot already gone is NO_OP. This
        was two SPARQL updates per slot with no lock, NOT_FOUND for an absent
        slot, and a slot whose delete failed silently dropped from the count.
        """
        from ..model.kgframes_model import SlotDeleteResponse

        def _no(status, message):
            return SlotDeleteResponse(status=status, message=message,
                                      deleted_count=0, deleted_uris=[])
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return _no(OperationStatus.NOT_FOUND, f"Space {space_id} not found")
            backend_impl = space_record.space_impl.get_db_space_impl()
            if not backend_impl:
                raise HTTPException(status_code=503, detail="Backend implementation not available")
            backend = create_backend_adapter(backend_impl)

            result = await backend.delete_frame_slots(
                space_id, graph_id, frame_uri, slot_uris, entity_uri=entity_uri,
                if_unmodified_since=if_unmodified_since)
            deleted, absent = result["deleted"], result["absent"]
            if deleted:
                if entity_uri:
                    await self._invalidate_entity_graph(space_id, graph_id, entity_uri)
                self._schedule_auto_sync(backend_impl, space_id, graph_id, deleted, "delete")
                return SlotDeleteResponse(
                    status=OperationStatus.DELETED,
                    message=(f"Successfully deleted {len(deleted)} slot(s) from frame {frame_uri}"
                             + (f"; {len(absent)} were already absent" if absent else "")),
                    deleted_count=len(deleted), deleted_uris=deleted, absent_uris=absent)
            return SlotDeleteResponse(
                status=OperationStatus.NO_OP,
                message=f"None of the {len(slot_uris)} slot(s) exist - no deletion performed",
                deleted_count=0, deleted_uris=[], absent_uris=absent)

        except HTTPException:
            raise
        except StaleWrite as e:
            return _no(OperationStatus.CONFLICT, message=str(e))
        except RequestRefused as e:
            return _no(OperationStatus(e.status), message=str(e))
        except GuardUnsatisfiable as e:
            return _no(OperationStatus.STORE_FAILED, message=str(e))
        except Exception as e:
            self.logger.error(f"Error deleting frame slots: {e}")
            return _no(OperationStatus.STORE_FAILED,
                       f"Slot delete failed, nothing was deleted: {e}")
    
    # Helper methods for SPARQL query building and VitalSigns conversion

    def _build_frame_filter_clauses(self, *,
                                    search: Optional[str] = None,
                                    form_type: Optional[str] = None,
                                    frame_type_uri: Optional[str] = None,
                                    status: Optional[str] = None,
                                    exclude_status: Optional[str] = None,
                                    created_after: Optional[str] = None,
                                    created_before: Optional[str] = None,
                                    modified_after: Optional[str] = None,
                                    modified_before: Optional[str] = None,
                                    parent_uri: Optional[str] = None) -> str:
        """Build SPARQL filter clause fragments for frame list queries."""
        parts = []

        # CHILD FRAMES of a given parent, by the same pattern
        # `kg_validation_utils` uses to verify the link exists: the edge is a
        # first-class node, not a property on the frame.
        if parent_uri:
            parts.append(
                f'?_pedge a <{self.haley_prefix}Edge_hasKGFrame> .\n'
                f'                ?_pedge <{self.vital_prefix}hasEdgeSource> <{parent_uri}> .\n'
                f'                ?_pedge <{self.vital_prefix}hasEdgeDestination> ?frame .')

        # Text search on name / description / URI
        if search:
            parts.append(f"""
                OPTIONAL {{ ?frame <{self.vital_prefix}hasName> ?name }}
                OPTIONAL {{ ?frame <{self.haley_prefix}hasKGraphDescription> ?description }}
                FILTER(
                    CONTAINS(LCASE(STR(?name)), LCASE("{search}")) ||
                    CONTAINS(LCASE(STR(?description)), LCASE("{search}")) ||
                    CONTAINS(LCASE(STR(?frame)), LCASE("{search}"))
                )""")

        # Form type (Assertion / Aspect). When hasKGFormType is unset, the frame
        # defaults by whether it has a hasFrameGraphURI: no URI → Assertion,
        # has URI → Aspect. So each filter matches explicit values plus the
        # corresponding unset default.
        if form_type:
            _assertion_uri = f'{self.haley_prefix}KGFormType_Assertion'
            _aspect_uri = f'{self.haley_prefix}KGFormType_Aspect'
            if form_type == _assertion_uri:
                # Assertion = explicit, OR (no form type AND no frame graph URI).
                # The default branch re-anchors ?frame with a positive pattern
                # (?frame a KGFrame) so the FILTER NOT EXISTS clauses bind
                # per-frame — a filter-only UNION branch mistranslates to SQL as
                # a global anti-join when other frames have hasFrameGraphURI.
                parts.append(
                    f'{{ {{ ?frame <{self.haley_prefix}hasKGFormType> <{form_type}> . }}\n'
                    f'                UNION\n'
                    f'                {{ ?frame a <{self.haley_prefix}KGFrame> .\n'
                    f'                  FILTER NOT EXISTS {{ ?frame <{self.haley_prefix}hasKGFormType> ?_ft . }}\n'
                    f'                  FILTER NOT EXISTS {{ ?frame <{self.haley_prefix}hasFrameGraphURI> ?_fg . }} }} }}'
                )
            elif form_type == _aspect_uri:
                # Aspect = explicit, OR (no form type AND has a frame graph URI)
                parts.append(
                    f'{{ {{ ?frame <{self.haley_prefix}hasKGFormType> <{form_type}> . }}\n'
                    f'                UNION\n'
                    f'                {{ FILTER NOT EXISTS {{ ?frame <{self.haley_prefix}hasKGFormType> ?_ft . }}\n'
                    f'                  ?frame <{self.haley_prefix}hasFrameGraphURI> ?_fg . }} }}'
                )
            else:
                parts.append(f'?frame <{self.haley_prefix}hasKGFormType> <{form_type}> .')

        # Frame type URI
        if frame_type_uri:
            parts.append(f'?frame <{self.haley_prefix}hasKGFrameType> <{frame_type_uri}> .')

        # Status filter
        if status:
            parts.append(f'?frame <http://vital.ai/ontology/vital-aimp#hasObjectStatusType> <{status}> .')

        # Exclude status
        if exclude_status:
            parts.append(f"""
                OPTIONAL {{ ?frame <http://vital.ai/ontology/vital-aimp#hasObjectStatusType> ?_excl_status . }}
                FILTER(!BOUND(?_excl_status) || ?_excl_status != <{exclude_status}>)""")

        # Date range filters
        creation_prop = "http://vital.ai/ontology/vital-aimp#hasObjectCreationTime"
        modification_prop = "http://vital.ai/ontology/vital#hasObjectModificationDateTime"

        if created_after or created_before:
            parts.append(f'?frame <{creation_prop}> ?_created .')
            if created_after:
                parts.append(f'FILTER(?_created >= "{created_after}"^^xsd:dateTime)')
            if created_before:
                parts.append(f'FILTER(?_created <= "{created_before}"^^xsd:dateTime)')

        if modified_after or modified_before:
            parts.append(f'?frame <{modification_prop}> ?_modified .')
            if modified_after:
                parts.append(f'FILTER(?_modified >= "{modified_after}"^^xsd:dateTime)')
            if modified_before:
                parts.append(f'FILTER(?_modified <= "{modified_before}"^^xsd:dateTime)')

        return "\n                ".join(parts)

    def _build_list_frames_query(self, backend, space_id: str, graph_id: str,
                                 search: Optional[str], page_size: int, offset: int,
                                 sort_by: Optional[str] = None, sort_order: str = "asc",
                                 form_type: Optional[str] = None,
                                 frame_type_uri: Optional[str] = None,
                                 status: Optional[str] = None,
                                 exclude_status: Optional[str] = None,
                                 created_after: Optional[str] = None,
                                 created_before: Optional[str] = None,
                                 modified_after: Optional[str] = None,
                                 modified_before: Optional[str] = None,
                                 parent_uri: Optional[str] = None) -> str:
        """Build SPARQL query for listing frame subjects with filtering and sorting."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id

        filters = self._build_frame_filter_clauses(
            search=search, form_type=form_type, frame_type_uri=frame_type_uri,
            status=status, exclude_status=exclude_status,
            created_after=created_after, created_before=created_before,
            modified_after=modified_after, modified_before=modified_before,
            parent_uri=parent_uri,
        )

        # Build sort clause.  Sequence properties get the numeric /
        # unsequenced-last construct; everything else sorts lexically.
        # The DISTINCT lives in an inner subquery: an ORDER BY alongside a
        # DISTINCT is silently dropped by the backend.
        sort_optional, sort_projection, order_clause = KGSparqlUtils.build_sort_clauses(
            "?frame", sort_by, sort_order,
        )

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT ?frame WHERE {{
            {{ SELECT DISTINCT ?frame {sort_projection} WHERE {{
                GRAPH <{full_graph_uri}> {{
                    ?frame a haley:KGFrame .
                    {filters}
                    {sort_optional}
                }}
            }} }}
        }}
        {order_clause}
        LIMIT {page_size}
        OFFSET {offset}
        """
    
    def _build_count_frames_query(self, backend, space_id: str, graph_id: str,
                                  search: Optional[str],
                                  form_type: Optional[str] = None,
                                  frame_type_uri: Optional[str] = None,
                                  status: Optional[str] = None,
                                  exclude_status: Optional[str] = None,
                                  created_after: Optional[str] = None,
                                  created_before: Optional[str] = None,
                                  modified_after: Optional[str] = None,
                                  modified_before: Optional[str] = None,
                                 parent_uri: Optional[str] = None) -> str:
        """Build SPARQL count query for frames with filtering."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id

        filters = self._build_frame_filter_clauses(
            search=search, form_type=form_type, frame_type_uri=frame_type_uri,
            status=status, exclude_status=exclude_status,
            created_after=created_after, created_before=created_before,
            modified_after=modified_after, modified_before=modified_before,
            parent_uri=parent_uri,
        )

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        
        SELECT (COUNT(DISTINCT ?frame) as ?count) WHERE {{
            GRAPH <{full_graph_uri}> {{
                ?frame a haley:KGFrame .
                {filters}
            }}
        }}
        """
    
    # Slot subclasses that carry a literal value. These reach their frame through
    # hasFrameGraphURI. KGEntitySlot is deliberately NOT here — it carries an
    # ENTITY and reaches its frame through an Edge_hasKGSlot edge instead, which
    # is why it needs its own branch below.
    _ATTRIBUTE_SLOT_CLASSES = (
        "KGTextSlot", "KGIntegerSlot", "KGDateTimeSlot",
        "KGBooleanSlot", "KGDoubleSlot",
    )

    def _build_slot_match_pattern(self, frame_uri: Optional[str]) -> str:
        """SPARQL matching a frame's slots under EITHER linkage.

        The model has two frame families and a space may contain both, so this
        cannot choose one (79 spaces: 21 attribute-only, 8 connection-only, 6
        with both):

          attribute  entity -> frame -> slot -> LITERAL, slot joined to its
                     frame by `hasFrameGraphURI`;
          connection entity -> frame -> slot -> ENTITY, the frame joined to its
                     slots by an `Edge_hasKGSlot` edge (frame is the edge
                     SOURCE, slot the DESTINATION) and the slot's role carried
                     in `hasKGSlotType`.

        Only the attribute half was implemented, so the frames UI reported "No
        slots found" for connection frames that plainly had them — and did so
        silently, because a pattern anchored on an absent predicate matches
        nothing rather than failing. It missed twice over: `hasFrameGraphURI`
        has zero rows in such a space, and KGEntitySlot was absent from the
        subclass list, so repairing the linkage alone would still have returned
        nothing.

        DISTINCT at the call site is what keeps a slot appearing once when a
        space uses both linkages.
        """
        haley = self.haley_prefix
        vital = self.vital_prefix
        subclasses = " UNION ".join(
            f"{{ ?slot a <{haley}{c}> . }}" for c in self._ATTRIBUTE_SLOT_CLASSES
        )
        attribute_scope = (
            f"\n                  ?slot <{haley}hasFrameGraphURI> <{frame_uri}> ."
            if frame_uri else ""
        )
        attribute = (
            f"{{ ?slot <{haley}hasFrameGraphURI> ?_frameGraphURI .\n"
            f"                  {subclasses}{attribute_scope} }}"
        )

        if frame_uri:
            # Anchored on the frame, so the edge is what scopes it.
            connection = (
                f"{{ ?slot a <{haley}KGEntitySlot> .\n"
                f"                  ?_slotEdge <{vital}hasEdgeDestination> ?slot .\n"
                f"                  ?_slotEdge <{vital}hasEdgeSource> <{frame_uri}> . }}"
            )
        else:
            # Listing every slot in the graph: the type alone identifies them,
            # and joining the edge would only add cost.
            connection = f"{{ ?slot a <{haley}KGEntitySlot> . }}"

        return f"{attribute}\n                UNION\n                {connection}"

    def _build_list_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str], page_size: int, offset: int,
                                sort_by: Optional[str] = None, sort_order: str = "asc") -> str:
        """Build SPARQL for listing a frame's slots, under either linkage."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>

        SELECT DISTINCT ?slot WHERE {{
            GRAPH <{full_graph_uri}> {{
                {self._build_slot_match_pattern(frame_uri)}
            }}
        }}
        ORDER BY ?slot
        LIMIT {page_size}
        OFFSET {offset}
        """

    def _build_count_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str]) -> str:
        """Count a frame's slots. Must use the SAME pattern as the list query —
        a count from one linkage beside a list from both reads as data loss."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>

        SELECT (COUNT(DISTINCT ?slot) as ?count) WHERE {{
            GRAPH <{full_graph_uri}> {{
                {self._build_slot_match_pattern(frame_uri)}
            }}
        }}
        """

    def _build_get_frame_query(self, graph_id: str, frame_uri: str, include_frame_graph: bool = False) -> str:
        """Build SPARQL query for getting frame subjects by subject URI."""
        if include_frame_graph:
            # Get all subjects that belong to this frame's graph (objects with frameGraphURI pointing to this frame)
            return f"""
            PREFIX haley: <{self.haley_prefix}>
            
            SELECT DISTINCT ?subject WHERE {{
                GRAPH <{graph_id}> {{
                    {{
                        # The frame itself
                        BIND(<{frame_uri}> as ?subject)
                        ?subject a haley:KGFrame .
                    }} UNION {{
                        # All objects that belong to this frame's graph
                        ?subject haley:hasFrameGraphURI <{frame_uri}> .
                    }}
                }}
            }}
            ORDER BY ?subject
            """
        else:
            # Get just the specific frame object
            return f"""
            PREFIX haley: <{self.haley_prefix}>
            
            SELECT DISTINCT ?subject WHERE {{
                GRAPH <{graph_id}> {{
                    BIND(<{frame_uri}> as ?subject)
                    ?subject a haley:KGFrame .
                }}
            }}
            """
    
    @staticmethod
    def _reorder_to_match(objects: List[Any], ordered_uris: List[str]) -> List[Any]:
        """Return ``objects`` in the order given by ``ordered_uris``.

        The paging/sorting query decides the order, but objects are rebuilt
        from a second triple fetch that groups by its own order. Without this,
        ORDER BY is honored when selecting WHICH subjects appear on a page but
        lost for the order they appear IN — so sorting looks broken end to end
        even though the SPARQL is correct.

        Objects whose URI is not in the list (shouldn't happen) are appended in
        their existing order rather than dropped.

        Thin delegate to KGSparqlUtils.reorder_to_match, which is the shared
        implementation now that frames, entity-frames, slots and relations all
        need it.
        """
        return KGSparqlUtils.reorder_to_match(objects, ordered_uris)

    async def _sparql_results_to_frames(self, backend, graph_id: str, sparql_result: Dict[str, Any], space_id: str) -> List[KGFrame]:
        """Convert SPARQL results to VitalSigns frame objects using proper triple conversion."""
        try:
            frames = []
            if not sparql_result:
                self.logger.debug("📋 No SPARQL results to convert")
                return frames
            
            self.logger.debug(f"📋 SPARQL result structure: {sparql_result}")
            
            # Handle both direct bindings and results.bindings structure
            bindings = sparql_result.get("bindings") or sparql_result.get("results", {}).get("bindings")
            if not bindings:
                self.logger.debug(f"📋 No bindings found in SPARQL result")
                return frames
            
            self.logger.debug(f"📋 Found {len(bindings)} bindings")
            
            # Extract subject URIs from initial query results (could be frames or related objects)
            subject_uris = []
            for binding in bindings:
                self.logger.debug(f"📋 Processing binding: {binding}")
                # Try both 'frame' and 'subject' keys for compatibility
                subject_uri = binding.get("frame", {}).get("value") or binding.get("subject", {}).get("value")
                if subject_uri:
                    subject_uris.append(subject_uri)
                    self.logger.debug(f"📋 Extracted subject URI: {subject_uri}")
            
            if not subject_uris:
                self.logger.debug("📋 No subject URIs extracted from bindings")
                return frames
            
            self.logger.debug(f"📋 Extracted {len(subject_uris)} subject URIs: {subject_uris}")
            
            # Get all triples for these subjects
            triples = await self._get_all_triples_for_subjects(backend, graph_id, subject_uris, space_id)
            self.logger.debug(f"📊 Retrieved {len(triples) if triples else 0} triples for subjects")
            
            # Convert triples directly to VitalSigns objects
            frames = await self._convert_triples_to_vitalsigns_frames(triples)
            self.logger.debug(f"🔄 Converted to {len(frames) if frames else 0} VitalSigns frames")

            # Restore the order the paging query established.  Rebuilding objects
            # from triples groups them by whatever order the triple fetch
            # returned, which silently discards the ORDER BY — so a sorted page
            # would come back in arbitrary order even though the right subjects
            # were selected.
            frames = self._reorder_to_match(frames, subject_uris)

            return frames
            
        except Exception as e:
            self.logger.error(f"Error converting SPARQL results to frames: {e}", exc_info=True)
            return []
    
    
    
    def _extract_count_from_results(self, count_results) -> int:
        """Extract count from SPARQL count query results."""
        try:
            if isinstance(count_results, dict):
                bindings = count_results.get("results", {}).get("bindings", [])
                for binding in bindings:
                    count_value = binding.get("count", {}).get("value", "0")
                    return int(count_value)
            return 0
        except Exception as e:
            self.logger.warning(f"Error extracting count from results: {e}")
            return 0
    
    # Helper methods for VitalSigns integration and frame operations
    

    
    
    def _set_frame_grouping_uris(self, frames: List[KGFrame], graph_id: str):
        """Set frameGraphURI on frame objects for frame-level grouping.
        
        Standalone frames use only frameGraphURI (= frame's own URI).
        No kGGraphURI is set — that is an entity-scoped concept.
        """
        for frame in frames:
            if isinstance(frame, KGFrame):
                if hasattr(frame, 'URI') and frame.URI:
                    frame.frameGraphURI = str(frame.URI)
    
    def _validate_frame_structure(self, objects: List[GraphObject]) -> Dict[str, Any]:
        """Validate frame structure following MockKGFramesEndpoint patterns."""
        try:
            frames = [obj for obj in objects if isinstance(obj, KGFrame)]
            
            if not frames:
                return {"valid": False, "error": "No KGFrame objects found"}
            
            # Validate each frame has required properties
            for frame in frames:
                if not hasattr(frame, 'URI') or not frame.URI:
                    return {"valid": False, "error": "Frame missing URI"}
                
                # Cast URI property to validate it has actual value
                try:
                    frame_uri_str = str(frame.URI)
                    if not frame_uri_str or frame_uri_str.strip() == "":
                        return {"valid": False, "error": f"Frame has empty URI"}
                except Exception as e:
                    return {"valid": False, "error": f"Frame URI casting failed: {str(e)}"}
            
            return {"valid": True, "error": None}
            
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    async def _handle_create_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str],
                                  if_unmodified_since: Optional[str] = None, precheck=None):
        """Handle CREATE mode: create frames using standalone frame processor."""
        try:
            # Initialize standalone frame processor if needed
            if not self.frame_processor:
                from ..kg_impl.kgframe_create_impl import KGFrameCreateProcessor
                self.frame_processor = KGFrameCreateProcessor()
            
            result = await self.frame_processor.create_frame(
                backend_adapter=backend,
                space_id=space_id,
                graph_id=graph_id,
                frame_objects=objects,
                operation_mode="CREATE",
                if_unmodified_since=if_unmodified_since,
                precheck=precheck,
            )
            
            if not result.success:
                return FrameCreateResponse(
                    status=OperationStatus.STORE_FAILED,
                    message=result.message,
                    created_count=0,
                    created_uris=[],
                )

            created_uris = [str(uri) for uri in result.created_uris]

            # Count slots created along with frames
            slots_count = 0
            if hasattr(result, 'slots_created'):
                slots_count = result.slots_created
            else:
                # Count KGSlot objects in the original objects
                from ai_haley_kg_domain.model.KGSlot import KGSlot
                slots_count = len([obj for obj in objects if isinstance(obj, KGSlot)])

            return FrameCreateResponse(
                status=OperationStatus.CREATED,
                message=f"Successfully created {len(created_uris)} frames in graph '{graph_id}' in space '{space_id}'",
                created_count=len(created_uris),
                created_uris=created_uris,
                slots_created=slots_count,
            )

        except HTTPException:
            raise
        except (StaleWrite, AmbiguousPrecondition,
                GuardUnsatisfiable, RequestRefused):
            # Past the mode handler, to be answered by `_create_frames`
            # (`issues/253`). This handler turns anything else into a 500, and
            # it turned the refusal into one too — a caller cannot tell a
            # refused write from a broken server, and the client's retry policy
            # treats the two oppositely.
            raise
        except Exception as e:
            self.logger.error(f"Error in CREATE mode: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create frames: {e}")
    
    async def _handle_update_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str],
                                  if_unmodified_since: Optional[str] = None, precheck=None):
        """Handle UPDATE mode: verify frames exist, then update using standalone processor.
        
        Args:
            parent_uri: Used for frame-to-frame validation (Edge_hasKGFrame).
        """
        try:
            # Validate parent-child relationship only if parent_uri is itself a KGFrame
            if parent_uri:
                parent_is_frame = await self._frame_exists_in_backend(backend, space_id, graph_id, parent_uri)
                if parent_is_frame:
                    from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
                    sparql_processor = KGSparqlQueryProcessor(backend, self.logger)
                    frame_uris = [str(f.URI) for f in frames if hasattr(f, 'URI')]
                    if frame_uris:
                        validation_map = await sparql_processor.validate_frame_parent_relationship(
                            space_id, graph_id, parent_uri, frame_uris
                        )
                        invalid_frames = [uri for uri, is_valid in validation_map.items() if not is_valid]
                        if invalid_frames:
                            return FrameUpdateResponse(
                                status=OperationStatus.INVALID_REQUEST,
                                message=f"Frames are not children of parent {parent_uri}: {', '.join(invalid_frames)}",
                                updated_uri="",
                                updated_count=0
                            )
            
            # Initialize standalone frame processor if needed
            if not self.frame_processor:
                from ..kg_impl.kgframe_create_impl import KGFrameCreateProcessor
                self.frame_processor = KGFrameCreateProcessor()
            
            result = await self.frame_processor.create_frame(
                backend_adapter=backend,
                space_id=space_id,
                graph_id=graph_id,
                frame_objects=objects,
                operation_mode="UPDATE",
                if_unmodified_since=if_unmodified_since,
                precheck=precheck,
            )
            
            if not result.success:
                return FrameUpdateResponse(
                    status=OperationStatus.STORE_FAILED,
                    message=result.message,
                    updated_uri="",
                )

            updated_uris = result.created_uris
            # The rest of each replaced frame graph (`issues/256`): their
            # vector/geo/fuzzy rows go too. FTS went in the transaction.
            if getattr(result, 'removed_uris', None):
                self._schedule_auto_sync(getattr(backend, 'backend', None), space_id,
                                         graph_id, result.removed_uris, "delete")

            return FrameUpdateResponse(
                status=OperationStatus.UPDATED,
                message=f"Successfully updated {len(updated_uris)} frames",
                updated_uri=updated_uris[0] if updated_uris else "unknown",
                updated_count=len(updated_uris),
                frames_updated=len(updated_uris),
            )

        except HTTPException:
            raise
        except (StaleWrite, AmbiguousPrecondition,
                GuardUnsatisfiable, RequestRefused):
            # Past the mode handler, to be answered by `_create_frames`
            # (`issues/253`). This handler turns anything else into a 500, and
            # it turned the refusal into one too — a caller cannot tell a
            # refused write from a broken server, and the client's retry policy
            # treats the two oppositely.
            raise
        except Exception as e:
            self.logger.error(f"Error in UPDATE mode: {e}")
            raise HTTPException(status_code=500, detail=f"Update operation failed: {e}")
    
    async def _handle_upsert_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str],
                                  if_unmodified_since: Optional[str] = None, precheck=None):
        """Handle UPSERT mode: create or update frames as needed using standalone processor."""
        try:
            # Initialize standalone frame processor if needed
            if not self.frame_processor:
                from ..kg_impl.kgframe_create_impl import KGFrameCreateProcessor
                self.frame_processor = KGFrameCreateProcessor()
            
            result = await self.frame_processor.create_frame(
                backend_adapter=backend,
                space_id=space_id,
                graph_id=graph_id,
                frame_objects=objects,
                operation_mode="UPSERT",
                if_unmodified_since=if_unmodified_since,
                precheck=precheck,
            )
            
            if not result.success:
                return FrameCreateResponse(
                    status=OperationStatus.STORE_FAILED,
                    message=result.message,
                    created_count=0,
                    created_uris=[],
                )

            upserted_uris = result.created_uris
            # The rest of each replaced frame graph (`issues/256`): their
            # vector/geo/fuzzy rows go too. FTS went in the transaction.
            if getattr(result, 'removed_uris', None):
                self._schedule_auto_sync(getattr(backend, 'backend', None), space_id,
                                         graph_id, result.removed_uris, "delete")

            return FrameCreateResponse(
                status=OperationStatus.UPSERTED,
                message=f"Successfully upserted {len(upserted_uris)} frames",
                created_count=len(upserted_uris),
                created_uris=upserted_uris,
            )

        except HTTPException:
            raise
        except (StaleWrite, AmbiguousPrecondition,
                GuardUnsatisfiable, RequestRefused):
            # Past the mode handler, to be answered by `_create_frames`
            # (`issues/253`). This handler turns anything else into a 500, and
            # it turned the refusal into one too — a caller cannot tell a
            # refused write from a broken server, and the client's retry policy
            # treats the two oppositely.
            raise
        except Exception as e:
            self.logger.error(f"Error in UPSERT mode: {e}")
            raise HTTPException(status_code=500, detail=f"Upsert operation failed: {e}")
    
    async def _handle_replace_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str],
                                  if_unmodified_since: Optional[str] = None, precheck=None):
        """Handle REPLACE mode: the named frames and their descendants, atomically.

        `issues/256` item 4; see `KGFrameCreateProcessor.replace_frames`. This
        deleted every child of `parent_uri` (or the named frames) frame by frame
        with SPARQL updates, then created — no lock, no guard, and a failure in
        between left neither the old frames nor the new. Now guarded: the
        delete and the insert are one transaction.
        """
        try:
            if not self.frame_processor:
                from ..kg_impl.kgframe_create_impl import KGFrameCreateProcessor
                self.frame_processor = KGFrameCreateProcessor()

            result = await self.frame_processor.replace_frames(
                backend, space_id, graph_id, objects, parent_uri=parent_uri,
                if_unmodified_since=if_unmodified_since, precheck=precheck)
            if not result.success:
                return FrameUpdateResponse(
                    status=OperationStatus.INVALID_REQUEST, message=result.message,
                    updated_uri="", updated_count=0)

            if result.removed_uris:
                self._schedule_auto_sync(getattr(backend, 'backend', None), space_id,
                                         graph_id, result.removed_uris, "delete")
            created_uris = result.created_uris
            return FrameUpdateResponse(
                status=OperationStatus.UPDATED,
                message=result.message,
                updated_uri=created_uris[0] if created_uris else "unknown",
                updated_count=len(created_uris),
                frames_updated=result.frame_count,
            )

        except HTTPException:
            raise
        except (StaleWrite, AmbiguousPrecondition,
                GuardUnsatisfiable, RequestRefused):
            # Past the mode handler, to be answered by `_create_frames`
            # (`issues/253`).
            raise
        except Exception as e:
            self.logger.error(f"Error in REPLACE mode: {e}")
            raise HTTPException(status_code=500, detail=f"Replace operation failed: {e}")
    
    async def _frame_exists_in_backend(self, backend, space_id: str, graph_id: str, frame_uri: str) -> bool:
        """Check if frame exists in backend."""
        try:
            query = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> vital-core:vitaltype <{self.haley_prefix}KGFrame> .
                    BIND(<{frame_uri}> as ?s)
                }}
            }}
            LIMIT 1
            """
            result = await backend.execute_sparql_query(space_id, query)
            
            # Check if we got any results
            if isinstance(result, dict):
                bindings = result.get("bindings") or result.get("results", {}).get("bindings")
                return bool(bindings and len(bindings) > 0)
            elif isinstance(result, list):
                return len(result) > 0
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking frame existence: {e}")
            return False
    
    
    
    
    # `_delete_frame_from_backend` (five SPARQL updates per frame, no
    # transaction, no lock) was DELETED 2026-10-04 (`issues/256`): delete and
    # replace go through `delete_frame_subtrees` now.

    async def _get_all_triples_for_subjects(self, backend, graph_id: str, subject_uris: List[str], space_id: str) -> List[Dict[str, str]]:
        """Get all triples for the given subject URIs."""
        try:
            if not subject_uris:
                return []
            
            # Build SPARQL query to get all triples for subjects
            # Use batching if there are many subjects
            batch_size = 50  # Reasonable batch size for SPARQL IN clause
            all_triples = []
            
            for i in range(0, len(subject_uris), batch_size):
                batch_uris = subject_uris[i:i + batch_size]
                uri_list = ", ".join([f"<{uri}>" for uri in batch_uris])
                
                query = f"""
                SELECT ?s ?p ?o WHERE {{
                    GRAPH <{graph_id}> {{
                        ?s ?p ?o .
                        FILTER(?s IN ({uri_list}))
                        FILTER(?p != <http://vital.ai/vitalgraph/direct#hasEntityFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasFrame> &&
                               ?p != <http://vital.ai/vitalgraph/direct#hasSlot>)
                    }}
                }}
                ORDER BY ?s ?p ?o
                """
                
                result = await backend.execute_sparql_query(space_id, query)
                # Handle both direct bindings and results.bindings structure
                bindings = result.get("bindings") or result.get("results", {}).get("bindings") if result else None
                if bindings:
                    for binding in bindings:
                        subject = binding.get("s", {}).get("value")
                        predicate = binding.get("p", {}).get("value") 
                        obj = binding.get("o", {}).get("value")
                        
                        if subject is not None and predicate is not None and obj is not None:
                            all_triples.append({
                                "subject": subject,
                                "predicate": predicate,
                                "object": obj
                            })
            
            return all_triples
            
        except Exception as e:
            self.logger.error(f"Error getting triples for subjects: {e}")
            return []
    
    async def _convert_triples_to_vitalsigns_frames(self, triples: List[Dict[str, str]]) -> List[KGFrame]:
        """Convert triples directly to VitalSigns frame objects using native conversion."""
        try:
            if not triples:
                return []
            
            # Create VitalSigns instance
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            from rdflib import URIRef, Literal
            vs = VitalSigns()
            
            # Convert dict triples to RDFLib tuples for VitalSigns
            def triples_generator():
                for triple in triples:
                    subject = URIRef(triple["subject"])
                    predicate = URIRef(triple["predicate"])
                    
                    # Determine if object is a URI or literal
                    obj_value = triple["object"]
                    if obj_value.startswith("http://") or obj_value.startswith("https://") or obj_value.startswith("urn:"):
                        obj = URIRef(obj_value)
                    else:
                        obj = Literal(obj_value)
                    
                    yield (subject, predicate, obj)
            
            # Use VitalSigns from_triples_list to convert all triples to objects
            all_objects = await asyncio.to_thread(vs.from_triples_list, list(triples_generator()))
            
            # Filter for KGFrame objects
            frames = []
            for obj in all_objects:
                if isinstance(obj, KGFrame):
                    frames.append(obj)
            
            return frames
            
        except Exception as e:
            self.logger.error(f"Error converting triples to VitalSigns frames: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    # `_store_frames_in_backend`, `_update_frames_in_backend` and
    # `_upsert_frames_in_backend` were DELETED here 2026-10-01 (`issues/253`).
    #
    # REDUNDANT, which is the reason — not merely uncalled. The live standalone
    # frame write is `KGFrameCreateProcessor.create_frame`, reached from
    # `_create_frames` through the mode handlers, and it writes through the same
    # `update_subjects_graph` with the frame-graph lock these did not take. So
    # the capability survives in one place instead of two, and NOTHING IS LOST —
    # which is the test `kgentities_endpoint._delete_frame_by_uri` was deleted
    # against, and the clause that matters in it.
    #
    # Weaker than that precedent in one respect, stated so nobody over-reads
    # this: `_delete_frame_by_uri` had ALSO never executed (it raised TypeError
    # on every invocation), so there was no behaviour to preserve at all. These
    # three would most likely have worked if wired up. They were deleted because
    # the live path already does the job, not because they were broken.
    #
    # They were also a closed cycle — the first called only by the other two,
    # which nothing called — and `_upsert_frames_in_backend` was defined TWICE,
    # which the note that used to live here described as deliberate overrides.


    # Removed duplicate _get_all_triples_for_subjects method - using the implementation above
    # Removed duplicate _convert_triples_to_vitalsigns_frames method - using the implementation above

    async def _validate_parent_object(self, backend, space_id: str, graph_id: str, parent_uri: str) -> Dict[str, Any]:
        """Validate that parent object exists and determine its type."""
        try:
            # Check if parent is a KGEntity
            entity_query = f"""
            ASK {{
                GRAPH <{graph_id}> {{
                    <{parent_uri}> a <{self.haley_prefix}KGEntity> .
                }}
            }}
            """
            entity_result = await backend.execute_sparql_query(space_id, entity_query)
            if entity_result.get("boolean", False):
                return {"valid": True, "type": "entity", "uri": parent_uri}

            # Check if parent is a KGFrame
            frame_query = f"""
            ASK {{
                GRAPH <{graph_id}> {{
                    <{parent_uri}> a <{self.haley_prefix}KGFrame> .
                }}
            }}
            """
            frame_result = await backend.execute_sparql_query(space_id, frame_query)
            if frame_result.get("boolean", False):
                return {"valid": True, "type": "frame", "uri": parent_uri}
            
            return {"valid": False, "error": f"Parent object {parent_uri} not found or invalid type"}
            
        except Exception as e:
            self.logger.error(f"Error validating parent object: {e}")
            return {"valid": False, "error": f"Parent validation failed: {str(e)}"}

    def _create_parent_edge(self, parent_uri: str, parent_type: str, frame_uri: str) -> VITAL_Edge:
        """Create appropriate edge based on parent type."""
        try:
            if parent_type == "entity":
                # Create Edge_hasEntityKGFrame for Entity → Frame relationship
                edge = Edge_hasEntityKGFrame()
                edge.URI = f"{frame_uri}_entity_edge"
                edge.edgeSource = parent_uri
                edge.edgeDestination = frame_uri
                return edge
                
            elif parent_type == "frame":
                # Create Edge_hasKGFrame for Frame → Frame relationship
                edge = Edge_hasKGFrame()
                edge.URI = f"{frame_uri}_frame_edge"
                edge.edgeSource = parent_uri
                edge.edgeDestination = frame_uri
                return edge
                
            else:
                raise ValueError(f"Invalid parent type: {parent_type}")
                
        except Exception as e:
            self.logger.error(f"Error creating parent edge: {e}")
            raise

    async def _handle_parent_relationships(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], 
                                         objects: List[GraphObject], parent_uri: Optional[str]) -> List[GraphObject]:
        """Handle parent relationships by validating parent and creating edges."""
        try:
            if not parent_uri:
                return objects
            
            # Validate parent object exists and get its type
            parent_validation = await self._validate_parent_object(backend, space_id, graph_id, parent_uri)
            if not parent_validation.get("valid", False):
                self.logger.error(f"Parent validation failed: {parent_validation.get('error', 'Parent validation failed')}")
                return objects  # Return original objects without parent relationships
            
            parent_type = parent_validation["type"]
            enhanced_objects = list(objects)  # Copy the objects list
            
            # Create parent edges for each frame
            for frame in frames:
                frame_uri_str = str(frame.URI)
                parent_edge = self._create_parent_edge(parent_uri, parent_type, frame_uri_str)
                enhanced_objects.append(parent_edge)
                
                self.logger.info(f"Created {parent_type} → frame edge: {parent_uri} → {frame_uri_str}")
            
            return enhanced_objects
            
        except Exception as e:
            self.logger.error(f"Error handling parent relationships: {e}")
            return objects  # Return original objects on error

    # Helper methods for frame-slot operations
    
    def _build_get_frame_slots_query(self, graph_id: str, frame_uri: str, kGSlotType: Optional[str] = None,
                                     sort_by: Optional[str] = None, sort_order: str = "asc",
                                     page_size: Optional[int] = None, offset: int = 0) -> str:
        """Build SPARQL query to get slots connected to a frame via Edge_hasKGSlot.

        page_size is optional: when None the full slot set is returned, which is
        the historical behavior.  Callers paging a frame with many slots should
        pass one.

        No type pattern on ?slot: Edge_hasKGSlot's destination IS a slot by
        construction, and _sparql_results_to_slots filters isinstance(KGSlot)
        anyway. The previous
            ?slot a ?slotType .
            FILTER(STRSTARTS(STR(?slotType), "...KG") && STRENDS(..., "Slot"))
        cost ~10s to return 25 slots from a 5k-slot frame (step 5 baselines):
        it joined every slot to its type and ran string functions over the
        result. Enumerating the concrete slot classes instead would work but
        drifts — there are 31 KG*Slot classes in the schema and the list in
        _build_list_slots_query names only 5, already missing KGCurrencySlot,
        KGJSONSlot, KGChoiceSlot and KGMultiChoiceSlot which occur in real data.
        """
        slot_type_filter = ""
        if kGSlotType:
            slot_type_filter = f"?slot <{self.haley_prefix}kGSlotType> \"{kGSlotType}\" ."

        sort_optional, sort_projection, order_clause = KGSparqlUtils.build_sort_clauses(
            "?slot", sort_by, sort_order,
        )

        pagination = ""
        if page_size is not None:
            pagination = f"\n        LIMIT {page_size}\n        OFFSET {offset}"

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

        SELECT ?slot WHERE {{
            {{ SELECT DISTINCT ?slot {sort_projection} WHERE {{
            GRAPH <{graph_id}> {{
                ?edge a haley:Edge_hasKGSlot ;
                      vital:hasEdgeSource <{frame_uri}> ;
                      vital:hasEdgeDestination ?slot .
                {slot_type_filter}
                {sort_optional}
            }}
            }} }}
        }}
        {order_clause}{pagination}
        """
    
    def _build_count_frame_slots_query(self, graph_id: str, frame_uri: str,
                                       kGSlotType: Optional[str] = None) -> str:
        """Count companion for _build_get_frame_slots_query.

        Same filters, no ordering or paging — needed so a paged slot response
        can report a real total_count.
        """
        slot_type_filter = ""
        if kGSlotType:
            slot_type_filter = f"?slot <{self.haley_prefix}kGSlotType> \"{kGSlotType}\" ."

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>

        SELECT (COUNT(DISTINCT ?slot) AS ?count) WHERE {{
            GRAPH <{graph_id}> {{
                ?edge a haley:Edge_hasKGSlot ;
                      vital:hasEdgeSource <{frame_uri}> ;
                      vital:hasEdgeDestination ?slot .
                {slot_type_filter}
            }}
        }}
        """

    async def _list_frame_slots_paged(self, space_id: str, graph_id: str, frame_uri: str,
                                      page_size: int, offset: int,
                                      kGSlotType: Optional[str] = None,
                                      sort_by: Optional[str] = None,
                                      sort_order: str = "asc") -> QuadResponse:
        """Slots of ONE frame, sorted and paged.

        The second half of the two-endpoint model: frames of an entity are
        paged by /kgentities/kgframes, then each frame's slots are paged here.
        Keeping them separate avoids needing a per-frame window inside a single
        query, which SPARQL cannot express (a sub-SELECT LIMIT is global).
        """
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return QuadResponse(status=OperationStatus.NOT_FOUND, results=[],
                                    total_count=0, page_size=page_size, offset=offset)

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=503, detail="Backend implementation not available")

            full_graph_uri = graph_id
            if hasattr(backend, '_get_space_graph_uri'):
                full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)

            query = self._build_get_frame_slots_query(
                full_graph_uri, frame_uri, kGSlotType,
                sort_by=sort_by, sort_order=sort_order,
                page_size=page_size, offset=offset)
            results = await backend.execute_sparql_query(space_id, query)
            slots = await self._sparql_results_to_slots(backend, full_graph_uri, results, space_id)

            count_results = await backend.execute_sparql_query(
                space_id, self._build_count_frame_slots_query(
                    full_graph_uri, frame_uri, kGSlotType))
            total_count = self._extract_count_from_results(count_results)

            quads = await asyncio.to_thread(
                graphobjects_to_quad_list, slots or [], graph_id)
            return QuadResponse(
                status=OperationStatus.FOUND if slots else OperationStatus.EMPTY,
                results=quads, total_count=total_count,
                page_size=page_size, offset=offset)

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error listing frame slots: {e}", exc_info=True)
            return QuadResponse(status=OperationStatus.ERROR, message=str(e),
                                results=[], total_count=0,
                                page_size=page_size, offset=offset)

    async def _sparql_results_to_slots(self, backend, graph_id: str, sparql_result: Dict[str, Any],
                                       space_id: Optional[str] = None) -> List[KGSlot]:
        """Convert SPARQL results to VitalSigns slot objects using proper triple conversion."""
        try:
            slots = []
            if not sparql_result:
                return slots

            # Handle both direct bindings and results.bindings structure.
            # This previously only read the top-level "bindings" key, so with a
            # backend that returns {"results": {"bindings": [...]}} it silently
            # returned zero slots.
            bindings = (sparql_result.get("bindings")
                        or sparql_result.get("results", {}).get("bindings"))
            if not bindings:
                return slots

            # Extract slot URIs from initial query results
            slot_uris = []
            for binding in bindings:
                slot_uri = binding.get("slot", {}).get("value")
                if slot_uri:
                    slot_uris.append(slot_uri)
            
            if not slot_uris:
                return slots
            
            # Get all triples for these slot subjects
            triples = await self._get_all_triples_for_subjects(backend, graph_id, slot_uris, space_id)
            
            # Convert triples directly to VitalSigns objects
            all_objects = await self._convert_triples_to_vitalsigns_objects(triples)
            
            # Filter for slot objects
            for obj in all_objects:
                if isinstance(obj, KGSlot):
                    slots.append(obj)

            # Restore the order the paging/sorting query established — the
            # triple re-fetch above groups by its own order, which would
            # silently discard ORDER BY. See §9c of the sequence plan.
            return self._reorder_to_match(slots, slot_uris)
            
        except Exception as e:
            self.logger.error(f"Error converting SPARQL results to slots: {e}")
            return []
    
    async def _convert_triples_to_vitalsigns_objects(self, triples: List[Dict[str, str]]) -> List[GraphObject]:
        """Convert triples directly to VitalSigns objects using native conversion."""
        try:
            if not triples:
                return []
            
            # Create VitalSigns instance
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            from rdflib import URIRef, Literal
            vs = VitalSigns()
            
            # Convert dict triples to RDFLib tuples for VitalSigns
            def triples_generator():
                for triple in triples:
                    subject = URIRef(triple["subject"])
                    predicate = URIRef(triple["predicate"])
                    
                    # Determine if object is a URI or literal
                    obj_value = triple["object"]
                    if obj_value.startswith("http://") or obj_value.startswith("https://") or obj_value.startswith("urn:"):
                        obj = URIRef(obj_value)
                    else:
                        obj = Literal(obj_value)
                    
                    yield (subject, predicate, obj)
            
            # Use VitalSigns from_triples_list to convert all triples to objects
            all_objects = await asyncio.to_thread(vs.from_triples_list, list(triples_generator()))
            
            return all_objects
            
        except Exception as e:
            self.logger.error(f"Error converting triples to VitalSigns objects: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    
    
    def _create_frame_slot_edges(self, frame_uri: str, slots: List[KGSlot], objects: List[GraphObject]) -> List[GraphObject]:
        """Create Edge_hasKGSlot relationships between frame and slots."""
        enhanced_objects = list(objects)  # Copy the objects list
        
        for slot in slots:
            slot_uri = str(slot.URI)
            
            # Create Edge_hasKGSlot
            edge = Edge_hasKGSlot()
            edge.URI = f"{frame_uri}_{slot_uri}_edge"
            edge.edgeSource = frame_uri
            edge.edgeDestination = slot_uri
            
            enhanced_objects.append(edge)
            
            self.logger.info(f"Created frame → slot edge: {frame_uri} → {slot_uri}")
        
        return enhanced_objects
    
    # Helper methods for frame query operations
    
    def _build_frame_query_sparql(self, graph_id: str, query_request: FrameQueryRequest) -> str:
        """Build SPARQL query based on frame query criteria."""
        # Start with basic frame selection
        # KGFrame is the only concrete frame class (every other *Frame in the
        # schema is an Edge_*), so matching it directly is exactly equivalent to
        # the old `?frame a ?frameType` + STRSTARTS/STRENDS pair — without
        # joining every frame to its type and running string functions on the
        # result. Same fix as _build_get_frame_slots_query; see step 7.
        where_clauses = [f"?frame a <{self.haley_prefix}KGFrame> ."]
        
        # Add name filter if specified (using criteria.search_string)
        if query_request.criteria.search_string:
            where_clauses.append(f"OPTIONAL {{ ?frame <{self.vital_prefix}hasName> ?name }}")
            where_clauses.append(f"FILTER(CONTAINS(LCASE(STR(?name)), LCASE(\"{query_request.criteria.search_string}\")))")
        
        # Add frame type filter if specified
        if query_request.criteria.frame_type:
            where_clauses.append(f"?frame a <{query_request.criteria.frame_type}> .")
        
        # Add entity type filter if specified
        if query_request.criteria.entity_type:
            # Filter frames by entity type - frames must be associated with entities of this type
            where_clauses.append(f"""
            ?entityEdge a <{self.haley_prefix}Edge_hasEntityKGFrame> ;
                       <{self.vital_prefix}hasEdgeSource> ?entity ;
                       <{self.vital_prefix}hasEdgeDestination> ?frame .
            ?entity a <{query_request.criteria.entity_type}> .
            """)
        
        # Build complete query
        where_clause = "\n            ".join(where_clauses)
        
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        
        SELECT DISTINCT ?frame WHERE {{
            GRAPH <{graph_id}> {{
                {where_clause}
            }}
        }}
        """
    
    async def _get_frame_graph(
        self,
        space_id: str,
        graph_id: str,
        frame_uri: str,
        current_user: Dict
    ):
        """Get complete frame graph using processor. Returns object with graph_objects list."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            
            result = await self.frame_graph_processor.get_frame_graph(
                backend_adapter=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                frame_uri=frame_uri
            )
            
            if result.success and result.graph_objects:
                if len(result.graph_objects) == 1:
                    self.logger.debug("Frame graph has only 1 object (frame only), returning None for complete_graph")
                    return None
                return result
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"Frame graph retrieval failed: {e}", exc_info=True)
            return None
    
    async def _delete_frame_graph(
        self,
        space_id: str,
        graph_id: str,
        frame_uri: str,
        current_user: Dict
    ) -> FrameDeleteResponse:
        """Delete frame graph using processor."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Delegate to graph processor
            success = await self.frame_graph_processor.delete_frame_graph(
                backend_adapter=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                frame_uri=frame_uri
            )
            
            return FrameDeleteResponse(
                status=OperationStatus.DELETED if success else OperationStatus.STORE_FAILED,
                message="Frame graph deleted successfully" if success else "Frame graph deletion failed",
                deleted_count=1 if success else 0,
                frames_deleted=1 if success else 0
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Frame graph deletion failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Frame graph deletion failed: {e}")
    
    def _apply_frame_sorting(self, frames: List[KGFrame], sort_by: Optional[str], sort_order: Optional[str]) -> List[KGFrame]:
        """Apply sorting to frame list."""
        if not sort_by or not frames:
            return frames
        
        try:
            reverse_order = sort_order and sort_order.lower() == "desc"
            
            if sort_by == "name":
                return sorted(frames, key=lambda f: str(getattr(f, 'name', '') or ''), reverse=reverse_order)
            elif sort_by == "uri":
                return sorted(frames, key=lambda f: str(f.URI), reverse=reverse_order)
            elif sort_by == "created_date":
                return sorted(frames, key=lambda f: getattr(f, 'hasCreatedDate', None) or '', reverse=reverse_order)
            elif sort_by == "frame_type":
                return sorted(frames, key=lambda f: str(type(f).__name__), reverse=reverse_order)
            else:
                # Default to URI sorting if sort_by is not recognized
                return sorted(frames, key=lambda f: str(f.URI), reverse=reverse_order)
                
        except Exception as e:
            self.logger.warning(f"Error sorting frames by {sort_by}: {e}")
            return frames
    
    def _apply_frame_pagination(self, frames: List[KGFrame], page_size: int, offset: int) -> List[KGFrame]:
        """Apply pagination to frame list."""
        if not frames:
            return frames
        
        start_idx = max(0, offset)
        end_idx = start_idx + max(1, page_size)
        
        return frames[start_idx:end_idx]


def create_kgframes_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG frames router."""
    endpoint = KGFramesEndpoint(space_manager, auth_dependency)
    return endpoint.router
