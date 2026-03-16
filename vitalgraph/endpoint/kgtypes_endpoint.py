"""KG Types Endpoint for VitalGraph

Implements REST API endpoints for KG type management operations.
Based on the planned API specification in docs/planned_rest_api_endpoints.md
"""

import asyncio
from typing import Dict, Any, Optional, List, Union
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
    KGTypeCreateRequest, KGTypeUpdateRequest, KGTypeBatchDeleteRequest
)


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
    
    
    def _setup_routes(self):
        """Setup KG types routes."""
        
        # GET /api/graphs/kgtypes - List KG types with pagination/filtering
        @self.router.get(
            "/kgtypes",
            response_model=None,
            tags=["KG Types"],
            summary="List KG Types",
            description="List KG types in graph with pagination and filtering options. Returns KGTypeGetResponse for single URI, KGTypeListResponse for lists/searches."
        )
        async def list_kgtypes(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=100, description="Number of types per page"),
            offset: int = Query(0, ge=0, description="Number of types to skip"),
            search: Optional[str] = Query(None, description="Search text to filter types"),
            uri: Optional[str] = Query(None, description="Get specific type by URI"),
            uri_list: Optional[str] = Query(None, description="Get multiple types by comma-separated URI list"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
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
                    search=search,
                )
        
        # POST /api/graphs/kgtypes - Create new KG types
        @self.router.post(
            "/kgtypes",
            response_model=KGTypeCreateResponse,
            tags=["KG Types"],
            summary="Create KG Types",
            description="Create new KG types in the specified graph"
        )
        async def create_kgtypes(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            body: QuadRequest = Body(..., description="KGType objects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            quads = body.quads
            return await self._create_kgtypes(space_id, graph_id, quads, current_user)
        
        # PUT /api/graphs/kgtypes - Update KG types
        @self.router.put(
            "/kgtypes",
            response_model=KGTypeUpdateResponse,
            tags=["KG Types"],
            summary="Update KG Types",
            description="Update existing KG types in the specified graph"
        )
        async def update_kgtypes(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            body: QuadRequest = Body(..., description="KGType objects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            quads = body.quads
            return await self._update_kgtypes(space_id, graph_id, quads, current_user)
        
        # DELETE /api/graphs/kgtypes - Delete KG types
        @self.router.delete(
            "/kgtypes",
            response_model=KGTypeDeleteResponse,
            tags=["KG Types"],
            summary="Delete KG Types",
            description="Delete KG types from the specified graph"
        )
        async def delete_kgtypes(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            uri: Optional[str] = Query(None, description="Delete specific type by URI"),
            uri_list: Optional[List[str]] = Query(None, description="Delete multiple types by URI list"),
            request: Optional[KGTypeBatchDeleteRequest] = Body(None, description="Batch delete request with Union data support"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._delete_kgtypes(space_id, graph_id, uri, uri_list, request.data if request else None, current_user)
    
    async def _list_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        page_size: int,
        offset: int,
        filter: Optional[str] = None,
        current_user: Dict = None,
        search: Optional[str] = None,
    ) -> QuadResponse:
        """List KG types with filtering and pagination."""
        
        try:
            self.logger.info(f"Listing KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Get complete document from atomic processor
            space_record = self.space_manager.get_space(space_id)
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
                search=search_filter
            )
            
            self.logger.info(f"🔍 LIST: Received {len(triples)} RDFLib triples, total_count: {total_count}")
            
            graph_objects = (await asyncio.to_thread(GraphObject.from_triples_list, triples)) if triples else []
            quads = graphobjects_to_quad_list(graph_objects, graph_id)
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
            space_record = self.space_manager.get_space(space_id)
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
            
            quads = graphobjects_to_quad_list([kgtype_object], graph_id)
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
            space_record = self.space_manager.get_space(space_id)
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
            
            quads = graphobjects_to_quad_list(kgtype_objects, graph_id)
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

            if not self.space_manager or not self.space_manager.has_space(space_id):
                raise HTTPException(status_code=404, detail=f"Space '{space_id}' not found")
            space_record = self.space_manager.get_space(space_id)
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

            if not self.space_manager or not self.space_manager.has_space(space_id):
                raise HTTPException(status_code=404, detail=f"Space '{space_id}' not found")
            space_record = self.space_manager.get_space(space_id)
            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            backend_adapter = create_backend_adapter(backend)

            kgtype_updates = {}
            for kgtype_obj in kgtype_objects:
                uri = str(kgtype_obj.URI)
                kgtype_updates[uri] = [kgtype_obj]
            updated_uris = await self.kgtypes_update_processor.update_kgtypes_batch(
                backend=backend_adapter, space_id=space_id, graph_id=graph_id, kgtype_updates=kgtype_updates)
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
            
            # Validate space exists (same as triples endpoint)
            if not self.space_manager.has_space(space_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Space '{space_id}' not found"
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
                    space_record = self.space_manager.get_space(space_id)
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


def create_kgtypes_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG types router."""
    endpoint = KGTypesEndpoint(space_manager, auth_dependency)
    return endpoint.router
