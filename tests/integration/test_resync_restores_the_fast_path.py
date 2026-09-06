"""A resync must leave the FILTER fast path ON, not merely not-broken.

`issues/161`. `resync_all` CLEARS the slot-sort coverage markers before
rebuilding — correctly, since a marker describing the previous contents would
let `fast_slot_filter` serve a confident subset mid-rebuild. It then rebuilt
`entity_slot_sort` in full and stopped, deferring re-establishment to "the
maintenance coverage probe afterwards".

That job runs on its own schedule and does not run at all for a space in
`VG_MAINTENANCE_EXCLUDE_SPACES`. So every repair, bulk import and
`repair_derived_tables.py` run switched the fast path OFF and left it off. It is
how `lead_nurture_100k` came to answer in >90s with a complete, correct table
underneath it, while the same queries took ~20ms once the marker was written by
hand.

The assertion is on the MARKER, not on a row count: a rebuilt table with no
marker is exactly the failure, and it looks identical to success from every
other angle.
"""
# pyright: reportArgumentType=false

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql.fast_slot_filter import (
    clear_slot_sort_coverage, slot_sort_coverage_is_complete)
from vitalgraph.db.sparql_sql.resync_all import (
    resync_all_auxiliary_tables as resync_all)

pytestmark = pytest.mark.asyncio(loop_scope="session")

_KG = "http://vital.ai/ontology/haley-ai-kg#"
_VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
_TYPE = "urn:test:entity:Widget"


@pytest_asyncio.fixture(loop_scope="session")
async def kg_space(pg_conn, test_space):
    """A minimal KG space: entities carrying a vitaltype."""
    sp = test_space
    g = uuid.uuid4()
    await pg_conn.execute(
        f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
        f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING",
        g, f"urn:g:{uuid.uuid4()}")
    pred, typ = uuid.uuid4(), uuid.uuid4()
    for tid, text in ((pred, _VITALTYPE), (typ, _TYPE)):
        await pg_conn.execute(
            f"INSERT INTO {sp}_term (term_uuid, term_text, term_type) "
            f"VALUES ($1,$2,'U') ON CONFLICT (term_uuid) DO NOTHING", tid, text)
    await pg_conn.executemany(
        f"INSERT INTO {sp}_rdf_quad (subject_uuid, predicate_uuid, object_uuid,"
        f" context_uuid) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
        [(uuid.uuid4(), pred, typ, g) for _ in range(5)])
    await pg_conn.execute(f"ANALYZE {sp}_rdf_quad")
    yield sp


async def test_resync_records_a_marker_for_every_type_it_finds(pg_conn, kg_space):
    """The contract: whatever the coverage probe reports, resync records.

    Driven through a stubbed probe rather than a hand-built KG fixture. The
    derivation needs a full entity -> edge -> frame -> slot shape to report any
    type at all, and building one here would test the FIXTURE. What changed in
    `resync_all` is that the probe's answer is now WRITTEN instead of discarded,
    and that is exactly what this pins.
    """
    sp = kg_space
    await clear_slot_sort_coverage(pg_conn, sp)
    assert not await slot_sort_coverage_is_complete(pg_conn, sp, _TYPE)

    import vitalgraph.db.sparql_sql.sync_entity_slot_sort as S
    original = S.entity_slot_sort_all_types
    fake_type = uuid.uuid4()

    async def one_complete_type(conn, space_id, **kw):
        return [{"entity_type_uuid": fake_type, "in_table": 7, "of_type": 7}]

    S.entity_slot_sort_all_types = one_complete_type
    try:
        result = await resync_all(pg_conn, sp)
    finally:
        S.entity_slot_sort_all_types = original

    row = await pg_conn.fetchrow(
        "SELECT complete FROM slot_sort_coverage "
        " WHERE space_id = $1 AND entity_type_uuid = $2", sp, fake_type)
    assert row is not None, (
        "resync_all cleared the markers and recorded none — the fast path is "
        "off for this space until an unrelated periodic job runs, and never if "
        "the space is maintenance-exempt")
    assert row["complete"] is True, "a fully covered type must mark complete"
    assert result["slot_sort_types_total"] == 1
    assert result["slot_sort_types_complete"] == 1


async def test_a_short_type_is_recorded_as_incomplete(pg_conn, kg_space):
    """Recording is not the same as asserting completeness. A short table must
    be written as INCOMPLETE, so the fast path keeps declining — a marker that
    could only ever say "complete" would be worse than none."""
    sp = kg_space
    await clear_slot_sort_coverage(pg_conn, sp)

    import vitalgraph.db.sparql_sql.sync_entity_slot_sort as S
    original = S.entity_slot_sort_all_types
    fake_type = uuid.uuid4()

    async def one_short_type(conn, space_id, **kw):
        return [{"entity_type_uuid": fake_type, "in_table": 3, "of_type": 900}]

    S.entity_slot_sort_all_types = one_short_type
    try:
        result = await resync_all(pg_conn, sp)
    finally:
        S.entity_slot_sort_all_types = original

    row = await pg_conn.fetchrow(
        "SELECT complete FROM slot_sort_coverage "
        " WHERE space_id = $1 AND entity_type_uuid = $2", sp, fake_type)
    assert row is not None and row["complete"] is False
    assert result["slot_sort_types_complete"] == 0


async def test_a_resync_failure_does_not_fail_the_resync(pg_conn, kg_space):
    """Recording is FAIL-SAFE and deliberately last.

    An unwritten marker leaves the filter path declining, which is slow and
    correct. Failing the whole resync over it would be worse than the cliff it
    prevents, so a broken coverage probe must not propagate.
    """
    sp = kg_space
    import vitalgraph.db.sparql_sql.sync_entity_slot_sort as S
    original = S.entity_slot_sort_all_types

    async def boom(*a, **k):
        raise RuntimeError("coverage probe unavailable")

    S.entity_slot_sort_all_types = boom
    try:
        result = await resync_all(pg_conn, sp)
    finally:
        S.entity_slot_sort_all_types = original
    assert result.get("slot_sort_types_total") == 0
    assert result.get("edge_rows") is not None, (
        "the rest of the resync must still have completed")
