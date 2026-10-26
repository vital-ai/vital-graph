"""COUNT over an expression reads its variables' text (issue 315).

A query whose aggregates are all COUNT took a shortcut: COUNT needs only term
uuids, so every term-table join was deferred (`emit_group._all_count_no_keys`,
`_pushdown_candidates`). That holds for COUNT(*) and COUNT(?v). It does not hold
for COUNT(LCASE(?n)), which needs ?n's text: the generator's guard refused the
statement (`UnresolvedVariableError: ?n (text-not-materialised)`) rather than
count NULLs, so the query failed. Found by the planner's contract check.
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

EX = "http://example.org/cnx/"
PFX = f"PREFIX ex: <{EX}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:a ex:name "alice" . ex:b ex:name "ALICE" . ex:c ex:name "bob" . ex:d ex:name "Anna" .
    }""", s)
    return s


async def test_count_distinct_of_an_expression(space, sparql_execute):
    rows = await sparql_execute(PFX + "SELECT (COUNT(DISTINCT LCASE(?n)) AS ?c) WHERE { ?s ex:name ?n }", space)
    assert int(rows[0]["c"]["value"]) == 3          # alice, bob, anna


async def test_count_of_an_expression_grouped(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s (COUNT(UCASE(?n)) AS ?c) WHERE { ?s ex:name ?n }
        GROUP BY ?s""", space)
    assert sorted(int(b["c"]["value"]) for b in rows) == [1, 1, 1, 1]


async def test_count_of_a_variable_still_takes_the_shortcut(space, sparql_execute):
    rows = await sparql_execute(PFX + "SELECT (COUNT(DISTINCT ?n) AS ?c) WHERE { ?s ex:name ?n }", space)
    assert int(rows[0]["c"]["value"]) == 4
