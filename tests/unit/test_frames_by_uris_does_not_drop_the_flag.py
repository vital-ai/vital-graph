"""`include_frame_graph` works on the `uris=` form, not just `?uri=`.

`issues/240`. The flag was in the signature of `_get_frames_by_uris` and NOWHERE
in the body, so the multi-URI lookup returned frames without their graphs —
HTTP 200, `status=FOUND`, nothing to say a parameter had been ignored. The
single-URI sibling implemented it all along, which is what made this a drop
rather than an unbuilt feature.

It survived because it was untested: the only `/kgframes` cell with the flag set
covers `?uri=`, and its docstring says so. **The control pair — flag true gets
graph objects, flag false does not — is what catches it**, and it is the pair
`issues/210` used on the neighbouring surface.

Driven through the function with a stubbed backend rather than a live space: the
property under test is whether the flag is READ, and a real space would only add
setup that can itself fail.
"""

import asyncio
import types

import pytest

from vitalgraph.endpoint import kgframes_endpoint


class _Obj:
    """Minimal GraphObject stand-in: `_dedupe_by_uri` keys on URI."""

    def __init__(self, uri):
        self.URI = uri

    def __repr__(self):
        return f"<{self.URI}>"


class _LookupResult:
    def __init__(self, objects):
        self.objects = objects


@pytest.fixture(autouse=True)
def _no_quad_serialisation(monkeypatch):
    """Quad conversion needs real VitalSigns internals and is not what is under
    test here — the question is whether the FLAG IS READ. Swap it for a shim
    that preserves one quad per object so the assertions can see them."""
    from vitalgraph.model.quad_model import Quad

    def _shim(objects, graph_id):
        # Real `Quad` — the response model validates, so a namespace is rejected.
        return [Quad(s=f"<{o.URI}>", p="<urn:p>", o="<urn:o>", g=f"<{graph_id}>")
                for o in objects]
    monkeypatch.setattr(kgframes_endpoint, "graphobjects_to_quad_list", _shim)


def _endpoint(graph_objects_for):
    """A KGFramesEndpoint with the two collaborators this path uses stubbed."""
    ep = object.__new__(kgframes_endpoint.KGFramesEndpoint)
    ep.logger = types.SimpleNamespace(
        info=lambda *a, **k: None, warning=lambda *a, **k: None,
        error=lambda *a, **k: None, debug=lambda *a, **k: None)

    async def _adapter(space_id):
        async def get_object(space_id, graph_id, uri):
            return _LookupResult([_Obj(uri)])
        return types.SimpleNamespace(get_object=get_object)

    ep._get_backend_adapter = _adapter

    async def _frame_graph(space_id, graph_id, frame_uri, current_user):
        objs = graph_objects_for(frame_uri)
        return types.SimpleNamespace(graph_objects=objs, graph=None) if objs else None

    ep._get_frame_graph = _frame_graph

    # The uris= form now goes through the BATCHED processor call. Recording the
    # frames it was asked for is what lets the control test assert that a caller
    # who did not ask causes no query at all.
    async def _get_frame_graphs(backend_adapter, space_id, graph_id, frame_uris):
        out = {}
        for u in frame_uris:
            objs = graph_objects_for(u)
            if objs:
                out[u] = objs
        return out

    ep.frame_graph_processor = types.SimpleNamespace(
        get_frame_graphs=_get_frame_graphs)
    return ep


def _uris_of(resp):
    return {q.s.strip("<>") for q in resp.results} if resp.results else set()


@pytest.mark.asyncio
async def test_the_flag_TRUE_returns_the_frame_graph():
    """The defect: this returned only the frames."""
    ep = _endpoint(lambda uri: [_Obj(uri), _Obj(uri + ":slot1")])
    resp = await ep._get_frames_by_uris(
        "sp", "urn:g", ["urn:f1", "urn:f2"], include_frame_graph=True,
        current_user={})
    got = _uris_of(resp)
    assert "urn:f1:slot1" in got and "urn:f2:slot1" in got, (
        f"the frame graphs are missing — the flag is still being dropped: {got}")


@pytest.mark.asyncio
async def test_the_flag_FALSE_returns_only_the_frames():
    """THE CONTROL. Without it, a function that always fetched graphs would
    pass the test above while ignoring the flag just as completely."""
    called = []

    def _graph(uri):
        called.append(uri)
        return [_Obj(uri + ":slot1")]

    ep = _endpoint(_graph)
    resp = await ep._get_frames_by_uris(
        "sp", "urn:g", ["urn:f1"], include_frame_graph=False, current_user={})
    assert called == [], "the graph was fetched for a caller that did not ask"
    assert _uris_of(resp) == {"urn:f1"}


@pytest.mark.asyncio
async def test_the_frame_is_not_emitted_twice():
    """The de-duplication trap the sibling documents: the frame is in BOTH the
    lookup result and its own graph, so every one of its quads would emit twice.
    Invisible until the graph actually contains something."""
    ep = _endpoint(lambda uri: [_Obj(uri), _Obj(uri + ":slot1")])
    resp = await ep._get_frames_by_uris(
        "sp", "urn:g", ["urn:f1"], include_frame_graph=True, current_user={})
    subjects = [q.s.strip("<>") for q in resp.results]
    assert subjects.count("urn:f1") == len(
        [s for s in set(subjects) if s == "urn:f1"]), (
        f"the frame's quads are duplicated: {subjects}")


@pytest.mark.asyncio
async def test_a_frame_with_no_graph_still_returns_the_frame():
    """`_get_frame_graph` returns None for a frame with no attribute-linked
    slots. That must not drop the frame itself."""
    ep = _endpoint(lambda uri: None)
    resp = await ep._get_frames_by_uris(
        "sp", "urn:g", ["urn:f1"], include_frame_graph=True, current_user={})
    assert _uris_of(resp) == {"urn:f1"}


def test_the_kgqueries_message_no_longer_misdirects():
    """It told callers to use `/kgframes` 'where the flag is implemented on the
    URI lookups' while the `uris=` form dropped it. Now both forms implement it,
    so the message must not claim otherwise either."""
    import inspect
    from vitalgraph.endpoint import kgquery_endpoint
    q = inspect.getsource(kgquery_endpoint)
    assert "the flag is implemented on the URI lookups" not in q
