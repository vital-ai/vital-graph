"""Spaces Endpoint for VitalGraph

Implements REST API endpoints for space management operations.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
import logging

from ..model.spaces_model import (
    Space, SpacesListResponse, SpaceCreateResponse, SpaceUpdateResponse, SpaceDeleteResponse, SpaceResponse, SpaceInfoResponse,
    SpaceAnalyticsResponse, SpaceAnalyticsData,
    EntityAnalytics, FrameAnalytics, RelationAnalytics, PropertyAnalytics,
    TypeCount, ConnectedEntity, PredicateCount,
)
from ..auth.role_dependencies import require_space_read, require_space_write, require_admin, get_space_access


class SpacesEndpoint:
    """Spaces endpoint handler."""
    
    def __init__(self, api, auth_dependency):
        self.api = api
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.SpacesEndpoint")
        self.router = APIRouter()
        self._setup_routes()
    
    async def list_spaces(self, current_user: Dict):
        """List all spaces for the current user."""
        self.logger.debug(f"🔍 ENDPOINT: list_spaces method called")
        self.logger.debug(f"🔍 ENDPOINT: current_user: {current_user}")
        self.logger.debug(f"🔍 ENDPOINT: self.api: {type(self.api)}")
        self.logger.debug(f"🔍 ENDPOINT: self.api object id: {id(self.api)}")
        self.logger.debug(f"🔍 ENDPOINT: self.api.space_manager: {getattr(self.api, 'space_manager', 'NOT_SET')}")
        self.logger.debug(f"🔍 ENDPOINT: About to call self.api.list_spaces()")
        
        try:
            spaces = await self.api.list_spaces(current_user)
            self.logger.debug(f"🔍 ENDPOINT: api.list_spaces returned: {spaces}")
            
            # Filter to only spaces the user has access to
            spaces = self._filter_accessible_spaces(spaces, current_user)
            
            response = SpacesListResponse(
                spaces=spaces,
                total_count=len(spaces),
                page_size=len(spaces),  # No pagination implemented yet
                offset=0
            )
            self.logger.debug(f"🔍 ENDPOINT: Created SpacesListResponse: {type(response)}")
            return response
        except Exception as e:
            self.logger.error(f"❌ ENDPOINT ERROR: Exception in list_spaces: {e}")
            self.logger.debug(f"🔍 ENDPOINT: Exception type: {type(e)}")
            import traceback
            self.logger.debug(f"🔍 ENDPOINT: Full traceback:\n{traceback.format_exc()}")
            raise
    
    async def add_space(self, space: Space, current_user: Dict):
        """Create a new space."""
        created_space = await self.api.add_space(space.dict(), current_user)
        # The API returns the space dict with 'space' field, not 'id'
        space_id = created_space.get('space', space.space)
        
        # Convert created_space dict to Space object
        space_obj = Space(**created_space) if created_space else None
        
        return SpaceCreateResponse(
            message="Space created successfully",
            created_count=1,
            created_uris=[str(space_id)],
            space=space_obj
        )
    
    async def get_space(self, space_id: str, current_user: Dict):
        """Get a specific space by ID."""
        try:
            space = await self.api.get_space_by_id(space_id, current_user)
            return SpaceResponse(
                success=True,
                message="Space retrieved successfully",
                space=space
            )
        except Exception as e:
            # Return error response instead of raising HTTP exception
            self.logger.warning(f"Space not found: {space_id} - {e}")
            return SpaceResponse(
                success=False,
                message=f"Space not found: {space_id}",
                space=None
            )
    
    async def get_space_info(self, space_id: str, current_user: Dict):
        """Get detailed space information including statistics."""
        try:
            # Get space data
            space = await self.api.get_space_by_id(space_id, current_user)
            
            # Get detailed info from space_manager
            info = await self.api.space_manager.get_space_info(space_id)
            
            # Extract statistics — some backends nest under 'statistics', others are flat
            statistics = info.get('statistics') if info else None
            if statistics is None and info:
                # Use the full info dict as statistics (sparql_sql backend returns flat)
                statistics = info
            quad_dump = info.get('quad_dump') if info else None
            
            return SpaceInfoResponse(
                success=True,
                message="Space info retrieved successfully",
                space=space,
                statistics=statistics,
                quad_dump=quad_dump
            )
        except Exception as e:
            # Return error response instead of raising HTTP exception
            self.logger.warning(f"Failed to get space info: {space_id} - {e}")
            return SpaceInfoResponse(
                success=False,
                message=f"Failed to get space info: {space_id}",
                space=None,
                statistics=None,
                quad_dump=None
            )
    
    async def get_space_analytics(self, space_id: str, refresh: bool, graph_uri=None, current_user=None):
        """Get analytics for a space. Optionally trigger a fresh computation."""
        try:
            from datetime import datetime, timezone
            pool = getattr(self.api, '_pool', None) or getattr(getattr(self.api, 'db_impl', None), 'connection_pool', None)
            if not pool:
                # Try getting pool from space_manager backend
                sm = getattr(self.api, 'space_manager', None)
                if sm and hasattr(sm, '_backend'):
                    pool = getattr(sm._backend, '_pool', None)
                if not pool and sm:
                    # Try via space records
                    for sr in getattr(sm, '_spaces', {}).values():
                        backend = getattr(getattr(sr, 'space_impl', None), 'backend', None)
                        if backend:
                            pool = getattr(backend, '_pool', None) or getattr(getattr(backend, '_db', None), '_pool', None)
                            if pool:
                                break

            if not pool:
                return SpaceAnalyticsResponse(
                    success=False,
                    message="Database pool not available for analytics"
                )

            if refresh or graph_uri:
                from ..process.analytics_job import AnalyticsJob
                job = AnalyticsJob(pool)
                result = await job.trigger_compute(space_id, graph_uri=graph_uri)
                if graph_uri and result and 'analytics' in result:
                    # Return live-computed graph-filtered analytics
                    data = result['analytics']
                    elapsed_ms = result.get('computation_time_ms', 0)
                    analytics = SpaceAnalyticsData(
                        space_id=space_id,
                        computed_at=datetime.now(timezone.utc).isoformat(),
                        computation_time_ms=elapsed_ms,
                        stale=False,
                        entity_analytics=EntityAnalytics(**(data.get("entity_analytics", {}))),
                        frame_analytics=FrameAnalytics(**(data.get("frame_analytics", {}))),
                        relation_analytics=RelationAnalytics(**(data.get("relation_analytics", {}))),
                        property_analytics=PropertyAnalytics(**(data.get("property_analytics", {}))),
                    )
                    return SpaceAnalyticsResponse(
                        success=True,
                        message=f"Analytics computed for graph: {graph_uri}",
                        analytics=analytics
                    )

            # Read latest analytics from space_analytics table
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT analytics_json, computed_at, computation_time_ms
                       FROM space_analytics
                       WHERE space_id = $1
                       ORDER BY computed_at DESC
                       LIMIT 1""",
                    space_id
                )

            if not row:
                return SpaceAnalyticsResponse(
                    success=True,
                    message="No analytics computed yet for this space",
                    analytics=None
                )

            import json
            data = json.loads(row["analytics_json"]) if isinstance(row["analytics_json"], str) else row["analytics_json"]
            computed_at = row["computed_at"]
            computation_time_ms = row["computation_time_ms"]

            # Check staleness (>24h)
            stale = False
            if computed_at:
                age = (datetime.now(timezone.utc) - computed_at).total_seconds()
                stale = age > 86400

            # Build typed response
            analytics = SpaceAnalyticsData(
                space_id=space_id,
                computed_at=computed_at.isoformat() if computed_at else None,
                computation_time_ms=computation_time_ms,
                stale=stale,
                entity_analytics=EntityAnalytics(**(data.get("entity_analytics", {}))),
                frame_analytics=FrameAnalytics(**(data.get("frame_analytics", {}))),
                relation_analytics=RelationAnalytics(**(data.get("relation_analytics", {}))),
                property_analytics=PropertyAnalytics(**(data.get("property_analytics", {}))),
            )

            return SpaceAnalyticsResponse(
                success=True,
                message="Analytics retrieved successfully",
                analytics=analytics
            )

        except Exception as e:
            self.logger.warning(f"Failed to get space analytics: {space_id} - {e}")
            return SpaceAnalyticsResponse(
                success=False,
                message=f"Failed to get space analytics: {e}"
            )

    async def update_space(self, space_id: str, space: Space, current_user: Dict):
        """Update an existing space."""
        updated_space = await self.api.update_space(space_id, space.dict(), current_user)
        return SpaceUpdateResponse(
            message="Space updated successfully",
            updated_uri=str(updated_space.get('id', space_id))
        )
    
    async def delete_space(self, space_id: str, current_user: Dict):
        """Delete a space."""
        result = await self.api.delete_space(space_id, current_user)
        return SpaceDeleteResponse(
            message="Space deleted successfully",
            deleted_count=1,
            deleted_uris=[space_id]
        )
    
    async def filter_spaces(self, name_filter: str, current_user: Dict):
        """Filter spaces by name."""
        spaces = await self.api.filter_spaces_by_name(name_filter, current_user)
        # Filter to only spaces the user has access to
        spaces = self._filter_accessible_spaces(spaces, current_user)
        return SpacesListResponse(
            spaces=spaces,
            total_count=len(spaces),
            page_size=len(spaces),  # No pagination implemented yet
            offset=0
        )
    
    def _filter_accessible_spaces(self, spaces: list, current_user: Dict) -> list:
        """Return only spaces the user has at least read access to.
        
        Admins see all spaces. Non-admin users see only spaces
        listed in their spaces map (including wildcard '*').
        """
        if current_user.get('role') == 'admin':
            return spaces
        
        return [
            s for s in spaces
            if get_space_access(current_user, s.get('space', '') if isinstance(s, dict) else getattr(s, 'space', '')) is not None
        ]

    def _setup_routes(self):
        """Setup space management routes."""
        
        @self.router.get(
            "/spaces",
            response_model=SpacesListResponse,
            tags=["Spaces"],
            summary="List Spaces",
            description="Get a list of all accessible graph spaces for the authenticated user"
        )
        async def list_spaces_route(current_user: Dict = Depends(self.auth_dependency)):
            self.logger.debug(f"🔍 ROUTING: GET /spaces endpoint called")
            self.logger.debug(f"🔍 ROUTING: current_user: {current_user}")
            self.logger.debug(f"🔍 ROUTING: About to call self.list_spaces()")
            try:
                result = await self.list_spaces(current_user)
                self.logger.debug(f"🔍 ROUTING: list_spaces returned successfully: {type(result)}")
                return result
            except Exception as e:
                self.logger.error(f"❌ ROUTING ERROR: Exception in list_spaces_route: {e}")
                self.logger.debug(f"🔍 ROUTING: Exception type: {type(e)}")
                import traceback
                self.logger.debug(f"🔍 ROUTING: Full traceback:\n{traceback.format_exc()}")
                raise
        
        @self.router.post(
            "/spaces",
            response_model=SpaceCreateResponse,
            tags=["Spaces"],
            summary="Create Space",
            description="Create a new graph space for storing RDF data and knowledge graphs"
        )
        async def add_space_route(space: Space, current_user: Dict = Depends(self.auth_dependency)):
            require_admin(current_user)
            return await self.add_space(space, current_user)
        
        @self.router.get(
            "/spaces/space",
            response_model=SpaceResponse,
            tags=["Spaces"],
            summary="Get Space",
            description="Retrieve detailed information about a specific graph space by ID"
        )
        async def get_space_route(
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_read(current_user, space_id)
            return await self.get_space(space_id, current_user)
        
        @self.router.get(
            "/spaces/info",
            response_model=SpaceInfoResponse,
            tags=["Spaces"],
            summary="Get Space Info",
            description="Retrieve detailed space information including statistics and metadata"
        )
        async def get_space_info_route(
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_read(current_user, space_id)
            return await self.get_space_info(space_id, current_user)
        
        @self.router.get(
            "/spaces/analytics",
            response_model=SpaceAnalyticsResponse,
            tags=["Spaces"],
            summary="Get Space Analytics",
            description="Retrieve KG analytics for a space (entity/frame/relation/property distributions). Use refresh=true to trigger recomputation."
        )
        async def get_space_analytics_route(
            space_id: str = Query(..., description="Space ID"),
            refresh: bool = Query(False, description="Force fresh analytics computation"),
            graph_uri: str = Query(None, description="Filter analytics to a specific graph URI"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_read(current_user, space_id)
            return await self.get_space_analytics(space_id, refresh, graph_uri, current_user)

        @self.router.put(
            "/spaces",
            response_model=SpaceUpdateResponse,
            tags=["Spaces"],
            summary="Update Space",
            description="Update an existing graph space (requires complete space object)"
        )
        async def update_space_route(
            space: Space,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_space_write(current_user, space_id)
            return await self.update_space(space_id, space, current_user)
        
        @self.router.delete(
            "/spaces",
            response_model=SpaceDeleteResponse,
            tags=["Spaces"],
            summary="Delete Space",
            description="Permanently delete a graph space and all associated RDF data"
        )
        async def delete_space_route(
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            require_admin(current_user)
            return await self.delete_space(space_id, current_user)
        
        @self.router.get(
            "/spaces/filter",
            response_model=SpacesListResponse,
            tags=["Spaces"],
            summary="Filter Spaces by Name",
            description="Search for spaces whose names contain the specified filter text"
        )
        async def filter_spaces_route(
            name_filter: str = Query(..., description="Name filter text"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            return await self.filter_spaces(name_filter, current_user)


def create_spaces_router(api, auth_dependency) -> APIRouter:
    """Create and return the spaces router."""
    logger = logging.getLogger(__name__)
    logger.debug(f"🔍 ENDPOINT CREATION DEBUG: Creating SpacesEndpoint with API: {api}")
    logger.debug(f"🔍 ENDPOINT CREATION DEBUG: API space_manager: {getattr(api, 'space_manager', 'NOT_SET')}")
    endpoint = SpacesEndpoint(api, auth_dependency)
    logger.debug(f"🔍 ENDPOINT CREATION DEBUG: SpacesEndpoint created with API space_manager: {getattr(endpoint.api, 'space_manager', 'NOT_SET')}")
    return endpoint.router