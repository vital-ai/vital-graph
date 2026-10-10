"""Integration: with N instances, the maintenance job runs once per interval.

`issues/264`. The scheduler took an advisory lock per CYCLE and released it
afterwards. That stops two instances running a cycle at the same moment, but
each instance still runs on its own clock, so production's two tasks took turns
and ran every maintenance step twice as often as configured: ANALYZE 216 vs
215, VACUUM 10 vs 11, stats recompute 199 vs 197, cycles 3,186 vs 3,188 over
2026-10-02..09.

A `single_runner` job keeps its lock between cycles. These tests use two real
`ProcessScheduler`s — two lock connections, as two ECS tasks would have — against
the test database, and drive `_run_once` directly so the interleaving is exact.
"""

from __future__ import annotations

import uuid

import pytest

from vitalgraph.process.process_lock_manager import process_lock_key
from vitalgraph.process.process_scheduler import ProcessScheduler

from .conftest import PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER, skip_no_infra

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

PG_CONFIG = dict(host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
                 username=PG_USER, password=PG_PASSWORD)


class _Counter:
    def __init__(self):
        self.runs = 0

    async def run(self):
        self.runs += 1


async def _instance(job_name: str, single_runner: bool):
    s = ProcessScheduler(None, PG_CONFIG)
    h = _Counter()
    s.register_job(job_name, 300, h, process_type="itest",
                   single_runner=single_runner)
    await s._lock_manager.connect()
    return s, h, s._jobs[job_name]


async def _hold_count(pg_conn, job_name: str) -> int:
    """How many times the lock is held, summed over sessions (re-entrancy shows
    up as a count above 1 on one session)."""
    key = process_lock_key("itest", job_name)
    classid, objid = (key >> 32) & 0xFFFFFFFF, key & 0xFFFFFFFF
    return await pg_conn.fetchval(
        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
        "AND classid::bigint = $1 AND objid::bigint = $2 AND granted",
        classid, objid)


async def test_one_instance_runs_every_cycle_and_the_other_none(pg_conn):
    name = f"single_{uuid.uuid4().hex[:8]}"
    a, ha, ja = await _instance(name, single_runner=True)
    b, hb, jb = await _instance(name, single_runner=True)
    try:
        for _ in range(5):              # the two tasks' cycles, interleaved
            await a._run_once(ja)
            await b._run_once(jb)
        assert (ha.runs, hb.runs) == (5, 0), (
            f"runs were {ha.runs} and {hb.runs}: with a single runner one "
            f"instance does every cycle and the other skips (issues/264)")
        assert await _hold_count(pg_conn, name) == 1, (
            "the runner re-acquired its own lock each cycle and stacked holds; "
            "advisory locks are re-entrant per session")
    finally:
        await a._lock_manager.disconnect()
        await b._lock_manager.disconnect()


async def test_the_other_instance_takes_over_when_the_runner_stops(pg_conn):
    name = f"failover_{uuid.uuid4().hex[:8]}"
    a, ha, ja = await _instance(name, single_runner=True)
    b, hb, jb = await _instance(name, single_runner=True)
    try:
        await a._run_once(ja)
        await b._run_once(jb)
        assert (ha.runs, hb.runs) == (1, 0)

        await a._lock_manager.disconnect()     # the runner's task stops
        await b._run_once(jb)
        await b._run_once(jb)
        assert hb.runs == 2, "the standby never took over after the runner stopped"
    finally:
        await a._lock_manager.disconnect()
        await b._lock_manager.disconnect()


async def test_a_dead_lock_connection_is_not_mistaken_for_holding_it(pg_conn):
    """If the runner's lock connection dies, the server has released the lock,
    possibly to another instance; the runner must not carry on as if it held it."""
    name = f"deadconn_{uuid.uuid4().hex[:8]}"
    a, ha, ja = await _instance(name, single_runner=True)
    b, hb, jb = await _instance(name, single_runner=True)
    try:
        await a._run_once(ja)
        pid = await a._lock_manager._conn.fetchval("SELECT pg_backend_pid()")
        await pg_conn.execute("SELECT pg_terminate_backend($1)", pid)

        await b._run_once(jb)                  # b takes the released lock
        await a._run_once(ja)                  # a must notice it lost it
        assert hb.runs == 1
        assert ha.runs == 1, (
            "the runner kept running after its lock connection died, so two "
            "instances ran the job at once")
    finally:
        await a._lock_manager.disconnect()
        await b._lock_manager.disconnect()


async def test_an_ordinary_job_still_takes_turns(pg_conn):
    """Unchanged behaviour for jobs that did not opt in."""
    name = f"turns_{uuid.uuid4().hex[:8]}"
    a, ha, ja = await _instance(name, single_runner=False)
    b, hb, jb = await _instance(name, single_runner=False)
    try:
        for _ in range(3):
            await a._run_once(ja)
            await b._run_once(jb)
        assert (ha.runs, hb.runs) == (3, 3)
        assert await _hold_count(pg_conn, name) == 0
    finally:
        await a._lock_manager.disconnect()
        await b._lock_manager.disconnect()
