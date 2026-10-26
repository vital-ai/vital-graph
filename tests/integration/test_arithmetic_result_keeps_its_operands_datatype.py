"""A BIND of arithmetic reports its operands' promoted datatype (issue 318).

`BIND(?v * 2 AS ?w)` over a stored float came back "3.0"^^xsd:integer, an integer
whose lexical form is not one. The result's datatype companion was the static
inference, where an operand known only at run time counts as the floor
(xsd:integer); it must stay static, because it classifies. `DATATYPE(?v * 2)`
already reported xsd:float, per row. Found by the planner's contract check on a
UNION branch computing `?v * 2`.
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

XSD = "http://www.w3.org/2001/XMLSchema#"
PFX = "PREFIX ex: <http://example.org/adt/>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:a ex:f "1.5"^^xsd:float . ex:a ex:d "1.5"^^xsd:double .
        ex:a ex:c "1.5"^^xsd:decimal . ex:a ex:i 3 }""", s)
    return s


async def _w(sparql_execute, space, p, expr):
    rows = await sparql_execute(PFX + f"SELECT ?w WHERE {{ ex:a ex:{p} ?v BIND({expr} AS ?w) }}", space)
    return rows[0]["w"]["value"], rows[0]["w"].get("datatype")


@pytest.mark.parametrize("p,dt", [("f", "float"), ("d", "double"), ("c", "decimal"), ("i", "integer")])
async def test_times_an_integer(space, sparql_execute, p, dt):
    assert (await _w(sparql_execute, space, p, "?v * 2"))[1] == XSD + dt


async def test_nested_arithmetic(space, sparql_execute):
    assert (await _w(sparql_execute, space, "f", "?v * 2 + 1"))[1] == XSD + "float"


async def test_an_integer_divided_is_a_decimal(space, sparql_execute):
    assert (await _w(sparql_execute, space, "i", "?v / 2"))[1] == XSD + "decimal"


async def test_constants_keep_the_static_answer(space, sparql_execute):
    assert (await _w(sparql_execute, space, "i", "1.5 * 2"))[1] == XSD + "decimal"
