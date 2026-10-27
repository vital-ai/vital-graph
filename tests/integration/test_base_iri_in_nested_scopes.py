"""A query's BASE resolves relative IRIs in nested scopes too (issue 321).

`IRI("x")` under `BASE <http://example.org/>` is `<http://example.org/x>`. The
emit context passed its base IRI to an EXISTS body but not to a child context,
so in a UNION branch or a sub-SELECT the IRI came back as `<x>`, unresolved.
Found by the planner, whose value levels are child contexts (W3C iri01).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

PFX = "BASE <http://example.org/b/>\nPREFIX ex: <http://example.org/b/>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + "INSERT DATA { ex:a ex:p 1 . }", s)
    return s


async def test_iri_in_a_union_branch(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?i WHERE {
        { ?s ex:p ?o BIND(IRI("x") AS ?i) } UNION { ?s ex:p ?o BIND(IRI("y") AS ?i) } }""", space)
    assert sorted(b["i"]["value"] for b in rows) == ["http://example.org/b/x", "http://example.org/b/y"]


async def test_iri_in_a_sub_select(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?i WHERE {
        { SELECT ?s (IRI("z") AS ?i) WHERE { ?s ex:p ?o } } }""", space)
    assert [b["i"]["value"] for b in rows] == ["http://example.org/b/z"]


async def test_iri_at_the_top(space, sparql_execute):
    rows = await sparql_execute(PFX + 'SELECT (IRI("t") AS ?i) WHERE { ?s ex:p ?o }', space)
    assert [b["i"]["value"] for b in rows] == ["http://example.org/b/t"]
