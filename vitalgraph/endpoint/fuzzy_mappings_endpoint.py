"""Fuzzy Mappings REST Endpoint

REST API for managing fuzzy_mapping + fuzzy_mapping_property rows per space.

Routes (all under /api/fuzzy-mappings):
    GET    /             — list mappings (filterable), or get single if mapping_id provided
    POST   /             — create mapping
    PUT    /             — update mapping fields
    DELETE /             — delete mapping (CASCADE)
    POST   /properties   — add property
    DELETE /properties   — remove property
    POST   /populate     — trigger full population for a mapping
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.role_dependencies import require_space_write, require_space_read
from ..vectorization.fuzzy_mapping_manager import FuzzyMappingManager
from ..model.fuzzy_mappings_model import (
    FuzzyMappingPropertyOut, FuzzyMappingOut, FuzzyMappingListResponse,
    FuzzyMappingStatsResponse,
    CreateFuzzyMappingRequest, UpdateFuzzyMappingRequest, AddFuzzyPropertyRequest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoint class
# ---------------------------------------------------------------------------

class FuzzyMappingsEndpoint:
    """REST endpoint for fuzzy mapping management."""

    def __init__(self, app_impl, auth_dependency):
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    async def _get_manager(self, space_id: str) -> tuple:
        """Acquire a connection and return a (FuzzyMappingManager, conn) tuple."""
        db_impl = self.app_impl.db_impl
        if db_impl is None or not getattr(db_impl, "connection_pool", None):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not available",
            )
        conn = await db_impl.connection_pool.acquire()
        return FuzzyMappingManager(conn, space_id), conn

    async def _release(self, conn):
        """Release the connection back to the pool."""
        try:
            db_impl = self.app_impl.db_impl
            if db_impl and db_impl.connection_pool:
                await db_impl.connection_pool.release(conn)
        except Exception:
            logger.exception("Error releasing connection")

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    async def list_mappings(
        self,
        space_id: str,
        index_name: Optional[str],
        mapping_type: Optional[str],
        enabled: Optional[bool],
        current_user: Dict,
    ):
        require_space_read(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dtos = await manager.list_mappings(
                index_name=index_name,
                mapping_type=mapping_type,
                enabled=enabled,
            )
            mappings = [FuzzyMappingOut(**d.to_dict()) for d in dtos]
            return FuzzyMappingListResponse(mappings=mappings, total_count=len(mappings))
        finally:
            await self._release(conn)

    async def create_mapping(self, space_id: str, body: CreateFuzzyMappingRequest, current_user: Dict):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            mapping_id = await manager.create_mapping(
                index_name=body.index_name,
                mapping_type=body.mapping_type,
                type_uri=body.type_uri,
                enabled=body.enabled,
                shingle_k=body.shingle_k,
                num_perm=body.num_perm,
                lsh_threshold=body.lsh_threshold,
                phonetic_bonus=body.phonetic_bonus,
            )
            dto = await manager.get_mapping(mapping_id)
            return FuzzyMappingOut(**dto.to_dict())
        finally:
            await self._release(conn)

    async def get_mapping(self, space_id: str, mapping_id: int, current_user: Dict):
        require_space_read(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dto = await manager.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Fuzzy mapping not found")
            return FuzzyMappingOut(**dto.to_dict())
        finally:
            await self._release(conn)

    async def update_mapping(
        self, space_id: str, mapping_id: int, body: UpdateFuzzyMappingRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dto = await manager.update_mapping(mapping_id, **body.dict(exclude_none=True))
            if dto is None:
                raise HTTPException(status_code=404, detail="Fuzzy mapping not found")
            return FuzzyMappingOut(**dto.to_dict())
        finally:
            await self._release(conn)

    async def delete_mapping(self, space_id: str, mapping_id: int, current_user: Dict):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            deleted = await manager.delete_mapping(mapping_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Fuzzy mapping not found")
            return {"message": "Fuzzy mapping deleted", "mapping_id": mapping_id}
        finally:
            await self._release(conn)

    async def add_property(
        self, space_id: str, mapping_id: int, body: AddFuzzyPropertyRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            pid = await manager.add_property(
                mapping_id,
                body.property_uri,
                property_role=body.property_role,
                ordinal=body.ordinal,
            )
            return FuzzyMappingPropertyOut(
                property_id=pid,
                mapping_id=mapping_id,
                property_uri=body.property_uri,
                property_role=body.property_role,
                ordinal=body.ordinal,
            )
        finally:
            await self._release(conn)

    async def remove_property(
        self, space_id: str, mapping_id: int, property_id: int, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            deleted = await manager.remove_property(property_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Property not found")
            return {"message": "Property removed", "property_id": property_id}
        finally:
            await self._release(conn)

    async def populate_mapping(
        self, space_id: str, mapping_id: int, current_user: Dict,
    ):
        """Start fuzzy population as a background task and return immediately.

        With large datasets the population can take minutes; running it
        synchronously inside the HTTP handler would hold a DB connection,
        block the caller, and risk an upstream timeout.  The background
        task acquires its own connection so the request connection is
        released immediately.
        """
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dto = await manager.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Fuzzy mapping not found")
            index_name = dto.index_name
        finally:
            await self._release(conn)

        # Spawn background task (acquires its own connection)
        asyncio.ensure_future(self._run_populate(space_id, mapping_id, index_name))

        return {
            "message": f"Fuzzy population started for mapping {mapping_id}",
            "mapping_id": mapping_id,
            "entities_indexed": 0,
        }

    async def _run_populate(
        self, space_id: str, mapping_id: int, index_name: str,
    ):
        """Background worker: populate the fuzzy index."""
        db_impl = self.app_impl.db_impl
        conn = await db_impl.connection_pool.acquire()
        try:
            from ..vectorization.fuzzy_populator import populate_fuzzy_index
            count = await populate_fuzzy_index(
                conn, space_id, index_name=index_name,
            )
            logger.info(
                "Fuzzy populate complete: %s/mapping_%s — %d entities",
                space_id, mapping_id, count,
            )
        except Exception:
            logger.exception("Fuzzy populate failed: %s/mapping_%s", space_id, mapping_id)
        finally:
            try:
                await db_impl.connection_pool.release(conn)
            except Exception:
                logger.exception("Error releasing fuzzy populate connection")

    async def get_stats(
        self, space_id: str, mapping_id: int, current_user: Dict,
    ):
        """Get index statistics for a fuzzy mapping."""
        require_space_read(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            stats = await manager.get_stats(mapping_id)
            if stats is None:
                raise HTTPException(status_code=404, detail="Fuzzy mapping not found")
            return FuzzyMappingStatsResponse(**stats)
        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/fuzzy-mappings",
            response_model=Union[FuzzyMappingOut, FuzzyMappingListResponse],
            tags=["Fuzzy Mappings"],
            summary="List or Get Fuzzy Mappings",
            description="List all fuzzy mappings for a space, or get a single mapping if mapping_id is provided",
        )
        async def list_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: Optional[int] = Query(None, description="Mapping ID (returns single if provided)"),
            index_name: Optional[str] = Query(None),
            mapping_type: Optional[str] = Query(None),
            enabled: Optional[bool] = Query(None),
            current_user: Dict = Depends(auth),
        ):
            if mapping_id is not None:
                return await self.get_mapping(space_id, mapping_id, current_user)
            return await self.list_mappings(space_id, index_name, mapping_type, enabled, current_user)

        @self.router.post(
            "/fuzzy-mappings",
            response_model=FuzzyMappingOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Fuzzy Mappings"],
            summary="Create Fuzzy Mapping",
        )
        async def create_route(
            body: CreateFuzzyMappingRequest,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.create_mapping(space_id, body, current_user)

        @self.router.put(
            "/fuzzy-mappings",
            response_model=FuzzyMappingOut,
            tags=["Fuzzy Mappings"],
            summary="Update Fuzzy Mapping",
        )
        async def update_route(
            body: UpdateFuzzyMappingRequest,
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID to update"),
            current_user: Dict = Depends(auth),
        ):
            return await self.update_mapping(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/fuzzy-mappings",
            tags=["Fuzzy Mappings"],
            summary="Delete Fuzzy Mapping",
        )
        async def delete_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID to delete"),
            current_user: Dict = Depends(auth),
        ):
            return await self.delete_mapping(space_id, mapping_id, current_user)

        @self.router.post(
            "/fuzzy-mappings/properties",
            response_model=FuzzyMappingPropertyOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Fuzzy Mappings"],
            summary="Add Fuzzy Mapping Property",
        )
        async def add_prop_route(
            body: AddFuzzyPropertyRequest,
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.add_property(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/fuzzy-mappings/properties",
            tags=["Fuzzy Mappings"],
            summary="Remove Fuzzy Mapping Property",
        )
        async def remove_prop_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID"),
            property_id: int = Query(..., description="Property ID to remove"),
            current_user: Dict = Depends(auth),
        ):
            return await self.remove_property(space_id, mapping_id, property_id, current_user)

        @self.router.get(
            "/fuzzy-mappings/stats",
            response_model=FuzzyMappingStatsResponse,
            tags=["Fuzzy Mappings"],
            summary="Get Fuzzy Index Statistics",
            description="Get band count, entity count, and phonetic band count for a mapping",
        )
        async def stats_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.get_stats(space_id, mapping_id, current_user)

        @self.router.post(
            "/fuzzy-mappings/populate",
            tags=["Fuzzy Mappings"],
            summary="Populate Fuzzy Index",
            description="Trigger a full population of fuzzy bands for a specific mapping",
        )
        async def populate_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID to populate"),
            current_user: Dict = Depends(auth),
        ):
            return await self.populate_mapping(space_id, mapping_id, current_user)


def create_fuzzy_mappings_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = FuzzyMappingsEndpoint(app_impl, auth_dependency)
    return endpoint.router
