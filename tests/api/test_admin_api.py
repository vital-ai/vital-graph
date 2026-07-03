"""API tests: Admin endpoint (resync + audit log).

Tests:
  - Resync auxiliary tables for a space
  - Query audit log with filters
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestAdmin:
    """Admin operations."""

    async def test_resync(self, vg_client, test_space):
        """Resync auxiliary tables — should return row counts."""
        resp = await vg_client.admin.resync(space_id=test_space)
        assert resp.space_id == test_space
        assert resp.elapsed_ms >= 0

    async def test_audit_log(self, vg_client):
        """Query audit log — should return paginated entries."""
        resp = await vg_client.admin.audit_log(limit=10)
        assert resp.total_count >= 0
        assert isinstance(resp.entries, list)
        assert resp.limit == 10

    async def test_audit_log_filter_by_actor(self, vg_client):
        """Filter audit log by admin actor."""
        resp = await vg_client.admin.audit_log(actor="admin", limit=5)
        assert resp.total_count >= 0
        for entry in resp.entries:
            assert entry.actor == "admin"
