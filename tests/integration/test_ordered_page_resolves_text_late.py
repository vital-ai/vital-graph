"""`ORDER BY ... LIMIT k` resolves projected text for the page only (`issues/333`).

`emit_slice._emit_late_text_ordered`: the child sorts on uuids and computed
values, the page is cut, and each projected variable that nothing inside reads
gets its term join for the page's rows only. Before it, the default path joined
the term table for every projected variable on EVERY candidate (20,000 for a
graph-scoped hybrid search over a 20,000-message graph, six joins each) and
sorted the wide rows.

The rewrite must return exactly what the inline form returns, row for row and
in order, so each case runs both and compares.
"""

from __future__ import annotations

import re

import pytest

from vitalgraph.db.sparql_sql import emit_slice

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

G = "urn:inttest:latepage:g"
T, D = "urn:inttest:p:text", "urn:inttest:p:at"
TEXTS = ["delta", "alpha", "echo", "charlie", "bravo", "foxtrot", "golf", "hotel"]

CASES = {
    # (query, whether the rewrite should fire)
    "order by a text variable": (
        f"SELECT ?s ?t WHERE {{ GRAPH <{G}> {{ ?s <{T}> ?t }} }} ORDER BY ?t LIMIT 3", True),
    "order by date, desc": (
        f"SELECT ?s ?t ?at WHERE {{ GRAPH <{G}> {{ ?s <{T}> ?t ; <{D}> ?at }} }} "
        f"ORDER BY DESC(?at) LIMIT 3", True),
    "offset": (
        f"SELECT ?s ?t ?at WHERE {{ GRAPH <{G}> {{ ?s <{T}> ?t ; <{D}> ?at }} }} "
        f"ORDER BY DESC(?at) LIMIT 3 OFFSET 2", True),
    "optional, unbound": (
        f"SELECT ?s ?t ?x WHERE {{ GRAPH <{G}> {{ ?s <{T}> ?t "
        f"OPTIONAL {{ ?s <urn:inttest:p:none> ?x }} }} }} ORDER BY ?t LIMIT 3", True),
    "filter reads text": (
        f"SELECT ?s ?t ?at WHERE {{ GRAPH <{G}> {{ ?s <{T}> ?t ; <{D}> ?at "
        f'FILTER(CONTAINS(?t, "o")) }} }} ORDER BY DESC(?at) ?t LIMIT 3', True),
    "everything read inside": (
        f"SELECT ?s ?t ?n WHERE {{ GRAPH <{G}> {{ ?s <{T}> ?t BIND(STRLEN(?t) AS ?n) }} }} "
        f"ORDER BY DESC(?n) ?s LIMIT 3", False),
}


async def _load(sparql_update, space):
    triples = " ".join(
        f'<urn:inttest:latepage:s{i}> <{T}> "{t}" . '
        f'<urn:inttest:latepage:s{i}> <{D}> "2026-01-0{i + 1}T00:00:00Z"'
        f'^^<http://www.w3.org/2001/XMLSchema#dateTime> .'
        for i, t in enumerate(TEXTS))
    await sparql_update(f"INSERT DATA {{ GRAPH <{G}> {{ {triples} }} }}", space)


@pytest.mark.parametrize("name", list(CASES))
async def test_the_page_is_the_inline_page(
        name, pg_conn, test_space, sparql_update, sparql_query_sql, monkeypatch):
    if name == next(iter(CASES)):          # the module's space: load once
        await _load(sparql_update, test_space)
    query, should_fire = CASES[name]

    new_sql = await sparql_query_sql(query, test_space)
    assert ("row_number() OVER ()" in new_sql) is should_fire, name
    monkeypatch.setattr(emit_slice, "_emit_late_text_ordered", lambda *a, **k: None)
    old_sql = await sparql_query_sql(query, test_space)

    old = [tuple(r) for r in await pg_conn.fetch(old_sql)]
    new = [tuple(r) for r in await pg_conn.fetch(new_sql)]
    assert old, f"{name}: the fixture produced no rows, so the comparison proves nothing"
    assert new == old, f"{name}: the late-text page differs from the inline page"


async def test_a_text_order_key_keeps_its_text_inside(test_space, sparql_query_sql):
    """`ORDER BY ?t` is held as a bare name, which no expression walker reads.
    Missed, `?t`'s text was suppressed inside the page and it sorted on NULLs
    (`issues/324`'s shape). Its text stays inside; only `?s` moves."""
    query, _ = CASES["order by a text variable"]
    sql = await sparql_query_sql(query, test_space)
    m = re.search(r"SELECT \* FROM \(\n(.*)\n\) AS (r\d+)_i\n.*?\) AS \2\n"
                  r"((?:LEFT JOIN [^\n]+\n)+)ORDER BY \2\.\2_rn", sql, re.S)
    assert m, "the ordered late-text page shape"
    inner, page_joins = m.group(1), m.group(3)
    assert page_joins.count("_term AS ") == 1, "only ?s is resolved after the page"
    assert "_term AS " in inner, "?t, the sort key, keeps its text inside the page"
