"""A projection must reach ALL THREE entity paths, not just the fast ones.

`issues/208` builds the projection as a shared step after the page is chosen,
and `issues/209` is why: a response field populated on one path and silently
absent on the others is a defect that ships looking like a working feature. The
entity query has three paths — the slot-sort SORT path, the slot-sort FILTER
path, and the general SPARQL pipeline — and a caller cannot tell which one
served it.

So this pins the contract at each of them: ask for columns, get columns.
"""

from __future__ import annotations

import pytest

from vitalgraph.endpoint import kgquery_endpoint as mod
from vitalgraph.endpoint.kgquery_endpoint import KGQueriesEndpoint
from vitalgraph.model.kgentities_model import EntityQueryCriteria
from vitalgraph.model.kgqueries_model import (
    KGQueryCriteria, KGQueryRequest, SlotProjection)

_KG = "http://vital.ai/ontology/haley-ai-kg#"
_URIS = ["urn:e:a", "urn:e:b"]
_VALUES = {"urn:e:a": {"name": ["Acme"]}, "urn:e:b": {"name": []}}
_COLUMN = SlotProjection(alias="name", frame_path=["urn:t:frame:F"],
                         slot_type="urn:t:slot:Name",
                         slot_class_uri=_KG + "KGTextSlot")


class _Pool:
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


def _request(projection):
    return KGQueryRequest(
        criteria=KGQueryCriteria(
            query_type="entity",
            source_entity_criteria=EntityQueryCriteria(
                entity_type="urn:t:entity:E")),
        page_size=25, offset=0,
        slot_projection=projection)


class _Criteria:
    entity_type = "urn:t:entity:E"


@pytest.fixture
def endpoint(monkeypatch):
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

    # The general path runs its real SPARQL builder and stops at the backend.
    async def _checked(backend, space_id, sparql, **kw):
        if "COUNT" in sparql.upper():
            return {"results": {"bindings": [{"count": {"value": "2"}}]}}
        return {"results": {"bindings": [
            {"entity": {"value": u, "type": "uri"}} for u in _URIS]}}

    monkeypatch.setattr(mod, "_checked_query", _checked)

    ep = KGQueriesEndpoint(space_manager=None, auth_dependency=None)
    ep.projected = []

    async def _project(backend, space_id, graph_id, uris, request, entity_type):
        if not getattr(request, "slot_projection", None) or not uris:
            return None
        ep.projected.append((list(uris), entity_type))
        return dict(_VALUES)

    ep._project_slot_values = _project
    return ep


async def _run(ep, which, request):
    if which == "general":
        return await ep._execute_entity_query(_Backend(), "sp", "urn:g", request)
    fn = (ep._try_fast_slot_sort if which == "sort" else ep._try_fast_slot_filter)
    return await fn(_Backend(), "sp", "urn:g", _Criteria(), request)


@pytest.mark.parametrize("which", ["sort", "filter", "general"])
async def test_every_path_returns_the_projection(endpoint, which):
    resp = await _run(endpoint, which, _request([_COLUMN]))

    assert resp is not None, f"the {which} path declined; nothing is pinned"
    assert resp.entity_uris == _URIS
    assert resp.entity_slot_values == _VALUES, (
        f"the {which} path returned entity_slot_values="
        f"{resp.entity_slot_values!r} for a request that asked for a column")
    assert endpoint.projected == [(_URIS, "urn:t:entity:E")], (
        "the projection must be asked for the page this path chose, and for "
        "the entity type whose coverage gates it")


@pytest.mark.parametrize("which", ["sort", "filter", "general"])
async def test_no_projection_asked_for_means_none_returned(endpoint, which):
    resp = await _run(endpoint, which, _request(None))

    assert resp is not None
    assert resp.entity_slot_values is None
    assert endpoint.projected == []


def test_two_columns_cannot_share_an_alias():
    """The response is keyed by alias, so a duplicate silently drops a column."""
    with pytest.raises(ValueError, match="duplicate projection alias"):
        _request([_COLUMN, _COLUMN])
