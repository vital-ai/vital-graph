"""API tests: document query enrichment points at the right documents, and
hybrid search returns rows at alpha 0.5 (`issues/288`).

Reported against 0.0.48 on the AWS test environment:

* `query_documents` with `include_parent_context` / `include_original_uri`
  repeated a hit and gave it a "parent" and "original" from an unrelated frame
  and its slots. Two sibling OPTIONALs: when the parent group did not match,
  the original group matched any edge in the graph.
* `vg:hybridSearch` at alpha 0.5 returned no rows where alpha 0 worked: the
  vector arm admitted a row only at cosine similarity above 0.4, which an
  OpenAI embedding's good matches (0.2-0.35) never reach.

The graph deliberately holds an UNRELATED entity with a frame and slots, because
those edges are what the broken OPTIONAL matched.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGDocument import KGDocument
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

INDEX = "document_segments"
DOC_TYPE = "urn:kgdoctype:test_enrichment"
SEG_METHOD = "urn:segmethod:plain_recursive_split"
NS = "urn:test:enrich"

ROOFING = "\n\n".join([
    "Our roofing crew replaces shingles and repairs flashing on houses.",
    "We find the source of a leak in the roof and seal it before the rain.",
    "Gutters, chimneys and skylights are inspected on every roofing job.",
    "A roofing estimate is free and includes photos of the damaged areas.",
] * 3)
BAKERY = "\n\n".join([
    "The bakery bakes sourdough loaves and croissants every morning.",
    "Our ovens turn out baguettes, muffins and cinnamon rolls before dawn.",
    "Customers order birthday cakes and pies for weekend celebrations.",
    "Flour, butter and sugar arrive daily from local farms for the bakery.",
] * 3)

PREFIXES = """PREFIX vg: <http://vital.ai/ontology/vitalgraph#>
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
"""


def _uid():
    return uuid.uuid4().hex[:8]


async def _sparql_rows(vg_client, space, graph, bind):
    from vitalgraph.model.sparql_model import SPARQLQueryRequest
    q = (PREFIXES + "SELECT ?seg ?score WHERE { GRAPH <" + graph + "> { "
         "?seg haley:hasKGDocumentSegmentIndex ?i . " + bind +
         " FILTER(?score > 0) } } ORDER BY DESC(?score) LIMIT 5")
    r = await vg_client.execute_sparql_query(space, SPARQLQueryRequest(query=q))
    results = getattr(r, "results", None)
    bindings = (results or {}).get("bindings") if isinstance(results, dict) \
        else getattr(results, "bindings", None)
    return [(b["seg"]["value"], float(b["score"]["value"])) for b in (bindings or [])]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def env(vg_client, test_space, test_graph):
    space, graph = test_space, test_graph
    cfg = await vg_client.kgdocuments.create_segmentation_config(
        space_id=space, document_type_uri=DOC_TYPE, segment_method_uri=SEG_METHOD,
        max_segment_tokens=40, min_segment_tokens=5, overlap_tokens=0,
        enabled=True, auto_vectorize=True)
    assert cfg.config_id is not None, cfg

    # The space bootstraps an OpenAI `document_segments` index; replace it with
    # a local model, plus an FTS index of the same name, as the Wikipedia e2e
    # does. Hybrid search resolves the one name to both.
    for drop in (vg_client.vector_indexes.delete_index, vg_client.fts_indexes.delete_index):
        try:
            await drop(space_id=space, index_name=INDEX)
        except Exception:
            pass
    await vg_client.vector_indexes.create_index(
        space_id=space, index_name=INDEX, dimensions=384, distance_metric="cosine",
        provider="vitalsigns", model_name="paraphrase-multilingual-MiniLM-L12-v2")
    await vg_client.fts_indexes.create_index(space_id=space, index_name=INDEX,
                                             languages=["english"])
    m = await vg_client.search_mappings.create_mapping(
        space_id=space, index_name=INDEX, mapping_type="kgdocument_segment",
        enabled=True, source_type="default")
    for kind in ("vector", "fts"):
        await vg_client.search_mappings.add_index(
            space_id=space, mapping_id=m.mapping_id, index_type=kind, index_name=INDEX)

    # The unrelated frame and slots the broken OPTIONAL used to bind.
    e = KGEntity(); e.URI = f"{NS}:entity:{_uid()}"; e.name = "Unrelated business"
    assert (await vg_client.kgentities.create_kgentities(
        space_id=space, graph_id=graph, objects=[e])).is_success
    f = KGFrame(); f.URI = f"{NS}:frame:{_uid()}"; f.name = "Registration"
    objs = [f]
    for i in range(3):
        s = KGTextSlot(); s.URI = f"{NS}:slot:{_uid()}"; s.name = f"field{i}"
        s.textSlotValue = f"value {i}"
        ed = Edge_hasKGSlot(); ed.URI = f"{NS}:edge:{_uid()}"
        ed.edgeSource = str(f.URI); ed.edgeDestination = str(s.URI)
        objs += [s, ed]
    assert (await vg_client.kgentities.create_entity_frames(
        space_id=space, graph_id=graph, entity_uri=str(e.URI), objects=objs)).is_success

    docs = {}
    for key, text in (("roofing", ROOFING), ("bakery", BAKERY)):
        d = KGDocument(); d.URI = f"{NS}:doc:{key}:{_uid()}"; d.name = f"{key} report"
        d.kGDocumentType = DOC_TYPE; d.kGDocumentContent = text; d.kGraphDescription = text
        assert (await vg_client.kgdocuments.create_kgdocuments(space, graph, [d])).is_success
        docs[key] = str(d.URI)

    # Segmentation is queued on create (issues/286); wait for both, then for
    # their segments' vectors.
    for _ in range(60):
        st = [await vg_client.kgdocuments.get_segmentation_status(space_id=space, document_uri=u)
              for u in docs.values()]
        if all(any(j.get("status") == "completed" for j in s.jobs) for s in st):
            break
        await asyncio.sleep(2.0)
    for _ in range(60):
        rows = await _sparql_rows(vg_client, space, graph,
                                  f'BIND(vg:vectorSimilarity(?seg, "roof repair", "{INDEX}") AS ?score)')
        if rows:
            break
        await asyncio.sleep(2.0)

    yield {"space": space, "graph": graph, "docs": docs}

    for u in docs.values():
        try:
            await vg_client.kgdocuments.delete_kgdocument(space, graph, u)
        except Exception:
            pass
    try:
        await vg_client.kgdocuments.delete_segmentation_config(space, cfg.config_id)
    except Exception:
        pass


class TestEnrichment:

    @pytest.mark.parametrize("managed", [False, True])
    async def test_parent_and_original_belong_to_the_hit(self, env, vg_client, managed):
        from vitalgraph.model.kgentities_model import VectorSearchCriteria
        r = await vg_client.kgqueries.query_documents(
            env["space"], env["graph"],
            exclude_managed_segments=managed,
            include_parent_context=True, include_original_uri=True,
            vector_criteria=VectorSearchCriteria(
                search_text="contractor that fixes leaks on the top of houses",
                index_name=INDEX, top_k=5))
        results = r.document_results or []
        if managed:
            # Managed objects excluded leaves only the originals, which a
            # segment-only index holds no vector for. They came back unscored
            # and unordered; a vector query now returns only scored rows.
            assert all(x.score is not None for x in results), (
                f"unscored rows in a vector result: {results}")
            assert not results, f"originals have no vector here: {results}"
            return
        assert results, f"no results: {r}"
        uris = [x.document_uri for x in results]
        assert len(uris) == len(set(uris)), f"a hit is repeated: {uris}"
        originals = set(env["docs"].values())
        for x in results:
            if x.parent_document_uri is not None:
                assert any(x.parent_document_uri.startswith(o + "_parent_") for o in originals), (
                    f"{x.document_uri}: parent {x.parent_document_uri} is not a parent copy")
                assert x.original_document_uri in originals, (
                    f"{x.document_uri}: original {x.original_document_uri} is not a document")
            else:
                assert x.original_document_uri is None, (
                    f"{x.document_uri}: an original with no parent: {x.original_document_uri}")
        if not managed:
            # Segments are managed objects, so only this case returns them.
            segs = [x for x in results if "_seg_" in x.document_uri]
            assert segs and all(s.parent_document_uri for s in segs), (
                "every segment hit must resolve its parent copy")
        if not managed:
            # The top hit is a roofing segment or roofing's parent copy (which
            # has no parent above it, so no original either). With managed
            # objects excluded only the ORIGINALS remain, and a segment-only
            # index holds no vector for them, so they come back unscored and
            # unordered -- recorded in issues/288, not asserted here.
            assert results[0].document_uri.startswith(env["docs"]["roofing"]), uris


class TestHybrid:

    async def test_alpha_half_returns_rows_at_low_similarity(self, env, vg_client):
        # The AWS failure, reproduced on the local model: no lexical match, and
        # a cosine similarity BELOW 0.4 (measured 0.35 against the bakery text,
        # -0.14 against roofing on paraphrase-multilingual-MiniLM-L12-v2). The
        # old `distance < 0.6` gate admitted nothing, as it admitted nothing on
        # OpenAI embeddings, whose good matches score 0.2-0.35.
        rows = await _sparql_rows(
            vg_client, env["space"], env["graph"],
            f'BIND(vg:hybridSearch(?seg, "somewhere to buy something sweet for a party", '
            f'"{INDEX}", 0.5) AS ?score)')
        assert rows, "hybrid search at alpha 0.5 returned no rows"
        assert rows[0][0].startswith(env["docs"]["bakery"]), rows

    async def test_alpha_zero_is_still_pure_lexical(self, env, vg_client):
        rows = await _sparql_rows(
            vg_client, env["space"], env["graph"],
            f'BIND(vg:hybridSearch(?seg, "roofing", "{INDEX}", 0) AS ?score)')
        assert rows and all(s.startswith(env["docs"]["roofing"]) for s, _ in rows), rows


class TestSegmentScope:

    async def test_search_scope_segments_returns_segments_only(self, env, vg_client):
        """The documented way to search segments: no hidden parent copies."""
        from vitalgraph.model.kgentities_model import VectorSearchCriteria
        r = await vg_client.kgqueries.query_documents(
            env["space"], env["graph"], search_scope="segments",
            exclude_managed_segments=False, include_parent_context=True,
            vector_criteria=VectorSearchCriteria(
                search_text="contractor that fixes leaks on the top of houses",
                index_name=INDEX, top_k=5))
        results = r.document_results or []
        assert results, r
        for x in results:
            assert "_seg_" in x.document_uri, f"not a segment: {x.document_uri}"
            assert x.score is not None
            assert x.parent_document_uri, x
