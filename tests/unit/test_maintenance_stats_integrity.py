"""MaintenanceJob — the recurring audit for rdf_stats counts.

A wrong count in `rdf_stats` does not produce a wrong answer. It produces a
wrong PLAN, and the query still returns exactly the right rows, just far too
slowly — so nothing about the result reveals it and no test of correctness can
catch it.

`semijoin._selective_enough` divides the probe's match count by the anchor's
candidate count to choose between a per-row probe and a set-based join. On a
5.1M-quad space the anchor pair (rdf:type, KGFrame) was stored as 6 against
60,054 actual, so a query that is genuinely 0.008% selective scored 83% and took
the probe: 60,054 correlated EXISTS evaluations to return 5 rows, 269ms where
the repaired plan is 33ms.

That corruption sat there silently and was found only because someone profiled a
slow endpoint. The detection existed in `scripts/repair_stats_tables.py` but
nothing ran it, which is the difference between "fixed" and "will not recur
unnoticed". This file covers the step that runs it every cycle.

The sampling is deliberate: the largest recorded pairs, not a full recount.
Understatement is what flips the gate and the largest rows are where it shows,
and an exact count on a handful of pairs is one index scan each.
"""

from __future__ import annotations

import asyncio

import pytest

from vitalgraph.process.maintenance_job import MaintenanceJob


class _Conn:
    """A space whose largest recorded pair disagrees with rdf_quad."""

    def __init__(self, stored: int, actual: int, record: list,
                 coverage_gap=None, oversized=None):
        self.stored, self.actual, self.record = stored, actual, record
        # Rows that are PRESENT but above the prune's cap (issues/142). None
        # means the space has none, which is what the other tests need so the
        # sampling path is the one exercised.
        self.oversized = oversized or []
        # The per-predicate coverage audit runs BEFORE the sample (issues/141).
        # None means "every unpruned predicate records all of its quads", which
        # is what these tests need so the SAMPLING path is the one exercised.
        self.coverage_gap = coverage_gap

    async def fetchrow(self, sql, *args):
        return self.coverage_gap

    async def fetch(self, sql, *args):
        if "ORDER BY s.row_count ASC" in sql:      # the oversized probe
            return self.oversized
        if "DELETE" in sql:
            return []
        # The sampled "largest recorded pairs" query.
        return [{"predicate_uuid": "p-uuid", "object_uuid": "o-uuid",
                 "row_count": self.stored}]

    async def fetchval(self, sql, *args):
        # The exact count for the sampled pair.
        return self.actual

    async def execute(self, sql, *args):
        return "OK"

    async def executemany(self, sql, args):
        if "DELETE" in sql:
            self.record.append(("deleted", len(list(args))))
        return "OK"


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        conn = _Conn(self._pool.stored, self._pool.actual, self._pool.record,
                     self._pool.coverage_gap, self._pool.oversized)
        self._pool.handed_out.append(conn)
        return conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, stored, actual, coverage_gap=None, oversized=None):
        self.stored, self.actual = stored, actual
        self.coverage_gap = coverage_gap
        self.oversized = oversized
        self.handed_out, self.record = [], []

    def acquire(self):
        return _Acquire(self)


def _run(job, spaces):
    return asyncio.run(job._run_stats_integrity(spaces))


def test_understated_pair_is_detected_and_rebuilt(monkeypatch):
    """The shape that cost 8x: stored far below actual."""
    rebuilt = []

    async def fake_resync(conn, space_id):
        rebuilt.append(space_id)
        return {"pred_stats": 1, "quad_stats": 1}

    import vitalgraph.db.sparql_sql.sync_stats_tables as sst
    monkeypatch.setattr(sst, "resync_stats_tables", fake_resync)

    job = MaintenanceJob(_Pool(stored=37, actual=304_859))
    result = _run(job, ["some_space"])

    assert result is not None, (
        "a pair stored as 37 against 304,859 actual was not reported — this is "
        "the exact corruption that made the semi-join gate choose a 60,054-row "
        "probe over a set-based join")
    assert result["stored"] == 37 and result["actual"] == 304_859
    assert rebuilt == ["some_space"], "detected the drift but never rebuilt it"


def test_overstated_pair_is_detected(monkeypatch):
    """Deletes that did not decrement. Same check, opposite direction.

    Found on three further host spaces (845 stored against 44 actual). An
    OVERSTATED anchor makes the gate too conservative rather than too eager, so
    it costs a plan rather than an outage — but it is the same broken invariant
    and the same repair, and a check that only looked for understatement would
    call those spaces clean.
    """
    async def fake_resync(conn, space_id):
        return {"pred_stats": 1, "quad_stats": 1}

    import vitalgraph.db.sparql_sql.sync_stats_tables as sst
    monkeypatch.setattr(sst, "resync_stats_tables", fake_resync)

    job = MaintenanceJob(_Pool(stored=845, actual=44))
    result = _run(job, ["some_space"])
    assert result is not None and result["stored"] == 845


def test_agreeing_counts_do_no_work(monkeypatch):
    """A healthy space must not be rebuilt.

    This step runs every cycle, so a check that always fires would resync a
    table per cycle forever — the audit becoming the load it was added to
    protect against.
    """
    rebuilt = []

    async def fake_resync(conn, space_id):
        rebuilt.append(space_id)
        return {}

    import vitalgraph.db.sparql_sql.sync_stats_tables as sst
    monkeypatch.setattr(sst, "resync_stats_tables", fake_resync)

    job = MaintenanceJob(_Pool(stored=1000, actual=1000))
    assert _run(job, ["a", "b", "c"]) is None
    assert not rebuilt


def test_a_failing_space_does_not_abort_the_cycle(monkeypatch):
    """One unreadable space must not cost every step that follows.

    A single `except` wraps the whole maintenance cycle, so an unguarded raise
    here would skip the prune, the histogram refresh, the vector reindex and the
    cleanup — and the completion line would report them as None, which reads
    exactly like a cycle with nothing to do.
    """
    class _Boom:
        def acquire(self):
            raise RuntimeError("no such table")

    job = MaintenanceJob(_Boom())
    assert _run(job, ["gone"]) is None       # must not raise


# ===========================================================================
# The coverage audit — issues/141
# ===========================================================================

def test_unpruned_predicate_missing_its_pairs_is_rebuilt(monkeypatch):
    """An unpruned predicate must record all of its quads.

    `pruned = FALSE` means absence of a pair is evidence of ZERO, so the
    recorded pairs have to sum to the predicate's exact total. Measured on
    production 2026-09-02: `hasKGEntityType` unpruned, 78,993 quads, 92
    recorded — 0.12%. The sampling check could not see it, because the
    corruption makes values LOW and the sample reads the high end.
    """
    from vitalgraph.db.sparql_sql import sync_stats_tables as sst

    async def fake_resync(conn, space_id):
        pool.record.append(space_id)
        return {"pred_stats": 0, "quad_stats": 0}
    monkeypatch.setattr(sst, "resync_stats_tables", fake_resync)

    gap = {"predicate_uuid": "p-uuid", "pred_total": 78_993, "pairs_sum": 92}
    pool = _Pool(stored=1, actual=1, coverage_gap=gap)
    job = MaintenanceJob.__new__(MaintenanceJob)
    job._pool = pool

    result = _run(job, ["sp_test"])

    assert result is not None, "an unpruned predicate at 0.12% coverage was not reported"
    assert result["reason"] == "coverage"
    assert result["pred_total"] == 78_993
    assert result["pairs_sum"] == 92
    assert pool.record == ["sp_test"], "the space should have been resynced"


def test_full_coverage_is_not_reported(monkeypatch):
    """A predicate recording all of its quads must not trigger a rebuild."""
    from vitalgraph.db.sparql_sql import sync_stats_tables as sst

    async def fake_resync(conn, space_id):
        raise AssertionError("a fully covered space must not be rebuilt")
    monkeypatch.setattr(sst, "resync_stats_tables", fake_resync)

    pool = _Pool(stored=5, actual=5, coverage_gap=None)
    job = MaintenanceJob.__new__(MaintenanceJob)
    job._pool = pool

    assert _run(job, ["sp_test"]) is None


# ===========================================================================
# Pairs that must not be PRESENT at all — issues/142
# ===========================================================================

def test_a_present_pair_above_the_cap_is_removed(monkeypatch):
    """`pruned` licenses ABSENCE, not WRONGNESS.

    A pair whose true count exceeds STATS_MAX_ROW_COUNT is evicted by the prune
    and never written by the resync, so absence IS its correct state — readers
    fall through to the bounded count, which saturates, and the semi-join gate
    declines. Present-and-low is the one state that is never right, and the
    flag cannot help: the writer takes the UPDATE-only path and faithfully
    increments a row that should not exist.

    Measured on production 2026-09-02: `(vitaltype, Edge_hasKGSlot)` recorded
    1,503 against 2,729,244 actual, with `pruned = true`. Understated 1,800x
    and read by the join reorder as a rare leaf.
    """
    from vitalgraph.db.sparql_sql import sync_stats_tables as sst

    async def fake_resync(conn, space_id):
        raise AssertionError("a resync cannot fix this — it never writes the pair")
    monkeypatch.setattr(sst, "resync_stats_tables", fake_resync)

    pool = _Pool(stored=1, actual=1, oversized=[
        {"predicate_uuid": "vitaltype", "object_uuid": "Edge_hasKGSlot",
         "row_count": 1503, "actual": 2_729_244},
        {"predicate_uuid": "vitaltype", "object_uuid": "small",
         "row_count": 2, "actual": 2},          # correct, must be left alone
    ])
    job = MaintenanceJob.__new__(MaintenanceJob)
    job._pool = pool

    result = _run(job, ["sp_test"])

    assert result is not None, "a pair 1,800x understated was not reported"
    assert result["reason"] == "oversized"
    assert result["removed"] == 1, "only the oversized pair should be removed"
    assert result["worst_actual"] == 2_729_244
    assert ("deleted", 1) in pool.record


def test_a_correctly_sized_present_pair_is_left_alone():
    """The probe samples LOW recorded values, most of which are simply small.

    Deleting those would destroy the statistics the reorder depends on, so the
    actual count is what decides — not the recorded one.
    """
    pool = _Pool(stored=1, actual=1, oversized=[
        {"predicate_uuid": "p", "object_uuid": "o", "row_count": 2, "actual": 2},
    ])
    job = MaintenanceJob.__new__(MaintenanceJob)
    job._pool = pool

    assert _run(job, ["sp_test"]) is None
    assert not any(r[0] == "deleted" for r in pool.record if isinstance(r, tuple))
