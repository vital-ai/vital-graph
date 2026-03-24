"""
Admin REST API endpoint for VitalGraph.

Provides administrative operations such as resyncing auxiliary tables
(edge, frame_entity, stats) for the sparql_sql backend.
"""

import logging
import time as _time
from typing import Dict, Optional
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel, Field


class ResyncResponse(BaseModel):
    """Response model for resync operation."""
    space_id: str
    edge_rows: int
    frame_entity_rows: int
    pred_stats_rows: int
    quad_stats_rows: int
    elapsed_ms: float


class AdminEndpoint:
    """REST API endpoint for VitalGraph admin operations."""

    def __init__(self, space_manager, auth_dependency):
        self.space_manager = space_manager
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(__name__)
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        """Set up FastAPI routes for admin operations."""

        @self.router.post("/resync", response_model=ResyncResponse, tags=["Admin"])
        async def resync_auxiliary_tables(
            space_id: str = Query(..., description="Space ID to resync"),
            current_user: Dict = Depends(self.auth_dependency)
        ):
            """
            Resync all auxiliary tables (edge, frame_entity, stats) from rdf_quad.

            Rebuilds the maintained tables from scratch, runs ANALYZE on all
            space tables, and invalidates the in-memory stats cache.
            Use after bulk loads, disaster recovery, or manual DB edits.
            """
            # Get backend implementation
            space_record = await self.space_manager.get_space_or_load(space_id)
            if not space_record:
                raise HTTPException(status_code=404, detail=f"Space {space_id} not found")

            space_impl = space_record.space_impl
            backend = space_impl.get_db_space_impl()
            if not backend:
                raise HTTPException(status_code=500, detail="Backend implementation not available")

            # Check that this is the sparql_sql backend
            db_impl = getattr(backend, 'db_impl', None)
            if not db_impl:
                raise HTTPException(
                    status_code=400,
                    detail="Resync is only available for the sparql_sql backend"
                )

            pool = getattr(db_impl, 'connection_pool', None)
            if not pool:
                raise HTTPException(status_code=500, detail="No connection pool available")

            try:
                from vitalgraph.db.sparql_sql.resync_all import resync_all_auxiliary_tables

                t0 = _time.monotonic()
                async with pool.acquire() as conn:
                    result = await resync_all_auxiliary_tables(conn, space_id)
                elapsed_ms = (_time.monotonic() - t0) * 1000

                self.logger.info(
                    "Admin resync [%s]: edge=%d, frame_entity=%d, pred_stats=%d, quad_stats=%d (%.0fms)",
                    space_id,
                    result['edge_rows'], result['frame_entity_rows'],
                    result['pred_stats_rows'], result['quad_stats_rows'],
                    elapsed_ms,
                )

                return ResyncResponse(
                    space_id=space_id,
                    edge_rows=result['edge_rows'],
                    frame_entity_rows=result['frame_entity_rows'],
                    pred_stats_rows=result['pred_stats_rows'],
                    quad_stats_rows=result['quad_stats_rows'],
                    elapsed_ms=round(elapsed_ms, 1),
                )

            except Exception as e:
                self.logger.error(f"Resync failed for space {space_id}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Resync failed: {str(e)}"
                )


def create_admin_router(space_manager, auth_dependency) -> APIRouter:
    """Factory function to create the admin router."""
    endpoint = AdminEndpoint(space_manager, auth_dependency)
    return endpoint.router
