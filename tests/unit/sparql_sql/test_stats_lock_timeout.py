"""Stats reads must not park behind the maintenance job's rebuild.

`issues/145`. The read path consults `{space}_rdf_stats` / `_rdf_pred_stats` to
feed the join-reorder heuristic, the semi-join gate and the slot-type tautology
check. The maintenance rebuild TRUNCATEs those tables, which takes an
AccessExclusiveLock held until its transaction commits — and that transaction
used to span an aggregate over the whole quad table.

Measured on prod: two such reads each waited the pool-wide `lock_timeout` of
10s and then failed, so a request whose SQL took 1,851 ms was reported by the
endpoint as 21,980 ms and planned without stats anyway. Sampling `pg_locks`
during a rebuild caught 144 blocked-reader samples over ~60 continuous seconds.

The contract these tests pin:

1. every stats read bounds its lock wait (they are plan INPUTS, not answers);
2. a transient failure does not get memoised into the stats cache, because
   failing faster makes an unlucky window likelier, and a poisoned cache would
   plan every later query for that space without stats.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import asyncpg
import pytest

from vitalgraph.db.sparql_sql import db_provider, generator as G


class _RecordingConn:
    """Records the statements issued, and whether a transaction was opened."""

    def __init__(self, rows=None, raise_on_fetch=None, lock_timeout="10s"):
        self.statements: list[str] = []
        self.in_transaction = False
        self.transaction_depth = 0
        self._rows = rows or []
        self._raise = raise_on_fetch
        self._lock_timeout = lock_timeout

    async def fetchval(self, sql, *_args):
        self.statements.append(sql)
        if "SHOW lock_timeout" in sql:
            return self._lock_timeout
        return None

    def transaction(self):
        conn = self

        class _Txn:
            async def __aenter__(self):
                conn.in_transaction = True
                conn.transaction_depth += 1
                conn.statements.append("BEGIN")
                return self

            async def __aexit__(self, *_exc):
                conn.statements.append("COMMIT")
                return False

        return _Txn()

    async def execute(self, sql, *_args):
        self.statements.append(sql)
        return "SET"

    async def fetch(self, sql, *_args):
        self.statements.append(sql)
        if self._raise is not None:
            raise self._raise
        return self._rows


@pytest.mark.asyncio
async def test_lock_timeout_is_applied_then_restored():
    conn = _RecordingConn(rows=[], lock_timeout="10s")
    await db_provider.execute_query("SELECT 1", conn=conn, lock_timeout_ms=100)

    assert conn.statements[0] == "SHOW lock_timeout"
    assert conn.statements[1] == "SET lock_timeout = '100ms'"
    assert "SELECT 1" in conn.statements[2]
    assert conn.statements[3] == "SET lock_timeout = '10s'", "must restore"


@pytest.mark.asyncio
async def test_it_does_not_open_a_transaction_of_its_own():
    """`create_transaction()` hands out a connection with a transaction already
    open. Nesting ours as a savepoint would be worse than useless: SET LOCAL
    survives a savepoint RELEASE and would impose 100ms on the rest of the
    caller's transaction. Save/restore is correct in both cases."""
    conn = _RecordingConn(rows=[])
    await db_provider.execute_query("SELECT 1", conn=conn, lock_timeout_ms=100)

    assert conn.transaction_depth == 0
    assert "BEGIN" not in conn.statements
    assert not any("SET LOCAL" in s for s in conn.statements)


@pytest.mark.asyncio
async def test_the_timeout_is_restored_even_when_the_query_fails():
    """The failing case is the one that matters — it is the case that happens."""
    boom = asyncpg.LockNotAvailableError("canceling statement due to lock timeout")
    conn = _RecordingConn(raise_on_fetch=boom, lock_timeout="10s")

    with pytest.raises(asyncpg.LockNotAvailableError):
        await db_provider.execute_query("SELECT 1", conn=conn, lock_timeout_ms=100)

    assert conn.statements[-1] == "SET lock_timeout = '10s'"


@pytest.mark.asyncio
async def test_no_timeout_requested_means_no_transaction_overhead():
    """The default path is unchanged — no BEGIN, no SET."""
    conn = _RecordingConn(rows=[])
    await db_provider.execute_query("SELECT 1", conn=conn)

    assert conn.statements == ["SELECT 1"], "no SHOW, no SET on the default path"
    assert conn.transaction_depth == 0


@pytest.mark.asyncio
async def test_the_timeout_precedes_the_query_so_it_covers_PREPARE():
    """asyncpg raised at PREPARE, not execute (`_get_statement` ->
    `protocol.prepare`), so the timeout has to be in force before the statement
    is sent — not merely applied to its execution."""
    conn = _RecordingConn(rows=[])
    await db_provider.execute_query("SELECT 2", conn=conn, lock_timeout_ms=250)

    set_at = next(i for i, s in enumerate(conn.statements)
                  if s.startswith("SET lock_timeout"))
    query_at = next(i for i, s in enumerate(conn.statements) if "SELECT 2" in s)
    assert set_at < query_at


def test_every_stats_read_bounds_its_lock_wait():
    """A stats read added later without a bound reintroduces `issues/145`.

    Counting call sites is crude, but the failure it guards is silent and cost a
    P1 to find. Update the expected count deliberately when adding a site, and
    only after deciding the new read may block a user request for 10 seconds.
    """
    import inspect

    src = inspect.getsource(G)
    reads = src.count("_rdf_stats ") + src.count("_rdf_pred_stats")
    bounded = src.count("lock_timeout_ms=STATS_LOCK_TIMEOUT_MS")
    assert bounded == 4, (
        f"generator.py has {bounded} bounded stats reads, expected 4 "
        f"(saw {reads} references to the stats tables)")

    from vitalgraph.db.sparql_sql import slot_type_tautology as T
    tsrc = inspect.getsource(T)
    assert "bounded_lock_wait" in tsrc, (
        "the tautology check reads _rdf_pred_stats and was the single "
        "most-blocked read observed on prod; it must bound its wait")


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    asyncpg.LockNotAvailableError("canceling statement due to lock timeout"),
    asyncpg.QueryCanceledError("canceling statement due to statement timeout"),
])
async def test_a_transient_failure_is_not_cached(monkeypatch, caplog, exc):
    """The poisoning hazard that makes fix 1 safe.

    `_load_quad_stats` caches `({}, {})` so a space genuinely without stats is
    not re-queried per request. A LOCK failure is not that, and memoising it
    would plan every later query for the space without stats — the `issues/140`
    shape: degrade correctly, say nothing, stay degraded.
    """
    G._stats_cache.pop("sp_x", None)

    async def _boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(db_provider, "execute_query", _boom)
    aliases = type("A", (), {"quad_stats": None, "pred_stats": None})()

    with caplog.at_level("WARNING"):
        await G._load_quad_stats(aliases, "sp_x")

    assert "sp_x" not in G._stats_cache, "a transient failure must not be memoised"
    assert aliases.quad_stats == {} and aliases.pred_stats == {}
    assert any("without stats" in r.message or "transiently" in r.message
               for r in caplog.records), "a silent degrade is what 140 was"


@pytest.mark.asyncio
async def test_a_genuinely_absent_table_is_still_cached(monkeypatch):
    """The behaviour fix 1 must not regress: when the tables do not exist, keep
    memoising the miss rather than re-querying on every request."""
    G._stats_cache.pop("sp_y", None)

    async def _missing(*_a, **_k):
        raise asyncpg.UndefinedTableError("relation does not exist")

    monkeypatch.setattr(db_provider, "execute_query", _missing)
    aliases = type("A", (), {"quad_stats": None, "pred_stats": None})()

    await G._load_quad_stats(aliases, "sp_y")

    assert G._stats_cache.get("sp_y") == ({}, {})
    G._stats_cache.pop("sp_y", None)
