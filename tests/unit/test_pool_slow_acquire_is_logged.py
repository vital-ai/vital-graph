"""A pool acquire that WAITS and then succeeds must say so.

Production, 2026-09-08: one `GET kgentities` measured 39.972s inside a calling
service while the calls either side of it — same endpoint, same client process,
milliseconds apart — took 0.020-0.092s. Nothing anywhere attributed
it. The pool's only diagnostic fired on `TimeoutError`, so starvation that
eventually resolved was invisible, and four separate hypotheses were chased
and disproved before the log line that mattered was found by accident.

A slow success and a timeout are the same starvation. Only one was logged.

Asserted against a stub context rather than a live pool: the behaviour under
test is "did it time the wait and report it", which needs no database.
"""

from __future__ import annotations

import asyncio
import logging

import pytest


class _StubCtx:
    """Stands in for asyncpg's PoolAcquireContext, with a controllable delay."""

    def __init__(self, delay: float, fail: bool = False):
        self._delay, self._fail = delay, fail

    async def __aenter__(self):
        await asyncio.sleep(self._delay)
        if self._fail:
            raise asyncio.TimeoutError()
        return "conn"

    async def __aexit__(self, *exc):
        return False

    def __await__(self):
        async def _run():
            return await self.__aenter__()
        return _run().__await__()


class _StubPool:
    def get_size(self): return 30
    def get_idle_size(self): return 0
    def get_min_size(self): return 10
    def get_max_size(self): return 30


def _ctx(delay, fail=False):
    from vitalgraph.db.pool import _LoggingAcquireContext
    return _LoggingAcquireContext(_StubPool(), _StubCtx(delay, fail))


@pytest.mark.asyncio
async def test_a_slow_acquire_is_reported(caplog, monkeypatch):
    import vitalgraph.db.pool as pool_mod
    monkeypatch.setattr(pool_mod, "SLOW_ACQUIRE_SECONDS", 0.05)

    with caplog.at_level(logging.WARNING, logger="vitalgraph.db.pool"):
        async with _ctx(0.12) as conn:
            assert conn == "conn"

    msgs = [r.getMessage() for r in caplog.records]
    assert any("acquire WAITED" in m for m in msgs), (
        f"a 0.12s wait that SUCCEEDED was not reported; that silence is why a "
        f"39.97s production request could not be attributed. records={msgs}")
    assert any("idle=0" in m for m in msgs), (
        f"pool occupancy is not in the message, so the log cannot show WHY it "
        f"waited: {msgs}")


@pytest.mark.asyncio
async def test_a_fast_acquire_stays_quiet(caplog, monkeypatch):
    """It must not log on the normal path — this runs on every query."""
    import vitalgraph.db.pool as pool_mod
    monkeypatch.setattr(pool_mod, "SLOW_ACQUIRE_SECONDS", 1.0)

    with caplog.at_level(logging.WARNING, logger="vitalgraph.db.pool"):
        async with _ctx(0.0):
            pass

    assert not [r for r in caplog.records if "acquire WAITED" in r.getMessage()], (
        "a fast acquire logged; this path runs on every single query")


@pytest.mark.asyncio
async def test_the_bare_await_form_is_covered_too(caplog, monkeypatch):
    """asyncpg allows `conn = await pool.acquire()`; both forms must report."""
    import vitalgraph.db.pool as pool_mod
    monkeypatch.setattr(pool_mod, "SLOW_ACQUIRE_SECONDS", 0.05)

    with caplog.at_level(logging.WARNING, logger="vitalgraph.db.pool"):
        conn = await _ctx(0.12)
        assert conn == "conn"

    assert any("acquire WAITED" in r.getMessage() for r in caplog.records), (
        "the `await pool.acquire()` form does not report a slow wait")


@pytest.mark.asyncio
async def test_a_timeout_still_reports_pool_state(caplog, monkeypatch):
    """The original diagnostic must survive the change."""
    with caplog.at_level(logging.WARNING, logger="vitalgraph.db.pool"):
        with pytest.raises(asyncio.TimeoutError):
            async with _ctx(0.0, fail=True):
                pass

    assert any("acquire timed out" in r.getMessage() for r in caplog.records)
