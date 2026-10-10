"""A frame_slot gap below the drift floor is repaired once it persists.

`issues/263`. `lead_prod_frame_slot` was 921 rows short for a month: 211 frames
written by the previous release during the 2026-09-10 migration window. The
integrity step warned on any drift — 3,402 times — while the backfill straight
after it acted only above `max(EDGE_DRIFT_MIN_ABS, 1% of expected)`, about
11,200 there. So a gap the backfill would have closed in one pass was, by
configuration, never closed.

The floor exists so a full-scan backfill does not chase rows a write is still
deriving. Those clear within a cycle; a residue does not. Hence: below the
floor, backfill after FRAME_SLOT_RESIDUE_CYCLES consecutive cycles of drift, and
do not repeat a backfill that inserted nothing until the drift changes.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from vitalgraph.db.sparql_sql import sync_frame_slot_table as FS
from vitalgraph.process import maintenance_job as M


class _Pool:
    def acquire(self):
        @asynccontextmanager
        async def _a():
            yield object()
        return _a()


class _World:
    """Drift per space, and what a backfill would insert."""

    def __init__(self, drift: dict, insertable: dict | None = None):
        self.drift = dict(drift)
        self.insertable = dict(insertable if insertable is not None else drift)
        self.backfills: list[str] = []

    async def frame_slot_drift(self, conn, space_id, timeout=None):
        return 1_000_000, 1_000_000 - self.drift[space_id]

    async def frame_slot_orphan_rate(self, conn, space_id):
        return 0.0

    async def backfill_frame_slot_table(self, conn, space_id, timeout=None):
        self.backfills.append(space_id)
        n = self.insertable.get(space_id, 0)
        self.drift[space_id] -= n
        self.insertable[space_id] = 0
        return n


@pytest.fixture
def world(monkeypatch):
    M.reset_probe_gate()
    M._frame_slot_residue_cycles.clear()
    M._frame_slot_residue_futile.clear()

    async def _changed(conn, space_id, probe):
        return True

    @asynccontextmanager
    async def _no_budget(conn):
        yield

    monkeypatch.setattr(M, "probe_data_changed", _changed)
    monkeypatch.setattr(M, "maintenance_timeouts", _no_budget)

    def install(w: _World):
        for name in ("frame_slot_drift", "frame_slot_orphan_rate",
                     "backfill_frame_slot_table"):
            monkeypatch.setattr(FS, name, getattr(w, name))
        return w

    yield install
    M.reset_probe_gate()
    M._frame_slot_residue_cycles.clear()
    M._frame_slot_residue_futile.clear()


async def _cycles(job, spaces, n):
    out = []
    for _ in range(n):
        out.append(await job._run_frame_slot_backfill(spaces))
    return out


@pytest.mark.asyncio
async def test_the_lead_prod_residue_is_repaired_after_it_persists(world):
    """921 missing rows of 1M — below both floors — is backfilled on the
    third consecutive cycle, not never."""
    w = world(_World({"lead_prod": 921}))
    job = M.MaintenanceJob(_Pool())

    results = await _cycles(job, ["lead_prod"], M.FRAME_SLOT_RESIDUE_CYCLES)

    assert results[:-1] == [None] * (M.FRAME_SLOT_RESIDUE_CYCLES - 1), (
        "a gap that has not yet persisted must not trigger the full-scan "
        "backfill — it may be rows a write is still deriving")
    assert w.backfills == ["lead_prod"]
    assert results[-1]["rows_added"] == 921
    assert w.drift["lead_prod"] == 0


@pytest.mark.asyncio
async def test_a_transient_gap_never_triggers_it(world):
    """Drift that clears within a cycle resets the count."""
    w = world(_World({"sp": 5}))
    job = M.MaintenanceJob(_Pool())
    for _ in range(4):
        await job._run_frame_slot_backfill(["sp"])   # drift 5, cycle 1
        w.drift["sp"] = 0
        await job._run_frame_slot_backfill(["sp"])   # cleared: count resets
        w.drift["sp"] = 5
    assert w.backfills == []


@pytest.mark.asyncio
async def test_an_unrepairable_gap_is_scanned_once_not_every_cycle(world):
    """If the backfill inserts nothing, the gap is not something its join can
    produce; rescanning every cycle would just repeat the full scan."""
    w = world(_World({"sp": 40}, insertable={"sp": 0}))
    job = M.MaintenanceJob(_Pool())

    await _cycles(job, ["sp"], M.FRAME_SLOT_RESIDUE_CYCLES + 5)

    assert w.backfills == ["sp"]


@pytest.mark.asyncio
async def test_a_changed_drift_is_tried_again(world):
    """New missing rows on top of an unrepairable gap are worth one more pass."""
    w = world(_World({"sp": 40}, insertable={"sp": 0}))
    job = M.MaintenanceJob(_Pool())
    await _cycles(job, ["sp"], M.FRAME_SLOT_RESIDUE_CYCLES)
    assert w.backfills == ["sp"]

    w.drift["sp"] = 47
    w.insertable["sp"] = 7
    await _cycles(job, ["sp"], M.FRAME_SLOT_RESIDUE_CYCLES)

    assert w.backfills == ["sp", "sp"]
    assert w.drift["sp"] == 40


@pytest.mark.asyncio
async def test_a_gap_above_the_floor_still_goes_first(world):
    """The floor path is unchanged: immediate, and ahead of any residue."""
    big = M.EDGE_DRIFT_MIN_ABS + 20_000
    w = world(_World({"small": 921, "big": big}))
    job = M.MaintenanceJob(_Pool())

    first = await job._run_frame_slot_backfill(["small", "big"])

    assert first["space_id"] == "big"
    assert w.backfills == ["big"]


@pytest.mark.asyncio
async def test_a_residue_space_keeps_its_probe_open(world):
    """Convergence used to be `drift <= 1000`, which marked a quiet space
    carrying a residue as done and stopped probing it for good."""
    world(_World({"quiet": 921}))
    job = M.MaintenanceJob(_Pool())
    await job._run_frame_slot_backfill(["quiet"])
    assert M._probe_unconverged.get(("frame_entity_drift", "quiet")) is True


def test_the_warning_names_the_backfill_when_nothing_is_orphaned():
    """The message recommended the TRUNCATE rebuild for 921 missing rows — an
    outage offered as the fix. It must name the tool that fits."""
    import inspect
    src = inspect.getsource(M.MaintenanceJob._run_frame_slot_integrity)
    assert "backfill_frame_slot_table" in src
    i_zero = src.index('f["orphan_rate"] == 0.0')
    # rindex: the docstring above names the script too, as the orphan repair.
    i_rebuild = src.rindex("migrate_frame_slot_table.py")
    assert i_rebuild > i_zero, (
        "the rebuild must be the ORPHAN branch, not the default advice")
