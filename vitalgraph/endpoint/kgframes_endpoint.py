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
from fastapi import APIRouter, Query, Depends, Request, Response, Body
from pydantic import BaseModel, Field, TypeAdapter
from enum import Enum

from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse, QuadResultsResponse
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
    FrameQueryResponse
)

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

# Import slot processors
from ..kg_impl.kgslot_create_impl import KGSlotCreateProcessor
from ..kg_impl.kgslot_delete_impl import KGSlotDeleteProcessor
from ..kg_impl.kgslot_update_impl import KGSlotUpdateProcessor

# Import new frame processors
from ..kg_impl.kgframe_hierarchical_impl import KGFrameHierarchicalProcessor
from ..kg_impl.kgframe_graph_impl import KGFrameGraphProcessor
from ..kg_impl.kgframe_query_impl import KGFrameQueryProcessor

# Import backend utilities
from ..kg_impl.kg_backend_utils import create_backend_adapter
from ..auth.role_dependencies import require_space_read, require_space_write



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
        self.frame_hierarchical_processor = KGFrameHierarchicalProcessor()
        self.frame_graph_processor = KGFrameGraphProcessor()
        self.frame_query_processor = KGFrameQueryProcessor()
        
        # Slot processors will be initialized when needed with backend adapter
        # (they require backend parameter in __init__)
        self.slot_create_processor = None
        self.slot_update_processor = None
        self.slot_delete_processor = None
        
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
        try:
            op_mode = OperationMode(operation_mode.lower())
        except ValueError:
            op_mode = OperationMode.CREATE

        def _fail_create(msg):
            return FrameCreateResponse(success=False, message=msg, created_count=0, created_uris=[], slots_created=0)

        def _fail_update(msg):
            return FrameUpdateResponse(success=False, message=msg, updated_uri="", updated_count=0)

        def _fail(msg):
            return _fail_update(msg) if op_mode == OperationMode.UPDATE else _fail_create(msg)

        try:
            # --- backend ---
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return _fail(f"Space {space_id} not found")
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return _fail("Backend implementation not available")
            backend = create_backend_adapter(backend_impl)

            # --- type filtering ---
            frames = [obj for obj in vitalsigns_objects if isinstance(obj, KGFrame)]
            if not frames:
                return _fail("No valid KGFrame objects found in request")

            # --- grouping URIs ---
            # Standalone frames use only frameGraphURI (no kGGraphURI, no entity_uri)
            self._set_frame_grouping_uris(frames, graph_id)

            # --- structure validation ---
            validation_result = self._validate_frame_structure(vitalsigns_objects)
            if not validation_result.get("valid", False):
                return _fail(f"Frame validation failed: {validation_result.get('error')}")

            # --- parent / entity relationships ---
            enhanced_objects = await self._handle_parent_relationships(
                backend, space_id, graph_id, frames, vitalsigns_objects, parent_uri
            )

            # --- dispatch by mode ---
            if op_mode == OperationMode.CREATE:
                _result = await self._handle_create_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri)
            elif op_mode == OperationMode.UPDATE:
                _result = await self._handle_update_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri)
            elif op_mode == OperationMode.UPSERT:
                _result = await self._handle_upsert_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri)
            elif op_mode == OperationMode.REPLACE:
                _result = await self._handle_replace_mode(backend, space_id, graph_id, frames, enhanced_objects, parent_uri)
            else:
                return _fail(f"Invalid operation_mode: {op_mode}")

            # Auto-sync vector/geo data for changed subjects
            _sync_uris = [str(o.URI) for o in enhanced_objects if hasattr(o, 'URI') and o.URI]
            self._schedule_auto_sync(backend_impl, space_id, graph_id, _sync_uris)

            return _result

        except Exception as e:
            self.logger.error(f"Frame operation from objects failed: {e}")
            return _fail(f"Frame operation failed: {str(e)}")

    async def _create_standalone_frames(self, backend_adapter, space_id: str, graph_id: str, frame_objects: List, operation_mode: str):
        """Create standalone frames without entity dependencies."""
        try:
            # Store frames directly using backend adapter
            from vitalgraph.model.kgframes_model import FrameCreateResponse
            
            # Convert frame objects to storage format and store them
            result = await backend_adapter.store_objects(space_id, graph_id, frame_objects)
            
            if result and hasattr(result, 'success') and result.success:
                # Extract frame URIs from the objects
                frame_uris = [str(obj.URI) for obj in frame_objects if hasattr(obj, 'URI')]
                
                return FrameCreateResponse(
                    success=True,
                    message=f"Successfully created {len(frame_uris)} standalone frames",
                    created_count=len(frame_uris),
                    created_uris=frame_uris,
                    slots_created=0
                )
            else:
                return FrameCreateResponse(
                    success=False,
                    message="Failed to create standalone frames",
                    created_count=0,
                    created_uris=[],
                    slots_created=0
                )
                
        except Exception as e:
            self.logger.error(f"Standalone frame creation failed: {e}")
            return FrameCreateResponse(
                success=False,
                message=f"Standalone frame creation failed: {str(e)}",
                created_count=0,
                created_uris=[],
                slots_created=0
            )
    
    async def _update_frames(self, space_id: str, graph_id: str, vitalsigns_objects: List, operation_mode: str):
        """Update frames using direct backend storage - no entity dependencies."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Update frames using backend storage
            frames = [obj for obj in vitalsigns_objects if hasattr(obj, 'URI') and 'KGFrame' in str(type(obj))]
            if not frames:
                raise ValueError("No frames found in update request")
            
            # Update frames directly using backend adapter
            result = await backend_adapter.store_objects(space_id, graph_id, vitalsigns_objects)
            
            if result and hasattr(result, 'success') and result.success:
                return FrameUpdateResponse(
                    message=f"Successfully updated frame {frames[0].URI}",
                    updated_uri=str(frames[0].URI)
                )
            else:
                return FrameUpdateResponse(
                    message="Failed to update frame",
                    updated_uri=""
                )
            
        except Exception as e:
            self.logger.error(f"Frame update failed: {e}")
            return FrameUpdateResponse(
                message=f"Frame update failed: {str(e)}",
                updated_uri=""
            )
    
    async def _delete_frames(self, space_id: str, graph_id: str, frame_uris: List[str]):
        """Delete frames using direct backend storage - no entity dependencies."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Delete frames directly using backend adapter
            deleted_count = 0
            for frame_uri in frame_uris:
                try:
                    # Delete frame and its associated slots
                    result = await backend_adapter.delete_object(space_id, graph_id, frame_uri)
                    if result:
                        deleted_count += 1
                except Exception as e:
                    self.logger.warning(f"Failed to delete frame {frame_uri}: {e}")
            
            return FrameDeleteResponse(
                message=f"Successfully deleted {deleted_count} frames",
                deleted_count=deleted_count,
                deleted_uris=frame_uris[:deleted_count]
            )
            
        except Exception as e:
            self.logger.error(f"Frame deletion failed: {e}")
            return FrameDeleteResponse(
                message=f"Frame deletion failed: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _get_frames(self, space_id: str, graph_id: str, current_user: Dict, page_size: int = 10, offset: int = 0):
        """Get frames with pagination - wrapper for _list_frames."""
        return await self._list_frames(space_id, graph_id, page_size, offset, None, current_user)
    
    async def _get_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, current_user: Dict, page_size: int = 10, offset: int = 0):
        """Get frames associated with a specific entity."""
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
            
            sparql_query = f"""
            PREFIX haley: <{self.haley_prefix}>
            PREFIX vital: <{self.vital_prefix}>
            
            SELECT DISTINCT ?frame WHERE {{
                GRAPH <{graph_id}> {{
                    ?frame a haley:KGFrame .
                    ?frame haley:hasKGGraphURI <{entity_uri}> .
                }}
            }}
            LIMIT {page_size}
            OFFSET {offset}
            """
            
            results = await backend.execute_sparql_query(space_id, sparql_query)
            frames = await self._sparql_results_to_frames(backend, graph_id, results, space_id)
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, frames or [], graph_id)
            return QuadResponse(results=quads, total_count=len(frames), page_size=page_size, offset=offset)
            
        except Exception as e:
            self.logger.error(f"Entity frame retrieval failed: {e}")
            return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
    
    async def _delete_entities(self, space_id: str, graph_id: str, entity_uris: List[str]):
        """Delegate entity deletion (for test compatibility)."""
        return await self._delete_frames(space_id, graph_id, entity_uris)
    
    # Slot endpoint methods for /api/graphs/kgframes/kgslots
    
    async def _create_slots(self, space_id: str, graph_id: str, vitalsigns_objects: List, operation_mode: str, parent_uri: Optional[str] = None, entity_uri: Optional[str] = None):
        """Delegate slot creation to KGSlotCreateProcessor."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            
            if not self.slot_create_processor:
                self.slot_create_processor = KGSlotCreateProcessor(backend_adapter)
            
            # Set entity graph URI and parent URI on objects if provided
            if entity_uri or parent_uri:
                for obj in vitalsigns_objects:
                    if entity_uri and hasattr(obj, 'kGGraphURI'):
                        obj.kGGraphURI = entity_uri
                    if parent_uri and hasattr(obj, 'parentURI'):
                        obj.parentURI = parent_uri
            
            # Delegate to slot processor
            from ..kg_impl.kgslot_create_impl import OperationMode as SlotOperationMode
            # operation_mode is already a string, convert directly to enum (enum values are lowercase)
            op_mode = SlotOperationMode(operation_mode.lower() if isinstance(operation_mode, str) else operation_mode.value)
            
            result = await self.slot_create_processor.create_or_update_slots(
                space_id, graph_id, vitalsigns_objects, op_mode
            )
            
            # Handle different response types based on operation mode
            if op_mode == SlotOperationMode.UPSERT:
                # For UPSERT, convert SlotUpdateResponse to SlotCreateResponse format
                created_count = 1 if hasattr(result, 'updated_uri') and result.updated_uri else 0
                created_uris = [str(result.updated_uri)] if hasattr(result, 'updated_uri') and result.updated_uri else []
                return SlotCreateResponse(
                    success=True,
                    message=result.message,
                    created_count=created_count,
                    created_uris=created_uris,
                    slots_created=created_count
                )
            else:
                # For CREATE mode, use normal response handling
                created_count = getattr(result, 'created_count', 0)
                return SlotCreateResponse(
                    success=True,
                    message=result.message,
                    created_count=created_count,
                    created_uris=[str(uri) for uri in getattr(result, 'created_uris', [])],
                    slots_created=created_count
                )
            
        except Exception as e:
            self.logger.error(f"Slot creation failed: {e}")
            return SlotCreateResponse(
                success=False,
                message=f"Slot creation failed: {str(e)}",
                created_count=0,
                created_uris=[],
                slots_created=0
            )
    
    async def _update_slots(self, space_id: str, graph_id: str, vitalsigns_objects: List, operation_mode: str, parent_uri: Optional[str] = None, entity_uri: Optional[str] = None):
        """Delegate slot updates to KGSlotUpdateProcessor."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Set entity graph URI and parent URI on objects if provided
            if entity_uri or parent_uri:
                for obj in vitalsigns_objects:
                    if entity_uri and hasattr(obj, 'kGGraphURI'):
                        obj.kGGraphURI = entity_uri
                    if parent_uri and hasattr(obj, 'parentURI'):
                        obj.parentURI = parent_uri
            
            # Extract slot URIs
            slots = [obj for obj in vitalsigns_objects if isinstance(obj, KGSlot)]
            if not slots:
                return SlotUpdateResponse(
                    message="No slots found in request",
                    updated_uri=""
                )
            
            # Delegate to slot processor
            result = await self.slot_update_processor.update_slot(
                backend_adapter, space_id, graph_id, str(slots[0].URI), vitalsigns_objects
            )
            
            return SlotUpdateResponse(
                message=result.message,
                updated_uri=result.updated_uri
            )
            
        except Exception as e:
            self.logger.error(f"Slot update failed: {e}")
            return SlotUpdateResponse(
                message=f"Slot update failed: {str(e)}",
                updated_uri=""
            )
    
    async def _delete_slots(self, space_id: str, graph_id: str, slot_uris: List[str]):
        """Delegate slot deletion to KGSlotDeleteProcessor."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Delegate to slot processor
            deleted_count = await self.slot_delete_processor.delete_slots_batch(
                backend_adapter, space_id, graph_id, slot_uris, delete_slot_graph=True
            )
            
            return SlotDeleteResponse(
                message=f"Successfully deleted {deleted_count} slots",
                deleted_count=deleted_count,
                deleted_uris=slot_uris[:deleted_count]
            )
            
        except Exception as e:
            self.logger.error(f"Slot deletion failed: {e}")
            return SlotDeleteResponse(
                message=f"Slot deletion failed: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _list_slots(self, space_id: str, graph_id: str, frame_uri: str = None, page_size: int = 10, offset: int = 0):
        """List slots with optional frame filtering."""
        try:
            backend = self.backend_adapter
            
            query = self._build_list_slots_query(backend, space_id, graph_id, frame_uri, page_size, offset)
            self.logger.debug(f"Executing slot list query: {query}")
            
            query_result = backend.execute_sparql_query(query)
            slot_uris = []
            
            if query_result and 'results' in query_result and 'bindings' in query_result['results']:
                for binding in query_result['results']['bindings']:
                    if 'slot' in binding:
                        slot_uri = binding['slot']['value']
                        slot_uris.append(slot_uri)
            
            self.logger.debug(f"Found {len(slot_uris)} slots")
            
            slot_objects = []
            for slot_uri in slot_uris:
                try:
                    slot_obj = backend.get_object(slot_uri)
                    if slot_obj:
                        slot_objects.append(slot_obj)
                except Exception as e:
                    self.logger.warning(f"Failed to retrieve slot {slot_uri}: {e}")
            
            count_query = self._build_count_slots_query(backend, space_id, graph_id, frame_uri)
            count_result = backend.execute_sparql_query(count_query)
            total_count = 0
            
            if count_result and 'results' in count_result and 'bindings' in count_result['results']:
                bindings = count_result['results']['bindings']
                if bindings and 'count' in bindings[0]:
                    total_count = int(bindings[0]['count']['value'])
            
            self.logger.info(f"Listed {len(slot_objects)} slots (total: {total_count}) in graph '{graph_id}' in space '{space_id}'")
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, slot_objects, graph_id)
            return QuadResponse(results=quads, total_count=total_count, page_size=page_size, offset=offset)
            
        except Exception as e:
            self.logger.error(f"Slot listing failed: {e}")
            return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
    
    async def _get_slot_by_uri(self, space_id: str, graph_id: str, slot_uri: str, parent_uri: Optional[str] = None, entity_uri: Optional[str] = None):
        """Get single slot by URI."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            
            if await backend_adapter.object_exists(space_id, graph_id, slot_uri):
                return QuadResultsResponse(results=[], total_count=1)
            else:
                return QuadResultsResponse(results=[], total_count=0)
            
        except Exception as e:
            self.logger.error(f"Slot retrieval failed: {e}")
            return QuadResultsResponse(results=[], total_count=0)
    
    def _setup_routes(self):
        """Setup FastAPI routes for KG frames management."""
        
        @self.router.get("/kgframes", tags=["KG Frames"])
        async def list_or_get_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of frames per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            search: Optional[str] = Query(None, description="Search text to find in frame properties"),
            uri: Optional[str] = Query(None, description="Single frame URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs"),
            include_frame_graph: bool = Query(False, description="If True, include complete frame graph with slots"),
            sort_by: Optional[str] = Query(None, description="Property URI to sort by (e.g. vital-core:hasName). Must be one of the allowed sortable properties."),
            sort_order: str = Query("asc", description="Sort order: 'asc' or 'desc'"),
            form_type: Optional[str] = Query(None, description="Filter by hasKGFormType: 'Assertion', 'Aspect', or full URI"),
            frame_type_uri: Optional[str] = Query(None, description="Filter by hasKGFrameTypeURI (frame type URI)"),
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
            | `Aspect` | `haley-ai-kg#KGFormType_Aspect` | Entity-enclosed frame or child of an Assertion |

            Pass the short label (`Assertion`, `Aspect`) or the full URI.

            **Sorting (`sort_by`):**

            Must be one of the allowed property URIs:
            - `http://vital.ai/ontology/vital-core#hasName`
            - `http://vital.ai/ontology/vital#hasObjectModificationDateTime`
            - `http://vital.ai/ontology/vital-aimp#hasObjectCreationTime`
            - `http://vital.ai/ontology/vital-aimp#hasObjectStatusType`
            - `http://vital.ai/ontology/haley-ai-kg#hasKGFormType`
            - `http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeURI`
            """
            
            require_space_read(current_user, space_id)
            
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
            )

        @self.router.post("/kgframes", response_model=Union[FrameCreateResponse, FrameUpdateResponse], tags=["KG Frames"])
        async def create_or_update_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            operation_mode: str = Query("create", description="Operation mode: create, update, or upsert"),
            parent_uri: Optional[str] = Query(None, description="Parent URI for hierarchical relationships"),
            entity_uri: Optional[str] = Query(None, description="Entity URI for frame association"),
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
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete frames by URI or URI list.
            
            Args:
                recursive: If true, cascade-delete all descendant frames. If false, fail if children exist.
            """
            require_space_write(current_user, space_id)
            if uri:
                return await self._delete_frame_by_uri(space_id, graph_id, uri, current_user, recursive=recursive)
            elif uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._delete_frames_by_uris(space_id, graph_id, uris, current_user, recursive=recursive)
            else:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
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
            page_size: int = Query(10, description="Number of items per page"),
            offset: int = Query(0, description="Offset for pagination"),
            entity_uri: Optional[str] = Query(None, description="Optional entity URI for filtering"),
            parent_uri: Optional[str] = Query(None, description="Optional parent URI for filtering"),
            search: Optional[str] = Query(None, description="Optional search term"),
            kGSlotType: Optional[str] = Query(None, description="Filter by slot type"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Get frames with their associated slots using pagination.
            """
            require_space_read(current_user, space_id)
            return await self._get_kgframes_with_slots(space_id, graph_id, frame_uri, page_size, offset, entity_uri, parent_uri, search, kGSlotType, current_user)
        
        @self.router.post("/kgframes/kgslots", response_model=Union[SlotCreateResponse, SlotUpdateResponse], tags=["KG Frame Slots"])
        async def create_or_update_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            frame_uri: str = Query(..., description="Frame URI to create/update slots for"),
            entity_uri: Optional[str] = Query(None, description="Entity URI for slot context"),
            parent_uri: Optional[str] = Query(None, description="Parent URI for slot hierarchy"),
            operation_mode: str = Query("create", description="Operation mode: create, update, or upsert"),
            body: QuadRequest = Body(..., description="GraphObjects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """
            Create or update slots for a specific frame from JSON Quads.
            Operation mode determines behavior: 'create' (fail if exists), 'update' (fail if not exists), 'upsert' (create or update).
            """
            require_space_write(current_user, space_id)
            quads = body.quads
            if operation_mode == "update":
                return await self._update_frame_slots(space_id, graph_id, frame_uri, quads, current_user)
            else:
                return await self._create_frame_slots(space_id, graph_id, frame_uri, quads, operation_mode, current_user, entity_uri, parent_uri)
        
        @self.router.delete("/kgframes/kgslots", response_model=SlotDeleteResponse, tags=["KG Frame Slots"])
        async def delete_frame_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            frame_uri: str = Query(..., description="Frame URI to delete slots from"),
            slot_uris: str = Query(..., description="Comma-separated list of slot URIs to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete specific slots from a frame using Edge_hasKGSlot relationships.
            """
            require_space_write(current_user, space_id)
            slot_uri_list = [uri.strip() for uri in slot_uris.split(',') if uri.strip()]
            return await self._delete_frame_slots(space_id, graph_id, frame_uri, slot_uri_list, current_user)
    
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
                           modified_before: Optional[str] = None) -> QuadResponse:
        """List KG frames with pagination using backend interface."""
        try:
            self.logger.info(f"Listing KGFrames in space {space_id}, graph {graph_id}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)

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
            )
            count_results = await backend.execute_sparql_query(space_id, count_query)
            total_count = self._extract_count_from_results(count_results)
            quads = await asyncio.to_thread(graphobjects_to_quad_list, frames or [], graph_id)
            return QuadResponse(
                results=quads,
                total_count=total_count,
                page_size=page_size,
                offset=offset,
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGFrames: {e}")
            return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
    
    async def _get_frame_by_uri(self, space_id: str, graph_id: str, uri: str, include_frame_graph: bool, current_user: Dict) -> QuadResultsResponse:
        """Get single frame by URI with optional complete graph."""
        try:
            self.logger.info(f"🔍 Getting KGFrame {uri} from space {space_id}, graph {graph_id}, include_frame_graph={include_frame_graph}")
            
            # Get backend implementation via generic interface
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                self.logger.warning(f"❌ Space not found: {space_id}")
                return QuadResultsResponse(results=[], total_count=0)
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                self.logger.warning(f"❌ Backend not found for space: {space_id}")
                return QuadResultsResponse(results=[], total_count=0)
            
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
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, all_objects, graph_id)
            return QuadResultsResponse(
                results=quads,
                total_count=len(all_objects),
            )
            
        except Exception as e:
            self.logger.error(f"❌ Error getting KGFrame {uri}: {e}")
            import traceback
            self.logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            return QuadResultsResponse(results=[], total_count=0)
    
    async def _get_kgframes_with_slots(self, space_id: str, graph_id: str, frame_uri: Optional[str], page_size: int, offset: int, entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str], current_user: Dict):
        """Get frames with their associated slots using pagination."""
        try:
            self.logger.info(f"Getting KGFrames with slots in space {space_id}, graph {graph_id}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
            
            sparql_query = self._build_frames_with_slots_query(backend, space_id, graph_id, frame_uri, entity_uri, parent_uri, search, kGSlotType, page_size, offset)
            results = await backend.execute_sparql_query(space_id, sparql_query)
            frames = await self._sparql_results_to_frames_with_slots(backend, graph_id, results, space_id)
            
            count_query = self._build_count_frames_with_slots_query(backend, space_id, graph_id, frame_uri, entity_uri, parent_uri, search, kGSlotType)
            count_results = await backend.execute_sparql_query(space_id, count_query)
            total_count = self._extract_count_from_results(count_results)
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, frames or [], graph_id)
            return QuadResponse(results=quads, total_count=total_count, page_size=page_size, offset=offset)
            
        except Exception as e:
            self.logger.error(f"Error getting KGFrames with slots: {e}")
            return QuadResponse(results=[], total_count=0, page_size=page_size, offset=offset)
    
    def _build_frames_with_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str], entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str], page_size: int, offset: int) -> str:
        """Build SPARQL query for frames with slots.

        Returns DISTINCT ?subject where ?subject is either a frame or a slot
        reachable from it via Edge_hasKGSlot.
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

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        PREFIX vital-core: <http://vital.ai/ontology/vital-core#>

        SELECT DISTINCT ?subject WHERE {{
            {{
                GRAPH <{full_graph_uri}> {{
                    ?subject a haley:KGFrame .
                    {frame_filter.replace('?frame', '?subject') if frame_filter else ''}
                    ?slot_edge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                    ?slot_edge vital-core:hasEdgeSource ?subject .
                    ?slot_edge vital-core:hasEdgeDestination ?slot .
                }}
            }} UNION {{
                GRAPH <{full_graph_uri}> {{
                    ?frame a haley:KGFrame .
                    {frame_filter}
                    ?slot_edge vital-core:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
                    ?slot_edge vital-core:hasEdgeSource ?frame .
                    ?slot_edge vital-core:hasEdgeDestination ?subject .
                    {slot_type_filter}
                }}
            }}
        }}
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
        """Get multiple frames by URI list."""
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
            
            results = await asyncio.gather(*[_fetch_frame(uri) for uri in frame_uris])
            
            all_objects = []
            for result in results:
                if result and hasattr(result, 'objects') and result.objects:
                    all_objects.extend(result.objects)
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, all_objects, graph_id)
            return QuadResponse(
                results=quads,
                total_count=len(all_objects),
                page_size=len(frame_uris),
                offset=0,
            )
            
        except Exception as e:
            self.logger.error(f"Frame retrieval by URIs failed: {e}")
            return QuadResponse(
                results=[],
                total_count=0,
                page_size=len(frame_uris) if frame_uris else 0,
                offset=0,
            )
    
    async def _query_frames(self, space_id: str, graph_id: str, query_request: FrameQueryRequest, current_user: Dict) -> FrameQueryResponse:
        """Query frames using enhanced criteria-based search with sorting support."""
        from ..model.kgframes_model import FrameQueryResponse
        
        try:
            self.logger.info(f"Querying frames in space {space_id}, graph {graph_id} with criteria: {query_request}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return FrameQueryResponse(
                    frame_uris=[],
                    total_count=0,
                    page_size=query_request.page_size,
                    offset=query_request.offset,
                    has_more=False
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return FrameQueryResponse(
                    frame_uris=[],
                    total_count=0,
                    page_size=query_request.page_size,
                    offset=query_request.offset,
                    has_more=False
                )
            
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
                frame_uris=frame_uris,
                total_count=len(frames),
                page_size=query_request.page_size,
                offset=query_request.offset,
                has_more=len(frames) > (query_request.offset + query_request.page_size)
            )
            
        except Exception as e:
            self.logger.error(f"Error querying frames: {e}")
            return FrameQueryResponse(
                frame_uris=[],
                total_count=0,
                page_size=query_request.page_size,
                offset=query_request.offset,
                has_more=False
            )
    
    async def _delete_frame_by_uri(self, space_id: str, graph_id: str, uri: str, current_user: Dict, recursive: bool = False) -> FrameDeleteResponse:
        """Delete single frame by URI.
        
        Args:
            recursive: If True, recursively delete all descendant frames.
                       If False (default), fail if frame has children.
        """
        from ..model.kgframes_model import FrameDeleteResponse
        
        try:
            self.logger.info(f"Deleting frame {uri} from space {space_id}, graph {graph_id}, recursive={recursive}")
            
            # Get backend implementation via generic interface
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return FrameDeleteResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return FrameDeleteResponse(
                    success=False,
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Wrap backend with adapter for consistency
            backend = create_backend_adapter(backend_impl)
            
            # Check if frame exists
            if not await self._frame_exists_in_backend(backend, space_id, graph_id, uri):
                return FrameDeleteResponse(
                    success=False,
                    message=f"Frame {uri} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Check for child frames and handle recursive vs fail mode
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            sparql_processor = KGSparqlQueryProcessor(backend, self.logger)
            children = await sparql_processor.find_child_frames(space_id, graph_id, uri)
            
            uris_to_delete = [uri]
            if children:
                if not recursive:
                    return FrameDeleteResponse(
                        success=False,
                        message=f"Cannot delete frame with children (use recursive=true to cascade): {uri} has {len(children)} child(ren)",
                        deleted_count=0,
                        deleted_uris=[]
                    )
                else:
                    descendants = await sparql_processor.collect_all_descendants(space_id, graph_id, [uri])
                    if descendants:
                        self.logger.info(f"🔄 Recursive delete: adding {len(descendants)} descendant frames to deletion")
                        uris_to_delete.extend(descendants)
            
            # Delete all frames (original + descendants)
            deleted_uris = []
            for frame_uri in uris_to_delete:
                success = await self._delete_frame_from_backend(backend, space_id, graph_id, frame_uri)
                if success:
                    deleted_uris.append(frame_uri)
            
            # Auto-sync vector/geo data for deleted frames
            if deleted_uris:
                self._schedule_auto_sync(backend_impl, space_id, graph_id, deleted_uris, "delete")

            return FrameDeleteResponse(
                message=f"Successfully deleted {len(deleted_uris)} frame(s)",
                deleted_count=len(deleted_uris),
                deleted_uris=deleted_uris
            )
                
        except Exception as e:
            self.logger.error(f"Error deleting frame: {e}")
            return FrameDeleteResponse(
                success=False,
                message=f"Failed to delete frame: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _delete_frames_by_uris(self, space_id: str, graph_id: str, uris: List[str], current_user: Dict, recursive: bool = False) -> FrameDeleteResponse:
        """Delete multiple frames by URI list.
        
        Args:
            recursive: If True, recursively delete all descendant frames.
                       If False (default), fail if any frame has children.
        """
        from ..model.kgframes_model import FrameDeleteResponse
        
        try:
            self.logger.info(f"Deleting {len(uris)} frames from space {space_id}, graph {graph_id}, recursive={recursive}")
            
            # Get backend implementation via generic interface
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return FrameDeleteResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return FrameDeleteResponse(
                    success=False,
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Wrap backend with adapter for consistency
            backend = create_backend_adapter(backend_impl)
            
            # Check for child frames and handle recursive vs fail mode
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            sparql_processor = KGSparqlQueryProcessor(backend, self.logger)
            
            frames_with_children = {}
            for uri in uris:
                children = await sparql_processor.find_child_frames(space_id, graph_id, uri)
                if children:
                    frames_with_children[uri] = children
            
            if frames_with_children:
                if not recursive:
                    child_summary = "; ".join(
                        f"{uri} has {len(kids)} child(ren)"
                        for uri, kids in frames_with_children.items()
                    )
                    return FrameDeleteResponse(
                        success=False,
                        message=f"Cannot delete frames with children (use recursive=true to cascade): {child_summary}",
                        deleted_count=0,
                        deleted_uris=[]
                    )
                else:
                    descendants = await sparql_processor.collect_all_descendants(space_id, graph_id, uris)
                    if descendants:
                        self.logger.info(f"🔄 Recursive delete: adding {len(descendants)} descendant frames to deletion")
                        uris = uris + descendants
            
            deleted_uris = []
            for uri in uris:
                try:
                    if await self._frame_exists_in_backend(backend, space_id, graph_id, uri):
                        success = await self._delete_frame_from_backend(backend, space_id, graph_id, uri)
                        if success:
                            deleted_uris.append(uri)
                except Exception as e:
                    self.logger.warning(f"Failed to delete frame {uri}: {e}")
                    continue
            
            # Auto-sync vector/geo data for deleted frames
            if deleted_uris:
                self._schedule_auto_sync(backend_impl, space_id, graph_id, deleted_uris, "delete")

            return FrameDeleteResponse(
                message=f"Successfully deleted {len(deleted_uris)} frame(s)",
                deleted_count=len(deleted_uris),
                deleted_uris=deleted_uris
            )
                
        except Exception as e:
            self.logger.error(f"Error deleting frames: {e}")
            return FrameDeleteResponse(
                success=False,
                message=f"Failed to delete frames: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
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
            slots = await self._sparql_results_to_slots(backend, graph_id, results)
            
            return slots or []
            
        except Exception as e:
            self.logger.error(f"Error getting frame slots: {e}")
            return []
    
    async def _create_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, quads: List[Quad], operation_mode: OperationMode, current_user: Dict, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> SlotCreateResponse:
        """Create slots for a specific frame from quads."""
        from ..model.kgframes_model import SlotCreateResponse
        vitalsigns_objects = quad_list_to_graphobjects(quads)
        
        try:
            self.logger.info(f"Creating slots for frame {frame_uri} with operation_mode {operation_mode}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return SlotCreateResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    created_count=0,
                    created_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return SlotCreateResponse(
                    success=False,
                    message="Backend implementation not available",
                    created_count=0,
                    created_uris=[]
                )
            backend = create_backend_adapter(backend_impl)
            
            if not await self._frame_exists_in_backend(backend, space_id, graph_id, frame_uri):
                return SlotCreateResponse(
                    success=False,
                    message=f"Frame {frame_uri} not found",
                    created_count=0,
                    created_uris=[]
                )
            
            # Extract slots and validate
            slots = [obj for obj in vitalsigns_objects if isinstance(obj, KGSlot)]
            if not slots:
                return SlotCreateResponse(
                    success=False,
                    message="No valid KGSlot objects found in request",
                    created_count=0,
                    created_uris=[]
                )
            
            # Set frameGraphURI on slots to connect them to the frame
            self._set_slot_frame_relationships(slots, frame_uri)
            
            # Create Edge_hasKGSlot relationships
            enhanced_objects = self._create_frame_slot_edges(frame_uri, slots, vitalsigns_objects)
            
            # Handle operation mode
            if operation_mode == OperationMode.CREATE:
                # Verify slots don't already exist
                for slot in slots:
                    slot_uri = str(slot.URI)
                    if await self._slot_exists_in_backend(backend, space_id, graph_id, slot_uri):
                        return SlotCreateResponse(
                            success=False,
                            message=f"Slot {slot_uri} already exists",
                            created_count=0,
                            created_uris=[]
                        )
            
            # Store slots and edges in backend
            created_uris = await self._store_frame_slots_in_backend(backend, space_id, graph_id, enhanced_objects)
            
            # Auto-sync vector/geo data for created slots
            _sync_uris = [str(o.URI) for o in enhanced_objects if hasattr(o, 'URI') and o.URI]
            self._schedule_auto_sync(backend_impl, space_id, graph_id, _sync_uris)

            return SlotCreateResponse(
                success=True,
                message=f"Successfully created {len(created_uris)} slots for frame {frame_uri}",
                created_count=len(created_uris),
                created_uris=created_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error creating frame slots: {e}")
            return SlotCreateResponse(
                success=False,
                message=f"Failed to create frame slots: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _update_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, quads: List[Quad], current_user: Dict) -> SlotUpdateResponse:
        """Update slots for a specific frame from quads."""
        from ..model.kgframes_model import SlotUpdateResponse
        vitalsigns_objects = quad_list_to_graphobjects(quads)
        
        try:
            self.logger.info(f"Updating slots for frame {frame_uri} in space {space_id}, graph {graph_id}")
            
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return SlotUpdateResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    updated_count=0,
                    updated_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return SlotUpdateResponse(
                    success=False,
                    message="Backend implementation not available",
                    updated_count=0,
                    updated_uris=[]
                )
            backend = create_backend_adapter(backend_impl)
            
            if not await self._frame_exists_in_backend(backend, space_id, graph_id, frame_uri):
                return SlotUpdateResponse(
                    success=False,
                    message=f"Frame {frame_uri} not found",
                    updated_count=0,
                    updated_uris=[]
                )
            
            # Extract slots and validate
            slots = [obj for obj in vitalsigns_objects if isinstance(obj, KGSlot)]
            if not slots:
                return SlotUpdateResponse(
                    success=False,
                    message="No valid KGSlot objects found in request",
                    updated_count=0,
                    updated_uris=[]
                )
            
            # Validate all slots exist before updating
            for slot in slots:
                slot_uri = str(slot.URI)
                if not await self._slot_exists_in_backend(backend, space_id, graph_id, slot_uri):
                    return SlotUpdateResponse(
                        success=False,
                        message=f"Slot {slot_uri} not found",
                        updated_count=0,
                        updated_uris=[]
                    )
            
            # Set frameGraphURI on slots to maintain frame relationships
            self._set_slot_frame_relationships(slots, frame_uri)
            
            # Update slots in backend (delete existing and insert updated)
            updated_uris = await self._update_frame_slots_in_backend(backend, space_id, graph_id, slots)
            
            # Auto-sync vector/geo data for updated slots
            _sync_uris = [str(s.URI) for s in slots if hasattr(s, 'URI') and s.URI]
            self._schedule_auto_sync(backend_impl, space_id, graph_id, _sync_uris)

            return SlotUpdateResponse(
                message=f"Successfully updated {len(updated_uris)} slots for frame {frame_uri}",
                updated_count=len(updated_uris),
                updated_uris=updated_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error updating frame slots: {e}")
            return SlotUpdateResponse(
                success=False,
                message=f"Failed to update frame slots: {str(e)}",
                updated_count=0,
                updated_uris=[]
            )
    
    async def _delete_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, slot_uris: List[str], current_user: Dict) -> SlotDeleteResponse:
        """Delete specific slots from a frame using Edge_hasKGSlot relationships."""
        from ..model.kgframes_model import SlotDeleteResponse
        
        try:
            self.logger.info(f"Deleting {len(slot_uris)} slots from frame {frame_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                return SlotDeleteResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return SlotDeleteResponse(
                    success=False,
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            backend = create_backend_adapter(backend_impl)
            
            # Validate that frame exists
            if not await self._frame_exists_in_backend(backend, space_id, graph_id, frame_uri):
                return SlotDeleteResponse(
                    success=False,
                    message=f"Frame {frame_uri} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Validate all slots exist and are connected to this frame
            validated_slots = []
            for slot_uri in slot_uris:
                if not await self._slot_exists_in_backend(backend, space_id, graph_id, slot_uri):
                    return SlotDeleteResponse(
                        success=False,
                        message=f"Slot {slot_uri} not found",
                        deleted_count=0,
                        deleted_uris=[]
                    )
                
                # Verify slot is connected to this frame via Edge_hasKGSlot
                if not await self._slot_connected_to_frame(backend, space_id, graph_id, frame_uri, slot_uri):
                    return SlotDeleteResponse(
                        success=False,
                        message=f"Slot {slot_uri} is not connected to frame {frame_uri}",
                        deleted_count=0,
                        deleted_uris=[]
                    )
                
                validated_slots.append(slot_uri)
            
            # Delete slots and their edges from backend
            deleted_count = await self._delete_frame_slots_from_backend(backend, space_id, graph_id, frame_uri, validated_slots)
            
            # Auto-sync vector/geo data for deleted slots
            if deleted_count > 0:
                self._schedule_auto_sync(backend_impl, space_id, graph_id, validated_slots[:deleted_count], "delete")

            return SlotDeleteResponse(
                success=True,
                message=f"Successfully deleted {deleted_count} slots from frame {frame_uri}",
                deleted_count=deleted_count,
                deleted_uris=validated_slots[:deleted_count]
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting frame slots: {e}")
            return SlotDeleteResponse(
                success=False,
                message=f"Failed to delete frame slots: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
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
                                    modified_before: Optional[str] = None) -> str:
        """Build SPARQL filter clause fragments for frame list queries."""
        parts = []

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
                                 modified_before: Optional[str] = None) -> str:
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
        )

        # Build sort clause
        direction = "DESC" if sort_order == "desc" else "ASC"
        sort_optional = ""
        if sort_by:
            sort_optional = f"OPTIONAL {{ ?frame <{sort_by}> ?sort_val . }}"
            order_clause = f"ORDER BY {direction}(?sort_val) ?frame"
        else:
            order_clause = "ORDER BY ?frame"

        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        
        SELECT DISTINCT ?frame WHERE {{
            GRAPH <{full_graph_uri}> {{
                ?frame a haley:KGFrame .
                {filters}
                {sort_optional}
            }}
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
                                  modified_before: Optional[str] = None) -> str:
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
    
    def _build_list_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str], page_size: int, offset: int) -> str:
        """Build SPARQL query for listing slot subjects by finding objects with hasFrameGraphURI property."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id
            
        frame_filter = ""
        if frame_uri:
            frame_filter = f"""
            ?slot haley:hasFrameGraphURI <{frame_uri}> .
            """
        
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT DISTINCT ?slot WHERE {{{{
            GRAPH <{full_graph_uri}> {{{{
                # Find objects that have hasFrameGraphURI property (these are slot objects)
                ?slot haley:hasFrameGraphURI ?hasFrameGraphURI .
                # Match all concrete slot subclasses
                {{
                    ?slot a haley:KGTextSlot .
                }} UNION {{
                    ?slot a haley:KGIntegerSlot .
                }} UNION {{
                    ?slot a haley:KGDateTimeSlot .
                }} UNION {{
                    ?slot a haley:KGBooleanSlot .
                }} UNION {{
                    ?slot a haley:KGDoubleSlot .
                }}
                {frame_filter}
            }}}}
        }}}}
        ORDER BY ?slot
        LIMIT {page_size}
        OFFSET {offset}
        """
    
    def _build_count_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str]) -> str:
        """Build SPARQL count query for slots by finding objects with hasFrameGraphURI property."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id
            
        frame_filter = ""
        if frame_uri:
            frame_filter = f"""
            ?slot haley:hasFrameGraphURI <{frame_uri}> .
            """
            
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT (COUNT(DISTINCT ?slot) as ?count) WHERE {{
            GRAPH <{full_graph_uri}> {{
                # Find objects that have hasFrameGraphURI property (these are slot objects)
                ?slot haley:hasFrameGraphURI ?hasFrameGraphURI .
                # Match all concrete slot subclasses
                {{
                    ?slot a haley:KGTextSlot .
                }} UNION {{
                    ?slot a haley:KGIntegerSlot .
                }} UNION {{
                    ?slot a haley:KGDateTimeSlot .
                }} UNION {{
                    ?slot a haley:KGBooleanSlot .
                }} UNION {{
                    ?slot a haley:KGDoubleSlot .
                }}
                {frame_filter}
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
    
    async def _handle_create_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str]):
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
                operation_mode="CREATE"
            )
            
            if not result.success:
                return FrameCreateResponse(
                    success=False,
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
                success=True,
                message=f"Successfully created {len(created_uris)} frames in graph '{graph_id}' in space '{space_id}'",
                created_count=len(created_uris),
                created_uris=created_uris,
                slots_created=slots_count,
            )
            
        except Exception as e:
            self.logger.error(f"Error in CREATE mode: {e}")
            return FrameCreateResponse(
                success=False,
                message=f"Failed to create frames: {str(e)}",
                created_count=0,
                created_uris=[],
                slots_created=0
            )
    
    async def _handle_update_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str]):
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
                                success=False,
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
                operation_mode="UPDATE"
            )
            
            if not result.success:
                return FrameUpdateResponse(
                success=False,
                message=result.message,
                updated_uri="",
            )
            
            updated_uris = result.created_uris
            
            return FrameUpdateResponse(
                success=True,
                message=f"Successfully updated {len(updated_uris)} frames",
                updated_uri=updated_uris[0] if updated_uris else "unknown",
                updated_count=len(updated_uris),
                frames_updated=len(updated_uris),
            )
            
        except Exception as e:
            self.logger.error(f"Error in UPDATE mode: {e}")
            return FrameUpdateResponse(
                success=False,
                message=f"Update operation failed: {str(e)}",
                updated_uri=""
            )
    
    async def _handle_upsert_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str]):
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
                operation_mode="UPSERT"
            )
            
            if not result.success:
                return FrameCreateResponse(
                    success=False,
                    message=result.message,
                    created_count=0,
                    created_uris=[],
                )
            
            upserted_uris = result.created_uris
            
            return FrameCreateResponse(
                success=True,
                message=f"Successfully upserted {len(upserted_uris)} frames",
                created_count=len(upserted_uris),
                created_uris=upserted_uris,
            )
            
        except Exception as e:
            self.logger.error(f"Error in UPSERT mode: {e}")
            return FrameCreateResponse(
                success=False,
                message=f"Upsert operation failed: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _handle_replace_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str]):
        """Handle REPLACE mode: delete the existing frame subtree, then insert the new frame graph.
        
        Determines the delete scope from EXISTING frames in the DB:
        - If parent_uri is a KGFrame: deletes its children + their descendants
        - Otherwise: falls back to deleting the replacement graph's frame URIs + descendants
        
        Then inserts the replacement graph via CREATE.
        
        Args:
            parent_uri: If provided and is a KGFrame, scopes replacement to children of this parent.
        """
        try:
            replacement_frame_uris = [str(f.URI) for f in frames if hasattr(f, 'URI')]
            if not replacement_frame_uris:
                return FrameUpdateResponse(
                    success=False,
                    message="No frame URIs found in replacement graph",
                    updated_uri="",
                    updated_count=0
                )
            
            # Phase 1: Determine delete scope from EXISTING frames in the DB
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            sparql_processor = KGSparqlQueryProcessor(backend, self.logger)
            
            if parent_uri:
                parent_is_frame = await self._frame_exists_in_backend(backend, space_id, graph_id, parent_uri)
                if parent_is_frame:
                    # Scoped replace: delete children of the given parent
                    existing_children = await sparql_processor.find_child_frames(
                        space_id, graph_id, parent_uri
                    )
                    root_frames_to_delete = existing_children
                else:
                    # parent_uri is not a frame (e.g. entity URI) — use replacement URIs as fallback
                    root_frames_to_delete = replacement_frame_uris
            else:
                # No parent scope — use replacement URIs as fallback
                root_frames_to_delete = replacement_frame_uris
            
            # Collect all descendants of the root frames being deleted
            all_uris_to_delete = list(root_frames_to_delete)
            if root_frames_to_delete:
                descendants = await sparql_processor.collect_all_descendants(space_id, graph_id, root_frames_to_delete)
                if descendants:
                    self.logger.info(f"🔄 REPLACE mode: found {len(descendants)} descendant frames to remove")
                    all_uris_to_delete.extend(descendants)
            
            # Phase 2: Delete existing subtree (frames + slots + edges) but NOT parent→root edges
            for uri in all_uris_to_delete:
                await self._delete_frame_from_backend(backend, space_id, graph_id, uri)
            self.logger.info(f"🗑️ REPLACE mode: deleted {len(all_uris_to_delete)} existing frames")
            
            # Phase 3: Insert replacement graph using standalone CREATE mode
            if not self.frame_processor:
                from ..kg_impl.kgframe_create_impl import KGFrameCreateProcessor
                self.frame_processor = KGFrameCreateProcessor()
            
            result = await self.frame_processor.create_frame(
                backend_adapter=backend,
                space_id=space_id,
                graph_id=graph_id,
                frame_objects=objects,
                operation_mode="CREATE"
            )
            
            if not result.success:
                return FrameUpdateResponse(
                    success=False,
                    message=f"Replace failed during re-creation: {result.message}",
                    updated_uri="",
                    updated_count=0
                )
            
            created_uris = result.created_uris
            return FrameUpdateResponse(
                success=True,
                message=f"Successfully replaced {len(all_uris_to_delete)} frames with {len(created_uris)} new frames",
                updated_uri=created_uris[0] if created_uris else "unknown",
                updated_count=len(created_uris),
                frames_updated=len(created_uris),
            )
            
        except Exception as e:
            self.logger.error(f"Error in REPLACE mode: {e}")
            return FrameUpdateResponse(
                success=False,
                message=f"Replace operation failed: {str(e)}",
                updated_uri=""
            )
    
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
    
    async def _store_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """
        Store VitalSigns frame objects in backend using atomic update_quads.
        
        Queries existing triples for all subject URIs first, then uses a single
        transaction for delete + insert to prevent triple accumulation.
        """
        try:
            frame_uris = []
            for obj in objects:
                if isinstance(obj, KGFrame):
                    frame_uris.append(str(obj.URI))
            
            # Step 1: Build insert quads from VitalSigns objects (preserve RDFLib objects)
            triples = await asyncio.to_thread(GraphObject.to_triples_list, objects)
            insert_quads = [(str(s), str(p), o, graph_id) for s, p, o in triples]
            
            if not insert_quads:
                return frame_uris
            
            # Step 2: Subject-level delete + insert (safe path)
            subject_uris = list({str(obj.URI) for obj in objects
                                 if hasattr(obj, 'URI') and obj.URI})
            
            if hasattr(backend, 'update_subjects_graph'):
                await backend.update_subjects_graph(
                    space_id, graph_id, subject_uris, insert_quads)
            else:
                delete_quads = []
                if subject_uris:
                    subject_values = " ".join(f"<{uri}>" for uri in subject_uris)
                    query = f"""SELECT ?subject ?predicate ?object WHERE {{
                        GRAPH <{graph_id}> {{
                            VALUES ?subject {{ {subject_values} }}
                            ?subject ?predicate ?object .
                        }}
                    }}"""
                    
                    results = await backend.execute_sparql_query(space_id, query)
                    
                    bindings = []
                    if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                        bindings = results['results'].get('bindings', [])
                    elif isinstance(results, list):
                        bindings = results
                    
                    from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib
                    for row in bindings:
                        if isinstance(row, dict):
                            s = str(row['subject'].get('value', '')) if isinstance(row.get('subject'), dict) else str(row.get('subject', ''))
                            p = str(row['predicate'].get('value', '')) if isinstance(row.get('predicate'), dict) else str(row.get('predicate', ''))
                            o = _sparql_binding_to_rdflib(row.get('object', ''))
                            if s and p and o is not None:
                                delete_quads.append((s, p, o, graph_id))
                
                await backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
            
            return frame_uris
            
        except Exception as e:
            self.logger.error(f"Error storing frames in backend: {e}")
            raise
    
    async def _update_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """
        Update VitalSigns objects in backend via atomic update_quads.
        
        Delegates to _store_frames_in_backend which handles atomic
        delete + insert in a single transaction.
        """
        try:
            return await self._store_frames_in_backend(backend, space_id, graph_id, objects)
            
        except Exception as e:
            self.logger.error(f"Error updating frames in backend: {e}")
            raise
    
    async def _upsert_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """Upsert VitalSigns objects in backend via atomic update_quads."""
        try:
            return await self._store_frames_in_backend(backend, space_id, graph_id, objects)
            
        except Exception as e:
            self.logger.error(f"Error upserting frames in backend: {e}")
            raise
    
    async def _delete_frame_from_backend(self, backend, space_id: str, graph_id: str, frame_uri: str) -> bool:
        """Delete frame and all objects in its frame graph using frameGraphURI grouping.
        
        Uses the frameGraphURI pattern to find every subject that belongs to
        this frame (the frame itself, its slots, and slot edges) and deletes
        all their triples in a single pass.  Then removes structural edges
        (Edge_hasKGFrame, Edge_hasEntityKGFrame) that reference this frame.
        """
        try:
            # Phase 1: Delete all subjects in the frame graph (frame, slots, slot edges)
            # Every object created under a frame has hasFrameGraphURI = frame_uri
            delete_frame_graph = f"""
            DELETE {{
                GRAPH <{graph_id}> {{
                    ?s ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    ?s <{self.haley_prefix}hasFrameGraphURI> <{frame_uri}> .
                    ?s ?p ?o .
                }}
            }}
            """
            await backend.execute_sparql_update(space_id, delete_frame_graph)
            
            # Also delete the frame's own triples (in case it does not have
            # hasFrameGraphURI pointing to itself)
            delete_frame_self = f"""
            DELETE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?p ?o .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?p ?o .
                }}
            }}
            """
            await backend.execute_sparql_update(space_id, delete_frame_self)
            
            # Phase 2: Clean up structural edges that reference this frame
            # Edge_hasKGFrame where this frame is destination (parent→this)
            delete_incoming_frame_edges = f"""
            DELETE {{
                GRAPH <{graph_id}> {{
                    ?edge ?ep ?eo .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <{self.haley_prefix}Edge_hasKGFrame> ;
                          <{self.vital_prefix}hasEdgeDestination> <{frame_uri}> .
                    ?edge ?ep ?eo .
                }}
            }}
            """
            await backend.execute_sparql_update(space_id, delete_incoming_frame_edges)
            
            # Edge_hasKGFrame where this frame is source (this→children)
            delete_outgoing_frame_edges = f"""
            DELETE {{
                GRAPH <{graph_id}> {{
                    ?edge ?ep ?eo .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <{self.haley_prefix}Edge_hasKGFrame> ;
                          <{self.vital_prefix}hasEdgeSource> <{frame_uri}> .
                    ?edge ?ep ?eo .
                }}
            }}
            """
            await backend.execute_sparql_update(space_id, delete_outgoing_frame_edges)
            
            # Edge_hasEntityKGFrame where this frame is destination (entity→this)
            delete_entity_frame_edges = f"""
            DELETE {{
                GRAPH <{graph_id}> {{
                    ?edge ?ep ?eo .
                }}
            }}
            WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <{self.haley_prefix}Edge_hasEntityKGFrame> ;
                          <{self.vital_prefix}hasEdgeDestination> <{frame_uri}> .
                    ?edge ?ep ?eo .
                }}
            }}
            """
            await backend.execute_sparql_update(space_id, delete_entity_frame_edges)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error deleting frame from backend: {e}")
            return False
    
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
    
    # NOTE: _update_frames_in_backend and _upsert_frames_in_backend are defined
    # earlier in the class and delegate to _store_frames_in_backend which uses
    # atomic update_quads.  The second definitions below are kept as overrides
    # for the slot-related sub-section of the endpoint.

    async def _upsert_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """Upsert VitalSigns objects in backend via atomic update_quads."""
        try:
            return await self._store_frames_in_backend(backend, space_id, graph_id, objects)
            
        except Exception as e:
            self.logger.error(f"Error upserting frames in backend: {e}")
            raise

    # Removed duplicate _delete_frame_from_backend method - using the implementation above
    # Removed duplicate _get_all_triples_for_subjects method - using the implementation above
    # Removed duplicate _convert_triples_to_vitalsigns_frames method - using the implementation above

    @staticmethod
    def _result_has_rows(result) -> bool:
        """Check if a SPARQL SELECT result contains any rows."""
        if isinstance(result, dict):
            bindings = result.get("bindings") or result.get("results", {}).get("bindings")
            return bool(bindings and len(bindings) > 0)
        elif isinstance(result, list):
            return len(result) > 0
        return False

    async def _validate_parent_object(self, backend, space_id: str, graph_id: str, parent_uri: str) -> Dict[str, Any]:
        """Validate that parent object exists and determine its type.
        
        Uses SELECT queries (not ASK) because the SQL backend compiles ASK
        to SELECT and does not return a 'boolean' key.
        """
        try:
            # Check if parent is a KGEntity
            entity_query = f"""
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{parent_uri}> a <{self.haley_prefix}KGEntity> .
                    BIND(<{parent_uri}> as ?s)
                }}
            }} LIMIT 1
            """
            entity_result = await backend.execute_sparql_query(space_id, entity_query)
            if self._result_has_rows(entity_result):
                return {"valid": True, "type": "entity", "uri": parent_uri}
            
            # Check if parent is a KGFrame
            frame_query = f"""
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{parent_uri}> a <{self.haley_prefix}KGFrame> .
                    BIND(<{parent_uri}> as ?s)
                }}
            }} LIMIT 1
            """
            frame_result = await backend.execute_sparql_query(space_id, frame_query)
            if self._result_has_rows(frame_result):
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
    
    def _build_get_frame_slots_query(self, graph_id: str, frame_uri: str, kGSlotType: Optional[str] = None) -> str:
        """Build SPARQL query to get slots connected to a frame via Edge_hasKGSlot."""
        slot_type_filter = ""
        if kGSlotType:
            slot_type_filter = f"?slot <{self.haley_prefix}kGSlotType> \"{kGSlotType}\" ."
        
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT DISTINCT ?slot WHERE {{
            GRAPH <{graph_id}> {{
                ?edge a haley:Edge_hasKGSlot ;
                      vital:hasEdgeSource <{frame_uri}> ;
                      vital:hasEdgeDestination ?slot .
                ?slot a ?slotType .
                FILTER(STRSTARTS(STR(?slotType), "{self.haley_prefix}KG") && STRENDS(STR(?slotType), "Slot"))
                {slot_type_filter}
            }}
        }}
        ORDER BY ?slot
        """
    
    async def _sparql_results_to_slots(self, backend, graph_id: str, sparql_result: Dict[str, Any]) -> List[KGSlot]:
        """Convert SPARQL results to VitalSigns slot objects using proper triple conversion."""
        try:
            slots = []
            if not sparql_result or not sparql_result.get("bindings"):
                return slots
            
            # Extract slot URIs from initial query results
            slot_uris = []
            for binding in sparql_result["bindings"]:
                slot_uri = binding.get("slot", {}).get("value")
                if slot_uri:
                    slot_uris.append(slot_uri)
            
            if not slot_uris:
                return slots
            
            # Get all triples for these slot subjects
            triples = await self._get_all_triples_for_subjects(backend, graph_id, slot_uris)
            
            # Convert triples directly to VitalSigns objects
            all_objects = await self._convert_triples_to_vitalsigns_objects(triples)
            
            # Filter for slot objects
            for obj in all_objects:
                if isinstance(obj, KGSlot):
                    slots.append(obj)
            
            return slots
            
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
    
    
    
    def _set_slot_frame_relationships(self, slots: List[KGSlot], frame_uri: str):
        """Set frameGraphURI on slots to connect them to the frame."""
        for slot in slots:
            if isinstance(slot, KGSlot):
                # Set frameGraphURI to connect slot to frame
                slot.frameGraphURI = frame_uri
    
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
    
    async def _slot_exists_in_backend(self, backend, space_id: str, graph_id: str, slot_uri: str) -> bool:
        """Check if slot exists in backend."""
        try:
            query = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{slot_uri}> vital-core:vitaltype ?type .
                    FILTER(STRSTARTS(STR(?type), "{self.haley_prefix}KG") && STRENDS(STR(?type), "Slot"))
                    BIND(<{slot_uri}> as ?s)
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
            self.logger.error(f"Error checking slot existence: {e}")
            return False
    
    async def _slot_connected_to_frame(self, backend, space_id: str, graph_id: str, frame_uri: str, slot_uri: str) -> bool:
        """Check if slot is connected to frame via Edge_hasKGSlot."""
        try:
            query = f"""
            PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
            SELECT ?edge WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge vital-core:vitaltype <{self.haley_prefix}Edge_hasKGSlot> .
                    ?edge vital-core:hasEdgeSource <{frame_uri}> .
                    ?edge vital-core:hasEdgeDestination <{slot_uri}> .
                }}
            }}
            LIMIT 1
            """
            result = await backend.execute_sparql_query(space_id, query)
            if isinstance(result, dict):
                bindings = result.get("bindings") or result.get("results", {}).get("bindings")
                return bool(bindings and len(bindings) > 0)
            return False
            
        except Exception as e:
            self.logger.error(f"Error checking slot-frame connection: {e}")
            return False
    
    async def _update_frame_slots_in_backend(self, backend, space_id: str, graph_id: str, slots: List[KGSlot]) -> List[str]:
        """
        Update VitalSigns slot objects in backend using atomic update_quads.
        
        Joins DELETE and INSERT into a single PostgreSQL transaction and a
        single Fuseki request, preventing triple accumulation if the delete
        phase succeeds but the insert fails (or vice versa).
        """
        try:
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            slot_uris = [str(slot.URI) for slot in slots]
            
            # Step 1: Build insert quads from VitalSigns objects (preserve RDFLib objects)
            triples = await asyncio.to_thread(GraphObject.to_triples_list, slots)
            insert_quads = [(str(s), str(p), o, graph_id) for s, p, o in triples]
            
            # Step 2: Subject-level delete + insert (safe path)
            if hasattr(backend, 'update_subjects_graph'):
                await backend.update_subjects_graph(
                    space_id, graph_id, slot_uris, insert_quads)
            else:
                subject_values = " ".join(f"<{uri}>" for uri in slot_uris)
                query = f"""SELECT ?subject ?predicate ?object WHERE {{
                    GRAPH <{graph_id}> {{
                        VALUES ?subject {{ {subject_values} }}
                        ?subject ?predicate ?object .
                    }}
                }}"""
                results = await backend.execute_sparql_query(space_id, query)
                
                delete_quads = []
                bindings = []
                if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                    bindings = results['results'].get('bindings', [])
                elif isinstance(results, list):
                    bindings = results
                
                from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib
                for row in bindings:
                    if isinstance(row, dict):
                        s = str(row['subject'].get('value', '')) if isinstance(row.get('subject'), dict) else str(row.get('subject', ''))
                        p = str(row['predicate'].get('value', '')) if isinstance(row.get('predicate'), dict) else str(row.get('predicate', ''))
                        o = _sparql_binding_to_rdflib(row.get('object', ''))
                        if s and p and o is not None:
                            delete_quads.append((s, p, o, graph_id))
                
                await backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
            
            return slot_uris
            
        except Exception as e:
            self.logger.error(f"Error updating frame slots in backend: {e}")
            raise
    
    async def _delete_frame_slots_from_backend(self, backend, space_id: str, graph_id: str, frame_uri: str, slot_uris: List[str]) -> int:
        """Delete slots and their Edge_hasKGSlot relationships from backend."""
        try:
            deleted_count = 0
            
            for slot_uri in slot_uris:
                try:
                    # Delete the slot itself
                    delete_slot_query = f"""
                    DELETE {{
                        GRAPH <{graph_id}> {{
                            <{slot_uri}> ?p ?o .
                        }}
                    }}
                    WHERE {{
                        GRAPH <{graph_id}> {{
                            <{slot_uri}> ?p ?o .
                        }}
                    }}
                    """
                    await backend.execute_sparql_update(space_id, delete_slot_query)
                    
                    # Delete the Edge_hasKGSlot connecting frame to slot
                    delete_edge_query = f"""
                    PREFIX vital-core: <http://vital.ai/ontology/vital-core#>
                    DELETE {{
                        GRAPH <{graph_id}> {{
                            ?edge ?ep ?eo .
                        }}
                    }}
                    WHERE {{
                        GRAPH <{graph_id}> {{
                            ?edge vital-core:vitaltype <{self.haley_prefix}Edge_hasKGSlot> .
                            ?edge vital-core:hasEdgeSource <{frame_uri}> .
                            ?edge vital-core:hasEdgeDestination <{slot_uri}> .
                            ?edge ?ep ?eo .
                        }}
                    }}
                    """
                    await backend.execute_sparql_update(space_id, delete_edge_query)
                    
                    deleted_count += 1
                    self.logger.info(f"Deleted slot {slot_uri} and its edge from frame {frame_uri}")
                    
                except Exception as e:
                    self.logger.error(f"Error deleting slot {slot_uri}: {e}")
                    continue
            
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error deleting frame slots from backend: {e}")
            raise
    
    async def _store_frame_slots_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """
        Store VitalSigns slot objects and edges in backend using atomic update_quads.
        
        Queries existing triples for all subject URIs first, then uses a single
        transaction for delete + insert to prevent triple accumulation.
        """
        try:
            slot_uris = []
            for obj in objects:
                if isinstance(obj, KGSlot):
                    slot_uris.append(str(obj.URI))
            
            # Step 1: Build insert quads from VitalSigns objects (preserve RDFLib objects)
            triples = await asyncio.to_thread(GraphObject.to_triples_list, objects)
            insert_quads = [(str(s), str(p), o, graph_id) for s, p, o in triples]
            
            if not insert_quads:
                return slot_uris
            
            # Step 2: Subject-level delete + insert (safe path)
            subject_uris = list({str(obj.URI) for obj in objects
                                 if hasattr(obj, 'URI') and obj.URI})
            
            if hasattr(backend, 'update_subjects_graph'):
                await backend.update_subjects_graph(
                    space_id, graph_id, subject_uris, insert_quads)
            else:
                delete_quads = []
                if subject_uris:
                    subject_values = " ".join(f"<{uri}>" for uri in subject_uris)
                    query = f"""SELECT ?subject ?predicate ?object WHERE {{
                        GRAPH <{graph_id}> {{
                            VALUES ?subject {{ {subject_values} }}
                            ?subject ?predicate ?object .
                        }}
                    }}"""
                    results = await backend.execute_sparql_query(space_id, query)
                    
                    bindings = []
                    if isinstance(results, dict) and 'results' in results and isinstance(results['results'], dict):
                        bindings = results['results'].get('bindings', [])
                    elif isinstance(results, list):
                        bindings = results
                    
                    from vitalgraph.kg_impl.kgentity_frame_create_impl import _sparql_binding_to_rdflib
                    for row in bindings:
                        if isinstance(row, dict):
                            s = str(row['subject'].get('value', '')) if isinstance(row.get('subject'), dict) else str(row.get('subject', ''))
                            p = str(row['predicate'].get('value', '')) if isinstance(row.get('predicate'), dict) else str(row.get('predicate', ''))
                            o = _sparql_binding_to_rdflib(row.get('object', ''))
                            if s and p and o is not None:
                                delete_quads.append((s, p, o, graph_id))
                
                await backend.update_quads(space_id, graph_id, delete_quads, insert_quads)
            
            return slot_uris
            
        except Exception as e:
            self.logger.error(f"Error storing frame slots in backend: {e}")
            raise
    
    # Helper methods for frame query operations
    
    def _build_frame_query_sparql(self, graph_id: str, query_request: FrameQueryRequest) -> str:
        """Build SPARQL query based on frame query criteria."""
        # Start with basic frame selection
        where_clauses = [f"?frame a ?frameType ."]
        where_clauses.append(f"FILTER(STRSTARTS(STR(?frameType), \"{self.haley_prefix}KG\") && STRENDS(STR(?frameType), \"Frame\"))")
        
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
    
    async def _create_child_frames(
        self,
        space_id: str,
        graph_id: str,
        parent_frame_uri: str,
        frame_objects: List,
        operation_mode: str,
        current_user: Dict
    ) -> FrameCreateResponse:
        """Create child frames linked to parent frame using processor."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Delegate to hierarchical processor
            result = await self.frame_hierarchical_processor.create_child_frames(
                backend_adapter=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                parent_frame_uri=parent_frame_uri,
                child_frame_objects=frame_objects,
                operation_mode=operation_mode
            )
            
            if result.success:
                return FrameCreateResponse(
                    success=True,
                    message=result.message,
                    created_count=result.frame_count,
                    created_uris=result.created_uris,
                    frames_created=result.frame_count
                )
            else:
                return FrameCreateResponse(
                    success=False,
                    message=result.message,
                    created_count=0,
                    created_uris=[],
                    frames_created=0
                )
                
        except Exception as e:
            self.logger.error(f"Child frame creation failed: {e}", exc_info=True)
            return FrameCreateResponse(
                success=False,
                message=f"Child frame creation failed: {str(e)}",
                created_count=0,
                created_uris=[],
                frames_created=0
            )
    
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
                success=success,
                message="Frame graph deleted successfully" if success else "Frame graph deletion failed",
                deleted_count=1 if success else 0,
                frames_deleted=1 if success else 0
            )
            
        except Exception as e:
            self.logger.error(f"Frame graph deletion failed: {e}", exc_info=True)
            return FrameDeleteResponse(
                success=False,
                message=f"Frame graph deletion failed: {str(e)}",
                deleted_count=0,
                frames_deleted=0
            )
    
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
