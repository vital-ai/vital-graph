"""An EXISTS body's FILTER that reads the outer row (issue 320).

    ?d ex:reason ?f . ?f ex:code ?c . FILTER NOT EXISTS { ?d ex:reason ?f2 . FILTER(?f2 != ?f) }

The body's FILTER conditions are emitted in the sub-link's own WHERE, beside the
correlation, so PostgreSQL can pull the sub-link up into an anti- or semi-join
(only_cause: 673 -> 153 ms). The answers must not move: these pin them for the
shapes the move touches, a FILTER reading an outer variable the body does not bind,
one reading only the body's, a constant one, and a nested EXISTS inside one.
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

EX = "http://example.org/ebf/"
PFX = f"PREFIX ex: <{EX}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    # d1: one reason. d2: two reasons. d3: two reasons, one of them flagged.
    await sparql_update(PFX + """INSERT DATA {
        ex:d1 a ex:D ; ex:reason ex:r11 . ex:r11 ex:code "x" ; ex:score 5 .
        ex:d2 a ex:D ; ex:reason ex:r21 , ex:r22 . ex:r21 ex:code "x" ; ex:score 1 . ex:r22 ex:code "y" ; ex:score 9 .
        ex:d3 a ex:D ; ex:reason ex:r31 , ex:r32 . ex:r31 ex:code "y" ; ex:score 4 . ex:r32 ex:code "z" ; ex:score 7 .
        ex:r32 ex:flag ex:ON .
    }""", s)
    return s


def _names(rows, var):
    return sorted(b[var]["value"].rsplit("/", 1)[-1] for b in rows)


async def test_only_reason_not_exists_reads_the_outer_frame(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?d WHERE { ?d a ex:D ; ex:reason ?f .
        FILTER NOT EXISTS { ?d ex:reason ?f2 FILTER(?f2 != ?f) } }""", space)
    assert _names(rows, "d") == ["d1"]                     # the only decision with one reason


async def test_exists_reads_an_outer_value(space, sparql_execute):
    # reasons with a higher-scoring sibling under the same decision
    rows = await sparql_execute(PFX + """SELECT ?f WHERE { ?d ex:reason ?f . ?f ex:score ?s .
        FILTER EXISTS { ?d ex:reason ?g . ?g ex:score ?t FILTER(?t > ?s) } }""", space)
    assert _names(rows, "f") == ["r21", "r31"]


async def test_body_only_filter(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?d WHERE { ?d a ex:D .
        FILTER EXISTS { ?d ex:reason ?g . ?g ex:code ?c FILTER(?c = "z") } }""", space)
    assert _names(rows, "d") == ["d3"]


async def test_constant_filter(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT ?d WHERE { ?d a ex:D .
        FILTER NOT EXISTS { ?d ex:reason ?g FILTER(false) } }""", space)
    assert _names(rows, "d") == ["d1", "d2", "d3"]         # an empty body excludes nothing


async def test_nested_exists_in_the_lifted_filter(space, sparql_execute):
    # decisions with a reason other than ?f that is flagged
    rows = await sparql_execute(PFX + """SELECT DISTINCT ?d WHERE { ?d ex:reason ?f .
        FILTER EXISTS { ?d ex:reason ?g FILTER(?g != ?f && EXISTS { ?g ex:flag ex:ON }) } }""", space)
    assert _names(rows, "d") == ["d3"]
