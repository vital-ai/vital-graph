"""Read-only watches come off the five-minute repair loop.

`issues/143`. Measured on prod over 46 minutes, the maintenance job was 87% of
all slow database time and 38% of wall-clock -- ~115s of sequential scans inside
every 300s cycle on a 4 vCPU box. Two of those are pure watches: they write
nothing, they only log, and they re-derive from the whole table every cycle.

    grouping self-link (typeless probe)   38.6s max, ~35s/cycle across spaces
    graph registration                    same shape

The cost is not only CPU. They scan the quad table and evict the buffer cache
the read path depends on, which is why the same listing query measured 1,216ms
and 11,187ms an hour apart.

These pin the two properties that make slowing them safe: repairs are NOT
slowed, and a restart still gets a full sweep.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import inspect

import pytest

from vitalgraph.process import maintenance_job as M


@pytest.fixture(autouse=True)
def _clean():
    M.reset_watch_schedule()
    yield
    M.reset_watch_schedule()


def test_a_watch_runs_once_then_waits():
    assert M.should_run_watch("w", "sp") is True
    assert M.should_run_watch("w", "sp") is False, "would be every 300s again"
    assert M.should_run_watch("w", "sp", now=1e9) is True


def test_spaces_are_independent_so_cost_spreads_across_cycles():
    """One space being due must not drag the others along -- that would restore
    the spike this change exists to remove, just less often."""
    assert M.should_run_watch("w", "a") is True
    assert M.should_run_watch("w", "b") is True
    assert M.should_run_watch("w", "a") is False
    assert M.should_run_watch("w", "b") is False


def test_watches_do_not_share_a_schedule():
    assert M.should_run_watch("self_link", "sp") is True
    assert M.should_run_watch("graph_reg", "sp") is True, "different watch"


def test_a_restart_gets_a_full_sweep():
    """The schedule is per-process. A fresh deploy must still report everything
    once, or a real finding could hide for an hour after the change that caused
    it."""
    assert M.should_run_watch("w", "sp") is True
    M.reset_watch_schedule()
    assert M.should_run_watch("w", "sp") is True


def test_the_interval_is_far_above_the_cycle():
    """Gating at less than the 300s cycle would be a no-op."""
    assert M.WATCH_INTERVAL_S >= 1800, (
        "at 35s/cycle the point is to amortise it; a short interval does not")


def test_only_the_read_only_checks_are_gated():
    """The gate must not reach a step that REPAIRS. Delaying a repair delays a
    fix; delaying a watch delays a log line."""
    src = inspect.getsource(M)
    gated = {n for n in ("grouping_self_link", "graph_registration",
                         "edge_integrity", "frame_entity_integrity",
                         "entity_slot_sort_integrity", "stats_integrity")
             if f'should_run_watch("{n}"' in src}
    assert gated == {"grouping_self_link", "graph_registration"}, (
        f"gated {gated}; only the two write-nothing watches may be slowed")


@pytest.mark.parametrize("fn", ["_run_grouping_self_link_check",
                                "_run_graph_registration_check"])
def test_the_gated_checks_still_write_nothing(fn):
    """If one of these ever grows a repair, gating it becomes wrong and this
    fails rather than silently delaying the fix."""
    body = inspect.getsource(getattr(M.MaintenanceJob, fn))
    for verb in ("UPDATE ", "INSERT ", "DELETE ", "TRUNCATE "):
        assert verb not in body, (
            f"{fn} now writes ({verb.strip()}) — it is a repair, so it must "
            f"come off the watch schedule")
