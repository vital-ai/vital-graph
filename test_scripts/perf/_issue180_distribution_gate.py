#!/usr/bin/env python3
"""issues/180: does distributing Join over Union still cost 2x on ORDER BY + LIMIT?

180's 2.0000x (31.2M vs 15.6M buffers) was measured BEFORE `merge_bgp_joins`
joined the rewrite (35cf5616), which then measured 362x on the same query. So
the open cost may no longer exist. This runs the 178 reference query through the
real generator with distribution ON and OFF (OFF = the rewrite patched to the
identity, so the merge sees what it saw before), in four shapes:

    full      no modifiers
    top10     ORDER BY ?entity LIMIT 10     the shape 180 measured
    top10f    ORDER BY ?frame  LIMIT 10     order on a C-side variable
    page      LIMIT 10 OFFSET 20            synthesized stable-paging order

Reports rows (a multiset digest, so ON and OFF must agree), buffers and ms from
EXPLAIN (ANALYZE, BUFFERS), 5 runs per cell, alternating ON/OFF.

Usage:  python test_scripts/perf/_issue180_distribution_gate.py
"""
import asyncio
import hashlib
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

SPACE = os.environ.get("SPACE", "wordnet_frames")
SIDECAR = os.environ.get("SIDECAR_URL", "http://localhost:7071")
DB = {"host": "localhost", "port": 5433, "user": "postgres",
      "password": "testpass", "database": "sparql_sql_graph"}
RUNS = int(os.environ.get("RUNS", "5"))

KG = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"

BODY = f"""
SELECT ?entity ?frame ?sourceSlot ?destinationSlot ?sourceSlotEntity ?destinationSlotEntity
WHERE {{
  GRAPH <urn:wordnet_frames> {{
    {{
      ?sourceSlotEntity a <{KG}KGEntity> .
      ?sourceSlotEntity <{KG}hasKGraphDescription> ?description1 .
      FILTER(CONTAINS(LCASE(STR(?description1)), "happy"))
      BIND(?sourceSlotEntity AS ?entity)
    }}
    UNION
    {{
      ?destinationSlotEntity a <{KG}KGEntity> .
      ?destinationSlotEntity <{KG}hasKGraphDescription> ?description2 .
      FILTER(CONTAINS(LCASE(STR(?description2)), "happy"))
      BIND(?destinationSlotEntity AS ?entity)
    }}
    ?frame a <{KG}KGFrame> .
    ?sourceEdge a <{KG}Edge_hasKGSlot> .
    ?sourceEdge <{VC}hasEdgeSource> ?frame .
    ?sourceEdge <{VC}hasEdgeDestination> ?sourceSlot .
    ?sourceSlot a <{KG}KGEntitySlot> .
    ?sourceSlot <{KG}hasEntitySlotValue> ?sourceSlotEntity .
    ?sourceSlot <{KG}hasKGSlotType> <urn:hasSourceEntity> .
    ?destinationEdge a <{KG}Edge_hasKGSlot> .
    ?destinationEdge <{VC}hasEdgeSource> ?frame .
    ?destinationEdge <{VC}hasEdgeDestination> ?destinationSlot .
    ?destinationSlot a <{KG}KGEntitySlot> .
    ?destinationSlot <{KG}hasEntitySlotValue> ?destinationSlotEntity .
    ?destinationSlot <{KG}hasKGSlotType> <urn:hasDestinationEntity> .
  }}
}}
"""
SHAPES = {
    "full": "",
    "top10": "ORDER BY ?entity LIMIT 10",
    "top10f": "ORDER BY ?frame LIMIT 10",
    "page": "LIMIT 10 OFFSET 20",
}


def _walk(node, key):
    if isinstance(node, dict):
        if key in node:
            yield node[key]
        for v in node.values():
            yield from _walk(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)


async def generate(cr, distribute):
    from vitalgraph.db.sparql_sql import db_provider as db
    from vitalgraph.db.sparql_sql import rewrite_distribute_union as rdu
    from vitalgraph.db.sparql_sql.generator import generate_sql
    saved = rdu.distribute_join_over_union
    if not distribute:
        rdu.distribute_join_over_union = lambda plan, aliases: plan
    try:
        async with db.get_connection(DB) as conn:
            return await generate_sql(cr, SPACE, conn_params=DB, conn=conn)
    finally:
        rdu.distribute_join_over_union = saved


async def run_once(gen):
    from vitalgraph.db.sparql_sql import db_provider as db
    async with db.get_connection(DB) as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL statement_timeout = '300s'")
            if gen.needs_ordered_scan:          # fence exactly as the executor does
                await conn.execute("SET LOCAL enable_sort = off")
            plan = await conn.fetchval("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + gen.sql)
            rows = await conn.fetch(gen.sql)
    plan = json.loads(plan)[0]
    top = plan["Plan"]
    buffers = top.get("Shared Hit Blocks", 0) + top.get("Shared Read Blocks", 0)
    digest = hashlib.sha1("\n".join(sorted(repr(tuple(r.values())) for r in rows)).encode()).hexdigest()[:10]
    return dict(ms=plan["Execution Time"], buffers=buffers, rows=len(rows), digest=digest)


async def main():
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph_sparql_sql_dev.jena_sparql_orchestrator import SparqlOrchestrator
    orch = SparqlOrchestrator(space_id=SPACE, sidecar_url=SIDECAR, db_params=DB)
    await orch._ensure_db_provider()

    client = AsyncSidecarClient(base_url=SIDECAR)
    print(f"{'shape':8} {'dist':4} {'rows':>5} {'digest':10} {'buffers min/med':>22} {'ms min/med/max':>24} nos")
    for shape, mods in SHAPES.items():
        cr = map_compile_response(await client.compile(BODY + mods))
        gens = {d: await generate(cr, d) for d in (True, False)}
        res = {True: [], False: []}
        for i in range(RUNS):
            for d in ((True, False) if i % 2 == 0 else (False, True)):
                res[d].append(await run_once(gens[d]))
        for d in (True, False):
            r = res[d]
            ms = sorted(x["ms"] for x in r)
            bf = sorted(x["buffers"] for x in r)
            print(f"{shape:8} {'ON' if d else 'OFF':4} {r[0]['rows']:5} {r[0]['digest']:10} "
                  f"{bf[0]:>10,}/{statistics.median(bf):>10,.0f} "
                  f"{ms[0]:7.1f}/{statistics.median(ms):7.1f}/{ms[-1]:7.1f} "
                  f"{gens[d].needs_ordered_scan}")
        sql_on, sql_off = gens[True].sql, gens[False].sql
        print(f"{'':8} null-tolerant preds ON={sql_on.count('IS NULL OR')} OFF={sql_off.count('IS NULL OR')}")
    await client.close()


asyncio.run(main())
