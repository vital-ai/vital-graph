"""L2 vector benchmark: HNSW similarity search over a populated index.

`issues/192` lists vector search as correctness-tested with zero bench cells.
Its correctness lives in the API tier (13 files), which the perf tier does not
run, and there was no populated vector index anywhere — zero `*_vec_*` tables on
the dev stack. So the bench builds its own.

EMBEDDING IS DELIBERATELY NOT IN THE MEASUREMENT. `VectorCriteria` takes either
`search_text`, which is vectorised SERVER-SIDE and would drag an OpenAI call or
a local MiniLM load into a perf run, or `vector`, a pre-computed literal. This
uses `vector`, so the number describes the INDEX — HNSW probe, join back to the
entity — and not an embedding model's latency. The vectors are seeded from a
fixed `random.Random(42)` for the same reason: reproducible, and nothing here
depends on them being semantically meaningful.

The index is built with the product's own DDL (`create_vector_data_table_sql`,
HNSW with `vector_cosine_ops`) rather than hand-rolled, so a schema change to
the vector table moves this bench rather than silently bypassing it.

WHY IT ASSERTS. An EMPTY vector index answers a top-k query instantly, so a
search-only bench against an unpopulated index reports a plausible latency for
matching nothing. `rows_returned`, `uses_vec_table` and the row count are all
checked before the timing is believed.

Ingest tier: it creates a space and writes. The search half is read-only and
would move to the fast tier if a SEEDED vector fixture existed; none does.
"""
from __future__ import annotations

import os
import random
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

DIMENSIONS = 384          # MiniLM-shaped, without needing MiniLM
N_ENTITIES = 2_000
INDEX_NAME = "entity_default"
TOP_K = 10
SEED = 42

PG = dict(
    host=os.environ.get("VG_TEST_PG_HOST", "localhost"),
    port=int(os.environ.get("VG_TEST_PG_PORT", "5433")),
    database=os.environ.get("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
    user=os.environ.get("VG_TEST_PG_USER", "postgres"),
    password=os.environ.get("VG_TEST_PG_PASSWORD", "testpass"),
)


def _vector(rng) -> str:
    """A pgvector literal. Values are arbitrary; only the SHAPE matters here."""
    return "[" + ",".join(f"{rng.random():.4f}" for _ in range(DIMENSIONS)) + "]"


@pytest_asyncio.fixture(loop_scope="session")
async def vector_space():
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
    sid = f"perfvec_{uuid.uuid4().hex[:8]}"
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


@pytest.mark.bench("vector.index_and_search")
async def test_vector_index_build_and_search(vector_space, perf_record):
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    from vitalgraph.sparql.kg_query_builder import (
        KGQueryCriteriaBuilder, EntityQueryCriteria, VectorCriteria)
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql

    sid, impl = vector_space
    graph = URIRef(f"urn:{sid}:g")
    rng = random.Random(SEED)

    quads = []
    for i in range(N_ENTITIES):
        e = URIRef(f"urn:perfvec:e:{i}")
        quads += [
            (e, URIRef(f"{CORE}vitaltype"), URIRef(f"{HALEY}KGEntity"), graph),
            (e, URIRef(f"{CORE}hasName"), Literal(f"entity {i}"), graph),
        ]
    t0 = time.perf_counter()
    await impl.add_rdf_quads_batch(sid, quads)
    seed_s = time.perf_counter() - t0

    pool = impl.db_impl._pool
    async with pool.acquire() as conn:
        ctx = await conn.fetchval(
            f"SELECT term_uuid FROM {sid}_term WHERE term_text = $1", str(graph))
        await conn.execute(
            f"INSERT INTO {sid}_vector_index "
            f"(index_name, dimensions, distance_metric, provider) "
            f"VALUES ($1, $2, 'cosine', 'openai') ON CONFLICT DO NOTHING",
            INDEX_NAME, DIMENSIONS)
        t0 = time.perf_counter()
        for stmt in SparqlSQLSchema().create_vector_data_table_sql(
                sid, INDEX_NAME, DIMENSIONS, "vector_cosine_ops"):
            await conn.execute(stmt)
        ddl_s = time.perf_counter() - t0

        subjects = await conn.fetch(
            f"SELECT DISTINCT subject_uuid FROM {sid}_rdf_quad LIMIT {N_ENTITIES}")
        t0 = time.perf_counter()
        await conn.executemany(
            f"INSERT INTO {sid}_vec_{INDEX_NAME} "
            f"(subject_uuid, context_uuid, embedding) "
            f"VALUES ($1, $2, $3::vector) ON CONFLICT DO NOTHING",
            [(r["subject_uuid"], ctx, _vector(rng)) for r in subjects])
        upsert_s = time.perf_counter() - t0
        vec_rows = await conn.fetchval(f"SELECT count(*) FROM {sid}_vec_{INDEX_NAME}")

    assert vec_rows >= N_ENTITIES * 0.9, (
        f"{vec_rows} vectors for {N_ENTITIES} entities — the search below would "
        f"measure an index that is not populated")

    crit = EntityQueryCriteria(
        entity_type=f"{HALEY}KGEntity",
        vector_criteria=VectorCriteria(vector=_vector(random.Random(SEED + 1)),
                                       index_name=INDEX_NAME, top_k=TOP_K))
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
    assert cr.ok, f"vector SPARQL failed to compile: {cr.error}"

    async with pool.acquire() as conn:
        gen = await generate_sql(cr, sid, conn=conn)
        assert gen.ok, f"vector query failed to generate SQL: {gen.error}"
        uses_vec = f"{sid}_vec_{INDEX_NAME}" in gen.sql
        await conn.fetch(gen.sql)                        # warm
        runs = []
        for _ in range(3):
            t0 = time.perf_counter()
            rows = await conn.fetch(gen.sql)
            runs.append((time.perf_counter() - t0) * 1000)
    search_ms = sorted(runs)[1]

    perf_record(
        kind="query", dataset=f"synthetic:{N_ENTITIES}vectors:{DIMENSIONS}d",
        metrics={
            "seed_quads_per_sec": round(len(quads) / seed_s),
            "index_ddl_s": round(ddl_s, 3),
            "vectors_upserted": vec_rows,
            "vectors_per_sec": round(vec_rows / upsert_s) if upsert_s else 0,
            "vector_search_ms": round(search_ms, 2),
            "rows_returned": len(rows),
        },
        notes=f"issues/192 — HNSW top-{TOP_K} over {N_ENTITIES} "
              f"{DIMENSIONS}-d vectors, pre-computed probe (no embedding)")

    assert uses_vec, (
        f"the vector search did not touch {sid}_vec_{INDEX_NAME}, so it is not "
        f"measuring the index at all")
    assert rows, (
        "the vector search returned no rows, so its latency describes a query "
        "that matched nothing")
