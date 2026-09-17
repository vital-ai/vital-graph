#!/usr/bin/env python3
"""issues/178: does rewrite_edge_table empty a PROJECTED edge variable?

`{space}_edge` HAS an edge_uuid column, so unlike frame_entity it could rebind
?sourceEdge. This decides whether the NULL seen in the CONSTRUCT's SQL is the
same defect or an unrelated projection choice.

Usage:  python test_scripts/debug/_issue178_edgevar.py
"""
import asyncio, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

SPACE = os.environ.get("SPACE", "wordnet_frames")
SIDECAR = os.environ.get("SIDECAR_URL", "http://localhost:7071")
DB = {"host": "localhost", "port": 5432, "user": "postgres",
      "password": "", "database": "sparql_sql_graph"}

KG = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"

# Projects the edge variable itself — the case the CONSTRUCT never exercised.
SPARQL = f"""
SELECT ?sourceEdge ?frame ?sourceSlot WHERE {{
  GRAPH <urn:wordnet_frames> {{
    ?sourceEdge <{VC}hasEdgeSource> ?frame .
    ?sourceEdge <{VC}hasEdgeDestination> ?sourceSlot .
    ?sourceSlot <{KG}hasKGSlotType> <urn:hasSourceEntity> .
  }}
}}
ORDER BY ?sourceEdge
LIMIT 200
"""

VARS = ["sourceEdge", "frame", "sourceSlot"]


async def run(label, disable_edge_rewrite):
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql import db_provider as db
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql import rewrite_edge_table as ret

    saved = ret.rewrite_edge_table
    if disable_edge_rewrite:
        ret.rewrite_edge_table = lambda plan, a, s: plan
    try:
        client = AsyncSidecarClient(base_url=SIDECAR)
        cr = map_compile_response(await client.compile(SPARQL))
        await client.close()
        async with db.get_connection(DB) as conn:
            gen = await generate_sql(cr, SPACE, conn_params=DB, conn=conn)
            if not gen.ok:
                print(f"{label}: GENERATION FAILED: {gen.error}")
                return None
            vm = gen.var_map or {}
            ids_for = {}
            for vid, name in vm.items():
                ids_for.setdefault(name, []).append(vid)
            hard_null = [f"{vid}({vm[vid]})" for vid in vm
                         if f"NULL AS {vid}," in gen.sql
                         or gen.sql.endswith(f"NULL AS {vid}")]
            print(f"{label}: sparql_vars={sorted(gen.sparql_vars or [])}")
            print(f"{label}: edge x{gen.sql.count(SPACE+'_edge')}, "
                  f"rdf_quad x{gen.sql.count(SPACE+'_rdf_quad')}")
            print(f"{label}: hard-NULLed in SQL: {hard_null or 'none'}")
            t0 = time.monotonic()
            rows = await conn.fetch(gen.sql)
            ms = (time.monotonic() - t0) * 1000
        cols = set(rows[0].keys()) if rows else set()

        def val(r, name):
            for vid in ids_for.get(name, []):
                if vid in cols and r[vid] is not None:
                    return r[vid]
            return None

        nulls = {v: sum(1 for r in rows if val(r, v) is None) for v in VARS}
        out = set(tuple(val(r, v) for v in VARS) for r in rows)
        print(f"{label}: {len(rows)} rows, {ms:.0f} ms")
        print(f"{label}: NULL counts {nulls}")
        return out
    finally:
        ret.rewrite_edge_table = saved


async def main():
    from vitalgraph_sparql_sql_dev.jena_sparql_orchestrator import SparqlOrchestrator
    orch = SparqlOrchestrator(space_id=SPACE, sidecar_url=SIDECAR, db_params=DB)
    await orch._ensure_db_provider()

    print("=== AS SHIPPED (edge rewrite on) ===")
    a = await run("shipped", False)
    print("\n=== EDGE REWRITE DISABLED ===")
    b = await run("plain  ", True)
    if a is None or b is None:
        return
    print("\n=== DIFF ===")
    print(f"  shipped only : {len(a - b)}   plain only : {len(b - a)}   in both : {len(a & b)}")

asyncio.run(main())
