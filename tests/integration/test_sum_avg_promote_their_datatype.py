"""SUM and AVG carry their inputs' promoted datatype (issue 325).

The result's datatype was a constant: xsd:integer for SUM, xsd:decimal for AVG. A
group holding a double summed to "119"^^xsd:integer where SPARQL (XSD numeric
promotion) gives an xsd:double. Now per group: integer < decimal < float < double,
AVG at least decimal; the value keeps its numeric lane (ordering, FILTER on it).
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

EX = "http://example.org/sap/"
XSD = "http://www.w3.org/2001/XMLSchema#"
PFX = f"PREFIX ex: <{EX}>\nPREFIX xsd: <{XSD}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:i1 ex:kind ex:ints ; ex:v 1 .
        ex:i2 ex:kind ex:ints ; ex:v 2 .
        ex:d1 ex:kind ex:decs ; ex:v 1 .
        ex:d2 ex:kind ex:decs ; ex:v 2.5 .
        ex:f1 ex:kind ex:dbls ; ex:v 10 .
        ex:f2 ex:kind ex:dbls ; ex:v "1.0E1"^^xsd:double .
    }""", s)
    return s


async def _by_kind(sparql_execute, space, agg):
    rows = await sparql_execute(PFX + f"""SELECT ?k ({agg}(?v) AS ?a) WHERE {{ ?s ex:kind ?k ; ex:v ?v }}
        GROUP BY ?k""", space)
    return {b["k"]["value"].rsplit("/", 1)[-1]: (float(b["a"]["value"]), b["a"].get("datatype")) for b in rows}


async def test_sum_promotes(space, sparql_execute):
    got = await _by_kind(sparql_execute, space, "SUM")
    assert got["ints"] == (3.0, XSD + "integer")
    assert got["decs"] == (3.5, XSD + "decimal")
    assert got["dbls"] == (20.0, XSD + "double")


async def test_avg_promotes(space, sparql_execute):
    got = await _by_kind(sparql_execute, space, "AVG")
    assert got["ints"] == (1.5, XSD + "decimal")             # AVG: at least decimal
    assert got["decs"] == (1.75, XSD + "decimal")
    assert got["dbls"] == (10.0, XSD + "double")


async def test_ordered_and_filtered_by_the_sum(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?k (SUM(?v) AS ?a) WHERE { ?s ex:kind ?k ; ex:v ?v }
        GROUP BY ?k HAVING (SUM(?v) > 3) ORDER BY DESC(?a)""", space)
    assert [b["k"]["value"].rsplit("/", 1)[-1] for b in rows] == ["dbls", "decs"]
