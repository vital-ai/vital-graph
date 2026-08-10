"""Integration tests: `{space}_frame_entity` stays in sync when quads are DELETED.

The companion to `test_edge_table_sync_on_delete.py`, for the other derived
traversal table. `frame_entity` records a frame's source and destination
entities, derived from slots whose `hasKGSlotType` is `urn:hasSourceEntity` /
`urn:hasDestinationEntity` and whose `hasEntitySlotValue` points at an entity.

It is maintained by the same subject-driven hooks as the edge table
(`sync_frame_entity_before_delete` / `sync_frame_entity_after_edge_insert`,
called from `execute_sparql_update`), so it has the same exposure: a delete whose
subjects are bound by a WHERE clause cannot enumerate them, and nothing removes
the rows their deletion invalidated (`issues/064`).

It is a second-order derivation — built from the edge table, which is itself
derived from quads — so it can be wrong either because its own maintenance
missed something or because the edge table underneath it did.

Assertions are REFERENTIAL, for the same reason as the edge tests: a stale row
is an extra row, so any count comparison reads a table containing them as
healthy.

See planning/planning_performance/edge_table_integrity_bug.md
"""

from __future__ import annotations

import pytest
from rdflib import URIRef

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

CORE = "http://vital.ai/ontology/vital-core#"
KG = "http://vital.ai/ontology/haley-ai-kg#"

HAS_EDGE_SOURCE = URIRef(f"{CORE}hasEdgeSource")
HAS_EDGE_DEST = URIRef(f"{CORE}hasEdgeDestination")
VITALTYPE = URIRef(f"{CORE}vitaltype")
EDGE_HAS_SLOT = URIRef(f"{KG}Edge_hasKGSlot")

HAS_SLOT_TYPE = URIRef(f"{KG}hasKGSlotType")
HAS_ENTITY_SLOT_VALUE = URIRef(f"{KG}hasEntitySlotValue")
SOURCE_ENTITY = URIRef("urn:hasSourceEntity")
DEST_ENTITY = URIRef("urn:hasDestinationEntity")

GRAPH = URIRef("urn:test:frame_entity_delete_graph")


async def _fe_rows(conn, space_id: str) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {space_id}_frame_entity")


async def _stale_fe_rows(conn, space_id: str) -> int:
    """frame_entity rows whose defining slot chain no longer exists.

    A row is valid only while its frame still reaches a slot typed
    `urn:hasSourceEntity` carrying the recorded source entity. Checking the
    chain rather than the row count is the whole point: a stale row is an EXTRA
    row, so `frame_entity_drift` — which compares counts — reads a table full of
    them as healthy.
    """
    return await conn.fetchval(
        f"""
        SELECT count(*) FROM {space_id}_frame_entity fe
        WHERE NOT EXISTS (
            SELECT 1
            FROM {space_id}_edge e
            JOIN {space_id}_rdf_quad st ON st.subject_uuid = e.dest_node_uuid
            JOIN {space_id}_term st_p ON st_p.term_uuid = st.predicate_uuid
            JOIN {space_id}_term st_o ON st_o.term_uuid = st.object_uuid
            JOIN {space_id}_rdf_quad sv ON sv.subject_uuid = e.dest_node_uuid
            JOIN {space_id}_term sv_p ON sv_p.term_uuid = sv.predicate_uuid
            WHERE e.source_node_uuid = fe.frame_uuid
              AND e.context_uuid = fe.context_uuid
              AND st_p.term_text = $1
              AND st_o.term_text = $2
              AND sv_p.term_text = $3
              AND sv.object_uuid = fe.source_entity_uuid)
        """,
        str(HAS_SLOT_TYPE), str(SOURCE_ENTITY), str(HAS_ENTITY_SLOT_VALUE),
    )


async def _seed_relation_frames(space_impl, space_id: str, n: int, tag: str):
    """Frames carrying a source-entity and destination-entity slot each.

    This is the shape frame_entity is derived from; both slots must be present
    or the resync's HAVING clause drops the frame entirely.
    """
    quads = []
    for i in range(n):
        frame = URIRef(f"urn:test:{tag}:frame:{i}")
        for role, slot_type in (("src", SOURCE_ENTITY), ("dst", DEST_ENTITY)):
            slot = URIRef(f"urn:test:{tag}:slot:{role}:{i}")
            edge = URIRef(f"urn:test:{tag}:edge:{role}:{i}")
            entity = URIRef(f"urn:test:{tag}:entity:{role}:{i}")
            quads += [
                (edge, VITALTYPE, EDGE_HAS_SLOT, GRAPH),
                (edge, HAS_EDGE_SOURCE, frame, GRAPH),
                (edge, HAS_EDGE_DEST, slot, GRAPH),
                (slot, HAS_SLOT_TYPE, slot_type, GRAPH),
                (slot, HAS_ENTITY_SLOT_VALUE, entity, GRAPH),
            ]
    await space_impl.add_rdf_quads_batch(space_id, quads)


class TestFrameEntitySyncOnDelete:

    async def test_seed_populates_frame_entity(
        self, test_space, space_impl, pg_conn
    ):
        """The fixture shape actually produces frame_entity rows.

        Guards the rest of this file. frame_entity is empty in every existing
        performance fixture — `resync_all_auxiliary_tables` reports
        `frame_entity_rows=0` for all of them — because none carry
        source/destination entity slots. A deletion test against an empty table
        passes no matter how broken the maintenance is.
        """
        await _seed_relation_frames(space_impl, test_space, 4, "seedcheck")
        rows = await _fe_rows(pg_conn, test_space)
        assert rows >= 4, (
            f"seed produced {rows} frame_entity rows; the rest of this file "
            f"would pass vacuously")
        assert await _stale_fe_rows(pg_conn, test_space) == 0

    async def test_delete_where_bound_leaves_no_stale_frame_entity_rows(
        self, test_space, space_impl, pg_conn
    ):
        """DELETE WHERE with a variable subject — the exposed case.

        Removes the `hasEntitySlotValue` quads that give each frame its source
        entity. Every frame_entity row recording one is invalidated; nothing
        enumerated those subjects, so nothing removed the rows.
        """
        await _seed_relation_frames(space_impl, test_space, 5, "bound")
        assert await _fe_rows(pg_conn, test_space) >= 5
        assert await _stale_fe_rows(pg_conn, test_space) == 0

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> "
            f"{{ ?slot <{HAS_ENTITY_SLOT_VALUE}> ?entity }} }}")

        stale = await _stale_fe_rows(pg_conn, test_space)
        assert stale == 0, (
            f"{stale} frame_entity row(s) still record a source entity whose "
            f"defining slot chain is gone. Entity-relationship queries will "
            f"return those entities as related when they no longer are, and no "
            f"count-based check can see it — a stale row is an EXTRA row. "
            f"See issues/064.")

    async def test_drop_graph_leaves_no_frame_entity_rows(
        self, test_space, space_impl, pg_conn
    ):
        """DROP GRAPH names no subjects, so per-subject hooks never fire."""
        await _seed_relation_frames(space_impl, test_space, 3, "dropped")
        assert await _fe_rows(pg_conn, test_space) >= 3

        await space_impl.execute_sparql_update(
            test_space, f"DROP GRAPH <{GRAPH}>")

        left = await pg_conn.fetchval(
            f"""
            SELECT count(*) FROM {test_space}_frame_entity fe
            JOIN {test_space}_term t ON t.term_uuid = fe.context_uuid
            WHERE t.term_text = $1
            """, str(GRAPH))
        assert left == 0, (
            f"{left} frame_entity row(s) survived DROP GRAPH — the frames they "
            f"describe no longer exist at all")
