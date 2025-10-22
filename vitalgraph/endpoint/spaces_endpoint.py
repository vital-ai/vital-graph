"""Spaces Endpoint for VitalGraph

Implements REST API endpoints for space management operations.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
import logging

from ..model.spaces_model import (
    Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse
)


class SpacesEndpoint:
    """Spaces endpoint handler."""
    
    def __init__(self, api, auth_dependency):
        self.api = api
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SpacesEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup space management routes."""
        
        @self.router.get(
            "/spaces",
            response_model=SpacesListResponse,
            tags=["Spaces"],
            summary="List Spaces",
            description="Get a list of all accessible graph spaces for the authenticated user"
        )
        async def list_spaces(current_user: Dict = Depends(self.auth_dependency)):
            spaces = await self.api.list_spaces(current_user)
            return SpacesListResponse(
                spaces=spaces,
                total_count=len(spaces),
                page_size=len(spaces),  # No pagination implemented yet
                offset=0
            )
        
        @self.router.post(
            "/spaces",
            response_model=SpaceCreateResponse,
            tags=["Spaces"],
            summary="Create Space",
            description="Create a new graph space for storing RDF data and knowledge graphs"
        )
        async def add_space(space: Space, current_user: Dict = Depends(self.auth_dependency)):
            created_space = await self.api.add_space(space.dict(), current_user)
            return SpaceCreateResponse(
                message="Space created successfully",
                created_count=1,
                created_uris=[str(created_space.get('id', ''))]
            )
        
        @self.router.get(
            "/spaces/{space_id}",
            response_model=Space,
            tags=["Spaces"],
            summary="Get Space",
            description="Retrieve detailed information about a specific graph space by ID"
        )
        async def get_space(space_id: str, current_user: Dict = Depends(self.auth_dependency)):
            return await self.api.get_space_by_id(space_id, current_user)
        
        @self.router.put(
            "/spaces/{space_id}",
            response_model=SpaceUpdateResponse,
            tags=["Spaces"],
            summary="Update Space",
            description="Update an existing graph space (requires complete space object)"
        )
        async def update_space(space_id: str, space: Space, current_user: Dict = Depends(self.auth_dependency)):
            updated_space = await self.api.update_space(space_id, space.dict(), current_user)
            return SpaceUpdateResponse(
                message="Space updated successfully",
                updated_uri=str(updated_space.get('id', space_id))
            )
        
        @self.router.delete(
            "/spaces/{space_id}",
            response_model=SpaceDeleteResponse,
            tags=["Spaces"],
            summary="Delete Space",
            description="Permanently delete a graph space and all associated RDF data"
        )
        async def delete_space(space_id: str, current_user: Dict = Depends(self.auth_dependency)):
            result = await self.api.delete_space(space_id, current_user)
            return SpaceDeleteResponse(
                message="Space deleted successfully",
                deleted_count=1,
                deleted_uris=[space_id]
            )
        
        @self.router.get(
            "/spaces/filter/{name_filter}",
            response_model=SpacesListResponse,
            tags=["Spaces"],
            summary="Filter Spaces by Name",
            description="Search for spaces whose names contain the specified filter text"
        )
        async def filter_spaces(name_filter: str, current_user: Dict = Depends(self.auth_dependency)):
            spaces = await self.api.filter_spaces_by_name(name_filter, current_user)
            return SpacesListResponse(
                spaces=spaces,
                total_count=len(spaces),
                page_size=len(spaces),  # No pagination implemented yet
                offset=0
            )


def create_spaces_router(api, auth_dependency) -> APIRouter:
    """Create and return the spaces router."""
    endpoint = SpacesEndpoint(api, auth_dependency)
    return endpoint.router