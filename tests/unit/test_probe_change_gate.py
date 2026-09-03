"""An O(graph) probe must not re-derive when nothing was written.

`issues/150`. `entity_slot_sort_drift` computes `expected` with the full
unseeded `WITH RECURSIVE frame_walk`. Measured on production 2026-09-03, AFTER
`478fa06` gave it the maintenance budget:

    durations: 216s, 216s, 122s, 303s, 252s, 59s, 256s
    DUTY CYCLE = 54% of wall-clock inside this ONE probe

Before that fix, asyncpg's `command_timeout=60` killed it at 60s. That was a bug
— the probe never completed, so the backfill it gates never ran — but it was
also accidentally bounding the damage. Raising the budget without gating the
cadence turned "fails fast every cycle" into "runs four minutes every cycle",
scanning the quad table and evicting the read path's cache. A user query
measured 1.5s with the probe idle and 58s with it running; a benchmark of that
query reported 58% of runs stalling, which matches the duty cycle.

The cheap probe stays ungated: `entity_slot_sort_coverage` measured 130ms and
answers the question that actually matters (is a type served at all).
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import inspect

import pytest

from vitalgraph.process import maintenance_job as M


class _Conn:
    def __init__(self, watermark):
        self.watermark = watermark

    async def fetchval(self, *_a):
        return self.watermark


@pytest.fixture(autouse=True)
def _clean():
    M.reset_probe_gate()
    yield
    M.reset_probe_gate()


@pytest.mark.asyncio
async def test_unchanged_data_skips_the_walk():
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is True
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is False


@pytest.mark.asyncio
async def test_a_write_reopens_it():
    await M.probe_data_changed(_Conn(100), "sp", "d")
    assert await M.probe_data_changed(_Conn(101), "sp", "d") is True


@pytest.mark.asyncio
async def test_unconverged_work_overrides_the_gate():
    """The trap in gating on writes alone.

    The backfill only ADDs, so a 2.7M-row gap takes many passes. On a quiet
    space, a write-only gate would skip every one of them and strand the table
    half-filled — the same "looks fixed, repairs nothing" outcome as issues/149.
    """
    await M.probe_data_changed(_Conn(100), "sp", "d")
    M.mark_probe_converged("sp", "d", False)
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is True

    M.mark_probe_converged("sp", "d", True)
    assert await M.probe_data_changed(_Conn(100), "sp", "d") is False


@pytest.mark.asyncio
async def test_a_stats_reset_fails_toward_running():
    """`pg_stat_reset()` moves the counter DOWN. `!=` is the honest test; `>`
    would silently disable the probe forever after a reset."""
    await M.probe_data_changed(_Conn(500), "sp", "d")
    assert await M.probe_data_changed(_Conn(3), "sp", "d") is True


@pytest.mark.asyncio
async def test_an_unreadable_counter_does_the_work():
    class _Boom:
        async def fetchval(self, *_a):
            raise RuntimeError("no pg_stat")

    assert await M.probe_data_changed(_Boom(), "sp", "d") is True
    assert await M.probe_data_changed(_Conn(None), "sp", "d") is True


@pytest.mark.asyncio
async def test_spaces_and_probes_do_not_share_a_watermark():
    await M.probe_data_changed(_Conn(100), "a", "d")
    assert await M.probe_data_changed(_Conn(100), "b", "d") is True
    assert await M.probe_data_changed(_Conn(100), "a", "other") is True


def test_the_remaining_o_graph_probes_are_gated():
    """The slot-sort walk left this path entirely in `issues/151` — coverage
    replaced it. The gate still guards the two sibling drift probes, which are
    the remaining full-table scans on the maintenance loop (edge_table_drift
    measured 17.7s over ~50M rows)."""
    src = inspect.getsource(M)
    for probe in ("edge_table_drift", "frame_entity_drift"):
        i = src.index(f'probe_data_changed(\n' if False else f'"{probe}")')
        window = src[max(0, i - 400):i]
        assert "probe_data_changed(" in window, f"{probe} is ungated"
    assert "mark_probe_converged(" in src, (
        "without recording convergence a repair strands half-done on a quiet "
        "space — the gate would skip the passes it still needs")


def test_the_slot_sort_repair_no_longer_uses_the_o_graph_walk():
    """`issues/151`: coverage (130ms) decides, a bounded batch repairs."""
    src = inspect.getsource(M.MaintenanceJob._run_entity_slot_sort_integrity)
    assert "entity_slot_sort_drift(" not in src
    assert "backfill_entity_slot_sort_batch(" in src
