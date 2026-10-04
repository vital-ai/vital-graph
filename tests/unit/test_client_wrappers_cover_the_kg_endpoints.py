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


# ── Every OTHER wrapper: forwards to a method that exists, under the right names ──
#
# The same positional drift had broken wrappers outside KG entities and frames:
# the six KGType wrappers still passed `graph_id` after KGTypes became
# space-scoped (five raised TypeError, list_kgtypes sent the graph id as
# page_size); upload_file_content sent the file URI as the graph and the graph
# as the data; search_triples and execute_graph_operation called endpoint
# methods that do not exist.

import re  # noqa: E402

import vitalgraph.client.vitalgraph_client as _client_module  # noqa: E402

# Wrapper parameter -> endpoint parameter, where the names differ on purpose.
RENAMED = {
    "upload_file_content": {"uri": "file_uri", "file_path": "source"},
    "search_triples": {"limit": "page_size", "object_value": "object"},
}
# Wrapper parameters accepted and deliberately NOT forwarded.
IGNORED = {n: {"graph_id"} for n in (
    "list_kgtypes", "get_kgtype", "create_kgtypes", "update_kgtypes",
    "delete_kgtype", "delete_kgtypes_batch")}
_CLIENT_SRC = inspect.getsource(VitalGraphClient)


def _delegations():
    out = []
    for name, fn in inspect.getmembers(VitalGraphClient, inspect.iscoroutinefunction):
        if name.startswith("_"):
            continue
        calls = set(re.findall(r"self\.(\w+)\.(\w+)\(", inspect.getsource(fn)))
        if len(calls) != 1:
            continue
        attr, target = calls.pop()
        assigned = re.search(rf"self\.{attr}\s*=\s*(\w+)\(", _CLIENT_SRC)
        cls = getattr(_client_module, assigned.group(1), None) if assigned else None
        if isinstance(cls, type) and cls.__name__.endswith("Endpoint"):
            out.append((name, attr, cls, target))
    return out


DELEGATIONS = _delegations()


def test_the_delegations_were_found():
    assert len(DELEGATIONS) > 100, len(DELEGATIONS)


@pytest.mark.parametrize("name,attr,cls,target", DELEGATIONS,
                         ids=[d[0] for d in DELEGATIONS])
async def test_every_wrapper_reaches_its_endpoint_with_the_right_arguments(name, attr, cls, target):
    assert hasattr(cls, target), f"{name} calls {attr}.{target}, which does not exist"
    client = VitalGraphClient.__new__(VitalGraphClient)
    mock = AsyncMock(return_value="result")
    setattr(client, attr, type("E", (), {target: mock})())
    sent = {p: f"<{p}>" for p, _ in _params(getattr(VitalGraphClient, name))}
    await getattr(client, name)(**sent)
    got = inspect.signature(getattr(cls, target)).bind(
        None, *mock.call_args.args, **mock.call_args.kwargs).arguments
    got.pop("self")
    got.update(got.pop("kwargs", {}) or {})
    rename = RENAMED.get(name, {})
    expected = {rename.get(p, p): v for p, v in sent.items() if p not in IGNORED.get(name, set())}
    assert got == expected
