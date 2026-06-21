"""
Pydantic request/response models for Fuzzy Mappings endpoints.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class FuzzyMappingPropertyOut(BaseModel):
    property_id: int
    mapping_id: int
    property_uri: str
    property_role: str = "include"
    ordinal: int = 0


class FuzzyMappingOut(BaseModel):
    mapping_id: int
    mapping_type: str
    type_uri: Optional[str] = None
    index_name: str
    enabled: bool = True
    shingle_k: int = 3
    num_perm: int = 64
    lsh_threshold: float = 0.3
    phonetic_bonus: float = 10.0
    created_time: Optional[str] = None
    properties: List[FuzzyMappingPropertyOut] = []


class FuzzyMappingListResponse(BaseModel):
    mappings: List[FuzzyMappingOut]
    total_count: int


class CreateFuzzyMappingRequest(BaseModel):
    mapping_type: str = Field(..., description="kgentity | kgdocument | kgframe | kgslot")
    type_uri: Optional[str] = Field(None, description="Specific KG Type URI (NULL = class-level)")
    index_name: str = Field(..., description="Fuzzy index name")
    enabled: bool = Field(True, description="Enable/disable fuzzy indexing")
    shingle_k: int = Field(3, ge=2, le=10, description="Character n-gram size")
    num_perm: int = Field(64, ge=16, le=256, description="MinHash permutations")
    lsh_threshold: float = Field(0.3, ge=0.1, le=1.0, description="Jaccard similarity threshold for LSH")
    phonetic_bonus: float = Field(10.0, ge=0.0, le=50.0, description="Score bonus for phonetic matches")


class UpdateFuzzyMappingRequest(BaseModel):
    enabled: Optional[bool] = None
    shingle_k: Optional[int] = Field(None, ge=2, le=10)
    num_perm: Optional[int] = Field(None, ge=16, le=256)
    lsh_threshold: Optional[float] = Field(None, ge=0.1, le=1.0)
    phonetic_bonus: Optional[float] = Field(None, ge=0.0, le=50.0)


class FuzzyMappingStatsResponse(BaseModel):
    mapping_id: int
    band_count: int = 0
    entity_count: int = 0
    phonetic_band_count: int = 0


class AddFuzzyPropertyRequest(BaseModel):
    property_uri: str = Field(..., description="Predicate URI to include in fuzzy index")
    property_role: str = Field("include", description="primary | alias | include")
    ordinal: int = Field(0, description="Controls concatenation order")
