"""L2 geo benchmark: populating the geo side-table, and searching it.

`issues/192` lists geo as having correctness tests and zero bench cells, and
`perf_coverage_gaps_plan.md` §5 described every such row as "a marker plus a
`perf_record` call away". That is not true here — geo's correctness lives in the
API tier (4 files), which the perf tier does not run — and it understates the
cost in the other direction too: there was no populated geo fixture ANYWHERE.
162 `*_geo` tables exist on the dev stack and the ones sampled hold zero rows.

So the bench builds its own, and that is the point rather than an inconvenience:

    populate_geo_s      the WRITE half — datatype-driven scan of the quads,
                        parse WKT, upsert points
    geo_search_ms       the READ half — vg:geoDistance through the same
                        builder -> sidecar -> generate_sql path every other
                        kgquery bench uses, with no app involved

BOTH HALVES, because an empty geo table answers a proximity search instantly and
would bench nothing. `rows_returned` and `uses_geo_table` are asserted for that
reason: this suite has repeatedly found "fast" numbers that were measuring a
query which matched nothing, and a geo bench against an unpopulated table is
exactly that failure with a plausible-looking latency attached.

Ingest tier: it creates a space and writes. The search half is read-only and
would belong in the fast tier if a SEEDED geo fixture existed; none does, so the
fixture and the measurement travel together for now.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import pytest_asyncio
from rdflib import URIRef, Literal

from .conftest import skip_no_pg

pytestmark = [pytest.mark.performance, pytest.mark.ingest_bench, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

CORE = "http://vital.ai/ontology/vital-core#"
HALEY = "http://vital.ai/ontology/haley-ai-kg#"
WKT = URIRef("http://www.opengis.net/ont/geosparql#wktLiteral")

# A 100x100 lattice of points over ~1 degree, so a radius search selects a
# meaningful fraction rather than everything or nothing.
N_POINTS = 2_000
SEARCH_RADIUS_M = 200_000
TOP_K = 25

PG = dict(
    host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
    port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
    database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
    user=os.environ.get("VG_TEST_PG_USER", "postgres"),
    password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"),
)


@pytest_asyncio.fixture(loop_scope="session")
async def geo_space():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    from vitalgraph.space.space_manager import SpaceManager
    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": PG["host"], "port": PG["port"],
                           "database": PG["database"], "username": PG["user"],
                           "password": PG["password"],
                           "min_pool_size": 1, "max_pool_size": 4},
        sidecar_config={"url": os.environ.get("VG_TEST_SIDECAR_URL",
                                              "http://localhost:7071")})
    await impl.connect()
    mgr = SpaceManager(db_impl=getattr(impl, "db_impl", None), space_backend=impl)
    sid = f"perfgeo_{uuid.uuid4().hex[:8]}"
    if not await mgr.create_space_with_tables(sid, sid):
        await impl.disconnect()
        pytest.skip(f"space manager failed to create {sid}")
    try:
        yield sid, impl
    finally:
        try:
            await mgr.delete_space_with_tables(sid)
        except Exception:
            pass
        await impl.disconnect()


@pytest.mark.bench("geo.populate_and_search")
async def test_geo_populate_and_search(geo_space, perf_record):
    from vitalgraph.vectorization.geo_populator import populate_geo
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria, GeoCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    sid, impl = geo_space
    graph = URIRef(f"urn:{sid}:g")

    quads = []
    for i in range(N_POINTS):
        e = URIRef(f"urn:perfgeo:e:{i}")
        lat = 37.0 + (i % 100) * 0.01
        lon = -122.0 + (i // 100) * 0.01
        quads += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{HALEY}KGEntity"), graph),
            (e, URIRef(f"{CORE}hasGeoLocation"),
             Literal(f"POINT({lon} {lat})", datatype=WKT), graph),
        ]
    t0 = time.perf_counter()
    await impl.add_rdf_quads_batch(sid, quads)
    seed_s = time.perf_counter() - t0

    pool = impl.db_impl._pool
    async with pool.acquire() as conn:
        ctx = await conn.fetchval(
            f"SELECT term_uuid FROM {sid}_term WHERE term_text = $1", str(graph))
        t0 = time.perf_counter()
        stats = await populate_geo(conn, sid, ctx)
        populate_s = time.perf_counter() - t0
        geo_rows = await conn.fetchval(f"SELECT count(*) FROM {sid}_geo")

    assert geo_rows == N_POINTS, (
        f"{geo_rows} geo rows for {N_POINTS} points — the search below would "
        f"measure a table that is not populated, which is the failure this "
        f"bench exists to avoid")

    crit = EntityQueryCriteria(
        entity_type=f"{HALEY}KGEntity",
        geo_criteria=GeoCriteria(latitude=37.5, longitude=-121.5,
                                 radius_m=SEARCH_RADIUS_M,
                                 sort_by_distance=True, top_k=TOP_K))
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(
        crit, str(graph), TOP_K, 0)
    client = AsyncSidecarClient(
        os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071"))
    try:
        raw = await client.compile(sparql)
    finally:
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if closer:
            res = closer()
            if hasattr(res, "__await__"):
                await res
    cr = map_compile_response(raw)
    assert cr.ok, f"geo SPARQL failed to compile: {cr.error}"

    async with pool.acquire() as conn:
        gen = await generate_sql(cr, sid, conn=conn)
        assert gen.ok, f"geo query failed to generate SQL: {gen.error}"
        uses_geo = f"{sid}_geo" in gen.sql
        await conn.fetch(gen.sql)                       # warm
        runs = []
        for _ in range(3):
            t0 = time.perf_counter()
            rows = await conn.fetch(gen.sql)
            runs.append((time.perf_counter() - t0) * 1000)
    search_ms = sorted(runs)[1]

    perf_record(
        kind="query", dataset=f"synthetic:{N_POINTS}points",
        metrics={
            "seed_quads_per_sec": round(len(quads) / seed_s),
            "populate_geo_s": round(populate_s, 3),
            "points_upserted": stats.points_upserted,
            "points_per_sec": round(stats.points_upserted / populate_s)
            if populate_s else 0,
            "geo_search_ms": round(search_ms, 1),
            "rows_returned": len(rows),
        },
        notes=f"issues/192 — geo populate + vg:geoDistance search, "
              f"radius {SEARCH_RADIUS_M}m top_k {TOP_K}")

    assert uses_geo, (
        f"the geo search did not touch {sid}_geo, so it is not measuring the "
        f"geo path at all")
    assert rows, (
        "the geo search returned no rows, so its latency describes a query "
        "that matched nothing")
