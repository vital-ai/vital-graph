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

from ..endpoint.impl.objects_impl import ObjectsImpl
from ..model.jsonld_model import JsonLdDocument, JsonLdObject, JsonLdRequest
from vitalgraph.model.objects_model import ObjectsResponse, SingleObjectResponse, ObjectCreateResponse, ObjectUpdateResponse, ObjectDeleteResponse


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
        
        @self.router.get("/objects", response_model=Union[ObjectsResponse, SingleObjectResponse, JsonLdDocument], tags=["Objects"])
        async def list_or_get_objects_route(
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
            return await self.list_or_get_objects(space_id, graph_id, page_size, offset, uri, uri_list, vitaltype_filter, search, current_user)
        
        @self.router.post("/objects", response_model=ObjectCreateResponse, tags=["Objects"])
        async def create_objects_route(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Create objects from JSON-LD. Uses discriminated union to automatically handle single objects (JsonLdObject) or multiple objects (JsonLdDocument)."""
            return await self.create_objects(request, space_id, graph_id, current_user)
        
        @self.router.put("/objects", response_model=ObjectUpdateResponse, tags=["Objects"])
        async def update_object_route(
            request: JsonLdRequest,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """Update objects from JSON-LD. Uses discriminated union to automatically handle single objects (JsonLdObject) or multiple objects (JsonLdDocument)."""
            return await self.update_object(request, space_id, graph_id, current_user)
        
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
    
    async def create_objects(self, request: JsonLdRequest, space_id: str, graph_id: Optional[str] = None, 
                           current_user: Dict = None):
        """
        Create new graph objects from JSON-LD document or object.
        """
        return await self._create_objects(space_id, graph_id, request, current_user)
    
    async def update_object(self, request: JsonLdRequest, space_id: str, graph_id: Optional[str] = None,
                          current_user: Dict = None):
        """
        Update object (deletes existing object with subject URI first, then inserts replacement).
        """
        return await self._update_object(space_id, graph_id, request, current_user)
    
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
            
            # Handle single vs multiple objects - use JsonLdRequest discriminated union
            graph = jsonld_document.get('@graph', [])
            if len(graph) == 1:
                # Single object - use JsonLdObject
                single_obj = graph[0]
                single_obj['@context'] = jsonld_document.get('@context', {})
                single_obj['jsonld_type'] = 'object'  # Add discriminator field
                objects_doc = JsonLdObject(**single_obj)
            else:
                # Multiple objects or empty - use JsonLdDocument
                jsonld_document['jsonld_type'] = 'document'  # Add discriminator field
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
    
    async def _get_object_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> SingleObjectResponse:
        """Get single object by URI using ObjectService."""
        try:
            # Get complete JSON-LD document from service (now returns complete document)
            jsonld_document = await self.object_impl.get_object_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            if not jsonld_document:
                # Return empty response instead of 404 - service should never return 404 for valid requests
                return ObjectResponse(
                    success=True,
                    message=f"Object with URI {uri} not found",
                    data=None
                )
            
            # Extract the single object from the JSON-LD document
            graph = jsonld_document.get('@graph', [])
            if not graph:
                # Return empty response instead of 404 - service should never return 404 for valid requests
                return ObjectResponse(
                    success=True,
                    message=f"Object with URI {uri} not found in graph",
                    data=None
                )
            
            # Return the first (and should be only) object as SingleObjectResponse
            from vitalgraph.model.jsonld_model import JsonLdObject
            single_object = JsonLdObject(**graph[0])
            return SingleObjectResponse(object=single_object)
            
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
    
    async def _create_objects(self, space_id: str, graph_id: Optional[str], request: JsonLdRequest, current_user: Dict) -> ObjectCreateResponse:
        """Create new graph objects using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Creating graph objects in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for object creation"
                )
            
            # Convert JsonLdRequest to dict format
            jsonld_data = request.model_dump(by_alias=True)
            
            # Handle JsonLdObject (single object) vs JsonLdDocument (multiple objects)
            if isinstance(request, JsonLdObject):
                # Single object - wrap in @graph array for processing
                context = jsonld_data.pop('@context', {})
                jsonld_document = {
                    '@context': context,
                    '@graph': [jsonld_data]
                }
                object_count = 1
            else:
                # Already a document with @graph
                jsonld_document = jsonld_data
                object_count = len(jsonld_document.get('@graph', []))
            
            # Validate we have objects to create
            if object_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: no objects to create"
                )
            
            # Check if we have multiple objects to use batch operations
            if object_count > 1:
                # Use batch create for multiple objects
                try:
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
    
    async def _update_object(self, space_id: str, graph_id: Optional[str], request: JsonLdRequest, current_user: Dict) -> ObjectUpdateResponse:
        """Update existing graph objects using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Updating graph objects in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for object update"
                )
            
            # Convert JsonLdRequest to dict format
            jsonld_data = request.model_dump(by_alias=True)
            
            # Handle JsonLdObject (single object) vs JsonLdDocument (multiple objects)
            if isinstance(request, JsonLdObject):
                # Single object - wrap in @graph array for processing
                context = jsonld_data.pop('@context', {})
                jsonld_document = {
                    '@context': context,
                    '@graph': [jsonld_data]
                }
                object_count = 1
            else:
                # Already a document with @graph
                jsonld_document = jsonld_data
                object_count = len(jsonld_document.get('@graph', []))
            
            # Validate we have objects to update
            if object_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: no objects to update"
                )
            
            # Check if we have multiple objects to use batch operations
            if object_count > 1:
                # Use batch update for multiple objects
                try:
                    # Validate that all objects have URIs before batch update
                    for i, object_obj in enumerate(jsonld_document.get('@graph', [])):
                        object_uri = object_obj.get('@id') or object_obj.get('URI')
                        if not object_uri:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Object at index {i} missing URI (@id or URI field) - required for batch update"
                            )
                    
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
                    updated_count = await self.object_impl.update_objects(
                        space_id=space_id,
                        jsonld_document=jsonld_document,
                        graph_id=graph_id
                    )
                    
                    # For single object update, return the first URI
                    graph_objects = jsonld_document.get('@graph', [])
                    updated_uri = graph_objects[0].get('@id') or graph_objects[0].get('URI') if graph_objects else "unknown"
                    
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
