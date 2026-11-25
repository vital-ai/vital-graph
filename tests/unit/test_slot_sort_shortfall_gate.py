"""The slot-sort shortfall probe re-derives only when the data changed.

`issues/343`. The block's own gate, "run the exact split only when the cheap count
is nonzero", can never close: value-less, entity and orphaned slots are correctly
absent from `entity_slot_sort`, so the cheap count is permanently > 0 on any real
space. Production, 2026-11-15, one quiet hour: `entity_slot_sort_gap` ran every
~15-minute cycle on every KG space at 15-85 s a call, 51 % of the database's time.

These drive `_run_entity_slot_sort_integrity` itself through a fake pool, and count
calls to the three space-proportional functions.
"""
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from vitalgraph.db.sparql_sql import fast_slot_filter as FSF
from vitalgraph.db.sparql_sql import sync_entity_slot_sort as ESS
from vitalgraph.process import maintenance_job as M


class _Conn:
    def __init__(self, state):
        self.state = state

    async def fetchval(self, *_a, **_k):     # probe_data_changed's watermark read
        return self.state["watermark"]

    async def execute(self, *_a, **_k):
        return None


class _Pool:
    def __init__(self, state):
        self.state = state

    @asynccontextmanager
    async def acquire(self):
        yield _Conn(self.state)


@asynccontextmanager
async def _no_timeouts(_conn):
    yield


@pytest.fixture
def rig(monkeypatch):
    M.reset_probe_gate()
    state = {"watermark": 100, "repair_rows": 0, "gap_raises": None, "now": 1000.0,
             "calls": {"shortfall": 0, "gap": 0, "repair": 0}}
    # `issues/349`: the gate also holds an opted-in probe for a minimum interval.
    monkeypatch.setattr(M, "_probe_clock", lambda: state["now"])

    async def shortfall(conn, space_id, timeout=None):
        state["calls"]["shortfall"] += 1
        # PERMANENTLY nonzero, as on every real space: the defect's precondition.
        return {"quad_slots": 1000, "table_rows": 900, "shortfall": 100}

    async def gap(conn, space_id, timeout=None):
        state["calls"]["gap"] += 1
        if state["gap_raises"]:
            raise state["gap_raises"]
        return {"real": 50, "table_rows": 900, "quad_slots": 1000, "shortfall": 100,
                "no_value": 30, "entity_slots": 20}

    async def repair(conn, space_id, timeout=None):
        state["calls"]["repair"] += 1
        return {"rows": state["repair_rows"], "slots": state["repair_rows"],
                "entities": 1 if state["repair_rows"] else 0,
                "unattributed": 0, "orphaned": 50}

    async def coverage(*_a, **_k):
        return []

    async def all_types(*_a, **_k):
        return []

    async def alarms(*_a, **_k):
        return []

    async def release(*_a, **_k):
        return False

    monkeypatch.setattr(ESS, "entity_slot_sort_row_shortfall", shortfall)
    monkeypatch.setattr(ESS, "entity_slot_sort_gap", gap)
    monkeypatch.setattr(ESS, "backfill_entity_slot_sort_missing_slots", repair)
    monkeypatch.setattr(ESS, "entity_slot_sort_coverage", coverage)
    monkeypatch.setattr(ESS, "entity_slot_sort_all_types", all_types)
    monkeypatch.setattr(FSF, "slot_sort_alarms", alarms)
    monkeypatch.setattr(FSF, "release_whole_space_block_if_complete", release)
    monkeypatch.setattr(M, "maintenance_timeouts", _no_timeouts)

    job = M.MaintenanceJob.__new__(M.MaintenanceJob)
    job._pool = _Pool(state)
    yield job, state
    M.reset_probe_gate()


async def _cycle(job):
    await job._run_entity_slot_sort_integrity(["sp"])


@pytest.mark.asyncio
async def test_unchanged_data_does_not_rerun_the_exact_split(rig):
    job, st = rig
    await _cycle(job)
    assert st["calls"] == {"shortfall": 1, "gap": 1, "repair": 1}
    for _ in range(3):
        await _cycle(job)
    assert st["calls"] == {"shortfall": 1, "gap": 1, "repair": 1}, (
        "the exact split re-ran on a space nobody wrote to: the issues/343 defect")


@pytest.mark.asyncio
async def test_a_write_reopens_it_once_the_interval_has_passed(rig):
    """`issues/349`: a write alone no longer reopens it inside the interval."""
    job, st = rig
    await _cycle(job)
    st["watermark"] = 101
    await _cycle(job)
    assert st["calls"]["gap"] == 1, "re-ran inside the minimum interval"
    st["now"] += M.PROBE_MIN_INTERVAL_S
    await _cycle(job)
    assert st["calls"]["gap"] == 2


@pytest.mark.asyncio
async def test_a_space_written_every_cycle_runs_once_per_interval(rig):
    """The production case: the main KG space is written between every two cycles.
    Under `343` alone the split ran every cycle there; now once per interval."""
    job, st = rig
    cycle_s = 900.0
    cycles = int(2 * M.PROBE_MIN_INTERVAL_S / cycle_s)
    for _ in range(cycles):
        st["watermark"] += 1
        await _cycle(job)
        st["now"] += cycle_s
    assert st["calls"]["gap"] == 2, st["calls"]


@pytest.mark.asyncio
async def test_a_repair_that_added_rows_is_checked_again(rig):
    """The repair writes `entity_slot_sort`, which the quad watermark cannot see.

    A bounded repair that made progress must get another pass on a quiet space,
    or it strands half-done: the issues/149 trap from the other direction.
    """
    job, st = rig
    st["repair_rows"] = 7
    await _cycle(job)
    await _cycle(job)                       # quads unchanged, but work was done
    assert st["calls"]["gap"] == 2
    st["repair_rows"] = 0                   # this pass finds nothing more to add
    await _cycle(job)
    await _cycle(job)                       # converged: now the gate holds
    assert st["calls"]["gap"] == 3


@pytest.mark.asyncio
async def test_a_failed_pass_runs_again(rig):
    """The watermark moved when the gate passed. A pass that dies part-way must
    not read as converged, or the space is never re-checked until its next write."""
    job, st = rig
    st["gap_raises"] = RuntimeError("boom")
    await _cycle(job)
    st["gap_raises"] = None
    await _cycle(job)
    assert st["calls"]["gap"] == 2
    await _cycle(job)
    assert st["calls"]["gap"] == 2


@pytest.mark.asyncio
async def test_a_timeout_backs_off_instead_of_rescanning(rig):
    """`issues/270`: a pass that proved too long to finish is not repeated next cycle."""
    job, st = rig
    st["gap_raises"] = TimeoutError()
    await _cycle(job)
    st["gap_raises"] = None
    await _cycle(job)
    assert st["calls"]["gap"] == 1, "a timed-out pass was retried inside its back-off"
