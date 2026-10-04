"""`VitalGraphClient` wraps every KGEntities and KGFrames endpoint method, faithfully.

The flat methods on `VitalGraphClient` delegate to `client.kgentities` /
`client.kgframes`. They covered only part of those endpoints — no slot route,
no entity-frame write, no child frames — and the ones they did cover drifted:
the batch delete passed a string the endpoint iterated character by character
and deleted nothing; the delete wrappers dropped `delete_entity_graph`,
`recursive` and `if_unmodified_since` (`issues/256`); and two forwarded
POSITIONALLY into endpoint signatures that had grown since —
`list_kgentities(search=...)` arrived as the ENTITY TYPE filter, and
`get_kgframes_with_slots` put page_size in frame_uri, offset in page_size and
search in offset.

So, for every public coroutine on the two endpoints:
  * a wrapper of the same name exists;
  * it declares the same parameters with the same defaults;
  * calling it hands EVERY argument through, with its value, to the endpoint;
and `VitalGraphClient` still implements every abstract method of its interface.
"""

import inspect
from unittest.mock import AsyncMock

import pytest

from vitalgraph.client.endpoint.kgentities_endpoint import KGEntitiesEndpoint
from vitalgraph.client.endpoint.kgframes_endpoint import KGFramesEndpoint
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.client.vitalgraph_client_inf import VitalGraphClientInterface

ENDPOINTS = {"kgentities": KGEntitiesEndpoint, "kgframes": KGFramesEndpoint}

CASES = [
    (attr, name)
    for attr, cls in ENDPOINTS.items()
    for name, fn in inspect.getmembers(cls, inspect.iscoroutinefunction)
    if not name.startswith("_")
]

# Where a wrapper's default deliberately differs from the endpoint's.
# get_kgentity_frames: the wrapper has always defaulted entity_uri to None;
# making it required would break callers that omit it.
DEFAULT_DIFFERS = {("get_kgentity_frames", "entity_uri")}


def _params(fn):
    return [(p.name, p.default) for p in inspect.signature(fn).parameters.values()
            if p.name != "self" and p.kind not in (p.VAR_KEYWORD, p.VAR_POSITIONAL)]


def _defaults(name, fn):
    return {p: (None if (name, p) in DEFAULT_DIFFERS else d) for p, d in _params(fn)}


@pytest.mark.parametrize("attr,name", CASES, ids=[f"{a}.{n}" for a, n in CASES])
def test_every_endpoint_method_has_a_wrapper(attr, name):
    assert inspect.iscoroutinefunction(getattr(VitalGraphClient, name, None)), (
        f"VitalGraphClient has no wrapper for {attr}.{name}")


@pytest.mark.parametrize("attr,name", CASES, ids=[f"{a}.{n}" for a, n in CASES])
def test_the_wrapper_declares_the_endpoint_parameters(attr, name):
    """Same names, same defaults. NOT the same order: a wrapper keeps the
    positional order its callers already rely on and appends what the endpoint
    gained since, forwarding by keyword."""
    endpoint = _defaults(name, getattr(ENDPOINTS[attr], name))
    wrapper = _defaults(name, getattr(VitalGraphClient, name))
    assert wrapper == endpoint, f"{name}: wrapper {wrapper} != endpoint {endpoint}"


@pytest.mark.parametrize("attr,name", CASES, ids=[f"{a}.{n}" for a, n in CASES])
async def test_the_wrapper_forwards_every_argument(attr, name):
    """Each parameter gets a distinct sentinel; the endpoint must receive all of
    them, bound to the right names — a dropped or swapped argument fails."""
    client = VitalGraphClient.__new__(VitalGraphClient)
    mock = AsyncMock(return_value="result")
    setattr(client, attr, type("E", (), {name: mock})())
    sentinels = {p: f"<{p}>" for p, _ in _params(getattr(VitalGraphClient, name))}
    assert await getattr(client, name)(**sentinels) == "result"
    got = inspect.signature(getattr(ENDPOINTS[attr], name)).bind(
        None, *mock.call_args.args, **mock.call_args.kwargs).arguments
    got.pop("self")
    assert got == sentinels


def test_the_client_implements_its_interface():
    missing = sorted(getattr(VitalGraphClient, "__abstractmethods__", set()))
    assert not missing, f"VitalGraphClient leaves abstract: {missing}"
    for name in VitalGraphClientInterface.__abstractmethods__:
        assert getattr(VitalGraphClient, name) is not getattr(VitalGraphClientInterface, name)
