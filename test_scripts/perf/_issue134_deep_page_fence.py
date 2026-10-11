#!/usr/bin/env python3
"""issues/134: the deep-page `OFFSET 0` fence, measured on the cases the issue priced.

Generates each deep page (offset 1000, 25 rows) with the CURRENT generator, then
measures that SQL two ways: as emitted, and with the deep page's fence put back
(`\\n) AS dpN` -> `\\nOFFSET 0\\n) AS dpN`). So the A/B is the fence and nothing
else. Fenced with `enable_sort = off` only where `needs_ordered_scan` is set, as
the executor does. 5 runs per cell, alternating order; rows compared exactly.

Run with the test app stopped (its maintenance job re-ANALYZEs fixtures).

    python test_scripts/perf/_issue134_deep_page_fence.py
"""
import asyncio
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("VG_TEST_PG_PORT", "5433")
os.environ.setdefault("VG_TEST_PG_PASSWORD", "testpass")
os.environ.setdefault("VG_TEST_SIDECAR_URL", "http://localhost:7071")

import asyncpg  # noqa: E402

PG = dict(host="localhost", port=5433, database="sparql_sql_graph", user="postgres", password="testpass")
OFFSET = int(os.environ.get("OFFSET", "1000"))
RUNS = int(os.environ.get("RUNS", "5"))
DEEP_FROM = re.compile(r"\n\) AS (dp\d+)\n")


async def gen_sql(conn, fx, crit):
    from tests.performance.test_kgquery_generated_sql_plans import _to_builder_frame
    from tests.performance import test_kgquery_growth_curve as gc
    from vitalgraph.sparql.kg_query_builder import KGQueryCriteriaBuilder, EntityQueryCriteria
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.sparql_sql.generator import generate_sql
    ec = EntityQueryCriteria(entity_type=gc.KGENTITY, entity_uris=None,
                             frame_criteria=[_to_builder_frame(f) for f in crit],
                             use_edge_pattern=True)
    sparql = KGQueryCriteriaBuilder().build_entity_query_sparql(ec, fx.graph, gc.PAGE_SIZE, OFFSET)
    client = AsyncSidecarClient(os.environ["VG_TEST_SIDECAR_URL"])
    try:
        cr = map_compile_response(await client.compile(sparql))
    finally:
        await client.close()
    gen = await generate_sql(cr, fx.space, conn=conn)
    assert gen.ok, gen.error
    return gen


async def timed(conn, sql, nos):
    async with conn.transaction():
        await conn.execute("SET LOCAL statement_timeout = '300s'")
        if nos:
            await conn.execute("SET LOCAL enable_sort = off")
        t0 = time.perf_counter()
        rows = await conn.fetch(sql)
        return (time.perf_counter() - t0) * 1000, [tuple(r.values()) for r in rows]


async def main():
    from tests.performance import test_kgquery_growth_curve as gc
    conn = await asyncpg.connect(**PG)
    cases = [("eq CA", gc._eq_criteria("CA")), ("eq IL", gc._eq_criteria("IL")),
             ("eq VT", gc._eq_criteria("VT")), ("range 0.8", gc._range_criteria(0.8))]
    print(f"offset {OFFSET}, {RUNS} runs/cell, ms min/med/max")
    print(f"{'case':18} {'nos':5} {'gated has fence':15} {'fenced':>24} {'unfenced':>24} {'x':>6} rows")
    for fx in gc.FIXTURES:
        for label, crit in cases:
            gen = await gen_sql(conn, fx, crit)
            sql = gen.sql
            if not DEEP_FROM.search(sql):
                print(f"{fx.label + ' ' + label:18} not a deep page (no dpN subquery) — skipped")
                continue
            has_fence = "OFFSET 0\n) AS dp" in sql
            unf = sql.replace("\nOFFSET 0\n) AS dp", "\n) AS dp")
            fen = DEEP_FROM.sub(lambda m: f"\nOFFSET 0\n) AS {m.group(1)}\n", unf, count=1)
            await timed(conn, fen, gen.needs_ordered_scan)          # warm both
            await timed(conn, unf, gen.needs_ordered_scan)
            res = {"f": [], "u": []}
            rows = {}
            for i in range(RUNS):
                for k, s in ((("f", fen), ("u", unf)) if i % 2 == 0 else (("u", unf), ("f", fen))):
                    ms, rs = await timed(conn, s, gen.needs_ordered_scan)
                    res[k].append(ms)
                    rows[k] = rs
            f, u = sorted(res["f"]), sorted(res["u"])
            same = rows["f"] == rows["u"]
            print(f"{fx.label + ' ' + label:18} {str(gen.needs_ordered_scan):5} {str(has_fence):15} "
                  f"{f[0]:7.1f}/{statistics.median(f):7.1f}/{f[-1]:8.1f} "
                  f"{u[0]:7.1f}/{statistics.median(u):7.1f}/{u[-1]:8.1f} "
                  f"{statistics.median(f) / statistics.median(u):6.1f} {len(rows['u'])} {'same' if same else 'DIFFER'}")
    await conn.close()


asyncio.run(main())
