"""
Pydantic request/response models for API key management endpoints.
"""

from typing import List, Optional
from pydantic import BaseModel

from .api_model import BasePaginatedResponse
from .result_status import ResultStatus, OperationStatus


class ApiKeyCreateRequest(BaseModel):
    username: Optional[str] = None  # target user (admin-only; omit for self)
    name: str                       # human-readable label
    expires_in_days: Optional[int] = None  # None = no expiry


class ApiKeyCreateResponse(ResultStatus):
    status: OperationStatus = OperationStatus.CREATED
    key_id: str
    key: str                    # full key (shown ONCE)
    prefix: str                 # vg_<prefix>...
    name: str
    username: str
    expires_at: Optional[str] = None


class ApiKeyInfo(BaseModel):
    key_id: str
    prefix: str                 # masked display: vg_Ab3kLm92...
    name: str
    username: str
    is_active: bool
    created_time: Optional[str] = None
    last_used: Optional[str] = None
    expires_at: Optional[str] = None


class ApiKeyGetResponse(ResultStatus):
    """Envelope for a single API key lookup."""
    status: OperationStatus = OperationStatus.FOUND
    key: Optional[ApiKeyInfo] = None


class ApiKeyListResponse(BasePaginatedResponse):
    keys: List[ApiKeyInfo]


class ApiKeyDeleteResponse(ResultStatus):
    status: OperationStatus = OperationStatus.DELETED
    key_id: str
