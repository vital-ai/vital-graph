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
from vitalgraph.db.sparql_sql.bulk_export import export_space, import_space
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
