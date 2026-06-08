"""
Pydantic request/response models for Geo Config and Geo Points endpoints.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Geo Config models
# ---------------------------------------------------------------------------

class GeoConfigOut(BaseModel):
    config_id: int
    enabled: bool = False
    auto_sync: bool = False
    lat_predicates: List[str] = Field(default_factory=list)
    lon_predicates: List[str] = Field(default_factory=list)
    updated_time: Optional[str] = None


class UpdateGeoConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    auto_sync: Optional[bool] = None
    lat_predicates: Optional[List[str]] = None
    lon_predicates: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Geo Points models
# ---------------------------------------------------------------------------

class GeoPointOut(BaseModel):
    subject_uri: str
    subject_uuid: str
    latitude: float
    longitude: float
    context_uuid: str
    distance_m: Optional[float] = None
    updated_time: Optional[str] = None


class GeoPointsResponse(BaseModel):
    points: List[GeoPointOut]
    total_count: int
    limit: int
    offset: int
