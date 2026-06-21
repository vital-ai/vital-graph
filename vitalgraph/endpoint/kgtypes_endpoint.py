"""KG Types Endpoint for VitalGraph

Implements REST API endpoints for KG type management operations.
Based on the planned API specification in docs/planned_rest_api_endpoints.md
"""

import asyncio
from typing import Dict, Any, Literal, Optional, List, Union
from fastapi import APIRouter, HTTPException, Depends, Query, Body, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging
from datetime import datetime

import vital_ai_vitalsigns as vitalsigns
from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGType import KGType

from ..kg_impl.kgtypes_create_impl import KGTypesCreateProcessor
from ..kg_impl.kgtypes_read_impl import KGTypesReadProcessor
from ..kg_impl.kgtypes_update_impl import KGTypesUpdateProcessor
from ..kg_impl.kgtypes_delete_impl import KGTypesDeleteProcessor
from ..kg_impl.kg_backend_utils import create_backend_adapter
from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse, QuadResultsResponse
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects, graphobjects_to_quad_list
from ..model.kgtypes_model import KGTypeFilter
from vitalgraph.model.kgtypes_model import (
    KGTypeCreateResponse, KGTypeUpdateResponse, KGTypeDeleteResponse,
    KGTypeCreateRequest, KGTypeUpdateRequest, KGTypeBatchDeleteRequest,
    KGTypeRelationshipsResponse,
    KGTypeRelationshipCreateRequest, KGTypeRelationshipCreateResponse,
    KGTypeRelationshipDeleteResponse,
    KGTypeDocumentationRequest, KGTypeDocumentationResponse,
    KGTypeDocumentationUpdateResponse, KGTypeDocumentationDeleteResponse,
    KGTypeSearchResponse,
)
from ..auth.role_dependencies import require_space_read, require_space_write, require_system_space_write


class KGTypesEndpoint:
    """KG Types endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.KGTypesEndpoint")
        self.router = APIRouter()
        
        # Initialize KGType services with new atomic processors
        self.kgtypes_create_processor = KGTypesCreateProcessor()
        self.kgtypes_read_processor = KGTypesReadProcessor()
        self.kgtypes_update_processor = KGTypesUpdateProcessor()
        self.kgtypes_delete_processor = KGTypesDeleteProcessor()
        
        self._setup_routes()

    @staticmethod
    def _types_graph(space_id: str) -> str:
        """Return the well-known KG Types graph URI for a space."""
        from vitalgraph.constants import SP_KG_TYPES, SP_KG_TYPES_GRAPH
        if space_id == SP_KG_TYPES:
            return SP_KG_TYPES_GRAPH
        return f"urn:vitalgraph:{space_id}:kg_types"

    def _schedule_auto_sync(self, backend_impl, space_id: str, graph_id: str,
                            subject_uris: List[str], operation: Literal["upsert", "delete"] = "upsert") -> None:
        """Schedule background auto-sync for vector and geo data.

        Fire-and-forget: failures are logged but never block the response.
        """
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
    
    
    def _setup_routes(self):
        """Setup KG types routes."""

        # GET /api/graphs/kgtypes/description - Get type description text
        @self.router.get(
            "/kgtypes/description",
            tags=["KG Types"],
            summary="Get Type Description",
            description="Fetch the type-specific description field from the centralized KG Types space",
        )
        async def get_type_description_text(
            type_uri: str = Query(..., description="The KGType URI to fetch description for"),
            mapping_type: str = Query("kgentity", description="Mapping type: kgentity, kgframe, kgdocument, kgslot"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            from vitalgraph.constants import SP_KG_TYPES
            require_space_read(current_user, SP_KG_TYPES)
            return await self._get_type_description_text(type_uri, mapping_type)

        # GET /api/graphs/kgtypes - List KG types with pagination/filtering
        @self.router.get(
            "/kgtypes",
            response_model=None,
            tags=["KG Types"],
            summary="List KG Types",
            description="List KG types in graph with pagination and filtering options. Returns KGTypeGetResponse for single URI, KGTypeListResponse for lists/searches."
        )
        async def list_kgtypes(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            page_size: int = Query(10, ge=1, le=100, description="Number of types per page"),
            offset: int = Query(0, ge=0, description="Number of types to skip"),
            search: Optional[str] = Query(None, description="Search text to filter types"),
            type_uri: Optional[str] = Query(None, description="Filter by KGType subclass URI (e.g. haley-ai-kg#KGFrameType)"),
            uri: Optional[str] = Query(None, description="Get specific type by URI"),
            uri_list: Optional[str] = Query(None, description="Get multiple types by comma-separated URI list"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_read(current_user, space_id)
            graph_id = self._types_graph(space_id)
            # Handle specific URI request
            if uri:
                return await self._get_kgtype_by_uri(space_id, graph_id, uri, current_user)
            
            # Handle multiple URI request
            elif uri_list:
                return await self._get_kgtypes_by_uris(space_id, graph_id, uri_list, current_user)
            
            # Handle regular list/search request
            else:
                return await self._list_kgtypes(
                    space_id, graph_id, page_size, offset, 
                    filter=None, current_user=current_user, 
                    search=search, type_uri=type_uri,
                )
        
        # GET /api/graphs/kgtypes/relationships - Get type relationships
        @self.router.get(
            "/kgtypes/relationships",
            response_model=KGTypeRelationshipsResponse,
            tags=["KG Types"],
            summary="Get Type Relationships",
            description="Get all type-level edges and connected types for a given type URI"
        )
        async def get_type_relationships(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            id: str = Query(..., alias="id", description="Type URI to query relationships for"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_read(current_user, space_id)
            return await self._get_type_relationships(space_id, self._types_graph(space_id), id, current_user)

        # POST /api/graphs/kgtypes/relationships - Create a type-level edge
        @self.router.post(
            "/kgtypes/relationships",
            response_model=KGTypeRelationshipCreateResponse,
            tags=["KG Types"],
            summary="Create Type Relationship",
            description="Create a type-level edge between two types"
        )
        async def create_type_relationship(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            id: str = Query(..., alias="id", description="Source type URI"),
            body: KGTypeRelationshipCreateRequest = Body(...),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_system_space_write(current_user, space_id)
            require_space_write(current_user, space_id)
            return await self._create_type_relationship(space_id, self._types_graph(space_id), id, body.edge_type, body.target_uri, current_user)

        # DELETE /api/graphs/kgtypes/relationships - Delete a type-level edge
        @self.router.delete(
            "/kgtypes/relationships",
            response_model=KGTypeRelationshipDeleteResponse,
            tags=["KG Types"],
            summary="Delete Type Relationship",
            description="Delete a type-level edge by URI"
        )
        async def delete_type_relationship(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            id: str = Query(..., alias="id", description="Type URI"),
            edge_uri: str = Query(..., description="Edge URI to delete"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_system_space_write(current_user, space_id)
            require_space_write(current_user, space_id)
            return await self._delete_type_relationship(space_id, self._types_graph(space_id), id, edge_uri, current_user)

        # GET /api/graphs/kgtypes/documentation - Get type documentation
        @self.router.get(
            "/kgtypes/documentation",
            response_model=KGTypeDocumentationResponse,
            tags=["KG Types"],
            summary="Get Type Documentation",
            description="Get the documentation KGDocument linked to a type"
        )
        async def get_type_documentation(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            id: str = Query(..., alias="id", description="Type URI"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_read(current_user, space_id)
            return await self._get_type_documentation(space_id, self._types_graph(space_id), id, current_user)

        # PUT /api/graphs/kgtypes/documentation - Create/update type documentation
        @self.router.put(
            "/kgtypes/documentation",
            response_model=KGTypeDocumentationUpdateResponse,
            tags=["KG Types"],
            summary="Update Type Documentation",
            description="Create or update the documentation KGDocument for a type"
        )
        async def update_type_documentation(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            id: str = Query(..., alias="id", description="Type URI"),
            body: KGTypeDocumentationRequest = Body(...),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_system_space_write(current_user, space_id)
            require_space_write(current_user, space_id)
            return await self._update_type_documentation(space_id, self._types_graph(space_id), id, body.content, current_user)

        # DELETE /api/graphs/kgtypes/documentation - Delete type documentation
        @self.router.delete(
            "/kgtypes/documentation",
            response_model=KGTypeDocumentationDeleteResponse,
            tags=["KG Types"],
            summary="Delete Type Documentation",
            description="Delete the documentation KGDocument and its linking edge"
        )
        async def delete_type_documentation(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            id: str = Query(..., alias="id", description="Type URI"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_system_space_write(current_user, space_id)
            require_space_write(current_user, space_id)
            return await self._delete_type_documentation(space_id, self._types_graph(space_id), id, current_user)

        # GET /api/graphs/kgtypes/search - Search types
        @self.router.get(
            "/kgtypes/search",
            response_model=KGTypeSearchResponse,
            tags=["KG Types"],
            summary="Search KG Types",
            description="Search types by keyword (FTS), vector similarity, or hybrid"
        )
        async def search_types(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            q: str = Query(..., description="Search query"),
            type: Optional[str] = Query(None, description="Type filter (e.g. frame, entity, slot, relation)"),
            search_mode: Optional[str] = Query("keyword", description="Search mode: keyword | fts | vector | hybrid"),
            alpha: Optional[float] = Query(None, description="Hybrid search alpha (0.0=pure BM25, 1.0=pure vector). Default 0.5"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_read(current_user, space_id)
            return await self._search_types(space_id, self._types_graph(space_id), q, type, search_mode or "keyword", current_user, alpha=alpha)

        # POST /api/graphs/kgtypes - Create new KG types
        @self.router.post(
            "/kgtypes",
            response_model=KGTypeCreateResponse,
            tags=["KG Types"],
            summary="Create KG Types",
            description="Create new KG types in the specified graph"
        )
        async def create_kgtypes(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            body: QuadRequest = Body(..., description="KGType objects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_system_space_write(current_user, space_id)
            require_space_write(current_user, space_id)
            quads = body.quads
            return await self._create_kgtypes(space_id, self._types_graph(space_id), quads, current_user)
        
        # PUT /api/graphs/kgtypes - Update KG types
        @self.router.put(
            "/kgtypes",
            response_model=KGTypeUpdateResponse,
            tags=["KG Types"],
            summary="Update KG Types",
            description="Update existing KG types in the specified graph"
        )
        async def update_kgtypes(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            body: QuadRequest = Body(..., description="KGType objects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_system_space_write(current_user, space_id)
            require_space_write(current_user, space_id)
            quads = body.quads
            return await self._update_kgtypes(space_id, self._types_graph(space_id), quads, current_user)
        
        # DELETE /api/graphs/kgtypes - Delete KG types
        @self.router.delete(
            "/kgtypes",
            response_model=KGTypeDeleteResponse,
            tags=["KG Types"],
            summary="Delete KG Types",
            description="Delete KG types from the specified graph"
        )
        async def delete_kgtypes(
            space_id: str = Query("sp_kg_types", description="Space ID (defaults to centralized KG Types space)"),
            uri: Optional[str] = Query(None, description="Delete specific type by URI"),
            uri_list: Optional[List[str]] = Query(None, description="Delete multiple types by URI list"),
            request: Optional[KGTypeBatchDeleteRequest] = Body(None, description="Batch delete request with Union data support"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            require_system_space_write(current_user, space_id)
            require_space_write(current_user, space_id)
            return await self._delete_kgtypes(space_id, self._types_graph(space_id), uri, uri_list, request.data if request else None, current_user)
    
    async def _get_type_description_text(self, type_uri: str, mapping_type: str):
        """Fetch type-specific description from sp_kg_types via the description lookup."""
        from vitalgraph.vectorization.kgtype_description_lookup import KGTypeDescriptionLookup
        from vitalgraph.constants import SP_KG_TYPES

        space_record = await self.space_manager.get_space_or_load(SP_KG_TYPES)
        if not space_record:
            raise HTTPException(status_code=503, detail="KG Types system space not available")

        backend = space_record.space_impl.get_db_space_impl()
        pool = getattr(backend, 'connection_pool', None) or getattr(backend, '_pool', None)
        if not pool:
            raise HTTPException(status_code=503, detail="No connection pool for sp_kg_types")

        lookup = KGTypeDescriptionLookup(mapping_type)
        async with pool.acquire() as conn:
            description = await lookup.get_description(conn, type_uri)

        return {
            "type_uri": type_uri,
            "mapping_type": mapping_type,
            "description": description,
        }

    async def _list_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        page_size: int,
        offset: int,
        filter: Optional[str] = None,
        current_user: Dict = None,
        search: Optional[str] = None,
        type_uri: Optional[str] = None,
    ) -> QuadResponse:
        """List KG types with filtering and pagination."""
        
        try:
            self.logger.info(f"Listing KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Get complete document from atomic processor
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available - server configuration error")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            backend_adapter = create_backend_adapter(backend)
            
            # Apply search filter if provided (prioritize search over filter for HTTP routes)
            search_filter = search if search else filter
            triples, total_count = await self.kgtypes_read_processor.list_kgtypes(
                backend=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                search=search_filter,
                type_uri=type_uri
            )
            
            self.logger.info(f"🔍 LIST: Received {len(triples)} RDFLib triples, total_count: {total_count}")
            
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
            self.logger.error(f"Error listing KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error listing KG types: {str(e)}"
            )
    
    async def _get_kgtype_by_uri(
        self,
        space_id: str,
        graph_id: str,
        uri: str,
        current_user: Dict,
    ) -> QuadResultsResponse:
        """Get a specific KGType by URI."""
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available - server configuration error")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            backend_adapter = create_backend_adapter(backend)
            kgtype_object = await self.kgtypes_read_processor.get_kgtype_by_uri(
                backend=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                kgtype_uri=uri
            )
            
            if not kgtype_object:
                self.logger.warning(f"🔍 GET: KGType not found: {uri}")
                return QuadResultsResponse(
                    message=f"KGType with URI '{uri}' not found",
                    total_count=0,
                    results=[],
                )
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, [kgtype_object], graph_id)
            return QuadResultsResponse(
                message=f"Found KGType '{uri}'",
                total_count=1,
                results=quads,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGType by URI: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting KGType: {str(e)}"
            )
    
    async def _get_kgtypes_by_uris(
        self,
        space_id: str,
        graph_id: str,
        uri_list: str,
        current_user: Dict,
    ) -> QuadResponse:
        """Get multiple KGTypes by URI list."""
        try:
            uris = [u.strip() for u in uri_list.split(',') if u.strip()]
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available - server configuration error")
            
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")
            
            backend_adapter = create_backend_adapter(backend)
            kgtype_objects = await self.kgtypes_read_processor.get_kgtypes_by_uris(
                backend=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                kgtype_uris=uris
            )
            
            self.logger.info(f"🔍 GET_BY_URIS: Received {len(kgtype_objects)} KGType GraphObjects for {len(uris)} URIs")
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, kgtype_objects, graph_id)
            return QuadResponse(
                total_count=len(kgtype_objects),
                page_size=len(kgtype_objects),
                offset=0,
                results=quads,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGTypes by URI list: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting KGTypes: {str(e)}"
            )
    
    async def _create_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        quads: List[Quad],
        current_user: Dict
    ) -> KGTypeCreateResponse:
        """Create KG types from quads."""
        try:
            self.logger.info(f"Creating KG types in space '{space_id}', graph '{graph_id}'")

            # Convert quads to GraphObjects and validate
            kgtype_objects = quad_list_to_graphobjects(quads)
            typed_objects = [obj for obj in kgtype_objects if isinstance(obj, KGType)]
            if not typed_objects:
                raise HTTPException(status_code=400, detail="No valid KGType objects found in request")
            kgtype_objects = typed_objects

            if not self.space_manager:
                raise HTTPException(status_code=404, detail=f"Space '{space_id}' not found")
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=404, detail=f"Space '{space_id}' not found")
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            backend_adapter = create_backend_adapter(backend)

            if len(kgtype_objects) == 1:
                created_uri = await self.kgtypes_create_processor.create_kgtype(
                    backend=backend_adapter, space_id=space_id, graph_id=graph_id, kgtype_object=kgtype_objects[0])
                created_uris = [created_uri]
            else:
                created_uris = await self.kgtypes_create_processor.create_kgtypes_batch(
                    backend=backend_adapter, space_id=space_id, graph_id=graph_id, kgtype_objects=kgtype_objects)

            # Trigger background vector/FTS sync for new KGTypes
            self._schedule_auto_sync(backend, space_id, graph_id, created_uris)

            # Invalidate type description cache for created types
            from vitalgraph.vectorization.kgtype_description_lookup import invalidate_cache
            for uri in created_uris:
                invalidate_cache(uri)

            # Cross-space re-sync: update vectors in other spaces referencing these types
            from vitalgraph.vectorization.kgtype_cross_space_sync import schedule_cross_space_sync
            schedule_cross_space_sync(
                space_manager=self.space_manager,
                updated_type_uris=created_uris,
            )

            return KGTypeCreateResponse(
                success=True,
                message=f"Successfully created {len(created_uris)} KG type definitions",
                created_count=len(created_uris),
                created_uris=created_uris
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating KG types from objects: {e}")
            raise HTTPException(status_code=500, detail=f"Error creating KG types: {str(e)}")

    async def _update_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        quads: List[Quad],
        current_user: Dict
    ) -> KGTypeUpdateResponse:
        """Update KG types from quads."""
        try:
            self.logger.info(f"Updating KG types in space '{space_id}', graph '{graph_id}'")

            # Convert quads to GraphObjects and validate
            kgtype_objects = quad_list_to_graphobjects(quads)
            typed_objects = [obj for obj in kgtype_objects if isinstance(obj, KGType)]
            if not typed_objects:
                raise HTTPException(status_code=400, detail="No valid KGType objects found in request")
            kgtype_objects = typed_objects

            if not self.space_manager:
                raise HTTPException(status_code=404, detail=f"Space '{space_id}' not found")
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=404, detail=f"Space '{space_id}' not found")
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            backend_adapter = create_backend_adapter(backend)

            kgtype_updates = {}
            for kgtype_obj in kgtype_objects:
                uri = str(kgtype_obj.URI)
                kgtype_updates[uri] = [kgtype_obj]
            updated_uris = await self.kgtypes_update_processor.update_kgtypes_batch(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id, kgtype_updates=kgtype_updates)

            # Trigger background vector/FTS sync for updated KGTypes
            self._schedule_auto_sync(backend, space_id, graph_id, updated_uris)

            # Invalidate type description cache for updated types
            from vitalgraph.vectorization.kgtype_description_lookup import invalidate_cache
            for uri in updated_uris:
                invalidate_cache(uri)

            # Cross-space re-sync: update vectors in other spaces referencing these types
            from vitalgraph.vectorization.kgtype_cross_space_sync import schedule_cross_space_sync
            schedule_cross_space_sync(
                space_manager=self.space_manager,
                updated_type_uris=updated_uris,
            )

            return KGTypeUpdateResponse(
                success=True,
                message=f"Successfully updated {len(updated_uris)} KG type definitions",
                updated_count=len(updated_uris),
                updated_uris=updated_uris
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating KG types from objects: {e}")
            raise HTTPException(status_code=500, detail=f"Error updating KG types: {str(e)}")

    async def _delete_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        uri: Optional[str],
        uri_list: Optional[str],
        document: Optional[Any],
        current_user: Dict
    ) -> KGTypeDeleteResponse:
        """Delete KG types by URI, URI list, or document using proper VitalGraph patterns."""
        
        try:
            self.logger.info(f"Deleting KG types from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate space manager (same as triples endpoint)
            if self.space_manager is None:
                raise HTTPException(
                    status_code=500,
                    detail="Space manager not available"
                )
            
            # Validate that at least one deletion method is provided
            if not uri and not uri_list and not (document and document.graph):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: must provide uri, uri_list, or document with objects"
                )
            
            deleted_count = 0
            deleted_uris = []
            delete_method = ""
            
            try:
                if uri:
                    # Delete single KGType by URI
                    # Ensure URI is a string (handle CombinedProperty from VitalSigns)
                    uri_str = str(uri) if uri else uri
                    space_record = await self.space_manager.get_space_or_load(space_id)
                    if not space_record:
                        raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                    
                    space_impl = space_record.space_impl
                    backend = space_impl.get_db_space_impl()
                    if not backend:
                        raise HTTPException(status_code=500, detail="Backend implementation not available")
                    
                    backend_adapter = create_backend_adapter(backend)
                    success = await self.kgtypes_delete_processor.delete_kgtype(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_uri=uri_str
                    )
                    if success:
                        deleted_count = 1
                        deleted_uris = [uri_str]
                        self.logger.info(f"Deleted KGType: {uri_str}")
                    delete_method = f"URI '{uri_str}'"
                        
                elif uri_list:
                    # Delete multiple KGTypes by URI list
                    # Handle both string (comma-separated) and list formats
                    if isinstance(uri_list, str):
                        uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                    elif isinstance(uri_list, list):
                        uris = []
                        for u in uri_list:
                            for part in str(u).split(','):
                                part = part.strip()
                                if part:
                                    uris.append(part)
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid URI list format: expected string or list"
                        )
                    
                    if not uris:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid URI list: no valid URIs found"
                        )
                    
                    space_record = self.space_manager.get_space(space_id)
                    if not space_record:
                        raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                    
                    space_impl = space_record.space_impl
                    backend = space_impl.get_db_space_impl()
                    if not backend:
                        raise HTTPException(status_code=500, detail="Backend implementation not available")
                    
                    backend_adapter = create_backend_adapter(backend)
                    deleted_count = await self.kgtypes_delete_processor.delete_kgtypes_batch(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_uris=uris
                    )
                    deleted_uris = uris[:deleted_count] if deleted_count > 0 else []
                    delete_method = f"URI list with {len(uris)} URIs"
                    
                elif document and document.graph:
                    # Delete KGTypes specified in document
                    uris_to_delete = []
                    for kgtype_obj in document.graph:
                        kgtype_uri = str(kgtype_obj.URI)
                        if kgtype_uri:
                            uris_to_delete.append(kgtype_uri)
                    
                    if not uris_to_delete:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid document: no valid URIs found in objects"
                        )
                    
                    space_record = self.space_manager.get_space(space_id)
                    if not space_record:
                        raise HTTPException(status_code=404, detail=f"Space {space_id} not found")
                    
                    space_impl = space_record.space_impl
                    backend = space_impl.get_db_space_impl()
                    if not backend:
                        raise HTTPException(status_code=500, detail="Backend implementation not available")
                    
                    backend_adapter = create_backend_adapter(backend)
                    deleted_count = await self.kgtypes_delete_processor.delete_kgtypes_batch(
                        backend=backend_adapter,
                        space_id=space_id,
                        graph_id=graph_id,
                        kgtype_uris=uris_to_delete
                    )
                    deleted_uris = uris_to_delete[:deleted_count] if deleted_count > 0 else []
                    delete_method = f"document with {len(uris_to_delete)} type definitions"
                
                # Ensure all URIs are strings (handle CombinedProperty from VitalSigns)
                deleted_uris_str = [str(u) for u in deleted_uris] if deleted_uris else []
                
                # Trigger background vector/FTS cleanup for deleted KGTypes
                if deleted_uris_str:
                    self._schedule_auto_sync(backend, space_id, graph_id, deleted_uris_str, operation="delete")
                
                self.logger.debug(f"Delete response - deleted_uris type: {type(deleted_uris)}, deleted_uris_str type: {type(deleted_uris_str)}")
                self.logger.debug(f"Delete response - deleted_uris: {deleted_uris}, deleted_uris_str: {deleted_uris_str}")
                
                return KGTypeDeleteResponse(
                    success=True,
                    message=f"Successfully deleted {deleted_count} KG types via {delete_method} from graph '{graph_id}' in space '{space_id}'",
                    deleted_count=deleted_count,
                    deleted_uris=deleted_uris_str
                )
                
            except Exception as e:
                # Handle service-level errors
                if "not found" in str(e).lower():
                    raise HTTPException(
                        status_code=404,
                        detail=f"One or more KGTypes not found: {str(e)}"
                    )
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to delete KGTypes: {str(e)}"
                    )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting KG types: {str(e)}"
            )


    async def _get_type_relationships(
        self,
        space_id: str,
        graph_id: str,
        type_uri: str,
        current_user: Dict,
    ) -> KGTypeRelationshipsResponse:
        """Get all type-level edges connected to a type."""
        try:
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=500, detail=f"Space {space_id} not available")

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")

            backend_adapter = create_backend_adapter(backend)
            rel_data = await self.kgtypes_read_processor.get_type_relationships(
                backend=backend_adapter,
                space_id=space_id,
                graph_id=graph_id,
                type_uri=type_uri,
            )

            return KGTypeRelationshipsResponse(
                success=True,
                message=f"Found {len(rel_data['edges'])} edges for type '{type_uri}'",
                source_type=rel_data['source_type'],
                edges=rel_data['edges'],
                connected_types=rel_data['connected_types'],
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting type relationships: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error getting type relationships: {str(e)}"
            )


    # ── Helper: get backend adapter ──────────────────────────────────

    async def _get_backend_adapter(self, space_id: str):
        """Get backend adapter for a space, raising HTTPException on failure."""
        space_record = await self.space_manager.get_space_or_load(space_id)
        if not space_record:
            raise HTTPException(status_code=500, detail=f"Space {space_id} not available")
        space_impl = space_record.space_impl
        backend = space_impl.get_db_space_impl()
        if not backend:
            raise HTTPException(status_code=500, detail="Backend implementation not available")
        return create_backend_adapter(backend)

    # ── Relationship Create/Delete ─────────────────────────────────

    async def _create_type_relationship(
        self, space_id: str, graph_id: str, type_uri: str,
        edge_type: str, target_uri: str, current_user: Dict,
    ) -> KGTypeRelationshipCreateResponse:
        """Create a type-level edge."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            result = await self.kgtypes_read_processor.create_type_relationship(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id,
                type_uri=type_uri, edge_type=edge_type, target_uri=target_uri,
            )
            return KGTypeRelationshipCreateResponse(
                success=True,
                message=f"Created {edge_type} edge from {type_uri} to {target_uri}",
                edge_uri=result['edge_uri'],
                edge_type=result['edge_type'],
                source_uri=result['source_uri'],
                destination_uri=result['destination_uri'],
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating type relationship: {e}")
            raise HTTPException(status_code=500, detail=f"Error creating type relationship: {str(e)}")

    async def _delete_type_relationship(
        self, space_id: str, graph_id: str, type_uri: str,
        edge_uri: str, current_user: Dict,
    ) -> KGTypeRelationshipDeleteResponse:
        """Delete a type-level edge."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            deleted = await self.kgtypes_read_processor.delete_type_relationship(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id,
                type_uri=type_uri, edge_uri=edge_uri,
            )
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Edge {edge_uri} not found or not associated with type {type_uri}")
            return KGTypeRelationshipDeleteResponse(
                success=True,
                message=f"Deleted edge {edge_uri}",
                deleted=True,
                edge_uri=edge_uri,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting type relationship: {e}")
            raise HTTPException(status_code=500, detail=f"Error deleting type relationship: {str(e)}")

    # ── Documentation CRUD ─────────────────────────────────────────

    async def _get_type_documentation(
        self, space_id: str, graph_id: str, type_uri: str, current_user: Dict,
    ) -> KGTypeDocumentationResponse:
        """Get documentation for a type."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            result = await self.kgtypes_read_processor.get_type_documentation(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id,
                type_uri=type_uri,
            )
            return KGTypeDocumentationResponse(
                success=True,
                message="Documentation found" if result['has_documentation'] else "No documentation",
                type_uri=result['type_uri'],
                content=result.get('content'),
                document_uri=result.get('document_uri'),
                has_documentation=result['has_documentation'],
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting type documentation: {e}")
            raise HTTPException(status_code=500, detail=f"Error getting type documentation: {str(e)}")

    async def _update_type_documentation(
        self, space_id: str, graph_id: str, type_uri: str,
        content: str, current_user: Dict,
    ) -> KGTypeDocumentationUpdateResponse:
        """Create or update documentation for a type."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            result = await self.kgtypes_read_processor.update_type_documentation(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id,
                type_uri=type_uri, content=content,
            )
            action = "Created" if result['created'] else "Updated"
            return KGTypeDocumentationUpdateResponse(
                success=True,
                message=f"{action} documentation for {type_uri}",
                type_uri=result['type_uri'],
                document_uri=result['document_uri'],
                created=result['created'],
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating type documentation: {e}")
            raise HTTPException(status_code=500, detail=f"Error updating type documentation: {str(e)}")

    async def _delete_type_documentation(
        self, space_id: str, graph_id: str, type_uri: str, current_user: Dict,
    ) -> KGTypeDocumentationDeleteResponse:
        """Delete documentation for a type."""
        try:
            backend_adapter = await self._get_backend_adapter(space_id)
            deleted = await self.kgtypes_read_processor.delete_type_documentation(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id,
                type_uri=type_uri,
            )
            return KGTypeDocumentationDeleteResponse(
                success=True,
                message="Documentation deleted" if deleted else "No documentation to delete",
                type_uri=type_uri,
                deleted=deleted,
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting type documentation: {e}")
            raise HTTPException(status_code=500, detail=f"Error deleting type documentation: {str(e)}")

    # ── Search ─────────────────────────────────────────────────────

    # Map short type names to full URIs
    TYPE_FILTER_MAP = {
        'frame': 'http://vital.ai/ontology/haley-ai-kg#KGFrameType',
        'entity': 'http://vital.ai/ontology/haley-ai-kg#KGEntityType',
        'slot': 'http://vital.ai/ontology/haley-ai-kg#KGSlotType',
        'relation': 'http://vital.ai/ontology/haley-ai-kg#KGRelationType',
        'role': 'http://vital.ai/ontology/haley-ai-kg#KGSlotRoleType',
    }

    async def _search_types(
        self, space_id: str, graph_id: str, query: str,
        type_filter: Optional[str], search_mode: str, current_user: Dict,
        *, alpha: Optional[float] = None,
    ) -> KGTypeSearchResponse:
        """Search types by keyword, FTS, vector, or hybrid.

        All modes go through the SPARQL pipeline — FTS/vector/hybrid
        use ``vg:textSearch`` / ``vg:vectorSimilarity`` /
        ``vg:hybridSearch`` custom functions that the SQL emitter
        translates into PostgreSQL queries against the vector table.
        """
        try:
            backend_adapter = await self._get_backend_adapter(space_id)

            # Resolve short type name to URI if needed
            resolved_type = self.TYPE_FILTER_MAP.get(type_filter, type_filter) if type_filter else None

            result = await self.kgtypes_read_processor.search_types(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id,
                query=query, type_filter=resolved_type, search_mode=search_mode,
                alpha=alpha,
            )

            return KGTypeSearchResponse(
                success=True,
                message=f"Found {result['count']} types matching '{query}'",
                types=result['types'],
                count=result['count'],
                search_mode=result['search_mode'],
                query=result['query'],
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error searching types: {e}")
            raise HTTPException(status_code=500, detail=f"Error searching types: {str(e)}")


def create_kgtypes_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG types router."""
    endpoint = KGTypesEndpoint(space_manager, auth_dependency)
    return endpoint.router
