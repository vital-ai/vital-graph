"""Entity-scoped advisory locking (`issues/173`)."""
import asyncio
import subprocess
import sys

import pytest

from vitalgraph.db.sparql_sql.entity_lock import entity_lock_key, lock_entities


class FakeConn:
    def __init__(self):
        self.keys = []

    async def execute(self, sql, *args):
        assert "pg_advisory_xact_lock" in sql, sql
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
