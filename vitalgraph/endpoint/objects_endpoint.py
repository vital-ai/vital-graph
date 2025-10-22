"""
Graph Objects REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing graph objects using JSON-LD 1.1 format.
Graph objects represent RDF resources with their associated triples.
"""

from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
import pyld
from pyld import jsonld
import logging

from ..endpoint.impl.object_impl import ObjectImpl
from ..model.jsonld_model import JsonLdDocument
from ..model.objects_model import (
    ObjectsResponse,
    ObjectCreateResponse,
    ObjectUpdateResponse,
    ObjectDeleteResponse
)


class GraphObjectsEndpoint:
    """Graph Objects endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self.logger = logging.getLogger(f"{__name__}.GraphObjectsEndpoint")
        
        # Initialize object service
        self.object_impl = ObjectImpl(space_manager)
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes for graph objects management."""
        
        @self.router.get("/objects", response_model=Union[ObjectsResponse, JsonLdDocument], tags=["Objects"])
        async def list_or_get_objects(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            page_size: int = Query(100, ge=1, le=1000, description="Number of objects per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            uri: Optional[str] = Query(None, description="Single object URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of object URIs"),
            vitaltype_filter: Optional[str] = Query(None, description="Filter by vitaltype URI"),
            search: Optional[str] = Query(None, description="Search text in object properties"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
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
        
        @self.router.post("/objects", response_model=ObjectCreateResponse, tags=["Objects"])
        async def create_objects(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Create new graph objects from JSON-LD document.
            Returns error if any subject URI already exists.
            """
            return await self._create_objects(space_id, graph_id, request, current_user)
        
        @self.router.put("/objects", response_model=ObjectUpdateResponse, tags=["Objects"])
        async def update_object(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Update object (deletes existing object with subject URI first, then inserts replacement).
            """
            return await self._update_object(space_id, graph_id, request, current_user)
        
        @self.router.delete("/objects", response_model=ObjectDeleteResponse, tags=["Objects"])
        async def delete_objects(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: Optional[str] = Query(None, description="Single object URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of object URIs to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
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
                           vitaltype_filter: Optional[str], search: Optional[str], current_user: Dict) -> ObjectsResponse:
        """List graph objects with pagination using ObjectService."""
        try:
            # Get JSON-LD document from service (now returns complete document)
            jsonld_document, total_count = await self.object_impl.list_objects(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                vitaltype_filter=vitaltype_filter,
                search_text=search
            )
            
            # Create JsonLdDocument from the returned document
            objects_doc = JsonLdDocument(**jsonld_document)
            
            return ObjectsResponse(
                objects=objects_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing objects: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list objects: {str(e)}")
    
    async def _get_object_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> JsonLdDocument:
        """Get single object by URI using ObjectService."""
        try:
            # Get complete JSON-LD document from service (now returns complete document)
            jsonld_document = await self.object_impl.get_object_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            if not jsonld_document:
                raise HTTPException(
                    status_code=404,
                    detail=f"Object with URI {uri} not found"
                )
            
            # Create JsonLdDocument from the returned complete document
            return JsonLdDocument(**jsonld_document)
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting object {uri}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get object: {str(e)}")
    
    async def _get_objects_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> JsonLdDocument:
        """Get multiple objects by URI list using ObjectService."""
        try:
            # Get complete JSON-LD document from service (now returns complete document)
            jsonld_document = await self.object_impl.get_objects_by_uris(
                space_id=space_id,
                uris=uris,
                graph_id=graph_id
            )
            
            # Create JsonLdDocument from the returned complete document
            return JsonLdDocument(**jsonld_document)
            
        except Exception as e:
            self.logger.error(f"Error getting objects by URIs: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to get objects: {str(e)}")
    
    async def _create_objects(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> ObjectCreateResponse:
        """Create new graph objects using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Creating graph objects in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for object creation"
                )
            
            # Validate input document
            if not request or not request.graph:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: document and @graph are required"
                )
            
            # Check if we have multiple objects to use batch operations
            if len(request.graph) > 1:
                # Use batch create for multiple objects
                try:
                    # Convert request to dict format for batch processing
                    jsonld_document = request.model_dump(by_alias=True)
                    created_uris = await self.object_impl.create_objects_batch(
                        space_id=space_id,
                        jsonld_document=jsonld_document,
                        graph_id=graph_id
                    )
                    
                    created_count = len(created_uris)
                    self.logger.info(f"Batch created {created_count} objects: {created_uris}")
                    
                    return ObjectCreateResponse(
                        message=f"Successfully created {created_count} graph objects in graph '{graph_id}' in space '{space_id}' using batch operation",
                        created_count=created_count,
                        created_uris=created_uris
                    )
                    
                except Exception as e:
                    self.logger.error(f"Batch create failed: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to create objects in batch: {str(e)}"
                    )
            else:
                # Use individual create for single object
                try:
                    # Convert request to dict format for processing
                    jsonld_document = request.model_dump(by_alias=True)
                    created_uris = await self.object_impl.create_objects(
                        space_id=space_id,
                        jsonld_document=jsonld_document,
                        graph_id=graph_id
                    )
                    
                    self.logger.info(f"Successfully created {len(created_uris)} graph objects")
                    
                    return ObjectCreateResponse(
                        message=f"Successfully created {len(created_uris)} graph objects in graph '{graph_id}' in space '{space_id}'",
                        created_count=len(created_uris),
                        created_uris=created_uris
                    )
                    
                except Exception as e:
                    self.logger.error(f"Individual create failed: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to create objects: {str(e)}"
                    )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating graph objects: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error creating graph objects: {str(e)}"
            )
    
    async def _update_object(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> ObjectUpdateResponse:
        """Update existing graph objects using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Updating graph objects in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for object update"
                )
            
            # Validate input document
            if not request or not request.graph:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: document and @graph are required"
                )
            
            # Check if we have multiple objects to use batch operations
            if len(request.graph) > 1:
                # Use batch update for multiple objects
                try:
                    # Validate that all objects have URIs before batch update
                    for i, object_obj in enumerate(request.graph):
                        object_uri = object_obj.get('@id') or object_obj.get('URI')
                        if not object_uri:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Object at index {i} missing URI (@id or URI field) - required for batch update"
                            )
                    
                    # Convert request to dict format for batch processing
                    jsonld_document = request.model_dump(by_alias=True)
                    updated_uris = await self.object_impl.update_objects_batch(
                        space_id=space_id,
                        jsonld_document=jsonld_document,
                        graph_id=graph_id
                    )
                    
                    updated_count = len(updated_uris)
                    self.logger.info(f"Batch updated {updated_count} objects: {updated_uris}")
                    
                    # For batch update, return the first URI (API compatibility)
                    updated_uri = updated_uris[0] if updated_uris else "unknown"
                    
                    return ObjectUpdateResponse(
                        message=f"Successfully updated {updated_count} graph objects in graph '{graph_id}' in space '{space_id}' using batch operation",
                        updated_uri=updated_uri
                    )
                    
                except Exception as e:
                    self.logger.error(f"Batch update failed: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to update objects in batch: {str(e)}"
                    )
            else:
                # Use individual update for single object
                try:
                    # Convert request to dict format for processing
                    jsonld_document = request.model_dump(by_alias=True)
                    updated_count = await self.object_impl.update_objects(
                        space_id=space_id,
                        jsonld_document=jsonld_document,
                        graph_id=graph_id
                    )
                    
                    # For single object update, return the first URI
                    updated_uri = request.graph[0].get('@id') or request.graph[0].get('URI') if request.graph else "unknown"
                    
                    self.logger.info(f"Successfully updated {updated_count} graph objects")
                    
                    return ObjectUpdateResponse(
                        message=f"Successfully updated {updated_count} graph objects in graph '{graph_id}' in space '{space_id}'",
                        updated_uri=updated_uri
                    )
                    
                except Exception as e:
                    self.logger.error(f"Individual update failed: {e}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to update objects: {str(e)}"
                    )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating graph objects: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error updating graph objects: {str(e)}"
            )
    
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
                raise HTTPException(
                    status_code=404,
                    detail=f"Graph object '{uri}' not found"
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
