"""A grouping root must be a member of the graph it roots.

`issues/091`. Every object in an entity's graph carries `hasKGGraphURI` pointing
at the root, THE ROOT INCLUDED. 619 grouping URIs across 12 spaces were not, and
the writer went unidentified for three days because the read path compensated:
`get_entity_graph` was a UNION whose first branch re-fetched the root by pinning
its URI, so a missing self-link produced no symptom.

That compensation is gone. Reads now select in one branch by grouping URI and
return EMPTY when the root is not among its own members — better failure
behaviour, and it turns this from invisible into a blank screen.

Three writers, found by matching the affected data's URI prefixes to the code:

    urn:vitalgraph:graphviz:entity:*    generate_graph_viz_test_data._entity
    urn:vitalgraph:journey:event:*      generate_customer_journey_events._event_entity
    .../app/KGDocument/<hex>            kgdocuments_endpoint._create

All three had the same shape: every MEMBER got `kGGraphURI = <root URI>` and the
root got nothing. The distribution proved it was a write path rather than drift —
`graph_viz_a` 30 of 30 and `customer_journey_test` 11 of 11, against `prod_kg` at
1 of 8,752, which was populated through the entity create path that does it
correctly.

The document case is the one that mattered, because it is shipped code and
because segmentation ALREADY treats the document as the root:

    kg_graph_uri = original_properties.get("kGGraphURI", original_uri)
    # kgdocument_segmentation_processor.py:164, auto_segmentation.py:132

Segments and their edges were grouped under a document that was not in its own
group. 500 of 500 in `doc_test`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fn_source(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(path.read_text(), node) or ""
    pytest.fail(f"{name} not found in {path.name}; this test now measures nothing")


class TestTheFixtureGeneratorsGiveTheOwnerItsOwnUri:
    """Both build the root, assign the members, and used to skip the root."""

    @pytest.mark.parametrize("rel,fn", [
        ("test_scripts/data/generate_graph_viz_test_data.py", "_entity"),
        ("test_scripts/data/generate_customer_journey_events.py", "_event_entity"),
    ])
    def test_the_root_factory_sets_its_own_grouping_uri(self, rel, fn):
        src = _fn_source(ROOT / rel, fn)
        assert "kGGraphURI" in src, (
            f"{rel}:{fn} builds the grouping ROOT; every member object in that "
            f"file takes kGGraphURI = <root URI> and the root took none")
        assert "ent.URI" in src


class TestTheDocumentCreatePathSetsItToo:

    def test_the_helper_exists_and_is_called_before_storing(self):
        src = (ROOT / "vitalgraph" / "endpoint" / "kgdocuments_endpoint.py").read_text()
        assert "_set_document_grouping_uris" in src
        call = src.index("_set_document_grouping_uris(graph_objects)")
        store = src.index("store_objects(space_id, graph_id, graph_objects)")
        assert call < store, "the grouping URI has to be set before the write"

    def test_it_only_fills_an_absent_value(self):
        """A caller may legitimately group a document under something else — and
        a SEGMENT is KGDocument-typed too, arriving with its parent's URI. Absence
        is what distinguishes a root from a member, which is the same rule
        `kgdocument_segmentation_processor.py:164` uses."""
        from vitalgraph.endpoint.kgdocuments_endpoint import _set_document_grouping_uris
        from ai_haley_kg_domain.model.KGDocument import KGDocument

        root = KGDocument()
        root.URI = "urn:doc:1"
        member = KGDocument()          # a segment, already grouped under root
        member.URI = "urn:doc:1_seg_1"
        member.kGGraphURI = "urn:doc:1"

        assert _set_document_grouping_uris([root, member]) == 1
        assert str(root.kGGraphURI) == "urn:doc:1"
        assert str(member.kGGraphURI) == "urn:doc:1", "an existing value is not overwritten"

    def test_an_object_with_no_uri_is_skipped(self):
        from vitalgraph.endpoint.kgdocuments_endpoint import _set_document_grouping_uris
        from ai_haley_kg_domain.model.KGDocument import KGDocument
        assert _set_document_grouping_uris([KGDocument()]) == 0

    def test_non_documents_are_untouched(self):
        """An edge is a member, never a root. Self-linking one would invent a
        group of one."""
        from vitalgraph.endpoint.kgdocuments_endpoint import _set_document_grouping_uris
        from ai_haley_kg_domain.model.Edge_hasKGDocumentSegment import (
            Edge_hasKGDocumentSegment)
        edge = Edge_hasKGDocumentSegment()
        edge.URI = "urn:doc:1_edge_1"
        assert _set_document_grouping_uris([edge]) == 0
        assert not str(getattr(edge, "kGGraphURI", "") or "")


class TestTheSegmentationDefaultIsWhatMakesThisConsistent:
    """The document path and the segmentation path now agree by construction
    rather than by coincidence: one elects the document as root, the other puts
    the document in it."""

    @pytest.mark.parametrize("rel", [
        "vitalgraph/document/kgdocument_segmentation_processor.py",
        "vitalgraph/document/auto_segmentation.py",
    ])
    def test_segmentation_still_defaults_the_group_to_the_document(self, rel):
        src = (ROOT / rel).read_text()
        assert 'get("kGGraphURI", original_uri)' in src or \
               'get("kGGraphURI", document_uri)' in src, (
            "if this default changes, the create-side self-link is grouping "
            "documents under a root nothing else uses")
