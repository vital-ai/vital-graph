"""An all-constant pattern must survive having a LIMIT put on it.

A BGP with no variables — `{ <s> <p> <o> }` — is an existence check, and
`emit_bgp` short-circuits it with `LIMIT 1`: one matching row settles it, so
scanning further is waste. That is right, and it TERMINATED the emitted string.

Every other emitter here returns composable SQL, meaning a parent can wrap it or
append to it. This one quietly did not, so a query carrying its own LIMIT emitted

    ... WHERE ... LIMIT 1 LIMIT 1

which PostgreSQL rejects with `syntax error at or near "LIMIT"`. Reproduced by

    SELECT * WHERE { GRAPH <g> { <s> <p> <o> } } LIMIT 1

Malformed SQL rather than a wrong answer, so it surfaces as a 500 — but only for
a shape nothing in the suite asked for, which is why it survived: the same query
without a LIMIT is fine, and `ASK` takes a different path.

The fix keeps the short-circuit and puts it inside a subquery.
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
SUBJ = "http://example.org/constbgp/frame1"
MISSING = "http://example.org/constbgp/absent"


@pytest.fixture(scope="module")
def graph_uri():
    return "urn:constbgp:graph"


async def _seed(impl, space_id, graph_uri):
    await impl.add_rdf_quads_batch_bulk(space_id, [
        (SUBJ, f"{CORE}vitaltype", f"{KG}KGFrame", graph_uri),
    ])


async def _rows(impl, space_id, sparql):
    res = await impl.execute_sparql_query(space_id, sparql)
    if isinstance(res, dict):
        return res.get("results", {}).get("bindings", []) or res.get("bindings", []) or []
    return res or []


@pytest.mark.parametrize("limit", ["LIMIT 1", "LIMIT 10", ""],
                         ids=["limit-1", "limit-10", "no-limit"])
async def test_a_constant_pattern_accepts_a_limit(space_impl, make_space, graph_uri, limit):
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    rows = await _rows(space_impl, space_id, f"""
        SELECT * WHERE {{ GRAPH <{graph_uri}> {{
            <{SUBJ}> <{CORE}vitaltype> <{KG}KGFrame>
        }} }} {limit}""")
    # One matching row; the point is that it EXECUTES rather than raising a
    # syntax error, and still answers the existence question.
    assert len(rows) == 1


async def test_an_absent_constant_pattern_answers_empty_under_a_limit(
        space_impl, make_space, graph_uri):
    """The short-circuit must still short-circuit, and still say 'no'."""
    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    rows = await _rows(space_impl, space_id, f"""
        SELECT * WHERE {{ GRAPH <{graph_uri}> {{
            <{MISSING}> <{CORE}vitaltype> <{KG}KGFrame>
        }} }} LIMIT 1""")
    assert rows == []


@pytest.mark.parametrize("subj,expected", [(SUBJ, True), (MISSING, False)],
                         ids=["present", "absent"])
async def test_ask_over_a_constant_pattern_still_generates(space_impl, make_space,
                                                           graph_uri, subj, expected):
    """ASK takes its own path — the control that the fix did not disturb it.

    Asserted on the SQL rather than the bindings: this impl returns ASK as a
    `SELECT EXISTS (...)` with an empty `bindings` list, so reading the rows says
    nothing about the answer. Running the emitted SQL is what does.
    """
    import asyncpg
    from devtools.target import pg_kwargs

    space_id = await make_space()
    await _seed(space_impl, space_id, graph_uri)
    res = await space_impl.execute_sparql_query(space_id, f"""
        ASK {{ GRAPH <{graph_uri}> {{ <{subj}> <{CORE}vitaltype> <{KG}KGFrame> }} }}""")
    sql = res.get("sql")
    assert sql, "the impl no longer reports the SQL it ran"
    conn = await asyncpg.connect(**pg_kwargs())
    try:
        assert await conn.fetchval(sql) is expected
    finally:
        await conn.close()
