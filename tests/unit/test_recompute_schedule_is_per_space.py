"""Each space recomputes on its OWN schedule, phase-offset by its space id.

The recompute is a GROUP BY over the whole quad table. Running several at once
is safe for LOCKING — the tables are per-space and TRUNCATE takes its
AccessExclusiveLock on one space only — but they share a buffer cache, and that
is the resource the P1 was about: prod's working set (11.21GB) already exceeds
shared_buffers (7.69GB), so N concurrent full scans evict the read path's cache
N times faster.

The previous shape did at most one space per cycle, which bounded the cost but
made N changed spaces take N cycles and picked the order out of dict iteration.
Independent hash-phased schedules spread the spaces across the interval with no
queue, no coordination and no concurrency limit — and nothing has to know how
many spaces there are.

These tests pin the three properties that makes true: the offset is STABLE
(otherwise restarts re-cluster), it SPREADS (otherwise the offset buys nothing),
and a space stays due until it actually runs (otherwise deferred work is lost).
"""

from __future__ import annotations

import pytest

from vitalgraph.process.maintenance_job import (
    STATS_RECOMPUTE_INTERVAL_S, mark_stats_recompute_done,
    recompute_phase_offset, reset_stats_recompute_schedule,
    stats_recompute_due)

IV = 3600.0
SPACES = [f"space_{i}" for i in range(40)]


@pytest.fixture(autouse=True)
def _clean():
    reset_stats_recompute_schedule()
    yield
    reset_stats_recompute_schedule()


class TestTheOffsetIsStableAndSpread:

    def test_the_offset_does_not_move_between_calls(self):
        """A salted hash would re-cluster the spaces on every restart.

        Python's built-in `hash()` is salted per interpreter (PYTHONHASHSEED),
        so two instances would disagree about the same space and the offsets
        would move on restart — which is the clustering this exists to avoid,
        arriving by another door. This is why the implementation uses blake2b.
        """
        first = [recompute_phase_offset(s, IV) for s in SPACES]
        second = [recompute_phase_offset(s, IV) for s in SPACES]
        assert first == second

    def test_the_offset_is_inside_the_interval(self):
        for s in SPACES:
            off = recompute_phase_offset(s, IV)
            assert 0.0 <= off < IV, f"{s} offset {off} outside [0, {IV})"

    def test_the_offsets_actually_spread(self):
        """The claim the whole design rests on, measured rather than assumed.

        40 spaces over 8 buckets: if the offsets clustered, some bucket would
        hold most of them and the point of phase-offsetting would be lost. A
        uniform hash puts ~5 in each; allowing 1-12 is loose enough not to be a
        flaky test of blake2b's distribution and tight enough to catch a
        constant, a near-constant, or an offset that tracks the name's length.
        """
        buckets = [0] * 8
        for s in SPACES:
            buckets[int(recompute_phase_offset(s, IV) / IV * 8)] += 1
        assert all(1 <= b <= 12 for b in buckets), buckets

    def test_two_spaces_do_not_share_a_slot_boundary(self):
        """Distinct ids should not land on the same instant."""
        offs = [recompute_phase_offset(s, IV) for s in SPACES]
        assert len(set(offs)) == len(offs), "two spaces share an offset exactly"


class TestDueness:

    def test_a_space_is_due_on_first_sight(self):
        """The scheduler says due; `_run_stats_recompute` decides the stagger.

        Kept deliberately: the first-sight policy needs to know whether the
        stats table is EMPTY, which needs a database, so it lives in the job
        rather than in this pure function.
        """
        assert stats_recompute_due("space_0", IV, now=1_000_000.0)

    def test_not_due_again_within_the_interval(self):
        now = 1_000_000.0
        mark_stats_recompute_done("space_0", IV, now=now)
        assert not stats_recompute_due("space_0", IV, now=now + 1)
        assert not stats_recompute_due("space_0", IV, now=now + IV / 4)

    def test_due_again_in_the_next_interval(self):
        now = 1_000_000.0
        mark_stats_recompute_done("space_0", IV, now=now)
        assert stats_recompute_due("space_0", IV, now=now + IV + 1)

    def test_checking_dueness_does_not_consume_it(self):
        """Separate from marking, because a due space can be DEFERRED.

        `STATS_RECOMPUTE_CYCLE_BUDGET_S` can stop a cycle before every due space
        has run. Those must stay due — if merely asking consumed the slot, a
        deferred space would wait a whole interval for work it was already
        scheduled for, and the deferral would silently become a skip.
        """
        now = 1_000_000.0
        assert stats_recompute_due("space_0", IV, now=now)
        assert stats_recompute_due("space_0", IV, now=now)
        assert stats_recompute_due("space_0", IV, now=now)

    def test_one_space_running_does_not_make_another_due(self):
        """Independence. The failure this replaces was a shared queue."""
        now = 1_000_000.0
        for s in SPACES:
            mark_stats_recompute_done(s, IV, now=now)
        mark_stats_recompute_done("space_0", IV, now=now + IV + 1)
        still_waiting = [s for s in SPACES[1:]
                         if not stats_recompute_due(s, IV, now=now + 1)]
        assert len(still_waiting) > 30, (
            "running one space made the others due; the schedules are not "
            "independent")


class TestSpacesDoNotAllRunAtOnce:

    def test_only_a_fraction_is_due_in_any_one_cycle(self):
        """The property that replaces the concurrency limit.

        With 40 spaces spread over a 3600s interval and a 300s cycle, roughly
        40 * 300/3600 ~= 3 should come due per cycle — not 40. Asserting a
        bound rather than a number, because the exact count depends on the hash.
        """
        start = 1_000_000.0
        for s in SPACES:
            mark_stats_recompute_done(s, IV, now=start)

        worst = 0
        for step in range(12):                      # one full interval
            t = start + step * 300.0
            due = [s for s in SPACES if stats_recompute_due(s, IV, now=t)]
            worst = max(worst, len(due))
            for s in due:
                mark_stats_recompute_done(s, IV, now=t)

        assert worst <= 12, (
            f"{worst} of {len(SPACES)} spaces came due in one 300s cycle; the "
            f"phase offsets are not spreading the load")

    def test_every_space_still_runs_within_the_interval(self):
        """Spreading must not mean starving. Coverage is the other half."""
        start = 1_000_000.0
        for s in SPACES:
            mark_stats_recompute_done(s, IV, now=start)

        ran = set()
        for step in range(1, 14):                   # a bit over one interval
            t = start + step * 300.0
            for s in SPACES:
                if stats_recompute_due(s, IV, now=t):
                    mark_stats_recompute_done(s, IV, now=t)
                    ran.add(s)
        assert ran == set(SPACES), f"never ran: {sorted(set(SPACES) - ran)}"


def test_the_shipped_interval_is_long_enough_to_spread():
    """A guard on the default, not on the mechanism.

    If the interval were shortened to the cycle length the offsets would stop
    separating anything — every space would be due every cycle and this would
    be the old behaviour with extra arithmetic.
    """
    assert STATS_RECOMPUTE_INTERVAL_S >= 900, (
        f"interval {STATS_RECOMPUTE_INTERVAL_S}s is close to the 300s cycle, "
        f"so phase offsets cannot spread the spaces apart")


class TestAnExplicitTriggerIsNotDeclinedByTheSchedule:
    """`trigger_maintenance` bypasses freshness checks — the schedule must too.

    The per-space schedule is right for the CYCLE and wrong for an operator who
    names a space: it would decline until that space's next slot, up to an
    interval away, and report nothing. Someone asking for a recompute and
    getting silence has been told the opposite of the truth.

    Checked by source inspection rather than by running a cycle, which needs a
    pool, a database and a scored space list. The property is narrow — the
    trigger passes force, and force skips both gates — and a cheap check that
    names the requirement beats no check.
    """

    def test_the_trigger_map_forces_the_recompute(self):
        import inspect
        from vitalgraph.process.maintenance_job import MaintenanceJob

        src = inspect.getsource(MaintenanceJob.trigger_maintenance)
        assert "force=True" in src, (
            "trigger_maintenance no longer forces the recompute, so an "
            "explicitly triggered space is silently skipped until its next slot")

    def test_force_bypasses_both_the_schedule_and_the_change_gate(self):
        import inspect
        from vitalgraph.process.maintenance_job import MaintenanceJob

        src = inspect.getsource(MaintenanceJob._run_stats_recompute)
        assert "list(space_ids) if force else []" in src, (
            "force no longer bypasses the schedule gate")
        assert "if not force and not await probe_data_changed" in src, (
            "force no longer bypasses the change gate; a triggered space whose "
            "quads have not moved would still be declined")
