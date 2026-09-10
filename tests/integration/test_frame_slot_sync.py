"""Integration tests: {space}_frame_slot stays in sync with rdf_quad.

frame_slot is the binary connection-frame optimization (a frame with a
`urn:hasSourceEntity` entity slot and a `urn:hasDestinationEntity` entity slot,
each `hasEntitySlotValue` → an entity). Like the edge table, it was only kept in
sync by the bulk write path; these tests cover the non-bulk paths + the
drift/backfill self-heal.

frame_slot is derived from the edge table, so the edge sync runs first.

Requires PostgreSQL. See planning/planning_performance/frame_slot_integrity_plan.md
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

RDF_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
KG_FRAME = URIRef("http://vital.ai/ontology/haley-ai-kg#KGFrame")
HAS_EDGE_SOURCE = URIRef("http://vital.ai/ontology/vital-core#hasEdgeSource")
HAS_EDGE_DEST = URIRef("http://vital.ai/ontology/vital-core#hasEdgeDestination")
HAS_SLOT_TYPE = URIRef("http://vital.ai/ontology/haley-ai-kg#hasKGSlotType")
HAS_ENTITY_SLOT_VALUE = URIRef("http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue")
SOURCE_ENTITY = URIRef("urn:hasSourceEntity")
DEST_ENTITY = URIRef("urn:hasDestinationEntity")
GRAPH = URIRef("urn:test:frame_slot_graph")


def _connection_frame_quads(tag: str):
    """Return (quads, frame, src_entity, dst_entity) for one binary connection
    frame: frame --Edge_hasKGSlot--> {src,dst} slot --hasEntitySlotValue--> entity."""
    frame = URIRef(f"urn:test:cf_frame_{tag}")
    e1 = URIRef(f"urn:test:cf_src_{tag}")
    e2 = URIRef(f"urn:test:cf_dst_{tag}")
    sslot = URIRef(f"urn:test:cf_sslot_{tag}")
    dslot = URIRef(f"urn:test:cf_dslot_{tag}")
    sedge = URIRef(f"urn:test:cf_sedge_{tag}")
    dedge = URIRef(f"urn:test:cf_dedge_{tag}")
    quads = [
        (frame, RDF_TYPE, KG_FRAME, GRAPH),          # frame is a subject
        (sedge, HAS_EDGE_SOURCE, frame, GRAPH),      # frame → src slot
        (sedge, HAS_EDGE_DEST, sslot, GRAPH),
        (dedge, HAS_EDGE_SOURCE, frame, GRAPH),      # frame → dst slot
        (dedge, HAS_EDGE_DEST, dslot, GRAPH),
        (sslot, HAS_SLOT_TYPE, SOURCE_ENTITY, GRAPH),
        (sslot, HAS_ENTITY_SLOT_VALUE, e1, GRAPH),
        (dslot, HAS_SLOT_TYPE, DEST_ENTITY, GRAPH),
        (dslot, HAS_ENTITY_SLOT_VALUE, e2, GRAPH),
    ]
    return quads, frame, e1, e2


async def _fe_row(conn, space_id: str, frame_uri: str):
    """Return (source_text, dest_text) for the frame's slots, or None.

    `frame_slot` holds ONE ROW PER SLOT with the role in `role_uuid`, where
    `frame_slot` held one row per frame with the two roles as COLUMNS
    (`issues/183`). The two values are therefore pivoted out of two rows here,
    selected BY ROLE — which is a data value supplied by the caller, not a URI
    this query names.
    """
    return await conn.fetchrow(
        f"""
        SELECT
          max(t.term_text) FILTER (WHERE tr.term_text = $2) AS src,
          max(t.term_text) FILTER (WHERE tr.term_text = $3) AS dst
        FROM {space_id}_frame_slot fs
        JOIN {space_id}_term tf ON tf.term_uuid = fs.frame_uuid
        JOIN {space_id}_term tr ON tr.term_uuid = fs.role_uuid
        JOIN {space_id}_term t  ON t.term_uuid  = fs.entity_uuid
        WHERE tf.term_text = $1
        HAVING count(*) > 0
        """,
        frame_uri, str(SOURCE_ENTITY), str(DEST_ENTITY),
    )


class TestFrameEntitySync:
    async def test_batch_insert_syncs_frame_slot(
        self, test_space, space_impl, pg_conn
    ):
        """A binary connection frame inserted via add_rdf_quads_batch (non-bulk)
        produces a frame_slot row."""
        quads, frame, e1, e2 = _connection_frame_quads("batch")
        await space_impl.add_rdf_quads_batch(test_space, quads)

        row = await _fe_row(pg_conn, test_space, str(frame))
        assert row is not None, "frame_slot row missing after batch insert"
        assert row["src"] == str(e1)
        assert row["dst"] == str(e2)

    async def test_backfill_repairs_frame_slot_drift(
        self, test_space, space_impl, pg_conn
    ):
        """frame_slot_drift detects a stale table and backfill_frame_slot_table
        repairs it without a TRUNCATE (the maintenance self-heal path)."""
        from vitalgraph.db.sparql_sql.sync_frame_slot_table import (
            frame_slot_drift, backfill_frame_slot_table,
        )

        quads, frame, e1, e2 = _connection_frame_quads("drift")
        await space_impl.add_rdf_quads_batch(test_space, quads)
        assert await _fe_row(pg_conn, test_space, str(frame)) is not None

        # Simulate drift: delete the frame_slot row while the quads remain.
        await pg_conn.execute(
            f"DELETE FROM {test_space}_frame_slot WHERE frame_uuid IN "
            f"(SELECT term_uuid FROM {test_space}_term WHERE term_text = $1)",
            str(frame),
        )
        assert await _fe_row(pg_conn, test_space, str(frame)) is None
        expected, actual = await frame_slot_drift(pg_conn, test_space)
        assert expected > actual, "drift should be detected"

        added = await backfill_frame_slot_table(pg_conn, test_space)
        assert added >= 1
        row = await _fe_row(pg_conn, test_space, str(frame))
        assert row is not None and row["src"] == str(e1) and row["dst"] == str(e2)

    async def test_sparql_insert_data_syncs_frame_slot(
        self, test_space, space_impl, pg_conn
    ):
        """A binary connection frame inserted via SPARQL INSERT DATA syncs
        frame_slot inline."""
        quads, frame, e1, e2 = _connection_frame_quads("sparql")
        triples = " ".join(f"<{s}> <{p}> <{o}> ." for s, p, o, _ in quads)
        ok = await space_impl.execute_sparql_update(
            test_space, f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}")
        assert ok
        row = await _fe_row(pg_conn, test_space, str(frame))
        assert row is not None, "frame_slot row missing after SPARQL INSERT DATA"
        assert row["src"] == str(e1) and row["dst"] == str(e2)
