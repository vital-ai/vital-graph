"""A FILTER inside an EXISTS / NOT EXISTS body compares typed values (issue 311).

The body's emit context was built without the space's datatype cache, so every
term row's typed columns there (`__num`, `__bool`, `__dt`, `__datatype`) were
`datatype_id IN (NULL)`: NULL. A numeric, boolean or date comparison in the body
never held: EXISTS was always false and NOT EXISTS always true. Found by the
planner's contract check on lead 10k: `?s :type :MQLRating FILTER NOT EXISTS
{ ?s :value ?v FILTER(?v >= 50.0) }` counted 10,000 slots, 5,024 correct.
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

EX = "http://example.org/exf/"
XSD = "http://www.w3.org/2001/XMLSchema#"
PFX = f"PREFIX ex: <{EX}>\nPREFIX xsd: <{XSD}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:low   ex:t ex:Slot ; ex:v "10.5"^^xsd:float ; ex:on false ; ex:at "2026-01-01T00:00:00"^^xsd:dateTime .
        ex:high  ex:t ex:Slot ; ex:v "90.5"^^xsd:float ; ex:on true  ; ex:at "2026-06-01T00:00:00"^^xsd:dateTime .
        ex:int   ex:t ex:Slot ; ex:v 70 .
        ex:none  ex:t ex:Slot .
    }""", s)
    return s


def _vals(bindings, var="s"):
    return sorted(b[var]["value"].rsplit("/", 1)[-1] for b in bindings if var in b)


async def test_not_exists_with_a_numeric_body_filter(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE {
        ?s ex:t ex:Slot FILTER NOT EXISTS { ?s ex:v ?v FILTER(?v >= 50.0) } }""", space)
    assert _vals(rows) == ["low", "none"]


async def test_exists_with_a_numeric_body_filter(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE {
        ?s ex:t ex:Slot FILTER EXISTS { ?s ex:v ?v FILTER(?v >= 50.0) } }""", space)
    assert _vals(rows) == ["high", "int"]


async def test_exists_with_a_boolean_body_filter(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE {
        ?s ex:t ex:Slot FILTER EXISTS { ?s ex:on ?b FILTER(?b) } }""", space)
    assert _vals(rows) == ["high"]


async def test_exists_with_a_date_body_filter(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?s WHERE {
        ?s ex:t ex:Slot FILTER EXISTS { ?s ex:at ?d FILTER(?d > "2026-03-01T00:00:00"^^xsd:dateTime) } }""",
                                space)
    assert _vals(rows) == ["high"]


async def test_the_same_filter_outside_exists_agrees(space, sparql_execute):
    """The control: the comparison itself was always right outside a body."""
    rows = await sparql_execute(PFX + """SELECT ?s WHERE {
        ?s ex:t ex:Slot ; ex:v ?v FILTER(?v >= 50.0) }""", space)
    assert _vals(rows) == ["high", "int"]
