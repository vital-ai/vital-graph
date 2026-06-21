"""Search Mappings REST Endpoint

REST API for managing shared search mappings (``{space}_search_mapping`` +
``{space}_search_mapping_property``).  These mappings define which entity
types and predicates feed into named search indexes, and are shared by
both FTS and vector indexes.

Routes (all under /api/search-mappings):
    GET    /                 — list mappings (optional filters)
    POST   /                 — create mapping
    GET    /{mapping_id}     — get single mapping with properties
    PUT    /{mapping_id}     — update mapping
    DELETE /{mapping_id}     — delete mapping (CASCADE deletes properties)
    POST   /{mapping_id}/properties — add property
    DELETE /{mapping_id}/properties/{property_id} — remove property
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth.role_dependencies import require_space_read, require_space_write
from ..model.search_mappings_model import (
    SearchMappingOut, SearchMappingPropertyOut, SearchMappingIndexOut,
    SearchMappingListResponse,
    CreateSearchMappingRequest, UpdateSearchMappingRequest,
    AddIndexRequest, AddPropertyRequest, DeleteResponse,
)
from ..vectorization.search_mapping_manager import SearchMappingManager

logger = logging.getLogger(__name__)


class SearchMappingsEndpoint:
    """REST endpoint for shared search mapping management."""

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

    async def list_mappings(
        self, space_id: str, current_user: Dict,
        index_name: Optional[str] = None,
        mapping_type: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            dtos = await mgr.list_mappings(
                index_name=index_name,
                mapping_type=mapping_type,
                enabled=enabled,
            )
            mappings = [_dto_to_out(d) for d in dtos]
            return SearchMappingListResponse(
                mappings=mappings, total_count=len(mappings),
            )
        except Exception as e:
            if "UndefinedTable" in type(e).__name__ or "does not exist" in str(e):
                logger.warning("Search mapping table not found for space %s — returning empty list", space_id)
                return SearchMappingListResponse(mappings=[], total_count=0)
            raise
        finally:
            await self._release(conn)

    async def get_mapping(self, space_id: str, mapping_id: int, current_user: Dict):
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            dto = await mgr.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return _dto_to_out(dto)
        finally:
            await self._release(conn)

    async def create_mapping(
        self, space_id: str, body: CreateSearchMappingRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            mapping_id = await mgr.create_mapping(
                index_name=body.index_name,
                mapping_type=body.mapping_type,
                type_uri=body.type_uri,
                enabled=body.enabled,
                source_type=body.source_type,
                separator=body.separator,
                include_pred_name=body.include_pred_name,
            )
            dto = await mgr.get_mapping(mapping_id)
            return _dto_to_out(dto)
        finally:
            await self._release(conn)

    async def update_mapping(
        self, space_id: str, mapping_id: int,
        body: UpdateSearchMappingRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            update_fields = body.model_dump(exclude_none=True)
            dto = await mgr.update_mapping(mapping_id, **update_fields)
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return _dto_to_out(dto)
        finally:
            await self._release(conn)

    async def delete_mapping(
        self, space_id: str, mapping_id: int, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            deleted = await mgr.delete_mapping(mapping_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Mapping not found")
            return DeleteResponse(message="Mapping deleted", deleted=True)
        finally:
            await self._release(conn)

    async def add_property(
        self, space_id: str, mapping_id: int,
        body: AddPropertyRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            # Verify mapping exists
            dto = await mgr.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            prop_id = await mgr.add_property(
                mapping_id, body.property_uri,
                property_role=body.property_role,
                ordinal=body.ordinal,
            )
            return SearchMappingPropertyOut(
                property_id=prop_id,
                mapping_id=mapping_id,
                property_uri=body.property_uri,
                property_role=body.property_role,
                ordinal=body.ordinal,
            )
        finally:
            await self._release(conn)

    async def remove_property(
        self, space_id: str, mapping_id: int, property_id: int,
        current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            deleted = await mgr.remove_property(property_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Property not found")
            return DeleteResponse(message="Property deleted", deleted=True)
        finally:
            await self._release(conn)

    async def list_indexes(
        self, space_id: str, mapping_id: int, current_user: Dict,
    ):
        require_space_read(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            dto = await mgr.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            indexes = await mgr.list_indexes(mapping_id)
            return [SearchMappingIndexOut(
                id=i.id, mapping_id=i.mapping_id,
                index_type=i.index_type, index_name=i.index_name,
                created_time=i.created_time,
            ) for i in indexes]
        finally:
            await self._release(conn)

    async def add_index(
        self, space_id: str, mapping_id: int,
        body: AddIndexRequest, current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        if body.index_type not in ('vector', 'fts'):
            raise HTTPException(
                status_code=400,
                detail="index_type must be 'vector' or 'fts'",
            )
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            dto = await mgr.get_mapping(mapping_id)
            if dto is None:
                raise HTTPException(status_code=404, detail="Mapping not found")
            junction_id = await mgr.add_index(
                mapping_id, body.index_type, body.index_name,
            )
            return SearchMappingIndexOut(
                id=junction_id, mapping_id=mapping_id,
                index_type=body.index_type, index_name=body.index_name,
            )
        finally:
            await self._release(conn)

    async def remove_index(
        self, space_id: str, mapping_id: int, junction_id: int,
        current_user: Dict,
    ):
        require_space_write(current_user, space_id)
        conn = await self._acquire()
        try:
            mgr = SearchMappingManager(conn, space_id)
            deleted = await mgr.remove_index(junction_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Index association not found")
            return DeleteResponse(message="Index association removed", deleted=True)
        finally:
            await self._release(conn)

    # ------------------------------------------------------------------
    # Route wiring
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        @self.router.get(
            "/search-mappings",
            response_model=SearchMappingListResponse,
            tags=["Search Mappings"],
            summary="List Search Mappings",
        )
        async def list_route(
            space_id: str = Query(..., description="Space ID"),
            index_name: Optional[str] = Query(None),
            mapping_type: Optional[str] = Query(None),
            enabled: Optional[bool] = Query(None),
            current_user: Dict = Depends(auth),
        ):
            return await self.list_mappings(
                space_id, current_user,
                index_name=index_name,
                mapping_type=mapping_type,
                enabled=enabled,
            )

        @self.router.get(
            "/search-mappings/{mapping_id}",
            response_model=SearchMappingOut,
            tags=["Search Mappings"],
            summary="Get Search Mapping",
        )
        async def get_route(
            mapping_id: int,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.get_mapping(space_id, mapping_id, current_user)

        @self.router.post(
            "/search-mappings",
            response_model=SearchMappingOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Search Mappings"],
            summary="Create Search Mapping",
        )
        async def create_route(
            body: CreateSearchMappingRequest,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.create_mapping(space_id, body, current_user)

        @self.router.put(
            "/search-mappings/{mapping_id}",
            response_model=SearchMappingOut,
            tags=["Search Mappings"],
            summary="Update Search Mapping",
        )
        async def update_route(
            mapping_id: int,
            body: UpdateSearchMappingRequest,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.update_mapping(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/search-mappings/{mapping_id}",
            response_model=DeleteResponse,
            tags=["Search Mappings"],
            summary="Delete Search Mapping",
        )
        async def delete_route(
            mapping_id: int,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.delete_mapping(space_id, mapping_id, current_user)

        @self.router.post(
            "/search-mappings/{mapping_id}/properties",
            response_model=SearchMappingPropertyOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Search Mappings"],
            summary="Add Property to Mapping",
        )
        async def add_property_route(
            mapping_id: int,
            body: AddPropertyRequest,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.add_property(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/search-mappings/{mapping_id}/properties/{property_id}",
            response_model=DeleteResponse,
            tags=["Search Mappings"],
            summary="Remove Property from Mapping",
        )
        async def remove_property_route(
            mapping_id: int,
            property_id: int,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.remove_property(
                space_id, mapping_id, property_id, current_user,
            )

        @self.router.get(
            "/search-mappings/{mapping_id}/indexes",
            response_model=list,
            tags=["Search Mappings"],
            summary="List Index Associations",
        )
        async def list_indexes_route(
            mapping_id: int,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.list_indexes(space_id, mapping_id, current_user)

        @self.router.post(
            "/search-mappings/{mapping_id}/indexes",
            response_model=SearchMappingIndexOut,
            status_code=status.HTTP_201_CREATED,
            tags=["Search Mappings"],
            summary="Associate Index with Mapping",
        )
        async def add_index_route(
            mapping_id: int,
            body: AddIndexRequest,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.add_index(space_id, mapping_id, body, current_user)

        @self.router.delete(
            "/search-mappings/{mapping_id}/indexes/{junction_id}",
            response_model=DeleteResponse,
            tags=["Search Mappings"],
            summary="Remove Index Association",
        )
        async def remove_index_route(
            mapping_id: int,
            junction_id: int,
            space_id: str = Query(..., description="Space ID"),
            current_user: Dict = Depends(auth),
        ):
            return await self.remove_index(
                space_id, mapping_id, junction_id, current_user,
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dto_to_out(dto) -> SearchMappingOut:
    """Convert a SearchMappingDTO to the Pydantic response model."""
    return SearchMappingOut(
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
            SearchMappingPropertyOut(
                property_id=p.property_id,
                mapping_id=p.mapping_id,
                property_uri=p.property_uri,
                property_role=p.property_role,
                ordinal=p.ordinal,
            )
            for p in dto.properties
        ],
        indexes=[
            SearchMappingIndexOut(
                id=i.id,
                mapping_id=i.mapping_id,
                index_type=i.index_type,
                index_name=i.index_name,
                created_time=i.created_time,
            )
            for i in getattr(dto, 'indexes', [])
        ],
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_search_mappings_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function matching the pattern used by other endpoints."""
    endpoint = SearchMappingsEndpoint(app_impl, auth_dependency)
    return endpoint.router
