"""
Pydantic request/response models for the Entity Registry REST API.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .result_status import ResultStatus, OperationStatus


# ------------------------------------------------------------------
# Request Models
# ------------------------------------------------------------------

class IdentifierCreateRequest(BaseModel):
    identifier_namespace: str = Field(..., description="Namespace/system, e.g. 'DUNS', 'EIN', 'CRM'")
    identifier_value: str = Field(..., description="External ID value")
    is_primary: bool = Field(default=False, description="Whether this is the preferred ID in this namespace")
    created_by: Optional[str] = None
    notes: Optional[str] = None


class AliasCreateRequest(BaseModel):
    alias_name: str
    alias_type: str = Field(default='aka', description="aka, dba, former, abbreviation, trade_name")
    is_primary: bool = False
    created_by: Optional[str] = None
    notes: Optional[str] = None


class LocationCreateRequest(BaseModel):
    location_type_key: str = Field(..., description="Location type key, e.g. 'headquarters', 'branch'")
    location_name: Optional[str] = None
    description: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    locality: Optional[str] = None
    admin_area_2: Optional[str] = None
    admin_area_1: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = Field(default=None, max_length=2)
    postal_code: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    timezone: Optional[str] = None
    google_place_id: Optional[str] = None
    external_location_id: Optional[str] = Field(default=None, max_length=50)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_primary: bool = False
    notes: Optional[str] = None


class LocationUpdateRequest(BaseModel):
    location_name: Optional[str] = None
    description: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    locality: Optional[str] = None
    admin_area_2: Optional[str] = None
    admin_area_1: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = Field(default=None, max_length=2)
    postal_code: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    timezone: Optional[str] = None
    google_place_id: Optional[str] = None
    external_location_id: Optional[str] = Field(default=None, max_length=50)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_primary: Optional[bool] = None
    notes: Optional[str] = None
    updated_by: Optional[str] = None


class EntityCreateRequest(BaseModel):
    type_key: str = Field(..., description="Entity type key, e.g. 'business', 'person'")
    primary_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    metadata: Optional[Dict[str, Any]] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None
    aliases: Optional[List[AliasCreateRequest]] = None
    identifiers: Optional[List[IdentifierCreateRequest]] = None
    locations: Optional[List[LocationCreateRequest]] = None


class EntityUpdateRequest(BaseModel):
    primary_name: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    metadata: Optional[Dict[str, Any]] = None
    verified: Optional[bool] = None
    verified_by: Optional[str] = None
    status: Optional[str] = None
    updated_by: Optional[str] = None
    notes: Optional[str] = None


class SameAsCreateRequest(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relationship_type: str = Field('same_as', description="same_as, merged_into, acquired_by, superseded_by")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    reason: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None


class SameAsRetractRequest(BaseModel):
    retracted_by: Optional[str] = None
    reason: Optional[str] = None


class EntityTypeCreateRequest(BaseModel):
    type_key: str
    type_label: str
    type_description: Optional[str] = None


class CategoryCreateRequest(BaseModel):
    category_key: str
    category_label: str
    category_description: Optional[str] = None


class EntityCategoryRequest(BaseModel):
    category_key: str
    created_by: Optional[str] = None
    notes: Optional[str] = None


class LocationCategoryRequest(BaseModel):
    category_key: str
    created_by: Optional[str] = None
    notes: Optional[str] = None


class RelationshipTypeCreateRequest(BaseModel):
    type_key: str
    type_label: str
    type_description: Optional[str] = None
    inverse_key: Optional[str] = None


class RelationshipCreateRequest(BaseModel):
    entity_source: str
    entity_destination: str
    relationship_type_key: str
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    description: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None


class RelationshipUpdateRequest(BaseModel):
    status: Optional[str] = None
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    updated_by: Optional[str] = None


class LocationTypeCreateRequest(BaseModel):
    type_key: str
    type_label: str
    type_description: Optional[str] = None


# ------------------------------------------------------------------
# Response Models
# ------------------------------------------------------------------

class IdentifierResponse(BaseModel):
    identifier_id: int
    entity_id: str
    identifier_namespace: str
    identifier_value: str
    is_primary: bool
    status: str
    created_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class AliasResponse(BaseModel):
    alias_id: int
    entity_id: str
    alias_name: str
    alias_type: str
    is_primary: bool
    status: str
    created_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class LocationResponse(BaseModel):
    location_id: int
    entity_id: str
    location_type_key: str
    location_type_label: Optional[str] = None
    location_name: Optional[str] = None
    description: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    locality: Optional[str] = None
    admin_area_2: Optional[str] = None
    admin_area_1: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    postal_code: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    google_place_id: Optional[str] = None
    external_location_id: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    is_active: bool = True
    is_primary: bool = False
    status: str = 'active'
    categories: List[Dict[str, Any]] = Field(default_factory=list)
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class RelationshipResponse(BaseModel):
    relationship_id: int
    entity_source: str
    entity_destination: str
    relationship_type_key: str
    relationship_type_label: Optional[str] = None
    inverse_key: Optional[str] = None
    status: str
    is_current: bool = True
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


# Reference-data models below are DUAL-PURPOSE: the same shape is both a list
# element and the body of the sibling single-object POST route. Only the latter
# should carry the ResultStatus contract — a list element shipping its own
# success/status/message triple is redundant on every row. So each is split into
# a plain `XItem` (list element) and `XResponse(ResultStatus, XItem)` (single
# object). XResponse keeps its exact previous wire shape, so the POST routes are
# unaffected.

class RelationshipTypeItem(BaseModel):
    relationship_type_id: Optional[int] = None
    type_key: Optional[str] = None
    type_label: Optional[str] = None
    type_description: Optional[str] = None
    inverse_key: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class RelationshipTypeResponse(ResultStatus, RelationshipTypeItem):
    status: OperationStatus = OperationStatus.FOUND


class LocationTypeItem(BaseModel):
    location_type_id: Optional[int] = None
    type_key: Optional[str] = None
    type_label: Optional[str] = None
    type_description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class LocationTypeResponse(ResultStatus, LocationTypeItem):
    status: OperationStatus = OperationStatus.FOUND


class LocationCategoryResponse(BaseModel):
    location_category_map_id: int
    location_id: int
    category_key: str
    category_label: Optional[str] = None
    category_description: Optional[str] = None
    status: str
    created_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class EntityResponse(BaseModel):
    entity_id: str
    entity_uri: str
    type_key: Optional[str] = None
    type_label: Optional[str] = None
    primary_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    website: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    verified: Optional[bool] = False
    verified_by: Optional[str] = None
    verified_time: Optional[datetime] = None
    status: str
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None
    identifiers: Optional[List[IdentifierResponse]] = None
    aliases: Optional[List[AliasResponse]] = None
    locations: Optional[List[LocationResponse]] = None
    relationships: Optional[List[RelationshipResponse]] = None

    class Config:
        from_attributes = True


class EntityCreateResponse(ResultStatus):
    status: OperationStatus = OperationStatus.CREATED
    entity_id: Optional[str] = None
    entity_uri: Optional[str] = None
    entity: Optional[EntityResponse] = None


class EntityListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    entities: List[EntityResponse]
    total_count: int
    page: int
    page_size: int


class SameAsResponse(BaseModel):
    same_as_id: int
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    status: str
    confidence: Optional[float] = None
    reason: Optional[str] = None
    created_time: Optional[datetime] = None
    retracted_time: Optional[datetime] = None
    created_by: Optional[str] = None
    retracted_by: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class EntityTypeItem(BaseModel):
    type_id: Optional[int] = None
    type_key: Optional[str] = None
    type_label: Optional[str] = None
    type_description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class EntityTypeResponse(ResultStatus, EntityTypeItem):
    status: OperationStatus = OperationStatus.FOUND


class CategoryItem(BaseModel):
    category_id: Optional[int] = None
    category_key: Optional[str] = None
    category_label: Optional[str] = None
    category_description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class CategoryResponse(ResultStatus, CategoryItem):
    status: OperationStatus = OperationStatus.FOUND


class EntityCategoryResponse(BaseModel):
    entity_category_id: int
    entity_id: str
    category_key: str
    category_label: Optional[str] = None
    category_description: Optional[str] = None
    status: str
    created_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ChangeLogEntry(BaseModel):
    log_id: int
    entity_id: Optional[str] = None
    change_type: str
    change_detail: Optional[Dict[str, Any]] = None
    changed_by: Optional[str] = None
    comment: Optional[str] = None
    created_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChangeLogResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    entries: List[ChangeLogEntry]
    total_count: int


# ------------------------------------------------------------------
# Similar Entity / Fuzzy Models
# ------------------------------------------------------------------

class SimilarEntityResult(BaseModel):
    entity_id: str
    primary_name: str
    type_key: Optional[str] = None
    score: float = Field(..., description="Composite similarity score 0-100")
    match_level: str = Field(..., description="high (>=90), likely (>=70), possible (>=50)")
    score_detail: Dict[str, float] = Field(default_factory=dict)


class SimilarEntityResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    candidates: List[SimilarEntityResult]


# ------------------------------------------------------------------
# Entity Search (unified semantic + geo)
# ------------------------------------------------------------------

class EntitySearchLocationResult(BaseModel):
    location_id: int
    location_name: Optional[str] = None
    location_type_key: Optional[str] = None
    formatted_address: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    locality: Optional[str] = None
    admin_area_1: Optional[str] = None
    country_code: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_primary: bool = False


class EntitySearchResult(BaseModel):
    entity_id: str
    primary_name: str
    description: Optional[str] = None
    type_key: Optional[str] = None
    type_label: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    category_keys: List[str] = Field(default_factory=list)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    score: float = Field(0.0, description="Weaviate certainty (0-1), 0 when no semantic search")
    distance: float = Field(0.0, description="Weaviate distance, 0 when no semantic search")
    locations: List[EntitySearchLocationResult] = Field(default_factory=list)


class EntitySearchResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    query: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    results: List[EntitySearchResult]


# ------------------------------------------------------------------
# Location Search (geo-radius on LocationIndex)
# ------------------------------------------------------------------

class LocationSearchResult(BaseModel):
    location_id: int
    entity_id: str
    location_name: Optional[str] = None
    location_type_key: Optional[str] = None
    formatted_address: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    locality: Optional[str] = None
    admin_area_1: Optional[str] = None
    country_code: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    external_location_id: Optional[str] = None
    is_primary: bool = False


class LocationSearchResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    results: List[LocationSearchResult]


# --- Unified metadata management (all six vocabularies) ---

class MetadataItemResponse(ResultStatus):
    """One metadata value in the normalized key/label/description shape shared by
    every kind. `inverse_key` is only populated for relationship-types;
    `usage_count` only when requested."""
    status: OperationStatus = OperationStatus.FOUND
    key: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    inverse_key: Optional[str] = None
    is_active: bool = True
    created_time: Optional[datetime] = None
    usage_count: Optional[int] = None


class MetadataCreateRequest(BaseModel):
    key: str = Field(..., description="Machine key (immutable, e.g. 'SSN')")
    label: str = Field(..., description="Human label")
    description: Optional[str] = None
    inverse_key: Optional[str] = Field(default=None, description="relationship-types only")


class MetadataUpdateRequest(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    inverse_key: Optional[str] = None


# ------------------------------------------------------------------
# Shared enveloped outcome responses
# ------------------------------------------------------------------
# Routes whose primary/success body is a bare data model that carries a domain
# `status: str` field (EntityResponse, LocationResponse, RelationshipResponse,
# SameAsResponse, IdentifierResponse, AliasResponse, EntityCategoryResponse,
# LocationCategoryResponse) cannot themselves carry the OperationStatus contract.
# Rather than a fragile response_model=Union[<DataModel>, RegistryErrorResponse]
# (where a success body can silently serialize as the error envelope and drop
# fields), each such route uses a single concrete NESTED ENVELOPE below: the
# ResultStatus contract lives on the envelope, and the data model is nested in a
# named Optional field (None on not-found / invalid-request). HTTP stays 200.

class EntityEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    entity: Optional[EntityResponse] = None


class IdentifierEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    identifier: Optional[IdentifierResponse] = None


class AliasEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    alias: Optional[AliasResponse] = None


class LocationEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    location: Optional[LocationResponse] = None


class RelationshipEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    relationship: Optional[RelationshipResponse] = None


class EntityCategoryEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    entity_category: Optional[EntityCategoryResponse] = None


class LocationCategoryEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    location_category: Optional[LocationCategoryResponse] = None


class SameAsEnvelope(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    same_as: Optional[SameAsResponse] = None


class EntityLookupResponse(ResultStatus):
    """Enveloped list outcome for GET /identifiers/lookup."""
    status: OperationStatus = OperationStatus.FOUND
    entities: List[EntityResponse] = []


class MetadataListResponse(ResultStatus):
    """Enveloped list outcome for GET /metadata/{kind}."""
    status: OperationStatus = OperationStatus.FOUND
    items: List[MetadataItemResponse] = []


class RegistryErrorResponse(ResultStatus):
    """Deprecated. Retained for backward-compat imports only; no route references it
    now that every domain outcome is carried by a single concrete envelope model."""
    status: OperationStatus = OperationStatus.NOT_FOUND


class RegistryWriteResponse(ResultStatus):
    """Enveloped outcome for delete/retract routes (and other simple mutations) that
    previously returned an ad-hoc ``{"success": True, "<id>": ...}`` dict. Echoes the
    affected resource identifier(s); only the relevant field(s) are populated."""
    status: OperationStatus = OperationStatus.DELETED
    entity_id: Optional[str] = None
    identifier_id: Optional[int] = None
    alias_id: Optional[int] = None
    location_id: Optional[int] = None
    relationship_id: Optional[int] = None
    same_as_id: Optional[int] = None
    category_key: Optional[str] = None
    kind: Optional[str] = None
    key: Optional[str] = None


# ------------------------------------------------------------------
# List envelopes
# ------------------------------------------------------------------
# These routes previously returned a BARE JSON ARRAY, so they carried no
# status/message and could not distinguish "matched nothing" (EMPTY) from
# "parent not found" (NOT_FOUND) — both serialized as []. Each now returns a
# ResultStatus envelope with a domain-named plural field plus total_count,
# matching the existing EntityListResponse / ChangeLogResponse convention.
#
# total_count is present on every envelope even where the list is unpaginated
# (reference data, where it always equals the item count). It is the
# forward-compatible hook: adding page/page_size to any one of these later is an
# additive, non-breaking change because the envelope already exists.

class IdentifierListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    identifiers: List[IdentifierResponse] = Field(default_factory=list)
    total_count: int = 0


class AliasListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    aliases: List[AliasResponse] = Field(default_factory=list)
    total_count: int = 0


class LocationListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    locations: List[LocationResponse] = Field(default_factory=list)
    total_count: int = 0


class LocationTypeListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    location_types: List[LocationTypeItem] = Field(default_factory=list)
    total_count: int = 0


class LocationCategoryListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    location_categories: List[LocationCategoryResponse] = Field(default_factory=list)
    total_count: int = 0


class RelationshipTypeListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    relationship_types: List[RelationshipTypeItem] = Field(default_factory=list)
    total_count: int = 0


class RelationshipListResponse(ResultStatus):
    """Paginated — a hub entity's adjacency list is unbounded (see page/page_size)."""

    status: OperationStatus = OperationStatus.FOUND
    relationships: List[RelationshipResponse] = Field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 20


class SameAsListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    same_as: List[SameAsResponse] = Field(default_factory=list)
    total_count: int = 0


class EntityTypeListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    entity_types: List[EntityTypeItem] = Field(default_factory=list)
    total_count: int = 0


class CategoryListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    categories: List[CategoryItem] = Field(default_factory=list)
    total_count: int = 0


class EntityCategoryListResponse(ResultStatus):
    status: OperationStatus = OperationStatus.FOUND
    entity_categories: List[EntityCategoryResponse] = Field(default_factory=list)
    total_count: int = 0


# ------------------------------------------------------------------
# Admin index rebuild
# ------------------------------------------------------------------
# Shared by POST /admin/rebuild (fuzzy, weaviate) and
# POST /admin/populate-vectors (vectors, fts, geo). Both are "rebuild one or more
# index subsystems", so they speak one shape rather than two vocabularies. Keeping
# them on a single model also means a future merge of the two routes is a
# route-level change with no model churn.

class SubsystemRebuildResult(BaseModel):
    """Per-subsystem outcome inside an admin rebuild."""

    subsystem: str = Field(..., description="fuzzy | weaviate | vectors | fts | geo")
    enabled: bool = Field(True, description="False when the subsystem is not configured; it was skipped")
    duration_seconds: Optional[float] = Field(None, description="Wall-clock time for this subsystem")
    counts: Dict[str, int] = Field(default_factory=dict, description="Subsystem-specific counters")
    errors: List[str] = Field(default_factory=list, description="Failures encountered; empty on success")


class AdminRebuildResponse(ResultStatus):
    """Response for the entity-registry admin rebuild routes."""

    status: OperationStatus = OperationStatus.OK
    results: List[SubsystemRebuildResult] = Field(default_factory=list)

    @classmethod
    def from_results(cls, results: List[SubsystemRebuildResult], message: str = "") -> "AdminRebuildResponse":
        """Derive the contract status from the per-subsystem outcomes.

        Nothing actually ran (none requested, or all disabled) -> NO_OP.
        All that ran succeeded -> OK. Every one that ran failed -> STORE_FAILED.
        Otherwise -> PARTIAL.
        """
        ran = [r for r in results if r.enabled]
        errored = [r for r in ran if r.errors]
        if not ran:
            status = OperationStatus.NO_OP
        elif not errored:
            status = OperationStatus.OK
        elif len(errored) == len(ran):
            status = OperationStatus.STORE_FAILED
        else:
            status = OperationStatus.PARTIAL
        return cls(status=status, results=results, message=message)


# Backward-compat aliases
EntityTopicSearchResult = EntitySearchResult
EntityTopicSearchResponse = EntitySearchResponse
LocationNearResult = LocationSearchResult
LocationNearResponse = LocationSearchResponse
TopicNearLocationResult = EntitySearchLocationResult
TopicNearResult = EntitySearchResult
TopicNearResponse = EntitySearchResponse
EntitiesNearResult = EntitySearchResult
EntitiesNearResponse = EntitySearchResponse
