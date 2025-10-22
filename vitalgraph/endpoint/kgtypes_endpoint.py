"""KG Types Endpoint for VitalGraph

Implements REST API endpoints for KG type management operations using JSON-LD 1.1 format.
Based on the planned API specification in docs/planned_rest_api_endpoints.md
"""

from typing import Dict, List, Any, Optional, Union
from fastapi import APIRouter, HTTPException, Depends, Query, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import logging
from datetime import datetime

from pyld import jsonld

from ..endpoint.impl.kgtype_impl import KGTypeImpl
from ..model.jsonld_model import JsonLdDocument
from ..model.kgtypes_model import KGTypeFilter
from ..model.kgtypes_model import (
    KGTypeListRequest,
    KGTypeListResponse,
    KGTypeCreateResponse,
    KGTypeUpdateResponse,
    KGTypeDeleteResponse
)


class KGTypesEndpoint:
    """KG Types endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.KGTypesEndpoint")
        self.router = APIRouter()
        
        # Initialize KGType service
        self.kgtype_impl = KGTypeImpl(space_manager)
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup KG types routes."""
        
        # GET /api/graphs/kgtypes - List KG types with pagination/filtering
        @self.router.get(
            "/kgtypes",
            response_model=KGTypeListResponse,
            tags=["KG Types"],
            summary="List KG Types",
            description="List KG types in graph with pagination and filtering options"
        )
        async def list_kgtypes(
            space_id: str = Query(..., description="Space ID"),
            graph_id: str = Query(..., description="Graph ID"),
            page_size: int = Query(10, ge=1, le=100, description="Number of types per page"),
            offset: int = Query(0, ge=0, description="Number of types to skip"),
            search: Optional[str] = Query(None, description="Search text to filter types"),
            uri: Optional[str] = Query(None, description="Get specific type by URI"),
            uri_list: Optional[str] = Query(None, description="Get multiple types by comma-separated URI list"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._list_kgtypes(
                space_id, graph_id, page_size, offset, search, uri, uri_list, current_user
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
            request: KGTypeListRequest = Body(..., description="JSON-LD document with KG types to create"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._create_kgtypes(space_id, graph_id, request.document, current_user)
        
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
            request: KGTypeListRequest = Body(..., description="JSON-LD document with KG types to update"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._update_kgtypes(space_id, graph_id, request.document, current_user)
        
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
            uri_list: Optional[str] = Query(None, description="Delete multiple types by comma-separated URI list"),
            request: Optional[KGTypeListRequest] = Body(None, description="JSON-LD document with KG types to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self._delete_kgtypes(space_id, graph_id, uri, uri_list, request.document if request else None, current_user)
    
    async def _list_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        page_size: int,
        offset: int,
        search: Optional[str],
        uri: Optional[str],
        uri_list: Optional[str],
        current_user: Dict
    ) -> KGTypeListResponse:
        """List KG types with filtering and pagination using JSON-LD format."""
        
        try:
            self.logger.info(f"Listing KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Handle specific URI or URI list requests
            if uri:
                return await self._get_kgtype_by_uri(space_id, graph_id, uri, current_user)
            elif uri_list:
                return await self._get_kgtypes_by_uris(space_id, graph_id, uri_list, current_user)
            
            # Create filter
            filters = KGTypeFilter(
                search_text=search,
                subject_uri=None
            )
            
            # Get complete JSON-LD document from implementation (now returns complete document)
            jsonld_document, total_count = await self.kgtype_impl.list_kgtypes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                filters=filters
            )
            
            # Create JsonLdDocument from the returned complete document
            jsonld_doc = JsonLdDocument(**jsonld_document)
            
            return KGTypeListResponse(
                data=jsonld_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset,
                pagination={
                    "page": (offset // page_size) + 1,
                    "limit": page_size,
                    "total": total_count,
                    "pages": (total_count + page_size - 1) // page_size
                },
                meta={
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "version": "1.0",
                    "format": "JSON-LD 1.1"
                }
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
        current_user: Dict
    ) -> KGTypeListResponse:
        """Get a specific KGType by URI."""
        try:
            kgtype = await self.kgtype_impl.get_kgtype_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            if not kgtype:
                raise HTTPException(
                    status_code=404,
                    detail=f"KGType with URI '{uri}' not found"
                )
            
            # Use complete JSON-LD document from implementation (now returns complete document)
            jsonld_doc = JsonLdDocument(**kgtype)
            
            return KGTypeListResponse(
                data=jsonld_doc,
                total_count=1,
                page_size=1,
                offset=0,
                pagination={
                    "page": 1,
                    "limit": 1,
                    "total": 1,
                    "pages": 1
                },
                meta={
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "version": "1.0",
                    "format": "JSON-LD 1.1"
                }
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
        current_user: Dict
    ) -> KGTypeListResponse:
        """Get multiple KGTypes by URI list."""
        try:
            uris = [u.strip() for u in uri_list.split(',') if u.strip()]
            
            # Get complete JSON-LD document from implementation (now returns complete document)
            jsonld_document = await self.kgtype_impl.get_kgtypes_by_uris(
                space_id=space_id,
                uris=uris,
                graph_id=graph_id
            )
            
            # Create JsonLdDocument from the returned complete document
            jsonld_doc = JsonLdDocument(**jsonld_document)
            
            # Get count from the JSON-LD document
            graph_objects = jsonld_document.get("@graph", [])
            object_count = len(graph_objects)
            
            return KGTypeListResponse(
                data=jsonld_doc,
                total_count=object_count,
                page_size=object_count,
                offset=0,
                pagination={
                    "page": 1,
                    "limit": object_count,
                    "total": object_count,
                    "pages": 1
                },
                meta={
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "version": "1.0",
                    "format": "JSON-LD 1.1"
                }
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
        document: JsonLdDocument,
        current_user: Dict
    ) -> KGTypeCreateResponse:
        """Create KG types from JSON-LD document using proper VitalGraph patterns."""
        
        try:
            self.logger.info(f"Creating KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Log the incoming document data for debugging

            self.logger.debug(f"🔍 RECEIVED DOCUMENT TYPE: {type(document)}")
            self.logger.debug(f"🔍 DOCUMENT DATA: {document}")
            if hasattr(document, 'graph'):
                self.logger.debug(f"🔍 DOCUMENT GRAPH TYPE: {type(document.graph)}")
                self.logger.debug(f"🔍 DOCUMENT GRAPH DATA: {document.graph}")
            if hasattr(document, '__dict__'):
                self.logger.debug(f"🔍 DOCUMENT DICT: {document.__dict__}")
            
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
            
            # Validate input document
            if not document or not document.graph:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: document and @graph are required"
                )
            
            # Always use batch operations for consistency and to avoid manual JSON-LD document creation
            try:
                # Convert request to dict format for batch processing (VitalSigns native functionality)
                jsonld_document = document.model_dump(by_alias=True)
                created_uris = await self.kgtype_impl.create_kgtypes_batch(
                    space_id=space_id,
                    jsonld_document=jsonld_document,
                    graph_id=graph_id
                )
                
                created_count = len(created_uris)
                self.logger.info(f"Created {created_count} KGTypes: {created_uris}")
                
                return KGTypeCreateResponse(
                    message=f"Successfully created {created_count} KG type definitions in graph '{graph_id}' in space '{space_id}'",
                    created_count=created_count,
                    created_uris=created_uris
                )
                
            except Exception as e:
                self.logger.error(f"Create operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create KGTypes: {str(e)}"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error creating KG types: {str(e)}"
            )
    
    async def _update_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        document: JsonLdDocument,
        current_user: Dict
    ) -> KGTypeUpdateResponse:
        """Update KG types from JSON-LD document using proper VitalGraph patterns."""
        
        try:
            self.logger.info(f"Updating KG types in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
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
            
            # Validate input document
            if not document or not document.graph:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: document and @graph are required"
                )
            
            # Validate that all objects have URIs before update
            for i, kgtype_obj in enumerate(document.graph):
                kgtype_uri = kgtype_obj.get('@id') or kgtype_obj.get('URI')
                if not kgtype_uri:
                    raise HTTPException(
                        status_code=400,
                        detail=f"KGType at index {i} missing URI (@id or URI field) - required for update"
                    )
            
            # Always use batch operations for consistency and to avoid manual JSON-LD document creation
            try:
                # Convert request to dict format for batch processing (VitalSigns native functionality)
                jsonld_document = document.model_dump(by_alias=True)
                updated_uris = await self.kgtype_impl.update_kgtypes_batch(
                    space_id=space_id,
                    jsonld_document=jsonld_document,
                    graph_id=graph_id
                )
                
                updated_count = len(updated_uris)
                self.logger.info(f"Updated {updated_count} KGTypes: {updated_uris}")
                
                # Return the first URI as the primary updated URI
                primary_uri = updated_uris[0] if updated_uris else ""
                return KGTypeUpdateResponse(
                    message=f"Successfully updated {updated_count} KG type definitions in graph '{graph_id}' in space '{space_id}'",
                    updated_uri=primary_uri
                )
                
            except Exception as e:
                self.logger.error(f"Update operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to update KGTypes: {str(e)}"
                )
        
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating KG types: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error updating KG types: {str(e)}"
            )
    
    async def _delete_kgtypes(
        self,
        space_id: str,
        graph_id: str,
        uri: Optional[str],
        uri_list: Optional[str],
        document: Optional[JsonLdDocument],
        current_user: Dict
    ) -> KGTypeDeleteResponse:
        """Delete KG types by URI, URI list, or JSON-LD document using proper VitalGraph patterns."""
        
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
                    detail="Invalid request: must provide uri, uri_list, or document with @graph"
                )
            
            deleted_count = 0
            deleted_uris = []
            delete_method = ""
            
            try:
                if uri:
                    # Delete single KGType by URI
                    # Ensure URI is a string (handle CombinedProperty from VitalSigns)
                    uri_str = str(uri) if uri else uri
                    success = await self.kgtype_impl.delete_kgtype(
                        space_id=space_id,
                        kgtype_uri=uri_str,
                        graph_id=graph_id
                    )
                    if success:
                        deleted_count = 1
                        deleted_uris = [uri_str]
                        self.logger.info(f"Deleted KGType: {uri_str}")
                    delete_method = f"URI '{uri_str}'"
                        
                elif uri_list:
                    # Delete multiple KGTypes by URI list
                    uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                    if not uris:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid URI list: no valid URIs found"
                        )
                    
                    deleted_count = await self.kgtype_impl.delete_kgtypes(
                        space_id=space_id,
                        kgtype_uris=uris,
                        graph_id=graph_id
                    )
                    deleted_uris = uris[:deleted_count] if deleted_count > 0 else []
                    delete_method = f"URI list with {len(uris)} URIs"
                    
                elif document and document.graph:
                    # Delete KGTypes specified in JSON-LD document
                    uris_to_delete = []
                    for kgtype_obj in document.graph:
                        kgtype_uri = kgtype_obj.get('@id') or kgtype_obj.get('URI')
                        if kgtype_uri:
                            uris_to_delete.append(kgtype_uri)
                    
                    if not uris_to_delete:
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid document: no valid URIs found in @graph objects"
                        )
                    
                    deleted_count = await self.kgtype_impl.delete_kgtypes(
                        space_id=space_id,
                        kgtype_uris=uris_to_delete,
                        graph_id=graph_id
                    )
                    deleted_uris = uris_to_delete[:deleted_count] if deleted_count > 0 else []
                    delete_method = f"JSON-LD document with {len(uris_to_delete)} type definitions"
                
                # Ensure all URIs are strings (handle CombinedProperty from VitalSigns)
                deleted_uris_str = [str(u) for u in deleted_uris] if deleted_uris else []
                
                self.logger.debug(f"Delete response - deleted_uris type: {type(deleted_uris)}, deleted_uris_str type: {type(deleted_uris_str)}")
                self.logger.debug(f"Delete response - deleted_uris: {deleted_uris}, deleted_uris_str: {deleted_uris_str}")
                
                return KGTypeDeleteResponse(
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
