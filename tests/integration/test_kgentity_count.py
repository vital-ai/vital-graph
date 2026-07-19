"""Integration test: KGEntity listing count (Fix 1 cache + Fix 3 fast count).

End-to-end against a real PostgreSQL space + Jena sidecar. Verifies that the
fast direct-SQL count equals the SPARQL COUNT(DISTINCT ?entity), that
list_entities reports the right total, and that the count cache is populated
and honored.

Requires PostgreSQL + Jena sidecar (auto-skips otherwise).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def count_space(make_space):
    """Ephemeral space (via the space manager) for the count tests."""
    return await make_space(f"{TEST_SPACE_PREFIX}count_{uuid.uuid4().hex[:8]}")


def _sparql_count(proc, backend_adapter, space_id, graph):
    """Run the SPARQL COUNT(DISTINCT ?entity) and return the int."""
    from vitalgraph.kg_impl.kgentity_list_impl import _extract_bindings

    async def _run():
        sparql = proc._build_count_query(graph, None, None)
        r = await backend_adapter.execute_sparql_query(space_id, sparql)
        b = _extract_bindings(r)
        return int(b[0]["count"]["value"]) if b and "count" in b[0] else 0

    return _run()


class TestEntityCount:
    async def test_fast_count_matches_sparql_and_list(self, backend_adapter, count_space):
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from vitalgraph.kg_impl.kgentity_list_impl import KGEntityListProcessor
        from vitalgraph.cache.count_cache import _count_cache

        graph = f"http://example.org/graph/{count_space}/{uuid.uuid4().hex[:8]}"
        N = 5

        entities = []
        for i in range(N):
            e = KGEntity()
            e.URI = f"http://example.org/entity/{uuid.uuid4()}"
            e.name = f"Count Entity {i}"
            entities.append(e)
        res = await backend_adapter.store_objects(count_space, graph, entities)
        assert res.success, f"store_objects failed: {res.message}"

        proc = KGEntityListProcessor()

        # 1) Fast direct-SQL count == N
        fast = await backend_adapter.fast_entity_count(count_space, graph)
        assert fast == N, f"fast_entity_count returned {fast}, expected {N}"

        # 2) SPARQL COUNT(DISTINCT) == N == fast (invariant: 1 vitaltype/entity)
        sparql_count = await _sparql_count(proc, backend_adapter, count_space, graph)
        assert sparql_count == N == fast, (
            f"SPARQL={sparql_count} fast={fast} expected={N}"
        )

        # 3) list_entities reports the right total and paginates
        _count_cache.invalidate_space(count_space)
        lr = await proc.list_entities(
            count_space, graph, backend_adapter, page_size=3, offset=0
        )
        assert lr.total_count == N, f"list total={lr.total_count} expected {N}"
        assert len(lr.entities) == 3, f"page had {len(lr.entities)} entities"

        # 4) The count is now cached under the SPARQL-count query hash
        count_sparql = proc._build_count_query(graph, None, None)
        qhash = _count_cache.query_hash(count_sparql)
        assert _count_cache.get(count_space, graph, qhash) == N

    async def test_fast_page_direct_listing(self, backend_adapter, count_space):
        """Default listing goes through the direct-SQL page (order by subject_uuid)."""
        from ai_haley_kg_domain.model.KGEntity import KGEntity
        from vitalgraph.kg_impl.kgentity_list_impl import KGEntityListProcessor

        graph = f"http://example.org/graph/{count_space}/{uuid.uuid4().hex[:8]}"
        N = 7
        created = {}
        for i in range(N):
            e = KGEntity()
            e.URI = f"http://example.org/pageentity/{uuid.uuid4()}"
            e.name = f"Page Entity {i}"
            created[str(e.URI)] = f"Page Entity {i}"
            await backend_adapter.store_objects(count_space, graph, [e])

        # fast_entity_page returns a page of URIs, all belonging to the space
        page1 = await backend_adapter.fast_entity_page(count_space, graph, 4, 0)
        page2 = await backend_adapter.fast_entity_page(count_space, graph, 4, 4)
        assert page1 is not None and page2 is not None
        assert len(page1) == 4 and len(page2) == 3
        # Non-overlapping and together cover all created entities
        assert not (set(page1) & set(page2))
        assert set(page1) | set(page2) == set(created)

        # Stable order across identical calls
        assert await backend_adapter.fast_entity_page(count_space, graph, 4, 0) == page1

        # list_entities uses the direct path: correct objects, total, names,
        # and no materialized frame/slot predicates leaking in.
        proc = KGEntityListProcessor()
        lr = await proc.list_entities(count_space, graph, backend_adapter,
                                      page_size=4, offset=0)
        assert lr.total_count == N
        assert len(lr.entities) == 4
        got_uris = [str(o.URI) for o in lr.entities]
        assert got_uris == page1  # order preserved from fast_entity_page
        for o in lr.entities:
            assert str(o.name) == created[str(o.URI)]

    async def test_fast_page_guards_return_none(self, backend_adapter, count_space):
        graph = f"http://example.org/graph/{count_space}/{uuid.uuid4().hex[:8]}"
        assert await backend_adapter.fast_entity_page(
            count_space, graph, 10, 0, search="x") is None
        assert await backend_adapter.fast_entity_page(
            count_space, graph, 10, 0, sort_by="http://vital.ai/ontology/vital-core#hasName") is None
        assert await backend_adapter.fast_entity_page(
            count_space, "default", 10, 0) is None

    async def test_shared_list_objects_fast_path(self, backend_adapter, space_impl, count_space):
        """The generic list_objects fast path (KGTypes/KGRelations) matches SPARQL.

        Keys on rdf:type like the SPARQL, orders by subject_uuid, and the count
        equals the SPARQL COUNT(DISTINCT ?s).
        """
        from ai_haley_kg_domain.model.KGType import KGType
        from vitalgraph.kg_impl.kg_graph_retrieval_utils import GraphObjectRetriever
        from vitalgraph.kg_impl.kg_backend_utils import (
            fast_typed_subject_count, fast_typed_subject_page, RDF_TYPE_URI)

        KGTYPE = "http://vital.ai/ontology/haley-ai-kg#KGType"
        graph = f"http://example.org/graph/{count_space}/{uuid.uuid4().hex[:8]}"
        N = 6
        objs, created = [], set()
        for i in range(N):
            k = KGType()
            k.URI = f"http://example.org/kgtype/{uuid.uuid4()}"
            k.name = f"Shared Type {i}"
            objs.append(k)
            created.add(str(k.URI))
        assert (await backend_adapter.store_objects(count_space, graph, objs)).success

        # Use the backend ADAPTER (as the real endpoints do via _ensure_retriever),
        # so the fast helpers must unwrap it to reach the space impl.
        retr = GraphObjectRetriever(backend_adapter)

        # Fast count == #seeded == SPARQL COUNT(DISTINCT ?s)
        fc = await fast_typed_subject_count(
            space_impl, count_space, graph, RDF_TYPE_URI, [KGTYPE])
        sparql = (f"SELECT (COUNT(DISTINCT ?s) AS ?count) WHERE {{ "
                  f"GRAPH <{graph}> {{ ?s a <{KGTYPE}> . }} }}")
        r = await space_impl.execute_sparql_query(count_space, sparql)
        b = r if isinstance(r, list) else r.get('results', {}).get('bindings', [])
        sparql_count = int(b[0]['count']['value']) if b else -1
        assert fc == N == sparql_count

        # list_objects (fast path) — pages ordered by subject_uuid, count correct
        page1 = await fast_typed_subject_page(
            space_impl, count_space, graph, RDF_TYPE_URI, [KGTYPE], 4, 0)
        tr1, total = await retr.list_objects(
            count_space, graph, [KGTYPE], page_size=4, offset=0, include_count=True)
        assert total == N

        def _subjects_in_order(triples):
            seen = []
            for s, _p, _o in triples:
                if str(s) not in seen:
                    seen.append(str(s))
            return seen

        subs1 = _subjects_in_order(tr1)
        assert subs1 == page1  # membership AND subject_uuid order preserved

        tr2, _ = await retr.list_objects(
            count_space, graph, [KGTYPE], page_size=4, offset=4, include_count=False)
        subs2 = _subjects_in_order(tr2)
        assert not (set(subs1) & set(subs2))
        assert set(subs1) | set(subs2) == created

        # Fallback path (fast path disabled) still returns the same subjects.
        # include_materialized_edges=True disables the fast path per its guard,
        # so this exercises the original SPARQL subquery branch.
        tr_fb, _ = await retr.list_objects(
            count_space, graph, [KGTYPE], page_size=50, offset=0,
            include_materialized_edges=True, include_count=False)
        assert set(_subjects_in_order(tr_fb)) == created

    async def test_frames_fast_path_by_vitaltype_and_assertion_default(
            self, backend_adapter, space_impl, count_space):
        """Frames count by vitaltype=KGFrame (like entities); unset frames are
        assertions.

        Regression guard for the fix that dropped the mandatory hasFrameGraphURI
        (which had hidden assertion frames).
        """
        from ai_haley_kg_domain.model.KGFrame import KGFrame
        from vitalgraph.kg_impl.kg_backend_utils import (
            fast_typed_subject_count, fast_typed_subject_page, VITALTYPE_URI)
        from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint

        KGFRAME = ['http://vital.ai/ontology/haley-ai-kg#KGFrame']
        ASSERTION = 'http://vital.ai/ontology/haley-ai-kg#KGFormType_Assertion'
        ASPECT = 'http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect'
        graph = f"http://example.org/graph/{count_space}/{uuid.uuid4().hex[:8]}"

        # N assertion frames (no kGFormType, no frameGraphURI → Assertion default)
        # + M aspect frames (no kGFormType, but frameGraphURI set → Aspect default)
        N, M = 5, 3
        objs, created = [], set()
        for i in range(N):
            f = KGFrame()
            f.URI = f"http://example.org/frame/{uuid.uuid4()}"
            f.name = f"Assertion Frame {i}"
            objs.append(f)
            created.add(str(f.URI))
        for i in range(M):
            f = KGFrame()
            f.URI = f"http://example.org/frame/{uuid.uuid4()}"
            f.name = f"Aspect Frame {i}"
            f.frameGraphURI = f"http://example.org/framegraph/{uuid.uuid4()}"
            objs.append(f)
            created.add(str(f.URI))
        assert (await backend_adapter.store_objects(count_space, graph, objs)).success

        ep = KGFramesEndpoint(space_manager=None, auth_dependency=None)

        async def _sparql_count(cq):
            r = await space_impl.execute_sparql_query(count_space, cq)
            b = r if isinstance(r, list) else r.get('results', {}).get('bindings', [])
            return int(b[0]['count']['value']) if b else -1

        # fast count == SPARQL count (a KGFrame) == all frames
        fc = await fast_typed_subject_count(
            space_impl, count_space, graph, VITALTYPE_URI, KGFRAME)
        assert fc == N + M == await _sparql_count(
            ep._build_count_frames_query(space_impl, count_space, graph, None))

        # Default rules: unset + no frameGraphURI → Assertion; unset + frameGraphURI → Aspect
        assert await _sparql_count(ep._build_count_frames_query(
            space_impl, count_space, graph, None, form_type=ASSERTION)) == N
        assert await _sparql_count(ep._build_count_frames_query(
            space_impl, count_space, graph, None, form_type=ASPECT)) == M

        # fast page: non-overlapping ordered pages covering all frames
        p1 = await fast_typed_subject_page(
            space_impl, count_space, graph, VITALTYPE_URI, KGFRAME, 5, 0)
        p2 = await fast_typed_subject_page(
            space_impl, count_space, graph, VITALTYPE_URI, KGFRAME, 5, 5)
        assert len(p1) == 5 and len(p2) == M
        assert not (set(p1) & set(p2))
        assert set(p1) | set(p2) == created

    async def test_documents_include_segments_toggle(self, backend_adapter, count_space):
        """KGDocuments: default lists top-level docs (segments excluded); the
        include_segments toggle lists documents + segments."""
        from ai_haley_kg_domain.model.KGDocument import KGDocument
        from vitalgraph.kg_impl.kgdocuments_read_impl import KGDocumentsReadProcessor

        graph = f"http://example.org/graph/{count_space}/{uuid.uuid4().hex[:8]}"
        docs, segs, objs = set(), set(), []
        for i in range(3):
            d = KGDocument()
            d.URI = f"http://example.org/doc/{uuid.uuid4()}"
            d.name = f"Doc {i}"
            objs.append(d)
            docs.add(str(d.URI))
        # Segments with a mix of segment types — including ones NOT in the
        # managed list — to prove exclusion is type-agnostic (any object with a
        # segment-type predicate is a segment). Guards the paragraph-leak fix.
        for i, seg_type in enumerate([
            "urn:segtype:text_chunk",
            "urn:segtype:markdown_section",
            "urn:segtype:paragraph",
            "urn:segtype:some_future_type",
        ]):
            s = KGDocument()
            s.URI = f"http://example.org/seg/{uuid.uuid4()}"
            s.name = f"Seg {i}"
            s.kGDocumentSegmentTypeURI = seg_type
            objs.append(s)
            segs.add(str(s.URI))
        assert (await backend_adapter.store_objects(count_space, graph, objs)).success

        proc = KGDocumentsReadProcessor()

        def _subjects(triples):
            out = []
            for t in triples:
                u = str(t[0])
                if u not in out:
                    out.append(u)
            return set(out)

        # Default: top-level documents only — ALL segment types excluded
        tri, total = await proc.list_kgdocuments(
            backend_adapter, count_space, graph, page_size=50, offset=0,
            include_segments=False)
        assert total == 3
        assert _subjects(tri) == docs

        # Toggle on: documents + segments (fast path via the adapter)
        tri2, total2 = await proc.list_kgdocuments(
            backend_adapter, count_space, graph, page_size=50, offset=0,
            include_segments=True)
        assert total2 == 3 + len(segs)
        assert _subjects(tri2) == docs | segs

    async def test_fast_count_guards_return_none(self, backend_adapter, count_space):
        graph = f"http://example.org/graph/{count_space}/{uuid.uuid4().hex[:8]}"
        # Filtered / searched / sorted / non-URI-graph shapes are not derivable
        # from a single COUNT(*) → fall back to SPARQL.
        assert await backend_adapter.fast_entity_count(
            count_space, graph, search="x") is None
        assert await backend_adapter.fast_entity_count(
            count_space, graph, entity_type_uri="http://x/T") is None
        assert await backend_adapter.fast_entity_count(
            count_space, graph, sort_by="http://vital.ai/ontology/vital-core#hasName") is None
        assert await backend_adapter.fast_entity_count(
            count_space, "default") is None
