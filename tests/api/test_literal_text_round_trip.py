"""
Literal text reaches the store, and comes back, unchanged (`issues/332`).

The stored bytes are asserted as well as the read: this defect ran on both
sides, so a read alone cannot say which side changed the value. A value written
through SPARQL is the control, since that path never used the N-Quads unescape.
"""

import uuid

import pytest
from ai_haley_kg_domain.model.KGEntity import KGEntity

from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.model.quad_model import Quad, QuadRequest
from vitalgraph.model.sparql_model import SPARQLInsertRequest, SPARQLQueryRequest
from vitalgraph.utils.quad_format_utils import _escape_nquads_string

pytestmark = pytest.mark.asyncio(loop_scope="session")

NAME = "http://vital.ai/ontology/vital-core#hasName"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"

VALUES = ["C:\\new\\report", "a\\nb", "\\newline \\rho", "a\\\\nb", "a\nb", "a\tb"]


def _uri() -> str:
    return f"urn:literal-round-trip:{uuid.uuid4().hex}"


async def _stored(pg_conn, space: str, value: str) -> int:
    return await pg_conn.fetchval(
        f"SELECT count(*) FROM {space_prefix(space)}_term "
        f"WHERE term_type = 'L' AND term_text = $1", value)


@pytest.mark.parametrize("value", VALUES)
async def test_entity_create_stores_and_returns_the_value(
        vg_client, test_space, test_graph, pg_conn, value):
    e = KGEntity()
    e.URI = _uri()
    e.name = value
    r = await vg_client.kgentities.create_kgentities(
        space_id=test_space, graph_id=test_graph, objects=[e])
    assert r.is_success, r.error_message

    assert await _stored(pg_conn, test_space, value) == 1

    got = await vg_client.kgentities.get_kgentity(
        test_space, test_graph, uri=str(e.URI))
    assert [str(o.name) for o in got.objects] == [value]


@pytest.mark.parametrize("value", VALUES)
async def test_add_triples_stores_the_value(
        vg_client, test_space, test_graph, pg_conn, value):
    quad = Quad(s=f"<{_uri()}>", p=f"<{NAME}>", g=f"<{test_graph}>",
                o=f'"{_escape_nquads_string(value)}"^^<{XSD_STRING}>')
    r = await vg_client.triples.add_triples(
        test_space, test_graph, QuadRequest(quads=[quad]))
    assert r.success, r.message

    assert await _stored(pg_conn, test_space, value) == 1


@pytest.mark.parametrize("value", VALUES)
async def test_a_value_stored_through_sparql_reads_back_unchanged(
        vg_client, test_space, test_graph, value):
    """The read side alone: this write never used the N-Quads unescape."""
    uri = _uri()
    literal = (_escape_nquads_string(value).replace("\t", "\\t"))
    update = (
        f'INSERT DATA {{ GRAPH <{test_graph}> {{ '
        f'<{uri}> <{NAME}> "{literal}"^^<{XSD_STRING}> . '
        f'<{uri}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{KG_ENTITY}> . '
        f'<{uri}> <http://vital.ai/ontology/vital-core#vitaltype> <{KG_ENTITY}> . '
        f'}} }}')
    r = await vg_client.sparql.execute_sparql_insert(
        test_space, SPARQLInsertRequest(update=update))
    assert r.success

    q = await vg_client.sparql.execute_sparql_query(test_space, SPARQLQueryRequest(
        query=f'SELECT ?o WHERE {{ GRAPH <{test_graph}> {{ <{uri}> <{NAME}> ?o }} }}'))
    bindings = (q.results.get("bindings") if isinstance(q.results, dict)
                else q.results.bindings)
    assert [b["o"]["value"] for b in bindings] == [value]

    got = await vg_client.kgentities.get_kgentity(test_space, test_graph, uri=uri)
    assert [str(o.name) for o in got.objects] == [value]
