"""
Entity Registry REST API Endpoint.

Provides CRUD operations for entities, aliases, identifiers,
same-as mappings, entity types, and change logs.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..model.entity_registry_model import (
    AliasCreateRequest,
    AliasResponse,
    ChangeLogEntry,
    ChangeLogResponse,
    EntityCreateRequest,
    EntityCreateResponse,
    EntityListResponse,
    EntityResponse,
    EntityTypeCreateRequest,
    EntityTypeResponse,
    EntityUpdateRequest,
    IdentifierCreateRequest,
    IdentifierResponse,
    SameAsCreateRequest,
    SameAsResponse,
    SameAsRetractRequest,
)
from ..entity_registry.entity_registry_id import entity_id_to_uri


logger = logging.getLogger(__name__)


def _entity_to_response(entity: dict) -> EntityResponse:
    """Convert an entity dict from the impl layer to an EntityResponse."""
    identifiers = None
    if entity.get('identifiers'):
        identifiers = [IdentifierResponse(**ident) for ident in entity['identifiers']]

    aliases = None
    if entity.get('aliases'):
        aliases = [AliasResponse(**alias) for alias in entity['aliases']]

    return EntityResponse(
        entity_id=entity['entity_id'],
        entity_uri=entity.get('entity_uri', entity_id_to_uri(entity['entity_id'])),
        type_key=entity.get('type_key'),
        type_label=entity.get('type_label'),
        primary_name=entity['primary_name'],
        description=entity.get('description'),
        country=entity.get('country'),
        region=entity.get('region'),
        locality=entity.get('locality'),
        website=entity.get('website'),
        status=entity['status'],
        created_time=entity.get('created_time'),
        updated_time=entity.get('updated_time'),
        created_by=entity.get('created_by'),
        notes=entity.get('notes'),
        identifiers=identifiers,
        aliases=aliases,
    )


class EntityRegistryEndpoint:
    """FastAPI endpoint handler for the Entity Registry."""

    def __init__(self, app_impl, auth_dependency):
        """
        Args:
            app_impl: VitalGraphAppImpl instance (provides self.entity_registry at runtime).
            auth_dependency: FastAPI dependency for JWT auth.
        """
        self.app_impl = app_impl
        self.auth_dependency = auth_dependency
        self.logger = logging.getLogger(f"{__name__}.EntityRegistryEndpoint")
        self.router = APIRouter()
        self._setup_routes()

    @property
    def registry(self):
        """Get the EntityRegistryImpl from app_impl (set during startup)."""
        reg = getattr(self.app_impl, 'entity_registry', None)
        if reg is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Entity Registry not initialized"
            )
        return reg

    # ------------------------------------------------------------------
    # Route setup
    # ------------------------------------------------------------------

    def _setup_routes(self):
        auth = self.auth_dependency

        # -- Entity CRUD --

        @self.router.post("/entities", response_model=EntityCreateResponse, tags=["Entity Registry"])
        async def create_entity_route(request: EntityCreateRequest, current_user: Dict = Depends(auth)):
            try:
                aliases = [a.model_dump() for a in request.aliases] if request.aliases else None
                identifiers = [i.model_dump() for i in request.identifiers] if request.identifiers else None
                entity = await self.registry.create_entity(
                    type_key=request.type_key, primary_name=request.primary_name,
                    description=request.description, country=request.country,
                    region=request.region, locality=request.locality,
                    website=request.website, created_by=request.created_by,
                    notes=request.notes, aliases=aliases, identifiers=identifiers,
                )
                full = await self.registry.get_entity(entity['entity_id'])
                return EntityCreateResponse(
                    success=True, entity_id=entity['entity_id'],
                    entity_uri=entity['entity_uri'], entity=_entity_to_response(full),
                )
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
            except Exception as e:
                self.logger.error(f"Error creating entity: {e}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

        @self.router.get("/entities", response_model=EntityListResponse, tags=["Entity Registry"])
        async def list_entities_route(
            query: Optional[str] = Query(None, description="Search text (ILIKE on name/aliases)"),
            type_key: Optional[str] = Query(None),
            country: Optional[str] = Query(None),
            region: Optional[str] = Query(None),
            entity_status: Optional[str] = Query('active', alias="status"),
            page: int = Query(1, ge=1),
            page_size: int = Query(20, ge=1, le=100),
            current_user: Dict = Depends(auth),
        ):
            entities, total = await self.registry.search_entities(
                query=query, type_key=type_key, country=country, region=region,
                status=entity_status, page=page, page_size=page_size,
            )
            return EntityListResponse(
                success=True, entities=[_entity_to_response(e) for e in entities],
                total_count=total, page=page, page_size=page_size,
            )

        @self.router.get("/entities/{entity_id}", response_model=EntityResponse, tags=["Entity Registry"])
        async def get_entity_route(entity_id: str, current_user: Dict = Depends(auth)):
            entity = await self.registry.get_entity(entity_id)
            if entity is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found: {entity_id}")
            return _entity_to_response(entity)

        @self.router.put("/entities/{entity_id}", response_model=EntityResponse, tags=["Entity Registry"])
        async def update_entity_route(entity_id: str, request: EntityUpdateRequest,
                                      current_user: Dict = Depends(auth)):
            try:
                entity = await self.registry.update_entity(
                    entity_id=entity_id, primary_name=request.primary_name,
                    description=request.description, country=request.country,
                    region=request.region, locality=request.locality,
                    website=request.website, status=request.status,
                    updated_by=request.updated_by, notes=request.notes,
                )
                if entity is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found: {entity_id}")
                return _entity_to_response(entity)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.delete("/entities/{entity_id}", tags=["Entity Registry"])
        async def delete_entity_route(entity_id: str, current_user: Dict = Depends(auth)):
            deleted = await self.registry.delete_entity(entity_id)
            if not deleted:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found: {entity_id}")
            return {"success": True, "entity_id": entity_id}

        # -- Identifiers --

        @self.router.post("/entities/{entity_id}/identifiers", response_model=IdentifierResponse, tags=["Entity Registry"])
        async def add_identifier_route(entity_id: str, request: IdentifierCreateRequest,
                                       current_user: Dict = Depends(auth)):
            try:
                ident = await self.registry.add_identifier(
                    entity_id=entity_id, identifier_namespace=request.identifier_namespace,
                    identifier_value=request.identifier_value, is_primary=request.is_primary,
                    created_by=request.created_by, notes=request.notes,
                )
                return IdentifierResponse(**ident)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/entities/{entity_id}/identifiers", tags=["Entity Registry"])
        async def list_identifiers_route(entity_id: str, current_user: Dict = Depends(auth)):
            idents = await self.registry.list_identifiers(entity_id)
            return [IdentifierResponse(**i) for i in idents]

        @self.router.delete("/identifiers/{identifier_id}", tags=["Entity Registry"])
        async def remove_identifier_route(identifier_id: int, current_user: Dict = Depends(auth)):
            removed = await self.registry.remove_identifier(identifier_id)
            if not removed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Identifier not found: {identifier_id}")
            return {"success": True, "identifier_id": identifier_id}

        @self.router.get("/lookup", response_model=List[EntityResponse], tags=["Entity Registry"])
        async def lookup_by_identifier_route(
            namespace: str = Query(..., description="Identifier namespace"),
            value: str = Query(..., description="Identifier value"),
            current_user: Dict = Depends(auth),
        ):
            entities = await self.registry.lookup_by_identifier(namespace, value)
            if not entities:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"No entity found for {namespace}:{value}")
            return [_entity_to_response(e) for e in entities]

        # -- Aliases --

        @self.router.post("/entities/{entity_id}/aliases", response_model=AliasResponse, tags=["Entity Registry"])
        async def add_alias_route(entity_id: str, request: AliasCreateRequest,
                                  current_user: Dict = Depends(auth)):
            try:
                alias = await self.registry.add_alias(
                    entity_id=entity_id, alias_name=request.alias_name,
                    alias_type=request.alias_type, is_primary=request.is_primary,
                    created_by=request.created_by, notes=request.notes,
                )
                return AliasResponse(**alias)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/entities/{entity_id}/aliases", tags=["Entity Registry"])
        async def list_aliases_route(entity_id: str, current_user: Dict = Depends(auth)):
            aliases = await self.registry.list_aliases(entity_id)
            return [AliasResponse(**a) for a in aliases]

        @self.router.delete("/aliases/{alias_id}", tags=["Entity Registry"])
        async def remove_alias_route(alias_id: int, current_user: Dict = Depends(auth)):
            removed = await self.registry.remove_alias(alias_id)
            if not removed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alias not found: {alias_id}")
            return {"success": True, "alias_id": alias_id}

        # -- Same-As --

        @self.router.post("/same-as", response_model=SameAsResponse, tags=["Entity Registry"])
        async def create_same_as_route(request: SameAsCreateRequest, current_user: Dict = Depends(auth)):
            try:
                mapping = await self.registry.create_same_as(
                    source_entity_id=request.source_entity_id,
                    target_entity_id=request.target_entity_id,
                    relationship_type=request.relationship_type,
                    confidence=request.confidence, reason=request.reason,
                    created_by=request.created_by, notes=request.notes,
                )
                return SameAsResponse(**mapping)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/entities/{entity_id}/same-as", tags=["Entity Registry"])
        async def get_same_as_route(entity_id: str, current_user: Dict = Depends(auth)):
            mappings = await self.registry.get_same_as(entity_id)
            return [SameAsResponse(**m) for m in mappings]

        @self.router.put("/same-as/{same_as_id}/retract", response_model=SameAsResponse, tags=["Entity Registry"])
        async def retract_same_as_route(same_as_id: int, request: SameAsRetractRequest,
                                        current_user: Dict = Depends(auth)):
            retracted = await self.registry.retract_same_as(
                same_as_id=same_as_id, retracted_by=request.retracted_by, reason=request.reason,
            )
            if not retracted:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"Same-as mapping not found or already retracted: {same_as_id}")
            async with self.registry.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM entity_same_as WHERE same_as_id = $1", same_as_id)
                return SameAsResponse(**dict(row))

        @self.router.get("/entities/{entity_id}/resolve", response_model=EntityResponse, tags=["Entity Registry"])
        async def resolve_entity_route(entity_id: str, current_user: Dict = Depends(auth)):
            try:
                entity = await self.registry.resolve_entity(entity_id)
                return _entity_to_response(entity)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

        # -- Entity Types --

        @self.router.get("/entity-types", tags=["Entity Registry"])
        async def list_entity_types_route(current_user: Dict = Depends(auth)):
            types = await self.registry.list_entity_types()
            return [EntityTypeResponse(**t) for t in types]

        @self.router.post("/entity-types", response_model=EntityTypeResponse, tags=["Entity Registry"])
        async def create_entity_type_route(request: EntityTypeCreateRequest, current_user: Dict = Depends(auth)):
            try:
                et = await self.registry.create_entity_type(
                    type_key=request.type_key, type_label=request.type_label,
                    type_description=request.type_description,
                )
                return EntityTypeResponse(**et)
            except Exception as e:
                if 'duplicate key' in str(e).lower() or 'unique' in str(e).lower():
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail=f"Entity type already exists: {request.type_key}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

        # -- Change Log --

        @self.router.get("/entities/{entity_id}/changelog", response_model=ChangeLogResponse, tags=["Entity Registry"])
        async def get_entity_changelog_route(
            entity_id: str,
            change_type: Optional[str] = Query(None),
            limit: int = Query(50, ge=1, le=500),
            offset: int = Query(0, ge=0),
            current_user: Dict = Depends(auth),
        ):
            entries, total = await self.registry.get_change_log(
                entity_id=entity_id, change_type=change_type, limit=limit, offset=offset,
            )
            return ChangeLogResponse(
                success=True, entries=[ChangeLogEntry(**e) for e in entries], total_count=total,
            )

        @self.router.get("/changelog", response_model=ChangeLogResponse, tags=["Entity Registry"])
        async def get_recent_changelog_route(
            change_type: Optional[str] = Query(None),
            limit: int = Query(50, ge=1, le=500),
            current_user: Dict = Depends(auth),
        ):
            entries = await self.registry.get_recent_changes(limit=limit, change_type=change_type)
            return ChangeLogResponse(
                success=True, entries=[ChangeLogEntry(**e) for e in entries], total_count=len(entries),
            )


def create_entity_registry_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function to create the entity registry router."""
    endpoint = EntityRegistryEndpoint(app_impl, auth_dependency)
    return endpoint.router
