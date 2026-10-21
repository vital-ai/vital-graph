"""Storage keys, and moving a space's objects onto one (storage-key Stage 2).

Graded by the enumerator, as the rename is: under the key the space must own
exactly the objects it owned under its id, with nothing `mismatched` and nothing
left behind. Plus the part the rename could not do — every auto-named object
must carry the name a FRESH create under the key gives it, including the five
constraints PostgreSQL truncated at 63 bytes when the space was made.

Every move here is a ROUND TRIP inside one rolled-back transaction: until the
cutover, a space whose objects sit under its key is unreachable.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.space_names import (
    is_storage_key, new_storage_key, storage_key_prefix)
from vitalgraph.db.sparql_sql.space_rekey import (
    _auto_named, _partition_count, fresh_names, plan_rekey, rekey_space,
    round_trip)
from vitalgraph.db.sparql_sql.space_rename import SpaceRenameRefused, rename_space
from vitalgraph.db.sparql_sql.space_rename_enumerate import enumerate_space_objects
from vitalgraph.db.sparql_sql.space_storage_key import storage_key_in_use
from vitalgraph.space.space_manager import InvalidSpaceIdError

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

_N = iter(range(1, 99))


class _Rollback(Exception):
    pass


def _short() -> str:
    return f"inttest_rk{next(_N)}"


async def _key(conn, space_id):
    return await conn.fetchval(
        "SELECT storage_key FROM space WHERE space_id = $1", space_id)


class TestANewSpaceGetsAKey:

    async def test_creation_records_one(self, pg_conn, make_space):
        sp = await make_space()
        assert is_storage_key(await _key(pg_conn, sp))

    async def test_two_spaces_never_share_one(self, pg_conn, make_space):
        a, b = await make_space(), await make_space()
        assert await _key(pg_conn, a) != await _key(pg_conn, b)

    async def test_a_key_shaped_id_is_refused(self, space_manager):
        with pytest.raises(InvalidSpaceIdError, match="storage key"):
            await space_manager.create_space_with_tables("abcd2345", "x")

    async def test_a_key_whose_prefix_names_a_relation_is_in_use(self, pg_conn):
        """A dropped space's leftovers keep its key unavailable."""
        key = new_storage_key()
        with pytest.raises(_Rollback):
            async with pg_conn.transaction():
                await pg_conn.execute(
                    f"CREATE TABLE {storage_key_prefix(key)}_leftover (x int)")
                assert await storage_key_in_use(pg_conn, key)
                raise _Rollback
        assert not await storage_key_in_use(pg_conn, key)


class TestARoundTrip:

    async def _check_round_trip(self, pg_conn, sp):
        before = await enumerate_space_objects(pg_conn, sp)
        seen = {}

        async def check(conn, plan):
            under_id = await enumerate_space_objects(conn, sp)
            seen["left_under_id"] = under_id["total"]
            seen["datatypes"] = await conn.fetchval(
                f"SELECT count(*) FROM {plan['to_prefix']}_datatype")

            # Every auto-named object carries what a fresh create under a key of
            # the same length calls it. Compared under a SECOND key because the
            # first one's names are now taken.
            other = new_storage_key()
            n = _partition_count(await enumerate_space_objects(
                conn, sp, prefix=plan["to_prefix"]), plan["to_prefix"])
            fresh = await fresh_names(conn, storage_key_prefix(other), n)
            moved = await _auto_named(conn, plan["to_prefix"])
            seen["compared"] = 0
            seen["differ"] = []
            for role, name in moved.items():
                want = fresh.get(role)
                if name is None or want is None:
                    continue
                seen["compared"] += 1
                if want.replace(other, plan["key"]) != name:
                    seen["differ"].append((name, want))

        report = await round_trip(pg_conn, sp, check=check)

        assert report["under_key"]["total"] == before["total"]
        assert report["under_key"]["mismatched"] == []
        assert seen["left_under_id"] == 0
        assert all(report["restored"].values()), report["restored"]
        assert seen["differ"] == [], seen["differ"][:5]
        assert seen["compared"] > 100
        # rolled back: nothing changed, and no key was recorded by the trip
        after = await enumerate_space_objects(pg_conn, sp)
        assert after["total"] == before["total"]
        return report, seen

    async def test_every_object_moves_and_comes_back(self, pg_conn, make_space):
        sp = await make_space(_short())
        report, seen = await self._check_round_trip(pg_conn, sp)
        assert report["statements"] > 100
        assert seen["datatypes"] > 0

    async def test_truncated_names_take_the_fresh_create_name(
            self, pg_conn, make_space):
        """The `issues/246` names: a prefix substitution cannot produce them."""
        sp = await make_space(_short())
        report, _ = await self._check_round_trip(pg_conn, sp)
        assert any(len(n) == 63 for n in report["fresh_named"]), \
            report["fresh_named"]

    async def test_a_partitioned_space(self, pg_conn, make_space):
        sp = await make_space(_short(), partition_quads=4)
        report, _ = await self._check_round_trip(pg_conn, sp)
        assert report["under_key"]["partition_children"]

    async def test_a_space_whose_id_another_extends(self, pg_conn, make_space):
        """`inttest_rkN` and `inttest_rkN_x`: the shorter one's move must not
        claim the longer one's objects, nor be blocked by them."""
        sp = await make_space(_short())
        longer = await make_space(f"{sp}_x")
        theirs = await enumerate_space_objects(pg_conn, longer)
        await self._check_round_trip(pg_conn, sp)
        assert (await enumerate_space_objects(pg_conn, longer))["total"] == \
            theirs["total"]


class TestTheRefusals:

    async def test_a_dry_run_changes_nothing(self, pg_conn, make_space):
        sp = await make_space(_short())
        key = await _key(pg_conn, sp)
        before = await enumerate_space_objects(pg_conn, sp)
        report = await rekey_space(pg_conn, sp, dry_run=True)
        assert report["dry_run"] and report["sql"]
        assert report["key"] == key, "an existing key is used, never replaced"
        assert (await enumerate_space_objects(pg_conn, sp))["total"] == \
            before["total"]
        assert await _key(pg_conn, sp) == key

    async def test_an_unknown_space(self, pg_conn):
        with pytest.raises(SpaceRenameRefused, match="no space"):
            await plan_rekey(pg_conn, "inttest_no_such_space")

    async def test_moving_back_a_space_that_was_never_moved(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused):
            await rekey_space(pg_conn, sp, reverse=True)

    async def test_a_key_is_never_replaced(self, pg_conn, make_space):
        sp = await make_space(_short())
        other = new_storage_key()
        async with pg_conn.transaction():
            with pytest.raises(SpaceRenameRefused, match="never changed"):
                await plan_rekey(pg_conn, sp, key=other)

    async def test_renaming_to_a_key_shaped_id(self, pg_conn, make_space):
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="storage key"):
            await rename_space(pg_conn, sp, "abcd2345")
