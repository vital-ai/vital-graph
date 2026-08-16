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

    def __init__(self, stored: int, actual: int, record: list):
        self.stored, self.actual, self.record = stored, actual, record

    async def fetch(self, sql, *args):
        # The sampled "largest recorded pairs" query.
        return [{"predicate_uuid": "p-uuid", "object_uuid": "o-uuid",
                 "row_count": self.stored}]

    async def fetchval(self, sql, *args):
        # The exact count for the sampled pair.
        return self.actual

    async def execute(self, sql, *args):
        return "OK"


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        conn = _Conn(self._pool.stored, self._pool.actual, self._pool.record)
        self._pool.handed_out.append(conn)
        return conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, stored, actual):
        self.stored, self.actual = stored, actual
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
