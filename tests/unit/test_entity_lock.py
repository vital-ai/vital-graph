"""Entity-scoped advisory locking (`issues/173`), and its bound (`issues/253`)."""
import asyncio
import re
import subprocess
import sys

import pytest

from vitalgraph.db.sparql_sql.entity_lock import (
    EntityLockTimeout,
    entity_lock_key,
    lock_entities,
)


class FakeConn:
    """Records the lock statements, and the `lock_timeout` they ran under.

    `bounded_lock_wait` reads the current value and restores it afterwards, so a
    `SHOW` has to answer with something PostgreSQL would accept back.
    """

    def __init__(self, fail_from=None, sqlstate="55P03"):
        self.keys = []
        self.timeouts = []          # lock_timeout in force at each lock, in ms
        self.statements = []
        self._current_ms = 10_000
        self._fail_from = fail_from  # index of the first lock to time out
        self._sqlstate = sqlstate

    async def fetchval(self, sql, *args):
        assert sql.strip().upper() == "SHOW LOCK_TIMEOUT", sql
        return f"{self._current_ms}ms"

    async def execute(self, sql, *args):
        self.statements.append(sql)
        m = re.match(r"SET lock_timeout = '(\d+)ms'", sql)
        if m:
            self._current_ms = int(m.group(1))
            return
        assert "pg_advisory_xact_lock" in sql, sql
        if self._fail_from is not None and len(self.keys) >= self._fail_from:
            exc = RuntimeError("canceling statement due to lock timeout")
            exc.sqlstate = self._sqlstate
            raise exc
        self.timeouts.append(self._current_ms)
        self.keys.append(args[0])


class TestKey:
    def test_fits_in_a_signed_bigint(self):
        # PostgreSQL advisory locks take a bigint; anything wider is an error.
        for u in ("urn:a", "urn:b", "x" * 500, "urn:unicode:é:☃"):
            assert -(2 ** 63) <= entity_lock_key(u) < 2 ** 63

    def test_distinct_uris_get_distinct_keys(self):
        keys = {entity_lock_key(f"urn:e:{i}") for i in range(2000)}
        assert len(keys) == 2000

    def test_stable_across_processes(self):
        # THE REASON THIS IS NOT `hash()`. PYTHONHASHSEED randomizes str hashing
        # per process, so two replicas would derive different keys for the same
        # entity and never contend — a lock that protects nothing.
        code = ("import sys; sys.path.insert(0,'.');"
                "from vitalgraph.db.sparql_sql.entity_lock import entity_lock_key;"
                "print(entity_lock_key('urn:prod_kg:probe'))")
        out = [subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, env={"PYTHONHASHSEED": s, "PATH": "/usr/bin:/bin"},
                              cwd=".").stdout.strip()
               for s in ("0", "1", "12345")]
        assert len(set(out)) == 1 and out[0], out


class TestLockOrdering:
    @pytest.mark.asyncio
    async def test_keys_are_taken_in_sorted_order(self):
        # Two writers locking the same set in opposite orders would deadlock;
        # a total order makes the second one WAIT instead of being killed.
        uris = [f"urn:e:{i}" for i in range(12)]
        a, b = FakeConn(), FakeConn()
        await lock_entities(a, uris)
        await lock_entities(b, list(reversed(uris)))
        assert a.keys == sorted(a.keys)
        assert a.keys == b.keys          # same order regardless of input order

    @pytest.mark.asyncio
    async def test_duplicates_are_collapsed(self):
        c = FakeConn()
        await lock_entities(c, ["urn:x", "urn:x", "urn:y", "urn:x"])
        assert len(c.keys) == 2 == len(set(c.keys))

    @pytest.mark.asyncio
    async def test_empty_is_a_no_op(self):
        c = FakeConn()
        assert await lock_entities(c, []) == []
        assert c.keys == []


class TestWaitingIsBoundedPerRequest:
    """`issues/253`. `lock_timeout` is per STATEMENT and each key is its own
    statement, so N contended keys could wait N x the timeout — 160 s at
    production's 10 s — with nothing bounding the request as a whole."""

    @pytest.mark.asyncio
    async def test_one_key_keeps_exactly_the_statement_it_had(self):
        # The hot path: a frame write locks one entity. One wait is ALREADY
        # bounded by the session's `lock_timeout`, so re-deriving that bound
        # would add two round trips to every write and buy nothing.
        c = FakeConn()
        await lock_entities(c, ["urn:e:1"])
        assert len(c.statements) == 1
        assert "pg_advisory_xact_lock" in c.statements[0]

    @pytest.mark.asyncio
    async def test_several_keys_share_one_budget(self):
        c = FakeConn()
        await lock_entities(c, [f"urn:e:{i}" for i in range(4)], budget_s=2.0)
        # Each wait is capped by what is LEFT, so the total cannot reach
        # 4 x the cap. Non-increasing because time only moves forward.
        assert len(c.timeouts) == 4
        assert c.timeouts == sorted(c.timeouts, reverse=True)
        assert max(c.timeouts) <= 2000

    @pytest.mark.asyncio
    async def test_a_spent_budget_never_sets_zero(self):
        # PostgreSQL reads `lock_timeout = 0` as WAIT FOREVER, so a budget that
        # rounds down to zero would remove the bound at the exact moment it is
        # needed. The clamp is the whole test.
        c = FakeConn()
        await lock_entities(c, [f"urn:e:{i}" for i in range(3)], budget_s=0.0001)
        assert c.timeouts and min(c.timeouts) >= 1

    @pytest.mark.asyncio
    async def test_budget_zero_restores_unbounded_per_key_waiting(self):
        # The escape hatch, and it must not touch `lock_timeout` at all.
        c = FakeConn()
        await lock_entities(c, ["urn:e:1", "urn:e:2"], budget_s=0)
        assert len(c.keys) == 2
        assert not any("SET lock_timeout" in s for s in c.statements)

    @pytest.mark.asyncio
    async def test_the_session_timeout_is_restored_afterwards(self):
        # A pooled connection outlives the request; leaking a 1 ms lock_timeout
        # onto the next user of it would be far worse than the bug being fixed.
        c = FakeConn()
        await lock_entities(c, ["urn:e:1", "urn:e:2"], budget_s=1.0)
        assert c.statements[-1] == "SET lock_timeout = '10000ms'"


class TestATimeoutNamesTheEntity:
    """Reported from production: "a failure cannot be traced to a lead, so
    nothing can be reconciled." PostgreSQL names the STATEMENT, and every write
    to every lead issues the same one."""

    @pytest.mark.asyncio
    async def test_the_uri_key_and_wait_are_all_carried(self):
        c = FakeConn(fail_from=0)
        with pytest.raises(EntityLockTimeout) as caught:
            await lock_entities(c, ["urn:lead:42"])
        exc = caught.value
        assert exc.uri == "urn:lead:42"
        assert exc.key == entity_lock_key("urn:lead:42")
        assert exc.waited_s >= 0
        assert "urn:lead:42" in str(exc)

    @pytest.mark.asyncio
    async def test_it_names_the_key_that_actually_blocked(self):
        # With several keys the FIRST is granted and the second blocks; naming
        # the request's first URI instead of the contended one would send a
        # reconciliation to the wrong lead.
        uris = ["urn:lead:a", "urn:lead:b", "urn:lead:c"]
        blocked_key = sorted(entity_lock_key(u) for u in uris)[1]
        blocked_uri = next(u for u in uris if entity_lock_key(u) == blocked_key)
        c = FakeConn(fail_from=1)
        with pytest.raises(EntityLockTimeout) as caught:
            await lock_entities(c, uris, budget_s=1.0)
        assert caught.value.uri == blocked_uri

    @pytest.mark.asyncio
    async def test_other_database_errors_are_not_relabelled(self):
        # Only 55P03 is a lock timeout. Calling a syntax error or a dead
        # connection "lock timeout" would send the next investigation to the
        # wrong place.
        c = FakeConn(fail_from=0, sqlstate="42601")
        with pytest.raises(RuntimeError) as caught:
            await lock_entities(c, ["urn:lead:42"])
        assert not isinstance(caught.value, EntityLockTimeout)
