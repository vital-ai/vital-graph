"""API tests: Process Endpoint via VitalGraphClient.

Tests the process tracking REST API: scheduler status, list processes,
trigger maintenance, get process by ID.
Based on test_scripts/vitalgraph_client_test/sparql_sql/case_process_endpoint.py
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]


class TestProcessEndpoint:
    """Process tracking: scheduler status, list, trigger, get by ID."""

    async def test_scheduler_status(self, vg_client):
        """Get scheduler status — returns enabled/running as booleans."""
        status = await vg_client.processes.get_scheduler_status()
        assert isinstance(status.enabled, bool)
        assert isinstance(status.running, bool)

    async def test_list_processes(self, vg_client):
        """List processes returns processes array and total_count >= 0."""
        resp = await vg_client.processes.list_processes(limit=10)
        assert isinstance(resp.processes, list)
        assert resp.total_count >= 0
        assert resp.total_count >= len(resp.processes)

    async def test_list_processes_with_type_filter(self, vg_client):
        """List processes with type filter — all results match type."""
        resp = await vg_client.processes.list_processes(process_type="maintenance", limit=10)
        assert isinstance(resp.processes, list)
        for p in resp.processes:
            assert p.process_type == "maintenance"

    async def test_list_processes_with_status_filter(self, vg_client):
        """List processes with status filter — all results match status."""
        resp = await vg_client.processes.list_processes(status="completed", limit=10)
        assert isinstance(resp.processes, list)
        for p in resp.processes:
            assert p.status == "completed"

    async def test_list_processes_pagination(self, vg_client):
        """List processes respects pagination params."""
        resp = await vg_client.processes.list_processes(limit=2, offset=0)
        assert resp.limit == 2
        assert resp.offset == 0
        assert len(resp.processes) <= 2

    async def test_trigger_maintenance(self, vg_client):
        """Trigger maintenance returns triggered boolean and a message string."""
        resp = await vg_client.processes.trigger(process_type="maintenance")
        assert isinstance(resp.triggered, bool)
        assert isinstance(resp.message, str) and len(resp.message) > 0

    async def test_get_nonexistent_process(self, vg_client):
        """Get non-existent process returns 404."""
        with pytest.raises(Exception, match=r"(?i)(404|not found)"):
            await vg_client.processes.get_process("00000000-0000-0000-0000-000000000000")
