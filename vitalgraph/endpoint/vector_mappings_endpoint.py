"""Vector Mappings REST Endpoint

REST API for managing search_mapping + search_mapping_property rows per space.
(Legacy /api/vector-mappings routes — delegates to shared search_mapping tables.)

Routes (all under /api/vector-mappings):
    GET    /             — list mappings (filterable), or get single if mapping_id provided
    POST   /             — create mapping
    PUT    /             — update mapping fields
    DELETE /             — delete mapping (CASCADE)
    POST   /properties   — add property
    DELETE /properties   — remove property
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.role_dependencies import require_space_write, require_space_read
from ..vectorization.search_mapping_manager import SearchMappingManager
from ..model.vector_mappings_model import (
    MappingPropertyOut, MappingOut, MappingListResponse,
    CreateMappingRequest, UpdateMappingRequest, AddPropertyRequest,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoint class
# ---------------------------------------------------------------------------

class VectorMappingsEndpoint:
    """REST endpoint for vector mapping management."""

    def __init__(self, app_impl, auth_dependency):
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.router = APIRouter()
        self._setup_routes()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------

    async def _get_manager(self, space_id: str) -> tuple:
        """Acquire a connection and return a (SearchMappingManager, conn) tuple."""
        db_impl = self.app_impl.db_impl
        if db_impl is None or not getattr(db_impl, "connection_pool", None):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not available",
            )
        conn = await db_impl.connection_pool.acquire()
        return SearchMappingManager(conn, space_id), conn

    async def _release(self, conn):
        """Release the connection back to the pool."""
        try:
            db_impl = self.app_impl.db_impl
            if db_impl and db_impl.connection_pool:
                await db_impl.connection_pool.release(conn)
        except Exception:
            logger.exception("Error releasing connection")

    # ------------------------------------------------------------------
    # DTO conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _dto_to_out(dto) -> MappingOut:
        """Convert SearchMappingDTO to the vector MappingOut model."""
        return MappingOut(
            mapping_id=dto.mapping_id,
            mapping_type=dto.mapping_type,
            type_uri=dto.type_uri,
            index_name=dto.index_name,
            enabled=dto.enabled,
            source_type=dto.source_type,
            separator=dto.separator,
            include_pred_name=dto.include_pred_name,
            created_time=dto.created_time,
            properties=[
                MappingPropertyOut(
                    property_id=p.property_id,
                    mapping_id=p.mapping_id,
                    property_uri=p.property_uri,
                    property_role=p.property_role,
                    ordinal=p.ordinal,
                )
                for p in dto.properties
            ],
        )

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
            mappings = [self._dto_to_out(d) for d in dtos]
            return MappingListResponse(mappings=mappings, total_count=len(mappings))
        finally:
            await self._release(conn)

    async def create_mapping(self, space_id: str, body: CreateMappingRequest, current_user: Dict):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            mapping_id = await manager.create_mapping(
                index_name=body.index_name,
                mapping_type=body.mapping_type,
                type_uri=body.type_uri,
                enabled=body.enabled,
                source_type=body.source_type,
                separator=body.separator,
                include_pred_name=body.include_pred_name,
            )
            dto = await manager.get_mapping(mapping_id)
            return self._dto_to_out(dto)
        finally:
            await self._release(conn)

    async def get_mapping(self, space_id: str, mapping_id: int, current_user: Dict):
        require_space_read(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dto = await manager.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return self._dto_to_out(dto)
        finally:
            await self._release(conn)

    async def update_mapping(
        self, space_id: str, mapping_id: int, body: UpdateMappingRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dto = await manager.update_mapping(mapping_id, **body.model_dump(exclude_none=True))
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return self._dto_to_out(dto)
        finally:
            await self._release(conn)

    async def delete_mapping(self, space_id: str, mapping_id: int, current_user: Dict):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            deleted = await manager.delete_mapping(mapping_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return {"message": "Mapping deleted", "mapping_id": mapping_id}
        finally:
            await self._release(conn)

    async def add_property(
        self, space_id: str, mapping_id: int, body: AddPropertyRequest, current_user: Dict,
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
            return MappingPropertyOut(
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

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/vector-mappings",
            response_model=Union[MappingOut, MappingListResponse],
            tags=["Vector Mappings"],
            summary="List or Get Vector Mappings",
            description="List all vector mappings for a space (with optional filters), or get a single mapping if mapping_id is provided",
        )
        async def list_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: Optional[int] = Query(None, description="Mapping ID (returns single mapping if provided)"),
            index_name: Optional[str] = Query(None),
            mapping_type: Optional[str] = Query(None),
            enabled: Optional[bool] = Query(None),
            current_user: Dict = Depends(auth),
        ):
            if mapping_id is not None:
                return await self.get_mapping(space_id, mapping_id, current_user)
            return await self.list_mappings(space_id, index_name, mapping_type, enabled, current_user)

        @self.router.post(
            "/vector-mappings",
            response_model=MappingOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Vector Mappings"],
            summary="Create Vector Mapping",
        )
        async def create_route(
            space_id: str = Query(..., description="Space ID"),
            body: CreateMappingRequest = None,
            current_user: Dict = Depends(auth),
        ):
            return await self.create_mapping(space_id, body, current_user)

        @self.router.put(
            "/vector-mappings",
            response_model=MappingOut,
            tags=["Vector Mappings"],
            summary="Update Vector Mapping",
        )
        async def update_route(
            body: UpdateMappingRequest,
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID to update"),
            current_user: Dict = Depends(auth),
        ):
            return await self.update_mapping(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/vector-mappings",
            tags=["Vector Mappings"],
            summary="Delete Vector Mapping",
        )
        async def delete_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID to delete"),
            current_user: Dict = Depends(auth),
        ):
            return await self.delete_mapping(space_id, mapping_id, current_user)

        @self.router.post(
            "/vector-mappings/properties",
            response_model=MappingPropertyOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Vector Mappings"],
            summary="Add Mapping Property",
        )
        async def add_prop_route(
            body: AddPropertyRequest,
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.add_property(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/vector-mappings/properties",
            tags=["Vector Mappings"],
            summary="Remove Mapping Property",
        )
        async def remove_prop_route(
            space_id: str = Query(..., description="Space ID"),
            mapping_id: int = Query(..., description="Mapping ID"),
            property_id: int = Query(..., description="Property ID to remove"),
            current_user: Dict = Depends(auth),
        ):
            return await self.remove_property(space_id, mapping_id, property_id, current_user)


def create_vector_mappings_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = VectorMappingsEndpoint(app_impl, auth_dependency)
    return endpoint.router
