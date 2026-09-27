"""`UPDATE space SET space_id` carries its children — issue 232.

`space.space_id` IS the primary key; there is no numeric surrogate anywhere. The
eleven admin tables that reference it declared `ON DELETE CASCADE` and no
`ON UPDATE CASCADE`, so renaming a space by updating that one row was REJECTED —
which is why a rename could not be a catalogue operation at all.

Decided 2026-09-26: add `ON UPDATE CASCADE` to all of them, and give
`user_space_access` the foreign key it never had.

THE TEST THAT MATTERS IS `TestAccessSurvivesARename`. `user_space_access` had no
FK, so unlike the eleven it would NOT reject a rename that forgot it — it would
silently keep rows pointing at an id nobody uses, which is a silent revocation of
every user's access to the renamed space. `issues/232` calls it the one failure
that is both invisible and security-relevant, and asks for exactly this test
BEFORE the rename ships rather than after.

These are schema tests, deliberately independent of the rename itself: the
cascade is what makes the rename possible, so it is worth proving on its own
before anything is built on top of it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


async def _rename(conn, old: str, new: str) -> None:
    await conn.execute("UPDATE space SET space_id = $1 WHERE space_id = $2",
                       new, old)


class TestTheUpdateIsAcceptedAtAll:

    async def test_renaming_the_registry_row_succeeds(self, pg_conn, make_space):
        """Before `ON UPDATE CASCADE` this raised a foreign-key violation, which
        is why `issues/232` could not be built as a catalogue operation."""
        sp = await make_space()
        new = f"{sp}_renamed"
        try:
            await _rename(pg_conn, sp, new)
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM space WHERE space_id = $1", new) == 1
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM space WHERE space_id = $1", sp) == 0
        finally:
            await _rename(pg_conn, new, sp)

    async def test_every_fk_to_space_cascades_on_update(self, pg_conn):
        """Derived from the catalogue, so a table added later with the old
        `ON DELETE CASCADE`-only pattern fails here instead of failing a rename.

        `confupdtype` is PostgreSQL's `"char"`, which asyncpg returns as BYTES —
        comparing it to a str is always False, and doing so made the migration
        report every constraint as unfixed immediately after fixing it.
        """
        rows = await pg_conn.fetch("""
            SELECT rel.relname AS child, con.conname, con.confupdtype
              FROM pg_constraint con
              JOIN pg_class rel ON rel.oid = con.conrelid
              JOIN pg_class ref ON ref.oid = con.confrelid
             WHERE con.contype = 'f' AND ref.relname = 'space'
        """)
        assert rows, "no foreign keys to space at all — schema not as expected"
        missing = [f"{r['child']}.{r['conname']}" for r in rows
                   if (r["confupdtype"].decode()
                       if isinstance(r["confupdtype"], bytes)
                       else r["confupdtype"]) != "c"]
        assert missing == [], (
            f"these would block or be stranded by a rename: {missing}")

    async def test_user_space_access_has_a_foreign_key_now(self, pg_conn):
        """It had none, which is what made the revocation silent rather than an
        error."""
        assert await pg_conn.fetchval("""
            SELECT count(*) FROM pg_constraint con
              JOIN pg_class rel ON rel.oid = con.conrelid
              JOIN pg_class ref ON ref.oid = con.confrelid
             WHERE con.contype = 'f' AND rel.relname = 'user_space_access'
               AND ref.relname = 'space'
        """) == 1


class TestAccessSurvivesARename:
    """The failure that does not announce itself."""

    @pytest_asyncio.fixture(loop_scope="session")
    async def a_user(self, pg_conn):
        username = f"inttest_u_{uuid.uuid4().hex[:8]}"
        uid = await pg_conn.fetchval(
            'INSERT INTO "user" (username, password_hash, email) '
            'VALUES ($1, $2, $3) RETURNING user_id',
            username, "x", f"{username}@example.invalid")
        yield uid
        await pg_conn.execute('DELETE FROM "user" WHERE user_id = $1', uid)

    async def test_a_grant_follows_the_space_to_its_new_id(
            self, pg_conn, make_space, a_user):
        sp = await make_space()
        new = f"{sp}_renamed"
        await pg_conn.execute(
            "INSERT INTO user_space_access (user_id, space_id, access_level) "
            "VALUES ($1, $2, 'rw')", a_user, sp)
        try:
            await _rename(pg_conn, sp, new)

            moved = await pg_conn.fetchval(
                "SELECT access_level FROM user_space_access "
                "WHERE user_id = $1 AND space_id = $2", a_user, new)
            assert moved == "rw", (
                "the grant did not follow the rename — every user's access to "
                "this space has been silently revoked")
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM user_space_access "
                "WHERE user_id = $1 AND space_id = $2", a_user, sp) == 0, \
                "a grant was left behind pointing at an id nobody uses"
        finally:
            await _rename(pg_conn, new, sp)
            await pg_conn.execute(
                "DELETE FROM user_space_access WHERE user_id = $1", a_user)

    async def test_a_grant_is_still_removed_when_the_space_is_deleted(
            self, pg_conn, make_space, a_user):
        """ON DELETE CASCADE must survive being re-added alongside ON UPDATE —
        the migration drops and re-adds each constraint, so losing the delete
        action is a live way to get this wrong, and it would leak grants for
        dropped spaces forever."""
        sp = await make_space()
        await pg_conn.execute(
            "INSERT INTO user_space_access (user_id, space_id, access_level) "
            "VALUES ($1, $2, 'r')", a_user, sp)
        await pg_conn.execute("DELETE FROM space WHERE space_id = $1", sp)
        assert await pg_conn.fetchval(
            "SELECT count(*) FROM user_space_access WHERE space_id = $1", sp) == 0

    async def test_a_grant_for_an_unknown_space_is_now_rejected(
            self, pg_conn, a_user):
        """The other half of having a foreign key: the rows cannot become
        orphaned in the first place."""
        import asyncpg
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await pg_conn.execute(
                "INSERT INTO user_space_access (user_id, space_id, access_level) "
                "VALUES ($1, 'inttest_no_such_space_at_all', 'r')", a_user)


class TestTheOtherChildrenFollowToo:

    async def test_a_graph_row_follows(self, pg_conn, make_space):
        sp = await make_space()
        new = f"{sp}_renamed"
        graph_uri = f"urn:{sp}:probe"
        await pg_conn.execute(
            "INSERT INTO graph (space_id, graph_uri, graph_name) "
            "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING", sp, graph_uri, "probe")
        try:
            await _rename(pg_conn, sp, new)
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM graph WHERE space_id = $1 "
                "AND graph_uri = $2", new, graph_uri) == 1
        finally:
            await _rename(pg_conn, new, sp)
            await pg_conn.execute(
                "DELETE FROM graph WHERE space_id = $1 AND graph_uri = $2",
                sp, graph_uri)

    async def test_backfill_state_follows(self, pg_conn, make_space):
        """Chosen as a second case because a stranded `backfill_state` row is the
        `issues/149`-shaped failure: the backfill would consider a graph complete
        under an id that no longer exists and never stamp the entities."""
        sp = await make_space()
        new = f"{sp}_renamed"
        await pg_conn.execute(
            "INSERT INTO backfill_state (space_id, graph_uri, quad_inserts) "
            "VALUES ($1, $2, 0) ON CONFLICT DO NOTHING", sp, "urn:probe")
        try:
            await _rename(pg_conn, sp, new)
            assert await pg_conn.fetchval(
                "SELECT count(*) FROM backfill_state WHERE space_id = $1",
                new) == 1
        finally:
            await _rename(pg_conn, new, sp)
            await pg_conn.execute(
                "DELETE FROM backfill_state WHERE space_id = $1", sp)
