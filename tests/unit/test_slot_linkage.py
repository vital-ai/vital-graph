"""A frame's slots must be found under EITHER linkage.

The KG model has two frame families and a space may contain both:

    attribute   entity -> frame -> slot -> LITERAL
                slot joined to its frame by `hasFrameGraphURI`
    connection  entity -> frame -> slot -> ENTITY
                frame joined to its slots by an `Edge_hasKGSlot` edge, the frame
                being the edge SOURCE and the slot the DESTINATION

Across the 79 spaces on the development database: 21 attribute-only, 8
connection-only, 6 with BOTH. So the query cannot pick a side.

Only the attribute half was implemented, and the frames UI reported "No slots
found for this frame" for connection frames that plainly had them — a wordnet
frame with a `hasSourceEntity` and a `hasDestinationEntity` slot showed an empty
Slot Summary. It missed twice over, which matters because fixing either alone
still yields nothing: `hasFrameGraphURI` has zero rows in such a space, AND
`KGEntitySlot` was absent from the subclass list.

These assert on generated SPARQL text, so they need no database.
"""

from __future__ import annotations

import pytest

from vitalgraph.endpoint.kgframes_endpoint import KGFramesEndpoint

pytestmark = pytest.mark.unit

HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VITAL = "http://vital.ai/ontology/vital-core#"
FRAME = "http://vital.ai/haley.ai/app/KGFrame/1716488391362_692038076"


@pytest.fixture
def endpoint():
    return KGFramesEndpoint(space_manager=None, auth_dependency=None)


class _Backend:
    def _get_space_graph_uri(self, space_id, graph_id):
        return graph_id


def _list(endpoint, frame_uri=FRAME):
    return endpoint._build_list_slots_query(
        _Backend(), "sp", "urn:g", frame_uri, 25, 0)


def _count(endpoint, frame_uri=FRAME):
    return endpoint._build_count_slots_query(_Backend(), "sp", "urn:g", frame_uri)


class TestBothLinkages:

    @pytest.mark.parametrize("build", [_list, _count], ids=["list", "count"])
    def test_entity_slots_are_matched(self, endpoint, build):
        """KGEntitySlot was missing entirely — the omission that made repairing
        the linkage alone insufficient."""
        assert f"{HALEY}KGEntitySlot" in build(endpoint)

    @pytest.mark.parametrize("build", [_list, _count], ids=["list", "count"])
    def test_the_edge_linkage_is_traversed(self, endpoint, build):
        """frame --Edge_hasKGSlot--> slot: frame is the edge SOURCE, slot the
        DESTINATION. Reversing these silently returns nothing."""
        q = build(endpoint)
        assert f"{VITAL}hasEdgeDestination> ?slot" in q, (
            "the slot must be the edge DESTINATION")
        assert f"{VITAL}hasEdgeSource> <{FRAME}>" in q, (
            "the frame must be the edge SOURCE")

    @pytest.mark.parametrize("build", [_list, _count], ids=["list", "count"])
    def test_the_attribute_linkage_still_works(self, endpoint, build):
        """21 spaces use only this one; it must not be traded away."""
        q = build(endpoint)
        assert f"{HALEY}hasFrameGraphURI" in q
        for cls in ("KGTextSlot", "KGIntegerSlot", "KGDateTimeSlot",
                    "KGBooleanSlot", "KGDoubleSlot"):
            assert f"{HALEY}{cls}" in q, f"{cls} dropped from the subclass list"

    def test_list_and_count_use_the_same_pattern(self, endpoint):
        """A count from one linkage beside a list from both reads as data loss:
        the page would show slots and a total of zero."""
        pattern = endpoint._build_slot_match_pattern(FRAME)
        assert pattern in _list(endpoint)
        assert pattern in _count(endpoint)


class TestScoping:

    def test_scoped_to_the_frame_on_both_sides(self, endpoint):
        """Without this the panel lists every slot in the graph."""
        q = _list(endpoint)
        assert f"{HALEY}hasFrameGraphURI> <{FRAME}>" in q, "attribute side unscoped"
        assert f"{VITAL}hasEdgeSource> <{FRAME}>" in q, "connection side unscoped"

    def test_unscoped_listing_does_not_join_the_edge(self, endpoint):
        """Listing every slot in a graph needs only the type; joining the edge
        would add cost for nothing."""
        q = _list(endpoint, frame_uri=None)
        assert f"{HALEY}KGEntitySlot" in q
        assert "hasEdgeSource" not in q
        assert f"hasFrameGraphURI> <" not in q, "no frame to scope to"

    def test_distinct_guards_the_overlap(self, endpoint):
        """6 spaces carry both linkages, so a slot can match both branches."""
        assert "SELECT DISTINCT ?slot" in _list(endpoint)
        assert "COUNT(DISTINCT ?slot)" in _count(endpoint)
