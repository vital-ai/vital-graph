"""Is a UNION traversal ever actually slow?

`dedup_chain` declines a UNION with "no single-child path from the root down to
one BGP [root_kind='distinct']" — each branch IS a chain and could be
deduplicated independently, but dedup_feasible walks root to exactly one BGP.
Recorded, not built, pending evidence it matters. 10-48 ms on 10k depth 2-3
from two ordinary starts is not that evidence.

This looks where it should hurt: the 100k space, hub starts, depth 3, both
unfiltered and filtered, and both frame|frame and frame|relation unions. The
comparison is against the SAME walk as a single branch, which DOES dedup — so
the number is what declining costs, not what the query costs.
"""
import asyncio, os, statistics, sys, time
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg
from tests.performance.graph_fixtures import (LARGE, CRITERIA, chain_query,
                                              frame_hop, relation_hop)
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
    cr = map_compile_response(raw)
    if not cr.ok: return None
    g = await generate_sql(cr, LARGE.space, conn=conn)
    return g if g.ok else None

def shape(sql):
    if "MATERIALIZED" in sql: return "dedup"
    if "CROSS JOIN LATERAL" in sql: return "hop-wise"
    return "flat"

def union_q(start, depth, crit="", second=relation_hop):
    a = "".join(frame_hop(i+1, f"?e{i}", f"?e{i+1}", crit) for i in range(depth))
    b = "".join(second(50+i, f"?e{i}", f"?e{i+1}") for i in range(depth))
    return f"""
    SELECT DISTINCT ?e{depth} WHERE {{ GRAPH <{LARGE.graph}> {{
        {{ {a} FILTER(?e0 = <{LARGE.entity_uri(start)}>) }}
        UNION
        {{ {b} FILTER(?e0 = <{LARGE.entity_uri(start)}>) }}
    }} }}"""

async def timed(conn, sql, reps=3):
    ts, n = [], 0
    for _ in range(reps):
        t0 = time.perf_counter(); rows = await conn.fetch(sql)
        ts.append((time.perf_counter()-t0)*1000); n = len(rows)
    return statistics.median(ts), n

async def main():
    conn = await asyncpg.connect(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass")
    await conn.execute("SET statement_timeout='180s'")
    starts = LARGE.sample_starts()[:4]
    score, _ = CRITERIA["score_gte_50"]
    print(f"{'case':34s} {'start':>7s} {'union':>10s} {'1 branch':>10s} {'shape':9s} rows")
    for label, depth, crit, second in (
            ("frame|relation d3 open",  3, "",      relation_hop),
            ("frame|relation d3 score", 3, score,   relation_hop),
            ("frame|frame    d3 open",  3, "",      frame_hop),
            ("frame|relation d4 open",  4, "",      relation_hop)):
        for start in starts:
            gu = await gen(conn, union_q(start, depth, crit, second))
            gs = await gen(conn, chain_query(LARGE, start, depth, criterion=crit))
            if gu is None or gs is None:
                print(f"{label:34s} {start:7d}  GEN FAIL", flush=True); continue
            try:
                mu, nu = await timed(conn, gu.sql)
                ms, ns = await timed(conn, gs.sql)
                print(f"{label:34s} {start:7d} {mu:10.1f} {ms:10.1f} "
                      f"{shape(gu.sql):9s} {nu}", flush=True)
            except Exception as e:
                print(f"{label:34s} {start:7d}  {str(e)[:50]}", flush=True)
    await conn.close()
asyncio.run(main())
