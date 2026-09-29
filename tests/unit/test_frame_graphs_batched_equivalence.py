"""The batched frame-graph query must return what the per-frame one returns.

`issues/240`. `get_frame_graphs` collapses N SELECTs into one by binding `?frame`
from a VALUES clause instead of interpolating a literal. The risk is entirely in
the four UNION arms.

WHY THAT RISK IS REAL AND SILENT. The singular query's own docstring records it:
only the ATTRIBUTE linkage was implemented once, so a CONNECTION frame returned
the frame alone, `get_frame_graph` read one object as "frame only" and returned
None, and the UI reported "No slots found for this frame" for a frame that had
two. A graph pattern anchored on an absent predicate matches nothing rather than
failing — so a dropped arm produces empty results, not an error.

These tests use the SINGULAR builder as the oracle: whatever arms it has, the
plural one must have, bound to `?frame` instead of a literal.
"""

import re

import pytest

from vitalgraph.kg_impl.kgframe_graph_impl import KGFrameGraphProcessor


@pytest.fixture
def proc():
    return object.__new__(KGFrameGraphProcessor)


def _arms(q: str):
    """The UNION arms, normalised so a literal frame and `?frame` compare equal."""
    body = q[q.index("GRAPH"):]
    parts = [p.strip() for p in body.split("UNION")]
    out = []
    for p in parts:
        p = re.sub(r"<urn:[^>]*>", "?frame", p)          # literal -> variable
        p = re.sub(r"BIND\(\?frame AS \?subject\)", "BIND", p)
        p = re.sub(r"\s+", " ", p)
        out.append(p)
    return out


def test_the_plural_query_keeps_every_arm_of_the_singular_one(proc):
    """THE TEST THIS CHANGE EXISTS FOR. A missing arm is silent in production."""
    single = proc._build_frame_graph_query("urn:f1", "urn:g")
    plural = proc._build_frame_graphs_query(["urn:f1", "urn:f2"], "urn:g")

    for marker in ("hasFrameGraphURI", "hasEdgeSource", "hasEdgeDestination"):
        assert single.count(marker) == plural.count(marker), (
            f"arm count differs for {marker}: the batched query has dropped or "
            f"duplicated a linkage, which fails SILENTLY at runtime")
    assert single.count("UNION") == plural.count("UNION")


def test_the_plural_query_binds_frame_from_VALUES(proc):
    q = proc._build_frame_graphs_query(["urn:f1", "urn:f2"], "urn:g")
    assert "VALUES ?frame" in q
    assert "<urn:f1>" in q and "<urn:f2>" in q
    # and it must project the frame, or results cannot be grouped back
    assert "SELECT DISTINCT ?frame ?subject" in q


def test_no_frame_uri_is_interpolated_into_a_pattern(proc):
    """If a URI is still spliced into an arm, the VALUES clause is decorative
    and the query answers for one frame."""
    q = proc._build_frame_graphs_query(["urn:f1", "urn:f2"], "urn:g")
    body = q[q.index("GRAPH"):]
    assert "<urn:f1>" not in body and "<urn:f2>" not in body


@pytest.mark.asyncio
async def test_objects_are_fetched_once_for_a_subject_shared_by_two_frames(proc):
    """The point of batching. A subject reachable from two frames must be
    fetched once, not once per frame."""
    import types
    proc.logger = types.SimpleNamespace(info=lambda *a, **k: None,
                                        error=lambda *a, **k: None,
                                        warning=lambda *a, **k: None)
    calls = []

    class _Obj:
        def __init__(self, uri): self.URI = uri

    async def _q(space_id, query):
        return {"results": {"bindings": [
            {"frame": {"value": "urn:f1"}, "subject": {"value": "urn:shared"}},
            {"frame": {"value": "urn:f2"}, "subject": {"value": "urn:shared"}},
            {"frame": {"value": "urn:f1"}, "subject": {"value": "urn:only1"}},
        ]}}

    async def _get(space_id, uris, graph_id):
        calls.append(list(uris))
        return [_Obj(u) for u in uris]

    adapter = types.SimpleNamespace(execute_sparql_query=_q,
                                    get_objects_by_uris=_get)
    out = await proc.get_frame_graphs(adapter, "sp", "urn:g", ["urn:f1", "urn:f2"])

    assert len(calls) == 1, f"objects fetched {len(calls)} times, expected 1"
    assert sorted(calls[0]) == ["urn:only1", "urn:shared"], "subjects not deduped"
    assert {str(o.URI) for o in out["urn:f1"]} == {"urn:shared", "urn:only1"}
    assert {str(o.URI) for o in out["urn:f2"]} == {"urn:shared"}


@pytest.mark.asyncio
async def test_empty_input_makes_no_query(proc):
    import types
    proc.logger = types.SimpleNamespace(info=lambda *a, **k: None,
                                        error=lambda *a, **k: None)
    called = []

    async def _q(*a, **k):
        called.append(1)
        return {}

    adapter = types.SimpleNamespace(execute_sparql_query=_q,
                                    get_objects_by_uris=None)
    assert await proc.get_frame_graphs(adapter, "sp", "urn:g", []) == {}
    assert not called


# --------------------------------------------------------------------------
# `issues/250` — the connection arms must be typed
# --------------------------------------------------------------------------

@pytest.mark.parametrize("build", ["single", "plural"])
def test_both_connection_arms_are_typed_to_the_slot_edge(proc, build):
    """THE CHILD-FRAME STUB. Untyped, these arms matched ANY edge out of the
    frame, and a frame's other outbound edge is `Edge_hasKGFrame` -> a CHILD
    frame. The child arrived with none of its slots (it carries its own
    `hasFrameGraphURI`, which the attribute arm cannot reach from the parent),
    and a frame with zero slots reads exactly like a frame whose slots were not
    fetched.

    Both builders are checked: they must move together, and the equivalence test
    above only proves they AGREE, not that either is right.
    """
    q = (proc._build_frame_graph_query("urn:f1", "urn:g") if build == "single"
         else proc._build_frame_graphs_query(["urn:f1"], "urn:g"))

    assert q.count("haley:Edge_hasKGSlot") == 2, (
        "expected both connection arms typed to the slot edge; an untyped arm "
        "pulls the child frame into its parent's graph")


@pytest.mark.parametrize("build", ["single", "plural"])
def test_the_type_filter_uses_vitaltype_not_rdf_type(proc, build):
    """NOT INTERCHANGEABLE, and wrong is silent.

    `vitaltype` is the single-valued type URI this codebase counts on, and the
    predicate `kg_query_builder.py` already uses to type a slot edge. `rdf:type`
    is present in the data too, so this looks like a free choice — but anchoring
    the arm on the wrong predicate matches nothing, and every CONNECTION frame
    comes back slotless with no error. That is the exact failure the four arms
    exist to prevent.
    """
    q = (proc._build_frame_graph_query("urn:f1", "urn:g") if build == "single"
         else proc._build_frame_graphs_query(["urn:f1"], "urn:g"))

    assert q.count("vital:vitaltype haley:Edge_hasKGSlot") == 2
    assert "rdf:type haley:Edge_hasKGSlot" not in q


def test_the_slot_edge_itself_is_still_returned(proc):
    """Typing must not be mistaken for "only the slots". The client pairs the
    EDGE with its destination to identify a slot, so dropping the edge arm
    renders nothing — see the singular builder's note."""
    q = proc._build_frame_graphs_query(["urn:f1"], "urn:g")

    assert "?subject vital:hasEdgeSource ?frame" in q, (
        "the arm returning the edge object itself is gone")
