"""MaintenanceJob — the released-connection bug in `_run_edge_integrity`.

Seen in the app log as, every cycle:

    MaintenanceJob cycle error: cannot call Connection.fetchval():
    connection has been released back to the pool

The `has_vitaltype` probe used `conn` from an `async with pool.acquire()` block
that had already exited. `EDGE_UNTYPED_WARN_PCT` is 0.01, so any space with 1%
untyped edge rows reached it — which is the normal state of a table whose
`edge_type_uuid` column was added by a migration and not yet backfilled.

WHY IT MATTERED MORE THAN ONE FAILED CHECK: a single `except` wraps the whole
cycle, so the raise skipped every remaining step — edge integrity, frame-entity
integrity, stats prune, vector reindex, cleanup. The completion line then
reported those untouched steps as None/False, which reads exactly like a cycle
with nothing to do. The job looked healthy while doing almost none of its work.
"""

from __future__ import annotations

import asyncio

import pytest

from vitalgraph.process.maintenance_job import MaintenanceJob


class _Conn:
    """Raises like asyncpg does once the pool has taken the connection back."""

    def __init__(self):
        self.released = False
        self.calls = 0

    async def fetchval(self, *args, **kwargs):
        if self.released:
            raise RuntimeError(
                "cannot call Connection.fetchval(): connection has been "
                "released back to the pool")
        self.calls += 1
        return True                      # the space DOES carry vitaltype

    async def fetch(self, *args, **kwargs):
        return []

    async def execute(self, *args, **kwargs):
        return "OK"


class _Acquire:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        conn = _Conn()
        self._pool.handed_out.append(conn)
        self._conn = conn
        return conn

    async def __aexit__(self, *exc):
        self._conn.released = True       # exactly what the real pool does
        return False


class _Pool:
    def __init__(self):
        self.handed_out = []

    def acquire(self):
        return _Acquire(self)


def test_vitaltype_probe_does_not_reuse_a_released_connection(monkeypatch):
    """The probe must run on a connection the pool still considers ours."""
    pool = _Pool()
    job = MaintenanceJob(pool)

    async def fake_drift(conn, space_id):
        return (10_000, 10_000)          # counts agree — no drift

    async def fake_orphan(conn, space_id):
        return 0.0                       # not stale

    async def fake_untyped(conn, space_id):
        return 0.5                       # 50% untyped: over the 1% threshold

    import vitalgraph.db.sparql_sql.sync_edge_table as sync
    monkeypatch.setattr(sync, "edge_table_drift", fake_drift)
    monkeypatch.setattr(sync, "edge_table_orphan_rate", fake_orphan)
    monkeypatch.setattr(sync, "edge_table_untyped_rate", fake_untyped)

    # Must not raise. Before the fix this was InterfaceError-equivalent.
    asyncio.run(job._run_edge_integrity(["some_space"]))

    probed = [c for c in pool.handed_out if c.calls > 0]
    assert probed, "the vitaltype probe never ran"
    for conn in probed:
        assert not conn.released or conn.calls > 0


def test_an_aborted_cycle_is_not_logged_as_a_clean_one(caplog):
    """A cycle that dies partway must not read like a quiet one.

    This is the reason the bug survived: the summary line printed
    `vector_reindex=None cleanup=False` for steps that never ran.
    """
    pool = _Pool()
    job = MaintenanceJob(pool)

    async def boom():
        raise RuntimeError("connection has been released back to the pool")

    job._fetch_space_stats = boom

    with caplog.at_level("INFO"):
        summary = asyncio.run(job.run())

    assert summary["aborted"], "an aborted cycle did not record why"
    text = caplog.text
    assert "ABORTED" in text, "the failure is not visible in the cycle log line"
    assert "cycle complete" not in text, \
        "an aborted cycle still reported itself complete"
