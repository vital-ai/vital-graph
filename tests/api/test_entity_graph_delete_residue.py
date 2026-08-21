"""Does the issues/092 residue still reproduce through the API?

19 typeless grouping targets were found across 4 live spaces, three of them
made by test suites. The origin was established as a DELETE, not a write:
`delete_entity_graph_bulk` picks members with one query on one mutable
predicate, so anything outside that snapshot survives its root. Which of the
three possible misses produced those 19 was never established.

This drives the exact shape that produced one of them — the entity a
server-properties case creates, frames, and deletes in a `finally` — and then
looks at the rows.
"""

from __future__ import annotations

import uuid

import pytest

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://vital.ai/test/residue/"
HGU = "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI"


async def test_entity_graph_delete_leaves_no_residue(vg_client, test_space,
                                                     test_graph, pg_conn):
    entity_uri = f"{NS}entity_{uuid.uuid4().hex[:8]}"
    entity = KGEntity()
    entity.URI = entity_uri
    entity.name = "Residue Probe"

    cr = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[entity])
    assert cr.is_success, f"entity create failed: {cr.error_message}"

    frame = KGFrame()
    frame.URI = f"{NS}frame_{uuid.uuid4().hex[:8]}"
    frame.name = "Residue Probe Frame"
    fr = await vg_client.kgentities.create_entity_frames(
        space_id=test_space, graph_id=test_graph,
        entity_uri=entity_uri, objects=[frame])
    assert fr.is_success, f"frame create failed: {fr.error_message}"

    async def rows(uri):
        return await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_quad q "
            f"JOIN {test_space}_term t ON t.term_uuid = q.subject_uuid "
            f"WHERE t.term_text = $1", uri)

    async def pointing_at(uri):
        return await pg_conn.fetchval(
            f"SELECT count(*) FROM {test_space}_rdf_quad q "
            f"JOIN {test_space}_term tp ON tp.term_uuid = q.predicate_uuid "
            f"JOIN {test_space}_term to_ ON to_.term_uuid = q.object_uuid "
            f"WHERE tp.term_text = $1 AND to_.term_text = $2", HGU, uri)

    before_e, before_f = await rows(entity_uri), await rows(str(frame.URI))
    linked = await pointing_at(entity_uri)
    assert before_e and before_f, (before_e, before_f)
    assert linked, "the frame never got its grouping link — different bug"

    dr = await vg_client.kgentities.delete_kgentity(
        space_id=test_space, graph_id=test_graph, uri=entity_uri,
        delete_entity_graph=True)
    assert dr.is_success, f"delete failed: {dr.error_message}"

    after_e, after_f = await rows(entity_uri), await rows(str(frame.URI))
    residue = await pointing_at(entity_uri)

    assert after_e == 0, f"the entity survived its own graph delete ({after_e} quads)"
    assert after_f == 0, (
        f"RESIDUE: the frame outlived its root — {after_f} quads still there, "
        f"{residue} of them pointing at the deleted entity. This is issues/092.")
