"""Vector Mappings REST Endpoint

REST API for managing vector_mapping + vector_mapping_property rows per space.

Routes (all under /api/spaces/{space_id}/vector-mappings):
    GET    /                         — list mappings (filterable)
    POST   /                         — create mapping
    GET    /{mapping_id}             — get mapping + properties
    PUT    /{mapping_id}             — update mapping fields
    DELETE /{mapping_id}             — delete mapping (CASCADE)
    POST   /{mapping_id}/properties  — add property
    DELETE /{mapping_id}/properties/{property_id} — remove property
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..auth.role_dependencies import require_space_write, require_space_read
from ..vectorization.mapping_manager import MappingManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class MappingPropertyOut(BaseModel):
    property_id: int
    mapping_id: int
    property_uri: str
    property_role: str = "include"
    ordinal: int = 0


class MappingOut(BaseModel):
    mapping_id: int
    mapping_type: str
    type_uri: Optional[str] = None
    index_name: str
    enabled: bool = True
    source_type: str = "default"
    separator: str = ". "
    include_pred_name: bool = False
    include_type_desc: bool = True
    created_time: Optional[str] = None
    properties: List[MappingPropertyOut] = []


class MappingListResponse(BaseModel):
    mappings: List[MappingOut]
    total_count: int


class CreateMappingRequest(BaseModel):
    mapping_type: str = Field(..., description="kgentity | kgdocument | kgframe | kgslot")
    type_uri: Optional[str] = Field(None, description="Specific KG Type URI (NULL = class-level)")
    index_name: str = Field(..., description="Vector index name")
    enabled: bool = Field(True, description="Enable/disable vectorization")
    source_type: str = Field("default", description="default | properties | slots")
    separator: str = Field(". ", description="Separator for concatenated text")
    include_pred_name: bool = Field(False, description="Include predicate local name in text")
    include_type_desc: bool = Field(True, description="Include KG Type description in text")


class UpdateMappingRequest(BaseModel):
    enabled: Optional[bool] = None
    source_type: Optional[str] = None
    separator: Optional[str] = None
    include_pred_name: Optional[bool] = None
    include_type_desc: Optional[bool] = None


class AddPropertyRequest(BaseModel):
    property_uri: str = Field(..., description="Predicate URI or slot type URI")
    property_role: str = Field("include", description="include | exclude")
    ordinal: int = Field(0, description="Controls concatenation order")


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
        """Acquire a connection and return a (MappingManager, conn) tuple."""
        db_impl = self.app_impl.db_impl
        if db_impl is None or not getattr(db_impl, "connection_pool", None):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not available",
            )
        conn = await db_impl.connection_pool.acquire()
        return MappingManager(conn, space_id), conn

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
            mappings = [MappingOut(**d.to_dict()) for d in dtos]
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
                include_type_desc=body.include_type_desc,
            )
            dto = await manager.get_mapping(mapping_id)
            return MappingOut(**dto.to_dict())
        finally:
            await self._release(conn)

    async def get_mapping(self, space_id: str, mapping_id: int, current_user: Dict):
        require_space_read(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dto = await manager.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return MappingOut(**dto.to_dict())
        finally:
            await self._release(conn)

    async def update_mapping(
        self, space_id: str, mapping_id: int, body: UpdateMappingRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        manager, conn = await self._get_manager(space_id)
        try:
            dto = await manager.update_mapping(mapping_id, **body.dict(exclude_none=True))
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return MappingOut(**dto.to_dict())
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
            "/spaces/{space_id}/vector-mappings",
            response_model=MappingListResponse,
            tags=["Vector Mappings"],
            summary="List Vector Mappings",
            description="List all vector mappings for a space, with optional filters",
        )
        async def list_route(
            space_id: str,
            index_name: Optional[str] = Query(None),
            mapping_type: Optional[str] = Query(None),
            enabled: Optional[bool] = Query(None),
            current_user: Dict = Depends(auth),
        ):
            return await self.list_mappings(space_id, index_name, mapping_type, enabled, current_user)

        @self.router.post(
            "/spaces/{space_id}/vector-mappings",
            response_model=MappingOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Vector Mappings"],
            summary="Create Vector Mapping",
        )
        async def create_route(
            space_id: str,
            body: CreateMappingRequest,
            current_user: Dict = Depends(auth),
        ):
            return await self.create_mapping(space_id, body, current_user)

        @self.router.get(
            "/spaces/{space_id}/vector-mappings/{mapping_id}",
            response_model=MappingOut,
            tags=["Vector Mappings"],
            summary="Get Vector Mapping",
        )
        async def get_route(
            space_id: str,
            mapping_id: int,
            current_user: Dict = Depends(auth),
        ):
            return await self.get_mapping(space_id, mapping_id, current_user)

        @self.router.put(
            "/spaces/{space_id}/vector-mappings/{mapping_id}",
            response_model=MappingOut,
            tags=["Vector Mappings"],
            summary="Update Vector Mapping",
        )
        async def update_route(
            space_id: str,
            mapping_id: int,
            body: UpdateMappingRequest,
            current_user: Dict = Depends(auth),
        ):
            return await self.update_mapping(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/spaces/{space_id}/vector-mappings/{mapping_id}",
            tags=["Vector Mappings"],
            summary="Delete Vector Mapping",
        )
        async def delete_route(
            space_id: str,
            mapping_id: int,
            current_user: Dict = Depends(auth),
        ):
            return await self.delete_mapping(space_id, mapping_id, current_user)

        @self.router.post(
            "/spaces/{space_id}/vector-mappings/{mapping_id}/properties",
            response_model=MappingPropertyOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Vector Mappings"],
            summary="Add Mapping Property",
        )
        async def add_prop_route(
            space_id: str,
            mapping_id: int,
            body: AddPropertyRequest,
            current_user: Dict = Depends(auth),
        ):
            return await self.add_property(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/spaces/{space_id}/vector-mappings/{mapping_id}/properties/{property_id}",
            tags=["Vector Mappings"],
            summary="Remove Mapping Property",
        )
        async def remove_prop_route(
            space_id: str,
            mapping_id: int,
            property_id: int,
            current_user: Dict = Depends(auth),
        ):
            return await self.remove_property(space_id, mapping_id, property_id, current_user)


def create_vector_mappings_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = VectorMappingsEndpoint(app_impl, auth_dependency)
    return endpoint.router
