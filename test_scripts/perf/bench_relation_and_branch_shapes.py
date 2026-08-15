"""Which traversal shapes the machinery fires on, and why it declines the rest.

GAP 4 lists relation walks, branching and UNION as shapes nothing had seen.
Measured 2026-08-15: relation walks use `emit_dedup_chain` exactly as frames do
(18/18 correct, 2-9 ms); branching and UNION decline to the flat plan, at
82-1,787 ms and 10-48 ms respectively.


GAP 4: relation walks go entity -> entity through Edge_hasKGRelation, with no
frame and no slots, so `frame_entity` cannot apply and the edge table has to
carry it. Chain detection, hop-wise emission and dedup were all built and
measured on the frame-mediated shape.

The declines log answers "why not" directly, which is what it was built for.
"""
import asyncio, os, statistics, sys, time
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg
from tests.performance.graph_fixtures import (SMALL, CRITERIA, chain_query,
                                              relation_hop, frame_hop, entity_indexes)
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql.generator import generate_sql

async def gen(conn, q):
    c = AsyncSidecarClient("http://localhost:7071")
    raw = await c.compile(q)
    cl = getattr(c,"aclose",None) or getattr(c,"close",None)
    if cl:
        r=cl()
        if hasattr(r,"__await__"): await r
    cr = map_compile_response(raw); assert cr.ok, cr.error
    return await generate_sql(cr, SMALL.space, conn=conn)

def shape(sql):
    if "MATERIALIZED" in sql: return "dedup"
    if "CROSS JOIN LATERAL" in sql: return "hop-wise"
    return "flat"

async def main():
    conn = await asyncpg.connect(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass")
    await conn.execute("SET statement_timeout='120s'")
    starts = SMALL.sample_starts()[:3]
    print(f"{'shape':10s} {'depth':>5s} {'start':>7s} {'emission':10s} {'ms':>9s} {'rows':>6s}  correct")
    for label, hop, key in (("frame", frame_hop, "frame_traversal"),
                            ("relation", relation_hop, "relation_traversal")):
        for depth in (1, 2, 3):
            for start in starts:
                q = chain_query(SMALL, start, depth, hop=hop)
                g = await gen(conn, q)
                t0 = time.perf_counter(); rows = await conn.fetch(g.sql)
                ms = (time.perf_counter()-t0)*1000
                got = entity_indexes(rows); exp = SMALL.expected(key, start, depth)
                print(f"{label:10s} {depth:5d} {start:7d} {shape(g.sql):10s} {ms:9.1f} "
                      f"{len(got):6d}  {'OK' if got==exp else f'MISMATCH exp {len(exp)}'}",
                      flush=True)
            if label == "relation" and depth == 3:
                g = await gen(conn, chain_query(SMALL, starts[0], depth, hop=hop))
                print("   declines for the relation walk:", flush=True)
                for d in (g.declines or []):
                    print(f"     {d}", flush=True)
    await conn.close()
asyncio.run(main())
