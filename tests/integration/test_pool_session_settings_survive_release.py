"""Session settings a pool SETs hold on every acquire, not only the first.

Settings moved from asyncpg's startup `server_settings` to a `SET` in the
pool's `init=`, because PgBouncer refuses startup parameters it does not
track. But asyncpg resets a connection on release, and the default reset
ends in `RESET ALL`, which discards a `SET`: the export's statement timeout
held on the first acquire and fell back to the role's on the next, even on a
direct connection. `pool.reset_then(settings_sql)` sends the default reset
query and the settings in one round trip. A custom `reset=` REPLACES the
default one, so the test also checks that the default reset's work is still
done.

One connection per pool, so every acquire is the same backend.
"""

from __future__ import annotations

import asyncpg
import pytest

from vitalgraph.cmd.vitalgraph_export_cmd import _session_settings_sql
from vitalgraph.db.pool import reset_then

from .conftest import HAS_PG, PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_PG, reason="Requires PostgreSQL"),
]


_SQL = _session_settings_sql("1234ms", "7min")


async def _settings(conn):
    await conn.execute(_SQL())


async def _pool(init=_settings, **extra):
    return await asyncpg.create_pool(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE, user=PG_USER,
        password=PG_PASSWORD, min_size=1, max_size=1, init=init, **extra)


async def _show(conn):
    return (await conn.fetchval("SELECT pg_backend_pid()"),
            await conn.fetchval("SHOW statement_timeout"),
            await conn.fetchval("SHOW idle_in_transaction_session_timeout"))


@pytest.mark.asyncio(loop_scope="session")
async def test_settings_hold_after_release():
    pool = await _pool(reset=reset_then(_SQL))
    try:
        seen = []
        for _ in range(3):
            async with pool.acquire() as conn:
                seen.append(await _show(conn))
        assert len({pid for pid, *_ in seen}) == 1, "one backend throughout"
        assert [s[1:] for s in seen] == [("1234ms", "7min")] * 3
    finally:
        await pool.close()


@pytest.mark.asyncio(loop_scope="session")
async def test_the_default_reset_still_runs():
    pool = await _pool(reset=reset_then(_SQL))
    try:
        async with pool.acquire() as conn:
            default_work_mem = await conn.fetchval("SHOW work_mem")
            await conn.execute("LISTEN pool_reset_check")
            await conn.execute("SELECT pg_advisory_lock(424242)")
            await conn.execute("SET work_mem = '77MB'")
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM pg_listening_channels()") == 0
            assert await conn.fetchval(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                "AND pid = pg_backend_pid()") == 0
            assert await conn.fetchval("SHOW work_mem") == default_work_mem
    finally:
        await pool.close()


@pytest.mark.asyncio(loop_scope="session")
async def test_without_it_the_settings_are_lost():
    """The control: init alone keeps them for the first acquire only."""
    pool = await _pool()
    try:
        async with pool.acquire() as conn:
            first = await _show(conn)
        async with pool.acquire() as conn:
            second = await _show(conn)
        assert first[0] == second[0]
        assert first[1:] == ("1234ms", "7min")
        assert second[1:] != ("1234ms", "7min")
    finally:
        await pool.close()


@pytest.mark.asyncio(loop_scope="session")
async def test_request_pool_lock_timeout_holds(monkeypatch):
    """The app's request pool, with its own init and reset."""
    from vitalgraph.db.sparql_sql import sparql_sql_db_impl as D
    monkeypatch.setattr(D, "_request_lock_timeout_s", lambda: 7)
    pool = await _pool(init=D._init_request_conn,
                       reset=reset_then(D._request_conn_settings_sql))
    try:
        seen = []
        for _ in range(3):
            async with pool.acquire() as conn:
                seen.append((await conn.fetchval("SELECT pg_backend_pid()"),
                             await conn.fetchval("SHOW lock_timeout")))
        assert len({pid for pid, _ in seen}) == 1
        assert [lt for _, lt in seen] == ["7s"] * 3
    finally:
        await pool.close()
