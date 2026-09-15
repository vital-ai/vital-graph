"""The frame_slot write helpers must not require the table to exist.

`scripts/migrate_frame_slot_table.py` states the contract: "A space that is NOT
migrated keeps working: `ensure_frame_slot_table` reports the table absent, the
rewrite declines, and queries fall back to the quad joins — correct, just
without the collapse."

That was true for READS and false for WRITES. The sync helpers named
`{space}_frame_slot` unconditionally, so on an unmigrated space every delete
failed at storage with `relation "{space}_frame_slot" does not exist`. Seen on
the dev instance, where 38 of 41 spaces had no such table — so the documented
"keeps working" was false for 93% of them, and the failure was a hard write
error rather than the graceful decline the contract promises.

These tests use a fake connection rather than a database because what is being
pinned is the GUARD, not the SQL: that an absent table means "do nothing and
return 0" instead of "issue a statement that will raise". The distinction
matters because these run inside the caller's write transaction, where a raised
error poisons the transaction and takes the caller's own writes down with it.
"""
from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql import sync_frame_slot_table as m


class FakeConn:
    """Minimal asyncpg stand-in. `present` drives what `to_regclass` returns."""

    def __init__(self, present: bool):
        self.present = present
        self.statements = []

    async def fetchval(self, sql, *args):
        if "to_regclass" in sql:
            return "public.sp_frame_slot" if self.present else None
        return None

    async def execute(self, sql, *args):
        self.statements.append(sql)
        return "DELETE 0"

    def is_in_transaction(self):
        return True            # avoids the transaction() context manager


@pytest.fixture(autouse=True)
def _clear_cache():
    m.reset_present_cache()
    yield
    m.reset_present_cache()


@pytest.mark.asyncio
async def test_after_edge_insert_is_a_noop_without_the_table():
    conn = FakeConn(present=False)
    assert await m.sync_frame_slot_after_edge_insert(conn, "sp", [uuid.uuid4()]) == 0
    assert conn.statements == [], "issued SQL against a table that does not exist"


@pytest.mark.asyncio
async def test_before_delete_is_a_noop_without_the_table():
    conn = FakeConn(present=False)
    assert await m.sync_frame_slot_before_delete(conn, "sp", [uuid.uuid4()]) == 0
    assert conn.statements == [], "issued SQL against a table that does not exist"


@pytest.mark.asyncio
async def test_delete_for_context_is_a_noop_without_the_table():
    conn = FakeConn(present=False)
    assert await m.delete_frame_slot_for_context(conn, "sp", uuid.uuid4()) == 0
    assert conn.statements == [], "issued SQL against a table that does not exist"


@pytest.mark.asyncio
async def test_a_present_table_is_still_maintained():
    # The guard must not disable the feature where it IS migrated -- an
    # over-broad guard would be silent data rot rather than a loud failure.
    conn = FakeConn(present=True)
    await m.delete_frame_slot_for_context(conn, "sp", uuid.uuid4())
    assert any("DELETE FROM sp_frame_slot" in s for s in conn.statements)


@pytest.mark.asyncio
async def test_absence_is_rechecked_so_a_migration_takes_effect():
    """Only a True is cached. A space migrated while the process runs must be
    picked up on its next write, not at the next restart."""
    conn = FakeConn(present=False)
    assert await m.delete_frame_slot_for_context(conn, "sp", uuid.uuid4()) == 0
    conn.present = True                       # the migration runs
    await m.delete_frame_slot_for_context(conn, "sp", uuid.uuid4())
    assert any("DELETE FROM sp_frame_slot" in s for s in conn.statements)
