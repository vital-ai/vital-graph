#!/usr/bin/env python3
"""Debug UNION+BIND SPARQL query on sparql_sql backend.

Creates test data via client, then uses V2 pipeline directly to compare
simple vs BIND vs UNION+BIND queries.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
logging.basicConfig(level=logging.WARNING, format="%(name)s - %(message)s")
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


SPACE_ID = "sp_debug_union"
GRAPH_ID = "urn:debug_union"
ENTITY_URI = "http://example.org/debug/entity_alpha"


async def run_sparql_v2(space_id: str, sparql: str, sidecar_url: str, pool):
    """Run a SPARQL query through the full V2 pipeline, returning SQL + rows + bindings."""
    from vitalgraph.db.jena_sparql.jena_sidecar_client import AsyncSidecarClient
    from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
    from vitalgraph.db.sparql_sql.generator import generate_sql
    from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl

    client = AsyncSidecarClient(base_url=sidecar_url)
    try:
        raw = await client.compile(sparql)
    finally:
        await client.close()

    cr = map_compile_response(raw)
    if not cr.ok:
        return {"error": cr.error}

    async with pool.acquire() as conn:
        gen = await generate_sql(cr, space_id, conn=conn)
        sql = gen.sql
        var_map = gen.var_map or {}

        rows = await conn.fetch(sql)
        result_rows = [dict(r) for r in rows]

    bindings = SparqlSQLSpaceImpl._rows_to_sparql_bindings(result_rows, var_map)

    return {
        "sql": sql,
        "var_map": var_map,
        "row_count": len(result_rows),
        "bindings_count": len(bindings),
        "bindings": bindings[:5],
        "raw_rows": result_rows[:3],
    }


async def main():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient
    from vitalgraph.model.spaces_model import Space
    from ai_haley_kg_domain.model.KGEntity import KGEntity

    # --- Step 1: Create test data via client ---
    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        print("❌ Not connected")
        return

    try:
        await client.spaces.delete_space(SPACE_ID)
    except:
        pass

    space = Space(space=SPACE_ID, space_name="Debug UNION")
    await client.spaces.create_space(space)
    await client.graphs.create_graph(SPACE_ID, GRAPH_ID)

    e = KGEntity()
    e.URI = ENTITY_URI
    e.name = "Alpha"
    cr = await client.kgentities.create_kgentities(SPACE_ID, GRAPH_ID, objects=[e])
    print(f"✅ Created entity: created_count={cr.created_count}")

    # Verify it exists via client
    gr = await client.kgentities.get_kgentity(SPACE_ID, GRAPH_ID, uri=ENTITY_URI)
    print(f"✅ Get entity: is_success={gr.is_success}, objects={len(gr.objects) if gr.objects else 0}")

    await client.close()

    # --- Step 2: Connect directly to the DB and run queries via V2 pipeline ---
    import os
    import asyncpg

    db_host = os.environ.get("LOCAL_DB_HOST", "localhost")
    db_port = os.environ.get("LOCAL_DB_PORT", "5432")
    db_name = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    db_user = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    db_pass = os.environ.get("LOCAL_DB_PASSWORD", "")
    db_url = f"postgresql://{db_user}:{db_pass}@localhost:{db_port}/{db_name}"
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    sidecar_url = os.environ.get("SIDECAR_URL", "http://localhost:7070")

    queries = {
        "1_Simple": f"""SELECT ?predicate ?object WHERE {{
            GRAPH <{GRAPH_ID}> {{ <{ENTITY_URI}> ?predicate ?object . }}
        }}""",

        "2_BIND_only": f"""SELECT ?subject ?predicate ?object WHERE {{
            GRAPH <{GRAPH_ID}> {{
                <{ENTITY_URI}> ?predicate ?object .
                BIND(<{ENTITY_URI}> AS ?subject)
            }}
        }}""",

        "3_UNION_BIND": f"""SELECT DISTINCT ?subject ?predicate ?object WHERE {{
            GRAPH <{GRAPH_ID}> {{
                {{
                    <{ENTITY_URI}> ?predicate ?object .
                    BIND(<{ENTITY_URI}> AS ?subject)
                }}
                UNION
                {{
                    ?subject <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{ENTITY_URI}> .
                    ?subject ?predicate ?object .
                }}
            }}
        }}""",
    }

    for label, sparql in queries.items():
        print(f"\n{'='*70}")
        print(f"  {label}")
        print(f"{'='*70}")
        result = await run_sparql_v2(SPACE_ID, sparql, sidecar_url, pool)

        if "error" in result:
            print(f"  ❌ Error: {result['error']}")
            continue

        print(f"  var_map: {result['var_map']}")
        print(f"  SQL rows: {result['row_count']}")
        print(f"  bindings: {result['bindings_count']}")

        if result['raw_rows']:
            print(f"  raw_rows[0] keys: {list(result['raw_rows'][0].keys())}")
            for i, row in enumerate(result['raw_rows'][:2]):
                # Print just the text columns (not uuid/type/lang etc)
                text_cols = {k: v for k, v in row.items()
                             if not any(k.endswith(s) for s in ('__type', '__uuid', '__lang', '__datatype', '__num', '__bool', '__dt'))}
                print(f"  raw_rows[{i}] text: {text_cols}")

        for i, b in enumerate(result['bindings'][:3]):
            print(f"  binding[{i}]: {b}")

    # Cleanup
    try:
        client2 = VitalGraphClient()
        await client2.open()
        await client2.spaces.delete_space(SPACE_ID)
        await client2.close()
    except:
        pass
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
