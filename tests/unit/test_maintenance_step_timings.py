"""issues/353: the cycle line carries per-step timings.

Before this, the completion line logged only the cycle total, so where a
production cycle's time went had to be found by sampling `pg_stat_activity`
against production for 26 minutes (`issues/349`).
"""

from __future__ import annotations

import asyncio

import pytest

from vitalgraph.process import maintenance_job as M
from vitalgraph.process.maintenance_job import MaintenanceJob, format_step_timings

# Every step `run()` awaits, with the fake seconds it takes.
STEP_COST = {
    "_run_analyze": 3.0,
    "_run_vacuum": 0.0,
    "_run_edge_integrity": 23.0,
    "_run_edge_type_reconcile": 0.01,
    "_run_frame_slot_integrity": 8.0,
    "_run_frame_slot_backfill": 0.2,
    "_run_entity_slot_sort_integrity": 98.0,
    "_run_grouping_self_link_check": 0.0,
    "_run_graph_registration_check": 0.0,
    "_run_space_index_check": 0.0,
    "_run_edge_fanout_refresh": 0.0,
    "_run_type_agreement_refresh": 0.0,
    "_run_pattern_verdict_refresh": 0.0,
    "_run_stats_recompute": 151.0,
    "_run_value_stats_refresh": 0.0,
    "_run_vector_reindex": 0.0,
}


@pytest.fixture
def rig(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(M, "_step_clock", lambda: clock["now"])
    job = MaintenanceJob.__new__(MaintenanceJob)

    async def stats():
        return {"sp_a": {"n_mod_since_analyze": 1, "n_dead_tup": 0}}
    job._fetch_space_stats = stats
    job._pick_worst_for_analyze = lambda s: "sp_a"
    job._pick_worst_for_vacuum = lambda s: None
    job._should_cleanup = lambda: False

    def make(cost, fail=False):
        async def step(*a, **k):
            clock["now"] += cost
            if fail:
                raise RuntimeError("step failed")
            return None
        return step
    for name, cost in STEP_COST.items():
        setattr(job, name, make(cost))
    return job, make


def test_every_step_is_timed_and_the_slow_ones_logged(rig, caplog):
    job, _ = rig
    with caplog.at_level("INFO"):
        summary = asyncio.run(job.run())

    t = summary["step_timings"]
    assert t["entity_slot_sort_integrity"] == pytest.approx(98.0)
    assert t["stats_recompute"] == pytest.approx(151.0)
    assert t["analyze(sp_a)"] == pytest.approx(3.0)       # names the space
    assert "vacuum(None)" not in t                         # not run, not listed
    line = next(r.getMessage() for r in caplog.records
                if "cycle complete" in r.getMessage())
    steps = line.split("steps=")[1]
    # Slowest first, under-threshold steps only counted.
    assert steps.startswith("stats_recompute:151.0s,entity_slot_sort_integrity:98.0s,"
                            "edge_integrity:23.0s,frame_slot_integrity:8.0s,analyze(sp_a):3.0s,")
    assert "edge_type_reconcile" not in steps
    assert steps.endswith("under 1s")


def test_an_aborted_cycle_reports_the_steps_that_ran_including_the_failing_one(rig, caplog):
    job, make = rig
    job._run_frame_slot_integrity = make(8.0, fail=True)
    with caplog.at_level("INFO"):
        summary = asyncio.run(job.run())

    assert summary["aborted"]
    t = summary["step_timings"]
    assert t["frame_slot_integrity"] == pytest.approx(8.0)   # the one that raised
    assert "entity_slot_sort_integrity" not in t             # never reached
    line = next(r.getMessage() for r in caplog.records if "ABORTED" in r.getMessage())
    assert "frame_slot_integrity:8.0s" in line


def test_format_step_timings():
    assert format_step_timings({}, 1) == "none"
    assert format_step_timings({"a": 0.2, "b": 0.3}, 1) == "+2 under 1s"
    assert format_step_timings({"a": 2.0, "b": 5.25, "c": 0.1}, 1) == "b:5.2s,a:2.0s,+1 under 1s"
    assert format_step_timings({"a": 1.0}, 1) == "a:1.0s"            # at threshold: listed
