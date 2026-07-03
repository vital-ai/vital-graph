"""API tests: Health and connectivity.

Validates the server is running and the client can authenticate.
"""

from __future__ import annotations

import httpx
import pytest

from .conftest import SERVER_URL

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestHealth:
    """Server health and client auth."""

    async def test_health_endpoint_raw(self):
        """GET /health returns 200 with status info (no auth required)."""
        async with httpx.AsyncClient() as raw:
            r = await raw.get(f"{SERVER_URL}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "status" in data

    async def test_client_connected(self, vg_client):
        """Client is connected and authenticated after open()."""
        assert vg_client.is_open
        assert vg_client.is_connected()
        assert vg_client.access_token is not None

    async def test_server_info(self, vg_client):
        """get_server_info() returns auth status."""
        info = vg_client.get_server_info()
        auth_info = info.get("authentication", {})
        assert auth_info.get("has_access_token") is True
