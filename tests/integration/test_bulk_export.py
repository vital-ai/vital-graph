"""Integration: streaming COPY export → import round-trips a space exactly.

Export the core tables of a loaded space via binary COPY, restore them into a
fresh space, and assert identical row counts, byte-exact quad_uuids, and that
the derived edge/stats tables were rebuilt on import (space is queryable again).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from rdflib import URIRef, Literal
from rdflib.namespace import XSD

from .conftest import skip_no_infra, TEST_SPACE_PREFIX
from vitalgraph.db.sparql_sql.bulk_export import (
    export_space, import_space, export_space_to_nquads)
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

pytestmark = [pytest.mark.integration, skip_no_infra,
              pytest.mark.asyncio(loop_scope="session")]

HES = URIRef("http://vital.ai/ontology/vital-core#hasEdgeSource")
HED = URIRef("http://vital.ai/ontology/vital-core#hasEdgeDestination")
G = URIRef("urn:export:g")
N_EDGES = 30


@pytest_asyncio.fixture(loop_scope="session")
async def two_spaces(space_impl):
    sids = [f"{TEST_SPACE_PREFIX}exp_{k}_{uuid.uuid4().hex[:8]}" for k in ("src", "dst")]
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        for sid in sids:
            await SparqlSQLSchema.create_space(conn, sid)
    yield sids
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        for sid in sids:
            await SparqlSQLSchema.drop_space(conn, sid)


async def _counts(conn, sid):
    t = SparqlSQLSchema.get_table_names(sid)
    return {k: await conn.fetchval(f"SELECT count(*) FROM {t[k]}")
            for k in ("datatype", "term", "rdf_quad", "edge")}


async def _quad_uuids(conn, sid):
    return {r["quad_uuid"] for r in
            await conn.fetch(f"SELECT quad_uuid FROM {sid}_rdf_quad")}


async def test_export_import_round_trip(space_impl, two_spaces, tmp_path):
    src, dst = two_spaces

    quads = []
    for i in range(N_EDGES):
        e = URIRef(f"urn:export:e:{i}")
        quads += [
            (e, HES, URIRef(f"urn:export:s:{i}"), G),
            (e, HED, URIRef(f"urn:export:d:{i}"), G),
            (URIRef(f"urn:export:n:{i}"), URIRef("urn:export:age"),
             Literal(i, datatype=XSD.integer), G),
        ]
    await space_impl.add_rdf_quads_batch_bulk(src, quads)

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        src_counts = await _counts(conn, src)
        src_quads = await _quad_uuids(conn, src)
        paths = await export_space(conn, src, str(tmp_path))

    async with space_impl.db_impl.connection_pool.acquire() as conn:
        async with conn.transaction():
            await import_space(conn, dst, paths)
        dst_counts = await _counts(conn, dst)
        dst_quads = await _quad_uuids(conn, dst)

    assert dst_counts == src_counts, (src_counts, dst_counts)
    assert src_counts["edge"] == N_EDGES        # derived table populated in src...
    assert dst_counts["edge"] == N_EDGES        # ...and rebuilt on import
    assert dst_quads == src_quads               # byte-exact quad_uuid fidelity


async def test_nquads_export_roundtrips_terms_and_escaping(space_impl, two_spaces, tmp_path):
    """DB → N-Quads → rdflib reparse preserves URIs, langs, datatypes, and
    literals with N-Triples special characters."""
    import rdflib
    from rdflib.namespace import XSD

    sid = two_spaces[0]
    g = URIRef("urn:nq:g")
    s = URIRef("urn:nq:s1")
    quads = [
        (s, URIRef("urn:nq:pu"), URIRef("urn:nq:obj"), g),
        (s, URIRef("urn:nq:plain"), Literal("hello world"), g),
        (s, URIRef("urn:nq:lang"), Literal("bonjour", lang="fr"), g),
        (s, URIRef("urn:nq:int"), Literal(42), g),                    # xsd:integer
        (s, URIRef("urn:nq:esc"), Literal('a "quote"\nand\\slash\ttab'), g),
    ]
    await space_impl.add_rdf_quads_batch_bulk(sid, quads)

    out = str(tmp_path / "export.nq")
    async with space_impl.db_impl.connection_pool.acquire() as conn:
        n = await export_space_to_nquads(conn, sid, out, graph_uri=str(g))
    assert n == len(quads)

    ds = rdflib.Dataset()
    ds.parse(out, format="nquads")
    got = {(str(qs), str(qp), str(qo)) for qs, qp, qo, _ in ds.quads()}
    want = {(str(a), str(b), str(c)) for a, b, c, _ in quads}
    assert got == want, (got ^ want)

    # datatype + lang survived (not just lexical form)
    objs = {p: o for _, p, o, _ in ds.quads()}
    assert objs[rdflib.URIRef("urn:nq:int")].datatype == XSD.integer
    assert objs[rdflib.URIRef("urn:nq:lang")].language == "fr"
