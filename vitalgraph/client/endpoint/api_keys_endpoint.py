"""
VitalGraph Client - API Keys Endpoint

Client-side endpoint for API Key management REST API operations.
"""

import logging
from typing import Optional

from .base_endpoint import BaseEndpoint
from ..utils.client_utils import VitalGraphClientError, validate_required_params, build_query_params
from ...model.api_key_model import (
    ApiKeyCreateRequest, ApiKeyCreateResponse,
    ApiKeyListResponse, ApiKeyInfo, ApiKeyDeleteResponse,
)

logger = logging.getLogger(__name__)


class ApiKeysClientEndpoint(BaseEndpoint):
    """Client endpoint for API Key management operations."""

    def __init__(self, client):
        super().__init__(client)
        self._base_path = "/api/keys"

    def _url(self, path: str = "") -> str:
        return f"{self._get_server_url()}{self._base_path}{path}"

    async def create_key(
        self,
        name: str,
        username: Optional[str] = None,
        expires_in_days: Optional[int] = None,
    ) -> ApiKeyCreateResponse:
        """Create a new API key.

        Args:
            name: Human-readable label for the key
            username: Target user (admin-only; omit for self)
            expires_in_days: Optional expiry in days (None = no expiry)

        Returns:
            ApiKeyCreateResponse with the full key (shown once)
        """
        self._check_connection()
        request = ApiKeyCreateRequest(
            name=name, username=username, expires_in_days=expires_in_days
        )
        return await self._make_typed_request(
            "POST", self._url(), ApiKeyCreateResponse, json=request.model_dump(exclude_none=True),
        )

    async def list_keys(self, username: Optional[str] = None) -> ApiKeyListResponse:
        """List API keys visible to the current user.

        Args:
            username: Optional filter by username (admin-only)

        Returns:
            ApiKeyListResponse with key metadata
        """
        self._check_connection()
        params = build_query_params(username=username)
        return await self._make_typed_request(
            "GET", self._url(), ApiKeyListResponse, params=params,
        )

    async def get_key(self, key_id: str) -> ApiKeyInfo:
        """Get metadata for a single API key.

        Args:
            key_id: Key ID

        Returns:
            ApiKeyInfo with key metadata
        """
        self._check_connection()
        validate_required_params(key_id=key_id)
        return await self._make_typed_request(
            "GET", self._url(f"/{key_id}"), ApiKeyInfo,
        )

    async def revoke_key(self, key_id: str) -> ApiKeyDeleteResponse:
        """Revoke (delete) an API key.

        Args:
            key_id: Key ID to revoke

        Returns:
            ApiKeyDeleteResponse confirming revocation
        """
        self._check_connection()
        validate_required_params(key_id=key_id)
        return await self._make_typed_request(
            "DELETE", self._url(f"/{key_id}"), ApiKeyDeleteResponse,
        )
