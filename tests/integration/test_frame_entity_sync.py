"""Integration tests: {space}_frame_entity stays in sync with rdf_quad.

frame_entity is the binary connection-frame optimization (a frame with a
`urn:hasSourceEntity` entity slot and a `urn:hasDestinationEntity` entity slot,
each `hasEntitySlotValue` → an entity). Like the edge table, it was only kept in
sync by the bulk write path; these tests cover the non-bulk paths + the
drift/backfill self-heal.

frame_entity is derived from the edge table, so the edge sync runs first.

Requires PostgreSQL. See planning/planning_performance/frame_entity_integrity_plan.md
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
GRAPH = URIRef("urn:test:frame_entity_graph")


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
    """Return (source_text, dest_text) for the frame's frame_entity row, or None."""
    return await conn.fetchrow(
        f"""
        SELECT ts.term_text AS src, td.term_text AS dst
        FROM {space_id}_frame_entity fe
        JOIN {space_id}_term tf ON tf.term_uuid = fe.frame_uuid
        JOIN {space_id}_term ts ON ts.term_uuid = fe.source_entity_uuid
        JOIN {space_id}_term td ON td.term_uuid = fe.dest_entity_uuid
        WHERE tf.term_text = $1
        """,
        frame_uri,
    )


class TestFrameEntitySync:
    async def test_batch_insert_syncs_frame_entity(
        self, test_space, space_impl, pg_conn
    ):
        """A binary connection frame inserted via add_rdf_quads_batch (non-bulk)
        produces a frame_entity row."""
        quads, frame, e1, e2 = _connection_frame_quads("batch")
        await space_impl.add_rdf_quads_batch(test_space, quads)

        row = await _fe_row(pg_conn, test_space, str(frame))
        assert row is not None, "frame_entity row missing after batch insert"
        assert row["src"] == str(e1)
        assert row["dst"] == str(e2)

    async def test_backfill_repairs_frame_entity_drift(
        self, test_space, space_impl, pg_conn
    ):
        """frame_entity_drift detects a stale table and backfill_frame_entity_table
        repairs it without a TRUNCATE (the maintenance self-heal path)."""
        from vitalgraph.db.sparql_sql.sync_frame_entity_table import (
            frame_entity_drift, backfill_frame_entity_table,
        )

        quads, frame, e1, e2 = _connection_frame_quads("drift")
        await space_impl.add_rdf_quads_batch(test_space, quads)
        assert await _fe_row(pg_conn, test_space, str(frame)) is not None

        # Simulate drift: delete the frame_entity row while the quads remain.
        await pg_conn.execute(
            f"DELETE FROM {test_space}_frame_entity WHERE frame_uuid IN "
            f"(SELECT term_uuid FROM {test_space}_term WHERE term_text = $1)",
            str(frame),
        )
        assert await _fe_row(pg_conn, test_space, str(frame)) is None
        expected, actual = await frame_entity_drift(pg_conn, test_space)
        assert expected > actual, "drift should be detected"

        added = await backfill_frame_entity_table(pg_conn, test_space)
        assert added >= 1
        row = await _fe_row(pg_conn, test_space, str(frame))
        assert row is not None and row["src"] == str(e1) and row["dst"] == str(e2)

    async def test_sparql_insert_data_syncs_frame_entity(
        self, test_space, space_impl, pg_conn
    ):
        """A binary connection frame inserted via SPARQL INSERT DATA syncs
        frame_entity inline."""
        quads, frame, e1, e2 = _connection_frame_quads("sparql")
        triples = " ".join(f"<{s}> <{p}> <{o}> ." for s, p, o, _ in quads)
        ok = await space_impl.execute_sparql_update(
            test_space, f"INSERT DATA {{ GRAPH <{GRAPH}> {{ {triples} }} }}")
        assert ok
        row = await _fe_row(pg_conn, test_space, str(frame))
        assert row is not None, "frame_entity row missing after SPARQL INSERT DATA"
        assert row["src"] == str(e1) and row["dst"] == str(e2)
