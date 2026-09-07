"""Measuring a space must release its WHOLE-SPACE block, or the gate deadlocks.

`issues/167`. `migrate_slot_sort_blocks` seeds a whole-space block
(`entity_type_uuid IS NULL`) for any space with no coverage rows — which is
EVERY space at upgrade. `slot_sort_is_blocked` matches

    entity_type_uuid IS NULL OR entity_type_uuid = $2

so that one row declines every type however complete they measure.

`record_slot_sort_coverage` releases only the PER-TYPE block for a type it just
measured. Before this test, the only code that released a whole-space block was
`resync_all` — which takes one itself. A block seeded by the migration therefore
had NO RELEASER: the backfill script would measure everything, report
`fast_path: ON`, and the fast path would still be off.

FOUND ON A PRODUCTION DEPLOY, not here: the shape stayed at a 60 s timeout after
a run that reported success. It was missed locally because both stacks already
had per-type coverage rows, so the migration seeded per-type blocks rather than
whole-space ones — the upgrade state was never reproduced.

That is what this test is: the upgrade state, reproduced.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest

from vitalgraph.db.sparql_sql.fast_slot_filter import (
    record_slot_sort_coverage, slot_sort_is_blocked, take_slot_sort_block)

pytestmark = pytest.mark.asyncio(loop_scope="session")

_TYPE = "urn:test:entity:Widget"


async def test_a_whole_space_block_declines_a_complete_type(pg_conn, test_space):
    """The deadlock's mechanism, stated as an assertion.

    A type measured COMPLETE releases its own block — and stays blocked, because
    the space-wide row still matches it.
    """
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid

    await take_slot_sort_block(pg_conn, sp, None, reason="coverage never measured")
    await record_slot_sort_coverage(pg_conn, sp, _term_uuid(_TYPE), 500, 500)

    assert await slot_sort_is_blocked(pg_conn, sp, _TYPE), (
        "precondition: a whole-space block declines even a complete type — if "
        "this fails the gate no longer works that way and the rest is moot")

    rows = await pg_conn.fetch(
        "SELECT entity_type_uuid FROM slot_sort_block WHERE space_id = $1", sp)
    assert [r["entity_type_uuid"] for r in rows] == [None], (
        "the per-type block was released and only the space-wide one remains — "
        "which is exactly the state nothing could clear")


async def test_the_backfill_script_releases_it(pg_conn, test_space):
    """The fix. Measuring the space clears the block whose reason no longer holds.

    Released on HAVING MEASURED, not on everything being complete: the block
    says "coverage never measured", and once measured that is false whatever the
    result. A short type keeps its own per-type block.
    """
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    await take_slot_sort_block(pg_conn, sp, None, reason="coverage never measured")

    import sys, os
    sys.path.insert(0, os.getcwd())
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bsc", os.path.join(os.getcwd(), "scripts",
                            "backfill_slot_sort_coverage.py"))
    bsc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bsc)

    async def one_complete_type(conn, space_id, **kw):
        from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
        return [{"entity_type_uuid": _term_uuid(_TYPE),
                 "in_table": 500, "of_type": 500}]

    import vitalgraph.db.sparql_sql.sync_entity_slot_sort as S
    original = S.entity_slot_sort_all_types
    S.entity_slot_sort_all_types = one_complete_type
    bsc.entity_slot_sort_all_types = one_complete_type
    try:
        res = await bsc.process_space(pg_conn, sp, dry_run=False,
                                      record_only=True, max_batches=1,
                                      batch_size=None)
    finally:
        S.entity_slot_sort_all_types = original

    assert res["space_block_released"] is True, res
    assert res["fast_path"] == "ON", (
        f"reported {res['fast_path']} — the script must not claim the fast path "
        f"is on while a whole-space block still declines every query: {res}")
    assert not await slot_sort_is_blocked(pg_conn, sp, _TYPE)


async def test_a_short_type_keeps_its_own_block_after_the_release(
        pg_conn, test_space):
    """Releasing the space-wide block must not serve something short."""
    sp = test_space
    await pg_conn.execute("DELETE FROM slot_sort_block WHERE space_id = $1", sp)
    from vitalgraph.db.sparql_sql.fast_slot_sort import _term_uuid
    await take_slot_sort_block(pg_conn, sp, None, reason="coverage never measured")
    await record_slot_sort_coverage(pg_conn, sp, _term_uuid(_TYPE), 3, 900)
    from vitalgraph.db.sparql_sql.fast_slot_filter import release_slot_sort_block
    await release_slot_sort_block(pg_conn, sp, None)

    assert await slot_sort_is_blocked(pg_conn, sp, _TYPE), (
        "a SHORT type must stay blocked by its own per-type row once the "
        "space-wide one is released")
