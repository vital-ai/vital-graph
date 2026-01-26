"""
KG Entities REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing KG entities using JSON-LD 1.1 format.
KG entities represent knowledge graph entities with their associated triples and frame relationships.
"""

import logging
from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel, Field
from enum import Enum

# Legacy import removed - now using kg_impl processors directly
from vitalgraph.model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from ..model.kgentities_model import (
    EntitiesResponse,
    EntityCreateResponse,
    EntityUpdateResponse,
    EntityDeleteResponse,
    EntityFramesResponse,
    EntityFramesMultiResponse,
    EntityGraphResponse,
    EntityQueryRequest,
    EntityQueryResponse,
    EntitiesGraphResponse
)
from ..model.kgframes_model import FramesResponse, FrameGraphsResponse, FrameCreateResponse, FrameUpdateResponse
# Import VitalSigns integration patterns from mock
from ..sparql.grouping_uri_queries import GroupingURIQueryBuilder, GroupingURIGraphRetriever
from ..sparql.graph_validation import EntityGraphValidator

# Import new kg_impl implementation
from ..kg_impl.kg_backend_utils import create_backend_adapter
from ..kg_impl.kgentity_create_impl import KGEntityCreateProcessor, OperationMode as ImplOperationMode
from ..kg_impl.kgentity_get_impl import KGEntityGetProcessor
from ..kg_impl.kgentity_list_impl import KGEntityListProcessor
from ..kg_impl.kgentity_update_impl import KGEntityUpdateProcessor
from ..kg_impl.kgentity_delete_impl import KGEntityDeleteProcessor
from ..kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor
from ..kg_impl.kgentity_frame_update_impl import KGEntityFrameUpdateProcessor
import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

# KG domain model imports
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame


class OperationMode(str, Enum):
    """Operation modes for entity lifecycle management."""
    CREATE = "create"
    UPDATE = "update"
    UPSERT = "upsert"


class KGEntitiesEndpoint:
    """KG Entities endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.KGEntitiesEndpoint")
        self.router = APIRouter()
        
        # VitalSigns prefixes for proper SPARQL generation
        self.haley_prefix = "http://vital.ai/ontology/haley-ai-kg#"
        self.vital_prefix = "http://vital.ai/ontology/vital-core#"
        
        # Initialize VitalSigns integration components (from mock implementation)
        self.grouping_uri_builder = GroupingURIQueryBuilder()
        self.graph_retriever = GroupingURIGraphRetriever(self.grouping_uri_builder)
        self.entity_validator = EntityGraphValidator()
        
        # Initialize kg_impl processors (will be created when backend is available)
        self.create_processor = None
        self.get_processor = None
        self.delete_processor = None
        self.update_processor = None
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes for KG entities management."""
        
        @self.router.get("/kgentities", response_model=Union[EntitiesResponse, JsonLdDocument, JsonLdObject], tags=["KG Entities"])
        async def list_or_get_entities(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of entities per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            entity_type_uri: Optional[str] = Query(None, description="Entity type URI to filter by"),
            search: Optional[str] = Query(None, description="Search text to find in entity properties"),
            uri: Optional[str] = Query(None, description="Single entity URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of entity URIs"),
            id: Optional[str] = Query(None, description="Single reference ID to retrieve"),
            id_list: Optional[str] = Query(None, description="Comma-separated list of reference IDs"),
            include_entity_graph: bool = Query(False, description="If True, include complete entity graphs with frames and slots"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            List KG entities with pagination, or get specific entities by URI(s) or reference ID(s).
            
            - If uri is provided: returns single entity by URI
            - If uri_list is provided: returns multiple entities by URIs
            - If id is provided: returns single entity by reference ID
            - If id_list is provided: returns multiple entities by reference IDs
            - Otherwise: returns paginated list of all entities
            
            Note: Cannot use both URI-based (uri/uri_list) and ID-based (id/id_list) parameters in the same request.
            """
            
            # Validate mutually exclusive parameters
            uri_params_used = bool(uri or uri_list)
            id_params_used = bool(id or id_list)
            
            if uri_params_used and id_params_used:
                from fastapi import HTTPException
                raise HTTPException(
                    status_code=400,
                    detail="Cannot use both URI-based (uri/uri_list) and ID-based (id/id_list) parameters in the same request"
                )
            
            # Handle single reference ID retrieval
            if id:
                return await self._get_entity_by_uri(space_id, graph_id, uri=None, include_entity_graph=include_entity_graph, current_user=current_user, reference_id=id)
            
            # Handle multiple reference ID retrieval
            if id_list:
                ids = [ref_id.strip() for ref_id in id_list.split(',') if ref_id.strip()]
                return await self._get_entities_by_uris(space_id, graph_id, uris=None, include_entity_graph=include_entity_graph, current_user=current_user, reference_ids=ids)
            
            # Handle single URI retrieval
            if uri:
                return await self._get_entity_by_uri(space_id, graph_id, uri, include_entity_graph, current_user)
            
            # Handle multiple URI retrieval
            if uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._get_entities_by_uris(space_id, graph_id, uris, include_entity_graph, current_user)
            
            # Handle paginated listing
            return await self._list_entities(space_id, graph_id, page_size, offset, entity_type_uri, search, include_entity_graph, current_user)
        
        @self.router.post("/kgentities", response_model=Union[EntityCreateResponse, EntityUpdateResponse], tags=["KG Entities"])
        async def create_or_update_entities(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            operation_mode: OperationMode = Query(OperationMode.CREATE, description="Operation mode: create, update, or upsert"),
            parent_uri: Optional[str] = Query(None, description="Parent entity URI for hierarchical relationships"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Create or update entities. Uses discriminated union to automatically handle single entities (JsonLdObject) or multiple entities (JsonLdDocument)."""
            return await self._create_or_update_entities(space_id, graph_id, request, operation_mode, parent_uri, current_user)
        
        
        @self.router.delete("/kgentities", response_model=EntityDeleteResponse, tags=["KG Entities"])
        async def delete_entities(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: Optional[str] = Query(None, description="Single entity URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of entity URIs to delete"),
            delete_entity_graph: bool = Query(False, description="If True, delete complete entity graph including related objects"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete entities by URI or URI list with optional cascade cleanup.
            """
            if uri:
                return await self._delete_entity_by_uri(space_id, graph_id, uri, delete_entity_graph, current_user)
            elif uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._delete_entities_by_uris(space_id, graph_id, uris, delete_entity_graph, current_user)
            else:
                from ..model.kgentities_model import EntityDeleteResponse
                return EntityDeleteResponse(
                    message="Either 'uri' or 'uri_list' parameter is required",
                    deleted_count=0,
                    deleted_uris=[]
                )
        
        @self.router.get("/kgentities/kgframes", response_model=Union[FramesResponse, FrameGraphsResponse], response_model_by_alias=True, tags=["KG Entities"])
        async def get_entity_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            entity_uri: Optional[str] = Query(None, description="Entity URI to get frames for"),
            frame_uris: Optional[List[str]] = Query(None, description="Specific frame URIs to retrieve (returns N JsonLD documents)"),
            parent_frame_uri: Optional[str] = Query(None, description="Parent frame URI for hierarchical filtering"),
            page_size: int = Query(10, ge=1, le=1000, description="Number of frames per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            search: Optional[str] = Query(None, description="Search text to find in frame properties"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Get frames associated with KGEntities using backend SPARQL queries.
            
            Args:
                space_id: Space identifier
                graph_id: Graph identifier
                entity_uri: Optional entity URI to get frames for
                frame_uris: Optional list of specific frame URIs to retrieve
                parent_frame_uri: Parent frame URI for hierarchical filtering
                    - If None: Returns top-level frames (children of entity via Edge_hasEntityKGFrame)
                    - If provided: Returns only frames that are children of the specified parent frame
                page_size: Number of frames per page
                offset: Offset for pagination
                search: Optional search term
                
            Returns:
                Dictionary with entity frames data or N JsonLD documents if frame_uris provided
            """
            return await self._get_kgentity_frames(space_id, graph_id, entity_uri, frame_uris, page_size, offset, search, current_user, parent_frame_uri)
        
        @self.router.post("/kgentities/kgframes", response_model=Union[FrameCreateResponse, FrameUpdateResponse], tags=["KG Entities"])
        async def create_or_update_entity_frames(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            entity_uri: str = Query(..., description="Entity URI"),
            operation_mode: OperationMode = Query(OperationMode.CREATE, description="Operation mode: create, update, or upsert"),
            parent_frame_uri: Optional[str] = Query(None, description="Parent frame URI for hierarchical operations"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Create or update entity frames. Uses discriminated union to automatically handle single frames (JsonLdObject) or multiple frames (JsonLdDocument)."""
            if operation_mode == OperationMode.UPDATE:
                # For updates, use the update-specific method
                return await self._update_entity_frames(space_id, graph_id, entity_uri, request, current_user, parent_frame_uri)
            else:
                # For create/upsert, use the create method
                return await self._create_or_update_frames(space_id, graph_id, request, operation_mode, entity_uri=entity_uri, current_user=current_user, parent_frame_uri=parent_frame_uri)
        
        @self.router.delete("/kgentities/kgframes", tags=["KG Entities"])
        async def delete_entity_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            entity_uri: str = Query(..., description="Entity URI to delete frames from"),
            frame_uris: str = Query(..., description="Comma-separated list of frame URIs to delete"),
            parent_frame_uri: Optional[str] = Query(None, description="Parent frame URI for validation"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete frames within entity context using Edge_hasEntityKGFrame relationships.
            
            Args:
                parent_frame_uri: If provided, validates frames are children of parent before deletion
            """
            frame_uri_list = [uri.strip() for uri in frame_uris.split(',') if uri.strip()]
            return await self._delete_entity_frames(space_id, graph_id, entity_uri, frame_uri_list, current_user, parent_frame_uri)
        
        @self.router.post("/kgentities/query", response_model=EntityQueryResponse, tags=["KG Entities"])
        async def query_entities(
            query_request: EntityQueryRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Query KGEntities using criteria-based search.
            """
            return await self._query_kgentities(space_id, graph_id, query_request, current_user)
        
    
    async def _list_entities(self, space_id: str, graph_id: Optional[str], page_size: int, offset: int, entity_type_uri: Optional[str], search: Optional[str], include_entity_graph: bool, current_user: Dict) -> EntitiesResponse:
        """List entities using KGEntityListProcessor and convert to JsonLD response."""
        from ..model.kgentities_model import EntitiesResponse
        from ..model.jsonld_model import JsonLdDocument
        
        try:
            self.logger.info(f"Listing KGEntities from space {space_id}, graph {graph_id}")
            
            # Backend setup (following _get_entity_by_uri pattern)
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return EntitiesResponse(
                    entities=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return EntitiesResponse(
                    entities=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            backend_adapter = create_backend_adapter(backend)
            
            # Use KGEntityListProcessor
            list_processor = KGEntityListProcessor(logger=self.logger)
            
            result = await list_processor.list_entities(
                space_id=space_id,
                graph_id=graph_id or "default",
                backend_adapter=backend_adapter,
                page_size=page_size,
                offset=offset,
                entity_type_uri=entity_type_uri,
                search=search,
                include_entity_graph=include_entity_graph
            )
            
            # Convert GraphObjects to JsonLD
            if not result.entities or len(result.entities) == 0:
                # Empty results
                jsonld_document = JsonLdDocument(
                    context={"@vocab": "http://vital.ai/ontology/haley-ai-kg#"},
                    graph=[]
                )
            elif len(result.entities) == 1:
                # Single entity - use JsonLdObject
                entity_dict = result.entities[0].to_jsonld()
                jsonld_document = JsonLdObject(**entity_dict)
            else:
                # Multiple entities - use JsonLdDocument
                entities_dict = GraphObject.to_jsonld_list(result.entities)
                jsonld_document = JsonLdDocument(**entities_dict)
            
            # Create EntitiesResponse with pagination metadata
            return EntitiesResponse(
                entities=jsonld_document,
                total_count=result.total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGEntities: {e}")
            return EntitiesResponse(
                entities=JsonLdDocument(graph=[]),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    async def _get_entity_by_uri(self, space_id: str, graph_id: Optional[str], uri: Optional[str], include_entity_graph: bool, current_user: Dict, reference_id: Optional[str] = None) -> Union[JsonLdObject, JsonLdDocument]:
        """Get single entity by URI or reference ID using original working implementation."""
        from ..model.jsonld_model import JsonLdObject, JsonLdDocument
        
        try:
            if uri:
                self.logger.info(f"Getting KGEntity {uri} from space {space_id}, graph {graph_id}")
            elif reference_id:
                self.logger.info(f"Getting KGEntity by reference ID '{reference_id}' from space {space_id}, graph {graph_id}")
            else:
                raise ValueError("Either uri or reference_id must be provided")
            
            # Use the original working retrieval logic that matches the insertion system
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return JsonLdObject()
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return JsonLdObject()
            
            # Use backend adapter for consistent retrieval
            backend_adapter = create_backend_adapter(backend)
            
            # Use kg_impl module for entity retrieval
            get_processor = KGEntityGetProcessor(logger=self.logger)
            
            # Get entity using kg_impl
            graph_objects = await get_processor.get_entity(
                space_id=space_id,
                graph_id=graph_id or "default",
                entity_uri=uri,
                reference_id=reference_id,
                include_entity_graph=include_entity_graph,
                backend_adapter=backend_adapter
            )
            
            self.logger.info(f"🔍 KGEntityGetProcessor returned {len(graph_objects) if graph_objects else 0} objects for entity {uri} (include_entity_graph={include_entity_graph})")
            
            # Convert GraphObjects back to JsonLD for response
            if not graph_objects or len(graph_objects) == 0:
                # Return empty JsonLdDocument for no results
                return JsonLdDocument(
                    context={"@vocab": "http://vital.ai/ontology/haley-ai-kg#"},
                    graph=[]
                )
            elif len(graph_objects) == 1:
                # Single entity - return as JsonLdObject
                entity_dict = graph_objects[0].to_jsonld()
                return JsonLdObject(**entity_dict)
            else:
                # Multiple entities - return as JsonLdDocument
                entities_dict = GraphObject.to_jsonld_list(graph_objects)
                return JsonLdDocument(**entities_dict)
            
        except Exception as e:
            self.logger.error(f"Error getting KGEntity: {e}")
            return JsonLdObject()
    
    async def _get_entities_by_uris(self, space_id: str, graph_id: Optional[str], uris: Optional[List[str]], include_entity_graph: bool, current_user: Dict, reference_ids: Optional[List[str]] = None) -> JsonLdDocument:
        """Get multiple entities by URI list or reference ID list using initialized processors."""
        try:
            if uris:
                self.logger.info(f"Getting {len(uris)} KGEntities by URIs from space {space_id}, graph {graph_id}")
                self.logger.info(f"🔍 Requested URIs: {uris}")
                identifiers = uris
                use_reference_ids = False
            elif reference_ids:
                self.logger.info(f"Getting {len(reference_ids)} KGEntities by reference IDs from space {space_id}, graph {graph_id}")
                self.logger.info(f"🔍 Requested reference IDs: {reference_ids}")
                identifiers = reference_ids
                use_reference_ids = True
            else:
                raise ValueError("Either uris or reference_ids must be provided")
            
            # Get each entity individually using _get_entity_by_uri
            all_entities = []
            
            for identifier in identifiers:
                try:
                    if use_reference_ids:
                        entity_doc = await self._get_entity_by_uri(
                            space_id=space_id,
                            graph_id=graph_id,
                            uri=None,
                            include_entity_graph=include_entity_graph,
                            current_user=current_user,
                            reference_id=identifier
                        )
                    else:
                        entity_doc = await self._get_entity_by_uri(
                            space_id=space_id,
                            graph_id=graph_id,
                            uri=identifier,
                            include_entity_graph=include_entity_graph,
                            current_user=current_user
                        )
                    
                    # Handle both JsonLdObject and JsonLdDocument return types
                    if entity_doc:
                        if hasattr(entity_doc, 'graph') and entity_doc.graph:
                            # JsonLdDocument with graph array
                            self.logger.info(f"🔍 Adding {len(entity_doc.graph)} objects from JsonLdDocument")
                            all_entities.extend(entity_doc.graph)
                        elif hasattr(entity_doc, 'model_dump'):
                            # JsonLdObject - convert to dict and add as single object
                            entity_dict = entity_doc.model_dump(by_alias=True)
                            self.logger.info(f"🔍 Adding 1 object from JsonLdObject")
                            all_entities.append(entity_dict)
                        else:
                            self.logger.warning(f"🔍 Unknown entity doc type: {type(entity_doc)}")
                    else:
                        self.logger.warning(f"🔍 No entity doc returned for {uri}")
                        
                except Exception as e:
                    self.logger.warning(f"Failed to get entity {uri}: {e}")
                    continue
            
            # Return JsonLdDocument with all found entities
            return JsonLdDocument(
                context="https://vitalgraph.ai/contexts/vital-core",
                graph=all_entities
            )
            
        except Exception as e:
            self.logger.error(f"Error getting KGEntities: {e}")
            return JsonLdDocument(graph=[])
    
    async def _create_or_update_entities(self, space_id: str, graph_id: str, request: JsonLdRequest, operation_mode: OperationMode, parent_uri: Optional[str], current_user: Dict) -> Union[EntityCreateResponse, EntityUpdateResponse]:
        """Create or update KG entities using refactored kg_impl implementation."""
        try:
            self.logger.info(f"Processing KG entities in space '{space_id}', graph '{graph_id}', operation_mode='{operation_mode}', parent_uri='{parent_uri}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                if operation_mode == OperationMode.CREATE:
                    from ..model.kgentities_model import EntityCreateResponse
                    return EntityCreateResponse(
                        success=False,
                        message="graph_id is required for entity creation/update",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    from ..model.kgentities_model import EntityUpdateResponse
                    return EntityUpdateResponse(
                        success=False,
                        message="graph_id is required for entity creation/update",
                        updated_uri="",
                        updated_count=0
                    )
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                if operation_mode == OperationMode.CREATE:
                    from ..model.kgentities_model import EntityCreateResponse
                    return EntityCreateResponse(
                        success=False,
                        message=f"Space {space_id} not found",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    from ..model.kgentities_model import EntityUpdateResponse
                    return EntityUpdateResponse(
                        success=False,
                        message=f"Space {space_id} not found",
                        updated_uri="",
                        updated_count=0
                    )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                if operation_mode == OperationMode.CREATE:
                    from ..model.kgentities_model import EntityCreateResponse
                    return EntityCreateResponse(
                        success=False,
                        message="Backend implementation not available",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    from ..model.kgentities_model import EntityUpdateResponse
                    return EntityUpdateResponse(
                        success=False,
                        message="Backend implementation not available",
                        updated_uri="",
                        updated_count=0
                    )
            
            # Convert operation mode to kg_impl format
            impl_operation_mode = self._convert_operation_mode(operation_mode)
            
            # Create backend adapter for kg_impl
            backend_adapter = create_backend_adapter(backend_impl)
            
            # Convert JsonLD to GraphObjects first (endpoint handles conversion)
            vitalsigns_objects = self._convert_jsonld_to_graph_objects(request)
            if not vitalsigns_objects:
                if operation_mode == OperationMode.CREATE:
                    from ..model.kgentities_model import EntityCreateResponse
                    return EntityCreateResponse(
                        success=False,
                        message="No valid objects found in request",
                        created_count=0,
                        created_uris=[]
                    )
                else:
                    from ..model.kgentities_model import EntityUpdateResponse
                    return EntityUpdateResponse(
                        success=False,
                        message="No valid objects found in request",
                        updated_uri="",
                        updated_count=0
                    )
            
            # Use appropriate processor based on operation mode
            if operation_mode == OperationMode.UPDATE:
                return await self._handle_update_mode(backend_adapter, space_id, graph_id, vitalsigns_objects, current_user)
            else:
                # Use kg_impl processor for the core logic
                processor = KGEntityCreateProcessor(backend_adapter)
                result = await processor.create_or_update_entities(
                    space_id=space_id,
                    graph_id=graph_id,
                    vitalsigns_objects=vitalsigns_objects,
                    operation_mode=impl_operation_mode,
                    parent_uri=parent_uri
                )
            
            # Handle any errors in the result - return the result as-is since it already contains proper error information
            
            return result
                
        except Exception as e:
            self.logger.error(f"Error processing entities: {e}")
            if operation_mode == OperationMode.CREATE:
                from ..model.kgentities_model import EntityCreateResponse
                return EntityCreateResponse(
                    success=False,
                    message=f"Failed to process entities: {str(e)}",
                    created_count=0,
                    created_uris=[]
                )
            else:
                from ..model.kgentities_model import EntityUpdateResponse
                return EntityUpdateResponse(
                    success=False,
                    message=f"Failed to process entities: {str(e)}",
                    updated_uri="",
                    updated_count=0
                )
    
    async def _handle_update_mode(self, backend_adapter, space_id: str, graph_id: str, 
                                 vitalsigns_objects: List[GraphObject], current_user: Dict) -> EntityUpdateResponse:
        """Handle UPDATE mode using KGEntityUpdateProcessor with DELETE + INSERT pattern."""
        try:
            self.logger.info(f"Handling UPDATE mode for entities in space '{space_id}', graph '{graph_id}'")
            
            # Initialize update processor if not already done
            if not hasattr(self, 'update_processor') or self.update_processor is None:
                self.update_processor = KGEntityUpdateProcessor()
            
            # Use the GraphObjects that were already converted by the endpoint
            updated_objects = vitalsigns_objects
            if not updated_objects:
                return EntityUpdateResponse(
                    message="No valid objects found in update data",
                    updated_uri=""
                )
            
            # Extract entity URIs from the objects
            entity_uris = self._extract_entity_uris(updated_objects)
            if not entity_uris:
                return EntityUpdateResponse(
                    message="No entity URIs found in update data",
                    updated_uri=""
                )
            
            # Check if entities exist before updating
            for entity_uri in entity_uris:
                if not await self.update_processor.entity_exists(backend_adapter, space_id, graph_id, entity_uri):
                    return EntityUpdateResponse(
                        message=f"Entity {entity_uri} does not exist. Use CREATE mode to create new entities.",
                        updated_uri=""
                    )
            
            # Perform updates
            if len(entity_uris) == 1:
                # Single entity update
                entity_uri = entity_uris[0]
                result = await self.update_processor.update_entity(
                    backend_adapter, space_id, graph_id, entity_uri, updated_objects
                )
            else:
                # Batch entity update
                # Group objects by entity URI
                entity_updates = {}
                for obj in updated_objects:
                    if hasattr(obj, 'URI'):
                        obj_uri = str(obj.URI)
                        if obj_uri not in entity_updates:
                            entity_updates[obj_uri] = []
                        entity_updates[obj_uri].append(obj)
                
                result = await self.update_processor.update_entities_batch(
                    backend_adapter, space_id, graph_id, entity_updates
                )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in UPDATE mode handling: {e}")
            return EntityUpdateResponse(
                message=f"Error updating entities: {str(e)}",
                updated_uri=""
            )
    
    def _convert_jsonld_to_graph_objects(self, jsonld_data: Union[JsonLdObject, JsonLdDocument]) -> List[GraphObject]:
        """Convert JSON-LD data to VitalSigns GraphObject instances using JSON-LD utilities."""
        from ..kg_impl.kg_jsonld_utils import KGJsonLdUtils
        return KGJsonLdUtils.convert_jsonld_to_graph_objects(jsonld_data)
    
    def _extract_entity_uris(self, graph_objects: List[GraphObject]) -> List[str]:
        """
        Extract entity URIs from GraphObject instances.
        """
        try:
            entity_uris = []
            for obj in graph_objects:
                if hasattr(obj, 'URI') and obj.URI:
                    # Handle VitalSigns URI property which may be a Property object
                    uri_value = str(obj.URI) if obj.URI else None
                    if uri_value:
                        entity_uris.append(uri_value)
                else:
                    self.logger.warning(f"GraphObject missing URI: {type(obj)}")
            
            self.logger.debug(f"Extracted {len(entity_uris)} entity URIs")
            return entity_uris
            
        except Exception as e:
            self.logger.error(f"Error extracting entity URIs: {e}")
            return []
    
    def _convert_operation_mode(self, operation_mode: OperationMode) -> ImplOperationMode:
        """Convert REST endpoint operation mode to kg_impl operation mode."""
        if operation_mode == OperationMode.CREATE:
            return ImplOperationMode.CREATE
        elif operation_mode == OperationMode.UPDATE:
            return ImplOperationMode.UPDATE
        elif operation_mode == OperationMode.UPSERT:
            return ImplOperationMode.UPSERT
        else:
            raise ValueError(f"Unknown operation mode: {operation_mode}")
    
    
    async def _delete_entity_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, delete_entity_graph: bool, current_user: Dict) -> EntityDeleteResponse:
        """Delete single KG entity by URI using KGEntityDeleteProcessor."""
        from ..model.kgentities_model import EntityDeleteResponse
        
        try:
            self.logger.info(f"Deleting KG entity '{uri}' from space '{space_id}', graph '{graph_id}', delete_entity_graph={delete_entity_graph}")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                return EntityDeleteResponse(
                    message="graph_id is required for entity deletion",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Backend setup (following established pattern)
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return EntityDeleteResponse(
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return EntityDeleteResponse(
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            backend_adapter = create_backend_adapter(backend_impl)
            
            # Use KGEntityDeleteProcessor
            delete_processor = KGEntityDeleteProcessor()
            
            # Check if entity exists before deletion (skip check for entity graph deletion)
            entity_exists = True
            if not delete_entity_graph:
                entity_exists = await delete_processor.entity_exists(backend_adapter, space_id, graph_id, uri)
                if not entity_exists:
                    # Return graceful response for non-existent entity instead of HTTP exception
                    return EntityDeleteResponse(
                        message=f"Entity {uri} not found - no deletion performed",
                        deleted_count=0,
                        deleted_uris=[]
                    )
            
            if delete_entity_graph:
                # Delete entire entity graph using processor
                deleted_count = await delete_processor.delete_entity_graph(backend_adapter, space_id, graph_id, uri)
                deletion_type = "entity graph (via kgGraphURI)"
                success = deleted_count > 0
                self.logger.info(f"🔍 DEBUG: delete_entity_graph returned: {deleted_count} (type: {type(deleted_count)})")
            else:
                # Delete only the specific entity using processor
                result = await delete_processor.delete_entity(backend_adapter, space_id, graph_id, uri)
                deletion_type = "entity only"
                # Handle BackendOperationResult object
                success = result.success if hasattr(result, 'success') else bool(result)
                deleted_count = 1 if success else 0
                self.logger.info(f"🔍 DEBUG: delete_entity returned: {result} (type: {type(result)})")
            
            # Always return response with actual deletion results
            self.logger.info(f"Deletion result - {deletion_type}: {uri}, success: {success}, deleted_count: {deleted_count}")
            
            return EntityDeleteResponse(
                message=f"Successfully deleted KG {deletion_type} '{str(uri)}' from graph '{graph_id}' in space '{space_id}' ({deleted_count} objects)" if success else f"Failed to delete KGEntity '{str(uri)}'",
                deleted_count=deleted_count,
                deleted_uris=[str(uri)] if success else []
            )
                
        except Exception as e:
            self.logger.error(f"Error deleting KG entity: {e}")
            return EntityDeleteResponse(
                message=f"Error deleting KG entity: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _delete_entities_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], delete_entity_graph: bool, current_user: Dict) -> EntityDeleteResponse:
        """Delete multiple KG entities by URI list using KGEntityDeleteProcessor."""
        from ..model.kgentities_model import EntityDeleteResponse
        
        try:
            self.logger.info(f"Deleting {len(uris)} KG entities from space '{space_id}', graph '{graph_id}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                return EntityDeleteResponse(
                    message="graph_id is required for entity deletion",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Backend setup (following established pattern)
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return EntityDeleteResponse(
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                return EntityDeleteResponse(
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            backend_adapter = create_backend_adapter(backend_impl)
            
            # Use KGEntityDeleteProcessor
            delete_processor = KGEntityDeleteProcessor()
            
            # Delete entities using processor batch method
            deleted_count = await delete_processor.delete_entities_batch(
                backend_adapter, space_id, graph_id, uris, delete_entity_graph
            )
            
            self.logger.info(f"Successfully deleted {deleted_count} KG entities")
            
            return EntityDeleteResponse(
                message=f"Successfully deleted {deleted_count} KG entities from graph '{graph_id}' in space '{space_id}'",
                deleted_count=deleted_count,
                deleted_uris=[str(uri) for uri in uris[:deleted_count]]  # Cast URIs to strings and only return the URIs that were actually deleted
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting KG entities: {e}")
            return EntityDeleteResponse(
                message=f"Error deleting KG entities: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _get_kgentity_frames(self, space_id: str, graph_id: str, entity_uri: Optional[str], frame_uris: Optional[List[str]], page_size: int, offset: int, search: Optional[str], current_user: Dict, parent_frame_uri: Optional[str] = None) -> 'FramesResponse':
        """Get frames associated with KGEntities using SPARQL query processor."""
        try:
            self.logger.info(f"Getting KGEntity frames in space {space_id}, graph {graph_id}, entity_uri {entity_uri}, frame_uris {frame_uris}, parent_frame_uri {parent_frame_uri}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.kgentities_model import FramesResponse
                from ..model.jsonld_model import JsonLdDocument
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                from ..model.kgentities_model import FramesResponse
                from ..model.jsonld_model import JsonLdDocument
                return FramesResponse(
                    frames=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=page_size,
                    offset=offset
                )
            
            # Create backend adapter and SPARQL processor
            from ..kg_impl.kg_backend_utils import create_backend_adapter
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            
            backend_adapter = create_backend_adapter(backend)
            sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
            
            # Check if specific frame URIs are requested (enhanced functionality)
            if frame_uris and entity_uri:
                return await self._get_specific_frame_graphs(backend_adapter, space_id, graph_id, entity_uri, frame_uris)
            
            # Use processor to get entity frames with pagination and search
            frame_results = await sparql_processor.get_entity_frames(
                space_id, graph_id, entity_uri, page_size, offset, search, parent_frame_uri
            )
            
            self.logger.error(f"🔍 DEBUG: Frame query results: {frame_results}")
            self.logger.error(f"🔍 DEBUG: Found {len(frame_results['frame_uris'])} frames for entity {entity_uri}")
            
            # Get all triples for the frame URIs and convert to VitalSigns objects
            frames = []
            if frame_results['frame_uris']:
                # Get triples for all frame subjects
                triples = await self._get_all_triples_for_subjects(backend, space_id, graph_id, frame_results['frame_uris'])
                self.logger.info(f"🔍 DEBUG: Got {len(triples)} triples for {len(frame_results['frame_uris'])} frame URIs")
                
                # Convert triples to VitalSigns frame objects
                frames = self._convert_triples_to_vitalsigns_frames(triples)
                self.logger.info(f"🔍 DEBUG: Converted to {len(frames)} VitalSigns frame objects")
            
            # Convert frames to JSON-LD document (same pattern as KGFramesEndpoint)
            from ..model.jsonld_model import JsonLdDocument, JsonLdObject
            
            if len(frames) == 1:
                # Single frame - return as JsonLdObject using to_jsonld()
                single_frame_dict = frames[0].to_jsonld()
                jsonld_response = JsonLdObject(**single_frame_dict)
            elif len(frames) == 0:
                # No frames - return empty JsonLdDocument
                jsonld_response = JsonLdDocument(graph=[])
            else:
                # Multiple frames - convert each frame individually then wrap in JsonLdDocument
                jsonld_objects = []
                for frame in frames:
                    try:
                        frame_dict = frame.to_jsonld()
                        # Remove individual @context - document-level context is sufficient
                        if '@context' in frame_dict:
                            del frame_dict['@context']
                        jsonld_objects.append(frame_dict)
                    except Exception as e:
                        self.logger.warning(f"Error converting frame to JSON-LD: {e}")
                        continue
                
                jsonld_response = JsonLdDocument(
                    context={"@vocab": "http://vital.ai/ontology/haley-ai-kg#"},
                    graph=jsonld_objects
                )
            
            # Return proper FramesResponse
            from ..model.kgframes_model import FramesResponse
            
            # Debug: Check what we're returning
            if hasattr(jsonld_response, 'graph'):
                self.logger.error(f"🔍 DEBUG: Returning JsonLdDocument with {len(jsonld_response.graph)} objects in graph")
            else:
                self.logger.error(f"🔍 DEBUG: Returning JsonLdObject")
            
            response = FramesResponse(
                frames=jsonld_response,
                total_count=frame_results['total_count'],
                page_size=page_size,
                offset=offset
            )
            
            # Debug: Check the response after creation
            if hasattr(response.frames, 'graph'):
                self.logger.error(f"🔍 DEBUG: FramesResponse.frames.graph has {len(response.frames.graph)} objects")
            
            return response
            
        except Exception as e:
            self.logger.error(f"Error getting KGEntity frames: {e}")
            from ..model.kgframes_model import FramesResponse
            from ..model.jsonld_model import JsonLdDocument
            return FramesResponse(
                frames=JsonLdDocument(graph=[]),
                total_count=0,
                page_size=page_size,
                offset=offset
            )
    
    async def _get_individual_frame(self, space_id: str, graph_id: str, frame_uri: str, include_frame_graph: bool = False, current_user: Dict = None):
        """Get an individual frame by URI using SPARQL query processor."""
        try:
            self.logger.info(f"Getting individual frame {frame_uri} from space {space_id}, graph {graph_id}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.jsonld_model import JsonLdObject
                return JsonLdObject()
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                from ..model.jsonld_model import JsonLdObject
                return JsonLdObject()
            
            # Create backend adapter and SPARQL processor
            from ..kg_impl.kg_backend_utils import create_backend_adapter
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            
            backend_adapter = create_backend_adapter(backend)
            sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
            
            # Use processor to get individual frame
            frame_data = await sparql_processor.get_individual_frame(space_id, graph_id, frame_uri, include_frame_graph)
            
            if not frame_data or not frame_data.get('subject_uris'):
                # Return empty response instead of 404 - service should never return 404 for valid requests
                class FrameResponse:
                    def __init__(self, success, message, data):
                        self.success = success
                        self.message = message
                        self.data = data
                
                return FrameResponse(
                    success=True,
                    message=f"Frame {frame_uri} not found",
                    data=None
                )
            
            self.logger.info(f"🔍 Found {len(frame_data['subject_uris'])} objects for frame {frame_uri}")
            
            # Get all triples for the subject URIs
            triples = await self._get_all_triples_for_subjects(backend, space_id, graph_id, frame_data['subject_uris'])
            
            # Convert triples to VitalSigns objects
            frame_objects = self._convert_triples_to_vitalsigns_frames(triples)
            
            # Return VitalSigns objects directly instead of converting to JSON
            # This avoids unnecessary JSON serialization/deserialization
            class FrameResponse:
                def __init__(self, graph):
                    self.graph = graph
            
            return FrameResponse(frame_objects)
            
        except Exception as e:
            self.logger.error(f"Error getting individual frame: {e}")
            from ..model.jsonld_model import JsonLdObject
            return JsonLdObject()
    
    async def _create_or_update_frames(self, space_id: str, graph_id: str, request: Any, operation_mode: Any, parent_uri: str = None, entity_uri: str = None, current_user: Dict = None, parent_frame_uri: str = None):
        """Create or update frames for KGEntities integration using KGEntityFrameCreateProcessor."""
        try:
            # Validate required parameters for KGEntities frame operations
            if not entity_uri:
                from ..model.kgframes_model import FrameCreateResponse
                return FrameCreateResponse(
                    success=False,
                    message="entity_uri is required for KGEntities frame operations",
                    created_count=0,
                    created_uris=[]
                )
            
            self.logger.info(f"Creating/updating frames for entity {entity_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.kgframes_model import FrameCreateResponse
                return FrameCreateResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    created_count=0,
                    created_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                from ..model.kgframes_model import FrameCreateResponse
                return FrameCreateResponse(
                    success=False,
                    message="Backend implementation not available",
                    created_count=0,
                    created_uris=[]
                )
            
            # Create backend adapter
            backend_adapter = create_backend_adapter(backend_impl)
            
            # Convert JSON-LD document to VitalSigns objects
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vs = VitalSigns()
            
            # Get the JSON-LD document
            jsonld_document = request.model_dump(by_alias=True)
            
            # Convert to VitalSigns objects
            graph_objects = vs.from_jsonld_list(jsonld_document)
            
            if not graph_objects:
                from ..model.kgframes_model import FrameCreateResponse
                return FrameCreateResponse(
                    success=False,
                    message="No valid objects found in request",
                    created_count=0,
                    created_uris=[]
                )
            
            # Use KGEntityFrameCreateProcessor to handle frame creation
            frame_processor = KGEntityFrameCreateProcessor()
            
            # Convert operation_mode to string for processor
            operation_mode_str = "CREATE"
            if operation_mode:
                if hasattr(operation_mode, 'value'):
                    operation_mode_str = operation_mode.value.upper()
                elif isinstance(operation_mode, str):
                    operation_mode_str = operation_mode.upper()
                else:
                    operation_mode_str = str(operation_mode).upper()
            
            # Delegate to processor
            result = await frame_processor.create_entity_frame(
                backend_adapter=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_objects=graph_objects,
                operation_mode=operation_mode_str
            )
            
            # Handle processor result and maintain API compatibility
            if result.success:
                self.logger.info(f"Successfully created/updated {result.frame_count} frame objects")
                
                # Return response in expected format (maintaining backward compatibility)
                class FrameCreateResponse:
                    def __init__(self, created_uris):
                        self.created_uris = created_uris
                        self.message = f"Successfully created {len(created_uris)} frames"
                
                return FrameCreateResponse(result.created_uris)
            else:
                # Handle processor failure
                from ..model.kgframes_model import FrameCreateResponse
                return FrameCreateResponse(
                    success=False,
                    message=result.message,
                    created_count=0,
                    created_uris=[]
                )
            
        except Exception as e:
            self.logger.error(f"Error creating/updating frames: {e}")
            from ..model.kgframes_model import FrameCreateResponse
            return FrameCreateResponse(
                success=False,
                message=f"Failed to create/update frames: {str(e)}",
                created_count=0,
                created_uris=[]
            )
    
    async def _delete_frame_by_uri(self, space_id: str, graph_id: str, uri: str, current_user: Dict = None):
        """Delete a frame by URI using SPARQL query processor."""
        try:
            self.logger.info(f"Deleting frame {uri} from space {space_id}, graph {graph_id}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Create backend adapter and SPARQL processor
            from ..kg_impl.kg_backend_utils import create_backend_adapter
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            
            backend_adapter = create_backend_adapter(backend)
            sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
            
            # Use processor to delete frame
            delete_result = await sparql_processor.delete_frame(space_id, graph_id, uri)
            
            self.logger.info(f"Successfully deleted frame {uri} and {delete_result['deleted_count']} related objects")
            
            # Return response in expected format
            class FrameDeleteResponse:
                def __init__(self, deleted_count):
                    self.deleted_count = deleted_count
                    self.message = f"Successfully deleted frame and {deleted_count} related objects"
            
            return FrameDeleteResponse(delete_result['deleted_count'])
            
        except Exception as e:
            self.logger.error(f"Error deleting frame: {e}")
            from ..model.kgframes_model import FrameDeleteResponse
            return FrameDeleteResponse(
                success=False,
                message=f"Failed to delete frame: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _create_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                                   request: JsonLdDocument, operation_mode: OperationMode, current_user: Dict, 
                                   parent_frame_uri: Optional[str] = None) -> FrameCreateResponse:
        """Create or update frames within entity context using Edge_hasEntityKGFrame relationships."""
        try:
            # Handle both OperationMode enum and string types
            mode_str = operation_mode.value if hasattr(operation_mode, 'value') else str(operation_mode)
            self.logger.info(f"Processing entity frames for {entity_uri} in space {space_id}, graph {graph_id}, mode '{mode_str}'")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return FrameCreateResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    created_count=0,
                    created_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return FrameCreateResponse(
                    success=False,
                    message="Backend implementation not available",
                    created_count=0,
                    created_uris=[]
                )
            
            # Convert JSON-LD to VitalSigns graph objects via triples
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            
            # Initialize VitalSigns for object conversion
            vs = VitalSigns()
            
            # Convert JSON-LD document to VitalSigns objects
            jsonld_document = request.model_dump(by_alias=True)
            
            # Use VitalSigns native JSON-LD processing to create graph objects
            graph_objects = vs.from_jsonld_list(jsonld_document)
            
            processed_frames = []
            
            for graph_obj in graph_objects:
                if isinstance(graph_obj, KGFrame):
                    frame_uri = graph_obj.URI
                    if not frame_uri:
                        return FrameCreateResponse(
                            success=False,
                            message="KGFrame missing URI - required for processing",
                            created_count=0,
                            created_uris=[]
                        )
                    
                    # Set grouping URI properties using VitalSigns property setters
                    # 1. Set frameGraphURI - groups all objects within this frame
                    graph_obj.frameGraphURI = frame_uri
                    
                    # 2. Set kGGraphURI - groups all objects within the entity's complete graph
                    graph_obj.kGGraphURI = entity_uri
                    
                    self.logger.info(f"Setting grouping URIs for frame {frame_uri}: frameGraphURI={frame_uri}, kgGraphURI={entity_uri}")
                    
                    processed_frames.append(graph_obj)
                else:
                    # Handle other graph objects (slots, edges, properties, etc.)
                    if hasattr(graph_obj, 'URI') and graph_obj.URI:
                        # Set kGGraphURI for entity-level grouping
                        graph_obj.kGGraphURI = entity_uri
                        
                        # Check if this is a slot edge that needs frameGraphURI
                        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
                        if isinstance(graph_obj, Edge_hasKGSlot):
                            # Slot edges connect frame to slot - they need frameGraphURI set to the frame URI
                            # The edgeSource should be the frame URI
                            if hasattr(graph_obj, 'edgeSource') and graph_obj.edgeSource:
                                frame_uri_for_edge = str(graph_obj.edgeSource)
                                graph_obj.frameGraphURI = frame_uri_for_edge
                                self.logger.info(f"Setting frameGraphURI={frame_uri_for_edge} on Edge_hasKGSlot {graph_obj.URI}")
                            else:
                                self.logger.warning(f"Edge_hasKGSlot missing edgeSource: {graph_obj.URI}")
                        
                        processed_frames.append(graph_obj)
            
            # Validate parent_frame_uri if provided using hierarchical frame processor
            if parent_frame_uri:
                from ..kg_impl.kgentity_hierarchical_frame_impl import KGEntityHierarchicalFrameProcessor
                from ..kg_impl.kg_backend_utils import create_backend_adapter
                
                backend_adapter = create_backend_adapter(backend)
                hierarchical_processor = KGEntityHierarchicalFrameProcessor(backend_adapter, self.logger)
                
                parent_frame_valid = await hierarchical_processor.validate_parent_frame(space_id, graph_id, entity_uri, parent_frame_uri)
                if not parent_frame_valid:
                    return FrameCreateResponse(
                        success=False,
                        message=f"Parent frame validation failed: {parent_frame_uri} does not exist or does not belong to entity {entity_uri}",
                        created_count=0,
                        created_uris=[]
                    )
            
            # Handle different operation modes with validation
            if operation_mode == OperationMode.CREATE:
                # For CREATE mode, we'll let the processor handle validation
                pass
                    
            elif operation_mode == OperationMode.UPDATE:
                # For UPDATE mode, we'll let the processor handle validation
                pass
            
            # Create connection edges using hierarchical frame processor
            if not 'hierarchical_processor' in locals():
                from ..kg_impl.kgentity_hierarchical_frame_impl import KGEntityHierarchicalFrameProcessor
                from ..kg_impl.kg_backend_utils import create_backend_adapter
                
                backend_adapter = create_backend_adapter(backend)
                hierarchical_processor = KGEntityHierarchicalFrameProcessor(backend_adapter, self.logger)
            
            connection_edges = hierarchical_processor.create_connection_edges(entity_uri, processed_frames, parent_frame_uri)
            
            # Convert VitalSigns graph objects back to JSON-LD for backend processing
            all_graph_objects = processed_frames + connection_edges
            
            # Create backend adapter for frame operations
            backend_adapter = create_backend_adapter(backend)
            
            # Use KGEntityFrameCreateProcessor for actual backend operations
            from ..kg_impl.kgentity_frame_create_impl import KGEntityFrameCreateProcessor
            frame_processor = KGEntityFrameCreateProcessor()
            
            # Convert operation mode to processor format
            processor_mode = "CREATE" if operation_mode == OperationMode.CREATE else "UPDATE"
            
            # Execute frame operations using the processor
            result = await frame_processor.create_entity_frame(
                backend_adapter=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_objects=all_graph_objects,
                operation_mode=processor_mode
            )
            
            # Convert CreateFrameResult to FrameCreateResponse
            if result.success:
                return FrameCreateResponse(
                    success=True,
                    message=result.message,
                    created_count=len(result.created_uris),
                    created_uris=result.created_uris,
                    slots_created=0
                )
            else:
                return FrameCreateResponse(
                    success=False,
                    message=result.message,
                    created_count=0,
                    created_uris=[],
                    slots_created=0
                )
            
        except Exception as e:
            self.logger.error(f"Error processing entity frames: {e}")
            return FrameCreateResponse(
                success=False,
                message=f"Failed to process entity frames: {str(e)}",
                created_count=0,
                created_uris=[],
                slots_created=0
            )
    
    
    async def _delete_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str], current_user: Dict, parent_frame_uri: Optional[str] = None):
        """Delete frames within entity context using Edge_hasEntityKGFrame relationships."""
        try:
            self.logger.info(f"Deleting entity frames for {entity_uri} in space {space_id}, graph {graph_id}, parent_frame_uri {parent_frame_uri}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Get the proper space-specific graph URI
            if hasattr(backend, '_get_space_graph_uri'):
                full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
            else:
                full_graph_uri = graph_id
            
            # Get the actual backend adapter for SPARQL operations
            from ..kg_impl.kg_backend_utils import create_backend_adapter
            backend_adapter = create_backend_adapter(backend)
            
            # Validate parent-child relationships if parent_frame_uri is provided
            if parent_frame_uri:
                from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
                sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
                
                validation_map = await sparql_processor.validate_frame_parent_relationship(
                    space_id, full_graph_uri, parent_frame_uri, frame_uris
                )
                
                # Check if all frames are valid children
                invalid_frames = [uri for uri, is_valid in validation_map.items() if not is_valid]
                if invalid_frames:
                    from ..model.kgframes_model import FrameDeleteResponse
                    return FrameDeleteResponse(
                        success=False,
                        message=f"Frames are not children of parent {parent_frame_uri}: {', '.join(invalid_frames)}",
                        deleted_count=0,
                        deleted_uris=[]
                    )
            
            # Use KGEntityFrameDeleteProcessor for deletion
            from ..kg_impl.kgentity_frame_delete_impl import KGEntityFrameDeleteProcessor
            processor = KGEntityFrameDeleteProcessor(backend_adapter, self.logger)
            
            # Execute frame deletion
            result = await processor.delete_frames(space_id, full_graph_uri, entity_uri, frame_uris)
            
            # Convert to response model
            from ..model.kgframes_model import FrameDeleteResponse
            
            return FrameDeleteResponse(
                message=result.message,
                deleted_count=len(result.deleted_frame_uris),
                deleted_uris=result.deleted_frame_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting entity frames: {e}")
            from ..model.kgframes_model import FrameDeleteResponse
            return FrameDeleteResponse(
                success=False,
                message=f"Failed to delete entity frames: {str(e)}",
                deleted_count=0,
                deleted_uris=[]
            )
    
    async def _update_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, 
                                   request: JsonLdDocument, current_user: Dict, 
                                   parent_frame_uri: Optional[str] = None) -> FrameUpdateResponse:
        """Update frames within entity context using complete frame replacement."""
        try:
            if parent_frame_uri:
                self.logger.info(f"Updating CHILD entity frames for {entity_uri} in space {space_id}, graph {graph_id}, parent_frame_uri={parent_frame_uri}")
            else:
                self.logger.info(f"Updating TOP-LEVEL entity frames for {entity_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message=f"Space {space_id} not found",
                    updated_uri="",
                    updated_count=0
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message="Backend implementation not available",
                    updated_uri="",
                    updated_count=0
                )
            
            # Convert JSON-LD to VitalSigns graph objects
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            from ai_haley_kg_domain.model.KGFrame import KGFrame
            vs = VitalSigns()
            jsonld_document = request.model_dump(by_alias=True)
            self.logger.info(f"🔍 Update request JSON-LD has {len(jsonld_document.get('graph', []))} objects")
            graph_objects = vs.from_jsonld_list(jsonld_document)
            self.logger.info(f"🔍 Converted to {len(graph_objects)} VitalSigns objects")
            for i, obj in enumerate(graph_objects):
                obj_type = type(obj).__name__
                obj_uri = str(obj.URI) if hasattr(obj, 'URI') else 'NO_URI'
                self.logger.info(f"🔍   Object {i+1}: {obj_type} - {obj_uri}")
            
            # Create backend adapter for frame operations
            from ..kg_impl.kg_backend_utils import create_backend_adapter
            backend_adapter = create_backend_adapter(backend)
            
            # Discover existing frames using frame discovery processor
            from ..kg_impl.kgentity_frame_discovery_impl import KGEntityFrameDiscoveryProcessor
            
            discovery_processor = KGEntityFrameDiscoveryProcessor(backend_adapter, self.logger)
            existing_frames = await discovery_processor.discover_entity_frames(space_id, graph_id, entity_uri)
            
            # Group incoming objects by frame for atomic operations (including connecting edges)
            frame_groups = {}
            connecting_edges = []  # Entity-to-frame and frame-to-frame edges
            
            for graph_obj in graph_objects:
                if isinstance(graph_obj, KGFrame):
                    frame_uri = str(graph_obj.URI)
                    if not frame_uri:
                        from ..model.kgframes_model import FrameUpdateResponse
                        return FrameUpdateResponse(
                            message="KGFrame missing URI - required for processing",
                            updated_uri="",
                            updated_count=0
                        )
                    
                    # Set grouping URI properties for the frame
                    graph_obj.frameGraphURI = frame_uri
                    graph_obj.kGGraphURI = entity_uri
                    
                    # Initialize frame group for atomic operation
                    if frame_uri not in frame_groups:
                        frame_groups[frame_uri] = {
                            'frame_objects': [],  # Objects with frameGraphURI
                            'connecting_edges': []  # Edges without frameGraphURI but part of atomic operation
                        }
                    frame_groups[frame_uri]['frame_objects'].append(graph_obj)
                    
                else:
                    # Handle other objects (slots, edges, etc.)
                    if hasattr(graph_obj, 'URI') and graph_obj.URI:
                        graph_obj.kGGraphURI = entity_uri
                        
                        # Check if this is a connecting edge (Edge_hasEntityKGFrame or frame-to-frame)
                        from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
                        from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
                        from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
                        is_entity_frame_edge = isinstance(graph_obj, (Edge_hasEntityKGFrame, Edge_hasKGFrame))
                        is_slot_edge = isinstance(graph_obj, Edge_hasKGSlot)
                        
                        if is_entity_frame_edge:
                            # Entity-to-frame edges don't have frameGraphURI but are part of atomic operations
                            connecting_edges.append(graph_obj)
                        elif is_slot_edge:
                            # Slot edges connect frame to slot - they need frameGraphURI set to the frame URI
                            # The edgeSource should be the frame URI
                            if hasattr(graph_obj, 'edgeSource') and graph_obj.edgeSource:
                                frame_uri_for_edge = str(graph_obj.edgeSource)
                                graph_obj.frameGraphURI = frame_uri_for_edge
                                if frame_uri_for_edge not in frame_groups:
                                    frame_groups[frame_uri_for_edge] = {
                                        'frame_objects': [],
                                        'connecting_edges': []
                                    }
                                frame_groups[frame_uri_for_edge]['frame_objects'].append(graph_obj)
                            else:
                                self.logger.warning(f"Edge_hasKGSlot missing edgeSource: {graph_obj.URI}")
                        else:
                            # Internal frame objects (slots, etc.) - assign to appropriate frame
                            target_frame_uri = None
                            if hasattr(graph_obj, 'frameGraphURI') and graph_obj.frameGraphURI:
                                target_frame_uri = str(graph_obj.frameGraphURI)
                            else:
                                # Determine frame association for objects without explicit frameGraphURI
                                # This could be based on relationships or other logic
                                frame_keys = list(frame_groups.keys())
                                if frame_keys:
                                    target_frame_uri = frame_keys[0]  # Assign to first frame
                                    graph_obj.frameGraphURI = target_frame_uri
                            
                            if target_frame_uri:
                                if target_frame_uri not in frame_groups:
                                    frame_groups[target_frame_uri] = {
                                        'frame_objects': [],
                                        'connecting_edges': []
                                    }
                                frame_groups[target_frame_uri]['frame_objects'].append(graph_obj)
            
            # Validate parent-child relationships if parent_frame_uri is provided
            if parent_frame_uri and frame_groups:
                from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
                sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
                
                frame_uris_to_validate = list(frame_groups.keys())
                validation_map = await sparql_processor.validate_frame_parent_relationship(
                    space_id, graph_id, parent_frame_uri, frame_uris_to_validate
                )
                
                # Check if all frames are valid children
                invalid_frames = [uri for uri, is_valid in validation_map.items() if not is_valid]
                if invalid_frames:
                    from ..model.kgframes_model import FrameUpdateResponse
                    return FrameUpdateResponse(
                        message=f"Frames are not children of parent {parent_frame_uri}: {', '.join(invalid_frames)}",
                        updated_uri="",
                        updated_count=0
                    )
            
            # Create hierarchical connection edges if parent_frame_uri is provided using processor
            if parent_frame_uri:
                if not 'hierarchical_processor' in locals():
                    from ..kg_impl.kgentity_hierarchical_frame_impl import KGEntityHierarchicalFrameProcessor
                    hierarchical_processor = KGEntityHierarchicalFrameProcessor(backend_adapter, self.logger)
                
                # Create connection edges for frames being updated
                frame_objects_for_edges = []
                for frame_uri in frame_groups.keys():
                    # Create a mock frame object for edge creation
                    from ai_haley_kg_domain.model.KGFrame import KGFrame
                    mock_frame = KGFrame()
                    mock_frame.URI = frame_uri
                    frame_objects_for_edges.append(mock_frame)
                
                hierarchical_edges = hierarchical_processor.create_connection_edges(entity_uri, frame_objects_for_edges, parent_frame_uri)
                
                # Add hierarchical edges to connecting edges and frame groups
                for edge in hierarchical_edges:
                    connecting_edges.append(edge)
                    
                    # Determine which frame this edge affects and add to frame group
                    affected_frames = hierarchical_processor.determine_affected_frames(edge, list(frame_groups.keys()))
                    for frame_uri in affected_frames:
                        if frame_uri in frame_groups:
                            frame_groups[frame_uri]['connecting_edges'].append(edge)
            
            # Distribute connecting edges to relevant frame groups for atomic operations
            for edge in connecting_edges:
                # Determine which frame(s) this connecting edge affects using processor
                if not 'hierarchical_processor' in locals():
                    from ..kg_impl.kgentity_hierarchical_frame_impl import KGEntityHierarchicalFrameProcessor
                    hierarchical_processor = KGEntityHierarchicalFrameProcessor(backend_adapter, self.logger)
                
                affected_frames = hierarchical_processor.determine_affected_frames(edge, list(frame_groups.keys()))
                for frame_uri in affected_frames:
                    if frame_uri in frame_groups:
                        # Only add if not already added (avoid duplicates from hierarchical edges above)
                        if edge not in frame_groups[frame_uri]['connecting_edges']:
                            frame_groups[frame_uri]['connecting_edges'].append(edge)
            
            if not frame_groups:
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message="No valid frames found for update",
                    updated_uri="",
                    updated_count=0
                )
            
            # Use KGEntityFrameUpdateProcessor for actual backend operations
            from ..kg_impl.kgentity_frame_update_impl import KGEntityFrameUpdateProcessor
            frame_processor = KGEntityFrameUpdateProcessor(backend_adapter, self.logger)
            
            # Execute atomic frame update operations for each complete frame group
            updated_frame_count = 0
            update_results = []
            
            self.logger.info(f"🔍 Frame groups to update: {list(frame_groups.keys())}")
            self.logger.info(f"🔍 Total frame groups: {len(frame_groups)}")
            
            for frame_uri, frame_group in frame_groups.items():
                frame_objects = frame_group['frame_objects']
                connecting_edges = frame_group['connecting_edges']
                total_objects = len(frame_objects) + len(connecting_edges)
                
                self.logger.info(f"Updating atomic frame operation: {frame_uri} with {len(frame_objects)} frame objects and {len(connecting_edges)} connecting edges (total: {total_objects})")
                for i, obj in enumerate(frame_objects):
                    obj_type = type(obj).__name__
                    obj_uri = str(obj.URI) if hasattr(obj, 'URI') else 'NO_URI'
                    self.logger.info(f"  Frame object {i+1}: {obj_type} - {obj_uri}")
                for i, obj in enumerate(connecting_edges):
                    obj_type = type(obj).__name__
                    obj_uri = str(obj.URI) if hasattr(obj, 'URI') else 'NO_URI'
                    self.logger.info(f"  Connecting edge {i+1}: {obj_type} - {obj_uri}")
                
                # Combine frame objects and connecting edges for atomic operation
                all_frame_components = frame_objects + connecting_edges
                
                # Update the complete atomic frame (frame objects + connecting edges) as a unit
                result = await frame_processor.update_frames(
                    space_id=space_id,
                    graph_id=graph_id,
                    entity_uri=entity_uri,
                    frame_objects=all_frame_components,
                    parent_frame_uri=parent_frame_uri
                )
                
                update_results.append(result)
                if result.success:
                    updated_frame_count += 1
            
            # Aggregate results
            successful_updates = [r for r in update_results if r.success]
            failed_updates = [r for r in update_results if not r.success]
            
            if successful_updates:
                success_messages = [r.message for r in successful_updates]
                failure_messages = [r.message for r in failed_updates] if failed_updates else []
                
                message = f"Successfully updated {len(successful_updates)} complete frame(s)"
                if failure_messages:
                    message += f", {len(failed_updates)} frame(s) failed: {'; '.join(failure_messages)}"
                
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message=message,
                    updated_uri=entity_uri,
                    updated_count=len(successful_updates)
                )
            else:
                error_messages = [r.message for r in failed_updates]
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message=f"All frame updates failed: {'; '.join(error_messages)}",
                    updated_uri="",
                    updated_count=0
                )
            
        except Exception as e:
            self.logger.error(f"Error updating entity frames: {e}")
            from ..model.kgframes_model import FrameUpdateResponse
            return FrameUpdateResponse(
                message=f"Failed to update entity frames: {str(e)}",
                updated_uri="",
                updated_count=0
            )
    
    async def _validate_entity_frame_relationships(self, space_id: str, graph_id: str, 
                                                 entity_uri: str, backend_adapter) -> bool:
        """Validate that entity-frame relationships are consistent using SPARQL query processor."""
        try:
            # Create SPARQL processor
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            
            sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
            
            # Use processor to validate entity-frame relationships
            return await sparql_processor.validate_entity_frame_relationships(space_id, graph_id, entity_uri)
            
        except Exception as e:
            self.logger.error(f"Error validating entity-frame relationships: {e}")
            return False
    
    async def _query_kgentities(self, space_id: str, graph_id: str, query_request: Any, current_user: Dict) -> 'EntitiesResponse':
        """Query KGEntities using criteria-based search with SPARQL processor."""
        from ..model.kgentities_model import EntitiesResponse
        from ..model.jsonld_model import JsonLdDocument
        from ..kg_impl.kg_backend_utils import create_backend_adapter
        from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
        try:
            self.logger.info(f"Querying KGEntities in space {space_id}, graph {graph_id} with criteria: {query_request.criteria}")
            
            # Get backend implementation via generic interface
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                return EntitiesResponse(
                    entities=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=0,
                    offset=0
                )
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                return EntitiesResponse(
                    entities=JsonLdDocument(graph=[]),
                    total_count=0,
                    page_size=0,
                    offset=0
                )
            
            # Create backend adapter and SPARQL processor
            
            backend_adapter = create_backend_adapter(backend)
            sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
            
            # Execute query using SPARQL processor
            query_results = await sparql_processor.execute_entity_query(space_id, graph_id, query_request)
            
            # Create response
            return EntityQueryResponse(
                entity_uris=query_results['entity_uris'],
                total_count=query_results['total_count'],
                page_size=query_results['page_size'],
                offset=query_results['offset']
            )
            
        except Exception as e:
            self.logger.error(f"Error querying KGEntities: {e}")
            return EntitiesResponse(
                entities=JsonLdDocument(graph=[]),
                total_count=0,
                page_size=0,
                offset=0
            )
    
    def _convert_query_criteria_to_sparql(self, criteria):
        """Convert Pydantic EntityQueryCriteria to SPARQL dataclass format."""
        from ..sparql.kg_query_builder import (
            EntityQueryCriteria as SparqlEntityQueryCriteria,
            SlotCriteria as SparqlSlotCriteria,
            SortCriteria as SparqlSortCriteria
        )
        from dataclasses import dataclass
        
        # Convert slot criteria
        sparql_slot_criteria = []
        if criteria.slot_criteria:
            for slot_criterion in criteria.slot_criteria:
                sparql_slot_criteria.append(SparqlSlotCriteria(
                    slot_type=slot_criterion.slot_type,
                    comparator=slot_criterion.comparator,
                    value=slot_criterion.value
                ))
        
        # Convert sort criteria if present
        sparql_sort_criteria = None
        if hasattr(criteria, 'sort_criteria') and criteria.sort_criteria:
            sparql_sort_criteria = []
            for sort_criterion in criteria.sort_criteria:
                sparql_sort_criteria.append(SparqlSortCriteria(
                    sort_type=sort_criterion.sort_type,
                    slot_type=sort_criterion.slot_type,
                    frame_type=sort_criterion.frame_type,
                    property_uri=sort_criterion.property_uri,
                    sort_order=sort_criterion.sort_order,
                    priority=sort_criterion.priority
                ))
        
        # Convert filters if present
        sparql_filters = None
        if hasattr(criteria, 'filters') and criteria.filters:
            from ..sparql.kg_query_builder import QueryFilter as SparqlQueryFilter
            sparql_filters = []
            for filter_criterion in criteria.filters:
                sparql_filters.append(SparqlQueryFilter(
                    property_name=filter_criterion.property_name,
                    operator=filter_criterion.operator,
                    value=filter_criterion.value
                ))
        
        # Create SPARQL criteria object
        sparql_criteria = SparqlEntityQueryCriteria(
            search_string=criteria.search_string,
            entity_type=criteria.entity_type,
            frame_type=criteria.frame_type,
            slot_criteria=sparql_slot_criteria,
            sort_criteria=sparql_sort_criteria,
            filters=sparql_filters
        )
        
        return sparql_criteria
    
    # Additional methods from mock implementation (not REST routes)
    
    async def list_kgentities_with_graphs(self, space_id: str, graph_id: str, page_size: int = 10, offset: int = 0,
                                   search: Optional[str] = None, include_entity_graphs: bool = False) -> EntitiesGraphResponse:
        """
        List KGEntities with optional complete graphs.
        
        This is a convenience method that delegates to the main _list_entities method.
        The include_entity_graphs parameter controls whether complete graphs are included.
        
        Args:
            space_id: Space identifier
            graph_id: Graph identifier  
            page_size: Number of entities per page
            offset: Offset for pagination
            search: Optional search term
            include_entity_graphs: If True, include complete entity graphs
            
        Returns:
            EntitiesGraphResponse containing entities and optional complete graphs
        """
        try:
            self.logger.info(f"Listing KGEntities with graphs in space {space_id}, graph {graph_id}, include_graphs={include_entity_graphs}")
            
            # Delegate to the main _list_entities method with include_entity_graph parameter
            # Create a mock user for internal calls
            mock_user = {"username": "system"}
            
            # Call the main list method with the include_entity_graph parameter
            entities_response = await self._list_entities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                entity_type_uri=None,
                search=search,
                include_entity_graph=include_entity_graphs,
                current_user=mock_user
            )
            
            # Convert EntitiesResponse to EntitiesGraphResponse
            complete_graphs = None
            if include_entity_graphs:
                # Extract complete graphs from the entities response
                # The graphs are already embedded in the entities JSON-LD when include_entity_graph=True
                # So we can extract them from the entity objects
                complete_graphs = []
                if entities_response.entities:
                    for entity in entities_response.entities:
                        if hasattr(entity, 'graph') and entity.graph:
                            complete_graphs.append(entity.graph)
                        elif hasattr(entity, 'data') and entity.data:
                            # Handle JsonLdDocument format
                            if hasattr(entity.data, 'graph'):
                                complete_graphs.append(entity.data.graph)
                
                self.logger.info(f"Extracted {len(complete_graphs)} complete entity graphs")
            
            return EntitiesGraphResponse(
                entities=entities_response.entities,
                complete_graphs=complete_graphs,
                total_count=entities_response.total_count,
                page_size=entities_response.page_size,
                offset=entities_response.offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGEntities with graphs: {e}")
            raise Exception(f"Failed to list KGEntities with graphs: {str(e)}")
    
    # Entity-Frame Relationship Methods (from mock implementation)
    
    async def create_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument, operation_mode: str = "create") -> 'FrameCreateResponse':
        """Create frames within entity context using Edge_hasEntityKGFrame relationships."""
        try:
            self.logger.info(f"Creating entity frames for {entity_uri} in space {space_id}, graph {graph_id}")
            
            # Use the existing _create_or_update_frames implementation
            from vitalgraph.endpoint.kgentities_endpoint import OperationMode
            
            # Convert operation_mode string to OperationMode enum
            if operation_mode.upper() == "UPDATE":
                op_mode = OperationMode.UPDATE
            elif operation_mode.upper() == "UPSERT":
                op_mode = OperationMode.UPSERT
            else:
                op_mode = OperationMode.CREATE
            
            # Get current user context (mock for now)
            current_user = {"username": "system", "user_id": "system"}
            
            result = await self._create_or_update_frames(
                space_id=space_id,
                graph_id=graph_id,
                request=document,
                operation_mode=op_mode,
                entity_uri=entity_uri,
                current_user=current_user
            )
            
            # Convert result to FrameCreateResponse format
            from ..model.kgframes_model import FrameCreateResponse
            
            if hasattr(result, 'created_uris') and result.created_uris:
                # Convert VitalSigns property objects to strings
                created_uris_str = [str(uri) for uri in result.created_uris]
                return FrameCreateResponse(
                    message=result.message,
                    created_count=len(result.created_uris),
                    created_uris=created_uris_str
                )
            else:
                return FrameCreateResponse(
                    message="Frame creation completed",
                    created_count=0,
                    created_uris=[]
                )
            
        except Exception as e:
            self.logger.error(f"Error creating entity frames: {e}")
            raise Exception(f"Failed to create entity frames: {str(e)}")
    
    async def _get_all_triples_for_subjects(self, backend, space_id: str, graph_id: str, subject_uris: List[str]) -> List[Dict[str, str]]:
        """Get all triples for the given subject URIs using SPARQL query processor."""
        try:
            # Create backend adapter and SPARQL processor
            from ..kg_impl.kg_backend_utils import create_backend_adapter
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            
            backend_adapter = create_backend_adapter(backend)
            sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
            
            # Use processor to get all triples for subjects
            return await sparql_processor.get_all_triples_for_subjects(space_id, graph_id, subject_uris)
            
        except Exception as e:
            self.logger.error(f"Error getting triples for subjects: {e}")
            return []

    async def update_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, document: JsonLdDocument) -> 'FrameUpdateResponse':
        """Update frames within entity context using Edge_hasEntityKGFrame relationships."""
        try:
            self.logger.info(f"🔄 Starting frame update for entity {entity_uri}: {len(document.graph) if document.graph else 0} frame objects")
            self.logger.info(f"Updating entity frames for {entity_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message=f"Space {space_id} not found",
                    updated_uri="",
                    updated_count=0
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message="Backend implementation not available",
                    updated_uri="",
                    updated_count=0
                )
            
            # Create backend adapter
            from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
            backend_adapter = create_backend_adapter(backend_impl)
            
            # Convert JSON-LD document to VitalSigns objects
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vs = VitalSigns()
            
            # Get the JSON-LD document
            jsonld_document = document.model_dump(by_alias=True)
            self.logger.info(f"🔄 Converting JSON-LD document with {len(jsonld_document.get('graph', []))} objects")
            
            # Convert to VitalSigns objects
            graph_objects = vs.from_jsonld_list(jsonld_document)
            self.logger.info(f"🔄 Converted to {len(graph_objects) if graph_objects else 0} VitalSigns objects")
            
            if not graph_objects:
                self.logger.error("❌ No valid objects found in JSON-LD document for frame update")
                from ..model.kgframes_model import FrameUpdateResponse
                return FrameUpdateResponse(
                    message="No valid objects found in request",
                    updated_uri="",
                    updated_count=0
                )
            
            # Use KGEntityFrameUpdateProcessor to handle frame updates
            frame_update_processor = KGEntityFrameUpdateProcessor(backend_adapter, self.logger)
            
            # Update frames using processor
            self.logger.info(f"🔄 Calling frame update processor with {len(graph_objects)} objects")
            result = await frame_update_processor.update_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_objects=graph_objects
            )
            
            self.logger.info(f"🔄 Frame update processor result: success={result.success}, message='{result.message}'")
            
            # Convert result to FrameUpdateResponse format
            from ..model.kgframes_model import FrameUpdateResponse
            
            if result.success:
                self.logger.info(f"✅ Frame update successful for entity {entity_uri}")
                return FrameUpdateResponse(
                    message=result.message,
                    updated_uri=entity_uri
                )
            else:
                self.logger.warning(f"⚠️ Frame update failed for entity {entity_uri}: {result.message}")
                return FrameUpdateResponse(
                    message=f"Frame update failed: {result.message}",
                    updated_uri=entity_uri
                )
            
        except Exception as e:
            self.logger.error(f"Error updating entity frames: {e}")
            raise Exception(f"Failed to update entity frames: {str(e)}")
    
    async def delete_entity_frames(self, space_id: str, graph_id: str, entity_uri: str, frame_uris: List[str]) -> 'FrameDeleteResponse':
        """Delete frames within entity context using Edge_hasEntityKGFrame relationships."""
        try:
            self.logger.info(f"Deleting entity frames for {entity_uri} in space {space_id}, graph {graph_id}")
            
            # Get backend implementation
            space_record = self.space_manager.get_space(space_id)
            if not space_record:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
                    message=f"Space {space_id} not found",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            space_impl = space_record.space_impl
            backend_impl = space_impl.get_db_space_impl()
            if not backend_impl:
                from ..model.kgframes_model import FrameDeleteResponse
                return FrameDeleteResponse(
                    success=False,
                    message="Backend implementation not available",
                    deleted_count=0,
                    deleted_uris=[]
                )
            
            # Create backend adapter
            from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
            backend_adapter = create_backend_adapter(backend_impl)
            
            # Use KGEntityFrameDeleteProcessor to handle frame deletion
            from vitalgraph.kg_impl.kgentity_frame_delete_impl import KGEntityFrameDeleteProcessor
            
            frame_delete_processor = KGEntityFrameDeleteProcessor(backend_adapter, self.logger)
            
            # Delete frames using processor
            result = await frame_delete_processor.delete_frames(
                space_id=space_id,
                graph_id=graph_id,
                entity_uri=entity_uri,
                frame_uris=frame_uris
            )
            
            # Convert result to FrameDeleteResponse format
            from ..model.kgframes_model import FrameDeleteResponse
            
            return FrameDeleteResponse(
                message=result.message,
                deleted_count=len(result.deleted_frame_uris),
                deleted_uris=result.deleted_frame_uris
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting entity frames: {e}")
            raise Exception(f"Failed to delete entity frames: {str(e)}")
    
    # Helper methods for entity CRUD operations
    
    async def _entity_exists_in_backend(self, backend, space_id: str, graph_id: str, entity_uri: str) -> bool:
        """Check if entity exists in backend using KGEntityDeleteProcessor."""
        try:
            # Use KGEntityDeleteProcessor for consistent entity existence checking
            delete_processor = KGEntityDeleteProcessor()
            backend_adapter = create_backend_adapter(backend)
            return await delete_processor.entity_exists(backend_adapter, space_id, graph_id, entity_uri)
        except Exception as e:
            self.logger.error(f"Error checking entity existence: {e}")
            return False
    
    def _extract_count_from_results(self, results):
        """Extract count value from SPARQL COUNT query results."""
        from ..kg_impl.kg_sparql_utils import KGSparqlUtils
        return KGSparqlUtils.extract_count_from_results(results)
    
    def _convert_triples_to_vitalsigns_frames(self, triples: List[Dict[str, str]]) -> List:
        """Convert triples to VitalSigns frame objects using SPARQL utility."""
        from ..kg_impl.kg_sparql_utils import KGSparqlUtils
        return KGSparqlUtils.convert_triples_to_vitalsigns_frames(triples)
    
    # Helper methods for proper VitalSigns integration
    
    def _build_list_entities_query(self, backend, space_id: str, graph_id: str, entity_type_uri: Optional[str], search: Optional[str], page_size: int, offset: int) -> str:
        """Build SPARQL query for listing entity subjects using query builder."""
        from ..kg_impl.kg_sparql_utils import KGSparqlQueryBuilder
        
        # Get the proper graph URI for Fuseki
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id
        
        # Use SPARQL query builder
        query_builder = KGSparqlQueryBuilder()
        return query_builder.build_list_entities_query(
            full_graph_uri, entity_type_uri, search, page_size, offset
        )
    
    def _build_list_entity_graphs_query(self, backend, space_id: str, graph_id: str, entity_type_uri: Optional[str], search: Optional[str], page_size: int, offset: int) -> str:
        """Build SPARQL query for listing complete entity graphs using query builder."""
        from ..kg_impl.kg_sparql_utils import KGSparqlQueryBuilder
        
        # Get the proper graph URI for Fuseki
        if hasattr(backend, '_get_space_graph_uri'):
            full_graph_uri = backend._get_space_graph_uri(space_id, graph_id)
        else:
            full_graph_uri = graph_id
        
        # Use SPARQL query builder
        query_builder = KGSparqlQueryBuilder()
        return query_builder.build_entity_graphs_query(
            full_graph_uri, entity_type_uri, search, page_size, offset
        )
    
    async def _get_specific_frame_graphs(self, backend, space_id: str, full_graph_uri: str, entity_uri: str, frame_uris: List[str]) -> Dict[str, Any]:
        """
        Retrieve specific frame graphs using SPARQL query processor.
        """
        try:
            # Create backend adapter and SPARQL processor
            from ..kg_impl.kg_backend_utils import create_backend_adapter
            from ..kg_impl.kg_sparql_query import KGSparqlQueryProcessor
            
            backend_adapter = create_backend_adapter(backend)
            sparql_processor = KGSparqlQueryProcessor(backend_adapter, self.logger)
            
            # Use processor to get specific frame graphs
            processor_results = await sparql_processor.get_specific_frame_graphs(
                space_id, full_graph_uri, entity_uri, frame_uris
            )
            
            # Convert processor results to endpoint format with VitalSigns processing
            frame_graphs = {}
            
            from vital_ai_vitalsigns.vitalsigns import VitalSigns
            vs = VitalSigns()
            
            for frame_uri, frame_data in processor_results['frame_graphs'].items():
                if 'error' in frame_data:
                    # Pass through error responses
                    frame_graphs[frame_uri] = frame_data
                elif 'triples' in frame_data and frame_data['triples']:
                    # Convert SPARQL result tuples to VitalSigns GraphObjects
                    try:
                        from rdflib import URIRef, Literal
                        from vital_ai_vitalsigns.utils.uri_utils import validate_rfc3986
                        
                        # Convert string tuples to RDFLib Triple objects
                        rdflib_triples = []
                        for subject_str, predicate_str, object_str in frame_data['triples']:
                            subject = URIRef(subject_str)
                            predicate = URIRef(predicate_str)
                            # Use VitalSigns RFC 3986 validation to determine if object is URI or Literal
                            if validate_rfc3986(object_str, rule='URI'):
                                obj = URIRef(object_str)
                            else:
                                obj = Literal(object_str)
                            rdflib_triples.append((subject, predicate, obj))
                        
                        # Use from_triples_list with RDFLib Triple objects
                        self.logger.info(f"🔍 Frame {frame_uri}: Converting {len(rdflib_triples)} RDFLib triples to VitalSigns objects")
                        graph_objects = vs.from_triples_list(rdflib_triples)
                        
                        # Log what types of objects were created
                        object_types = {}
                        for obj in graph_objects:
                            obj_type = type(obj).__name__
                            object_types[obj_type] = object_types.get(obj_type, 0) + 1
                        self.logger.info(f"🔍 Frame {frame_uri}: Created objects: {object_types}")
                        
                        from vital_ai_vitalsigns.model.GraphObject import GraphObject
                        jsonld_dict = GraphObject.to_jsonld_list(graph_objects)
                        frame_graphs[frame_uri] = jsonld_dict
                        self.logger.info(f"🔍 Frame {frame_uri}: Retrieved {len(graph_objects)} objects from {len(frame_data['triples'])} triples")
                    except Exception as vs_error:
                        self.logger.warning(f"VitalSigns conversion error for frame {frame_uri}: {vs_error}")
                        # Don't include frames with conversion errors
                else:
                    # Empty or no data - don't include deleted/non-existent frames in response
                    self.logger.info(f"🔍 Frame {frame_uri}: No graph data found (frame may not exist)")
            
            # Return response in expected format
            return {
                "frame_graphs": frame_graphs,
                "entity_uri": entity_uri,
                "requested_frames": processor_results['requested_frames'],
                "retrieved_frames": processor_results['retrieved_frames'],
                "validation_results": processor_results['validation_results']
            }
            
        except Exception as e:
            self.logger.error(f"Error in specific frame graph retrieval: {e}")
            from ..model.jsonld_model import JsonLdDocument
            return JsonLdDocument(graph=[])
    
    def _extract_frame_uris_from_results(self, results) -> List[str]:
        """Extract frame URIs from SPARQL query results."""
        from ..kg_impl.kg_sparql_utils import KGSparqlUtils
        return KGSparqlUtils.extract_frame_uris_from_results(results)
    
    def _extract_triples_from_sparql_results(self, results) -> List[tuple]:
        """Extract triples from SPARQL SELECT results."""
        from ..kg_impl.kg_sparql_utils import KGSparqlUtils
        return KGSparqlUtils.extract_triples_from_sparql_results(results)


def create_kgentities_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG entities router."""
    endpoint = KGEntitiesEndpoint(space_manager, auth_dependency)
    return endpoint.router
