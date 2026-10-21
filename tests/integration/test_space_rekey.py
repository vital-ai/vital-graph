"""Storage keys, and moving a space's objects onto one (storage-key Stages 2-3).

Graded by the enumerator, as the rename is: under the key the space must own
exactly the objects it owned under its id, with nothing `mismatched` and nothing
left behind. Plus the part the rename could not do — every auto-named object
must carry the name a FRESH create under the key gives it, including the five
constraints PostgreSQL truncated at 63 bytes when the space was made.

TWO KINDS OF SPACE. One created through the space manager is KEYED from birth
(its objects are `vgs_<key>_…`). A LEGACY space — tables named by id, a row
with no key — is what every database held before the cutover, and the
temporary id fallback still serves it; `_legacy` makes one.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.space_names import (
    forget_storage_key, is_storage_key, new_storage_key, registered_storage_key,
    space_prefix, storage_key_prefix)
from vitalgraph.db.sparql_sql.space_rekey import (
    _auto_named, _partition_count, fresh_names, plan_rekey, rekey_space,
    round_trip)
from vitalgraph.db.sparql_sql.space_rename import (
    SpaceRenameRefused, plan_rename, rename_space)
from vitalgraph.db.sparql_sql.space_rename_enumerate import enumerate_space_objects
from vitalgraph.db.sparql_sql.space_storage_key import (
    is_keyed, load_storage_keys, storage_key_in_use)
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
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


class TestANewSpaceIsKeyed:

    async def test_creation_records_a_key(self, pg_conn, make_space):
        sp = await make_space()
        assert is_storage_key(await _key(pg_conn, sp))

    async def test_its_objects_are_named_under_the_key(self, pg_conn, make_space):
        sp = await make_space()
        key = await _key(pg_conn, sp)
        assert space_prefix(sp) == storage_key_prefix(key)
        assert await is_keyed(pg_conn, sp)
        assert await pg_conn.fetchval(
            "SELECT to_regclass($1) IS NULL", f"{sp}_rdf_quad"), \
            "nothing may be named by the id any more"
        assert (await enumerate_space_objects(pg_conn, sp))["total"] > 100

    async def test_two_spaces_never_share_a_key(self, pg_conn, make_space):
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


class TestTheKeyMapFollowsTheDatabase:

    async def test_loading_finds_a_keyed_space(self, pg_conn, make_space):
        sp = await make_space()
        key = registered_storage_key(sp)
        forget_storage_key(sp)
        assert space_prefix(sp) == sp
        assert await load_storage_keys(pg_conn, sp) == 1
        assert registered_storage_key(sp) == key

    async def test_a_recorded_key_with_objects_by_id_is_not_keyed(
            self, pg_conn, make_legacy_space):
        """A space created before the cutover holds a key and id-named objects;
        naming it by the key would point at nothing."""
        sp = await make_legacy_space(_short())
        await pg_conn.execute(
            "UPDATE space SET storage_key = $1 WHERE space_id = $2",
            new_storage_key(), sp)
        assert await load_storage_keys(pg_conn, sp) == 0
        assert space_prefix(sp) == sp


class TestARoundTrip:
    """Onto the key and back, in one rolled-back transaction."""

    async def _check_round_trip(self, pg_conn, sp):
        before = await enumerate_space_objects(pg_conn, sp)
        seen = {}

        async def check(conn, plan):
            under_id = await enumerate_space_objects(conn, sp, prefix=sp)
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

        assert not report["was_keyed"]
        assert report["under_key"]["total"] == before["total"]
        assert report["under_key"]["mismatched"] == []
        assert seen["left_under_id"] == 0
        assert all(report["restored"].values()), report["restored"]
        assert seen["differ"] == [], seen["differ"][:5]
        assert seen["compared"] > 100
        after = await enumerate_space_objects(pg_conn, sp)
        assert after["total"] == before["total"]
        return report, seen

    async def test_every_object_moves_and_comes_back(self, pg_conn, make_legacy_space):
        sp = await make_legacy_space(_short())
        report, seen = await self._check_round_trip(pg_conn, sp)
        assert report["statements"] > 100
        assert seen["datatypes"] > 0

    async def test_truncated_names_take_the_fresh_create_name(
            self, pg_conn, make_legacy_space):
        """The `issues/246` names: a prefix substitution cannot produce them."""
        sp = await make_legacy_space(_short())
        report, _ = await self._check_round_trip(pg_conn, sp)
        assert any(len(n) == 63 for n in report["fresh_named"]), \
            report["fresh_named"]

    async def test_a_partitioned_space(self, pg_conn, make_legacy_space):
        sp = await make_legacy_space(_short(), partition_quads=4)
        report, _ = await self._check_round_trip(pg_conn, sp)
        assert report["under_key"]["partition_children"]

    async def test_a_space_whose_id_another_extends(self, pg_conn, make_legacy_space):
        """`inttest_rkN` and `inttest_rkN_x`: the shorter one's move must not
        claim the longer one's objects, nor be blocked by them."""
        sp = await make_legacy_space(_short())
        longer = await make_legacy_space(f"{sp}_x")
        theirs = await enumerate_space_objects(pg_conn, longer)
        await self._check_round_trip(pg_conn, sp)
        assert (await enumerate_space_objects(pg_conn, longer))["total"] == \
            theirs["total"]

    async def test_a_user_named_vector_table_with_truncated_names(
            self, pg_conn, make_legacy_space):
        """Found on the dev database: a vec table named for a long user index
        carries NOT NULL constraints PostgreSQL truncated at 63 bytes, which the
        bare schema probe never creates — so the move was refused. The probe
        now builds the space's own vec/fts tables too."""
        sp = await make_legacy_space("inttest_rk_vecname")
        schema = SparqlSQLSchema()
        for stmt in schema.create_vector_data_table_sql(
                sp, "paraphrase_test_85c7071", 384):
            await pg_conn.execute(stmt)
        names = (await enumerate_space_objects(pg_conn, sp))["constraints"]
        assert any(len(n) == 63 and "_vec_paraphrase" in n for n in names), \
            "the fixture should reproduce the truncated names"
        report, _ = await self._check_round_trip(pg_conn, sp)
        assert any("_vec_paraphrase" in n for n in report["fresh_named"])

    async def test_a_keyed_space_goes_to_its_id_and_back(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        before = await enumerate_space_objects(pg_conn, sp)
        report = await round_trip(pg_conn, sp)
        assert report["was_keyed"]
        assert all(report["restored"].values()), report["restored"]
        assert (await enumerate_space_objects(pg_conn, sp))["total"] == \
            before["total"]


class TestACommittedReKey:

    async def test_a_legacy_space_moves_onto_its_key_and_back(
            self, pg_conn, make_legacy_space):
        sp = await make_legacy_space(_short())
        await pg_conn.execute(
            f"INSERT INTO {space_prefix(sp)}_datatype (datatype_uri) VALUES ('urn:probe:rk')")
        before = await enumerate_space_objects(pg_conn, sp)

        report = await rekey_space(pg_conn, sp, dry_run=False)
        key = report["key"]
        assert await is_keyed(pg_conn, sp)
        assert space_prefix(sp) == storage_key_prefix(key)
        assert (await enumerate_space_objects(pg_conn, sp))["total"] == \
            before["total"]
        assert await pg_conn.fetchval(
            f"SELECT count(*) FROM {space_prefix(sp)}_datatype "
            f"WHERE datatype_uri = 'urn:probe:rk'") == 1

        await rekey_space(pg_conn, sp, reverse=True, dry_run=False)
        assert not await is_keyed(pg_conn, sp)
        assert space_prefix(sp) == sp
        assert await _key(pg_conn, sp) == key, "moving back keeps the key"
        assert (await enumerate_space_objects(pg_conn, sp))["total"] == \
            before["total"]

    async def test_a_dry_run_changes_nothing(self, pg_conn, make_legacy_space):
        sp = await make_legacy_space(_short())
        before = await enumerate_space_objects(pg_conn, sp)
        report = await rekey_space(pg_conn, sp, dry_run=True)
        assert report["dry_run"] and report["sql"]
        assert (await enumerate_space_objects(pg_conn, sp))["total"] == \
            before["total"]
        assert await _key(pg_conn, sp) is None
        assert space_prefix(sp) == sp


class TestARenameOfAKeyedSpace:

    async def test_is_the_registry_rows_and_nothing_else(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        stmts = await plan_rename(pg_conn, sp, f"{sp}r")
        assert [k for k, _ in stmts] == ["registry", "process"]

    async def test_the_objects_stay_and_the_new_id_finds_them(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        new = f"{sp}r"
        prefix = space_prefix(sp)
        await pg_conn.execute(
            f"INSERT INTO {prefix}_datatype (datatype_uri) VALUES ('urn:probe:rn')")
        before = await enumerate_space_objects(pg_conn, sp)
        await rename_space(pg_conn, sp, new)
        try:
            assert space_prefix(new) == prefix
            assert space_prefix(sp) == sp
            after = await enumerate_space_objects(pg_conn, new)
            assert after["total"] == before["total"]
            assert after["tables"] == before["tables"], "nothing was renamed"
            assert await pg_conn.fetchval(
                f"SELECT count(*) FROM {space_prefix(new)}_datatype "
                f"WHERE datatype_uri = 'urn:probe:rn'") == 1
        finally:
            await rename_space(pg_conn, new, sp)
        assert space_prefix(sp) == prefix

    async def test_a_length_change_is_no_longer_refused(
            self, pg_conn, make_space):
        """The `issues/246` refusal was about re-truncating object names; a keyed
        space's names do not move, so any valid id length is fine."""
        sp = await make_space(_short())
        new = f"{sp}_longer_name"
        await rename_space(pg_conn, sp, new)
        await rename_space(pg_conn, new, sp)
        assert await is_keyed(pg_conn, sp)


class TestTheRefusals:

    async def test_an_unknown_space(self, pg_conn):
        with pytest.raises(SpaceRenameRefused, match="no space"):
            await plan_rekey(pg_conn, "inttest_no_such_space")

    async def test_moving_back_a_space_that_was_never_moved(
            self, pg_conn, make_legacy_space):
        sp = await make_legacy_space(_short())
        with pytest.raises(SpaceRenameRefused):
            await rekey_space(pg_conn, sp, reverse=True)

    async def test_moving_a_keyed_space_onto_its_key_again(
            self, pg_conn, make_space):
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="re-keyed already"):
            await rekey_space(pg_conn, sp)

    async def test_a_key_is_never_replaced(self, pg_conn, make_space):
        sp = await make_space(_short())
        async with pg_conn.transaction():
            with pytest.raises(SpaceRenameRefused, match="never changed"):
                await plan_rekey(pg_conn, sp, key=new_storage_key())

    async def test_renaming_to_a_key_shaped_id(self, pg_conn, make_space):
        sp = await make_space(_short())
        with pytest.raises(SpaceRenameRefused, match="storage key"):
            await rename_space(pg_conn, sp, "abcd2345")
