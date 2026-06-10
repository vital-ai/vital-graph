"""
API Keys endpoint — CRUD operations for API key management.

Self-service: authenticated users can create/list/revoke their own keys.
Admins can manage any user's keys.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
import logging

from ..auth.api_key import generate_api_key, hash_api_key
from ..auth.audit import emit_audit_event
from ..model.api_key_model import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyDeleteResponse,
    ApiKeyInfo,
    ApiKeyListResponse,
)

logger = logging.getLogger(__name__)

MAX_KEYS_PER_USER = 10


class ApiKeysEndpoint:
    """API Keys endpoint handler with self-service + admin access."""

    def __init__(self, api, auth_dependency):
        self.api = api
        self.auth_dependency = auth_dependency
        self.router = APIRouter(prefix="/api/keys", tags=["API Keys"])
        self._setup_routes()

    def _setup_routes(self):
        @self.router.post("", response_model=ApiKeyCreateResponse)
        async def create_key(
            request: ApiKeyCreateRequest,
            current_user: Dict = Depends(self.auth_dependency),
        ):
            return await self._create_key(request, current_user)

        @self.router.get("", response_model=ApiKeyListResponse)
        async def list_keys(
            username: Optional[str] = Query(None),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            return await self._list_keys(current_user, username)

        @self.router.get("/key", response_model=ApiKeyInfo)
        async def get_key(
            key_id: str = Query(..., description="API Key ID"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            return await self._get_key(key_id, current_user)

        @self.router.delete("", response_model=ApiKeyDeleteResponse)
        async def revoke_key(
            key_id: str = Query(..., description="API Key ID to revoke"),
            current_user: Dict = Depends(self.auth_dependency),
        ):
            return await self._revoke_key(key_id, current_user)

    async def _create_key(
        self, request: ApiKeyCreateRequest, current_user: Dict
    ) -> ApiKeyCreateResponse:
        if not self.api.db:
            raise HTTPException(status_code=500, detail="Database not configured")

        actor = current_user.get("username", "unknown")
        target_username = request.username or actor

        # Non-admins can only create keys for themselves
        if target_username != actor and current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot create keys for other users",
            )

        # Resolve target user
        target_user = await self.api.db.get_user_by_username(target_username)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{target_username}' not found",
            )

        # Enforce max keys
        count = await self.api.db.count_user_api_keys(target_user['user_id'])
        if count >= MAX_KEYS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum API keys ({MAX_KEYS_PER_USER}) reached for this user",
            )

        # Generate key
        full_key, prefix = generate_api_key()
        key_hash = hash_api_key(full_key)

        # Calculate expiry
        expires_at = None
        if request.expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=request.expires_in_days)

        # Insert
        record = await self.api.db.create_api_key(
            user_id=target_user['user_id'],
            name=request.name,
            key_prefix=prefix,
            key_hash=key_hash,
            expires_at=expires_at,
        )

        emit_audit_event("auth.apikey.created", actor,
                         target=target_username,
                         key_name=request.name,
                         key_prefix=prefix)

        return ApiKeyCreateResponse(
            key_id=str(record['key_id']),
            key=full_key,
            prefix=f"vg_{prefix}...",
            name=request.name,
            username=target_username,
            expires_at=expires_at.isoformat() if expires_at else None,
        )

    async def _list_keys(
        self, current_user: Dict, username: Optional[str] = None
    ) -> ApiKeyListResponse:
        if not self.api.db:
            raise HTTPException(status_code=500, detail="Database not configured")

        actor = current_user.get("username", "unknown")
        is_admin = current_user.get("role") == "admin"

        # Non-admins always see only their own keys
        if not is_admin:
            username = actor

        user_id = None
        if username:
            user = await self.api.db.get_user_by_username(username)
            if user:
                user_id = user['user_id']
            else:
                return ApiKeyListResponse(keys=[], total_count=0)

        rows = await self.api.db.list_api_keys(user_id=user_id)

        keys = [
            ApiKeyInfo(
                key_id=str(row['key_id']),
                prefix=f"vg_{row['key_prefix']}...",
                name=row['name'],
                username=row['username'],
                is_active=row['is_active'],
                created_time=row['created_time'].isoformat() if row.get('created_time') else None,
                last_used=row['last_used'].isoformat() if row.get('last_used') else None,
                expires_at=row['expires_at'].isoformat() if row.get('expires_at') else None,
            )
            for row in rows
        ]

        return ApiKeyListResponse(keys=keys, total_count=len(keys))

    async def _get_key(self, key_id: str, current_user: Dict) -> ApiKeyInfo:
        if not self.api.db:
            raise HTTPException(status_code=500, detail="Database not configured")

        key = await self.api.db.get_api_key_by_id(key_id)
        if not key:
            raise HTTPException(status_code=404, detail="API key not found")

        # Check ownership or admin
        actor = current_user.get("username", "unknown")
        if key['username'] != actor and current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return ApiKeyInfo(
            key_id=str(key['key_id']),
            prefix=f"vg_{key['key_prefix']}...",
            name=key['name'],
            username=key['username'],
            is_active=key['is_active'],
            created_time=key['created_time'].isoformat() if key.get('created_time') else None,
            last_used=key['last_used'].isoformat() if key.get('last_used') else None,
            expires_at=key['expires_at'].isoformat() if key.get('expires_at') else None,
        )

    async def _revoke_key(self, key_id: str, current_user: Dict) -> ApiKeyDeleteResponse:
        if not self.api.db:
            raise HTTPException(status_code=500, detail="Database not configured")

        key = await self.api.db.get_api_key_by_id(key_id)
        if not key:
            raise HTTPException(status_code=404, detail="API key not found")

        actor = current_user.get("username", "unknown")
        if key['username'] != actor and current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot revoke another user's key",
            )

        await self.api.db.deactivate_api_key(key_id)

        emit_audit_event("auth.apikey.revoked", actor,
                         target=key['username'], level="WARN",
                         key_id=key_id, key_name=key['name'])

        return ApiKeyDeleteResponse(
            message=f"API key '{key['name']}' revoked",
            key_id=key_id,
        )


def create_api_keys_router(api, auth_dependency) -> APIRouter:
    """Create and return the API keys router."""
    endpoint = ApiKeysEndpoint(api, auth_dependency)
    return endpoint.router
