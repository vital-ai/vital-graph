"""The write gate holds opted-in probes for a minimum interval per space.

`issues/349`. `343`'s gate re-derives a probe whenever the space's quads changed since
it last ran. Production's main KG space is written continuously, so that was true every
cycle there and its 98-248 s slot-sort split still ran every cycle. Maintenance
statements were 69 % of wall-clock in a sampled production cycle, these probes ~62 % of
that.

These drive `probe_data_changed` directly with a fake clock and a fake watermark.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import pytest

from vitalgraph.process import maintenance_job as M


class _Conn:
    def __init__(self, st):
        self.st = st

    async def fetchval(self, *_a, **_k):
        if isinstance(self.st["wm"], Exception):
            raise self.st["wm"]
        return self.st["wm"]


@pytest.fixture
def st(monkeypatch):
    M.reset_probe_gate()
    state = {"wm": 100, "now": 1000.0}
    monkeypatch.setattr(M, "_probe_clock", lambda: state["now"])
    monkeypatch.setattr(M, "PROBE_MIN_INTERVAL_S", 3600.0)
    yield state
    M.reset_probe_gate()


async def _gate(st, probe, space="sp"):
    return await M.probe_data_changed(_Conn(st), space, probe)


def test_the_opted_in_probes_are_the_ones_that_only_warn_or_repair():
    assert M.INTERVAL_GATED_PROBES == {
        "entity_slot_sort_row_shortfall", "edge_table_drift",
        "frame_slot_integrity", "frame_entity_drift"}
    # Read-path markers and blocks; delaying it can serve a fast path on stale coverage.
    assert "entity_slot_sort_coverage" not in M.INTERVAL_GATED_PROBES
    # Has its own per-space schedule.
    assert "stats_recompute" not in M.INTERVAL_GATED_PROBES


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", sorted(M.INTERVAL_GATED_PROBES))
async def test_a_write_inside_the_interval_waits_for_it(st, probe):
    assert await _gate(st, probe)               # first sight runs
    st["wm"] += 1
    st["now"] += 3599
    assert not await _gate(st, probe)           # written, but inside the interval
    st["now"] += 1
    assert await _gate(st, probe)               # the write made during it still counts


@pytest.mark.asyncio
async def test_no_write_means_no_run_even_after_the_interval(st):
    p = "edge_table_drift"
    assert await _gate(st, p)
    st["now"] += 10 * 3600
    assert not await _gate(st, p)


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", ["entity_slot_sort_coverage", "stats_recompute"])
async def test_probes_not_opted_in_still_reopen_on_any_write(st, probe):
    assert await _gate(st, probe)
    st["wm"] += 1
    st["now"] += 1
    assert await _gate(st, probe)


@pytest.mark.asyncio
async def test_unconverged_work_still_runs_inside_the_interval(st):
    p = "frame_entity_drift"
    assert await _gate(st, p)
    M.mark_probe_converged("sp", p, False)      # the pass repaired rows, or failed
    st["now"] += 1
    assert await _gate(st, p)
    M.mark_probe_converged("sp", p, True)
    st["wm"] += 1
    st["now"] += 1
    assert not await _gate(st, p), "the interval runs from the last pass, converged or not"


@pytest.mark.asyncio
async def test_the_interval_is_per_space(st):
    p = "entity_slot_sort_row_shortfall"
    assert await _gate(st, p, "a")
    st["wm"] += 1
    assert await _gate(st, p, "b")
    assert not await _gate(st, p, "a")


@pytest.mark.asyncio
async def test_zero_turns_the_interval_off(st, monkeypatch):
    monkeypatch.setattr(M, "PROBE_MIN_INTERVAL_S", 0.0)
    p = "edge_table_drift"
    assert await _gate(st, p)
    st["wm"] += 1
    assert await _gate(st, p)                   # `343` behaviour exactly


@pytest.mark.asyncio
async def test_an_unreadable_watermark_still_runs_outside_the_interval(st):
    p = "frame_slot_integrity"
    st["wm"] = RuntimeError("stats unreadable")
    assert await _gate(st, p)
    st["now"] += 1
    assert not await _gate(st, p), "an unreadable counter must not defeat the interval"
    st["now"] += 3600
    assert await _gate(st, p)


def test_the_default_interval_is_six_hours():
    # From the source, not a reload: reloading the module would hand later tests
    # new classes and functions that their imports do not see.
    import inspect
    src = inspect.getsource(M)
    assert 'os.getenv("VG_MAINTENANCE_PROBE_MIN_INTERVAL_S", "21600")' in src
