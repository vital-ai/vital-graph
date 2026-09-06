"""The alarms that make the block-list self-checking rather than optimistic.

`issues/167`. Inverting the gate inverts the failure mode:

    allow-list   forget to mark COMPLETE   ->  slow, correct
    block-list   forget to mark AT RISK    ->  fast, WRONG

The design's correctness therefore rests on every risky operation taking a
block, and no audit can prove that a FUTURE write path will. These alarms are
what detects the hole instead of waiting for a wrong answer to be noticed.

UNDECLARED SHORTFALL is the one that matters: a type measured short with no
block already held means something made the table incomplete without declaring
it, so queries were being served from it. It reports a bug in the CODE, not a
problem with the data.

STALE BLOCK is the converse: a block nothing is clearing, which is
slow-and-correct but indefinite, and which nothing else would report.

ORDER IS LOAD-BEARING and the maintenance job depends on it:
`record_slot_sort_coverage` takes a block for every short type, so the alarms
must be computed BEFORE recording or the first one can never fire.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.fast_slot_filter import (
    record_slot_sort_coverage, slot_sort_alarms, take_slot_sort_block)

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _cov(type_uuid, in_table, of_type):
    return {"entity_type_uuid": type_uuid, "in_table": in_table,
            "of_type": of_type}


async def test_a_shortfall_with_no_block_is_an_undeclared_shortfall(
        pg_conn, test_space):
    """The detector for the design's one real hole."""
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    t = uuid.uuid4()

    found = await slot_sort_alarms(pg_conn, sp, [_cov(t, 3, 900)])

    assert [f for f in found if f["kind"] == "undeclared_shortfall"], (
        "a type short with no block held means a write path made it incomplete "
        "without declaring it — queries were served from a short table")


async def test_a_shortfall_under_a_block_is_not_an_alarm(pg_conn, test_space):
    """A declared shortfall is the system working, not a fault."""
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    t = uuid.uuid4()
    await take_slot_sort_block(pg_conn, sp, t, reason="repair in flight")

    found = await slot_sort_alarms(pg_conn, sp, [_cov(t, 3, 900)])

    assert not [f for f in found if f["kind"] == "undeclared_shortfall"]


async def test_a_whole_space_block_declares_every_type(pg_conn, test_space):
    """A restore blocks the space without knowing its type uuids, so a
    shortfall under that block is declared."""
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    await take_slot_sort_block(pg_conn, sp, None, reason="restore in flight")

    found = await slot_sort_alarms(
        pg_conn, sp, [_cov(uuid.uuid4(), 0, 900), _cov(uuid.uuid4(), 1, 5)])

    assert not [f for f in found if f["kind"] == "undeclared_shortfall"]


async def test_recording_first_would_hide_the_alarm(pg_conn, test_space):
    """Pins the ordering the maintenance job depends on.

    `record_slot_sort_coverage` takes a block for a short type, so computing the
    alarms afterwards can never report an undeclared shortfall — it would look
    like a clean system forever.
    """
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    t = uuid.uuid4()

    before = await slot_sort_alarms(pg_conn, sp, [_cov(t, 3, 900)])
    await record_slot_sort_coverage(pg_conn, sp, t, 3, 900)
    after = await slot_sort_alarms(pg_conn, sp, [_cov(t, 3, 900)])

    assert [f for f in before if f["kind"] == "undeclared_shortfall"]
    assert not [f for f in after if f["kind"] == "undeclared_shortfall"], (
        "recording first hides the alarm — this is why the maintenance job "
        "computes alarms BEFORE it records")


async def test_a_block_held_too_long_is_reported(pg_conn, test_space):
    """Slow-and-correct, but indefinite, and nothing else would say so."""
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    t = uuid.uuid4()
    await take_slot_sort_block(pg_conn, sp, t, reason="stuck repair")
    await pg_conn.execute(
        "UPDATE slot_sort_block SET created_at = NOW() - INTERVAL '30 hours'"
        " WHERE space_id = $1 AND entity_type_uuid = $2", sp, t)

    found = await slot_sort_alarms(pg_conn, sp, [], stale_after_hours=24)

    stale = [f for f in found if f["kind"] == "stale_block"]
    assert stale and stale[0]["reason"] == "stuck repair"


async def test_a_fresh_block_is_not_stale(pg_conn, test_space):
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    await take_slot_sort_block(pg_conn, sp, uuid.uuid4(), reason="just taken")

    found = await slot_sort_alarms(pg_conn, sp, [], stale_after_hours=24)

    assert not [f for f in found if f["kind"] == "stale_block"]
