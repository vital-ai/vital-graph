"""A frame_slot table can be the right SIZE and entirely wrong (issues/041).

`frame_slot_drift` compares counts. The failure this exists for has identical
counts: a space reloaded in place — or under a new graph URI — leaves the derived
table a faithful materialisation of the PREVIOUS contents. Same rows, disjoint
set, drift zero, and every frame traversal returning nothing with no error.

That gap was closed for `{space}_edge` in 2026-08-08 and the issue recorded that
the same argument applied to `frame_slot`, which had no equivalent probe. These
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
import pytest_asyncio
from rdflib import URIRef

from vitalgraph.db.sparql_sql.sync_frame_slot_table import (
    frame_slot_drift,
    frame_slot_orphan_rate,
    resync_frame_slot_table,
)

from .conftest import skip_no_infra
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

# The threshold the maintenance job and the repair script both use.
STALE = 0.5


RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
KG_FRAME = URIRef("http://vital.ai/ontology/haley-ai-kg#KGFrame")
HAS_EDGE_SOURCE = URIRef("http://vital.ai/ontology/vital-core#hasEdgeSource")
HAS_EDGE_DEST = URIRef("http://vital.ai/ontology/vital-core#hasEdgeDestination")
HAS_SLOT_TYPE = URIRef("http://vital.ai/ontology/haley-ai-kg#hasKGSlotType")
HAS_ENTITY_SLOT_VALUE = URIRef("http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue")
SOURCE_ENTITY = URIRef("urn:hasSourceEntity")
DEST_ENTITY = URIRef("urn:hasDestinationEntity")
GRAPH = URIRef("urn:test:frame_slot_staleness")
N_FRAMES = 30


def _connection_frame(i: int):
    """One binary connection frame: frame -> {src,dst} slot -> entity."""
    f, s, d = (URIRef(f"urn:test:st_{k}_{i}") for k in ("frame", "sslot", "dslot"))
    se, de = URIRef(f"urn:test:st_sedge_{i}"), URIRef(f"urn:test:st_dedge_{i}")
    return [
        (f, RDF_TYPE, KG_FRAME, GRAPH),
        (se, HAS_EDGE_SOURCE, f, GRAPH), (se, HAS_EDGE_DEST, s, GRAPH),
        (de, HAS_EDGE_SOURCE, f, GRAPH), (de, HAS_EDGE_DEST, d, GRAPH),
        (s, HAS_SLOT_TYPE, SOURCE_ENTITY, GRAPH),
        (s, HAS_ENTITY_SLOT_VALUE, URIRef(f"urn:test:st_src_{i}"), GRAPH),
        (d, HAS_SLOT_TYPE, DEST_ENTITY, GRAPH),
        (d, HAS_ENTITY_SLOT_VALUE, URIRef(f"urn:test:st_dst_{i}"), GRAPH),
    ]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def populated_space(make_space, space_impl, pg_pool):
    """A space of this module's OWN, with a small, healthy frame_slot.

    It used to borrow "the first space on this stack whose frame_slot has
    rows". That made the result depend on whatever else was there: during a
    suite run it picked other tests' transient `inttest_*` spaces, one of
    which held 60 frame_slot rows its quads no longer produce (drift
    `0 == 60`, orphan rate 1.0), and on a dataset volume holding only
    `sp_lead_synth_100k` it rewrote a 4M-row table and ran for over 15
    minutes. Every case here is rolled back, but a real fixture is still the
    wrong thing to corrupt.
    """
    sid = await make_space()
    quads = [q for i in range(N_FRAMES) for q in _connection_frame(i)]
    await space_impl.add_rdf_quads_batch(sid, quads)
    async with pg_pool.acquire() as conn:
        rows = await conn.fetchval(f"SELECT count(*) FROM {space_prefix(sid)}_frame_slot")
    # Two rows per binary connection frame, one per slot. Without them, "a
    # healthy table reads zero" would pass on an empty table.
    assert rows == 2 * N_FRAMES, f"fixture produced {rows} frame_slot rows"
    return sid


async def test_a_healthy_table_reads_zero(pg_conn, populated_space):
    """Without this, a probe that always returns 1.0 would pass everything else."""
    sid = populated_space
    assert await frame_slot_orphan_rate(pg_conn, sid) == 0.0


@pytest.mark.parametrize("column,mode", [
    ("frame_uuid", "reloaded with new node URIs"),
    ("context_uuid", "reloaded under a different graph URI"),
], ids=["identity", "context"])
async def test_staleness_is_detected_where_drift_is_blind(pg_conn, populated_space, column, mode):
    sid = populated_space
    table = f"{space_prefix(sid)}_frame_slot"

    # Rolled back: this deliberately corrupts the fixture table.
    tx = pg_conn.transaction()
    await tx.start()
    try:
        await pg_conn.execute(f"UPDATE {table} SET {column} = gen_random_uuid()")
        rate = await frame_slot_orphan_rate(pg_conn, sid)
        expected, actual = await frame_slot_drift(pg_conn, sid)
        assert rate > STALE, f"{mode} not detected: orphan rate {rate}"
        # The whole reason the probe exists: the count check calls this healthy.
        assert expected == actual, (
            "this fixture no longer demonstrates the point — drift now sees the "
            "fault, so the referential probe is not the only thing that can")
    finally:
        await tx.rollback()

    assert await frame_slot_orphan_rate(pg_conn, sid) == 0.0, "rollback failed"


async def test_resync_repairs_a_stale_table(pg_conn, populated_space):
    """The maintenance job's message points an operator at a repair. It has to
    work: the script only ever repaired an EMPTY table, so the one fault it could
    not fix was this one."""
    sid = populated_space
    table = f"{space_prefix(sid)}_frame_slot"
    before = await pg_conn.fetchval(f"SELECT count(*) FROM {table}")

    tx = pg_conn.transaction()
    await tx.start()
    try:
        await pg_conn.execute(f"UPDATE {table} SET context_uuid = gen_random_uuid()")
        assert await frame_slot_orphan_rate(pg_conn, sid) > STALE
        await resync_frame_slot_table(pg_conn, sid)
        assert await frame_slot_orphan_rate(pg_conn, sid) == 0.0
        assert await pg_conn.fetchval(f"SELECT count(*) FROM {table}") == before
    finally:
        await tx.rollback()
