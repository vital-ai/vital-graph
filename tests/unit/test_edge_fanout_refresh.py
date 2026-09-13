"""`edge_fanout` must be refreshed, and an EMPTY table must not read as safe.

The table is consumed on the query path: `generator.py` loads it and
`emit_slice` asks `assess_traversal` whether a two-phase probe's traversal
amplifies. Measured across the whole query tier it is consulted 61 times and
declines 2 of them ("hop tail 468 exceeds 16 — this direction fans out"), so a
stale or absent value is a WRONG PLAN rather than a missed optimisation.

Nothing refreshed it periodically. `compute_edge_fanout` had one caller,
`resync_all`, reached only from an admin resync, a data import or the bulk
loader — so ordinary CRUD drifted it with nothing to notice. Its own docstring
says a periodic recompute is enough and rejects incremental maintenance,
because it records avg/p99/max per bucket and keeping that current under every
write means maintaining a DISTRIBUTION on the write path.

The empty case is the one that bites: `emit_slice` guards with `if fanout:`, so
zero rows skips the check for every query, silently. Found on
`sp_lead_synth_100k` — 4,977,000 typed edges and no fan-out rows at all.
"""
from __future__ import annotations

import inspect

from vitalgraph.process import maintenance_job as M


class TestTheSchedule:

    def test_it_has_its_own_slot(self):
        """Sharing the stats slot would let one starve the other: whichever ran
        first would mark the interval consumed for both."""
        M._edge_fanout_slot.clear()
        M._recompute_slot.clear()
        M.mark_edge_fanout_done("sp_x")
        assert "sp_x" in M._edge_fanout_slot, "its own slot was not recorded"
        assert "sp_x" not in M._recompute_slot, "it consumed the stats slot"
        assert M.stats_recompute_due("sp_x"), (
            "marking edge_fanout done must not make a stats recompute look "
            "already handled — one would starve the other")

    def test_due_then_not_due_then_due_again(self):
        M._edge_fanout_slot.clear()
        iv, t = 100.0, 1_000_000.0
        assert M.edge_fanout_due("sp_y", iv, t), "never run must be due"
        M.mark_edge_fanout_done("sp_y", iv, t)
        assert not M.edge_fanout_due("sp_y", iv, t)
        assert M.edge_fanout_due("sp_y", iv, t + 2 * iv), "a later interval is due"

    def test_spaces_are_phase_offset(self):
        """Spaces spread across the interval instead of queueing behind each
        other, which is the point of the offset in the stats schedule too."""
        iv = 3600.0
        offsets = {M.recompute_phase_offset(f"sp_{i}", iv) for i in range(12)}
        assert len(offsets) > 6, "offsets collapsed — spaces would run together"


class TestItIsWired:

    def test_the_cycle_runs_it(self):
        src = inspect.getsource(M.MaintenanceJob)
        assert "_run_edge_fanout_refresh" in src
        assert "edge_fanout_refresh" in src, "not reported in the summary"

    def test_an_explicit_trigger_forces_past_the_schedule(self):
        """A user asking for maintenance on one space must not be told 'not due'."""
        src = inspect.getsource(M.MaintenanceJob)
        i = src.index('("edge_fanout_refresh"')
        assert "force=True" in src[i:i + 200], (
            "the per-space trigger must force, like stats_recompute does")


class TestTheEmptyCase:

    def test_empty_is_repaired_regardless_of_schedule(self):
        """Zero rows disables the guard silently, so it cannot wait for a slot."""
        src = inspect.getsource(M.MaintenanceJob._run_edge_fanout_refresh)
        assert 'reason = "empty"' in src
        # the empty branch must be tested BEFORE the schedule branch
        assert src.index('reason = "empty"') < src.index('reason = "due"')

    def test_a_space_with_no_typed_edges_is_left_alone(self):
        """Zero rows is the RIGHT answer where there is nothing to measure, and
        flagging it would queue a rebuild that can never converge."""
        src = inspect.getsource(M.MaintenanceJob._run_edge_fanout_refresh)
        assert "has_edges" in src
        assert "empty and has_edges" in src

    def test_it_warns_rather_than_repairing_quietly(self):
        src = inspect.getsource(M.MaintenanceJob._run_edge_fanout_refresh)
        assert "logger.warning" in src, (
            "a space that was running unguarded should say so")
