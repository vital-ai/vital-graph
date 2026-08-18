"""A frame_entity table can be the right SIZE and entirely wrong (issues/041).

`frame_entity_drift` compares counts. The failure this exists for has identical
counts: a space reloaded in place — or under a new graph URI — leaves the derived
table a faithful materialisation of the PREVIOUS contents. Same rows, disjoint
set, drift zero, and every frame traversal returning nothing with no error.

That gap was closed for `{space}_edge` in 2026-08-08 and the issue recorded that
the same argument applied to `frame_entity`, which had no equivalent probe. These
tests cover the probe that fills it, and the repair path that the maintenance
job's error message now names.

TWO FAILURE MODES, and the second is the one that got away the first time. A
reload with new node URIs breaks identity; a GRAPH RENAME leaves identity intact
and moves the context. An identity-only probe reports a healthy 0% for the
second, which is exactly how the edge probe was wrong when first written —
`sp_lead_synth_100k` read 0% while a criterion with 9,220 expected matches
returned 0 rows in 154 seconds.

WHY IT IS ANCHORED ON `hasEdgeSource`. The first version of this probe asked
whether the frame still carried a `vitaltype` quad and read 100% on
`prolog_spike_frames` — a space with no vitaltype quads at all, whose rows all
resolve. Nothing obliges a frame to carry a type. The probe asks about the quad
that CREATES the row instead.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sync_frame_entity_table import (
    frame_entity_drift,
    frame_entity_orphan_rate,
    resync_frame_entity_table,
)

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

# The threshold the maintenance job and the repair script both use.
STALE = 0.5


async def _populated_space(conn):
    """A space on this stack whose frame_entity has rows, or skip."""
    rows = await conn.fetch("SELECT space_id FROM space ORDER BY space_id")
    for r in rows:
        sid = r["space_id"]
        if not await conn.fetchval(
                "SELECT 1 FROM pg_tables WHERE tablename = $1", f"{sid}_frame_entity"):
            continue
        if await conn.fetchval(f"SELECT count(*) FROM {sid}_frame_entity"):
            return sid
    pytest.skip("no space on this stack has a populated frame_entity")


async def test_a_healthy_table_reads_zero(pg_conn):
    """Without this, a probe that always returns 1.0 would pass everything else."""
    sid = await _populated_space(pg_conn)
    assert await frame_entity_orphan_rate(pg_conn, sid) == 0.0


@pytest.mark.parametrize("column,mode", [
    ("frame_uuid", "reloaded with new node URIs"),
    ("context_uuid", "reloaded under a different graph URI"),
], ids=["identity", "context"])
async def test_staleness_is_detected_where_drift_is_blind(pg_conn, column, mode):
    sid = await _populated_space(pg_conn)
    table = f"{sid}_frame_entity"

    # Rolled back: this deliberately corrupts a real fixture table.
    tx = pg_conn.transaction()
    await tx.start()
    try:
        await pg_conn.execute(f"UPDATE {table} SET {column} = gen_random_uuid()")
        rate = await frame_entity_orphan_rate(pg_conn, sid)
        expected, actual = await frame_entity_drift(pg_conn, sid)
        assert rate > STALE, f"{mode} not detected: orphan rate {rate}"
        # The whole reason the probe exists: the count check calls this healthy.
        assert expected == actual, (
            "this fixture no longer demonstrates the point — drift now sees the "
            "fault, so the referential probe is not the only thing that can")
    finally:
        await tx.rollback()

    assert await frame_entity_orphan_rate(pg_conn, sid) == 0.0, "rollback failed"


async def test_resync_repairs_a_stale_table(pg_conn):
    """The maintenance job's message points an operator at a repair. It has to
    work: the script only ever repaired an EMPTY table, so the one fault it could
    not fix was this one."""
    sid = await _populated_space(pg_conn)
    table = f"{sid}_frame_entity"
    before = await pg_conn.fetchval(f"SELECT count(*) FROM {table}")

    tx = pg_conn.transaction()
    await tx.start()
    try:
        await pg_conn.execute(f"UPDATE {table} SET context_uuid = gen_random_uuid()")
        assert await frame_entity_orphan_rate(pg_conn, sid) > STALE
        await resync_frame_entity_table(pg_conn, sid)
        assert await frame_entity_orphan_rate(pg_conn, sid) == 0.0
        assert await pg_conn.fetchval(f"SELECT count(*) FROM {table}") == before
    finally:
        await tx.rollback()
