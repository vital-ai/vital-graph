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


logger = logging.getLogger(__name__)


class EntityRegistryClientEndpoint(BaseEndpoint):
    """Client endpoint for Entity Registry operations."""

    def __init__(self, client):
        super().__init__(client)
        self._base_path = "/api/entity-registry"

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
            "GET", self._url(f"/entities/{entity_id}"), EntityResponse,
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
            "PUT", self._url(f"/entities/{entity_id}"), EntityResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def delete_entity(self, entity_id: str) -> Dict[str, Any]:
        """Soft-delete an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url(f"/entities/{entity_id}"),
        )
        return response.json()

    # ------------------------------------------------------------------
    # Identifiers
    # ------------------------------------------------------------------

    async def add_identifier(self, entity_id: str, request: IdentifierCreateRequest) -> IdentifierResponse:
        """Add an external identifier to an entity."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url(f"/entities/{entity_id}/identifiers"), IdentifierResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def list_identifiers(self, entity_id: str) -> List[IdentifierResponse]:
        """List all active identifiers for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url(f"/entities/{entity_id}/identifiers"),
        )
        data = response.json()
        return [IdentifierResponse.model_validate(i) for i in data]

    async def remove_identifier(self, identifier_id: int) -> Dict[str, Any]:
        """Retract an identifier."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url(f"/identifiers/{identifier_id}"),
        )
        return response.json()

    async def lookup_by_identifier(self, namespace: str, value: str) -> List[EntityResponse]:
        """Lookup entities by external identifier. Returns a list since identifiers are not unique."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/lookup"),
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
            "POST", self._url(f"/entities/{entity_id}/aliases"), AliasResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def list_aliases(self, entity_id: str) -> List[AliasResponse]:
        """List all active aliases for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url(f"/entities/{entity_id}/aliases"),
        )
        data = response.json()
        return [AliasResponse.model_validate(a) for a in data]

    async def remove_alias(self, alias_id: int) -> Dict[str, Any]:
        """Retract an alias."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "DELETE", self._url(f"/aliases/{alias_id}"),
        )
        return response.json()

    # ------------------------------------------------------------------
    # Same-As
    # ------------------------------------------------------------------

    async def create_same_as(self, request: SameAsCreateRequest) -> SameAsResponse:
        """Create a same-as mapping between two entities."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/same-as"), SameAsResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def get_same_as(self, entity_id: str) -> List[SameAsResponse]:
        """Get all active same-as mappings for an entity."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url(f"/entities/{entity_id}/same-as"),
        )
        data = response.json()
        return [SameAsResponse.model_validate(m) for m in data]

    async def retract_same_as(self, same_as_id: int, request: SameAsRetractRequest) -> SameAsResponse:
        """Retract a same-as mapping."""
        self._check_connection()
        return await self._make_typed_request(
            "PUT", self._url(f"/same-as/{same_as_id}/retract"), SameAsResponse,
            json=request.model_dump(exclude_none=True),
        )

    async def resolve_entity(self, entity_id: str) -> EntityResponse:
        """Resolve entity to canonical ID via transitive same-as chain."""
        self._check_connection()
        return await self._make_typed_request(
            "GET", self._url(f"/entities/{entity_id}/resolve"), EntityResponse,
        )

    # ------------------------------------------------------------------
    # Entity Types
    # ------------------------------------------------------------------

    async def list_entity_types(self) -> List[EntityTypeResponse]:
        """List all entity types."""
        self._check_connection()
        response = await self._make_authenticated_request(
            "GET", self._url("/entity-types"),
        )
        data = response.json()
        return [EntityTypeResponse.model_validate(t) for t in data]

    async def create_entity_type(self, request: EntityTypeCreateRequest) -> EntityTypeResponse:
        """Create a new entity type."""
        self._check_connection()
        return await self._make_typed_request(
            "POST", self._url("/entity-types"), EntityTypeResponse,
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
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if change_type:
            params["change_type"] = change_type
        return await self._make_typed_request(
            "GET", self._url(f"/entities/{entity_id}/changelog"), ChangeLogResponse,
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
