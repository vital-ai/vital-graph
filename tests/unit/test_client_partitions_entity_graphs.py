"""The entity counterpart of the frame-graph partition, extracted from two
identical inline copies.

`issues/240`. `group_objects_by_entity` and `group_objects_by_frame` shipped
DEAD in `d5d3d636` and were both wrong the same way — `groups[obj.URI].append(obj)`
puts every object in its own group, which is not grouping by entity or by frame
at all. Nothing ever called either one, so nothing ever failed.

The frame one was superseded by `group_objects_by_frame_graph` and deleted. The
entity one was replaced by THIS function, whose body is the rule
`kgentities_endpoint` had already open-coded correctly in both of its
`include_entity_graph` branches. So the risk being tested is not "does the
grouping work" — it demonstrably did, inline, at two sites — but that a helper
with an inviting name now exists where a WRONG one used to, and that the two
copies cannot drift apart again.
"""

from vitalgraph.client.response.response_builder import group_objects_by_entity_graph


class _Obj:
    def __init__(self, uri, graph_uri=None):
        self.URI = uri
        self.kGGraphURI = graph_uri


def test_objects_are_grouped_by_their_graph_not_by_themselves():
    """THE DEFECT IN THE HELPER THIS REPLACED.

    Keying on `obj.URI` gave three groups of one. The entity graph URI is what
    says which graph an object belongs to.
    """
    objs = [_Obj("urn:a", "urn:g1"), _Obj("urn:b", "urn:g1"), _Obj("urn:c", "urn:g2")]

    groups = group_objects_by_entity_graph(objs)

    assert set(groups) == {"urn:g1", "urn:g2"}
    assert [o.URI for o in groups["urn:g1"]] == ["urn:a", "urn:b"]
    assert [o.URI for o in groups["urn:g2"]] == ["urn:c"]


def test_an_object_with_no_graph_uri_is_dropped_not_collected_under_None():
    """A `None` key becomes `build_entity_graph(None, objs)` — a graph that does
    not exist, rendered in the response list alongside real ones."""
    groups = group_objects_by_entity_graph([_Obj("urn:a", "urn:g1"), _Obj("urn:orphan")])

    assert list(groups) == ["urn:g1"]
    assert None not in groups


def test_the_attribute_missing_entirely_is_also_dropped():
    """The inline copies used `hasattr(obj, 'kGGraphURI') and obj.kGGraphURI`;
    this uses `getattr(obj, ..., None)`. Same outcome, and it has to stay so —
    a deserialised object need not carry the field at all."""
    class _Bare:
        URI = "urn:bare"

    assert group_objects_by_entity_graph([_Bare()]) == {}


def test_the_graph_uri_is_stringified():
    """`kGGraphURI` is a VitalSigns property object, not a str. Grouping on the
    raw value would key on identity and split one graph into many."""
    class _URIValue:
        def __init__(self, v):
            self._v = v

        def __str__(self):
            return self._v

    objs = [_Obj("urn:a", _URIValue("urn:g1")), _Obj("urn:b", _URIValue("urn:g1"))]

    groups = group_objects_by_entity_graph(objs)

    assert list(groups) == ["urn:g1"], "two property objects for one graph split it"
    assert len(groups["urn:g1"]) == 2


def test_the_endpoint_no_longer_open_codes_it():
    """Both `include_entity_graph` branches must route through the helper.

    Checked textually: exercising them needs a live server and a deserialiser,
    and the property is "there is one copy of this rule", which is textual. Two
    call sites and one missed leaves the duplication this removed.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2]
           / "vitalgraph" / "client" / "endpoint" / "kgentities_endpoint.py").read_text()

    assert src.count("group_objects_by_entity_graph(objects)") == 2, (
        "an include_entity_graph branch still groups inline")
    assert "entity_graphs_dict.setdefault" not in src, (
        "the open-coded grouping is back")


def test_the_dead_helpers_are_gone():
    """Neither may come back under its old name: both were wrong, and both had a
    working replacement. `group_objects_by_frame` in particular sits one
    autocomplete away from `group_objects_by_frame_graph`, which is correct."""
    from vitalgraph.client.response import response_builder

    assert not hasattr(response_builder, "group_objects_by_frame")
    assert not hasattr(response_builder, "group_objects_by_entity")
