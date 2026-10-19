"""The vectorize rule every vector writer applies (`issues/285`).

Precedence: an explicit `hasKGIndexStatusURI` on the subject, then a whole
document's type default (`auto_vectorize` across its enabled segmentation
configs), then embed. Also: an untyped KGDocument is classified as a DOCUMENT,
not as an entity.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
EX = "http://example.org/vecpolicy/"
GRAPH = "http://example.org/vecpolicy/graph"
TYPE_ON, TYPE_OFF, TYPE_MIXED, TYPE_NONE = (
    f"{EX}TypeOn", f"{EX}TypeOff", f"{EX}TypeMixed", f"{EX}TypeNoConfig")
NO_INDEX = f"{HALEY}KGIndexStatus_NO_INDEX"
VECTOR = f"{HALEY}KGIndexStatus_VECTOR"


def _doc(name, doc_type=None, status=None, segment_index=None):
    from rdflib import Literal, URIRef
    g, s = URIRef(GRAPH), URIRef(f"{EX}{name}")
    out = [(s, URIRef(RDF_TYPE), URIRef(f"{HALEY}KGDocument"), g),
           (s, URIRef(f"{CORE}hasName"), Literal(name), g)]
    if doc_type:
        out.append((s, URIRef(f"{HALEY}hasKGDocumentType"), URIRef(doc_type), g))
    if status:
        out.append((s, URIRef(f"{HALEY}hasKGIndexStatusURI"), URIRef(status), g))
    if segment_index is not None:
        out.append((s, URIRef(f"{HALEY}hasKGDocumentSegmentIndex"),
                    Literal(segment_index), g))
    return out


@pytest.fixture(scope="module")
def docs():
    return {
        "plain_on": dict(doc_type=TYPE_ON),
        "plain_off": dict(doc_type=TYPE_OFF),
        "mixed": dict(doc_type=TYPE_MIXED),
        "no_config": dict(doc_type=TYPE_NONE),
        "explicit_off_on_type_on": dict(doc_type=TYPE_ON, status=NO_INDEX),
        "explicit_on_on_type_off": dict(doc_type=TYPE_OFF, status=VECTOR),
        # A segment carries `document_segment` as its type in real data; here
        # it carries TYPE_OFF to prove rule 2 never applies to a segment.
        "segment_unstamped": dict(doc_type=TYPE_OFF, segment_index=1),
        "segment_stamped": dict(doc_type=TYPE_ON, segment_index=2, status=NO_INDEX),
        "untyped": dict(),
    }


async def test_the_rule(test_space, space_impl, pg_pool, docs):
    from vitalgraph.document.vectorize_policy import vector_opt_outs
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import _u

    quads = []
    for name, spec in docs.items():
        quads += _doc(name, **spec)
    await space_impl.add_rdf_quads_batch(test_space, quads)

    async with pg_pool.acquire() as conn:
        t = f"{test_space}_document_segmentation_config"
        for doc_type, method, auto in (
                (TYPE_ON, "urn:m:a", True), (TYPE_OFF, "urn:m:a", False),
                # Mixed: one config on, one off -> on (off only when NONE is on).
                (TYPE_MIXED, "urn:m:a", False), (TYPE_MIXED, "urn:m:b", True)):
            await conn.execute(
                f"INSERT INTO {t} (document_type_uri, segment_method_uri, "
                f"auto_vectorize) VALUES ($1, $2, $3)", doc_type, method, auto)
        # A DISABLED off config does not count.
        await conn.execute(
            f"INSERT INTO {t} (document_type_uri, segment_method_uri, "
            f"auto_vectorize, enabled) VALUES ($1, 'urn:m:z', false, false)", TYPE_NONE)

        uuids = {name: _u(f"{EX}{name}") for name in docs}
        off = await vector_opt_outs(conn, test_space, list(uuids.values()), _u(GRAPH))

    got = {name for name, u in uuids.items() if str(u) in off}
    assert got == {"plain_off", "explicit_off_on_type_on", "segment_stamped"}, got


async def test_an_untyped_document_is_a_document(test_space, space_impl, pg_pool):
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import _u
    from vitalgraph.vectorization.auto_sync import _subject_scopes

    await space_impl.add_rdf_quads_batch(test_space, _doc("bare_upload"))
    async with pg_pool.acquire() as conn:
        scopes = await _subject_scopes(
            conn, test_space, [_u(f"{EX}bare_upload")], _u(GRAPH))
    assert scopes[str(_u(f"{EX}bare_upload"))] == ("kgdocument", None), (
        "an untyped document fell through to `kgentity` and was embedded into "
        "entity indexes")
