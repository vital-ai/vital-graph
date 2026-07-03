"""API tests: Metrics endpoint (query metrics + slow queries).

Tests:
  - Get realtime metrics for a space
  - Get slow queries for a space
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestMetrics:
    """Query metrics retrieval."""

    async def test_get_metrics_realtime(self, vg_client, test_space):
        """Get realtime metrics — should return a dict with expected keys."""
        resp = await vg_client.metrics.get_metrics(
            space_id=test_space, range="realtime"
        )
        assert resp["success"] is True
        assert resp["space_id"] == test_space
        assert resp["range"] == "realtime"
        assert "totals" in resp

    async def test_get_slow_queries(self, vg_client, test_space):
        """Get slow queries — should return a dict (possibly empty list)."""
        resp = await vg_client.metrics.get_slow_queries(
            space_id=test_space, limit=10
        )
        assert resp["success"] is True
        assert resp["space_id"] == test_space
        assert isinstance(resp["slow_queries"], list)
