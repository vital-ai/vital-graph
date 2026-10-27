"""A NOT EXISTS inside a NOT EXISTS body reads the body's own row (issue 319).

    ?e a ex:T . FILTER NOT EXISTS { ?e ex:name ?n FILTER NOT EXISTS { ?e ex:status ex:ACTIVE } }

The inner negation's correlation was written `WHERE ex_v0__uuid =
ex__ex0.ex_v0__uuid`: the unqualified name resolves to the innermost scope, the
inner sub-query itself, so the condition compared a column with itself and the
inner NOT EXISTS became "no entity at all is ACTIVE". With one ACTIVE entity
anywhere, every outer row passed. Found by reading the plan of the planner's n06
shape (an InitPlan, run once, where a correlated sub-link was expected).
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

EX = "http://example.org/nne/"
PFX = f"PREFIX ex: <{EX}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:a a ex:T . ex:a ex:name "a" .
        ex:b a ex:T . ex:b ex:name "b" . ex:b ex:status ex:ACTIVE .
        ex:c a ex:T .
    }""", s)
    return s


async def test_inner_not_exists_reads_the_body_row(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?e WHERE { ?e a ex:T .
        FILTER NOT EXISTS { ?e ex:name ?n FILTER NOT EXISTS { ?e ex:status ex:ACTIVE } } }""", space)
    # a: named and not ACTIVE, so the body matches and a is excluded
    # b: named but ACTIVE, so the body is empty and b is kept
    # c: no name, so the body is empty and c is kept
    assert sorted(b["e"]["value"].rsplit("/", 1)[-1] for b in rows) == ["b", "c"]


async def test_inner_exists_reads_the_body_row(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?e WHERE { ?e a ex:T .
        FILTER EXISTS { ?e ex:name ?n FILTER EXISTS { ?e ex:status ex:ACTIVE } } }""", space)
    assert sorted(b["e"]["value"].rsplit("/", 1)[-1] for b in rows) == ["b"]
