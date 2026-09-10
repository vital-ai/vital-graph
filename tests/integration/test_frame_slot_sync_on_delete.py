"""Integration tests: `{space}_frame_slot` stays in sync when quads are DELETED.

The companion to `test_edge_table_sync_on_delete.py`, for the other derived
traversal table. `frame_slot` records a frame's source and destination
entities, derived from slots whose `hasKGSlotType` is `urn:hasSourceEntity` /
`urn:hasDestinationEntity` and whose `hasEntitySlotValue` points at an entity.

It is maintained by the same subject-driven hooks as the edge table
(`sync_frame_slot_before_delete` / `sync_frame_slot_after_edge_insert`,
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

GRAPH = URIRef("urn:test:frame_slot_delete_graph")


async def _fe_rows(conn, space_id: str) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {space_id}_frame_slot")


async def _stale_fe_rows(conn, space_id: str) -> int:
    """frame_slot rows whose defining slot chain no longer exists.

    A row is valid only while its frame still reaches THAT slot, and the slot
    still carries both the recorded role and the recorded entity. Checking the
    chain rather than the row count is the whole point: a stale row is an EXTRA
    row, so `frame_slot_drift` — which compares counts — reads a table full of
    them as healthy.

    Role-agnostic by construction. The `frame_slot` version of this check
    named `urn:hasSourceEntity` in its SQL, which is a DATA value in this
    dataset and not part of any schema (`issues/183`); `frame_slot` carries the
    role as `role_uuid`, so the row supplies it and the query does not.
    """
    return await conn.fetchval(
        f"""
        SELECT count(*) FROM {space_id}_frame_slot fs
        WHERE NOT EXISTS (
            SELECT 1
            FROM {space_id}_edge e
            JOIN {space_id}_rdf_quad st
              ON st.subject_uuid = fs.slot_uuid
             AND st.object_uuid = fs.role_uuid
             AND st.predicate_uuid = (SELECT term_uuid FROM {space_id}_term
                                      WHERE term_text = $1)
            JOIN {space_id}_rdf_quad sv
              ON sv.subject_uuid = fs.slot_uuid
             AND sv.object_uuid = fs.entity_uuid
             AND sv.predicate_uuid = (SELECT term_uuid FROM {space_id}_term
                                      WHERE term_text = $2)
            WHERE e.source_node_uuid = fs.frame_uuid
              AND e.dest_node_uuid = fs.slot_uuid
              AND e.context_uuid = fs.context_uuid)
        """,
        str(HAS_SLOT_TYPE), str(HAS_ENTITY_SLOT_VALUE),
    )


async def _seed_relation_frames(space_impl, space_id: str, n: int, tag: str):
    """Frames carrying a source-entity and destination-entity slot each.

    This is the shape frame_slot is derived from — one row per SLOT, so a
    frame with a source and a destination slot contributes two.
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


class TestFrameSlotSyncOnDelete:

    async def test_seed_populates_frame_slot(
        self, test_space, space_impl, pg_conn
    ):
        """The fixture shape actually produces frame_slot rows.

        Guards the rest of this file. frame_slot's predecessor was empty in every existing
        performance fixture — `resync_all_auxiliary_tables` reports
        `frame_slot_rows=0` for all of them — because none carry
        source/destination entity slots. A deletion test against an empty table
        passes no matter how broken the maintenance is.
        """
        await _seed_relation_frames(space_impl, test_space, 4, "seedcheck")
        rows = await _fe_rows(pg_conn, test_space)
        assert rows >= 8, (
            f"seed produced {rows} frame_slot rows; the rest of this file "
            f"would pass vacuously")
        assert await _stale_fe_rows(pg_conn, test_space) == 0

    async def test_delete_where_bound_leaves_no_stale_frame_slot_rows(
        self, test_space, space_impl, pg_conn
    ):
        """DELETE WHERE with a variable subject — the exposed case.

        Removes the `hasEntitySlotValue` quads that give each frame its source
        entity. Every frame_slot row recording one is invalidated; nothing
        enumerated those subjects, so nothing removed the rows.

        DEFERRED, NOT SYNCHRONOUS — and this half was briefly cleaned by
        NOTHING. Moving the sweep out of `execute_sparql_update` (`issues/079`,
        the inline pass was cancelled by the command timeout and cleaned
        nothing) took the edge sweep to `MaintenanceJob` and dropped the
        frame_slot sweep entirely: `cleanup_stale_frame_slot` was left with
        no caller anywhere in the codebase. Asserting the sweep runs AND clears
        is what makes that visible, because an uncalled function is invisible to
        every test that only checks end state after a maintenance tick.
        """
        from vitalgraph.db.sparql_sql.sync_edge_table import take_sweep_pending
        from vitalgraph.db.sparql_sql.sync_frame_slot_table import (
            cleanup_stale_frame_slot)

        await _seed_relation_frames(space_impl, test_space, 5, "bound")
        assert await _fe_rows(pg_conn, test_space) >= 5
        assert await _stale_fe_rows(pg_conn, test_space) == 0
        take_sweep_pending()                    # ignore marks from seeding

        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE WHERE {{ GRAPH <{GRAPH}> "
            f"{{ ?slot <{HAS_ENTITY_SLOT_VALUE}> ?entity }} }}")

        assert test_space in take_sweep_pending(), (
            "the WHERE-bound delete did not mark the space for the referential "
            "sweep, so nothing will ever clean up after it (issues/064)")

        await cleanup_stale_frame_slot(pg_conn, test_space)

        stale = await _stale_fe_rows(pg_conn, test_space)
        assert stale == 0, (
            f"{stale} frame_slot row(s) still record a source entity whose "
            f"defining slot chain is gone. Entity-relationship queries will "
            f"return those entities as related when they no longer are, and no "
            f"count-based check can see it — a stale row is an EXTRA row. "
            f"See issues/064.")

    async def test_drop_graph_leaves_no_frame_slot_rows(
        self, test_space, space_impl, pg_conn
    ):
        """DROP GRAPH names no subjects, so per-subject hooks never fire."""
        await _seed_relation_frames(space_impl, test_space, 3, "dropped")
        assert await _fe_rows(pg_conn, test_space) >= 3

        await space_impl.execute_sparql_update(
            test_space, f"DROP GRAPH <{GRAPH}>")

        left = await pg_conn.fetchval(
            f"""
            SELECT count(*) FROM {test_space}_frame_slot fe
            JOIN {test_space}_term t ON t.term_uuid = fe.context_uuid
            WHERE t.term_text = $1
            """, str(GRAPH))
        assert left == 0, (
            f"{left} frame_slot row(s) survived DROP GRAPH — the frames they "
            f"describe no longer exist at all")

    async def test_slot_value_update_refreshes_frame_slot(
        self, test_space, space_impl, pg_conn
    ):
        """Incremental CRUD: change a slot's entity value on an EXISTING frame.

        The frame is not a subject of this write — only the slot is — so a sync
        that matches the frame position alone never fires, and frame_slot
        keeps asserting the OLD entity. It still has a row, so nothing looks
        wrong; the row just describes a relationship that has changed.

        This is the case the frame-position-only filter missed. Creating a frame
        works either way, because a new frame carries its own type triple and is
        therefore a subject of its own creation.
        """
        frame = URIRef("urn:test:crud:frame")
        sslot = URIRef("urn:test:crud:slot:src")
        dslot = URIRef("urn:test:crud:slot:dst")
        old_entity = URIRef("urn:test:crud:entity:old")
        new_entity = URIRef("urn:test:crud:entity:new")

        quads = [(frame, VITALTYPE, URIRef(f"{KG}KGFrame"), GRAPH)]
        for slot, edge, stype, ent in (
            (sslot, URIRef("urn:test:crud:edge:src"), SOURCE_ENTITY, old_entity),
            (dslot, URIRef("urn:test:crud:edge:dst"), DEST_ENTITY,
             URIRef("urn:test:crud:entity:d")),
        ):
            quads += [
                (edge, VITALTYPE, EDGE_HAS_SLOT, GRAPH),
                (edge, HAS_EDGE_SOURCE, frame, GRAPH),
                (edge, HAS_EDGE_DEST, slot, GRAPH),
                (slot, HAS_SLOT_TYPE, stype, GRAPH),
                (slot, HAS_ENTITY_SLOT_VALUE, ent, GRAPH),
            ]
        await space_impl.add_rdf_quads_batch(test_space, quads)
        assert await _fe_rows(pg_conn, test_space) >= 1, "seed produced no row"

        # Repoint the source slot at a different entity — the frame itself is
        # untouched by this update.
        await space_impl.execute_sparql_update(
            test_space,
            f"DELETE DATA {{ GRAPH <{GRAPH}> {{ "
            f"<{sslot}> <{HAS_ENTITY_SLOT_VALUE}> <{old_entity}> . }} }}")
        await space_impl.execute_sparql_update(
            test_space,
            f"INSERT DATA {{ GRAPH <{GRAPH}> {{ "
            f"<{sslot}> <{HAS_ENTITY_SLOT_VALUE}> <{new_entity}> . }} }}")

        stale = await _stale_fe_rows(pg_conn, test_space)
        assert stale == 0, (
            f"{stale} frame_slot row(s) still name the old entity after the "
            f"slot was repointed. Relationship queries return a stale answer "
            f"and the row count is unchanged, so no drift check can see it.")
        # `frame_slot` has no `source_entity_uuid`: the role is a VALUE in
        # `role_uuid`, one row per slot, so the source row is selected by role
        # rather than read off a column named after it (`issues/183`).
        row = await pg_conn.fetchrow(
            f"""
            SELECT t.term_text AS src FROM {test_space}_frame_slot fe
            JOIN {test_space}_term t ON t.term_uuid = fe.entity_uuid
            JOIN {test_space}_term tf ON tf.term_uuid = fe.frame_uuid
            JOIN {test_space}_term tr ON tr.term_uuid = fe.role_uuid
            WHERE tf.term_text = $1 AND tr.term_text = $2
            """, str(frame), str(SOURCE_ENTITY))
        assert row and row["src"] == str(new_entity), (
            f"frame_slot source is {row['src'] if row else None}, "
            f"expected {new_entity}")
