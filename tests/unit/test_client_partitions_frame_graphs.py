"""A merged frame-graph response must be split back into per-frame graphs.

`issues/240`. The `uris=` endpoint now answers N frames in ONE query and returns
a single flat, de-duplicated object list. The client turned that into
`MultiFrameGraphResponse` by calling `build_frame_graph(uri, objects)` per
frame — handing EVERY frame the WHOLE list.

That was invisible for as long as the server dropped the flag: the list held
only the frames themselves, so each FrameGraph got N frames and no slots. Wrong,
but nothing looked like slots. The moment the server started returning graphs,
every frame would claim every other frame's slots — and `FrameGraph.objects` is
documented as "GraphObjects in THIS frame graph".

So this is a client bug that the server fix EXPOSES rather than causes, which is
why it is tested here in its own right.
"""

import pytest

from vitalgraph.client.response.response_builder import group_objects_by_frame_graph


class _Frame:
    def __init__(self, uri):
        self.URI = uri


class _AttrSlot:
    """Attribute linkage: the slot names its frame."""

    def __init__(self, uri, frame_uri):
        self.URI = uri
        self.hasFrameGraphURI = frame_uri


class _Edge:
    """Connection linkage: an edge from a frame to a slot."""

    def __init__(self, uri, src, dst):
        self.URI = uri
        self.hasEdgeSource = src
        self.hasEdgeDestination = dst


class _PlainSlot:
    """Reached only as an edge destination — carries no frame property."""

    def __init__(self, uri):
        self.URI = uri


def _uris(objs):
    return {str(o.URI) for o in objs}


def test_each_frame_gets_only_its_own_objects():
    """THE DEFECT. Previously every frame received all six objects."""
    objs = [
        _Frame("urn:f1"), _Frame("urn:f2"),
        _AttrSlot("urn:s1", "urn:f1"),
        _AttrSlot("urn:s2", "urn:f2"),
    ]
    g = group_objects_by_frame_graph(["urn:f1", "urn:f2"], objs)
    assert _uris(g["urn:f1"]) == {"urn:f1", "urn:s1"}
    assert _uris(g["urn:f2"]) == {"urn:f2", "urn:s2"}


def test_the_connection_linkage_is_followed_to_the_slot():
    """The arm whose absence produced "No slots found for this frame" for a
    frame with two — a slot reached ONLY through its edge."""
    objs = [
        _Frame("urn:f1"),
        _Edge("urn:e1", "urn:f1", "urn:s1"),
        _PlainSlot("urn:s1"),
    ]
    g = group_objects_by_frame_graph(["urn:f1"], objs)
    assert _uris(g["urn:f1"]) == {"urn:f1", "urn:e1", "urn:s1"}, (
        "the edge destination was not followed — connection frames lose their "
        "slots, silently")


def test_a_slot_shared_by_two_frames_appears_in_both():
    """Matching what a per-frame fetch would have returned."""
    objs = [
        _Frame("urn:f1"), _Frame("urn:f2"),
        _AttrSlot("urn:shared", "urn:f1"),
        _Edge("urn:e2", "urn:f2", "urn:shared"),
    ]
    g = group_objects_by_frame_graph(["urn:f1", "urn:f2"], objs)
    assert "urn:shared" in _uris(g["urn:f1"])
    assert "urn:shared" in _uris(g["urn:f2"])


def test_an_object_reachable_twice_is_listed_once():
    """Both linkages can reach the same slot; it is one object."""
    objs = [
        _Frame("urn:f1"),
        _AttrSlot("urn:s1", "urn:f1"),
        _Edge("urn:e1", "urn:f1", "urn:s1"),
    ]
    g = group_objects_by_frame_graph(["urn:f1"], objs)
    got = [str(o.URI) for o in g["urn:f1"]]
    assert got.count("urn:s1") == 1, f"duplicated: {got}"


def test_a_frame_with_nothing_gets_an_empty_list_not_everything():
    """The failure mode being fixed: absence must not become the whole list."""
    objs = [_Frame("urn:f1"), _AttrSlot("urn:s1", "urn:f1")]
    g = group_objects_by_frame_graph(["urn:f1", "urn:missing"], objs)
    assert g["urn:missing"] == []


def test_the_client_uses_the_partition():
    """Asserted against source: the response builder is where the merged list
    becomes per-frame graphs, and passing `objects` wholesale is the bug."""
    import inspect
    from vitalgraph.client.endpoint import kgframes_endpoint as ce
    src = inspect.getsource(ce)
    assert "group_objects_by_frame_graph(uris, objects)" in src
    assert "build_frame_graph(uri, objects) for uri in uris" not in src, (
        "every frame is being handed the whole object list again")
