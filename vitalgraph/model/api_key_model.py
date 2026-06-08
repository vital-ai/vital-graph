"""
Pydantic request/response models for API key management endpoints.
"""

from typing import List, Optional
from pydantic import BaseModel


class ApiKeyCreateRequest(BaseModel):
    username: Optional[str] = None  # target user (admin-only; omit for self)
    name: str                       # human-readable label
    expires_in_days: Optional[int] = None  # None = no expiry


class ApiKeyCreateResponse(BaseModel):
    key_id: str
    key: str                    # full key (shown ONCE)
    prefix: str                 # vg_<prefix>...
    name: str
    username: str
    expires_at: Optional[str] = None
    message: str = "API key created. Save the key — it cannot be retrieved again."


class ApiKeyInfo(BaseModel):
    key_id: str
    prefix: str                 # masked display: vg_Ab3kLm92...
    name: str
    username: str
    is_active: bool
    created_time: Optional[str] = None
    last_used: Optional[str] = None
    expires_at: Optional[str] = None


class ApiKeyListResponse(BaseModel):
    keys: List[ApiKeyInfo]
    total_count: int


class ApiKeyDeleteResponse(BaseModel):
    message: str
    key_id: str
