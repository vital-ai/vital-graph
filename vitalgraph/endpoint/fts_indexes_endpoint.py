"""FTS Indexes REST Endpoint

REST API for managing per-space FTS indexes (``{space}_fts_index`` registry)
and their backing data tables (``{space}_fts_{index_name}``).

Routes (all under /api/fts-indexes):
    GET    /              — list FTS indexes
    POST   /              — create FTS index
    DELETE /              — delete FTS index
    GET    /stats         — get FTS data table statistics
    PUT    /languages     — update languages (recreates trigger)
    POST   /populate      — populate FTS data from entity properties
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.role_dependencies import require_space_read, require_space_write
from ..model.fts_index_model import (
    FtsIndexOut, FtsIndexListResponse, FtsIndexStatsResponse,
    CreateFtsIndexRequest, UpdateFtsLanguagesRequest,
    PopulateFtsRequest, PopulateFtsResponse,
    DeleteResponse,
)
from ..vectorization.fts_index_lifecycle import (
    ensure_fts_index, teardown_fts_index,
    list_fts_indexes, get_fts_index, get_fts_stats,
    update_fts_languages,
)

logger = logging.getLogger(__name__)


class FtsIndexesEndpoint:
    """REST endpoint for FTS index management."""

    def __init__(self, app_impl, auth_dependency):
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    async def _acquire(self):
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

    async def list_indexes(self, space_id: str, current_user: Dict):
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            rows = await list_fts_indexes(conn, space_id)
            indexes = [
                FtsIndexOut(
                    index_id=r["index_id"],
                    index_name=r["index_name"],
                    languages=r["languages"],
                    created_time=r.get("created_time"),
                )
                for r in rows
            ]
            return FtsIndexListResponse(indexes=indexes, total_count=len(indexes))
        finally:
            await self._release(conn)

    async def create_index(
        self, space_id: str, body: CreateFtsIndexRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            # Check if already exists → 409
            existing = await get_fts_index(conn, space_id, body.index_name)
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"FTS index '{body.index_name}' already exists",
                )

            ok = await ensure_fts_index(
                conn, space_id, body.index_name, languages=body.languages,
            )
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create FTS index '{body.index_name}' — check server logs",
                )
            info = await get_fts_index(conn, space_id, body.index_name)
            if info is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="FTS index created but not found in registry",
                )
            return FtsIndexOut(
                index_id=info["index_id"],
                index_name=info["index_name"],
                languages=info["languages"],
                created_time=info.get("created_time"),
            )
        finally:
            await self._release(conn)

    async def delete_index(
        self, space_id: str, index_name: str, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            info = await get_fts_index(conn, space_id, index_name)
            if info is None:
                raise HTTPException(status_code=404, detail="FTS index not found")
            ok = await teardown_fts_index(conn, space_id, index_name)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete FTS index",
                )
            return DeleteResponse(message=f"FTS index '{index_name}' deleted", deleted=True)
        finally:
            await self._release(conn)

    async def stats(self, space_id: str, index_name: str, current_user: Dict):
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            info = await get_fts_index(conn, space_id, index_name)
            if info is None:
                raise HTTPException(status_code=404, detail="FTS index not found")
            s = await get_fts_stats(conn, space_id, index_name)
            return FtsIndexStatsResponse(
                index_name=index_name,
                row_count=s["row_count"],
                distinct_entity_count=s["distinct_entity_count"],
                has_tsv_count=s["has_tsv_count"],
            )
        finally:
            await self._release(conn)

    async def update_languages(
        self, space_id: str, index_name: str,
        body: UpdateFtsLanguagesRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            ok = await update_fts_languages(
                conn, space_id, index_name, body.languages,
                refresh_tsv=body.refresh_tsv,
            )
            if not ok:
                raise HTTPException(
                    status_code=404,
                    detail=f"FTS index '{index_name}' not found",
                )
            info = await get_fts_index(conn, space_id, index_name)
            return FtsIndexOut(
                index_id=info["index_id"],
                index_name=info["index_name"],
                languages=info["languages"],
                created_time=info.get("created_time"),
            )
        finally:
            await self._release(conn)

    async def populate(
        self, space_id: str, index_name: str,
        body: PopulateFtsRequest, current_user: Dict,
    ):
        """Start FTS population as a background task and return immediately."""
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            info = await get_fts_index(conn, space_id, index_name)
            if info is None:
                raise HTTPException(status_code=404, detail="FTS index not found")
        finally:
            await self._release(conn)

        # Resolve graph URI → context UUID
        ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
        context_uuid = uuid.uuid5(ns, f"{body.graph_uri}\x00U")

        # Spawn background task
        asyncio.ensure_future(self._run_populate(
            space_id, index_name, context_uuid, body,
        ))

        return PopulateFtsResponse(
            message=f"FTS population started for '{index_name}'",
            index_name=index_name,
            rows_populated=0,
            elapsed_seconds=0.0,
            errors=[],
        )

    async def _run_populate(
        self, space_id: str, index_name: str, context_uuid,
        body: PopulateFtsRequest,
    ):
        """Background worker: populate the FTS index."""
        conn = await self._acquire()
        try:
            from ..vectorization.fts_populator import populate_fts_index
            stats = await populate_fts_index(
                conn, space_id, index_name, context_uuid,
                mapping_type=body.mapping_type,
                type_uri=body.type_uri,
                batch_size=body.batch_size,
            )
            logger.info(
                "FTS populate complete: %s/%s — %d rows (%.1fs)",
                space_id, index_name,
                stats.rows_stored, stats.elapsed_seconds,
            )
        except Exception:
            logger.exception("FTS populate failed: %s/%s", space_id, index_name)
        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/fts-indexes",
            response_model=FtsIndexListResponse,
            tags=["FTS Indexes"],
            summary="List FTS Indexes",
        )
        async def list_route(
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.list_indexes(space_id, current_user)

        @self.router.post(
            "/fts-indexes",
            response_model=FtsIndexOut,
            status_code=status.HTTP_201_CREATED,
            tags=["FTS Indexes"],
            summary="Create FTS Index",
        )
        async def create_route(
            body: CreateFtsIndexRequest,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.create_index(space_id, body, current_user)

        @self.router.delete(
            "/fts-indexes",
            response_model=DeleteResponse,
            tags=["FTS Indexes"],
            summary="Delete FTS Index",
        )
        async def delete_route(
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Index name to delete"),
            current_user: Dict = Depends(auth),
        ):
            return await self.delete_index(space_id, index_name, current_user)

        @self.router.get(
            "/fts-indexes/stats",
            response_model=FtsIndexStatsResponse,
            tags=["FTS Indexes"],
            summary="Get FTS Index Statistics",
        )
        async def stats_route(
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Index name"),
            current_user: Dict = Depends(auth),
        ):
            return await self.stats(space_id, index_name, current_user)

        @self.router.put(
            "/fts-indexes/languages",
            response_model=FtsIndexOut,
            tags=["FTS Indexes"],
            summary="Update FTS Index Languages",
        )
        async def update_languages_route(
            body: UpdateFtsLanguagesRequest,
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Index name"),
            current_user: Dict = Depends(auth),
        ):
            return await self.update_languages(
                space_id, index_name, body, current_user,
            )

        @self.router.post(
            "/fts-indexes/populate",
            response_model=PopulateFtsResponse,
            tags=["FTS Indexes"],
            summary="Populate FTS Index",
            description="Populate FTS data table from entity properties",
        )
        async def populate_route(
            body: PopulateFtsRequest,
            space_id: str = Query(..., description="Space ID"),
            index_name: str = Query(..., description="Index name to populate"),
            current_user: Dict = Depends(auth),
        ):
            return await self.populate(space_id, index_name, body, current_user)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_fts_indexes_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = FtsIndexesEndpoint(app_impl, auth_dependency)
    return endpoint.router
