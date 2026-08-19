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

    async def test_trigger_maintenance(self, vg_client, test_space):
        """Trigger maintenance for ONE space returns triggered + a message.

        SCOPED deliberately. The unscoped form runs the whole pass — it scores
        every space and each of the six integrity phases sweeps all of them — so
        its cost tracks the NUMBER OF SPACES on the stack, not the work this
        assertion needs. Measured here: 148 s unscoped against 0.8 s for one
        space, and the client's read timeout expires long before the former.

        That made this test fail on a machine carrying perf fixtures and pass on
        a fresh one, which is a property of the stack rather than of the code
        under test. The contract asserted below is identical either way.
        """
        resp = await vg_client.processes.trigger(
            process_type="maintenance", space_id=test_space)
        assert isinstance(resp.triggered, bool)
        assert isinstance(resp.message, str) and len(resp.message) > 0

    async def test_trigger_maintenance_honours_the_space(self, vg_client, test_space):
        """`space_id` must actually scope the work.

        It was accepted and DISCARDED: `ProcessScheduler.trigger_now` scopes by
        looking up `trigger_<process_type>` on the handler, and `MaintenanceJob`
        had `trigger_analyze`/`trigger_vacuum`/... but no `trigger_maintenance`,
        so the request fell through to `run()`. No error, no scoping — the
        parameter was documented as "Target space (omit for auto-select)" and did
        nothing.
        """
        resp = await vg_client.processes.trigger(
            process_type="maintenance", space_id=test_space)
        assert resp.triggered
        result = getattr(resp, "result", None)
        assert result, "no result payload — cannot tell what was acted on"
        assert result.get("space_id") == test_space, (
            f"maintenance reported on {result.get('space_id')!r} for a request "
            f"scoped to {test_space!r} — the parameter is being ignored")

    async def test_get_nonexistent_process(self, vg_client):
        """Get non-existent process returns 404."""
        with pytest.raises(Exception, match=r"(?i)(404|not found)"):
            await vg_client.processes.get_process("00000000-0000-0000-0000-000000000000")
