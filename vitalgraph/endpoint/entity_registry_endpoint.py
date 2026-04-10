"""
Entity Registry REST API Endpoint.

Provides CRUD operations for entities, aliases, identifiers,
same-as mappings, entity types, and change logs.
"""

import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..model.entity_registry_model import (
    AliasCreateRequest,
    AliasResponse,
    CategoryCreateRequest,
    CategoryResponse,
    ChangeLogEntry,
    ChangeLogResponse,
    EntityCategoryRequest,
    EntityCategoryResponse,
    EntityCreateRequest,
    EntityCreateResponse,
    EntityListResponse,
    EntityResponse,
    EntityTypeCreateRequest,
    EntityTypeResponse,
    EntityUpdateRequest,
    IdentifierCreateRequest,
    IdentifierResponse,
    LocationCategoryRequest,
    LocationCategoryResponse,
    LocationCreateRequest,
    LocationResponse,
    LocationTypeCreateRequest,
    LocationTypeResponse,
    LocationUpdateRequest,
    RelationshipCreateRequest,
    RelationshipResponse,
    RelationshipTypeCreateRequest,
    RelationshipTypeResponse,
    RelationshipUpdateRequest,
    SameAsCreateRequest,
    SameAsResponse,
    SameAsRetractRequest,
    SimilarEntityResponse,
    SimilarEntityResult,
    EntitySearchResponse,
    EntitySearchResult,
    EntitySearchLocationResult,
    LocationSearchResponse,
    LocationSearchResult,
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

    locations = None
    if entity.get('locations'):
        locations = [LocationResponse(**loc) for loc in entity['locations']]

    relationships = None
    if entity.get('relationships'):
        relationships = [RelationshipResponse(**rel) for rel in entity['relationships']]

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
        latitude=entity.get('latitude'),
        longitude=entity.get('longitude'),
        metadata=json.loads(entity['metadata']) if isinstance(entity.get('metadata'), str) else (entity.get('metadata') or {}),
        verified=entity.get('verified', False),
        verified_by=entity.get('verified_by'),
        verified_time=entity.get('verified_time'),
        status=entity['status'],
        created_time=entity.get('created_time'),
        updated_time=entity.get('updated_time'),
        created_by=entity.get('created_by'),
        notes=entity.get('notes'),
        identifiers=identifiers,
        aliases=aliases,
        locations=locations,
        relationships=relationships,
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
                locations = [l.model_dump() for l in request.locations] if request.locations else None
                entity = await self.registry.create_entity(
                    type_key=request.type_key, primary_name=request.primary_name,
                    description=request.description, country=request.country,
                    region=request.region, locality=request.locality,
                    website=request.website, latitude=request.latitude,
                    longitude=request.longitude, metadata=request.metadata,
                    created_by=request.created_by,
                    notes=request.notes, aliases=aliases, identifiers=identifiers,
                    locations=locations,
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

        @self.router.get("/entities/get", response_model=EntityResponse, tags=["Entity Registry"])
        async def get_entity_route(
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            entity = await self.registry.get_entity(entity_id)
            if entity is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found: {entity_id}")
            return _entity_to_response(entity)

        @self.router.put("/entities/update", response_model=EntityResponse, tags=["Entity Registry"])
        async def update_entity_route(
            request: EntityUpdateRequest,
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                entity = await self.registry.update_entity(
                    entity_id=entity_id, primary_name=request.primary_name,
                    description=request.description, country=request.country,
                    region=request.region, locality=request.locality,
                    website=request.website, latitude=request.latitude,
                    longitude=request.longitude, metadata=request.metadata,
                    verified=request.verified, verified_by=request.verified_by,
                    status=request.status,
                    updated_by=request.updated_by, notes=request.notes,
                )
                if entity is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found: {entity_id}")
                return _entity_to_response(entity)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.delete("/entities/delete", tags=["Entity Registry"])
        async def delete_entity_route(
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            deleted = await self.registry.delete_entity(entity_id)
            if not deleted:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity not found: {entity_id}")
            return {"success": True, "entity_id": entity_id}

        # -- Identifiers --

        @self.router.post("/identifiers/add", response_model=IdentifierResponse, tags=["Entity Registry"])
        async def add_identifier_route(
            request: IdentifierCreateRequest,
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                ident = await self.registry.add_identifier(
                    entity_id=entity_id, identifier_namespace=request.identifier_namespace,
                    identifier_value=request.identifier_value, is_primary=request.is_primary,
                    created_by=request.created_by, notes=request.notes,
                )
                return IdentifierResponse(**ident)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/identifiers/list", tags=["Entity Registry"])
        async def list_identifiers_route(
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            idents = await self.registry.list_identifiers(entity_id)
            return [IdentifierResponse(**i) for i in idents]

        @self.router.delete("/identifiers/remove", tags=["Entity Registry"])
        async def remove_identifier_route(
            identifier_id: int = Query(..., description="Identifier ID"),
            current_user: Dict = Depends(auth),
        ):
            removed = await self.registry.remove_identifier(identifier_id)
            if not removed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Identifier not found: {identifier_id}")
            return {"success": True, "identifier_id": identifier_id}

        @self.router.get("/identifiers/lookup", response_model=List[EntityResponse], tags=["Entity Registry"])
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

        @self.router.post("/aliases/add", response_model=AliasResponse, tags=["Entity Registry"])
        async def add_alias_route(
            request: AliasCreateRequest,
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                alias = await self.registry.add_alias(
                    entity_id=entity_id, alias_name=request.alias_name,
                    alias_type=request.alias_type, is_primary=request.is_primary,
                    created_by=request.created_by, notes=request.notes,
                )
                return AliasResponse(**alias)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/aliases/list", tags=["Entity Registry"])
        async def list_aliases_route(
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            aliases = await self.registry.list_aliases(entity_id)
            return [AliasResponse(**a) for a in aliases]

        @self.router.delete("/aliases/remove", tags=["Entity Registry"])
        async def remove_alias_route(
            alias_id: int = Query(..., description="Alias ID"),
            current_user: Dict = Depends(auth),
        ):
            removed = await self.registry.remove_alias(alias_id)
            if not removed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Alias not found: {alias_id}")
            return {"success": True, "alias_id": alias_id}

        # -- Categories --

        @self.router.get("/categories", response_model=List[CategoryResponse], tags=["Entity Registry"])
        async def list_categories_route(current_user: Dict = Depends(auth)):
            categories = await self.registry.list_categories()
            return [CategoryResponse(**c) for c in categories]

        @self.router.post("/categories", response_model=CategoryResponse, tags=["Entity Registry"])
        async def create_category_route(request: CategoryCreateRequest, current_user: Dict = Depends(auth)):
            try:
                category = await self.registry.create_category(
                    category_key=request.category_key,
                    category_label=request.category_label,
                    category_description=request.category_description,
                )
                return CategoryResponse(**category)
            except Exception as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/categories/entity", response_model=List[EntityCategoryResponse],
                         tags=["Entity Registry"])
        async def list_entity_categories_route(
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            cats = await self.registry.list_entity_categories(entity_id)
            return [EntityCategoryResponse(**c) for c in cats]

        @self.router.post("/categories/assign", response_model=EntityCategoryResponse,
                          tags=["Entity Registry"])
        async def add_entity_category_route(
            request: EntityCategoryRequest,
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                result = await self.registry.add_entity_category(
                    entity_id=entity_id, category_key=request.category_key,
                    created_by=request.created_by, notes=request.notes,
                )
                return EntityCategoryResponse(**result)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.delete("/categories/remove", tags=["Entity Registry"])
        async def remove_entity_category_route(
            entity_id: str = Query(..., description="Entity ID"),
            category_key: str = Query(..., description="Category key"),
            current_user: Dict = Depends(auth),
        ):
            try:
                removed = await self.registry.remove_entity_category(entity_id, category_key)
                if not removed:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                        detail=f"Category mapping not found: {entity_id}/{category_key}")
                return {"success": True, "entity_id": entity_id, "category_key": category_key}
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/categories/entities", response_model=List[EntityResponse],
                         tags=["Entity Registry"])
        async def list_entities_by_category_route(
            category_key: str = Query(..., description="Category key"),
            current_user: Dict = Depends(auth),
        ):
            entities = await self.registry.list_entities_by_category(category_key)
            return [_entity_to_response(e) for e in entities]

        # -- Location Types --

        @self.router.get("/location/types", tags=["Entity Registry"])
        async def list_location_types_route(current_user: Dict = Depends(auth)):
            types = await self.registry.list_location_types()
            return [LocationTypeResponse(**t) for t in types]

        @self.router.post("/location/types", response_model=LocationTypeResponse, tags=["Entity Registry"])
        async def create_location_type_route(request: LocationTypeCreateRequest, current_user: Dict = Depends(auth)):
            try:
                lt = await self.registry.create_location_type(
                    type_key=request.type_key, type_label=request.type_label,
                    type_description=request.type_description,
                )
                return LocationTypeResponse(**lt)
            except Exception as e:
                if 'duplicate key' in str(e).lower() or 'unique' in str(e).lower():
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail=f"Location type already exists: {request.type_key}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

        # -- Locations --

        @self.router.post("/locations/add", response_model=LocationResponse, tags=["Entity Registry"])
        async def create_location_route(
            request: LocationCreateRequest,
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                loc = await self.registry.create_location(
                    entity_id=entity_id, location_type_key=request.location_type_key,
                    created_by=None, **request.model_dump(exclude={'location_type_key'}),
                )
                return LocationResponse(**loc)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/locations/get", response_model=LocationResponse, tags=["Entity Registry"])
        async def get_location_route(
            location_id: int = Query(..., description="Location ID"),
            current_user: Dict = Depends(auth),
        ):
            loc = await self.registry.get_location(location_id)
            if loc is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"Location not found: {location_id}")
            return LocationResponse(**loc)

        @self.router.get("/locations/list", tags=["Entity Registry"])
        async def list_locations_route(
            entity_id: str = Query(..., description="Entity ID"),
            include_expired: bool = Query(False, description="Include expired locations"),
            current_user: Dict = Depends(auth),
        ):
            locs = await self.registry.list_locations(entity_id, include_expired=include_expired)
            return [LocationResponse(**loc) for loc in locs]

        @self.router.put("/locations/update", response_model=LocationResponse, tags=["Entity Registry"])
        async def update_location_route(
            request: LocationUpdateRequest,
            location_id: int = Query(..., description="Location ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                loc = await self.registry.update_location(
                    location_id=location_id, updated_by=request.updated_by,
                    **request.model_dump(exclude={'updated_by'}, exclude_none=True),
                )
                if loc is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                        detail=f"Location not found: {location_id}")
                return LocationResponse(**loc)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.delete("/locations/remove", tags=["Entity Registry"])
        async def remove_location_route(
            location_id: int = Query(..., description="Location ID"),
            current_user: Dict = Depends(auth),
        ):
            removed = await self.registry.remove_location(location_id)
            if not removed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"Location not found: {location_id}")
            return {"success": True, "location_id": location_id}

        # -- Location Categories --

        @self.router.post("/locations/categories/assign", response_model=LocationCategoryResponse,
                          tags=["Entity Registry"])
        async def add_location_category_route(
            request: LocationCategoryRequest,
            location_id: int = Query(..., description="Location ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                result = await self.registry.add_location_category(
                    location_id=location_id, category_key=request.category_key,
                    created_by=request.created_by, notes=request.notes,
                )
                return LocationCategoryResponse(**result)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.delete("/locations/categories/remove", tags=["Entity Registry"])
        async def remove_location_category_route(
            location_id: int = Query(..., description="Location ID"),
            category_key: str = Query(..., description="Category key"),
            current_user: Dict = Depends(auth),
        ):
            try:
                removed = await self.registry.remove_location_category(location_id, category_key)
                if not removed:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                        detail=f"Location category mapping not found: {location_id}/{category_key}")
                return {"success": True, "location_id": location_id, "category_key": category_key}
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/locations/categories/list", tags=["Entity Registry"])
        async def list_location_categories_route(
            location_id: int = Query(..., description="Location ID"),
            current_user: Dict = Depends(auth),
        ):
            cats = await self.registry.list_location_categories(location_id)
            return [LocationCategoryResponse(**c) for c in cats]

        # -- Relationship Types --

        @self.router.get("/relationship/types", tags=["Entity Registry"])
        async def list_relationship_types_route(current_user: Dict = Depends(auth)):
            types = await self.registry.list_relationship_types()
            return [RelationshipTypeResponse(**t) for t in types]

        @self.router.post("/relationship/types", response_model=RelationshipTypeResponse,
                          tags=["Entity Registry"])
        async def create_relationship_type_route(
            request: RelationshipTypeCreateRequest, current_user: Dict = Depends(auth),
        ):
            try:
                rt = await self.registry.create_relationship_type(
                    type_key=request.type_key, type_label=request.type_label,
                    type_description=request.type_description,
                    inverse_key=request.inverse_key,
                )
                return RelationshipTypeResponse(**rt)
            except Exception as e:
                if 'duplicate key' in str(e).lower() or 'unique' in str(e).lower():
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail=f"Relationship type already exists: {request.type_key}")
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

        # -- Relationships --

        @self.router.post("/relationships", response_model=RelationshipResponse, tags=["Entity Registry"])
        async def create_relationship_route(
            request: RelationshipCreateRequest, current_user: Dict = Depends(auth),
        ):
            try:
                rel = await self.registry.create_relationship(
                    entity_source=request.entity_source,
                    entity_destination=request.entity_destination,
                    relationship_type_key=request.relationship_type_key,
                    start_datetime=request.start_datetime,
                    end_datetime=request.end_datetime,
                    description=request.description,
                    created_by=request.created_by,
                    notes=request.notes,
                )
                return RelationshipResponse(**rel)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.get("/relationships/get", response_model=RelationshipResponse, tags=["Entity Registry"])
        async def get_relationship_route(
            relationship_id: int = Query(..., description="Relationship ID"),
            current_user: Dict = Depends(auth),
        ):
            rel = await self.registry.get_relationship(relationship_id)
            if rel is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"Relationship not found: {relationship_id}")
            return RelationshipResponse(**rel)

        @self.router.get("/relationships/list", tags=["Entity Registry"])
        async def list_relationships_route(
            entity_id: str = Query(..., description="Entity ID"),
            direction: str = Query('both', description="outgoing, incoming, or both"),
            include_expired: bool = Query(False, description="Include non-current relationships"),
            current_user: Dict = Depends(auth),
        ):
            rels = await self.registry.list_relationships(
                entity_id, direction=direction, include_expired=include_expired,
            )
            return [RelationshipResponse(**r) for r in rels]

        @self.router.put("/relationships/update", response_model=RelationshipResponse,
                         tags=["Entity Registry"])
        async def update_relationship_route(
            request: RelationshipUpdateRequest,
            relationship_id: int = Query(..., description="Relationship ID"),
            current_user: Dict = Depends(auth),
        ):
            try:
                rel = await self.registry.update_relationship(
                    relationship_id=relationship_id, updated_by=request.updated_by,
                    **request.model_dump(exclude={'updated_by'}, exclude_none=True),
                )
                if rel is None:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                        detail=f"Relationship not found: {relationship_id}")
                return RelationshipResponse(**rel)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

        @self.router.delete("/relationships/remove", tags=["Entity Registry"])
        async def remove_relationship_route(
            relationship_id: int = Query(..., description="Relationship ID"),
            current_user: Dict = Depends(auth),
        ):
            removed = await self.registry.remove_relationship(relationship_id)
            if not removed:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"Relationship not found or already retracted: {relationship_id}")
            return {"success": True, "relationship_id": relationship_id}

        # -- Same-As --

        @self.router.post("/sameas", response_model=SameAsResponse, tags=["Entity Registry"])
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

        @self.router.get("/sameas/list", tags=["Entity Registry"])
        async def get_same_as_route(
            entity_id: str = Query(..., description="Entity ID"),
            current_user: Dict = Depends(auth),
        ):
            mappings = await self.registry.get_same_as(entity_id)
            return [SameAsResponse(**m) for m in mappings]

        @self.router.put("/sameas/retract", response_model=SameAsResponse, tags=["Entity Registry"])
        async def retract_same_as_route(
            request: SameAsRetractRequest,
            same_as_id: int = Query(..., description="Same-as mapping ID"),
            current_user: Dict = Depends(auth),
        ):
            retracted = await self.registry.retract_same_as(
                same_as_id=same_as_id, retracted_by=request.retracted_by, reason=request.reason,
            )
            if not retracted:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail=f"Same-as mapping not found or already retracted: {same_as_id}")
            async with self.registry.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM entity_same_as WHERE same_as_id = $1", same_as_id)
                return SameAsResponse(**dict(row))

        @self.router.get("/sameas/resolve", response_model=EntityResponse, tags=["Entity Registry"])
        async def resolve_entity_route(
            entity_id: str = Query(..., description="Entity ID to resolve"),
            current_user: Dict = Depends(auth),
        ):
            try:
                entity = await self.registry.resolve_entity(entity_id)
                return _entity_to_response(entity)
            except ValueError as e:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

        # -- Entity Types --

        @self.router.get("/entity/types", tags=["Entity Registry"])
        async def list_entity_types_route(current_user: Dict = Depends(auth)):
            types = await self.registry.list_entity_types()
            return [EntityTypeResponse(**t) for t in types]

        @self.router.post("/entity/types", response_model=EntityTypeResponse, tags=["Entity Registry"])
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

        @self.router.get("/changelog/entity", response_model=ChangeLogResponse, tags=["Entity Registry"])
        async def get_entity_changelog_route(
            entity_id: str = Query(..., description="Entity ID"),
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

        # -- Admin: Index Rebuild --

        @self.router.post("/admin/rebuild", tags=["Entity Registry Admin"])
        async def admin_rebuild_route(
            rebuild_dedup: bool = Query(True, description="Rebuild the in-memory dedup index"),
            rebuild_weaviate: bool = Query(False, description="Full Weaviate entity + location sync"),
            notify_workers: bool = Query(True, description="Send pg NOTIFY so other workers also rebuild"),
            current_user: Dict = Depends(auth),
        ):
            """Rebuild secondary indexes (dedup, Weaviate) and notify all workers.

            Intended for use after bulk data loads or manual data corrections.
            The dedup rebuild reloads the entire MinHash LSH index from PostgreSQL.
            The Weaviate rebuild does a full entity + location sync (upsert, not drop/recreate).
            """
            import time as _time
            reg = self._get_registry()
            results = {}

            if rebuild_dedup and reg.dedup_index:
                start = _time.time()
                count = await reg.dedup_index.initialize(reg.pool)
                duration = _time.time() - start
                results['dedup'] = {
                    'entities_indexed': count,
                    'duration_seconds': round(duration, 1),
                }
                logger.info(f"Admin rebuild: dedup index rebuilt — {count} entities in {duration:.1f}s")

                if notify_workers:
                    await reg._notify_dedup_reload()
                    results['dedup']['workers_notified'] = True
            elif rebuild_dedup:
                results['dedup'] = {'status': 'not_enabled'}

            if rebuild_weaviate:
                weaviate_index = getattr(reg, 'weaviate_index', None)
                if weaviate_index:
                    start = _time.time()
                    await weaviate_index.ensure_collection()
                    ent_count, ent_deleted = await weaviate_index.full_sync(
                        reg.pool, batch_size=200)
                    loc_count, loc_deleted = await weaviate_index.location_sync(
                        reg.pool, batch_size=200)
                    duration = _time.time() - start
                    results['weaviate'] = {
                        'entities_upserted': ent_count,
                        'entities_deleted': ent_deleted,
                        'locations_upserted': loc_count,
                        'locations_deleted': loc_deleted,
                        'duration_seconds': round(duration, 1),
                    }
                    logger.info(
                        f"Admin rebuild: Weaviate sync — {ent_count} entities, "
                        f"{loc_count} locations in {duration:.1f}s"
                    )
                else:
                    results['weaviate'] = {'status': 'not_enabled'}

            return {'success': True, 'rebuild': results}

        # -- Similar / Dedup --

        @self.router.get("/search/similar", response_model=SimilarEntityResponse, tags=["Entity Registry"])
        async def find_similar_route(
            name: str = Query(..., description="Entity name to search for"),
            type_key: Optional[str] = Query(None, description="Filter by entity type"),
            country: Optional[str] = Query(None),
            region: Optional[str] = Query(None),
            locality: Optional[str] = Query(None),
            limit: int = Query(10, ge=1, le=100),
            min_score: float = Query(50.0, ge=0, le=100),
            current_user: Dict = Depends(auth),
        ):
            candidates = await self.registry.find_similar(
                name=name, country=country, region=region, locality=locality,
                type_key=type_key, limit=limit, min_score=min_score,
            )
            return SimilarEntityResponse(
                success=True,
                candidates=[SimilarEntityResult(**c) for c in candidates],
            )

        # -- Entity Search (unified semantic + geo) --

        @self.router.get("/search/entity", response_model=EntitySearchResponse, tags=["Entity Registry"])
        async def search_entity_route(
            q: Optional[str] = Query(None, description="Free-text query (vectorized). Omit for geo-only search."),
            identifier_value: Optional[str] = Query(None, description="Search by external identifier value"),
            identifier_namespace: Optional[str] = Query(None, description="Identifier namespace (requires identifier_value)"),
            type_key: Optional[str] = Query(None),
            category_key: Optional[str] = Query(None),
            country: Optional[str] = Query(None),
            region: Optional[str] = Query(None),
            locality: Optional[str] = Query(None),
            latitude: Optional[float] = Query(None, ge=-90, le=90, description="Center latitude for geo range"),
            longitude: Optional[float] = Query(None, ge=-180, le=180, description="Center longitude for geo range"),
            radius_km: Optional[float] = Query(None, gt=0, description="Radius in km for geo range filter"),
            limit: int = Query(20, ge=1, le=100),
            min_certainty: float = Query(0.7, ge=0, le=1),
            current_user: Dict = Depends(auth),
        ):
            weaviate_index = getattr(self.registry, 'weaviate_index', None)
            if not weaviate_index:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Weaviate entity indexing is not enabled",
                )

            has_geo = latitude is not None and longitude is not None and radius_km is not None
            has_query = q is not None and q.strip()
            has_identifier = identifier_value is not None and identifier_value.strip()

            if not has_query and not has_geo and not has_identifier:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Must provide 'q' (semantic), geo params (latitude/longitude/radius_km), "
                           "identifier_value, or a combination",
                )

            filters = {}
            if type_key:
                filters["type_key"] = type_key
            if category_key:
                filters["category_key"] = category_key
            if country:
                filters["country"] = country
            if region:
                filters["region"] = region
            if locality:
                filters["locality"] = locality
            if has_geo:
                filters["geo_range"] = {"latitude": latitude, "longitude": longitude, "radius_km": radius_km}
            if has_identifier:
                filters["identifier"] = {"value": identifier_value}
                if identifier_namespace:
                    filters["identifier"]["namespace"] = identifier_namespace

            # All search modes go through Weaviate — identifier filtering is native
            id_kw = {}
            if has_identifier:
                id_kw = {"identifier_value": identifier_value, "identifier_namespace": identifier_namespace}

            if has_query and has_geo:
                # Combined: semantic + LocationIndex geo via cross-reference
                raw = await weaviate_index.search_topic_near(
                    query=q, latitude=latitude, longitude=longitude, radius_km=radius_km,
                    type_key=type_key, category_key=category_key,
                    limit=limit, min_certainty=min_certainty, **id_kw,
                )
                results = [EntitySearchResult(
                    **{k: v for k, v in r.items() if k != 'locations'},
                    locations=[EntitySearchLocationResult(**loc) for loc in r.get('locations', [])],
                ) for r in raw]
            elif has_query:
                # Semantic only
                raw = await weaviate_index.search_topic(
                    query=q, type_key=type_key, category_key=category_key,
                    country=country, region=region, locality=locality,
                    limit=limit, min_certainty=min_certainty, **id_kw,
                )
                results = [EntitySearchResult(**r) for r in raw]
            elif has_geo:
                # Geo only via LocationIndex cross-reference
                raw = await weaviate_index.search_entities_near(
                    latitude=latitude, longitude=longitude, radius_km=radius_km,
                    type_key=type_key, limit=limit, **id_kw,
                )
                results = [EntitySearchResult(
                    **{k: v for k, v in r.items() if k != 'locations'},
                    locations=[EntitySearchLocationResult(**loc) for loc in r.get('locations', [])],
                ) for r in raw]
            else:
                # Identifier-only: Weaviate filter search (exact match, no vector)
                raw = await weaviate_index.search_by_identifier(
                    identifier_value=identifier_value,
                    identifier_namespace=identifier_namespace,
                    type_key=type_key, category_key=category_key,
                    country=country, region=region, locality=locality,
                    limit=limit,
                )
                results = [EntitySearchResult(**r) for r in raw]

            return EntitySearchResponse(
                success=True,
                query=q if has_query else None,
                filters=filters,
                results=results,
            )

        # -- Location Search (geo-radius on LocationIndex) --

        @self.router.get("/search/location", response_model=LocationSearchResponse, tags=["Entity Registry"])
        async def search_location_route(
            external_location_id: Optional[str] = Query(None, description="Business-assigned location reference"),
            latitude: Optional[float] = Query(None, ge=-90, le=90, description="Center latitude"),
            longitude: Optional[float] = Query(None, ge=-180, le=180, description="Center longitude"),
            radius_km: Optional[float] = Query(None, gt=0, description="Radius in km"),
            q: Optional[str] = Query(None, description="Semantic search on location name/description"),
            address: Optional[str] = Query(None, description="Keyword search on address lines (BM25)"),
            location_type_key: Optional[str] = Query(None, description="Filter by location type"),
            country_code: Optional[str] = Query(None, description="Filter by country code (e.g. US, GB)"),
            locality: Optional[str] = Query(None, description="Filter by city/locality"),
            admin_area_1: Optional[str] = Query(None, description="Filter by state/province"),
            postal_code: Optional[str] = Query(None, description="Filter by postal code"),
            location_name: Optional[str] = Query(None, description="Filter by exact location name"),
            entity_id: Optional[str] = Query(None, description="Filter to a specific entity"),
            is_primary: Optional[bool] = Query(None, description="Filter primary locations only"),
            include_expired: bool = Query(False, description="Include locations outside effective dates (PostgreSQL only)"),
            min_certainty: float = Query(0.5, ge=0.0, le=1.0, description="Min certainty for semantic search"),
            limit: int = Query(20, ge=1, le=100),
            current_user: Dict = Depends(auth),
        ):
            has_geo = latitude is not None and longitude is not None and radius_km is not None
            has_semantic = q is not None and q.strip()
            has_address = address is not None and address.strip()
            has_external_id = external_location_id is not None and external_location_id.strip()

            if not has_geo and not has_semantic and not has_address and not has_external_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Must provide at least one of: external_location_id, "
                           "geo params (latitude/longitude/radius_km), q (semantic), or address (BM25)",
                )

            # PostgreSQL path: external_location_id without geo/semantic/address
            if has_external_id and not has_geo and not has_semantic and not has_address:
                rows = await self.registry.search_locations_by_external_id(
                    external_location_id=external_location_id.strip(),
                    entity_id=entity_id,
                    include_expired=include_expired,
                )
                return LocationSearchResponse(
                    success=True,
                    results=[LocationSearchResult(**r) for r in rows],
                )

            # Weaviate path: geo, semantic, address, or combinations
            weaviate_index = getattr(self.registry, 'weaviate_index', None)
            if not weaviate_index:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Weaviate entity indexing is not enabled",
                )
            results = await weaviate_index.search_locations_near(
                latitude=latitude, longitude=longitude, radius_km=radius_km,
                q=q, address=address,
                location_type_key=location_type_key,
                country_code=country_code, locality=locality,
                admin_area_1=admin_area_1, postal_code=postal_code,
                location_name=location_name, entity_id=entity_id,
                is_primary=is_primary,
                external_location_id=external_location_id.strip() if has_external_id else None,
                min_certainty=min_certainty,
                limit=limit,
            )
            return LocationSearchResponse(
                success=True,
                results=[LocationSearchResult(**r) for r in results],
            )


def create_entity_registry_router(app_impl, auth_dependency) -> APIRouter:
    """Factory function to create the entity registry router."""
    endpoint = EntityRegistryEndpoint(app_impl, auth_dependency)
    return endpoint.router
