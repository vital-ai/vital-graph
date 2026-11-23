"""A create for a space that already exists cannot re-key it — issues/348.

Two instances over one database. Instance B had not heard of a space A had
just created; B's create looked for its tables under the bare id (its key map
lacked the key), found none, allocated a NEW key, created a full set of empty
tables under it, and upserted the `space` row with that key. A's space was then
pointed at empty tables, its data cut off under the old key.

Two guards, both tested here against the real schema:
* the manager reads the row (loading its key) before checking for tables, so
  B finds the space where it is;
* the row write refuses to replace a key whose objects exist, for the create
  that passes the check concurrently. It then drops only its OWN objects —
  never the `space`/`graph` rows by id, which are the other space's.

"B" is a fresh SpaceManager whose key map has forgotten the space.
"""

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.space_names import (
    forget_storage_key, registered_storage_key)
from vitalgraph.space.space_manager import SpaceAlreadyExistsError, SpaceManager

from .conftest import TEST_SPACE_PREFIX, skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


async def _key(conn, space_id):
    return await conn.fetchval(
        "SELECT storage_key FROM space WHERE space_id = $1", space_id)


async def _tables_under(conn, key):
    return await conn.fetchval(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
        "AND starts_with(tablename, $1)", f"vgs_{key}_")


async def _all_keyed_tables(conn):
    return await conn.fetchval(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
        "AND starts_with(tablename, 'vgs_')")


class TestTheManagerFindsTheSpace:

    async def test_a_create_on_an_instance_that_has_not_heard_is_refused(
            self, pg_conn, make_space, space_impl):
        sp = await make_space()
        key = await _key(pg_conn, sp)
        tables_before = await _all_keyed_tables(pg_conn)

        forget_storage_key(sp)                      # B has not heard of it
        b = SpaceManager(space_backend=space_impl)
        with pytest.raises(SpaceAlreadyExistsError):
            await b.create_space_with_tables(sp, sp)

        assert await _key(pg_conn, sp) == key
        assert registered_storage_key(sp) == key
        assert await _all_keyed_tables(pg_conn) == tables_before


class TestADeleteOnAnInstanceThatHasNotHeard:

    async def test_it_drops_the_keyed_tables(self, pg_conn, make_space, space_impl):
        """Before: B looked for the space under its bare id and reported it
        missing. Now B loads the key and drops the space's real tables."""
        sp = await make_space()
        key = await _key(pg_conn, sp)
        forget_storage_key(sp)
        b = SpaceManager(space_backend=space_impl)
        assert await b.delete_space_with_tables(sp)
        assert await _tables_under(pg_conn, key) == 0
        assert await _key(pg_conn, sp) is None


class TestTheRowWriteRefuses:

    async def test_a_create_that_loses_the_row_keeps_the_existing_space(
            self, pg_conn, make_space, space_impl):
        """The concurrent case: B passed every check before A's row existed,
        built its own tables, and only the row write can still refuse."""
        sp = await make_space()
        key_a = await _key(pg_conn, sp)
        graphs_before = await pg_conn.fetchval(
            "SELECT count(*) FROM graph WHERE space_id = $1", sp)

        forget_storage_key(sp)
        assert await space_impl.create_space_storage(sp)
        key_b = registered_storage_key(sp)
        assert key_b and key_b != key_a
        assert await _tables_under(pg_conn, key_b) > 0

        with pytest.raises(SpaceAlreadyExistsError):
            await space_impl.create_space_metadata(sp, {"space_name": sp})

        # A's space is untouched and this process names it by A's key again.
        assert await _key(pg_conn, sp) == key_a
        assert registered_storage_key(sp) == key_a
        assert await _tables_under(pg_conn, key_a) > 0
        assert await pg_conn.fetchval(
            "SELECT count(*) FROM graph WHERE space_id = $1", sp) == graphs_before
        # B's own tables are gone.
        assert await _tables_under(pg_conn, key_b) == 0

    async def test_a_row_without_objects_is_still_taken_over(
            self, pg_conn, space_impl):
        """A row left with no tables names nothing; creating the space again
        over it works, as it did before."""
        sp = f"{TEST_SPACE_PREFIX}or{uuid.uuid4().hex[:8]}"
        await pg_conn.execute(
            "INSERT INTO space (space_id, space_name, update_time, storage_key) "
            "VALUES ($1, $1, NOW(), 'zzzzzzzz')", sp)
        b = SpaceManager(space_backend=space_impl)
        try:
            assert await b.create_space_with_tables(sp, sp)
            key = await _key(pg_conn, sp)
            assert key != "zzzzzzzz"
            assert registered_storage_key(sp) == key
            assert await _tables_under(pg_conn, key) > 0
        finally:
            await b.delete_space_with_tables(sp)
            await pg_conn.execute("DELETE FROM space WHERE space_id = $1", sp)
