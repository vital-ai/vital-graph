"""The default graph is not one of the named graphs.

`named_graph_semantics` §4.2. Quads written without an explicit graph land in
a context whose URI is the literal `urn:default`. That context used to be an
ordinary named graph in every respect, so the same triples were reachable
three ways — as the default graph, as `GRAPH <urn:default>`, and as a member
of `GRAPH ?g` — and the catalog listed `urn:default` as though a user had
created it.

SPARQL's dataset model says the default graph is not a named graph. These
tests pin the three exclusions that make that true, because the failure mode
is a silently WIDER answer: nothing errors, a `GRAPH ?g` query just quietly
returns rows the spec says it should not, and no existing test noticed.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import Literal, URIRef

from vitalgraph.db.sparql_sql.default_graph import DEFAULT_GRAPH_URI

from .conftest import skip_no_infra, TEST_SPACE_PREFIX

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

NAMED = "urn:dg:named"
P = "urn:dg:p"
SIDECAR = "http://localhost:7071"


@pytest_asyncio.fixture(loop_scope="session")
async def dg_space(space_impl, make_space):
    """One real named graph, plus data in the default graph's context."""
    sid = await make_space(f"{TEST_SPACE_PREFIX}dg_{uuid.uuid4().hex[:8]}")
    await space_impl.add_rdf_quads_batch_bulk(sid, [
        (URIRef("urn:dg:inNamed"), URIRef(P), Literal("named"), URIRef(NAMED)),
        (URIRef("urn:dg:inDefault"), URIRef(P), Literal("default"),
         URIRef(DEFAULT_GRAPH_URI)),
    ])
    return sid


async def _run(space_impl, space, sparql):
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    client = AsyncSidecarClient(SIDECAR)
    try:
        cr = map_compile_response(await client.compile(sparql))
        assert cr.ok, f"compile failed: {cr.error}"
        async with space_impl.db_impl.connection_pool.acquire() as conn:
            gen = await generate_sql(cr, space, conn=conn)
            assert gen.ok, f"generation refused: {gen.error}"
            rows = await conn.fetch(gen.sql)
        return sorted(str(list(dict(r).values())[0]) for r in rows)
    finally:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close:
            res = close()
            if hasattr(res, "__await__"):
                await res


# --- 1. GRAPH ?g enumeration ----------------------------------------------

async def test_graph_var_does_not_enumerate_the_default_graph(
        space_impl, dg_space):
    """THE case. `GRAPH ?g` lists named graphs, and the default is not one.

    This is the exclusion that was only applied when a caller passed an
    explicit default_graph — which production never does — so every real
    deployment enumerated `urn:default` here.
    """
    graphs = await _run(space_impl, dg_space,
                        "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }")
    assert graphs == [NAMED]
    assert DEFAULT_GRAPH_URI not in graphs


async def test_graph_var_still_returns_real_named_graphs(space_impl, dg_space):
    """The exclusion must not be a blanket one."""
    subjects = await _run(
        space_impl, dg_space,
        "SELECT ?s WHERE { GRAPH ?g { ?s <%s> ?o } }" % P)
    assert subjects == ["urn:dg:inNamed"]


# --- 2. FROM NAMED eligibility --------------------------------------------

async def test_from_named_cannot_name_the_default_graph(space_impl, dg_space):
    """`FROM NAMED <urn:default>` must not make the default graph addressable.

    Empty, not "everything" — the §4.1 rule that an empty named-graph set
    matches nothing is what keeps this from silently widening.
    """
    subjects = await _run(
        space_impl, dg_space,
        f"SELECT ?s FROM NAMED <{DEFAULT_GRAPH_URI}> "
        "WHERE { GRAPH ?g { ?s ?p ?o } }")
    assert subjects == []


async def test_from_named_on_a_real_graph_still_works(space_impl, dg_space):
    subjects = await _run(
        space_impl, dg_space,
        f"SELECT ?s FROM NAMED <{NAMED}> WHERE {{ GRAPH ?g {{ ?s ?p ?o }} }}")
    assert subjects == ["urn:dg:inNamed"]


# --- 3. the graph catalog --------------------------------------------------

async def test_catalog_does_not_register_the_default_graph(
        space_impl, dg_space):
    """`register_graphs_from_data` derives rows from the data, minus this one.

    The carve-out is deliberate and declared in that module: `urn:default` is
    a storage detail, not a graph a user made, and registering it put it in
    every listing of "the graphs in this space".
    """
    from vitalgraph.db.sparql_sql.graph_registry import register_graphs_from_data

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        await register_graphs_from_data(conn, dg_space)
        rows = await conn.fetch(
            "SELECT graph_uri FROM graph WHERE space_id = $1", dg_space)
    uris = sorted(r["graph_uri"] for r in rows)
    assert DEFAULT_GRAPH_URI not in uris
    assert NAMED in uris
