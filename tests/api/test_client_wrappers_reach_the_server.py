"""The repaired `VitalGraphClient` wrappers work against a real server.

The unit test (`tests/unit/test_client_wrappers_cover_the_kg_endpoints.py`)
proves each wrapper hands its arguments to the right endpoint parameter. This
proves the ones that were broken now do something useful end to end, called
the way existing callers call them:

  * the KGType wrappers, WITH a graph_id — five raised TypeError and
    list_kgtypes sent the graph id as page_size, since KGTypes became
    space-scoped;
  * upload_file_content — sent the file URI as the graph and the graph as
    the data;
  * search_triples — called an endpoint method that does not exist;
  * list_kgentities(search=...) — sent the search term as the entity TYPE.

Runs against the vg-test stack (:8002).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGType import KGType
from vital_ai_domain.model.FileNode import FileNode

pytestmark = [pytest.mark.api, pytest.mark.asyncio(loop_scope="session")]

NS = "http://example.org/apitest/wrappers/"
PNG_FILE = Path(__file__).parent.parent.parent / "test_files" / "vampire_queen_baby.png"


def _uri():
    return f"{NS}{uuid.uuid4().hex[:12]}"


async def test_the_kgtype_wrappers_work_when_called_with_a_graph(vg_client, test_space, test_graph):
    t = KGType()
    t.URI = _uri()
    t.name = f"Wrapper Type {uuid.uuid4().hex[:6]}"
    created = await vg_client.create_kgtypes(test_space, test_graph, [t])
    assert created.is_success, created.error_message

    got = await vg_client.get_kgtype(test_space, test_graph, str(t.URI))
    assert got.is_success, got.error_message

    listed = await vg_client.list_kgtypes(test_space, test_graph, page_size=100)
    assert listed.is_success, listed.error_message
    assert str(t.URI) in {str(o.URI) for o in listed.types}

    t.name = "Renamed"
    updated = await vg_client.update_kgtypes(test_space, test_graph, [t])
    assert updated.is_success, updated.error_message

    deleted = await vg_client.delete_kgtype(test_space, test_graph, str(t.URI))
    assert deleted.is_success, deleted.error_message


async def test_upload_file_content_uploads_to_the_file_node(vg_client, test_space, test_graph):
    f = FileNode()
    f.URI = _uri()
    f.name = "wrapper upload"
    cr = await vg_client.files.create_file(space_id=test_space, graph_id=test_graph, objects=[f])
    assert cr.is_success, cr.error_message
    up = await vg_client.upload_file_content(test_space, str(f.URI), str(PNG_FILE), graph_id=test_graph)
    assert up.is_success, up.error_message
    assert up.file_uri == str(f.URI)
    assert up.size == PNG_FILE.stat().st_size


async def test_search_triples_returns_the_matching_triples(vg_client, test_space, test_graph):
    e = KGEntity()
    e.URI = _uri()
    e.name = "Triple Search Probe"
    cr = await vg_client.create_kgentities(test_space, test_graph, [e])
    assert cr.is_success, cr.error_message
    r = await vg_client.search_triples(test_space, test_graph, subject=str(e.URI), limit=50)
    assert r.success, r.message
    assert r.results, "no triples returned for the entity just created"
    # Quads carry N-Quads terms: a URI subject is `<uri>`.
    assert {q.s for q in r.results} == {f"<{e.URI}>"}, (
        "the subject filter was not applied")


async def test_list_kgentities_search_is_a_search_not_a_type_filter(vg_client, test_space, test_graph):
    word = f"wrapsearch{uuid.uuid4().hex[:6]}"
    e = KGEntity()
    e.URI = _uri()
    e.name = f"Entity {word}"
    cr = await vg_client.create_kgentities(test_space, test_graph, [e])
    assert cr.is_success, cr.error_message
    r = await vg_client.list_kgentities(test_space, test_graph, page_size=10, offset=0, search=word)
    assert r.is_success, r.error_message
    assert str(e.URI) in {str(o.URI) for o in r.objects}, (
        "the search term was not used as a search")
