"""A variable bound by BIND must still come back from a paged query.

`af10e5f` moved text resolution after the LIMIT: the page is chosen by uuid and
the term text is joined for those rows only. That is right for a variable whose
value IS a term in the quad table, and wrong for one bound by an expression —
`BIND(<uri> AS ?s)` has no term row to come back to.

The guard checked that the child exposed a `<var>__uuid` COLUMN. It does: the
emitter writes `NULL::uuid AS v0__uuid` for an expression-bound variable, so the
name test passed and the text join then matched nothing. The query returned zero
rows instead of its answer — correct-looking SQL, silently empty.

WHAT IT COST. `_frame_exists_in_backend` asks exactly this shape:

    SELECT ?s WHERE { GRAPH <g> { <f> vitaltype <KGFrame> . BIND(<f> AS ?s) } }

It went from 1 row to 0, so every frame looked absent, DELETE answered "Frame not
found", and fourteen API tests failed. None of them named the cause, and the
kgframes suite is not where anyone would look for a paging optimisation.

It also hid for a day. The change shipped 2026-08-17 and the test-stack container
was 43 hours old, so no API request ran the new code until the image was rebuilt
— a reminder that a green `tests/api` proves nothing about code the running
image does not contain.
"""

from __future__ import annotations

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

KG = "http://vital.ai/ontology/haley-ai-kg#"
CORE = "http://vital.ai/ontology/vital-core#"
FRAME = "http://example.org/bindproj/frame1"


@pytest.fixture(scope="module")
def graph_uri():
    return "urn:bindproj:graph"


async def _seed(impl, space_id, graph_uri):
    await impl.add_rdf_quads_batch_bulk(space_id, [
        (FRAME, f"{CORE}vitaltype", f"{KG}KGFrame", graph_uri),
        (FRAME, f"{KG}hasName", "bind projection fixture", graph_uri),
    ])


async def _rows(impl, space_id, sparql):
    res = await impl.execute_sparql_query(space_id, sparql)
    if isinstance(res, dict):
        return res.get("results", {}).get("bindings", []) or res.get("bindings", []) or []
    return res or []


async def test_a_bind_bound_variable_is_returned(space_impl, make_space, graph_uri):
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    rows = await _rows(space_impl, space_id, f"""
        SELECT ?s WHERE {{ GRAPH <{graph_uri}> {{
            <{FRAME}> <{CORE}vitaltype> <{KG}KGFrame> .
            BIND(<{FRAME}> AS ?s)
        }} }} LIMIT 1""")
    assert len(rows) == 1, "a BIND-projected existence check returned nothing"
    assert rows[0]["s"]["value"] == FRAME


async def test_the_same_query_without_bind_is_unchanged(space_impl, make_space, graph_uri):
    """The control. Without it, a fix that broke the ordinary path would pass."""
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    rows = await _rows(space_impl, space_id, f"""
        SELECT ?s WHERE {{ GRAPH <{graph_uri}> {{
            ?s <{CORE}vitaltype> <{KG}KGFrame>
        }} }} LIMIT 1""")
    assert len(rows) == 1
    assert rows[0]["s"]["value"] == FRAME


async def test_text_still_comes_back_for_a_quad_bound_variable(space_impl, make_space,
                                                               graph_uri):
    """The optimisation must still resolve text for the page it selected —
    declining it for BIND must not decline it for everything."""
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    rows = await _rows(space_impl, space_id, f"""
        SELECT ?name WHERE {{ GRAPH <{graph_uri}> {{
            <{FRAME}> <{KG}hasName> ?name
        }} }} LIMIT 1""")
    assert len(rows) == 1
    assert rows[0]["name"]["value"] == "bind projection fixture"
