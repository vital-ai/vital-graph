#!/usr/bin/env python3
"""issues/178 defect 1: are the slot variables joined-but-unprojected, or gone?

Mirrors the server's own path (sidecar compile -> generate_sql) so the SQL is
the same SQL, then reports which of the CONSTRUCT template's six variables
survive into `var_map`.

Usage:  python test_scripts/debug/_issue178_varmap.py
"""
import asyncio, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql_dev.jena_sparql_orchestrator import SparqlOrchestrator

SPACE = os.environ.get("SPACE", "wordnet_frames")
SIDECAR = os.environ.get("SIDECAR_URL", "http://localhost:7071")
DB = {"host": "localhost", "port": 5432, "user": "postgres",
      "password": "", "database": "sparql_sql_graph"}

QUERY = open(os.path.join(
    os.path.dirname(__file__), '..', '..',
    'vitalgraph_sparql_sql_dev/sql_reference/happy_frame_query.sparql')).read()

TEMPLATE_VARS = ["entity", "frame", "sourceSlot", "destinationSlot",
                 "sourceSlotEntity", "destinationSlotEntity"]


async def main():
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql import db_provider as db
    from vitalgraph.db.sparql_sql.generator import generate_sql

    orch = SparqlOrchestrator(space_id=SPACE, sidecar_url=SIDECAR, db_params=DB)
    await orch._ensure_db_provider()

    client = AsyncSidecarClient(base_url=SIDECAR)
    raw = await client.compile(QUERY)
    cr = map_compile_response(raw)
    print("compile ok:", cr.ok, "| form:", getattr(cr.meta, 'sparql_form', None))

    import time as _t
    async with db.get_connection(DB) as conn:
        _t0=_t.monotonic()
        gen = await generate_sql(cr, SPACE, conn_params=DB, conn=conn)
        _gen_ms=(_t.monotonic()-_t0)*1000
        print(f"\nGENERATION: {_gen_ms:.0f} ms (cold process, empty _CACHE)")
        _t1=_t.monotonic()
        gen2 = await generate_sql(cr, SPACE, conn_params=DB, conn=conn)
        print(f"GENERATION (2nd, same process): {(_t.monotonic()-_t1)*1000:.0f} ms")

    print("gen ok:", gen.ok)
    print("sparql_vars:", gen.sparql_vars)
    vm = gen.var_map or {}
    print("\nvar_map:", {k: vm[k] for k in sorted(vm)})
    print("\nCONSTRUCT template variables:")
    for v in TEMPLATE_VARS:
        print(f"  {v:24s} {'PROJECTED -> ' + str(vm[v]) if v in vm else 'ABSENT from var_map'}")

    sql = gen.sql or ""
    print(f"\nSQL {len(sql)} chars")
    for t in (f"{SPACE}_frame_entity", f"{SPACE}_edge", f"{SPACE}_rdf_quad"):
        print(f"  {t:34s} x{sql.count(t)}")

    out = os.path.join(os.path.dirname(__file__), '_issue178_generated.sql')
    open(out, 'w').write(sql)
    print("SQL written to", out)
    await client.close()

asyncio.run(main())
