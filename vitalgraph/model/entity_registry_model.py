"""
Pydantic request/response models for the Entity Registry REST API.
"""

from datetime import datetime
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


class EntityCreateRequest(BaseModel):
    type_key: str = Field(..., description="Entity type key, e.g. 'business', 'person'")
    primary_name: str
    description: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    website: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None
    aliases: Optional[List[AliasCreateRequest]] = None
    identifiers: Optional[List[IdentifierCreateRequest]] = None


class EntityUpdateRequest(BaseModel):
    primary_name: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    locality: Optional[str] = None
    website: Optional[str] = None
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
    status: str
    created_time: Optional[datetime] = None
    updated_time: Optional[datetime] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None
    identifiers: Optional[List[IdentifierResponse]] = None
    aliases: Optional[List[AliasResponse]] = None

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
