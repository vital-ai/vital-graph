"""A VALUES row joins a stored term only when it is the same TERM (issue 316).

A VALUES block holding UNDEF has no term identity, so the join fell back to
comparing text: `CAST(a AS TEXT) = CAST(b AS TEXT)`. "3.0"^^xsd:decimal then
matched a stored "3.0"^^xsd:float, and the literal "x" a stored IRI <x>. SPARQL
joins compatible mappings, and compatible means the same RDF term. Found by the
planner's contract check, whose VALUES join compares term uuids.
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

EX = "http://example.org/vut/"
PFX = f"PREFIX ex: <{EX}>\nPREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:a ex:v "3.0"^^xsd:float .
        ex:b ex:v "3.0"^^xsd:decimal .
        ex:c ex:v <urn:x> .
        ex:d ex:v "urn:x" .
        ex:e ex:v "hi"@en .
        ex:f ex:v "hi" .
    }""", s)
    return s


async def _subjects(sparql_execute, space, values):
    rows = await sparql_execute(PFX + f"""SELECT ?s WHERE {{ ?s ex:v ?v }}
        VALUES (?v ?k) {{ {values} }}""", space)
    return sorted(b["s"]["value"].rsplit("/", 1)[-1] for b in rows)


async def test_a_decimal_does_not_match_a_float(space, sparql_execute):
    assert await _subjects(sparql_execute, space, '(3.0 UNDEF)') == ["b"]


async def test_a_literal_does_not_match_an_iri(space, sparql_execute):
    assert await _subjects(sparql_execute, space, '("urn:x" UNDEF)') == ["d"]
    assert await _subjects(sparql_execute, space, '(<urn:x> UNDEF)') == ["c"]


async def test_a_plain_literal_does_not_match_a_tagged_one(space, sparql_execute):
    assert await _subjects(sparql_execute, space, '("hi" UNDEF)') == ["f"]
    assert await _subjects(sparql_execute, space, '("hi"@EN UNDEF)') == ["e"]


async def test_undef_still_matches_everything(space, sparql_execute):
    assert await _subjects(sparql_execute, space, '(UNDEF 1)') == ["a", "b", "c", "d", "e", "f"]


async def test_a_column_holding_undef_compares_the_term(space, sparql_execute):
    # ?v has UNDEF in a row, so no term identity: the join compares text, and
    # needs the term's kind, language and datatype beside it
    rows = await sparql_execute(PFX + """SELECT ?s WHERE { ?s ex:v ?v }
        VALUES (?v ?s) { (3.0 UNDEF) ("urn:x" UNDEF) ("hi"@en UNDEF) (UNDEF ex:zz) }""", space)
    assert sorted(b["s"]["value"].rsplit("/", 1)[-1] for b in rows) == ["b", "d", "e"]
