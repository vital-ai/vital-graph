"""Late text resolution must not strip text an expression still reads.

Two regressions from the same commit (`af10e5f`), which moved text resolution
after the LIMIT. Both returned no rows from a query that has rows, and neither
named the cause.

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


async def test_a_filter_over_text_still_generates(space_impl, make_space, graph_uri):
    """The frames list: `total_count: 3` above an empty table.

    `_emit_late_text` set `text_needed_vars` to the EMPTY SET, suppressing text
    for every variable in the child — including ones a FILTER inside that child
    reads. The scope guard caught the resulting NULL comparison and REFUSED to
    generate (issues/023, issues/027), which is the right call:

        Variable(s) lost their value while in scope: ?name
        (text-not-materialised, depth 1) ... silently weakening the enclosing
        constraint

    The endpoint's count query is a different, simpler shape, so it kept working.
    The list therefore reported a result count above no results — the search box
    said "3" and showed nothing.

    Bisected: this query returns 3 rows at `af10e5f~1` and fails to generate at
    `af10e5f`.
    """
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    rows = await _rows(space_impl, space_id, f"""
        SELECT DISTINCT ?frame WHERE {{ GRAPH <{graph_uri}> {{
            ?frame <{CORE}vitaltype> <{KG}KGFrame> .
            OPTIONAL {{ ?frame <{KG}hasName> ?name }}
            FILTER(CONTAINS(LCASE(STR(?name)), "fixture"))
        }} }} LIMIT 25""")
    assert len(rows) == 1, (
        "a paged query whose FILTER reads text returned nothing — late text "
        "resolution stripped the variable the filter needs")
    assert rows[0]["frame"]["value"] == FRAME


async def test_the_page_does_not_materialise_the_projected_text(space_impl, make_space,
                                                                graph_uri):
    """The SAVING, not just the answer — this had no guard and was lost twice.

    Late text resolution exists to keep the projected variable's term join OUT of
    the page. Nothing asserted that, so a correctness fix silently reverted the
    optimisation to its pre-`af10e5f` cost (1,744 buffers back to 16,000+) while
    every test stayed green — an empty-or-slow result satisfies every
    upper-bound assertion, which is the trap issues/041 documents.

    Asserted on the SHAPE rather than a timing: exactly one term join, the one
    outside the LIMIT. A buffer count would be a machine-dependent number in a
    correctness suite.
    """
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    res = await space_impl.execute_sparql_query(space_id, f"""
        SELECT DISTINCT ?frame WHERE {{ GRAPH <{graph_uri}> {{
            ?frame <{CORE}vitaltype> <{KG}KGFrame> .
            FILTER NOT EXISTS {{ ?frame <{KG}hasKGFormType> ?ft }}
        }} }} LIMIT 25""")
    sql = res.get("sql") or ""
    assert sql, "the impl no longer reports the SQL it ran"
    joins = sql.count(f"{space_id}_term")
    assert joins == 1, (
        f"expected ONE term join (outside the LIMIT), found {joins} — the "
        f"projected variable's text is being resolved inside the page again")


async def test_a_filter_over_text_still_forces_materialisation(space_impl, make_space,
                                                               graph_uri):
    """The other side of the same coin, so the two cannot both be satisfied by
    simply never resolving text: a FILTER that reads text must still get it."""
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    res = await space_impl.execute_sparql_query(space_id, f"""
        SELECT DISTINCT ?frame WHERE {{ GRAPH <{graph_uri}> {{
            ?frame <{CORE}vitaltype> <{KG}KGFrame> .
            OPTIONAL {{ ?frame <{KG}hasName> ?name }}
            FILTER(CONTAINS(LCASE(STR(?name)), "fixture"))
        }} }} LIMIT 25""")
    bindings = res.get("results", {}).get("bindings", [])
    assert len(bindings) == 1, "the filter's variable lost its text again"
