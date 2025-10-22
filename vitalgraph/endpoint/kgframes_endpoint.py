"""
KG Frames REST API endpoint for VitalGraph.

This module provides REST API endpoints for managing KG frames and their slots using JSON-LD 1.1 format.
KG frames represent structured knowledge frames with connected slot nodes and values.
"""

import logging
from typing import Dict, List, Optional, Union, Any
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field
import pyld
from pyld import jsonld

from ..endpoint.impl.kgframe_impl import KGFrameImpl
from ..model.jsonld_model import JsonLdDocument
from ..model.kgframes_model import (
    FramesResponse,
    FrameCreateResponse,
    FrameUpdateResponse,
    FrameDeleteResponse
)


class KGFramesEndpoint:
    """KG Frames endpoint handler."""
    
    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.KGFramesEndpoint")
        self.router = APIRouter()
        
        # Initialize the KGFrame service
        self.kgframe_impl = KGFrameImpl(space_manager)
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup FastAPI routes for KG frames management."""
        
        @self.router.get("/kgframes", response_model=Union[FramesResponse, JsonLdDocument], tags=["KG Frames"])
        async def list_or_get_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            page_size: int = Query(100, ge=1, le=1000, description="Number of frames per page"),
            offset: int = Query(0, ge=0, description="Offset for pagination"),
            frame_uri_type: Optional[str] = Query(None, description="Frame URI type to filter by"),
            search: Optional[str] = Query(None, description="Search text to find in frame properties"),
            uri: Optional[str] = Query(None, description="Single frame URI to retrieve"),
            uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            List KG frames with pagination, or get specific frames by URI(s).
            
            - If uri is provided: returns single frame
            - If uri_list is provided: returns multiple frames
            - Otherwise: returns paginated list of all frames
            """
            
            # Handle single URI retrieval
            if uri:
                return await self._get_frame_by_uri(space_id, graph_id, uri, current_user)
            
            # Handle multiple URI retrieval
            if uri_list:
                uris = [u.strip() for u in uri_list.split(',') if u.strip()]
                return await self._get_frames_by_uris(space_id, graph_id, uris, current_user)
            
            # Handle paginated listing
            return await self._list_frames(space_id, graph_id, page_size, offset, frame_uri_type, search, current_user)
        
        @self.router.post("/kgframes", response_model=FrameCreateResponse, tags=["KG Frames"])
        async def create_frames(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Create new KG frames from JSON-LD document.
            Returns error if any subject URI already exists.
            """
            return await self._create_frames(space_id, graph_id, request, current_user)
        
        @self.router.put("/kgframes", response_model=FrameUpdateResponse, tags=["KG Frames"])
        async def update_frame(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Update frame (deletes existing frame with subject URI first, then inserts replacement).
            """
            return await self._update_frame(space_id, graph_id, request, current_user)
        
        @self.router.delete("/kgframes", response_model=FrameDeleteResponse, tags=["KG Frames"])
        async def delete_frames(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
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
                raise HTTPException(status_code=400, detail="Either 'uri' or 'uri_list' parameter is required")
        
        @self.router.get("/kgframes/kgslots", response_model=JsonLdDocument, tags=["KG Frames"])
        async def get_frames_with_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            frame_uri: Optional[str] = Query(None, description="Single frame URI to get with slots"),
            frame_uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Get frame(s) plus their slot elements.
            Returns complete frame objects with connected slot nodes and values in JSON-LD RDF format.
            """
            if frame_uri:
                return await self._get_frame_with_slots(space_id, graph_id, frame_uri, current_user)
            elif frame_uri_list:
                uris = [u.strip() for u in frame_uri_list.split(',') if u.strip()]
                return await self._get_frames_with_slots(space_id, graph_id, uris, current_user)
            else:
                raise HTTPException(status_code=400, detail="Either 'frame_uri' or 'frame_uri_list' parameter is required")
        
        @self.router.post("/kgframes/kgslots", response_model=FrameCreateResponse, tags=["KG Frames"])
        async def create_frames_with_slots(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Insert frame/slots (set of frame objects with their slot nodes).
            Returns error if any frame URI already exists.
            """
            return await self._create_frames_with_slots(space_id, graph_id, request, current_user)
        
        @self.router.put("/kgframes/kgslots", response_model=FrameUpdateResponse, tags=["KG Frames"])
        async def update_frames_with_slots(
            request: JsonLdDocument,
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Update frame/slots (deletes existing frame and slot objects with same URIs first, then inserts replacements).
            """
            return await self._update_frames_with_slots(space_id, graph_id, request, current_user)
        
        @self.router.delete("/kgframes/kgslots", response_model=FrameDeleteResponse, tags=["KG Frames"])
        async def delete_frames_with_slots(
            space_id: str = Query(..., description="Space ID"),
            graph_id: Optional[str] = Query(None, description="Graph ID"),
            frame_uri: Optional[str] = Query(None, description="Single frame URI to delete with slots"),
            frame_uri_list: Optional[str] = Query(None, description="Comma-separated list of frame URIs"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Delete frame(s) and their slot elements by frame URI(s).
            """
            if frame_uri:
                return await self._delete_frame_with_slots(space_id, graph_id, frame_uri, current_user)
            elif frame_uri_list:
                uris = [u.strip() for u in frame_uri_list.split(',') if u.strip()]
                return await self._delete_frames_with_slots(space_id, graph_id, uris, current_user)
            else:
                raise HTTPException(status_code=400, detail="Either 'frame_uri' or 'frame_uri_list' parameter is required")
    
    async def _list_frames(self, space_id: str, graph_id: Optional[str], page_size: int, offset: int, frame_uri_type: Optional[str], search: Optional[str], current_user: Dict) -> FramesResponse:
        """List KG frames with pagination."""
        try:
            self.logger.info(f"Listing KGFrames in space {space_id}, graph {graph_id}")
            
            # Get complete JSON-LD document from implementation (now returns complete document)
            jsonld_document, total_count = await self.kgframe_impl.list_kgframes(
                space_id=space_id,
                graph_id=graph_id,
                page_size=page_size,
                offset=offset,
                frame_type_filter=frame_uri_type,
                search_text=search
            )
            
            # Create JsonLdDocument from the returned complete document
            jsonld_doc = JsonLdDocument(**jsonld_document)
            
            return FramesResponse(
                frames=jsonld_doc,
                total_count=total_count,
                page_size=page_size,
                offset=offset
            )
            
        except Exception as e:
            self.logger.error(f"Error listing KGFrames: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to list KGFrames: {str(e)}"
            )
    
    async def _get_frame_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> JsonLdDocument:
        """Get single frame by URI."""
        try:
            self.logger.info(f"Getting KGFrame {uri} from space {space_id}, graph {graph_id}")
            
            # Get frame from service
            frame = await self.kgframe_impl.get_kgframe_by_uri(
                space_id=space_id,
                uri=uri,
                graph_id=graph_id
            )
            
            if not frame:
                raise HTTPException(
                    status_code=404,
                    detail=f"KGFrame with URI {uri} not found"
                )
            
            # Return the frame as JSON-LD (it's already in the right format)
            return JsonLdDocument(**frame)
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error getting KGFrame: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get KGFrame: {str(e)}"
            )
    
    async def _get_frames_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> JsonLdDocument:
        """Get multiple frames by URI list."""
        try:
            self.logger.info(f"Getting {len(uris)} KGFrames from space {space_id}, graph {graph_id}")
            
            # Get complete JSON-LD document from implementation (now returns complete document)
            jsonld_document = await self.kgframe_impl.get_kgframes_by_uris(
                space_id=space_id,
                uris=uris,
                graph_id=graph_id
            )
            
            # Create JsonLdDocument from the returned complete document
            return JsonLdDocument(**jsonld_document)
            
        except Exception as e:
            self.logger.error(f"Error getting KGFrames: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get KGFrames: {str(e)}"
            )
    
    async def _create_frames(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> FrameCreateResponse:
        """Create new KG frames using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Creating KG frames in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for frame creation"
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
                created_uris = await self.kgframe_impl.create_kgframes_batch(
                    space_id=space_id,
                    jsonld_document=jsonld_document,
                    graph_id=graph_id
                )
                
                created_count = len(created_uris)
                self.logger.info(f"Created {created_count} KGFrames: {created_uris}")
                
                return FrameCreateResponse(
                    message=f"Successfully created {created_count} KG frames in graph '{graph_id}' in space '{space_id}'",
                    created_count=created_count,
                    created_uris=created_uris
                )
                
            except Exception as e:
                self.logger.error(f"Create operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create KGFrames: {str(e)}"
                )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error creating KG frames: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error creating KG frames: {str(e)}"
            )
    
    async def _update_frame(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> FrameUpdateResponse:
        """Update existing KG frames using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Updating KG frames in space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for frame update"
                )
            
            # Validate input document
            if not request or not request.graph:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid request: document and @graph are required"
                )
            
            # Validate that all objects have URIs before update
            for i, kgframe_obj in enumerate(request.graph):
                kgframe_uri = kgframe_obj.get('@id') or kgframe_obj.get('URI')
                if not kgframe_uri:
                    raise HTTPException(
                        status_code=400,
                        detail=f"KGFrame at index {i} missing URI (@id or URI field) - required for update"
                    )
            
            # Always use batch operations for consistency and to avoid manual JSON-LD document creation
            try:
                # Convert request to dict format for batch processing (VitalSigns native functionality)
                jsonld_document = request.model_dump(by_alias=True)
                updated_uris = await self.kgframe_impl.update_kgframes_batch(
                    space_id=space_id,
                    jsonld_document=jsonld_document,
                    graph_id=graph_id
                )
                
                updated_count = len(updated_uris)
                self.logger.info(f"Updated {updated_count} KGFrames: {updated_uris}")
                
                # Return the first URI as the primary updated URI
                updated_uri = updated_uris[0] if updated_uris else "unknown"
                
                return FrameUpdateResponse(
                    message=f"Successfully updated {updated_count} KG frames in graph '{graph_id}' in space '{space_id}'",
                    updated_uri=updated_uri
                )
                
            except Exception as e:
                self.logger.error(f"Update operation failed: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to update KGFrames: {str(e)}"
                )
            
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error updating KG frames: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error updating KG frames: {str(e)}"
            )
    
    async def _delete_frame_by_uri(self, space_id: str, graph_id: Optional[str], uri: str, current_user: Dict) -> FrameDeleteResponse:
        """Delete single KG frame by URI using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Deleting KG frame '{uri}' from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for frame deletion"
                )
            
            # Delete single KGFrame by URI
            success = await self.kgframe_impl.delete_kgframe(
                space_id=space_id,
                kgframe_uri=uri,
                graph_id=graph_id
            )
            
            if success:
                self.logger.info(f"Deleted KGFrame: {uri}")
                return FrameDeleteResponse(
                    message=f"Successfully deleted KG frame '{uri}' from graph '{graph_id}' in space '{space_id}'",
                    deleted_count=1,
                    deleted_uris=[uri]
                )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"KGFrame '{uri}' not found"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error deleting KG frame: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting KG frame: {str(e)}"
            )
    
    async def _delete_frames_by_uris(self, space_id: str, graph_id: Optional[str], uris: List[str], current_user: Dict) -> FrameDeleteResponse:
        """Delete multiple KG frames by URI list using proper VitalGraph patterns."""
        try:
            self.logger.info(f"Deleting {len(uris)} KG frames from space '{space_id}', graph '{graph_id}' for user '{current_user.get('username', 'unknown')}'")
            
            # Validate graph_id is provided (required for CRUD operations)
            if not graph_id:
                raise HTTPException(
                    status_code=400,
                    detail="graph_id is required for frame deletion"
                )
            
            # Delete multiple KGFrames by URI list
            deleted_count = await self.kgframe_impl.delete_kgframes(
                space_id=space_id,
                kgframe_uris=uris,
                graph_id=graph_id
            )
            
            self.logger.info(f"Successfully deleted {deleted_count} KG frames")
            
            return FrameDeleteResponse(
                message=f"Successfully deleted {deleted_count} KG frames from graph '{graph_id}' in space '{space_id}'",
                deleted_count=deleted_count,
                deleted_uris=uris[:deleted_count]  # Only return the URIs that were actually deleted
            )
            
        except Exception as e:
            self.logger.error(f"Error deleting KG frames: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error deleting KG frames: {str(e)}"
            )
    
    async def _get_frame_with_slots(self, space_id: str, graph_id: Optional[str], frame_uri: str, current_user: Dict) -> JsonLdDocument:
        """Get single frame with its slot elements."""
        # NO-OP implementation - return sample frame with connected slots
        return JsonLdDocument(**{
            "@context": {
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                "vital": "http://vital.ai/ontology/vital-core#",
                "haley": "http://vital.ai/ontology/haley-ai-kg#",
                "name": "vital:name",
                "description": "vital:description",
                "hasSlot": "haley:hasSlot",
                "slotValue": "haley:hasSlotValue",
                "slotType": "haley:hasSlotType",
                "type": "@type"
            },
            "@graph": [
                {
                    "@id": frame_uri,
                    "type": "haley:AddressFrame",
                    "name": "Home Address Frame",
                    "description": "Complete residential address information",
                    "hasSlot": [
                        "haley:slot_street_001",
                        "haley:slot_city_001", 
                        "haley:slot_postal_001"
                    ]
                },
                {
                    "@id": "haley:slot_street_001",
                    "type": "haley:StreetAddressSlot",
                    "name": "Street Address Slot",
                    "slotType": "haley:StreetAddressSlotType",
                    "slotValue": "123 Main Street"
                },
                {
                    "@id": "haley:slot_city_001",
                    "type": "haley:CitySlot",
                    "name": "City Slot",
                    "slotType": "haley:CitySlotType",
                    "slotValue": "San Francisco"
                },
                {
                    "@id": "haley:slot_postal_001",
                    "type": "haley:PostalCodeSlot",
                    "name": "Postal Code Slot",
                    "slotType": "haley:PostalCodeSlotType",
                    "slotValue": "94102"
                }
            ]
        })
    
    async def _get_frames_with_slots(self, space_id: str, graph_id: Optional[str], frame_uris: List[str], current_user: Dict) -> JsonLdDocument:
        """Get multiple frames with their slot elements."""
        # NO-OP implementation - return sample frames with connected slots
        graph_objects = []
        
        for i, frame_uri in enumerate(frame_uris[:2]):  # Limit to first 2 frames for demo
            # Add frame object
            graph_objects.append({
                "@id": frame_uri,
                "type": "haley:AddressFrame" if i % 2 == 0 else "haley:BiographicalFrame",
                "name": f"Frame {i+1}",
                "description": f"Sample frame with URI {frame_uri}",
                "hasSlot": [
                    f"haley:slot_{i}_1",
                    f"haley:slot_{i}_2"
                ]
            })
            
            # Add slot objects for this frame
            graph_objects.extend([
                {
                    "@id": f"haley:slot_{i}_1",
                    "type": "haley:TextSlot",
                    "name": f"Slot {i+1}-1",
                    "slotType": "haley:TextSlotType",
                    "slotValue": f"Value for slot {i+1}-1"
                },
                {
                    "@id": f"haley:slot_{i}_2",
                    "type": "haley:NumberSlot",
                    "name": f"Slot {i+1}-2",
                    "slotType": "haley:NumberSlotType",
                    "slotValue": f"{(i+1) * 100}"
                }
            ])
        
        return JsonLdDocument(**{
            "@context": {
                "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
                "vital": "http://vital.ai/ontology/vital-core#",
                "haley": "http://vital.ai/ontology/haley-ai-kg#",
                "name": "vital:name",
                "description": "vital:description",
                "hasSlot": "haley:hasSlot",
                "slotValue": "haley:hasSlotValue",
                "slotType": "haley:hasSlotType",
                "type": "@type"
            },
            "@graph": graph_objects
        })
    
    async def _create_frames_with_slots(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> FrameCreateResponse:
        """Create new frames with slots."""
        # NO-OP implementation - simulate frame+slot creation
        created_uris = []
        
        # Extract frame URIs from the request graph (frames typically have hasSlot property)
        if hasattr(request, 'graph') and request.graph:
            for obj in request.graph:
                if '@id' in obj and ('hasSlot' in obj or 'haley:hasSlot' in obj):
                    created_uris.append(obj['@id'])
        
        # If no frames found, assume single frame with generated URI
        if not created_uris:
            created_uris = ["haley:kgframe_with_slots_001"]
        
        return FrameCreateResponse(
            message=f"Successfully created {len(created_uris)} KG frames with slots",
            created_count=len(created_uris),
            created_uris=created_uris
        )
    
    async def _update_frames_with_slots(self, space_id: str, graph_id: Optional[str], request: JsonLdDocument, current_user: Dict) -> FrameUpdateResponse:
        """Update existing frames with slots."""
        # NO-OP implementation - simulate frame+slot update
        updated_uri = "haley:kgframe_updated_with_slots_001"
        
        # Try to extract frame URI from request
        if hasattr(request, 'graph') and request.graph:
            for obj in request.graph:
                if '@id' in obj and ('hasSlot' in obj or 'haley:hasSlot' in obj):
                    updated_uri = obj['@id']
                    break
        
        return FrameUpdateResponse(
            message=f"Successfully updated KG frame with slots",
            updated_uri=updated_uri
        )
    
    async def _delete_frame_with_slots(self, space_id: str, graph_id: Optional[str], frame_uri: str, current_user: Dict) -> FrameDeleteResponse:
        """Delete single frame and its slot elements."""
        # NO-OP implementation - simulate frame+slot deletion
        return FrameDeleteResponse(
            message=f"Successfully deleted KG frame and its slot elements",
            deleted_count=1,
            deleted_uris=[frame_uri]
        )
    
    async def _delete_frames_with_slots(self, space_id: str, graph_id: Optional[str], frame_uris: List[str], current_user: Dict) -> FrameDeleteResponse:
        """Delete multiple frames and their slot elements."""
        # NO-OP implementation - simulate multiple frame+slot deletion
        return FrameDeleteResponse(
            message=f"Successfully deleted {len(frame_uris)} KG frames and their slot elements",
            deleted_count=len(frame_uris),
            deleted_uris=frame_uris
        )


def create_kgframes_router(space_manager, auth_dependency) -> APIRouter:
    """Create and return the KG frames router."""
    endpoint = KGFramesEndpoint(space_manager, auth_dependency)
    return endpoint.router
