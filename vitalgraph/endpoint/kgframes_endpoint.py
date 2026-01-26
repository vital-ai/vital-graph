"""
KG Frames REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing KG frames and their slots using JSON-LD 1.1 format.
KG frames represent structured knowledge frames with connected slot nodes and values.

Follows MockKGFramesEndpoint patterns with proper VitalSigns integration:
- Backend interface usage via SpaceBackendInterface
- VitalSigns graph objects conversion (KGFrame, KGSlot, Edge_hasKGSlot)
- Grouping URI management (frameGraphURI)
- Operation modes (CREATE, UPDATE, UPSERT)
- Complete sub-endpoint support
"""

import logging
from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel, Field
from enum import Enum

from ..model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from ..model.kgframes_model import (
    FramesResponse,
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
from ..kg_impl.kg_backend_utils import create_backend_adapter, FusekiPostgreSQLBackendAdapter

# Import JSON-LD utilities
from ..kg_impl.kg_jsonld_utils import KGJsonLdUtils


class OperationMode(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


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
        
        # Frame processor for entity frame operations (initialized when needed)
        self.frame_processor = None
        
        self._setup_routes()
    
    async def _get_backend_adapter(self, space_id: str):
        """Get backend adapter for the space."""
        space_record = self.space_manager.get_space(space_id)
        if not space_record:
            raise ValueError(f"Space not found: {space_id}")
        
        space_impl = space_record.space_impl
        
        # KGFrames endpoint uses direct backend storage - no processors needed
        backend = space_impl.get_db_space_impl()
        if not backend:
            raise ValueError(f"Backend not available for space: {space_id}")
        
        return FusekiPostgreSQLBackendAdapter(backend)
    
    def _jsonld_request_to_vitalsigns(self, document: JsonLdRequest) -> List:
        """Convert JsonLdRequest (JsonLdObject or JsonLdDocument) to VitalSigns objects."""
        from vital_ai_vitalsigns.vitalsigns import VitalSigns
        vs = VitalSigns()
        
        if isinstance(document, JsonLdObject):
            # Single object - wrap in document structure for from_jsonld_list
            jsonld_data = document.model_dump(by_alias=True)
            context = jsonld_data.pop('@context', {})
            wrapped_doc = {
                '@context': context,
                '@graph': [jsonld_data]
            }
            return vs.from_jsonld_list(wrapped_doc)
        else:
            # Already a JsonLdDocument
            return vs.from_jsonld_list(document.model_dump(by_alias=True))
    
    async def _create_frames(self, space_id: str, graph_id: str, document: JsonLdRequest, operation_mode: str):
        """Delegate frame creation to existing KGEntityFrameCreateProcessor."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # KGFrames endpoint uses direct backend storage - no entity processors needed
            
            # Convert JSON-LD to VitalSigns objects
            vitalsigns_objects = self._jsonld_request_to_vitalsigns(document)
            
            # KGFrames endpoint handles only frames and slots - no entity dependencies
            frame_objects = vitalsigns_objects
            result = await self._create_standalone_frames(
                backend_adapter, space_id, graph_id, frame_objects, operation_mode.upper()
            )
            
            return FrameCreateResponse(
                success=True,
                message=result.message,
                created_count=getattr(result, 'created_count', 0),
                created_uris=[str(uri) for uri in getattr(result, 'created_uris', [])],
                slots_created=0
            )
            
        except Exception as e:
            self.logger.error(f"Frame creation failed: {e}")
            return FrameCreateResponse(
                success=False,
                message=f"Frame creation failed: {str(e)}",
                created_count=0,
                created_uris=[],
                slots_created=0
            )
    
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
    
    async def _update_frames(self, space_id: str, graph_id: str, document: JsonLdRequest, operation_mode: str):
        """Update frames using direct backend storage - no entity dependencies."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Convert JSON-LD to VitalSigns objects
            vitalsigns_objects = self._jsonld_request_to_vitalsigns(document)
            
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
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Build SPARQL query for entity-associated frames
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
            
            # Execute query
            results = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Convert results to frames
            frames = await self._sparql_results_to_frames(backend, graph_id, results, space_id)
            
            # Convert to JSON-LD document
            frames_doc = self._frames_to_jsonld_document(frames)
            
            return FramesResponse(
                frames=frames_doc,
                total_count=len(frames),
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Entity frame retrieval failed: {e}")
            return FramesResponse(
                frames=JsonLdDocument(graph=[]),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    async def _delete_entities(self, space_id: str, graph_id: str, entity_uris: List[str]):
        """Delegate entity deletion (for test compatibility)."""
        return await self._delete_frames(space_id, graph_id, entity_uris)
    
    # Slot endpoint methods for /api/graphs/kgframes/kgslots
    
    async def _create_slots(self, space_id: str, graph_id: str, document: JsonLdRequest, operation_mode: str, parent_uri: Optional[str] = None, entity_uri: Optional[str] = None):
        """Delegate slot creation to KGSlotCreateProcessor."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Initialize slot create processor with backend
            if not self.slot_create_processor:
                self.slot_create_processor = KGSlotCreateProcessor(backend_adapter)
            
            # Convert JSON-LD to VitalSigns objects
            vitalsigns_objects = self._jsonld_request_to_vitalsigns(document)
            
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
    
    async def _update_slots(self, space_id: str, graph_id: str, document: JsonLdRequest, operation_mode: str, parent_uri: Optional[str] = None, entity_uri: Optional[str] = None):
        """Delegate slot updates to KGSlotUpdateProcessor."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Convert JSON-LD to VitalSigns objects
            vitalsigns_objects = self._jsonld_request_to_vitalsigns(document)
            
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
            
            # Build and execute SPARQL query to find slot URIs
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
            
            # Retrieve slot objects from backend
            slot_objects = []
            for slot_uri in slot_uris:
                try:
                    slot_obj = backend.get_object(slot_uri)
                    if slot_obj:
                        slot_objects.append(slot_obj)
                except Exception as e:
                    self.logger.warning(f"Failed to retrieve slot {slot_uri}: {e}")
            
            # Convert to JSON-LD document
            slots_doc = self._convert_objects_to_jsonld_document(slot_objects)
            
            # Get total count for pagination
            count_query = self._build_count_slots_query(backend, space_id, graph_id, frame_uri)
            count_result = backend.execute_sparql_query(count_query)
            total_count = 0
            
            if count_result and 'results' in count_result and 'bindings' in count_result['results']:
                bindings = count_result['results']['bindings']
                if bindings and 'count' in bindings[0]:
                    total_count = int(bindings[0]['count']['value'])
            
            self.logger.info(f"Listed {len(slot_objects)} slots (total: {total_count}) in graph '{graph_id}' in space '{space_id}'")
            
            return FramesResponse(
                frames=slots_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Slot listing failed: {e}")
            return FramesResponse(
                frames=JsonLdDocument(context={"@vocab": self.haley_prefix}, graph=[]),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    async def _get_slot_by_uri(self, space_id: str, graph_id: str, slot_uri: str, parent_uri: Optional[str] = None, entity_uri: Optional[str] = None):
        """Get single slot by URI."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Check if slot exists and retrieve
            # Additional filtering by parent_uri and entity_uri can be added here
            if await backend_adapter.object_exists(space_id, graph_id, slot_uri):
                # This would need actual slot retrieval logic with parent_uri/entity_uri filtering
                # For now, return basic response structure
                return FramesResponse(
                    frames=JsonLdDocument(context={"@vocab": self.haley_prefix}, graph=[]),
                    total_count=1,
                    page_size=1,
                    offset=0
                )
            else:
                return FramesResponse(
                    frames=JsonLdDocument(context={"@vocab": self.haley_prefix}, graph=[]),
                    total_count=0,
                    page_size=1,
                    offset=0
                )
            
        except Exception as e:
            self.logger.error(f"Slot retrieval failed: {e}")
            return FramesResponse(
                frames=JsonLdDocument(context={"@vocab": self.haley_prefix}, graph=[]),
                total_count=0,
                page_size=1,
                offset=0
            )
    
    def _setup_routes(self):
        """Setup FastAPI routes for KG frames management."""
        
        @self.router.get("/kgframes", response_model=Union[FramesResponse, FrameGraphResponse], tags=["KG Frames"])
        async def list_or_get_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of frames per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            search: Optional[str] = Query(None, description="Search text to find in frame properties"),
            uri: Optional[str] = Query(None, description="Single frame URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs"),
            include_frame_graph: bool = Query(False, description="If True, include complete frame graph with slots"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            List KG frames with pagination, or get specific frames by URI(s).
            
            - If uri is provided: returns single frame
            - If uri_list is provided: returns multiple frames  
            - Otherwise: returns paginated list of all frames
            - include_frame_graph: retrieves complete frame graphs with slots
            """
            
            # Handle single URI retrieval
            if uri:
                return await self._get_frame_by_uri(space_id, graph_id, uri, include_frame_graph, current_user)
            
            # Handle multiple URI retrieval
            if uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._get_frames_by_uris(space_id, graph_id, uris, include_frame_graph, current_user)
            
            # Handle paginated list of all frames
            return await self._list_frames(space_id, graph_id, page_size, offset, None, current_user)

        @self.router.post("/kgframes", response_model=Union[FrameCreateResponse, FrameUpdateResponse], tags=["KG Frames"])
        async def create_or_update_frames(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            operation_mode: str = Query("create", description="Operation mode: create, update, or upsert"),
            parent_uri: Optional[str] = Query(None, description="Parent URI for hierarchical relationships"),
            entity_uri: Optional[str] = Query(None, description="Entity URI for frame association"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Create or update KG frames with JSON-LD 1.1 format.
            
            Supports multiple operation modes:
            - create: Create new frames (default)
            - update: Update existing frames
            - upsert: Create or update frames
            """
            self.logger.info(f"🔍 ROUTE: POST /kgframes called with space_id={space_id}, graph_id={graph_id}, operation_mode={operation_mode}")
            self.logger.info(f"🔍 ROUTE: Request type: {type(request)}, entity_uri={entity_uri}, parent_uri={parent_uri}")
            
            # Log request structure for debugging
            if hasattr(request, 'model_dump'):
                request_dict = request.model_dump()
                self.logger.info(f"🔍 ROUTE: Request model_dump keys: {list(request_dict.keys()) if isinstance(request_dict, dict) else 'Not a dict'}")
            elif hasattr(request, '__dict__'):
                self.logger.info(f"🔍 ROUTE: Request __dict__ keys: {list(request.__dict__.keys())}")
            else:
                self.logger.info(f"🔍 ROUTE: Request str representation: {str(request)[:100]}...")
            
            try:
                return await self._create_or_update_frames(space_id, graph_id, request, operation_mode, parent_uri, entity_uri, current_user)
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
            return await self._query_frames(space_id, graph_id, query_request, current_user)
        
        @self.router.delete("/kgframes", response_model=FrameDeleteResponse, tags=["KG Frames"])
        async def delete_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            uri: Optional[str] = Query(None, description="Single frame URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete frames by URI or URI list.
            """
            if uri:
                return await self._delete_frame_by_uri(space_id, graph_id, uri, current_user)
            elif uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._delete_frames_by_uris(space_id, graph_id, uris, current_user)
            else:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
                    message="Either 'uri' or 'uri_list' parameter is required",
                    deleted_count=0,
                    deleted_uris=[]
                )
        
        # Frame-Slot Sub-Endpoint Operations (matching MockKGFramesEndpoint)
        
        @self.router.get("/kgframes/kgslots", response_model=FramesResponse, tags=["KG Frame Slots"])
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
            return await self._get_kgframes_with_slots(space_id, graph_id, frame_uri, page_size, offset, entity_uri, parent_uri, search, kGSlotType, current_user)
        
        @self.router.post("/kgframes/kgslots", response_model=Union[SlotCreateResponse, SlotUpdateResponse], tags=["KG Frame Slots"])
        async def create_or_update_frame_slots(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            frame_uri: str = Query(..., description="Frame URI to create/update slots for"),
            entity_uri: Optional[str] = Query(None, description="Entity URI for slot context"),
            parent_uri: Optional[str] = Query(None, description="Parent URI for slot hierarchy"),
            operation_mode: str = Query("create", description="Operation mode: create, update, or upsert"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Create or update slots for a specific frame using Edge_hasKGSlot relationships.
            Operation mode determines behavior: 'create' (fail if exists), 'update' (fail if not exists), 'upsert' (create or update).
            """
            if operation_mode == "update":
                return await self._update_frame_slots(space_id, graph_id, frame_uri, request, current_user)
            else:
                return await self._create_frame_slots(space_id, graph_id, frame_uri, request, operation_mode, current_user, entity_uri, parent_uri)
        
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
            slot_uri_list = [uri.strip() for uri in slot_uris.split(',') if uri.strip()]
            return await self._delete_frame_slots(space_id, graph_id, frame_uri, slot_uri_list, current_user)
    
    # Implementation methods following MockKGFramesEndpoint patterns with VitalSigns integration
    
    async def _list_frames(self, space_id: str, graph_id: str, page_size: int, offset: int, search: Optional[str], current_user: Dict) -> FramesResponse:
        """List KG frames with pagination using backend interface."""
        from ..model.kgframes_model import FramesResponse
        from ..model.jsonld_model import JsonLdDocument
        
        try:
            self.logger.info(f"Listing KGFrames in space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Build SPARQL query for listing frames
            sparql_query = self._build_list_frames_query(backend, space_id, graph_id, search, page_size, offset)
            
            # Execute query via backend interface
            results = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Convert results to VitalSigns frame objects
            frames = await self._sparql_results_to_frames(backend, graph_id, results, space_id)
            
            # Convert to JSON-LD document
            frames_doc = self._frames_to_jsonld_document(frames)
            
            # Get total count
            count_query = self._build_count_frames_query(backend, space_id, graph_id, search)
            count_results = await backend.execute_sparql_query(space_id, count_query)
            total_count = self._extract_count_from_results(count_results)
            
            return FramesResponse(
                frames=frames_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGFrames: {e}")
            return FramesResponse(
                frames=JsonLdDocument(graph=[]),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    async def _get_frame_by_uri(self, space_id: str, graph_id: str, uri: str, include_frame_graph: bool, current_user: Dict):
        """Get single frame by URI with optional complete graph."""
        from ..model.jsonld_model import JsonLdDocument
        from ..model.kgframes_model import FrameGraphResponse
        
        try:
            self.logger.info(f"🔍 Getting KGFrame {uri} from space {space_id}, graph {graph_id}, include_frame_graph={include_frame_graph}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                self.logger.warning(f"❌ Space not found: {space_id}")
                return FrameGraphResponse(
                    success=False,
                    message=f"Space '{space_id}' not found",
                    frame=JsonLdDocument(graph=[]),
                    complete_graph=None
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                self.logger.warning(f"❌ Backend not found for space: {space_id}")
                return FrameGraphResponse(
                    success=False,
                    message=f"Backend not found for space '{space_id}'",
                    frame=JsonLdDocument(graph=[]),
                    complete_graph=None
                )
            
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
            
            if not frames:
                # Return empty FrameGraphResponse for not found frames
                self.logger.info(f"📭 No frames found for URI: {uri}")
                return FrameGraphResponse(
                    success=False,
                    message=f"No frames found for URI: {uri}",
                    frame=JsonLdDocument(graph=[]),
                    complete_graph=None
                )
            
            # Convert to JSON-LD - use JsonLdObject for single frame, JsonLdDocument for multiple frames
            self.logger.debug(f"📄 Converting {len(frames)} frames to JSON-LD")
            
            # Get complete graph if requested
            complete_graph = None
            if include_frame_graph:
                self.logger.debug(f"🔍 Getting complete frame graph for URI: {uri}")
                complete_graph = await self._get_frame_graph(
                    space_id=space_id,
                    graph_id=graph_id,
                    frame_uri=uri,
                    current_user=current_user
                )
                self.logger.debug(f"✅ Complete graph retrieved with {len(complete_graph.graph) if complete_graph and complete_graph.graph else 0} objects")
            
            if len(frames) == 1:
                # Single frame - use JsonLdObject (JsonLdDocument requires 0 or 2+ objects)
                from ..model.jsonld_model import JsonLdObject
                frame_dict = frames[0].to_jsonld()
                frame_obj = JsonLdObject(**frame_dict)
                self.logger.debug(f"✅ Created JsonLdObject for single frame")
                
                return FrameGraphResponse(
                    success=True,
                    message=f"Successfully retrieved frame for URI: {uri}",
                    frame=frame_obj,
                    complete_graph=complete_graph
                )
            else:
                # Multiple frames (0 or 2+) - use JsonLdDocument
                frame_doc = self._frames_to_jsonld_document(frames)
                self.logger.debug(f"✅ JSON-LD document created with {len(frame_doc.graph) if frame_doc.graph else 0} graph items")
                
                return FrameGraphResponse(
                    success=True,
                    message=f"Successfully retrieved frame for URI: {uri}",
                    frame=frame_doc,
                    complete_graph=complete_graph if complete_graph else frame_doc
                )
            
        except Exception as e:
            self.logger.error(f"❌ Error getting KGFrame {uri}: {e}")
            self.logger.error(f"❌ Exception type: {type(e).__name__}")
            import traceback
            self.logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            return FrameGraphResponse(
                success=False,
                message=f"Error retrieving frame for URI {uri}: {str(e)}",
                frame=JsonLdDocument(graph=[]),
                complete_graph=None
            )
    
    async def _get_kgframes_with_slots(self, space_id: str, graph_id: str, frame_uri: Optional[str], page_size: int, offset: int, entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str], current_user: Dict) -> FramesResponse:
        """Get frames with their associated slots using pagination."""
        from ..model.kgframes_model import FramesResponse
        from ..model.jsonld_model import JsonLdDocument
        
        try:
            self.logger.info(f"Getting KGFrames with slots in space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Build SPARQL query for listing frames with slots
            sparql_query = self._build_frames_with_slots_query(backend, space_id, graph_id, frame_uri, entity_uri, parent_uri, search, kGSlotType, page_size, offset)
            
            # Execute query via backend interface
            results = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Convert results to VitalSigns frame objects with slots
            frames = await self._sparql_results_to_frames_with_slots(backend, graph_id, results, space_id)
            
            # Convert to JSON-LD document
            frames_doc = self._frames_to_jsonld_document(frames)
            
            # Get total count
            count_query = self._build_count_frames_with_slots_query(backend, space_id, graph_id, frame_uri, entity_uri, parent_uri, search, kGSlotType)
            count_results = await backend.execute_sparql_query(space_id, count_query)
            total_count = self._extract_count_from_results(count_results)
            
            return FramesResponse(
                frames=frames_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error getting KGFrames with slots: {e}")
            return FramesResponse(
                frames=JsonLdDocument(graph=[]),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    def _build_frames_with_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str], entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str], page_size: int, offset: int) -> str:
        """Build SPARQL query for frames with slots."""
        # For now, use the same query as regular frames listing
        return self._build_list_frames_query(backend, space_id, graph_id, search, page_size, offset)
    
    def _build_count_frames_with_slots_query(self, backend, space_id: str, graph_id: str, frame_uri: Optional[str], entity_uri: Optional[str], parent_uri: Optional[str], search: Optional[str], kGSlotType: Optional[str]) -> str:
        """Build SPARQL count query for frames with slots."""
        # For now, use the same query as regular frames count
        return self._build_count_frames_query(backend, space_id, graph_id, search)
    
    async def _sparql_results_to_frames_with_slots(self, backend, graph_id: str, results, space_id: str):
        """Convert SPARQL results to VitalSigns frame objects with slots."""
        # For now, use the same conversion as regular frames
        return await self._sparql_results_to_frames(backend, graph_id, results, space_id)
        
    async def _get_frames_by_uris(self, space_id: str, graph_id: str, frame_uris: List[str], include_frame_graph: bool = False, current_user: Dict = None) -> FramesResponse:
        """Get multiple frames by URI list."""
        from ..model.jsonld_model import JsonLdDocument
        
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Retrieve frames for each URI
            all_objects = []
            for frame_uri in frame_uris:
                try:
                    result = await backend_adapter.get_object(space_id, graph_id, frame_uri)
                    # get_object returns BackendOperationResult with objects attribute
                    if result and hasattr(result, 'objects') and result.objects:
                        all_objects.extend(result.objects)
                except Exception as e:
                    self.logger.warning(f"Failed to retrieve frame {frame_uri}: {e}")
            
            # Convert VitalSigns objects to JSON-LD document
            if all_objects:
                from vital_ai_vitalsigns.vitalsigns import VitalSigns
                vs = VitalSigns()
                jsonld_dict = vs.to_jsonld_list(all_objects)
                jsonld_doc = JsonLdDocument(context=jsonld_dict.get('@context', {"@vocab": self.haley_prefix}), graph=jsonld_dict.get('@graph', []))
            else:
                jsonld_doc = JsonLdDocument(context={"@vocab": self.haley_prefix}, graph=[])
            
            return FramesResponse(
                frames=jsonld_doc,
                total_count=len(all_objects),
                page_size=len(frame_uris),
                offset=0
            )
            
        except Exception as e:
            self.logger.error(f"Frame retrieval by URIs failed: {e}")
            return FramesResponse(
                frames=JsonLdDocument(context={"@vocab": self.haley_prefix}, graph=[]),
                total_count=0,
                page_size=len(frame_uris) if frame_uris else 0,
                offset=0
            )
    
    async def _create_or_update_frames(self, space_id: str, graph_id: str, request: Union[JsonLdObject, JsonLdDocument], operation_mode: str, parent_uri: Optional[str], entity_uri: Optional[str], current_user: Dict):
        """Create, update, or upsert frames with VitalSigns integration."""
        from ..model.kgframes_model import FrameCreateResponse, FrameUpdateResponse
        
        # Convert string operation_mode to enum
        try:
            op_mode = OperationMode(operation_mode.lower())
        except ValueError:
            op_mode = OperationMode.CREATE
        
        try:
            self.logger.info(f"🔍 Processing frames with operation_mode {op_mode} in space {space_id}, graph {graph_id}")
            self.logger.info(f"🔍 Request type: {type(request)}")
            self.logger.info(f"🔍 Request content preview: {str(request)[:200]}...")
            if entity_uri:
                self.logger.info(f"🔍 Entity URI: {entity_uri}")
            if parent_uri:
                self.logger.info(f"🔍 Parent URI: {parent_uri}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                if op_mode == OperationMode.CREATE:
                    return FrameCreateResponse(
                        success=False,
                        message=f"Space {space_id} not found",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    return FrameUpdateResponse(
                        success=False,
                        message=f"Space {space_id} not found",
                        updated_uri=""
                    )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                if op_mode == OperationMode.CREATE:
                    return FrameCreateResponse(
                        success=False,
                        message="Backend implementation not available",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    return FrameUpdateResponse(
                        success=False,
                        message="Backend implementation not available",
                        updated_uri=""
                    )
            
            # Wrap backend with adapter to provide update_quads method for UPDATE operations
            from ..kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter
            backend = FusekiPostgreSQLBackendAdapter(backend_impl)
            
            # Handle JsonLdObject and JsonLdDocument separately - do not mix them
            if isinstance(request, JsonLdObject):
                # Convert single JsonLdObject to VitalSigns objects using VitalSigns utilities
                from vital_ai_vitalsigns.vitalsigns import VitalSigns
                vs = VitalSigns()
                jsonld_dict = request.model_dump(by_alias=True)
                vitalsigns_obj = vs.from_jsonld(jsonld_dict)
                vitalsigns_objects = [vitalsigns_obj] if not isinstance(vitalsigns_obj, list) else vitalsigns_obj
            else:
                # Handle JsonLdDocument
                vitalsigns_objects = self._jsonld_document_to_vitalsigns_objects(request)
            
            # Extract frames and validate
            frames = [obj for obj in vitalsigns_objects if isinstance(obj, KGFrame)]
            if not frames:
                if op_mode == OperationMode.CREATE:
                    return FrameCreateResponse(
                        success=False,
                        message="No valid KGFrame objects found in request",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    return FrameUpdateResponse(
                        success=False,
                        message="No valid KGFrame objects found in request",
                        updated_uri=""
                    )
            
            # Set grouping URIs on frames
            effective_parent_uri = entity_uri if entity_uri else parent_uri
            self._set_frame_grouping_uris(frames, graph_id, effective_parent_uri)
            
            # Validate frame structure
            validation_result = self._validate_frame_structure(vitalsigns_objects)
            if not validation_result.get("valid", False):
                if op_mode == OperationMode.CREATE:
                    return FrameCreateResponse(
                        success=False,
                        message=f"Frame validation failed: {validation_result.get('error')}",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    return FrameUpdateResponse(
                        success=False,
                        message=f"Frame validation failed: {validation_result.get('error')}",
                        updated_uri=""
                    )
            
            # Handle parent relationships and create edges
            enhanced_objects = await self._handle_parent_relationships(backend, space_id, graph_id, frames, vitalsigns_objects, effective_parent_uri)
            
            # Execute operation based on mode
            if op_mode == OperationMode.CREATE:
                return await self._handle_create_mode(backend, space_id, graph_id, frames, enhanced_objects, effective_parent_uri)
            elif op_mode == OperationMode.UPDATE:
                return await self._handle_update_mode(backend, space_id, graph_id, frames, enhanced_objects, effective_parent_uri)
            elif op_mode == OperationMode.UPSERT:
                return await self._handle_upsert_mode(backend, space_id, graph_id, frames, enhanced_objects, effective_parent_uri)
            else:
                return FrameCreateResponse(
                    success=False,
                    message=f"Invalid operation_mode: {op_mode}",
                    created_count=0,
                    created_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error processing frames: {e}")
            return FrameCreateResponse(
                success=False,
                message=f"Failed to process frames: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _query_frames(self, space_id: str, graph_id: str, query_request: FrameQueryRequest, current_user: Dict) -> FrameQueryResponse:
        """Query frames using enhanced criteria-based search with sorting support."""
        from ..model.kgframes_model import FrameQueryResponse
        from ..model.jsonld_model import JsonLdDocument
        
        try:
            self.logger.info(f"Querying frames in space {space_id}, graph {graph_id} with criteria: {query_request}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return FrameQueryResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return FrameQueryResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0
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
    
    async def _delete_frame_by_uri(self, space_id: str, graph_id: str, uri: str, current_user: Dict) -> FrameDeleteResponse:
        """Delete single frame by URI."""
        from ..model.kgframes_model import FrameDeleteResponse
        
        try:
            self.logger.info(f"Deleting frame {uri} from space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
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
            from ..kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter
            backend = FusekiPostgreSQLBackendAdapter(backend_impl)
            
            # Check if frame exists
            if not await self._frame_exists_in_backend(backend, space_id, graph_id, uri):
                return FrameDeleteResponse(
                    success=False,
                    message=f"Frame {uri} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Delete frame and associated objects
            success = await self._delete_frame_from_backend(backend, space_id, graph_id, uri)
            
            if success:
                return FrameDeleteResponse(
                    message=f"Successfully deleted frame {uri}",
                    deleted_count=1,
                    deleted_uris=[uri]
                )
            else:
                return FrameDeleteResponse(
                    success=False,
                    message=f"Failed to delete frame {uri}",
                    deleted_count=0,
                    deleted_uris=[]
                )
                
        except Exception as e:
            self.logger.error(f"Error deleting frame: {e}")
            return FrameDeleteResponse(
                success=False,
                message=f"Failed to delete frame: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _delete_frames_by_uris(self, space_id: str, graph_id: str, uris: List[str], current_user: Dict) -> FrameDeleteResponse:
        """Delete multiple frames by URI list."""
        from ..model.kgframes_model import FrameDeleteResponse
        
        try:
            self.logger.info(f"Deleting {len(uris)} frames from space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
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
            from ..kg_impl.kg_backend_utils import FusekiPostgreSQLBackendAdapter
            backend = FusekiPostgreSQLBackendAdapter(backend_impl)
            
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
            
            return FrameDeleteResponse(
                message=f"Successfully deleted {len(deleted_uris)} of {len(uris)} frames",
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
    
    async def _get_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, kGSlotType: Optional[str], current_user: Dict) -> JsonLdDocument:
        """Get slots for a specific frame using Edge_hasKGSlot relationships."""
        from ..model.jsonld_model import JsonLdDocument
        
        try:
            self.logger.info(f"Getting slots for frame {frame_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return JsonLdDocument(graph=[])
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return JsonLdDocument(graph=[])
            
            # Build SPARQL query to get slots connected to this frame
            sparql_query = self._build_get_frame_slots_query(graph_id, frame_uri, kGSlotType)
            
            # Execute query via backend interface
            results = await backend.execute_sparql_query(space_id, sparql_query)
            
            # Convert results to VitalSigns slot objects
            slots = await self._sparql_results_to_slots(backend, graph_id, results)
            
            # Convert to JSON-LD document
            slots_doc = self._slots_to_jsonld_document(slots)
            
            return slots_doc
            
        except Exception as e:
            self.logger.error(f"Error getting frame slots: {e}")
            return JsonLdDocument(graph=[])
    
    async def _create_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, request: JsonLdDocument, operation_mode: OperationMode, current_user: Dict, entity_uri: Optional[str] = None, parent_uri: Optional[str] = None) -> SlotCreateResponse:
        """Create slots for a specific frame using Edge_hasKGSlot relationships."""
        from ..model.kgframes_model import SlotCreateResponse
        
        try:
            self.logger.info(f"Creating slots for frame {frame_uri} with operation_mode {operation_mode}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return SlotCreateResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    created_count=0,
                    created_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return SlotCreateResponse(
                    success=False,
                    message="Backend implementation not available",
                    created_count=0,
                    created_uris=[]
                )
            
            # Validate that frame exists
            if not await self._frame_exists_in_backend(backend, space_id, graph_id, frame_uri):
                return SlotCreateResponse(
                    success=False,
                    message=f"Frame {frame_uri} not found",
                    created_count=0,
                    created_uris=[]
                )
            
            # Convert JSON-LD to VitalSigns objects
            vitalsigns_objects = self._jsonld_document_to_vitalsigns_objects(request)
            
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
    
    async def _update_frame_slots(self, space_id: str, graph_id: str, frame_uri: str, request: JsonLdDocument, current_user: Dict) -> SlotUpdateResponse:
        """Update slots for a specific frame using Edge_hasKGSlot relationships."""
        from ..model.kgframes_model import SlotUpdateResponse
        
        try:
            self.logger.info(f"Updating slots for frame {frame_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return SlotUpdateResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    updated_count=0,
                    updated_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return SlotUpdateResponse(
                    success=False,
                    message="Backend implementation not available",
                    updated_count=0,
                    updated_uris=[]
                )
            
            # Validate that frame exists
            if not await self._frame_exists_in_backend(backend, space_id, graph_id, frame_uri):
                return SlotUpdateResponse(
                    success=False,
                    message=f"Frame {frame_uri} not found",
                    updated_count=0,
                    updated_uris=[]
                )
            
            # Convert JSON-LD to VitalSigns objects
            vitalsigns_objects = self._jsonld_document_to_vitalsigns_objects(request)
            
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
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return SlotDeleteResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return SlotDeleteResponse(
                    success=False,
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
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
            
            return SlotDeleteResponse(
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
    
    def _build_list_frames_query(self, backend, space_id: str, graph_id: str, search: Optional[str], page_size: int, offset: int) -> str:
        """Build SPARQL query for listing frame subjects by finding objects with frameGraphURI property."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id
            
        search_filter = ""
        if search:
            # Search using actual KGFrame properties from schema
            # hasName: http://vital.ai/ontology/vital-core#hasName
            # hasKGraphDescription: http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription
            search_filter = f"""
            OPTIONAL {{ ?frame <{self.vital_prefix}hasName> ?name }}
            OPTIONAL {{ ?frame <{self.haley_prefix}hasKGraphDescription> ?description }}
            FILTER(
                CONTAINS(LCASE(STR(?name)), LCASE("{search}")) ||
                CONTAINS(LCASE(STR(?description)), LCASE("{search}")) ||
                CONTAINS(LCASE(STR(?frame)), LCASE("{search}"))
            )
            """
        
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT DISTINCT ?frame WHERE {{
            GRAPH <{full_graph_uri}> {{
                # Find objects that have hasFrameGraphURI property (these are frame objects)
                ?frame haley:hasFrameGraphURI ?frameGraphURI .
                ?frame a haley:KGFrame .
                {search_filter}
            }}
        }}
        ORDER BY ?frame
        LIMIT {page_size}
        OFFSET {offset}
        """
    
    def _build_count_frames_query(self, backend, space_id: str, graph_id: str, search: Optional[str]) -> str:
        """Build SPARQL count query for frames by finding objects with frameGraphURI property."""
        # Get the proper space-specific graph URI
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id
            
        return f"""
        PREFIX haley: <{self.haley_prefix}>
        PREFIX vital: <{self.vital_prefix}>
        
        SELECT (COUNT(DISTINCT ?frame) as ?count) WHERE {{
            GRAPH <{full_graph_uri}> {{
                # Find objects that have hasFrameGraphURI property (these are frame objects)
                ?frame haley:hasFrameGraphURI ?frameGraphURI .
                ?frame a haley:KGFrame .
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
            frames = self._convert_triples_to_vitalsigns_frames(triples)
            self.logger.debug(f"🔄 Converted to {len(frames) if frames else 0} VitalSigns frames")
            
            return frames
            
        except Exception as e:
            self.logger.error(f"Error converting SPARQL results to frames: {e}", exc_info=True)
            return []
    
    def _frames_to_jsonld_document(self, frames: List[KGFrame]) -> JsonLdDocument:
        """Convert frame objects to JSON-LD document."""
        try:
            self.logger.debug(f"📄 Converting {len(frames) if frames else 0} frames to JSON-LD document")
            if not frames:
                self.logger.debug(f"📄 No frames to convert, returning empty document")
                return JsonLdDocument(
                    context={"@vocab": self.haley_prefix},
                    graph=[]
                )
            
            # Convert VitalSigns objects to JSON-LD using native functionality
            jsonld_objects = []
            for i, frame in enumerate(frames):
                try:
                    self.logger.debug(f"📄 Converting frame {i+1}/{len(frames)}: {frame.URI}")
                    # Use VitalSigns native JSON-LD conversion
                    frame_dict = frame.to_jsonld()
                    self.logger.debug(f"📄 Frame dict keys: {list(frame_dict.keys()) if frame_dict else 'None'}")
                    jsonld_objects.append(frame_dict)
                except Exception as e:
                    self.logger.warning(f"Error converting frame {frame.URI} to JSON-LD: {e}")
                    import traceback
                    self.logger.warning(f"Traceback: {traceback.format_exc()}")
                    continue
            
            self.logger.debug(f"📄 Successfully converted {len(jsonld_objects)} frames to JSON-LD")
            return JsonLdDocument(
                context={"@vocab": self.haley_prefix},
                graph=jsonld_objects
            )
            
        except Exception as e:
            self.logger.error(f"Error converting frames to JSON-LD document: {e}")
            return JsonLdDocument(
                context={"@vocab": self.haley_prefix},
                graph=[]
            )
    
    def _extract_count_from_results(self, count_results) -> int:
        """Extract count from SPARQL count query results."""
        try:
            # Handle different result formats
            if isinstance(count_results, dict):
                if count_results.get("bindings"):
                    for binding in count_results["bindings"]:
                        count_value = binding.get("count", {}).get("value", "0")
                        return int(count_value)
            elif isinstance(count_results, list):
                # Handle list format results
                for item in count_results:
                    if isinstance(item, dict) and "count" in item:
                        return int(item["count"].get("value", "0"))
            return 0
        except Exception as e:
            self.logger.warning(f"Error extracting count from results: {e}")
            return 0
    
    # Helper methods for VitalSigns integration and frame operations
    

    def _jsonld_document_to_vitalsigns_objects(self, jsonld_doc: JsonLdDocument) -> List[GraphObject]:
        """Convert JSON-LD document to VitalSigns objects."""
        try:
            # Convert to dict format for VitalSigns processing
            jsonld_dict = jsonld_doc.model_dump(by_alias=True)
            
            # Create VitalSigns instance
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vs = VitalSigns()
            
            # Use VitalSigns native JSON-LD conversion
            if '@graph' in jsonld_dict:
                vitalsigns_objects = vs.from_jsonld_list(jsonld_dict)
            else:
                vitalsigns_obj = vs.from_jsonld(jsonld_dict)
                # Ensure we always return a list
                vitalsigns_objects = [vitalsigns_obj] if not isinstance(vitalsigns_obj, list) else vitalsigns_obj
            
            return vitalsigns_objects
            
        except Exception as e:
            self.logger.error(f"Error converting JSON-LD to VitalSigns objects: {e}")
            return []  # Return empty list for invalid JSON-LD format
    
    def _set_frame_grouping_uris(self, frames: List[KGFrame], graph_id: str, parent_uri: Optional[str]):
        """Set grouping URIs on frame objects following MockKGFramesEndpoint patterns."""
        for frame in frames:
            if isinstance(frame, KGFrame):
                # Set frameGraphURI for frame-level grouping - should be the frame URI itself
                if hasattr(frame, 'URI') and frame.URI:
                    # Cast URI property to get actual string value
                    frame_uri_str = str(frame.URI)
                    frame.frameGraphURI = frame_uri_str
                
                # Set kGGraphURI for entity-level grouping (if parent provided)
                if parent_uri:
                    frame.kGGraphURI = parent_uri
                else:
                    # Use frame URI as fallback for kGGraphURI
                    frame_uri_str = str(frame.URI)
                    frame.kGGraphURI = frame_uri_str
    
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
        """Handle CREATE mode: verify frames dont exist, then create using atomic processor."""
        try:
            # Initialize frame processor if needed
            if not self.frame_processor:
                from ..kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor
                self.frame_processor = KGEntityFrameCreateProcessor()
            
            # Use atomic frame processor for CREATE mode
            # Extract entity URI from parent_uri or first entity in objects
            entity_uri = parent_uri
            if not entity_uri:
                # Try to find entity URI from objects
                for obj in objects:
                    if hasattr(obj, 'kGGraphURI') and obj.kGGraphURI:
                        entity_uri = str(obj.kGGraphURI)
                        break
            
            if not entity_uri:
                return FrameCreateResponse(
                    success=False,
                    message="Entity URI required for frame creation",
                    created_count=0,
                    created_uris=[]
                )
            
            result = await self.frame_processor.create_entity_frame(
                backend_adapter=backend,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_objects=objects,
                operation_mode="CREATE"
            )
            
            if not result.success:
                return FrameCreateResponse(
                    success=False,
                    message=result.message,
                    created_count=0,
                    created_uris=[]
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
                slots_created=slots_count
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
        """Handle UPDATE mode: verify frames exist, then update using atomic processor."""
        try:
            # Use atomic frame processor for UPDATE mode
            # Extract entity URI from parent_uri or first entity in objects
            entity_uri = parent_uri
            if not entity_uri:
                # Try to find entity URI from objects
                for obj in objects:
                    if hasattr(obj, 'kGGraphURI') and obj.kGGraphURI:
                        entity_uri = str(obj.kGGraphURI)
                        break
            
            if not entity_uri:
                return FrameUpdateResponse(
                success=False,
                message="Entity URI required for frame update",
                updated_uri=""
            )
            
            result = await self.frame_processor.create_entity_frame(
                backend_adapter=backend,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_objects=objects,
                operation_mode="UPDATE"
            )
            
            if not result.success:
                return FrameUpdateResponse(
                success=False,
                message=result.message,
                updated_uri=""
            )
            
            updated_uris = result.created_uris
            
            return FrameUpdateResponse(
                success=True,
                message=f"Successfully updated {len(updated_uris)} frames",
                updated_uri=updated_uris[0] if updated_uris else "unknown",
                updated_count=len(updated_uris),
                frames_updated=len(updated_uris)
            )
            
        except Exception as e:
            self.logger.error(f"Error in UPDATE mode: {e}")
            return FrameUpdateResponse(
                success=False,
                message=f"Update operation failed: {str(e)}",
                updated_uri=""
            )
    
    async def _handle_upsert_mode(self, backend, space_id: str, graph_id: str, frames: List[KGFrame], objects: List[GraphObject], parent_uri: Optional[str]):
        """Handle UPSERT mode: create or update frames as needed using atomic processor."""
        try:
            # Use atomic frame processor for UPSERT mode
            # Extract entity URI from parent_uri or first entity in objects
            entity_uri = parent_uri
            if not entity_uri:
                # Try to find entity URI from objects
                for obj in objects:
                    if hasattr(obj, 'kGGraphURI') and obj.kGGraphURI:
                        entity_uri = str(obj.kGGraphURI)
                        break
            
            if not entity_uri:
                return FrameCreateResponse(
                    success=False,
                    message="Entity URI required for frame upsert",
                    created_count=0,
                    created_uris=[]
                )
            
            result = await self.frame_processor.create_entity_frame(
                backend_adapter=backend,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_objects=objects,
                operation_mode=OperationMode.UPSERT
            )
            
            if not result.success:
                return FrameCreateResponse(
                    success=False,
                    message=result.message,
                    created_count=0,
                    created_uris=[]
                )
            
            upserted_uris = result.created_uris
            
            return FrameCreateResponse(
                success=True,
                message=f"Successfully upserted {len(upserted_uris)} frames",
                created_count=len(upserted_uris),
                created_uris=upserted_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error in UPSERT mode: {e}")
            return FrameCreateResponse(
                success=False,
                message=f"Upsert operation failed: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _frame_exists_in_backend(self, backend, space_id: str, graph_id: str, frame_uri: str) -> bool:
        """Check if frame exists in backend."""
        try:
            # Use SELECT query instead of ASK to check existence
            # ASK queries are being executed as SELECT and return results array
            query = f"""
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> a <{self.haley_prefix}KGFrame> .
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
        """Store VitalSigns objects in backend via triples."""
        try:
            # Convert objects to triples
            all_triples = []
            frame_uris = []
            
            for obj in objects:
                if isinstance(obj, KGFrame):
                    # Cast URI property to get actual string value
                    frame_uris.append(str(obj.URI))
                
                # Convert to triples using VitalSigns
                triples = obj.to_triples()
                all_triples.extend(triples)
            
            # Build SPARQL INSERT query
            if all_triples:
                # Format triple components based on RDFLib object types
                from rdflib import URIRef, Literal, BNode
                triple_statements = []
                for t in all_triples:
                    subject = str(t.subject)
                    predicate = str(t.predicate)
                    
                    # Format object based on its RDFLib type
                    if isinstance(t.object, Literal):
                        if t.object.datatype:
                            obj_str = f'"{t.object}"^^<{t.object.datatype}>'
                        elif t.object.language:
                            obj_str = f'"{t.object}"@{t.object.language}'
                        else:
                            obj_str = f'"{t.object}"'
                    elif isinstance(t.object, URIRef):
                        obj_str = f"<{t.object}>"
                    elif isinstance(t.object, BNode):
                        obj_str = f"_:{t.object}"
                    else:
                        # Fallback for strings
                        obj_str = f'"{t.object}"'
                    
                    triple_statements.append(f"<{subject}> <{predicate}> {obj_str}")
                
                triples_str = " .\n    ".join(triple_statements)
                insert_query = f"""
                INSERT DATA {{
                    GRAPH <{graph_id}> {{
                        {triples_str} .
                    }}
                }}
                """
                await backend.execute_sparql_update(insert_query)
            
            return frame_uris
            
        except Exception as e:
            self.logger.error(f"Error storing frames in backend: {e}")
            raise
    
    async def _update_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """Update VitalSigns objects in backend via triples."""
        try:
            frame_uris = []
            
            for obj in objects:
                if isinstance(obj, KGFrame):
                    # Cast URI property to get actual string value
                    frame_uri = str(obj.URI)
                    frame_uris.append(frame_uri)
                    
                    # Delete existing frame triples
                    delete_query = f"""
                    DELETE WHERE {{
                        GRAPH <{graph_id}> {{
                            <{frame_uri}> ?p ?o .
                        }}
                    }}
                    """
                    await backend.execute_sparql_update(delete_query)
            
            # Insert updated frames
            await self._store_frames_in_backend(backend, space_id, graph_id, objects)
            
            return frame_uris
            
        except Exception as e:
            self.logger.error(f"Error updating frames in backend: {e}")
            raise
    
    async def _upsert_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """Upsert VitalSigns objects in backend via triples."""
        try:
            # For upsert, we delete existing and insert new (same as update)
            return await self._update_frames_in_backend(backend, space_id, graph_id, objects)
            
        except Exception as e:
            self.logger.error(f"Error upserting frames in backend: {e}")
            raise
    
    async def _delete_frame_from_backend(self, backend, space_id: str, graph_id: str, frame_uri: str) -> bool:
        """Delete frame and associated objects from backend."""
        try:
            # Delete frame and all its properties
            delete_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    <{frame_uri}> ?p ?o .
                }}
            }}
            """
            await backend.execute_sparql_update(space_id, delete_query)
            
            # Also delete any slots connected to this frame
            delete_slots_query = f"""
            DELETE WHERE {{
                GRAPH <{graph_id}> {{
                    ?edge a <{self.haley_prefix}Edge_hasKGSlot> ;
                          <{self.vital_prefix}hasEdgeSource> <{frame_uri}> ;
                          <{self.vital_prefix}hasEdgeDestination> ?slot .
                    ?slot ?p ?o .
                    ?edge ?ep ?eo .
                }}
            }}
            """
            await backend.execute_sparql_update(space_id, delete_slots_query)
            
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
                        
                        if subject and predicate and obj:
                            all_triples.append({
                                "subject": subject,
                                "predicate": predicate,
                                "object": obj
                            })
            
            return all_triples
            
        except Exception as e:
            self.logger.error(f"Error getting triples for subjects: {e}")
            return []
    
    def _convert_triples_to_vitalsigns_frames(self, triples: List[Dict[str, str]]) -> List[KGFrame]:
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
            all_objects = vs.from_triples_list(triples_generator())
            
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
    
    async def _update_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """Update VitalSigns objects in backend via triples."""
        try:
            frame_uris = []
            
            for obj in objects:
                if isinstance(obj, KGFrame):
                    # Cast URI property to get actual string value
                    frame_uri = str(obj.URI)
                    frame_uris.append(frame_uri)
                    
                    # Delete existing frame triples
                    delete_query = f"""
                    DELETE WHERE {{
                        GRAPH <{graph_id}> {{
                            <{frame_uri}> ?p ?o .
                        }}
                    }}
                    """
                    await backend.execute_sparql_update(delete_query)
            
            # Insert updated frames
            await self._store_frames_in_backend(backend, space_id, graph_id, objects)
            
            return frame_uris
            
        except Exception as e:
            self.logger.error(f"Error updating frames in backend: {e}")
            raise

    async def _upsert_frames_in_backend(self, backend, space_id: str, graph_id: str, objects: List[GraphObject]) -> List[str]:
        """Upsert VitalSigns objects in backend via triples."""
        try:
            # For upsert, we delete existing and insert new (same as update)
            return await self._update_frames_in_backend(backend, space_id, graph_id, objects)
            
        except Exception as e:
            self.logger.error(f"Error upserting frames in backend: {e}")
            raise

    # Removed duplicate _delete_frame_from_backend method - using the implementation above
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
            if entity_result and entity_result.get("boolean", False):
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
            if frame_result and frame_result.get("boolean", False):
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
            all_objects = self._convert_triples_to_vitalsigns_objects(triples)
            
            # Filter for slot objects
            for obj in all_objects:
                if isinstance(obj, KGSlot):
                    slots.append(obj)
            
            return slots
            
        except Exception as e:
            self.logger.error(f"Error converting SPARQL results to slots: {e}")
            return []
    
    def _convert_triples_to_vitalsigns_objects(self, triples: List[Dict[str, str]]) -> List[GraphObject]:
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
            all_objects = vs.from_triples_list(triples_generator())
            
            return all_objects
            
        except Exception as e:
            self.logger.error(f"Error converting triples to VitalSigns objects: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
    def _slots_to_jsonld_document(self, slots: List[KGSlot]) -> JsonLdDocument:
        """Convert slot objects to JSON-LD document."""
        try:
            if not slots:
                return JsonLdDocument(
                    context={"@vocab": self.haley_prefix},
                    graph=[]
                )
            
            # Convert VitalSigns objects to JSON-LD using native functionality
            jsonld_objects = []
            for slot in slots:
                try:
                    # Use VitalSigns native JSON-LD conversion
                    slot_dict = slot.to_jsonld()
                    jsonld_objects.append(slot_dict)
                except Exception as e:
                    self.logger.warning(f"Error converting slot {str(slot.URI)} to JSON-LD: {e}")
                    continue
            
            return JsonLdDocument(
                context={"@vocab": self.haley_prefix},
                graph=jsonld_objects
            )
            
        except Exception as e:
            self.logger.error(f"Error converting slots to JSON-LD document: {e}")
            return JsonLdDocument(
                context={"@vocab": self.haley_prefix},
                graph=[]
            )
    
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
            # Use SELECT query instead of ASK to check existence
            # ASK queries are being executed as SELECT and return results array
            query = f"""
            SELECT ?s WHERE {{
                GRAPH <{graph_id}> {{
                    <{slot_uri}> a ?type .
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
            ASK {{
                GRAPH <{graph_id}> {{
                    ?edge a <{self.haley_prefix}Edge_hasKGSlot> ;
                          <{self.vital_prefix}hasEdgeSource> <{frame_uri}> ;
                          <{self.vital_prefix}hasEdgeDestination> <{slot_uri}> .
                }}
            }}
            """
            result = await backend.execute_sparql_query(space_id, query)
            return result.get("boolean", False) if result else False
            
        except Exception as e:
            self.logger.error(f"Error checking slot-frame connection: {e}")
            return False
    
    async def _update_frame_slots_in_backend(self, backend, space_id: str, graph_id: str, slots: List[KGSlot]) -> List[str]:
        """Update VitalSigns slot objects in backend via SPARQL (coordinates Fuseki + PostgreSQL)."""
        try:
            slot_uris = []
            
            # First, delete existing slot triples using SPARQL
            # The dual-write coordinator will apply this to both Fuseki and PostgreSQL
            for slot in slots:
                slot_uri = str(slot.URI)
                slot_uris.append(slot_uri)
                
                # Delete existing slot data via SPARQL
                delete_query = f"""
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
                await backend.execute_sparql_update(space_id, delete_query)
            
            # Then, insert updated slot data using SPARQL
            all_triples = []
            for slot in slots:
                # Convert to triples using VitalSigns
                triples = slot.to_triples()
                all_triples.extend(triples)
            
            # Build SPARQL INSERT query
            if all_triples:
                # Format triple components based on RDFLib object types
                from rdflib import URIRef, Literal, BNode
                triple_statements = []
                for t in all_triples:
                    subject = str(t[0])
                    predicate = str(t[1])
                    
                    # Format object based on its RDFLib type
                    if isinstance(t[2], Literal):
                        if t[2].datatype:
                            obj_str = f'"{t[2]}"^^<{t[2].datatype}>'
                        elif t[2].language:
                            obj_str = f'"{t[2]}"@{t[2].language}'
                        else:
                            obj_str = f'"{t[2]}"'
                    elif isinstance(t[2], URIRef):
                        obj_str = f"<{t[2]}>"
                    elif isinstance(t[2], BNode):
                        obj_str = f"_:{t[2]}"
                    else:
                        # Fallback for strings
                        obj_str = f'"{t[2]}"'
                    
                    triple_statements.append(f"<{subject}> <{predicate}> {obj_str}")
                
                triples_str = " .\n    ".join(triple_statements)
                insert_query = f"""
                INSERT DATA {{
                    GRAPH <{graph_id}> {{
                        {triples_str} .
                    }}
                }}
                """
                await backend.execute_sparql_update(space_id, insert_query)
            
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
                    DELETE WHERE {{
                        GRAPH <{graph_id}> {{
                            <{slot_uri}> ?p ?o .
                        }}
                    }}
                    """
                    await backend.execute_sparql_update(space_id, delete_slot_query)
                    
                    # Delete the Edge_hasKGSlot connecting frame to slot
                    delete_edge_query = f"""
                    DELETE WHERE {{
                        GRAPH <{graph_id}> {{
                            ?edge a <{self.haley_prefix}Edge_hasKGSlot> ;
                                  <{self.vital_prefix}hasEdgeSource> <{frame_uri}> ;
                                  <{self.vital_prefix}hasEdgeDestination> <{slot_uri}> .
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
        """Store VitalSigns slot objects and edges in backend via triples."""
        try:
            # Convert objects to triples
            all_triples = []
            slot_uris = []
            
            for obj in objects:
                if isinstance(obj, KGSlot):
                    # Cast URI property to get actual string value
                    slot_uris.append(str(obj.URI))
                
                # Convert to triples using VitalSigns
                triples = obj.to_triples()
                all_triples.extend(triples)
            
            # Build SPARQL INSERT query
            if all_triples:
                # Convert VitalSigns tuples to RDFLib format
                from rdflib import URIRef, Literal
                from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                rdflib_triples = []
                for triple in all_triples:
                    # VitalSigns returns tuples (s, p, o)
                    s, p, o = triple
                    # Convert to RDFLib objects
                    s_ref = URIRef(str(s))
                    p_ref = URIRef(str(p))
                    # Object could be URI or Literal - use proper URI validation
                    o_str = str(o)
                    if validate_rfc3986(o_str, rule='URI'):
                        o_ref = URIRef(o_str)
                    else:
                        o_ref = Literal(o_str)
                    rdflib_triples.append((s_ref, p_ref, o_ref))
                
                # Build triple statements for SPARQL
                from rdflib import BNode
                triple_statements = []
                for s, p, o in rdflib_triples:
                    subject = str(s)
                    predicate = str(p)
                    
                    # Format object based on its RDFLib type
                    if isinstance(o, Literal):
                        if o.datatype:
                            obj_str = f'"{o}"^^<{o.datatype}>'
                        elif o.language:
                            obj_str = f'"{o}"@{o.language}'
                        else:
                            obj_str = f'"{o}"'
                    elif isinstance(o, URIRef):
                        obj_str = f"<{o}>"
                    elif isinstance(o, BNode):
                        obj_str = f"_:{o}"
                    else:
                        # Fallback for strings
                        obj_str = f'"{o}"'
                    
                    triple_statements.append(f"<{subject}> <{predicate}> {obj_str}")
                
                triples_str = " .\n    ".join(triple_statements)
                insert_query = f"""
                INSERT DATA {{
                    GRAPH <{graph_id}> {{
                        {triples_str} .
                    }}
                }}
                """
                await backend.execute_sparql_update(space_id, insert_query)
            
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
        request: JsonLdRequest,
        operation_mode: str,
        current_user: Dict
    ) -> FrameCreateResponse:
        """Create child frames linked to parent frame using processor."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Convert JSON-LD to VitalSigns objects at boundary
            frame_objects = self._jsonld_document_to_vitalsigns_objects(request)
            
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
    ) -> JsonLdDocument:
        """Get complete frame graph using processor."""
        try:
            # Get backend adapter
            backend_adapter = await self._get_backend_adapter(space_id)
            
            # Delegate to graph processor
            result = await self.frame_graph_processor.get_frame_graph(
                backend_adapter=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                frame_uri=frame_uri
            )
            
            if result.success and result.graph_objects:
                # Convert VitalSigns objects to JSON-LD at boundary
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                
                # Handle single object case - JsonLdDocument requires 0 or 2+ objects
                if len(result.graph_objects) == 1:
                    # Single object (just the frame, no slots) - return None for complete_graph
                    self.logger.debug("Frame graph has only 1 object (frame only), returning None for complete_graph")
                    return None
                
                jsonld_data = GraphObject.to_jsonld_list(result.graph_objects)
                return JsonLdDocument(**jsonld_data)
            else:
                # Return empty document
                from vital_ai_vitalsigns.model.GraphObject import GraphObject
                empty_jsonld = GraphObject.to_jsonld_list([])
                return JsonLdDocument(**empty_jsonld)
                
        except Exception as e:
            self.logger.error(f"Frame graph retrieval failed: {e}", exc_info=True)
            return JsonLdDocument(
                context={"@vocab": self.haley_prefix},
                graph=[]
            )
    
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
