"""The frame-grouping rule, `issues/257`: every frame is grouped with itself.

- a KGFrame's hasFrameGraphURI is its own URI;
- a slot's is the frame that links it by Edge_hasKGSlot;
- an Edge_hasKGSlot's is its source frame;
- and nothing a client sent survives.

`assign_frame_groupings` is the single place every write path now decides this.
Before it, eight places did, and between them they let a client's value
through for a slot with no edge in a multi-frame payload, for an edge whose
source frame was not in the payload, for any slot outside a six-class list,
and for every slot written through the slot route.
"""

from __future__ import annotations

import pytest

from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGChoiceSlot import KGChoiceSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGGeoLocationSlot import KGGeoLocationSlot
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGURISlot import KGURISlot

from vitalgraph.kg_impl.frame_grouping import UngroupableSlot, assign_frame_groupings

WRONG = "urn:client:sent:this"


def _frame(uri, fgu=WRONG):
    f = KGFrame()
    f.URI = uri
    f.frameGraphURI = fgu
    return f


def _slot(uri, cls=KGTextSlot, fgu=WRONG):
    s = cls()
    s.URI = uri
    s.frameGraphURI = fgu
    return s


def _edge(cls, uri, src, dst, fgu=WRONG):
    e = cls()
    e.URI = uri
    e.edgeSource = src
    e.edgeDestination = dst
    e.frameGraphURI = fgu
    return e


def _g(obj):
    v = obj.frameGraphURI
    return str(v) if v is not None else None


def test_a_frame_is_grouped_with_itself_whatever_the_client_sent():
    f = _frame("urn:f1")
    assign_frame_groupings([f])
    assert _g(f) == "urn:f1"


def test_a_slot_is_grouped_with_the_frame_its_edge_names():
    f1, f2 = _frame("urn:f1"), _frame("urn:f2")
    s = _slot("urn:s1")
    e = _edge(Edge_hasKGSlot, "urn:e1", "urn:f2", "urn:s1")
    assign_frame_groupings([f1, f2, s, e])
    assert _g(s) == "urn:f2"
    assert _g(e) == "urn:f2", "an Edge_hasKGSlot is grouped with its source frame"


def test_the_edge_decides_even_when_its_frame_is_not_in_the_request():
    # The old code required the edge's source to be a frame IN the payload;
    # otherwise the slot kept the client's value.
    s = _slot("urn:s1")
    e = _edge(Edge_hasKGSlot, "urn:e1", "urn:f_elsewhere", "urn:s1")
    assign_frame_groupings([_frame("urn:fa"), _frame("urn:fb"), s, e])
    assert _g(s) == "urn:f_elsewhere"
    assert _g(e) == "urn:f_elsewhere"


@pytest.mark.parametrize("cls", [KGTextSlot, KGChoiceSlot, KGURISlot, KGGeoLocationSlot],
                         ids=lambda c: c.__name__)
def test_every_slot_class_is_grouped_not_just_six(cls):
    s = _slot("urn:s1", cls=cls)
    e = _edge(Edge_hasKGSlot, "urn:e1", "urn:f1", "urn:s1")
    assign_frame_groupings([_frame("urn:f1"), _frame("urn:f2"), s, e])
    assert _g(s) == "urn:f1", f"{cls.__name__} kept the client's grouping"


def test_a_single_frame_owns_a_slot_that_no_edge_claims():
    s = _slot("urn:s1")
    assign_frame_groupings([_frame("urn:f1"), s])
    assert _g(s) == "urn:f1"


def test_the_routes_owning_frame_places_a_slot_with_no_frame_in_the_request():
    # The slot route: the payload holds slots only, the URL names the frame.
    s = _slot("urn:s1")
    assign_frame_groupings([s], owning_frame_uri="urn:f_route")
    assert _g(s) == "urn:f_route", "the slot kept the client's grouping"


def test_an_edge_still_beats_the_routes_owning_frame():
    s = _slot("urn:s1")
    e = _edge(Edge_hasKGSlot, "urn:e1", "urn:f_edge", "urn:s1")
    assign_frame_groupings([s, e], owning_frame_uri="urn:f_route")
    assert _g(s) == "urn:f_edge"


def test_a_slot_that_cannot_be_placed_is_refused_naming_it():
    s1, s2 = _slot("urn:s1"), _slot("urn:s2")
    with pytest.raises(UngroupableSlot) as exc:
        assign_frame_groupings([_frame("urn:f1"), _frame("urn:f2"), s1, s2])
    assert exc.value.slot_uris == ["urn:s1", "urn:s2"]
    assert "Edge_hasKGSlot" in str(exc.value)


def test_a_lone_slot_with_no_frame_anywhere_is_refused():
    with pytest.raises(UngroupableSlot):
        assign_frame_groupings([_slot("urn:s1")])


def test_objects_without_the_property_are_skipped():
    # KGEntity and Edge_hasEntityKGFrame do not carry hasFrameGraphURI in the
    # domain model at all, so a client cannot send one; they are in the entity
    # graph and no frame's.
    ent = KGEntity()
    ent.URI = "urn:ent"
    ef = Edge_hasEntityKGFrame()
    ef.URI = "urn:ef"
    ef.edgeSource = "urn:ent"
    ef.edgeDestination = "urn:f1"
    f = _frame("urn:f1")
    assign_frame_groupings([ent, ef, f])
    assert _g(f) == "urn:f1"


def test_a_parent_child_edge_is_in_no_frames_graph():
    # Decided 2026-10-03: like Edge_hasEntityKGFrame, a parent -> child link
    # belongs to no frame's graph, whatever the client sent and whether or not
    # either frame is in the request.
    for frames in ([], ["urn:child"], ["urn:parent", "urn:child"]):
        e = _edge(Edge_hasKGFrame, "urn:pc", "urn:parent", "urn:child")
        assign_frame_groupings([_frame(f) for f in frames] + [e])
        assert _g(e) is None, f"grouped {_g(e)!r} with frames {frames}"


def test_the_root_grouped_shape_found_in_production_cannot_be_written():
    # issues/257: a child frame and its slot grouped under the ROOT. Sent back
    # as-is, every grouping is recomputed from the frames and edges.
    root, child = _frame("urn:root", fgu="urn:root"), _frame("urn:child", fgu="urn:root")
    slot = _slot("urn:s", fgu="urn:root")
    se = _edge(Edge_hasKGSlot, "urn:se", "urn:child", "urn:s", fgu="urn:root")
    assign_frame_groupings([root, child, slot, se])
    assert (_g(root), _g(child), _g(slot), _g(se)) == (
        "urn:root", "urn:child", "urn:child", "urn:child")
