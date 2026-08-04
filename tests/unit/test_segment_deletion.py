"""Unit tests for relationship-based segmentation deletion and URI minting.

Guards `issues/021_uri_prefix_string_matching_in_deletes.md`: segmentation
output must be identified by traversing Edge_hasKGDocumentSegment, never by
string-matching the subject URI prefix.

No server or database required.
"""

from __future__ import annotations

import pytest

from vitalgraph.document.segment_deletion import (
    EDGE_HAS_SEGMENT,
    HAS_SEGMENT_METHOD_URI,
    SEGMENTATION_PARENT_TYPE,
    delete_segmentation,
    find_segmentation_uris,
    mint_uri,
    sparql_bindings,
)

ORIGINAL = "urn:doc:1"
GRAPH = "http://example.org/graph/test"
SPACE = "testspace"


class FakeBackend:
    """Records SPARQL issued, and replays a canned traversal result."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries: list[str] = []
        self.updates: list[str] = []

    async def execute_sparql_query(self, space_id, query, **kwargs):
        self.queries.append(query)
        return {"results": {"bindings": self.rows}}

    async def execute_sparql_update(self, space_id, update, **kwargs):
        self.updates.append(update)
        return True


def _row(**kwargs):
    return {k: {"type": "uri", "value": v} for k, v in kwargs.items()}


# ---------------------------------------------------------------------------
# URI minting (§3.4) — uniqueness, not shape
# ---------------------------------------------------------------------------

class TestMintUri:

    def test_repeated_mints_are_unique(self):
        """Same prefix twice must not collide. The core of the minting fix."""
        assert mint_uri("urn:doc:1_parent_x") != mint_uri("urn:doc:1_parent_x")

    def test_prefix_is_preserved_for_readability(self):
        """The descriptive prefix survives — its only job is debuggability."""
        assert mint_uri("urn:doc:1_parent_x").startswith("urn:doc:1_parent_x")

    def test_many_mints_all_distinct(self):
        assert len({mint_uri("p") for _ in range(1000)}) == 1000


# ---------------------------------------------------------------------------
# Traversal query shape (§3.1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestFindSegmentationUris:

    async def test_query_traverses_edges_and_never_string_matches(self):
        backend = FakeBackend()
        await find_segmentation_uris(backend, SPACE, GRAPH, ORIGINAL)

        q = backend.queries[0]
        assert "hasEdgeSource" in q and "hasEdgeDestination" in q
        assert EDGE_HAS_SEGMENT in q
        assert SEGMENTATION_PARENT_TYPE in q
        # The whole point: no string matching on URIs.
        for banned in ("STRSTARTS", "STRENDS", "CONTAINS", "REGEX", "FILTER("):
            assert banned not in q.upper().replace("FILTER (", "FILTER("), banned

    async def test_method_scoping_matches_uri_not_literal(self):
        """The method URI is a URIProperty — matching it as a quoted literal
        (the pre-fix worker bug) silently matches nothing."""
        backend = FakeBackend()
        await find_segmentation_uris(
            backend, SPACE, GRAPH, ORIGINAL, method_uri="urn:segmethod:md"
        )
        q = backend.queries[0]
        assert f"<{HAS_SEGMENT_METHOD_URI}> <urn:segmethod:md>" in q
        assert '"urn:segmethod:md"' not in q

    async def test_unscoped_omits_method_clause(self):
        backend = FakeBackend()
        await find_segmentation_uris(backend, SPACE, GRAPH, ORIGINAL)
        assert HAS_SEGMENT_METHOD_URI not in backend.queries[0]

    async def test_collects_edges_parents_and_segments_deduped(self):
        backend = FakeBackend(rows=[
            _row(parent_edge="urn:e1", parent="urn:p", seg_edge="urn:e2", seg="urn:s1"),
            _row(parent_edge="urn:e1", parent="urn:p", seg_edge="urn:e3", seg="urn:s2"),
        ])
        uris = await find_segmentation_uris(backend, SPACE, GRAPH, ORIGINAL)
        assert set(uris) == {"urn:e1", "urn:p", "urn:e2", "urn:s1", "urn:e3", "urn:s2"}
        assert len(uris) == len(set(uris)), "duplicates not collapsed"

    async def test_parent_with_no_segments_still_returned(self):
        """OPTIONAL second hop — a parent copy with zero segments must still
        be deleted, not skipped."""
        backend = FakeBackend(rows=[_row(parent_edge="urn:e1", parent="urn:p")])
        uris = await find_segmentation_uris(backend, SPACE, GRAPH, ORIGINAL)
        assert set(uris) == {"urn:e1", "urn:p"}

    async def test_no_segmentation_returns_empty(self):
        assert await find_segmentation_uris(FakeBackend(), SPACE, GRAPH, ORIGINAL) == []

    async def test_unsafe_uri_refused(self):
        backend = FakeBackend()
        assert await find_segmentation_uris(
            backend, SPACE, GRAPH, "urn:doc:1> } INSERT { ?s ?p ?o"
        ) == []
        assert backend.queries == [], "must not issue a query for an unsafe URI"


# ---------------------------------------------------------------------------
# Deletion (§3.1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestDeleteSegmentation:

    async def test_deletes_via_update_not_query(self):
        """The pre-fix cascade issued DELETE through execute_sparql_query,
        which the SQL backend compiles as a SELECT — a silent no-op."""
        backend = FakeBackend(rows=[_row(parent_edge="urn:e1", parent="urn:p")])
        deleted = await delete_segmentation(backend, SPACE, GRAPH, ORIGINAL)

        assert deleted == 2
        assert len(backend.updates) == 1
        assert "DELETE" in backend.updates[0]
        assert len(backend.queries) == 1, "traversal only; no DELETE via query path"

    async def test_delete_targets_exact_uris(self):
        backend = FakeBackend(rows=[_row(parent_edge="urn:e1", parent="urn:p")])
        await delete_segmentation(backend, SPACE, GRAPH, ORIGINAL)

        upd = backend.updates[0]
        assert "<urn:e1>" in upd and "<urn:p>" in upd
        assert "STRSTARTS" not in upd

    async def test_delete_is_constrained_by_a_values_list(self):
        """`?s ?p ?o` is only safe because VALUES constrains it.

        This shape was unusable until issue 023 was fixed — the backend dropped
        the VALUES clause and the delete matched the whole graph. The pairing is
        the invariant: an unbound subject pattern MUST be accompanied by a
        VALUES list naming every subject.
        """
        backend = FakeBackend(rows=[_row(parent_edge="urn:e1", parent="urn:p")])
        await delete_segmentation(backend, SPACE, GRAPH, ORIGINAL)

        upd = backend.updates[0]
        assert "VALUES ?s" in upd
        assert "?s ?p ?o" in upd
        # every subject the delete can reach is named explicitly
        values_list = upd.split("VALUES ?s {", 1)[1].split("}", 1)[0]
        assert "<urn:e1>" in values_list and "<urn:p>" in values_list
        assert "?" not in values_list, "VALUES list must contain no variables"

    async def test_every_batch_is_constrained(self):
        """No batch may emit a bare `?s ?p ?o` — that is a whole-graph delete."""
        rows = [_row(parent_edge=f"urn:e{i}", parent=f"urn:p{i}") for i in range(300)]
        backend = FakeBackend(rows=rows)
        await delete_segmentation(backend, SPACE, GRAPH, ORIGINAL)

        assert backend.updates
        for upd in backend.updates:
            assert "VALUES ?s" in upd, "unconstrained DELETE emitted"
            values_list = upd.split("VALUES ?s {", 1)[1].split("}", 1)[0]
            assert values_list.strip(), "empty VALUES list — matches nothing safely, but signals a bug"

    async def test_nothing_to_delete_issues_no_update(self):
        backend = FakeBackend()
        assert await delete_segmentation(backend, SPACE, GRAPH, ORIGINAL) == 0
        assert backend.updates == []

    async def test_original_document_is_never_deleted(self):
        """delete_segmentation removes output, not the document itself."""
        backend = FakeBackend(rows=[_row(parent_edge="urn:e1", parent="urn:p")])
        await delete_segmentation(backend, SPACE, GRAPH, ORIGINAL)
        assert f"<{ORIGINAL}>" not in backend.updates[0]

    async def test_batches_large_deletes(self):
        rows = [_row(parent_edge=f"urn:e{i}", parent=f"urn:p{i}") for i in range(300)]
        backend = FakeBackend(rows=rows)
        deleted = await delete_segmentation(backend, SPACE, GRAPH, ORIGINAL)
        assert deleted == 600
        assert len(backend.updates) == 3  # 600 URIs / 200 per batch


# ---------------------------------------------------------------------------
# Result-shape tolerance
# ---------------------------------------------------------------------------

class TestSparqlBindings:

    def test_sparql_json_results(self):
        assert sparql_bindings({"results": {"bindings": [{"a": 1}]}}) == [{"a": 1}]

    def test_plain_list_results(self):
        assert sparql_bindings([{"a": 1}]) == [{"a": 1}]

    def test_empty_and_malformed(self):
        assert sparql_bindings({}) == []
        assert sparql_bindings(None) == []
        assert sparql_bindings({"results": {}}) == []


# ---------------------------------------------------------------------------
# Processor-level minting (§3.4) — the namespace collision
# ---------------------------------------------------------------------------

class TestProcessorMintingCollision:
    """Two method URIs sharing a local name must not mint the same parent URI.

    Pre-fix, `method_uri.split(":")[-1]` discarded the namespace, so
    urn:segmethod:X and urn:other:X produced an identical parent URI and one
    method's output silently overwrote the other's.
    """

    @staticmethod
    def _run(method_uri):
        from vitalgraph.document.kgdocument_segmentation_processor import (
            KGDocumentSegmentationProcessor,
        )
        from vitalgraph.document.segment_config import MarkdownSegmentConfig

        config = MarkdownSegmentConfig(segment_method_uri=method_uri)
        return KGDocumentSegmentationProcessor().process(
            original_uri=ORIGINAL,
            original_properties={"URI": ORIGINAL, "kGDocumentContent":
                                 "# Heading\n\nSome body text here.\n"},
            config=config,
            kg_graph_uri="urn:kggraph:test",
        )

    def test_same_local_name_different_namespace_do_not_collide(self):
        a = self._run("urn:segmethod:markdown_heading_split")
        b = self._run("urn:other:markdown_heading_split")
        assert (a.parent_copy_properties["URI"] != b.parent_copy_properties["URI"])
        assert (a.edge_original_to_parent["URI"] != b.edge_original_to_parent["URI"])

    def test_same_method_twice_mints_distinct_uris(self):
        """Re-segmentation must not reuse URIs; the delete path is traversal
        based, so it no longer depends on regenerating the same URI."""
        a = self._run("urn:segmethod:markdown_heading_split")
        b = self._run("urn:segmethod:markdown_heading_split")
        assert a.parent_copy_properties["URI"] != b.parent_copy_properties["URI"]

    def test_segments_and_edges_derive_from_unique_parent(self):
        out = self._run("urn:segmethod:markdown_heading_split")
        parent = out.parent_copy_properties["URI"]
        for seg in out.segment_properties_list:
            assert seg["URI"].startswith(parent)
        for edge in out.edge_parent_to_segments:
            assert edge["URI"].startswith(parent)
            assert edge["edgeSource"] == parent
        assert out.edge_original_to_parent["edgeSource"] == ORIGINAL
        assert out.edge_original_to_parent["edgeDestination"] == parent
