"""A frame's graph must include its slots under either linkage — and the edges.

`get_frame_graph` promises, in its own contract, to return "All immediate
connected slots, All Edge_hasKGSlot relationships". `_build_frame_graph_query`
implemented only the ATTRIBUTE linkage (`hasFrameGraphURI`), so on a connection
frame it returned the frame alone; `get_frame_graph` then saw a single object,
treated it as "frame only" and returned None, and the UI reported "No slots
found for this frame" for a frame with two.

Why it stayed hidden: an absent predicate matches nothing rather than failing,
so every layer reported success on an empty answer.

The EDGES matter as much as the slots. The client does not walk from frame to
slot itself — it pairs `isEdgeHasKGSlot(o) && o.edgeSource === frameId` with the
object at `edgeDestination`. Returning slots without their edges renders exactly
nothing, which is why that is asserted separately here.

Assertions are on generated SPARQL text, so no database is needed.
"""

from __future__ import annotations

import pytest

from vitalgraph.kg_impl.kgframe_graph_impl import KGFrameGraphProcessor

pytestmark = pytest.mark.unit

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
FRAME = "http://vital.ai/haley.ai/app/KGFrame/1716488391362_692038076"
GRAPH = "urn:wordnet_frames"


@pytest.fixture
def query():
    proc = KGFrameGraphProcessor.__new__(KGFrameGraphProcessor)
    return proc._build_frame_graph_query(FRAME, GRAPH)


def test_the_frame_itself_is_included(query):
    assert f"<{FRAME}> ?p ?o" in query
    assert f"BIND(<{FRAME}> AS ?subject)" in query


def test_the_attribute_linkage_is_kept(query):
    """21 of 79 spaces use only this one; it must not be traded away."""
    assert f"?subject haley:hasFrameGraphURI <{FRAME}>" in query


def test_the_connecting_edges_are_returned(query):
    """Not merely a route to the slots — the client identifies a slot BY its
    edge, so slots without edges render nothing."""
    assert f"?subject vital:hasEdgeSource <{FRAME}>" in query


def test_the_slots_those_edges_point_at_are_returned(query):
    assert f"?_slotEdge vital:hasEdgeSource <{FRAME}>" in query
    assert "?_slotEdge vital:hasEdgeDestination ?subject" in query


def test_edge_direction_is_frame_to_slot(query):
    """Frame is the edge SOURCE and slot the DESTINATION. Reversed, this
    returns nothing at all — and returns it silently."""
    assert f"vital:hasEdgeDestination <{FRAME}>" not in query, (
        "the frame must be the edge SOURCE, not the destination")


def test_the_graph_is_scoped(query):
    assert f"GRAPH <{GRAPH}>" in query


def test_subjects_are_deduplicated(query):
    """A subject can be reached by more than one branch once a space carries
    both linkages — 6 of 79 do."""
    assert "SELECT DISTINCT ?subject" in query


class TestNoDuplicateFrame:
    """The frame is in BOTH the lookup result and the frame graph.

    `_get_frame_by_uri` concatenates `frames` with `frame_graph.graph_objects`,
    and the frame graph includes the frame by design — so without a dedupe every
    quad of the frame is emitted twice. The UI showed the frame's 5 properties
    twice over.

    This was invisible while the frame graph returned None for a frame whose
    slots were unreachable; it appeared the moment the graph had contents.
    """

    def _obj(self, uri):
        class _O:
            URI = uri
        return _O()

    def test_the_frame_appears_once(self):
        from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
        frame = self._obj(FRAME)
        objs = [frame, self._obj(FRAME), self._obj("urn:slot:a"), self._obj("urn:slot:b")]
        out = KGFramesEndpoint._dedupe_by_uri(objs)
        assert [getattr(o, "URI") for o in out] == [FRAME, "urn:slot:a", "urn:slot:b"]

    def test_input_order_is_preserved(self):
        """Stable output, so the payload is easy to read and diff.

        Deliberately NOT a statement that consumers may rely on position: this
        response is a set of graph objects and each is identified by its URI. A
        detail view selects the object it asked for by URI, so the frame being
        first is incidental.
        """
        from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
        out = KGFramesEndpoint._dedupe_by_uri(
            [self._obj("urn:slot:a"), self._obj(FRAME), self._obj("urn:slot:a")])
        assert [getattr(o, "URI") for o in out] == ["urn:slot:a", FRAME]

    def test_an_object_without_a_uri_is_kept(self):
        """Losing data to a defensive filter is worse than a duplicate."""
        from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint
        class _NoUri:
            pass
        out = KGFramesEndpoint._dedupe_by_uri([_NoUri(), _NoUri()])
        assert len(out) == 2
