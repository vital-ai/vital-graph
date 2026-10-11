"""Integration: /kgentities/count takes the listing's count path — issue 228.

The count endpoint built the listing's SPARQL `COUNT(DISTINCT)` and executed it
directly, so it never reached `entity_prop_sort`, which the listing's own count
reads for exactly these shapes. Production: 85,153 matches in 1.0 s through the
endpoint against 25-82 ms on the table; a cold wide count crossed the 60 s
statement timeout and came back as an HTTP 500.

Pinned here: the endpoint's answer comes FROM the table (the SPARQL fallback is
made to fail, so only a served fast path can answer); it agrees with the SPARQL
count; a count that cannot be computed is a 200 `query_failed`, not a 500; and a
batch count reports a failed label instead of a zero.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
AIMP = "http://vital.ai/ontology/vital-aimp#"
EX = "http://example.org/cnt228/"
GRAPH = "http://example.org/cnt228/graph"
ETYPE = f"{EX}CountedType"
ROWS = [("a", "Active"), ("b", "Active"), ("c", "Closed"), ("d", "Active")]


def _quads():
    from rdflib import Literal, URIRef
    g = URIRef(GRAPH)
    out = []
    for n, st in ROWS:
        e = URIRef(f"{EX}{n}")
        out += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{KG}KGEntity"), g),
            (e, URIRef(f"{KG}hasKGEntityType"), URIRef(ETYPE), g),
            (e, URIRef(f"{CORE}hasName"), Literal(n), g),
            (e, URIRef(f"{AIMP}hasObjectStatusType"), URIRef(f"{EX}{st}"), g),
        ]
    return out


@pytest_asyncio.fixture(loop_scope="session")
async def endpoint(test_space, space_impl, space_manager):
    from vitalgraph.cache.count_cache import _count_cache
    from vitalgraph.endpoint.kgentities_endpoint import KGEntitiesEndpoint
    await space_impl.add_rdf_quads_batch(test_space, _quads())
    _count_cache.invalidate_graph(test_space, GRAPH)
    return KGEntitiesEndpoint(space_manager, auth_dependency=lambda: {})


def _sparql_fails(monkeypatch):
    """Make every SPARQL read fail, so only the table can answer."""
    from vitalgraph.kg_impl import kg_backend_utils as K
    calls = []

    async def failing(self, space_id, query, *a, **k):
        calls.append(query)
        return {"success": False, "error": "SPARQL path must not be used",
                "results": {"bindings": []}}
    for name in dir(K):
        cls = getattr(K, name)
        if isinstance(cls, type) and "execute_sparql_query" in vars(cls):
            monkeypatch.setattr(cls, "execute_sparql_query", failing)
    return calls


@pytest.mark.parametrize("kw,expected", [
    ({}, 4),
    ({"status": f"{EX}Active"}, 3),
    ({"exclude_status": f"{EX}Active"}, 1),
])
async def test_the_count_endpoint_is_served_from_the_table(
        endpoint, test_space, monkeypatch, kw, expected):
    sparql_calls = _sparql_fails(monkeypatch)
    r = await endpoint._count_entities(test_space, GRAPH, ETYPE, None, None, **kw)
    assert r.count == expected, (r.status, r.message)
    assert sparql_calls == [], (
        "the count went to SPARQL for a shape entity_prop_sort serves (issues/228)")


async def test_the_table_count_agrees_with_the_sparql_count(endpoint, test_space):
    from vitalgraph.cache.count_cache import _count_cache
    from vitalgraph.kg_impl.kgentity_list_impl import KGEntityListProcessor, _extract_bindings
    from vitalgraph.kg_impl.kg_backend_utils import create_backend_adapter
    fast = await endpoint._count_entities(test_space, GRAPH, ETYPE, None, None,
                                          status=f"{EX}Active")
    lp = KGEntityListProcessor()
    q = lp._build_count_query(GRAPH, ETYPE, None, prop_filters=lp._build_property_filter_clauses(
        status=f"{EX}Active"))
    rec = await endpoint.space_manager.get_space_or_load(test_space)
    res = await create_backend_adapter(rec.space_impl.get_db_space_impl()) \
        .execute_sparql_query(test_space, q)
    slow = int(_extract_bindings(res)[0]["count"]["value"])
    assert fast.count == slow == 3


async def test_a_failed_count_is_a_200_query_failed_not_a_500(
        endpoint, test_space, monkeypatch):
    """`search` declines the fast path, so this shape needs the SPARQL path —
    which fails here, as a cancelled statement would."""
    _sparql_fails(monkeypatch)
    try:
        r = await endpoint._count_entities(test_space, GRAPH, ETYPE, "anything", None)
    except HTTPException as e:
        pytest.fail(f"a failed count raised HTTP {e.status_code}; it is a domain "
                    f"outcome and should be 200 query_failed (issues/228)")
    assert r.status.value == "query_failed" and r.success is False


async def test_a_failed_batch_label_is_reported_not_zero(
        endpoint, test_space, monkeypatch):
    from types import SimpleNamespace
    _sparql_fails(monkeypatch)
    cr = lambda label, search=None, **kw: SimpleNamespace(
        label=label, entity_type_uri=ETYPE, search=search, sort_by=None,
        status=kw.get("status"), exclude_status=None, created_after=None,
        created_before=None, modified_after=None, modified_before=None)
    body = SimpleNamespace(space_id=test_space, graph_id=GRAPH, count_requests=[
        cr("served", status=f"{EX}Active"), cr("needs_sparql", search="x")])
    r = await endpoint._batch_count_entities(body)
    by = {c.label: c for c in r.counts}
    assert by["served"].count == 3 and by["served"].error is None
    assert by["needs_sparql"].error, "a failed count must say so, not report 0"
    assert r.status.value == "partial"
