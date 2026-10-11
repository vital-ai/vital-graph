#!/usr/bin/env python3
"""issues/220: what does declining the vector top-K rewrite cost, and is there a correct fast form?

220's fix made `_annotate_vector_top_k` DECLINE when a FILTER sits between the
ORDER and the EXTEND, so a filtered vector query takes the correlated form (score
every row, then sort). It left three questions open, all needing "a fixture with a
large vector table AND a filtered query", which did not exist:

  1. what the decline costs on a large index with a selective filter;
  2. whether the driving form's child materialisation costs more than it saves;
  3. whether over-fetch-and-retry is needed, or something simpler is correct.

FIXTURE (`setup`, idempotent): space `perf220_vec_100k`, 100,000 KGEntities, each
with `urn:p220:tier` in {common 50%, uncommon 5%, rare 0.5%, other}, and a random
384-d vector in index `p220` (HNSW, the product DDL). Random vectors: the question
is plan cost and page fullness, not semantics.

FORMS, per filter selectivity:
  shipped   the query as a client writes it — FILTER in the same group as the
            BIND, so the FILTER lands ABOVE the EXTEND and the rewrite declines
  pushed    the same query with the FILTER in an inner group, so it lands BELOW
            the EXTEND — inside the driving subquery's child. Semantically
            identical (the filter does not mention ?vg_score), and it is the form
            an algebraic push-down would produce
  forced    shipped, with the decline patched out — the pre-220 behaviour, to
            show the short page it produced

Every form is checked against the EXACT answer (brute-force distance over the
filtered set in SQL): rows returned and overlap with the true top 10.

    python test_scripts/perf/_issue220_vector_topk.py setup
    python test_scripts/perf/_issue220_vector_topk.py measure
"""
import asyncio
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from rdflib import Literal, URIRef  # noqa: E402

SPACE = "perf220_vec_100k"
GRAPH = f"urn:{SPACE}:g"
INDEX = "p220"
DIM = 384
N = 100_000
K = 10
RUNS = int(os.environ.get("RUNS", "5"))
PG = dict(host="localhost", port=5433, database="sparql_sql_graph", user="postgres", password="testpass")
SIDECAR = "http://localhost:7071"
CORE = "http://vital.ai/ontology/vital-core#"
HALEY = "http://vital.ai/ontology/haley-ai-kg#"
VG = "http://vital.ai/ontology/vitalgraph#"
TIER = "urn:p220:tier"


def tier_of(i):
    r = (i * 2654435761) % 1000          # deterministic, evenly spread
    return "rare" if r < 5 else "uncommon" if r < 55 else "common" if r < 555 else "other"


def vec(rng):
    return "[" + ",".join(f"{rng.random() - 0.5:.4f}" for _ in range(DIM)) + "]"


async def _impl():
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
    impl = SparqlSQLSpaceImpl(
        postgresql_config={"host": PG["host"], "port": PG["port"], "database": PG["database"],
                           "username": PG["user"], "password": PG["password"],
                           "min_pool_size": 1, "max_pool_size": 4},
        sidecar_config={"url": SIDECAR})
    await impl.connect()
    return impl


async def setup():
    from vitalgraph.space.space_manager import SpaceManager
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    impl = await _impl()
    mgr = SpaceManager(db_impl=impl.db_impl, space_backend=impl)
    if not await mgr.get_space_or_load(SPACE):
        assert await mgr.create_space_with_tables(SPACE, SPACE, "issues/220 vector fixture")
    pool = impl.db_impl._pool
    async with pool.acquire() as c:
        have = await c.fetchval(f"SELECT count(*) FROM {SPACE}_rdf_quad")
    if not have:
        t0 = time.time()
        g = URIRef(GRAPH)
        for lo in range(0, N, 10_000):
            quads = []
            for i in range(lo, lo + 10_000):
                e = URIRef(f"urn:p220:e:{i}")
                quads += [(e, URIRef(f"{CORE}vitaltype"), URIRef(f"{HALEY}KGEntity"), g),
                          (e, URIRef(f"{CORE}hasName"), Literal(f"entity {i}"), g),
                          (e, URIRef(TIER), Literal(tier_of(i)), g)]
            await impl.add_rdf_quads_batch(SPACE, quads)
        print(f"quads loaded in {time.time() - t0:.0f}s")
    async with pool.acquire() as c:
        await c.execute(f"INSERT INTO {SPACE}_vector_index (index_name, dimensions, distance_metric, provider) "
                        f"VALUES ($1, $2, 'cosine', 'openai') ON CONFLICT DO NOTHING", INDEX, DIM)
        for stmt in SparqlSQLSchema().create_vector_data_table_sql(SPACE, INDEX, DIM, "vector_cosine_ops"):
            await c.execute(stmt)
        nvec = await c.fetchval(f"SELECT count(*) FROM {SPACE}_vec_{INDEX}")
        if nvec < N:
            ctx = await c.fetchval(f"SELECT term_uuid FROM {SPACE}_term WHERE term_text = $1", GRAPH)
            subs = await c.fetch(
                f"SELECT q.subject_uuid FROM {SPACE}_rdf_quad q JOIN {SPACE}_term t ON t.term_uuid = q.object_uuid "
                f"WHERE t.term_text = $1 ORDER BY q.subject_uuid", f"{HALEY}KGEntity")
            rng = random.Random(220)
            t0 = time.time()
            # Bulk load: maintaining HNSW per insert is slow enough to time out.
            # Drop it, load, then recreate the product's own DDL read back here.
            hnsw = await c.fetchrow(
                "SELECT indexrelid::regclass::text AS name, pg_get_indexdef(indexrelid) AS ddl "
                "FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid JOIN pg_am a ON a.oid = c.relam "
                "WHERE i.indrelid = $1::regclass AND a.amname = 'hnsw'", f"{SPACE}_vec_{INDEX}")
            if hnsw:
                await c.execute(f"DROP INDEX {hnsw['name']}")
            # No binary COPY encoder for `vector`; text literals through executemany.
            recs = [(r["subject_uuid"], ctx, vec(rng)) for r in subs]
            for lo in range(0, len(recs), 5000):
                await c.executemany(
                    f"INSERT INTO {SPACE}_vec_{INDEX} (subject_uuid, context_uuid, embedding) "
                    f"VALUES ($1, $2, $3::vector) ON CONFLICT DO NOTHING", recs[lo:lo + 5000])
            if hnsw:
                t1 = time.time()
                await c.execute("SET maintenance_work_mem = '2GB'")
                await c.execute(hnsw["ddl"], timeout=3600)
                print(f"HNSW rebuilt in {time.time() - t1:.0f}s")
            print(f"{len(subs):,} vectors loaded in {time.time() - t0:.0f}s")
        await c.execute(f"ANALYZE {SPACE}_vec_{INDEX}")
        print("vectors:", await c.fetchval(f"SELECT count(*) FROM {SPACE}_vec_{INDEX}"))
    await impl.disconnect()


def sparql(probe, tier, form):
    bind = f'BIND(<{VG}vectorNearby>(?e, "{probe}", "{INDEX}") AS ?vg_score)'
    base = f"?e <{CORE}vitaltype> <{HALEY}KGEntity> ."
    if tier is None:
        body = f"{base} {bind}"
    else:
        flt = f'?e <{TIER}> ?t . FILTER(?t = "{tier}")'
        body = f"{{ {base} {flt} }} {bind}" if form == "pushed" else f"{base} {flt} {bind}"
    return (f"SELECT ?e ?vg_score WHERE {{ GRAPH <{GRAPH}> {{ {body} }} }} "
            f"ORDER BY DESC(?vg_score) LIMIT {K}")


async def generate(text, forced):
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql import vg_optimize as vo
    client = AsyncSidecarClient(base_url=SIDECAR)
    cr = map_compile_response(await client.compile(text))
    await client.close()
    saved = vo._restriction_between
    if forced:
        vo._restriction_between = lambda *a, **k: None
    try:
        import asyncpg
        conn = await asyncpg.connect(**PG)
        try:
            gen = await generate_sql(cr, SPACE, conn=conn)
        finally:
            await conn.close()
    finally:
        vo._restriction_between = saved
    assert gen.ok, gen.error
    return gen


async def measure():
    import asyncpg
    from vitalgraph.db.sparql_sql.vg_resolve import resolve_vector_requests
    rng = random.Random(4220)
    probe = vec(rng)
    conn = await asyncpg.connect(**PG)
    # The executor resolves vector placeholders before running; do the same.
    print(f"{'filter':9} {'form':7} {'driving':7} {'rows':>4} {'recall@10':>9} {'buffers':>10} {'ms min/med/max':>22}")
    for tier in (None, "common", "uncommon", "rare"):
        where = "" if tier is None else (
            f"AND v.subject_uuid IN (SELECT q.subject_uuid FROM {SPACE}_rdf_quad q "
            f"JOIN {SPACE}_term p ON p.term_uuid = q.predicate_uuid AND p.term_text = '{TIER}' "
            f"JOIN {SPACE}_term o ON o.term_uuid = q.object_uuid AND o.term_text = '{tier}')")
        # EXACT: the brute-force nearest over the filtered set, no HNSW.
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_indexscan = off")
            truth = {r[0] for r in await conn.fetch(
                f"SELECT v.subject_uuid FROM {SPACE}_vec_{INDEX} v WHERE TRUE {where} "
                f"ORDER BY v.embedding <=> '{probe}'::vector LIMIT {K}")}
        for form in (("shipped",) if tier is None else ("shipped", "pushed", "forced")):
            gen = await generate(sparql(probe, tier, form), form == "forced")
            sql = gen.sql
            if gen.vector_requests:
                sql = await resolve_vector_requests(sql, gen.vector_requests, SPACE, conn)
            driving = "__vg_score" in sql
            ms, bufs, rows = [], [], None
            for _ in range(RUNS):
                async with conn.transaction():
                    await conn.execute("SET LOCAL statement_timeout = '120s'")
                    if gen.needs_ordered_scan:
                        await conn.execute("SET LOCAL enable_sort = off")
                    pj = json.loads(await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql))[0]
                    rows = await conn.fetch(sql)
                ms.append(pj["Execution Time"])
                bufs.append(pj["Plan"].get("Shared Hit Blocks", 0) + pj["Plan"].get("Shared Read Blocks", 0))
            got = set()
            for r in rows:
                for k, v in r.items():
                    if k.endswith("__uuid") and v in truth:
                        got.add(v)
            ms.sort()
            print(f"{tier or 'none':9} {form:7} {str(driving):7} {len(rows):4} {len(got):>6}/{len(truth):<2} "
                  f"{statistics.median(bufs):>10,.0f} {ms[0]:7.1f}/{statistics.median(ms):7.1f}/{ms[-1]:7.1f}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run({"setup": setup, "measure": measure}[sys.argv[1]]())
