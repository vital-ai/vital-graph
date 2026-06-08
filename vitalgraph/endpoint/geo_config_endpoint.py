"""Geo Config REST Endpoint

REST API for managing the per-space geo_config table.

Routes (all under /api/spaces/{space_id}/geo-config):
    GET    /   — get current geo config (or create defaults)
    PUT    /   — update geo config
    DELETE /   — reset geo config (delete row)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth.role_dependencies import require_space_read, require_space_write
from ..vectorization.geo_config_manager import GeoConfigManager, DEFAULT_LAT_PREDICATES, DEFAULT_LON_PREDICATES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GeoConfigOut(BaseModel):
    config_id: int
    enabled: bool = False
    auto_sync: bool = False
    lat_predicates: List[str] = Field(default_factory=lambda: list(DEFAULT_LAT_PREDICATES))
    lon_predicates: List[str] = Field(default_factory=lambda: list(DEFAULT_LON_PREDICATES))
    updated_time: Optional[str] = None


class UpdateGeoConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_sync: Optional[bool] = None
    lat_predicates: Optional[List[str]] = None
    lon_predicates: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Endpoint class
# ---------------------------------------------------------------------------

class GeoConfigEndpoint:
    """REST endpoint for geo config management."""

    def __init__(self, app_impl, auth_dependency):
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    async def _get_manager(self, space_id: str) -> tuple:
        """Acquire a connection and return a (GeoConfigManager, conn) tuple."""
        db_impl = self.app_impl.db_impl
        if db_impl is None or not getattr(db_impl, "connection_pool", None):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not available",
            )
        conn = await db_impl.connection_pool.acquire()
        return GeoConfigManager(conn, space_id), conn

    async def _release(self, conn):
        try:
            db_impl = self.app_impl.db_impl
            if db_impl and db_impl.connection_pool:
                await db_impl.connection_pool.release(conn)
        except Exception:
            logger.exception("Error releasing connection")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def get_config(self, space_id: str, current_user: Dict):
        require_space_read(current_user, space_id)
        mgr, conn = await self._get_manager(space_id)
        try:
            dto = await mgr.ensure_config()
            return GeoConfigOut(**dto.to_dict())
        finally:
            await self._release(conn)

    async def update_config(self, space_id: str, body: UpdateGeoConfigRequest, current_user: Dict):
        require_space_write(current_user, space_id)
        mgr, conn = await self._get_manager(space_id)
        try:
            await mgr.ensure_config()
            dto = await mgr.update_config(**body.dict(exclude_none=True))
            if dto is None:
                raise HTTPException(status_code=404, detail="Geo config not found")
            return GeoConfigOut(**dto.to_dict())
        finally:
            await self._release(conn)

    async def delete_config(self, space_id: str, current_user: Dict):
        require_space_write(current_user, space_id)
        mgr, conn = await self._get_manager(space_id)
        try:
            await mgr.delete_config()
            return {"message": "Geo config reset", "space_id": space_id}
        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/spaces/{space_id}/geo-config",
            response_model=GeoConfigOut,
            tags=["Geo Config"],
            summary="Get Geo Config",
            description="Get or create default geo configuration for a space",
        )
        async def get_route(space_id: str, current_user: Dict = Depends(auth)):
            return await self.get_config(space_id, current_user)

        @self.router.put(
            "/spaces/{space_id}/geo-config",
            response_model=GeoConfigOut,
            tags=["Geo Config"],
            summary="Update Geo Config",
            description="Update geo configuration (enabled, auto_sync, predicates)",
        )
        async def update_route(
            space_id: str,
            body: UpdateGeoConfigRequest,
            current_user: Dict = Depends(auth),
        ):
            return await self.update_config(space_id, body, current_user)

        @self.router.delete(
            "/spaces/{space_id}/geo-config",
            tags=["Geo Config"],
            summary="Reset Geo Config",
            description="Delete geo config row (resets to unconfigured state)",
        )
        async def delete_route(space_id: str, current_user: Dict = Depends(auth)):
            return await self.delete_config(space_id, current_user)


def create_geo_config_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = GeoConfigEndpoint(app_impl, auth_dependency)
    return endpoint.router
