"""A fast-served page must still carry the entity graphs it was asked for.

`issues/209`. `include_entity_graph` was honoured only on the general pipeline:
the hydration block sits at `kgquery_endpoint.py:876`, BELOW both fast-path
returns, and neither `can_serve` nor `can_serve_filter` counted the flag among
its disqualifiers. So the shapes MOST likely to want hydration — a sorted list,
a filtered list, and since `issues/172` both at once — were the shapes that lost
it, with a 200, a correct page, a correct total, and `entity_graphs: null`.
Character for character the response for not having asked.

Reproduced against the vg-test stack on `lead_nurture_grouped` before the fix:

    baseline (general pipeline)   25 uris   25 graphs   18,937 quads   43.5 s
    + a slot-value sort           25 uris    0 graphs            0      1.0 s
    + frame-criteria equality     25 uris    0 graphs            0      0.3 s

with the server log naming `entity_slot_sort` as what served the last two.

These tests are at the DISPATCH, not in the SQL, because the SQL was never
wrong. Three things are pinned, and the third is why the fix is not "decline the
fast path when the flag is set": hydration must not happen when nobody asked for
it, or the fast path pays a 4-second fan-out to answer a question about URIs.
"""

from __future__ import annotations

import pytest

from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint
from vitalgraph.model.kgqueries_model import KGQueryCriteria, KGQueryRequest

_URIS = ["urn:e:a", "urn:e:b"]
_GRAPHS = {"urn:e:a": [{"s": "urn:e:a", "p": "urn:p", "o": "1", "g": "urn:g"}]}


class _Pool:
    """An asyncpg pool whose connection is never actually used here."""

    def acquire(self):
        class _CM:
            async def __aenter__(self_inner):
                return object()

            async def __aexit__(self_inner, *exc):
                return False
        return _CM()


class _Backend:
    def __init__(self):
        self.db_impl = type("Impl", (), {"connection_pool": _Pool()})()


def _request(include_graph, count_only=False):
    return KGQueryRequest(
        criteria=KGQueryCriteria(query_type="entity"),
        page_size=25, offset=0,
        include_entity_graph=include_graph, count_only=count_only)


class _Criteria:
    entity_type = "urn:t:entity:E"


@pytest.fixture
def endpoint(monkeypatch):
    """The endpoint with every collaborator of the two fast paths stubbed.

    The fast paths import their helpers INSIDE the method, so patching the
    source modules is what reaches them -- patching the endpoint module would
    not.
    """
    from vitalgraph.db.sparql_sql import fast_slot_filter, fast_slot_sort

    async def _page(*a, **k):
        return list(_URIS)

    async def _count(*a, **k):
        return len(_URIS)

    async def _not_blocked(*a, **k):
        return False

    monkeypatch.setattr(fast_slot_sort, "can_serve", lambda c: True)
    monkeypatch.setattr(fast_slot_sort, "fast_slot_sort_page", _page)
    monkeypatch.setattr(fast_slot_sort, "fast_slot_sort_count", _count)
    monkeypatch.setattr(fast_slot_filter, "can_serve_filter", lambda c: True)
    monkeypatch.setattr(fast_slot_filter, "fast_slot_filter_page", _page)
    monkeypatch.setattr(fast_slot_filter, "fast_slot_filter_count", _count)
    monkeypatch.setattr(fast_slot_filter, "slot_sort_is_blocked", _not_blocked)

    ep = KGQueriesEndpoint(space_manager=None, auth_dependency=None)
    ep.fetched = []

    async def _fetch(backend, space_id, graph_id, uris):
        ep.fetched.append(list(uris))
        return dict(_GRAPHS)

    ep._fetch_entity_graphs = _fetch
    return ep


async def _run(ep, which, request):
    fn = (ep._try_fast_slot_sort if which == "sort"
          else ep._try_fast_slot_filter)
    return await fn(_Backend(), "sp", "urn:g", _Criteria(), request)


@pytest.mark.parametrize("which", ["sort", "filter"])
async def test_the_flag_is_honoured_on_the_fast_path(endpoint, which):
    """The defect: a fast-served page answered with the field unset."""
    resp = await _run(endpoint, which, _request(include_graph=True))

    assert resp is not None, f"the {which} fast path declined; nothing is pinned"
    assert resp.entity_uris == _URIS
    assert resp.entity_graphs == _GRAPHS, (
        f"the {which} fast path returned entity_graphs={resp.entity_graphs!r} "
        f"for a request that set include_entity_graph — the caller cannot tell "
        f"that from having asked for nothing")
    assert endpoint.fetched == [_URIS], (
        "the graphs must be fetched for the page the fast path chose, not for "
        "some other set")


@pytest.mark.parametrize("which", ["sort", "filter"])
async def test_no_fan_out_when_nobody_asked(endpoint, which):
    """The other half, and the reason this is not a blanket decline.

    `_fetch_entity_graphs` is the expensive branch — measured at 4,080ms for 25
    entities on `lead_nurture_grouped` — and the fast path exists to answer a
    question about URIs in milliseconds. Hydrating unasked would hand that back.
    """
    resp = await _run(endpoint, which, _request(include_graph=False))

    assert resp is not None
    assert resp.entity_graphs is None
    assert endpoint.fetched == [], (
        "a fan-out ran for a request that did not ask for entity graphs")


async def test_count_only_has_no_page_to_hydrate(endpoint):
    """`count_only` is served by the filter path alone and returns no URIs.

    There is nothing to hydrate, and asking for graphs must not invent a page
    -- the general path's own guard (`and entity_uris`) decides the same way.
    """
    resp = await _run(endpoint, "filter",
                      _request(include_graph=True, count_only=True))

    assert resp is not None
    assert resp.entity_uris == []
    assert resp.entity_graphs is None
    assert endpoint.fetched == []
