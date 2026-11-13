"""Numbers from VALUES compute, and an integer cast of a number truncates.

- `issues/340`: a number bound by VALUES projected as itself but took no part
  in arithmetic or comparison: `FILTER(?a > 1)` dropped every row and
  `BIND(?a + 1 AS ?y)` was unbound. Wrong answers, not errors.
- `issues/341`: `xsd:integer(5.0)` was unbound instead of 5.

Read-only queries; each row is the issue's reproduction with the answer SPARQL
gives.
"""

from __future__ import annotations

import pytest

from vitalgraph.model.sparql_model import SPARQLQueryRequest

pytestmark = [
    pytest.mark.api,
    pytest.mark.asyncio(loop_scope="session"),
]

X = "http://www.w3.org/2001/XMLSchema#"


async def _column(vg_client, space, query, var):
    r = await vg_client.sparql.execute_sparql_query(space, SPARQLQueryRequest(query=query))
    assert not getattr(r, "error", None), r.error
    rows = (r.results or {}).get("bindings", [])
    return [float(b[var]["value"]) if var in b else None for b in rows]


@pytest.mark.parametrize("query, var, expected", [
    ("SELECT ?y WHERE { VALUES ?a { 1 2 } BIND(?a + 1 AS ?y) } ORDER BY ?y", "y", [2, 3]),
    ("SELECT ?y WHERE { VALUES ?a { 1 2 } BIND(?a * 3 AS ?y) } ORDER BY ?y", "y", [3, 6]),
    ("SELECT ?a WHERE { VALUES ?a { 1 2 } FILTER(?a > 1) }", "a", [2]),
    ("SELECT ?a WHERE { VALUES ?a { 1 2 } FILTER(?a * 3 > 4) }", "a", [2]),
    ("SELECT ?a WHERE { VALUES ?a { 1.5 2.5 } FILTER(?a < 2) }", "a", [1.5]),
    ("SELECT ?a WHERE { VALUES ?a { 1e0 3e0 } FILTER(?a >= 2) }", "a", [3]),
    # a value off the numeric lane in its datatype stays off it, as when stored
    (f'SELECT ?a WHERE {{ VALUES ?a {{ "xyz"^^<{X}integer> 5 }} FILTER(?a > 1) }}', "a", [5]),
    # numbers ordered as numbers, not text ("10" < "9")
    ("SELECT ?a WHERE { VALUES ?a { 9 10 } } ORDER BY DESC(?a + 0)", "a", [10, 9]),
])
async def test_a_values_number_computes(vg_client, test_space, query, var, expected):
    assert await _column(vg_client, test_space, query, var) == expected


async def test_a_values_boolean_and_datetime_compute(vg_client, test_space):
    q = f'SELECT ?a WHERE {{ VALUES ?a {{ true false }} FILTER(?a) }}'
    r = await vg_client.sparql.execute_sparql_query(test_space, SPARQLQueryRequest(query=q))
    assert [b["a"]["value"] for b in r.results["bindings"]] == ["true"]
    q = (f'SELECT ?y WHERE {{ VALUES ?d {{ "2024-03-05T00:00:00"^^<{X}dateTime> }} '
         f'BIND(YEAR(?d) AS ?y) }}')
    assert await _column(vg_client, test_space, q, "y") == [2024]


@pytest.mark.parametrize("query, expected", [
    (f"SELECT ?y WHERE {{ BIND(<{X}integer>(5.0) AS ?y) }}", [5]),
    (f'SELECT ?y WHERE {{ BIND(<{X}integer>("5.0"^^<{X}decimal>) AS ?y) }}', [5]),
    (f"SELECT ?y WHERE {{ BIND(<{X}integer>(-2.7) AS ?y) }}", [-2]),
    (f'SELECT ?y WHERE {{ BIND(<{X}integer>("1e3"^^<{X}double>) AS ?y) }}', [1000]),
    (f"SELECT ?y WHERE {{ BIND(2.5*2 AS ?x) BIND(<{X}integer>(?x) AS ?y) }}", [5]),
    (f"SELECT ?y WHERE {{ VALUES ?x {{ 2.7 }} BIND(<{X}integer>(?x) AS ?y) }}", [2]),
    # a string must already be an integer: "5.0" is an error, i.e. unbound
    (f'SELECT ?y WHERE {{ BIND(<{X}integer>("5.0") AS ?y) }}', [None]),
    (f'SELECT ?y WHERE {{ BIND(<{X}integer>("7") AS ?y) }}', [7]),
])
async def test_an_integer_cast_of_a_number_truncates(vg_client, test_space, query, expected):
    assert await _column(vg_client, test_space, query, "y") == expected
