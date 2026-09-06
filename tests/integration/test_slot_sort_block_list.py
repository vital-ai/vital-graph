"""Absence of a block means SERVE; a block means decline.

`issues/167`. `slot_sort_coverage` was read as an ALLOW-LIST — a row saying "this
type is proven complete", absence meaning decline. Absence is the common case,
and that is the whole defect: nine spaces were measured with complete, correct
`entity_slot_sort` tables being served by the slow SPARQL path purely because no
row existed.

Inverted, a row means "known at risk right now" — an operation in flight, or a
shortfall a job is converging on — and absence means serve.

THE FAILURE MODE INVERTS TOO, which is why these tests exist:

    allow-list   forget to mark COMPLETE   ->  slow, correct
    block-list   forget to mark AT RISK    ->  fast, WRONG

so the tests that matter are the ones asserting a block IS taken by the
operations that create the risk, not merely that absence serves.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.fast_slot_filter import (
    record_slot_sort_coverage, release_slot_sort_block, slot_sort_is_blocked,
    take_slot_sort_block)

pytestmark = pytest.mark.asyncio(loop_scope="session")

_TYPE = "urn:test:entity:Widget"


async def _blocks(conn, space_id):
    return await conn.fetch(
        "SELECT entity_type_uuid, reason FROM slot_sort_block "
        " WHERE space_id = $1", space_id)


async def test_absence_of_a_block_serves(pg_conn, test_space):
    """The inversion. Under the allow-list this exact state DECLINED."""
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    assert not await slot_sort_is_blocked(pg_conn, sp, _TYPE), (
        "a space nobody is touching and nothing has flagged must be served — "
        "this is the state nine measured spaces were in while being declined")


async def test_a_whole_space_block_covers_every_type(pg_conn, test_space):
    """What a restore or full resync needs: it invalidates every type at once
    and does not know their uuids when it starts."""
    sp = test_space
    await take_slot_sort_block(pg_conn, sp, None, reason="test")
    try:
        assert await slot_sort_is_blocked(pg_conn, sp, _TYPE)
        assert await slot_sort_is_blocked(pg_conn, sp, "urn:test:entity:Other")
    finally:
        await release_slot_sort_block(pg_conn, sp, None)
    assert not await slot_sort_is_blocked(pg_conn, sp, _TYPE)


async def test_uncertainty_blocks_rather_than_serves(pg_conn, test_space):
    """DEFAULTS TO BLOCKED on any error — an unreadable or missing table.

    The asymmetry the allow-list had still applies in this one place: not
    knowing is not knowing it is fine, and being wrong here is a confident
    subset rather than a slow answer.
    """
    class _Boom:
        async def fetchrow(self, *a, **k):
            raise RuntimeError("relation does not exist")

    assert await slot_sort_is_blocked(_Boom(), "sp", _TYPE) is True


async def test_a_short_type_is_blocked_by_the_measurement(pg_conn, test_space):
    """The measurement and the gate are maintained by ONE function.

    Splitting them is what produced every marker-lifecycle bug in `issues/161`:
    something cleared one and did not restore the other.
    """
    sp = test_space
    t = uuid.uuid4()
    await record_slot_sort_coverage(pg_conn, sp, t, 3, 900)
    rows = [r for r in await _blocks(pg_conn, sp) if r["entity_type_uuid"] == t]
    assert rows, "a short type must take a block"
    assert "3/900" in rows[0]["reason"]


async def test_a_complete_type_releases_its_block(pg_conn, test_space):
    """And the release is safe by construction: coverage was just measured,
    which is the condition releasing requires."""
    sp = test_space
    t = uuid.uuid4()
    await record_slot_sort_coverage(pg_conn, sp, t, 3, 900)
    assert [r for r in await _blocks(pg_conn, sp) if r["entity_type_uuid"] == t]

    await record_slot_sort_coverage(pg_conn, sp, t, 900, 900)
    assert not [r for r in await _blocks(pg_conn, sp)
                if r["entity_type_uuid"] == t], (
        "a type measured complete must release its block, or the fast path "
        "stays off for a table that is correct — the defect being inverted")


async def test_an_empty_type_does_not_release(pg_conn, test_space):
    """`of_type == 0` is not evidence of completeness — it is evidence that
    nothing was measured. It must not clear a block."""
    sp = test_space
    t = uuid.uuid4()
    await record_slot_sort_coverage(pg_conn, sp, t, 0, 0)
    assert [r for r in await _blocks(pg_conn, sp) if r["entity_type_uuid"] == t]
