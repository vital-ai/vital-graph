"""
KG Entities REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing KG entities using JSON-LD 1.1 format.
KG entities represent knowledge graph entities with their associated triples and frame relationships.
"""

import logging
from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field
import pyld
from pyld import jsonld

from ..endpoint.impl.kgentity_impl import KGEntityImpl
from ..model.jsonld_model import JsonLdDocument
from ..model.kgentities_model import (
    EntitiesResponse,
    EntityCreateResponse,
    EntityUpdateResponse,
    EntityDeleteResponse,
    EntityFramesResponse,
    EntityFramesMultiResponse
)


class KGEntitiesEndpoint:
    """KG Entities endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.KGEntitiesEndpoint")
        self.router = APIRouter()
        
        # Initialize the KGEntity service
        self.kgentity_impl = KGEntityImpl(space_manager)
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes for KG entities management."""
        
        @self.router.get("/kgentities", response_model=Union[EntitiesResponse, JsonLdDocument], tags=["KG Entities"])
        async def list_or_get_entities(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            page_size: int = Query(100, ge=1, le=1000, description="Number of entities per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            entity_type_uri: Optional[str] = Query(None, description="Entity type URI to filter by"),
            search: Optional[str] = Query(None, description="Search text to find in entity properties"),
            uri: Optional[str] = Query(None, description="Single entity URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of entity URIs"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            List KG entities with pagination, or get specific entities by URI(s).
            
            - If uri is provided: returns single entity
            - If uri_list is provided: returns multiple entities
            - Otherwise: returns paginated list of all entities
            """
            
            # Handle single URI retrieval
            if uri:
                return await self._get_entity_by_uri(space_id, graph_id, uri, current_user)
            
            # Handle multiple URI retrieval
            if uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._get_entities_by_uris(space_id, graph_id, uris, current_user)
            
            # Handle paginated listing
            return await self._list_entities(space_id, graph_id, page_size, offset, entity_type_uri, search, current_user)
        
        @self.router.post("/kgentities", response_model=EntityCreateResponse, tags=["KG Entities"])
        async def create_entities(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Create new KG entities from JSON-LD document.
            Returns error if any subject URI already exists.
            """
            return await self._create_entities(space_id, graph_id, request, current_user)
        
        @self.router.put("/kgentities", response_model=EntityUpdateResponse, tags=["KG Entities"])
        async def update_entity(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Update entity (deletes existing entity with subject URI first, then inserts replacement).
            """
            return await self._update_entity(space_id, graph_id, request, current_user)
        
        @self.router.delete("/kgentities", response_model=EntityDeleteResponse, tags=["KG Entities"])
        async def delete_entities(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            uri: Optional[str] = Query(None, description="Single entity URI to delete"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of entity URIs to delete"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete entities by URI or URI list.
            """
            if uri:
                return await self._delete_entity_by_uri(space_id, graph_id, uri, current_user)
            elif uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._delete_entities_by_uris(space_id, graph_id, uris, current_user)
            else:
                raise HTTPException(status_code=400, detail="Either 'uri' or 'uri_list' parameter is required")
        
        @self.router.get("/kgentities/kgframes", response_model=Union[EntityFramesResponse, EntityFramesMultiResponse], tags=["KG Entities"])
        async def get_entity_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            frame_type_uri: Optional[str] = Query(None, description="Frame type URI to filter by"),
            uri: Optional[str] = Query(None, description="Single entity URI to get frames for"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of entity URIs"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Get frame URIs linked to entity(ies).
            
            - If uri is provided: returns list of frame URIs for single entity
            - If uri_list is provided: returns map of entity URI -> frame URI list
            """
            if uri:
                return await self._get_frames_for_entity(space_id, graph_id, uri, frame_type_uri, current_user)
            elif uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._get_frames_for_entities(space_id, graph_id, uris, frame_type_uri, current_user)
            else:
                raise HTTPException(status_code=400, detail="Either 'uri' or 'uri_list' parameter is required")
    
    async def _list_entities(self, space_id: str, graph_id: Optional[str], page_size: int, offset: int, entity_type_uri: Optional[str], search: Optional[str], current_user: Dict) -> EntitiesResponse:
        """List KG entities with pagination."""
        try:
            self.logger.info(f"Listing KGEntities in space {space_id}, graph {graph_id}")
            
            # Get complete JSON-LD document from implementation (now returns complete document)
            jsonld_document, total_count = await self.kgentity_impl.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                entity_type_filter=entity_type_uri,
                search_text=search
            )
            
            # Create JsonLdDocument from the returned complete document
            jsonld_doc = JsonLdDocument(**jsonld_document)
            
            return EntitiesResponse(
                entities=jsonld_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGEntities: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list KGEntities: {str(e)}"
            )
    
    async def _get_entity_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> JsonLdDocument:
        """Get single entity by URI."""
        try:
            self.logger.info(f"Getting KGEntity {uri} from space {space_id}, graph {graph_id}")
            
            # Get entity from service
            entity = await self.kgentity_impl.get_kgentity_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            if not entity:
                raise HTTPException(
                    status_code=404,
                    detail=f"KGEntity with URI {uri} not found"
                )
            
            # Return the entity as JSON-LD (it's already in the right format)
            return JsonLdDocument(**entity)
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGEntity: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get KGEntity: {str(e)}"
            )
    
    async def _get_entities_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> JsonLdDocument:
        """Get multiple entities by URI list."""
        try:
            self.logger.info(f"Getting {len(uris)} KGEntities from space {space_id}, graph {graph_id}")
            
            # Get complete JSON-LD document from implementation (now returns complete document)
            jsonld_document = await self.kgentity_impl.get_kgentities_by_uris(
                space_id=space_id,
                uris=uris,
                graph_id=graph_id
            )
            
            # Create JsonLdDocument from the returned complete document
            return JsonLdDocument(**jsonld_document)
            
        except Exception as e:
            self.logger.error(f"Error getting KGEntities: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get KGEntities: {str(e)}"
            )
    
    async def _create_entities(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> EntityCreateResponse:
        """Create new KG entities using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Creating KG entities in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for entity creation"
                )
            
            # Validate input document
            if not request or not request.graph:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: document and @graph are required"
                )
            
            # Always use batch operations for consistency and to avoid manual JSON-LD document creation
            try:
                # Convert request to dict format for batch processing (VitalSigns native functionality)
                jsonld_document = request.model_dump(by_alias=True)
                created_uris = await self.kgentity_impl.create_kgentities_batch(
                    space_id=space_id,
                    jsonld_document=jsonld_document,
                    graph_id=graph_id
                )
                
                created_count = len(created_uris)
                self.logger.info(f"Created {created_count} KGEntities: {created_uris}")
                
                return EntityCreateResponse(
                    message=f"Successfully created {created_count} KG entities in graph '{graph_id}' in space '{space_id}'",
                    created_count=created_count,
                    created_uris=created_uris
                )
                
            except Exception as e:
                self.logger.error(f"Create operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create KGEntities: {str(e)}"
                )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating KG entities: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error creating KG entities: {str(e)}"
            )
    
    async def _update_entity(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> EntityUpdateResponse:
        """Update existing KG entities using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Updating KG entities in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for entity update"
                )
            
            # Validate input document
            if not request or not request.graph:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: document and @graph are required"
                )
            
            # Validate that all objects have URIs before update
            for i, kgentity_obj in enumerate(request.graph):
                kgentity_uri = kgentity_obj.get('@id') or kgentity_obj.get('URI')
                if not kgentity_uri:
                    raise HTTPException(
                        status_code=400,
                        detail=f"KGEntity at index {i} missing URI (@id or URI field) - required for update"
                    )
            
            # Always use batch operations for consistency and to avoid manual JSON-LD document creation
            try:
                # Convert request to dict format for batch processing (VitalSigns native functionality)
                jsonld_document = request.model_dump(by_alias=True)
                updated_uris = await self.kgentity_impl.update_kgentities_batch(
                    space_id=space_id,
                    jsonld_document=jsonld_document,
                    graph_id=graph_id
                )
                
                updated_count = len(updated_uris)
                self.logger.info(f"Updated {updated_count} KGEntities: {updated_uris}")
                
                # Return the first URI as the primary updated URI
                updated_uri = updated_uris[0] if updated_uris else "unknown"
                
                return EntityUpdateResponse(
                    message=f"Successfully updated {updated_count} KG entities in graph '{graph_id}' in space '{space_id}'",
                    updated_uri=updated_uri
                )
                
            except Exception as e:
                self.logger.error(f"Update operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to update KGEntities: {str(e)}"
                )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating KG entities: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error updating KG entities: {str(e)}"
            )
    
    async def _delete_entity_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> EntityDeleteResponse:
        """Delete single KG entity by URI using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Deleting KG entity '{uri}' from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for entity deletion"
                )
            
            # Delete single KGEntity by URI
            success = await self.kgentity_impl.delete_kgentity(
                space_id=space_id,
                kgentity_uri=uri,
                graph_id=graph_id
            )
            
            if success:
                self.logger.info(f"Deleted KGEntity: {uri}")
                return EntityDeleteResponse(
                    message=f"Successfully deleted KG entity '{uri}' from graph '{graph_id}' in space '{space_id}'",
                    deleted_count=1,
                    deleted_uris=[uri]
                )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"KGEntity '{uri}' not found"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting KG entity: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting KG entity: {str(e)}"
            )
    
    async def _delete_entities_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> EntityDeleteResponse:
        """Delete multiple KG entities by URI list using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Deleting {len(uris)} KG entities from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for entity deletion"
                )
            
            # Delete multiple KGEntities by URI list
            deleted_count = await self.kgentity_impl.delete_kgentities(
                space_id=space_id,
                kgentity_uris=uris,
                graph_id=graph_id
            )
            
            self.logger.info(f"Successfully deleted {deleted_count} KG entities")
            
            return EntityDeleteResponse(
                message=f"Successfully deleted {deleted_count} KG entities from graph '{graph_id}' in space '{space_id}'",
                deleted_count=deleted_count,
                deleted_uris=uris[:deleted_count]  # Only return the URIs that were actually deleted
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting KG entities: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting KG entities: {str(e)}"
            )
    
    async def _get_frames_for_entity(self, space_id: str, graph_id: Optional[str], uri: str, frame_type_uri: Optional[str], current_user: Dict) -> EntityFramesResponse:
        """Get frame URIs linked to single entity - returns list of frame URIs."""
        # NO-OP implementation - return sample frame URIs
        sample_frame_uris = [
            "haley:kgframe_bio_001",
            "haley:kgframe_work_001",
            "haley:kgframe_education_001"
        ]
        
        # Filter by frame type if provided
        if frame_type_uri:
            # Simulate filtering - in real implementation would query by frame type
            sample_frame_uris = [uri for uri in sample_frame_uris if "bio" in uri or "work" in uri]
        
        return EntityFramesResponse(frame_uris=sample_frame_uris)
    
    async def _get_frames_for_entities(self, space_id: str, graph_id: Optional[str], uris: List[str], frame_type_uri: Optional[str], current_user: Dict) -> EntityFramesMultiResponse:
        """Get frame URIs linked to multiple entities - returns map of entity URI -> frame URI list."""
        # NO-OP implementation - return sample entity -> frame URI mappings
        entity_frame_map = {}
        
        for i, entity_uri in enumerate(uris):
            # Generate different frame URIs for each entity
            frame_uris = [
                f"haley:kgframe_{i}_bio_001",
                f"haley:kgframe_{i}_work_001"
            ]
            
            # Add extra frame for some entities
            if i % 2 == 0:
                frame_uris.append(f"haley:kgframe_{i}_education_001")
            
            # Filter by frame type if provided
            if frame_type_uri:
                # Simulate filtering - in real implementation would query by frame type
                frame_uris = [uri for uri in frame_uris if "bio" in uri or "work" in uri]
            
            entity_frame_map[entity_uri] = frame_uris
        
        return EntityFramesMultiResponse(entity_frame_map=entity_frame_map)


def create_kgentities_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG entities router."""
    endpoint = KGEntitiesEndpoint(space_manager, auth_dependency)
    return endpoint.router
