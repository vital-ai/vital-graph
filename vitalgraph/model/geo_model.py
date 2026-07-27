"""
Pydantic request/response models for Geo Config and Geo Points endpoints.
"""

from typing import List, Optional
from pydantic import BaseModel, Field

from .api_model import BasePaginatedResponse
from .result_status import ResultStatus, OperationStatus


# ---------------------------------------------------------------------------
# Geo Config models
# ---------------------------------------------------------------------------

class GeoConfigOut(ResultStatus):
    config_id: Optional[int] = None
    enabled: bool = False
    auto_sync: bool = False
    lat_predicates: List[str] = Field(default_factory=list)
    lon_predicates: List[str] = Field(default_factory=list)
    updated_time: Optional[str] = None
    status: OperationStatus = Field(
        OperationStatus.FOUND, description="Outcome discriminator (FOUND/UPDATED/...)"
    )


class GeoConfigResetResponse(ResultStatus):
    """Response for resetting (deleting) a space's geo config row."""
    space_id: str
    status: OperationStatus = Field(
        OperationStatus.DELETED, description="Outcome discriminator (DELETED/...)"
    )


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


class GeoPointsResponse(BasePaginatedResponse):
    points: List[GeoPointOut]
