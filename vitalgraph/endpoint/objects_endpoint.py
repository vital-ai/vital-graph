"""
Graph Objects REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing graph objects.
Graph objects represent RDF resources with their associated triples.
"""

import asyncio
from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, HTTPException, Depends, Query, Request, Response, Body
from pydantic import BaseModel, Field
import logging

from ..endpoint.impl.objects_impl import ObjectsImpl
from vitalgraph.model.quad_model import Quad, QuadRequest, QuadResponse, QuadResultsResponse
from vitalgraph.utils.quad_format_utils import quad_list_to_graphobjects, graphobjects_to_quad_list
from vitalgraph.model.objects_model import ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse


class GraphObjectsEndpoint:
    """Graph Objects endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self.logger = logging.getLogger(f"{__name__}.GraphObjectsEndpoint")
        
        # Initialize object service
        self.object_impl = ObjectsImpl(space_manager)
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes for graph objects management."""
        
        @self.router.get("/objects", tags=["Objects"])
        async def list_or_get_objects_route(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            page_size: int = Query(100, ge=1, le=1000, description="Number of objects per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            uri: Optional[str] = Query(None, description="Single object URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of object URIs"),
            vitaltype_filter: Optional[str] = Query(None, description="Filter by vitaltype URI"),
            search: Optional[str] = Query(None, description="Search text in object properties"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            return await self.list_or_get_objects(space_id, graph_id, page_size, offset, uri, uri_list, vitaltype_filter, search, current_user)
        
        @self.router.post("/objects", response_model=ObjectCreateResponse, tags=["Objects"])
        async def create_objects_route(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            body: QuadRequest = Body(..., description="GraphObjects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Create objects from JSON Quads."""
            quads = body.quads
            return await self._create_objects(space_id, graph_id, quads, current_user)
        
        @self.router.put("/objects", response_model=ObjectUpdateResponse, tags=["Objects"])
        async def update_object_route(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            body: QuadRequest = Body(..., description="GraphObjects serialized as JSON Quads"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            """Update objects from JSON Quads."""
            quads = body.quads
            return await self._update_objects(space_id, graph_id, quads, current_user)
        
        @self.router.delete("/objects", response_model=ObjectDeleteResponse, tags=["Objects"])
        async def delete_objects_route(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: Optional[str] = Query(None, description="Single object URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of object URIs to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            return await self.delete_objects(space_id, graph_id, uri, uri_list, current_user)
    
    async def list_or_get_objects(self, space_id: str, graph_id: Optional[str] = None, page_size: int = 100, 
                                 offset: int = 0, uri: Optional[str] = None, uri_list: Optional[str] = None,
                                 vitaltype_filter: Optional[str] = None, search: Optional[str] = None,
                                 current_user: Dict = None):
        """
        List graph objects with pagination, or get specific objects by URI(s).
        
        - If uri is provided: returns single object
        - If uri_list is provided: returns multiple objects
        - Otherwise: returns paginated list of all objects
        """
        
        # Handle single URI retrieval
        if uri:
            return await self._get_object_by_uri(space_id, graph_id, uri, current_user)
        
        # Handle multiple URI retrieval
        if uri_list:
            uris = [u.strip() for u in uri_list.split(',') if u.strip()]
            return await self._get_objects_by_uris(space_id, graph_id, uris, current_user)
        
        # Handle paginated listing
        return await self._list_objects(space_id, graph_id, page_size, offset, vitaltype_filter, search, current_user)
    
    async def delete_objects(self, space_id: str, graph_id: Optional[str] = None, uri: Optional[str] = None,
                           uri_list: Optional[str] = None, current_user: Dict = None):
        """
        Delete objects by URI or URI list.
        """
        if uri:
            return await self._delete_object_by_uri(space_id, graph_id, uri, current_user)
        elif uri_list:
            uris = [u.strip() for u in uri_list.split(',') if u.strip()]
            return await self._delete_objects_by_uris(space_id, graph_id, uris, current_user)
        else:
            raise HTTPException(status_code=400, detail="Either 'uri' or 'uri_list' parameter is required")
    
    async def _list_objects(self, space_id: str, graph_id: Optional[str], page_size: int, offset: int, 
                           vitaltype_filter: Optional[str], search: Optional[str], current_user: Dict) -> QuadResponse:
        """List graph objects with pagination."""
        try:
            graph_objects, total_count = await self.object_impl.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                vitaltype_filter=vitaltype_filter,
                search_text=search
            )
            
            quads = await asyncio.to_thread(graphobjects_to_quad_list, graph_objects, graph_id)
            return QuadResponse(
                total_count=total_count,
                page_size=page_size,
                offset=offset,
                results=quads,
            )
            
        except Exception as e:
            self.logger.error(f"Error listing objects: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list objects: {str(e)}")
    
    async def _get_object_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> QuadResultsResponse:
        """Get single object by URI."""
        try:
            graph_objects = await self.object_impl.get_object_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            quads = (await asyncio.to_thread(graphobjects_to_quad_list, graph_objects, graph_id)) if graph_objects else []
            return QuadResultsResponse(
                total_count=len(graph_objects) if graph_objects else 0,
                results=quads,
            )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting object {uri}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get object: {str(e)}")
    
    async def _get_objects_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> QuadResultsResponse:
        """Get multiple objects by URI list."""
        try:
            graph_objects = await self.object_impl.get_objects_by_uris(
                space_id=space_id,
                uris=uris,
                graph_id=graph_id
            )
            
            quads = (await asyncio.to_thread(graphobjects_to_quad_list, graph_objects, graph_id)) if graph_objects else []
            return QuadResultsResponse(
                total_count=len(graph_objects) if graph_objects else 0,
                results=quads,
            )
            
        except Exception as e:
            self.logger.error(f"Error getting objects by URIs: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get objects: {str(e)}")
    
    async def _create_objects(self, space_id: str, graph_id: Optional[str], quads: List[Quad], current_user: Dict) -> ObjectCreateResponse:
        """Create objects from quads."""
        try:
            if not graph_id:
                raise HTTPException(status_code=400, detail="graph_id is required for object creation")
            graph_objects = quad_list_to_graphobjects(quads)
            if not graph_objects:
                raise HTTPException(status_code=400, detail="No valid objects found in request")
            
            created_uris = await self.object_impl.create_objects_batch(
                space_id=space_id,
                graph_objects=graph_objects,
                graph_id=graph_id
            )
            return ObjectCreateResponse(
                message=f"Successfully created {len(created_uris)} graph objects",
                created_count=len(created_uris),
                created_uris=created_uris
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating objects: {e}")
            raise HTTPException(status_code=500, detail=f"Error creating graph objects: {str(e)}")

    async def _update_objects(self, space_id: str, graph_id: Optional[str], quads: List[Quad], current_user: Dict) -> ObjectUpdateResponse:
        """Update objects from quads."""
        try:
            if not graph_id:
                raise HTTPException(status_code=400, detail="graph_id is required for object update")
            graph_objects = quad_list_to_graphobjects(quads)
            if not graph_objects:
                raise HTTPException(status_code=400, detail="No valid objects found in request")
            
            updated_uris = await self.object_impl.update_objects_batch(
                space_id=space_id,
                graph_objects=graph_objects,
                graph_id=graph_id
            )
            
            updated_uri = str(graph_objects[0].URI) if graph_objects else "unknown"
            
            return ObjectUpdateResponse(
                message=f"Successfully updated {len(updated_uris)} graph objects",
                updated_uri=updated_uri
            )
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating objects: {e}")
            raise HTTPException(status_code=500, detail=f"Error updating graph objects: {str(e)}")

    async def _delete_object_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> ObjectDeleteResponse:
        """Delete single graph object by URI using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Deleting graph object '{uri}' from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for object deletion"
                )
            
            # Delete single object by URI
            deleted_count = await self.object_impl.delete_objects(
                space_id=space_id,
                object_uris=[uri],
                graph_id=graph_id
            )
            
            if deleted_count > 0:
                self.logger.info(f"Deleted graph object: {uri}")
                return ObjectDeleteResponse(
                    message=f"Successfully deleted graph object '{uri}' from graph '{graph_id}' in space '{space_id}'",
                    deleted_count=deleted_count,
                    deleted_uris=[uri]
                )
            else:
                # Return empty response instead of 404 - service should never return 404 for valid requests
                return ObjectDeleteResponse(
                    success=True,
                    message=f"Graph object '{uri}' not found - no deletion needed",
                    deleted_count=0,
                    deleted_uris=[]
                )
                
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting graph object: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting graph object: {str(e)}"
            )
    
    async def _delete_objects_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> ObjectDeleteResponse:
        """Delete multiple graph objects by URI list using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Deleting {len(uris)} graph objects from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for object deletion"
                )
            
            # Delete multiple objects by URI list
            deleted_count = await self.object_impl.delete_objects(
                space_id=space_id,
                object_uris=uris,
                graph_id=graph_id
            )
            
            self.logger.info(f"Successfully deleted {deleted_count} graph objects")
            
            return ObjectDeleteResponse(
                message=f"Successfully deleted {deleted_count} graph objects from graph '{graph_id}' in space '{space_id}'",
                deleted_count=deleted_count,
                deleted_uris=uris[:deleted_count]  # Only return the URIs that were actually deleted
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting graph objects: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting graph objects: {str(e)}"
            )


def create_objects_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the graph objects router."""
    endpoint = GraphObjectsEndpoint(space_manager, auth_dependency)
    return endpoint.router
