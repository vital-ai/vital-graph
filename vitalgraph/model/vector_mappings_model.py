"""
Pydantic request/response models for Vector Mappings endpoints.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


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
