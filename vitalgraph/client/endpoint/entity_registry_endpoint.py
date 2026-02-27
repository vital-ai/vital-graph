"""
VitalGraph Client - Entity Registry Endpoint

Client-side endpoint for Entity Registry REST API operations.
"""

import logging
from typing import Any, Dict, List, Optional

from .base_endpoint import BaseEndpoint
from ...model.entity_registry_model import (
    AliasCreateRequest,
    AliasResponse,
    CategoryCreateRequest,
    CategoryResponse,
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
    EntitySearchResponse,
    LocationSearchResponse,
)


logger = logging.getLogger(__name__)


class EntityRegistryClientEndpoint(BaseEndpoint):
    """Client endpoint for Entity Registry operations."""

    def __init__(self, client):
        super().__init__(client)
        self._base_path = "/api/registry"

    def _url(self, path: str) -> str:
        return f"{self._get_server_url()}{self._base_path}{path}"

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    async def create_entity(self, request: EntityCreateRequest) -> EntityCreateResponse:
        """Create a new entity."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/entities"), EntityCreateResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def get_entity(self, entity_id: str) -> EntityResponse:
        """Get entity by ID."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/entities/get"), EntityResponse,
            params={"entity_id": entity_id},
        )

    async def search_entities(
        self,
        query: Optional[str] = None,
        type_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        status: Optional[str] = 'active',
        page: int = 1,
        page_size: int = 20,
    ) -> EntityListResponse:
        """Search/list entities with filters."""
        self._check_connection()
        params = {"page": page, "page_size": page_size}
        if query:
            params["query"] = query
        if type_key:
            params["type_key"] = type_key
        if country:
            params["country"] = country
        if region:
            params["region"] = region
        if status:
            params["status"] = status
        return await self._make_typed_request(
            "GET", self._url("/entities"), EntityListResponse, params=params,
        )

    async def update_entity(self, entity_id: str, request: EntityUpdateRequest) -> EntityResponse:
        """Update an entity."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/entities/update"), EntityResponse,
            params={"entity_id": entity_id},
            json=request.model_dump(exclude_none=True),
        )

    async def delete_entity(self, entity_id: str) -> Dict[str, Any]:
        """Soft-delete an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/entities/delete"),
            params={"entity_id": entity_id},
        )
        return response.json()

    # ------------------------------------------------------------------
    # Identifiers
    # ------------------------------------------------------------------

    async def add_identifier(self, entity_id: str, request: IdentifierCreateRequest) -> IdentifierResponse:
        """Add an external identifier to an entity."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/identifiers/add"), IdentifierResponse,
            params={"entity_id": entity_id},
            json=request.model_dump(exclude_none=True),
        )

    async def list_identifiers(self, entity_id: str) -> List[IdentifierResponse]:
        """List all active identifiers for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/identifiers/list"),
            params={"entity_id": entity_id},
        )
        data = response.json()
        return [IdentifierResponse.model_validate(i) for i in data]

    async def remove_identifier(self, identifier_id: int) -> Dict[str, Any]:
        """Retract an identifier."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/identifiers/remove"),
            params={"identifier_id": identifier_id},
        )
        return response.json()

    async def lookup_by_identifier(self, namespace: str, value: str) -> List[EntityResponse]:
        """Lookup entities by external identifier. Returns a list since identifiers are not unique."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/identifiers/lookup"),
            params={"namespace": namespace, "value": value},
        )
        return [EntityResponse.model_validate(e) for e in response.json()]

    # ------------------------------------------------------------------
    # Aliases
    # ------------------------------------------------------------------

    async def add_alias(self, entity_id: str, request: AliasCreateRequest) -> AliasResponse:
        """Add an alias to an entity."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/aliases/add"), AliasResponse,
            params={"entity_id": entity_id},
            json=request.model_dump(exclude_none=True),
        )

    async def list_aliases(self, entity_id: str) -> List[AliasResponse]:
        """List all active aliases for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/aliases/list"),
            params={"entity_id": entity_id},
        )
        data = response.json()
        return [AliasResponse.model_validate(a) for a in data]

    async def remove_alias(self, alias_id: int) -> Dict[str, Any]:
        """Retract an alias."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/aliases/remove"),
            params={"alias_id": alias_id},
        )
        return response.json()

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    async def list_categories(self) -> List[CategoryResponse]:
        """List all entity categories."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/categories"),
        )
        data = response.json()
        return [CategoryResponse.model_validate(c) for c in data]

    async def create_category(self, request: CategoryCreateRequest) -> CategoryResponse:
        """Create a new entity category."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/categories"), CategoryResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def list_entity_categories(self, entity_id: str) -> List[EntityCategoryResponse]:
        """List all active categories for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/categories/entity"),
            params={"entity_id": entity_id},
        )
        data = response.json()
        return [EntityCategoryResponse.model_validate(c) for c in data]

    async def add_entity_category(self, entity_id: str, request: EntityCategoryRequest) -> EntityCategoryResponse:
        """Assign a category to an entity."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/categories/assign"), EntityCategoryResponse,
            params={"entity_id": entity_id},
            json=request.model_dump(exclude_none=True),
        )

    async def remove_entity_category(self, entity_id: str, category_key: str) -> Dict[str, Any]:
        """Remove a category from an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/categories/remove"),
            params={"entity_id": entity_id, "category_key": category_key},
        )
        return response.json()

    async def list_entities_by_category(self, category_key: str) -> List[EntityResponse]:
        """List all entities in a given category."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/categories/entities"),
            params={"category_key": category_key},
        )
        data = response.json()
        return [EntityResponse.model_validate(e) for e in data]

    # ------------------------------------------------------------------
    # Location Types
    # ------------------------------------------------------------------

    async def list_location_types(self) -> List[LocationTypeResponse]:
        """List all location types."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/location/types"),
        )
        data = response.json()
        return [LocationTypeResponse.model_validate(t) for t in data]

    async def create_location_type(self, request: LocationTypeCreateRequest) -> LocationTypeResponse:
        """Create a new location type."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/location/types"), LocationTypeResponse,
            json=request.model_dump(exclude_none=True),
        )

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    async def create_location(self, entity_id: str, request: LocationCreateRequest) -> LocationResponse:
        """Add a location to an entity."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/locations/add"), LocationResponse,
            params={"entity_id": entity_id},
            json=request.model_dump(exclude_none=True),
        )

    async def get_location(self, location_id: int) -> LocationResponse:
        """Get a location by ID."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/locations/get"), LocationResponse,
            params={"location_id": location_id},
        )

    async def list_locations(self, entity_id: str, include_expired: bool = False) -> List[LocationResponse]:
        """List locations for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/locations/list"),
            params={"entity_id": entity_id, "include_expired": include_expired},
        )
        data = response.json()
        return [LocationResponse.model_validate(loc) for loc in data]

    async def update_location(self, location_id: int, request: LocationUpdateRequest) -> LocationResponse:
        """Update a location."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/locations/update"), LocationResponse,
            params={"location_id": location_id},
            json=request.model_dump(exclude_none=True),
        )

    async def remove_location(self, location_id: int) -> Dict[str, Any]:
        """Remove a location."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/locations/remove"),
            params={"location_id": location_id},
        )
        return response.json()

    # ------------------------------------------------------------------
    # Location Categories
    # ------------------------------------------------------------------

    async def add_location_category(self, location_id: int, request: LocationCategoryRequest) -> LocationCategoryResponse:
        """Assign a category to a location."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/locations/categories/assign"), LocationCategoryResponse,
            params={"location_id": location_id},
            json=request.model_dump(exclude_none=True),
        )

    async def remove_location_category(self, location_id: int, category_key: str) -> Dict[str, Any]:
        """Remove a category from a location."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/locations/categories/remove"),
            params={"location_id": location_id, "category_key": category_key},
        )
        return response.json()

    async def list_location_categories(self, location_id: int) -> List[LocationCategoryResponse]:
        """List categories for a location."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/locations/categories/list"),
            params={"location_id": location_id},
        )
        data = response.json()
        return [LocationCategoryResponse.model_validate(c) for c in data]

    # ------------------------------------------------------------------
    # Relationship Types
    # ------------------------------------------------------------------

    async def list_relationship_types(self) -> List[RelationshipTypeResponse]:
        """List all relationship types."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/relationship/types"),
        )
        data = response.json()
        return [RelationshipTypeResponse.model_validate(t) for t in data]

    async def create_relationship_type(self, request: RelationshipTypeCreateRequest) -> RelationshipTypeResponse:
        """Create a new relationship type."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/relationship/types"), RelationshipTypeResponse,
            json=request.model_dump(exclude_none=True),
        )

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    async def create_relationship(self, request: RelationshipCreateRequest) -> RelationshipResponse:
        """Create a relationship between two entities."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/relationships"), RelationshipResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def get_relationship(self, relationship_id: int) -> RelationshipResponse:
        """Get a relationship by ID."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/relationships/get"), RelationshipResponse,
            params={"relationship_id": relationship_id},
        )

    async def list_relationships(
        self, entity_id: str, direction: str = 'both', include_expired: bool = False,
    ) -> List[RelationshipResponse]:
        """List relationships for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/relationships/list"),
            params={"entity_id": entity_id, "direction": direction, "include_expired": include_expired},
        )
        data = response.json()
        return [RelationshipResponse.model_validate(r) for r in data]

    async def update_relationship(self, relationship_id: int, request: RelationshipUpdateRequest) -> RelationshipResponse:
        """Update a relationship."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/relationships/update"), RelationshipResponse,
            params={"relationship_id": relationship_id},
            json=request.model_dump(exclude_none=True),
        )

    async def remove_relationship(self, relationship_id: int) -> Dict[str, Any]:
        """Remove (retract) a relationship."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url("/relationships/remove"),
            params={"relationship_id": relationship_id},
        )
        return response.json()

    # ------------------------------------------------------------------
    # Same-As
    # ------------------------------------------------------------------

    async def create_same_as(self, request: SameAsCreateRequest) -> SameAsResponse:
        """Create a same-as mapping between two entities."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/sameas"), SameAsResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def get_same_as(self, entity_id: str) -> List[SameAsResponse]:
        """Get all active same-as mappings for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/sameas/list"),
            params={"entity_id": entity_id},
        )
        data = response.json()
        return [SameAsResponse.model_validate(m) for m in data]

    async def retract_same_as(self, same_as_id: int, request: SameAsRetractRequest) -> SameAsResponse:
        """Retract a same-as mapping."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url("/sameas/retract"), SameAsResponse,
            params={"same_as_id": same_as_id},
            json=request.model_dump(exclude_none=True),
        )

    async def resolve_entity(self, entity_id: str) -> EntityResponse:
        """Resolve entity to canonical ID via transitive same-as chain."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url("/sameas/resolve"), EntityResponse,
            params={"entity_id": entity_id},
        )

    # ------------------------------------------------------------------
    # Entity Types
    # ------------------------------------------------------------------

    async def list_entity_types(self) -> List[EntityTypeResponse]:
        """List all entity types."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/entity/types"),
        )
        data = response.json()
        return [EntityTypeResponse.model_validate(t) for t in data]

    async def create_entity_type(self, request: EntityTypeCreateRequest) -> EntityTypeResponse:
        """Create a new entity type."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/entity/types"), EntityTypeResponse,
            json=request.model_dump(exclude_none=True),
        )

    # ------------------------------------------------------------------
    # Change Log
    # ------------------------------------------------------------------

    async def get_entity_changelog(
        self, entity_id: str,
        change_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ChangeLogResponse:
        """Get change log for a specific entity."""
        self._check_connection()
        params: Dict[str, Any] = {"entity_id": entity_id, "limit": limit, "offset": offset}
        if change_type:
            params["change_type"] = change_type
        return await self._make_typed_request(
            "GET", self._url("/changelog/entity"), ChangeLogResponse,
            params=params,
        )

    async def get_recent_changelog(
        self, limit: int = 50, change_type: Optional[str] = None,
    ) -> ChangeLogResponse:
        """Get recent changes across all entities."""
        self._check_connection()
        params: Dict[str, Any] = {"limit": limit}
        if change_type:
            params["change_type"] = change_type
        return await self._make_typed_request(
            "GET", self._url("/changelog"), ChangeLogResponse,
            params=params,
        )

    # ------------------------------------------------------------------
    # Similar / Dedup
    # ------------------------------------------------------------------

    async def find_similar(
        self, name: str,
        type_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        limit: int = 10,
        min_score: float = 50.0,
    ) -> SimilarEntityResponse:
        """Find entities similar to the given name."""
        self._check_connection()
        params: Dict[str, Any] = {"name": name, "limit": limit, "min_score": min_score}
        if type_key:
            params["type_key"] = type_key
        if country:
            params["country"] = country
        if region:
            params["region"] = region
        if locality:
            params["locality"] = locality
        return await self._make_typed_request(
            "GET", self._url("/search/similar"), SimilarEntityResponse,
            params=params,
        )

    # ------------------------------------------------------------------
    # Entity Search (unified semantic + geo)
    # ------------------------------------------------------------------

    async def search_entity(
        self,
        q: Optional[str] = None,
        identifier_value: Optional[str] = None,
        identifier_namespace: Optional[str] = None,
        type_key: Optional[str] = None,
        category_key: Optional[str] = None,
        country: Optional[str] = None,
        region: Optional[str] = None,
        locality: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
        limit: int = 20,
        min_certainty: float = 0.7,
    ) -> EntitySearchResponse:
        """Unified entity search: semantic (q), geo (lat/lon/radius), identifier, or combinations.

        - q only: semantic vector search on entities
        - geo only: entities with a location within the radius
        - identifier_value: find entities by external identifier
        - combinations: results are intersected
        """
        self._check_connection()
        params: Dict[str, Any] = {"limit": limit, "min_certainty": min_certainty}
        if q:
            params["q"] = q
        if identifier_value:
            params["identifier_value"] = identifier_value
        if identifier_namespace:
            params["identifier_namespace"] = identifier_namespace
        if type_key:
            params["type_key"] = type_key
        if category_key:
            params["category_key"] = category_key
        if country:
            params["country"] = country
        if region:
            params["region"] = region
        if locality:
            params["locality"] = locality
        if latitude is not None:
            params["latitude"] = latitude
        if longitude is not None:
            params["longitude"] = longitude
        if radius_km is not None:
            params["radius_km"] = radius_km
        return await self._make_typed_request(
            "GET", self._url("/search/entity"), EntitySearchResponse,
            params=params,
        )

    # ------------------------------------------------------------------
    # Location Search (geo-radius on LocationIndex)
    # ------------------------------------------------------------------

    async def search_location(
        self,
        external_location_id: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_km: Optional[float] = None,
        q: Optional[str] = None,
        address: Optional[str] = None,
        location_type_key: Optional[str] = None,
        country_code: Optional[str] = None,
        locality: Optional[str] = None,
        admin_area_1: Optional[str] = None,
        postal_code: Optional[str] = None,
        location_name: Optional[str] = None,
        entity_id: Optional[str] = None,
        is_primary: Optional[bool] = None,
        include_expired: bool = False,
        min_certainty: float = 0.5,
        limit: int = 20,
    ) -> LocationSearchResponse:
        """Search locations by external ID, geo-radius, semantic query, or combinations.

        Args:
            external_location_id: Business-assigned location reference (PostgreSQL exact match
                when used alone; Weaviate filter when combined with geo/semantic/address).
            latitude: Center latitude for geo search.
            longitude: Center longitude for geo search.
            radius_km: Radius in km for geo search.
            q: Semantic search on location name/description (near_text).
            address: Keyword search on address_line_1/address_line_2 (BM25).
            include_expired: Include locations outside effective dates (PostgreSQL path only).
        """
        self._check_connection()
        params: Dict[str, Any] = {"limit": limit, "min_certainty": min_certainty}
        if external_location_id:
            params["external_location_id"] = external_location_id
        if latitude is not None:
            params["latitude"] = latitude
        if longitude is not None:
            params["longitude"] = longitude
        if radius_km is not None:
            params["radius_km"] = radius_km
        if q:
            params["q"] = q
        if address:
            params["address"] = address
        if location_type_key:
            params["location_type_key"] = location_type_key
        if country_code:
            params["country_code"] = country_code
        if locality:
            params["locality"] = locality
        if admin_area_1:
            params["admin_area_1"] = admin_area_1
        if postal_code:
            params["postal_code"] = postal_code
        if location_name:
            params["location_name"] = location_name
        if entity_id:
            params["entity_id"] = entity_id
        if is_primary is not None:
            params["is_primary"] = is_primary
        if include_expired:
            params["include_expired"] = include_expired
        return await self._make_typed_request(
            "GET", self._url("/search/location"), LocationSearchResponse,
            params=params,
        )
