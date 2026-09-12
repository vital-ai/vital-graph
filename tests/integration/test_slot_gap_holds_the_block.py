"""A genuinely absent slot row must BLOCK, and complete entity coverage must
not release it.

`issues/194`. `slot_sort_block` is a block-list — absence means SERVE — so a
shortfall that is detected and left unblocked is knowingly serving a short page
for a sort and a plausible SUBSET for a filter. That is a wrong answer, not a
slow one, which is why it cannot wait on a size threshold.

THE TRAP THIS GUARDS is the marker lifecycle, not the block itself. The two
measurements see different things: `in_table`/`of_type` count ENTITIES, so an
entity holding rows for slot type A while missing type B counts as covered. A
blocker bolted alongside `record_slot_sort_coverage` would therefore take a
block that the very next per-entity sweep released, every cycle, which is the
class of failure `issues/161` catalogues. So the slot-level number enters the
SAME decision, and these tests pin that it cannot be released around.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

# `slot_sort_block` and `slot_sort_coverage` are GLOBAL tables whose `space_id`
# is a FOREIGN KEY into `space`, so a fabricated id cannot be inserted — spaces
# are explicitly managed, and the fixture is the place to respect that rather
# than the insert path. So these use the real `test_space` and isolate on a
# random `entity_type_uuid` per test instead.
#
# Cleanup happens INSIDE each test, not in an async fixture teardown: tearing
# down around `pg_conn` raced the connection ("another operation is in
# progress") and turned every test in this file into an error.


async def _clean(pg_conn, sid, ty):
    for t in ("slot_sort_block", "slot_sort_coverage"):
        await pg_conn.execute(
            f"DELETE FROM {t} WHERE space_id = $1 AND entity_type_uuid = $2",
            sid, ty)


async def _blocked(pg_conn, sid, ty=None):
    return await pg_conn.fetchval(
        "SELECT count(*) FROM slot_sort_block WHERE space_id = $1"
        "   AND (($2::uuid IS NULL AND entity_type_uuid IS NULL)"
        "        OR entity_type_uuid = $2)", sid, ty) > 0


async def test_complete_coverage_with_NO_slot_gap_releases(pg_conn, test_space):
    """The baseline: unchanged behaviour when nothing is absent."""
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        record_slot_sort_coverage, take_slot_sort_block)
    sid, ty = test_space, uuid.uuid4()
    await _clean(pg_conn, sid, ty)
    await take_slot_sort_block(pg_conn, sid, ty, reason="test")
    assert await _blocked(pg_conn, sid, ty)
    await record_slot_sort_coverage(pg_conn, sid, ty, 10, 10, slot_shortfall=0)
    assert not await _blocked(pg_conn, sid, ty), "complete and clean: released"


async def test_a_slot_gap_BLOCKS_despite_complete_entity_coverage(
        pg_conn, test_space):
    """THE ASSERTION THAT MATTERS.

    Entity coverage is 10/10 — perfect — and a slot row is absent. The type must
    be blocked, because the entity numbers cannot see a missing slot type.
    """
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        record_slot_sort_coverage)
    sid, ty = test_space, uuid.uuid4()
    await _clean(pg_conn, sid, ty)
    await record_slot_sort_coverage(pg_conn, sid, ty, 10, 10, slot_shortfall=1)
    assert await _blocked(pg_conn, sid, ty), (
        "a single absent slot row must hold the type, or a sort on the affected "
        "slot type is served from a table known to be short")


async def test_a_slot_gap_is_not_RELEASED_by_complete_entity_coverage(
        pg_conn, test_space):
    """The flap this design exists to prevent: block taken, then released by a
    measurement that cannot see the gap."""
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        record_slot_sort_coverage, take_slot_sort_block)
    sid, ty = test_space, uuid.uuid4()
    await _clean(pg_conn, sid, ty)
    await take_slot_sort_block(pg_conn, sid, ty, reason="slot gap")
    await record_slot_sort_coverage(pg_conn, sid, ty, 10, 10, slot_shortfall=3)
    assert await _blocked(pg_conn, sid, ty), "must still be held"


async def test_the_coverage_row_agrees_with_the_gate(pg_conn, test_space):
    """`complete` is what an operator reads. It must not say complete while the
    gate holds — that disagreement is how a stuck block looks like a bug."""
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        record_slot_sort_coverage)
    sid, ty = test_space, uuid.uuid4()
    await _clean(pg_conn, sid, ty)
    await record_slot_sort_coverage(pg_conn, sid, ty, 10, 10, slot_shortfall=1)
    row = await pg_conn.fetchrow(
        "SELECT complete FROM slot_sort_coverage WHERE space_id = $1"
        "   AND entity_type_uuid = $2", sid, ty)
    assert row is not None and row["complete"] is False


async def test_the_whole_space_release_holds_on_a_slot_gap(pg_conn, test_space):
    """Touches the space-wide row (entity_type_uuid IS NULL), which is shared —
    so it restores whatever it found rather than assuming there was none."""
    from vitalgraph.db.sparql_sql.fast_slot_filter import (
        release_whole_space_block_if_complete, take_slot_sort_block)
    sid = test_space
    had = await _blocked(pg_conn, sid, None)
    covs = [{"entity_type_uuid": uuid.uuid4(), "in_table": 5, "of_type": 5}]
    await take_slot_sort_block(pg_conn, sid, None, reason="whole space")
    assert not await release_whole_space_block_if_complete(
        pg_conn, sid, covs, slot_shortfall=2), "must refuse while short"
    assert await _blocked(pg_conn, sid, None)
    assert await release_whole_space_block_if_complete(
        pg_conn, sid, covs, slot_shortfall=0), "and release once clean"
    assert not await _blocked(pg_conn, sid, None)
    if had:
        await take_slot_sort_block(pg_conn, sid, None, reason="restored by test")
