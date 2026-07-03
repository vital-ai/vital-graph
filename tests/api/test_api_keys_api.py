"""API tests: API Keys CRUD lifecycle via VitalGraphClient.

Tests API key management endpoints:
  - Create key → list → get → revoke
  - Verify key no longer active after revocation
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestApiKeysCrud:
    """API key create → list → get → revoke lifecycle."""

    async def test_create_key(self, vg_client):
        """Create an API key and verify response contains the full key."""
        resp = await vg_client.api_keys.create_key(name="test_create_key")
        assert resp.key_id is not None
        assert resp.key  # full key shown once
        assert resp.name == "test_create_key"
        # Cleanup
        await vg_client.api_keys.revoke_key(resp.key_id)

    async def test_list_keys(self, vg_client):
        """Create a key, then verify it appears in the list."""
        created = await vg_client.api_keys.create_key(name="test_list_key")

        resp = await vg_client.api_keys.list_keys()
        assert resp.total_count >= 1
        key_ids = [k.key_id for k in resp.keys]
        assert created.key_id in key_ids
        # Cleanup
        await vg_client.api_keys.revoke_key(created.key_id)

    async def test_get_key(self, vg_client):
        """Create a key, then get it by ID."""
        created = await vg_client.api_keys.create_key(name="test_get_key")

        fetched = await vg_client.api_keys.get_key(created.key_id)
        assert fetched.key_id == created.key_id
        assert fetched.name == "test_get_key"
        assert fetched.is_active is True
        # Cleanup
        await vg_client.api_keys.revoke_key(created.key_id)

    async def test_revoke_key(self, vg_client):
        """Create a key, revoke it, verify it is no longer active."""
        created = await vg_client.api_keys.create_key(name="test_revoke_key")

        del_resp = await vg_client.api_keys.revoke_key(created.key_id)
        assert del_resp.key_id == created.key_id

        # Verify deactivated
        fetched = await vg_client.api_keys.get_key(created.key_id)
        assert fetched.is_active is False

    async def test_create_key_with_expiry(self, vg_client):
        """Create a key with an expiry and verify expires_at is set."""
        resp = await vg_client.api_keys.create_key(
            name="test_expiry_key", expires_in_days=30
        )
        assert resp.expires_at is not None
        # Cleanup
        await vg_client.api_keys.revoke_key(resp.key_id)
