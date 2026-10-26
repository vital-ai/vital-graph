"""SELECT DISTINCT keeps a BIND's IRI and the same IRI from a pattern once (issue 317).

`BIND(<iri> AS ?s)` carried the IRI with a NULL `__uuid`; the same IRI read from a
pattern carries its term's uuid. SELECT DISTINCT compares every column, so the two
rows stayed apart: one term, returned twice. The frame fetch with its frame graph
asks exactly this (`{ BIND(<f> AS ?subject) ... } UNION { ?subject
hasFrameGraphURI <f> }`, a frame that is in its own frame graph). Found by the
planner's contract check, whose pin gives the IRI its uuid.
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

EX = "http://example.org/dbi/"
PFX = f"PREFIX ex: <{EX}>\n"


@pytest_asyncio.fixture(loop_scope="session")
async def space(make_space, sparql_update):
    s = await make_space()
    await sparql_update(PFX + """INSERT DATA {
        ex:f ex:type ex:Frame . ex:f ex:inGraph ex:f .
        ex:s1 ex:inGraph ex:f . ex:s2 ex:inGraph ex:f .
    }""", s)
    return s


async def test_the_frame_is_returned_once(space, sparql_execute):
    rows = await sparql_execute(PFX + """SELECT DISTINCT ?s WHERE {
        { BIND(ex:f AS ?s) ?s ex:type ex:Frame } UNION { ?s ex:inGraph ex:f } } ORDER BY ?s""", space)
    assert [b["s"]["value"].rsplit("/", 1)[-1] for b in rows] == ["f", "s1", "s2"]


async def test_a_bound_iri_not_stored_is_still_returned(space, sparql_execute):
    rows = await sparql_execute(PFX + "SELECT ?s WHERE { BIND(ex:nowhere AS ?s) }", space)
    assert [b["s"]["value"] for b in rows] == [f"{EX}nowhere"]
