"""
Pydantic request/response models for the Entity Registry REST API.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Request Models
# ------------------------------------------------------------------

class IdentifierCreateRequest(BaseModel):
    identifier_namespace: str = Field(..., description="Namespace/system, e.g. 'DUNS', 'EIN', 'CRM'")
    identifier_value: str = Field(..., description="External ID value")
    is_primary: bool = Field(False, description="Whether this is the preferred ID in this namespace")
    created_by: Optional[str] = None
    notes: Optional[str] = None


class AliasCreateRequest(BaseModel):
    alias_name: str
    alias_type: str = Field('aka', description="aka, dba, former, abbreviation, trade_name")
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
    country_code: Optional[str] = Field(None, max_length=2)
    postal_code: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    timezone: Optional[str] = None
    google_place_id: Optional[str] = None
    external_location_id: Optional[str] = Field(None, max_length=50)
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
    country_code: Optional[str] = Field(None, max_length=2)
    postal_code: Optional[str] = None
    formatted_address: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    timezone: Optional[str] = None
    google_place_id: Optional[str] = None
    external_location_id: Optional[str] = Field(None, max_length=50)
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
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
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
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
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


class RelationshipTypeResponse(BaseModel):
    relationship_type_id: int
    type_key: str
    type_label: str
    type_description: Optional[str] = None
    inverse_key: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class LocationTypeResponse(BaseModel):
    location_type_id: int
    type_key: str
    type_label: str
    type_description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


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


class EntityCreateResponse(BaseModel):
    success: bool
    entity_id: str
    entity_uri: str
    entity: EntityResponse


class EntityListResponse(BaseModel):
    success: bool
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


class EntityTypeResponse(BaseModel):
    type_id: int
    type_key: str
    type_label: str
    type_description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class CategoryResponse(BaseModel):
    category_id: int
    category_key: str
    category_label: str
    category_description: Optional[str] = None
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None

    class Config:
        from_attributes = True


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


class ChangeLogResponse(BaseModel):
    success: bool
    entries: List[ChangeLogEntry]
    total_count: int


# ------------------------------------------------------------------
# Similar Entity / Dedup Models
# ------------------------------------------------------------------

class SimilarEntityResult(BaseModel):
    entity_id: str
    primary_name: str
    type_key: Optional[str] = None
    score: float = Field(..., description="Composite similarity score 0-100")
    match_level: str = Field(..., description="high (>=90), likely (>=70), possible (>=50)")
    score_detail: Dict[str, float] = Field(default_factory=dict)


class SimilarEntityResponse(BaseModel):
    success: bool
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


class EntitySearchResponse(BaseModel):
    success: bool
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


class LocationSearchResponse(BaseModel):
    success: bool
    results: List[LocationSearchResult]


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
