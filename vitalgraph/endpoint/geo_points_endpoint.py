"""Geo Points REST Endpoint

REST API for listing and querying geo-populated entities in a space.

Routes (all under /api/spaces/{space_id}/geo):
    GET /  — list geo points (optionally filtered by spatial radius)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam, status
from pydantic import BaseModel, Field

from ..auth.role_dependencies import require_space_read

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GeoPointOut(BaseModel):
    subject_uri: str
    subject_uuid: str
    latitude: float
    longitude: float
    context_uuid: str
    distance_m: Optional[float] = None
    updated_time: Optional[str] = None


class GeoPointsResponse(BaseModel):
    points: List[GeoPointOut]
    total_count: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Endpoint class
# ---------------------------------------------------------------------------

class GeoPointsEndpoint:
    """REST endpoint for listing/querying geo points."""

    def __init__(self, app_impl, auth_dependency):
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    async def _acquire_conn(self):
        """Acquire a database connection from the pool."""
        db_impl = self.app_impl.db_impl
        if db_impl is None or not getattr(db_impl, "connection_pool", None):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not available",
            )
        return await db_impl.connection_pool.acquire()

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

    async def list_geo_points(
        self,
        space_id: str,
        current_user: Dict,
        near_lat: Optional[float] = None,
        near_lon: Optional[float] = None,
        radius_km: Optional[float] = None,
        graph_uri: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> GeoPointsResponse:
        require_space_read(current_user, space_id)

        # Validate spatial params: all-or-none
        spatial_params = [near_lat, near_lon, radius_km]
        has_spatial = any(p is not None for p in spatial_params)
        if has_spatial and not all(p is not None for p in spatial_params):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Spatial query requires all of: near_lat, near_lon, radius_km",
            )

        # Clamp limit
        limit = max(1, min(limit, 1000))
        offset = max(0, offset)

        conn = await self._acquire_conn()
        try:
            geo_table = f"{space_id}_geo"
            term_table = f"{space_id}_term"

            # Check geo table exists
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1)",
                geo_table,
            )
            if not exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Space '{space_id}' geo table not found",
                )

            # Build query
            params = []
            where_clauses = []
            param_idx = 1

            # Graph filter
            if graph_uri:
                where_clauses.append(
                    f"g.context_uuid = (SELECT term_uuid FROM {term_table} "
                    f"WHERE term_text = ${param_idx} AND term_type = 'U' LIMIT 1)"
                )
                params.append(graph_uri)
                param_idx += 1

            # Spatial filter
            distance_col = "NULL::double precision"
            order_clause = "g.updated_time DESC NULLS LAST"

            if has_spatial:
                radius_m = radius_km * 1000.0
                where_clauses.append(
                    f"ST_DWithin(g.location, "
                    f"ST_MakePoint(${param_idx}, ${param_idx + 1})::geography, "
                    f"${param_idx + 2})"
                )
                params.extend([near_lon, near_lat, radius_m])
                distance_col = (
                    f"ST_Distance(g.location, "
                    f"ST_MakePoint(${param_idx}, ${param_idx + 1})::geography)"
                )
                order_clause = "distance_m ASC NULLS LAST"
                param_idx += 3

            where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

            # Count query
            count_sql = f"SELECT COUNT(*) FROM {geo_table} g WHERE TRUE{where_sql}"
            total_count = await conn.fetchval(count_sql, *params)

            # Data query
            data_sql = f"""
                SELECT
                    t.term_text AS subject_uri,
                    g.subject_uuid::text AS subject_uuid,
                    g.latitude,
                    g.longitude,
                    g.context_uuid::text AS context_uuid,
                    {distance_col} AS distance_m,
                    g.updated_time::text AS updated_time
                FROM {geo_table} g
                JOIN {term_table} t ON t.term_uuid = g.subject_uuid AND t.term_type = 'U'
                WHERE TRUE{where_sql}
                ORDER BY {order_clause}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([limit, offset])

            rows = await conn.fetch(data_sql, *params)

            points = [
                GeoPointOut(
                    subject_uri=row["subject_uri"],
                    subject_uuid=row["subject_uuid"],
                    latitude=row["latitude"],
                    longitude=row["longitude"],
                    context_uuid=row["context_uuid"],
                    distance_m=row["distance_m"],
                    updated_time=row["updated_time"],
                )
                for row in rows
            ]

            return GeoPointsResponse(
                points=points,
                total_count=total_count or 0,
                limit=limit,
                offset=offset,
            )

        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/spaces/{space_id}/geo",
            response_model=GeoPointsResponse,
            tags=["Geo"],
            summary="List Geo Points",
            description=(
                "List geo-populated entities in a space. "
                "Optionally filter by spatial radius (near_lat, near_lon, radius_km) "
                "and/or graph URI."
            ),
        )
        async def list_route(
            space_id: str,
            near_lat: Optional[float] = QueryParam(None, description="Latitude of center point"),
            near_lon: Optional[float] = QueryParam(None, description="Longitude of center point"),
            radius_km: Optional[float] = QueryParam(None, ge=0.001, le=40075, description="Radius in km"),
            graph_uri: Optional[str] = QueryParam(None, description="Filter to a specific graph URI"),
            limit: int = QueryParam(100, ge=1, le=1000, description="Max results"),
            offset: int = QueryParam(0, ge=0, description="Pagination offset"),
            current_user: Dict = Depends(auth),
        ):
            return await self.list_geo_points(
                space_id, current_user,
                near_lat=near_lat, near_lon=near_lon, radius_km=radius_km,
                graph_uri=graph_uri, limit=limit, offset=offset,
            )


def create_geo_points_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = GeoPointsEndpoint(app_impl, auth_dependency)
    return endpoint.router
