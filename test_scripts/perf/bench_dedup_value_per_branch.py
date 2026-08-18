"""What is dedup worth on ONE branch at the hub? That is the union's upside.

If per-branch dedup were available under a UNION, the frame branch would go
from its flat cost to its dedup cost. Measuring that difference on the same
query bounds the win — anything the union does beyond it is the second branch
doing real work, which no optimisation removes.
"""
import asyncio, os, statistics, sys, time
sys.path.insert(0, "/Users/hadfield/Local/vital-git/vital-graph")
from devtools.target import sidecar_url  # noqa: E402
os.chdir("/Users/hadfield/Local/vital-git/vital-graph")
import asyncpg
from tests.performance.graph_fixtures import LARGE, CRITERIA, chain_query
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
from vitalgraph.db.sparql_sql import emit_traversal
from vitalgraph.db.sparql_sql.generator import generate_sql

_real = emit_traversal.dedup_feasible
def _nodedup(*a, **kw): return None

async def gen(conn, q):
    c = AsyncSidecarClient(sidecar_url())
    raw = await c.compile(q)
    cl = getattr(c,"aclose",None) or getattr(c,"close",None)
    if cl:
        r=cl()
        if hasattr(r,"__await__"): await r
    g = await generate_sql(map_compile_response(raw), LARGE.space, conn=conn)
    return g

def shape(sql):
    if "MATERIALIZED" in sql: return "dedup"
    if "CROSS JOIN LATERAL" in sql: return "hop-wise"
    return "flat"

async def med(conn, sql, reps=3):
    ts = []
    for _ in range(reps):
        t0=time.perf_counter(); rows=await conn.fetch(sql); ts.append((time.perf_counter()-t0)*1000)
    return statistics.median(ts), len(rows)

async def main():
    conn = await asyncpg.connect(host="localhost", port=5433,
        database="sparql_sql_graph", user="postgres", password="testpass")
    await conn.execute("SET statement_timeout='180s'")
    score, _ = CRITERIA["score_gte_50"]
    print(f"{'case':28s} {'start':>7s} {'with dedup':>11s} {'no dedup':>10s} {'ratio':>7s}  rows")
    for label, depth, crit in (("d3 open", 3, ""), ("d3 score", 3, score),
                               ("d4 open", 4, "")):
        for start in LARGE.sample_starts()[:4]:
            q = chain_query(LARGE, start, depth, criterion=crit)
            emit_traversal.dedup_feasible = _real
            ga = await gen(conn, q)
            emit_traversal.dedup_feasible = _nodedup
            gb = await gen(conn, q)
            emit_traversal.dedup_feasible = _real
            if shape(ga.sql) == shape(gb.sql):
                print(f"{label:28s} {start:7d}  both {shape(ga.sql)} — dedup not in play", flush=True)
                continue
            try:
                ma, na = await med(conn, ga.sql)
                mb, nb = await med(conn, gb.sql)
                flag = "" if na == nb else f"  ROWS DIFFER {na}/{nb}"
                print(f"{label:28s} {start:7d} {ma:11.1f} {mb:10.1f} {mb/ma:6.2f}x  {na}{flag}", flush=True)
            except Exception as e:
                print(f"{label:28s} {start:7d}  {str(e)[:60]}", flush=True)
    await conn.close()
asyncio.run(main())
