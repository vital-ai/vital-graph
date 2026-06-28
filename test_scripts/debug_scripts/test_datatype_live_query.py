"""Live test: run the exact UNION+BIND query from _build_delete_quads_for_entity
through the V2 SQL pipeline and check if __datatype is populated in raw rows."""
import asyncio
import sys
import os
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(name)s - %(message)s")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


async def run_sparql_v2(space_id, sparql, sidecar_url, pool):
    """Run SPARQL through V2 pipeline, returning SQL + raw rows + bindings."""
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
        "raw_rows": result_rows,
        "bindings": bindings,
    }


async def main():
    import asyncpg

    db_host = os.environ.get("LOCAL_DB_HOST", "localhost")
    db_port = os.environ.get("LOCAL_DB_PORT", "5432")
    db_name = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    db_user = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    db_pass = os.environ.get("LOCAL_DB_PASSWORD", "")
    db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    sidecar_url = os.environ.get("SIDECAR_URL", "http://localhost:7070")

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

    # Find a space with data (tables are {space_id}_rdf_quad in public schema)
    async with pool.acquire() as conn:
        tabs = await conn.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE '%_rdf_quad' "
            "ORDER BY table_name LIMIT 10"
        )
    space_ids = [r["table_name"].replace("_rdf_quad", "") for r in tabs]
    print(f"Spaces: {space_ids}")

    if not space_ids:
        print("No spaces found.")
        await pool.close()
        return

    # Try each space until we find one with datetime data
    space_id = None
    for sid in space_ids:
        async with pool.acquire() as conn:
            cnt = await conn.fetchval(
                f"SELECT COUNT(*) FROM {sid}_rdf_quad LIMIT 1"
            )
        if cnt and cnt > 0:
            print(f"  {sid}: {cnt} quads")
            if space_id is None:
                space_id = sid
    if space_id is None:
        print("No non-empty spaces found.")
        await pool.close()
        return
    print(f"Using space: {space_id}")

    # --- Test 1: Simple query for datetime-typed literals ---
    print(f"\n{'='*70}")
    print(f"  Test 1: Simple dateTime query on {space_id}")
    print(f"{'='*70}")

    # First, find typed literals using a direct SQL check
    async with pool.acquire() as conn:
        dt_rows = await conn.fetch(
            f"SELECT datatype_id, datatype_uri FROM {space_id}_datatype ORDER BY datatype_id LIMIT 20"
        )
    if dt_rows:
        print(f"  Datatype table ({len(dt_rows)} entries):")
        for r in dt_rows:
            print(f"    {r['datatype_id']}: {r['datatype_uri']}")
    else:
        print("  No datatype table entries!")

    # Find a predicate that has typed literals
    async with pool.acquire() as conn:
        typed_rows = await conn.fetch(
            f"SELECT t.term_text, t.datatype_id, d.datatype_uri, COUNT(*) as cnt "
            f"FROM {space_id}_rdf_quad q "
            f"JOIN {space_id}_term t ON q.object_uuid = t.term_uuid "
            f"LEFT JOIN {space_id}_datatype d ON t.datatype_id = d.datatype_id "
            f"WHERE t.term_type = 'L' AND t.datatype_id IS NOT NULL "
            f"GROUP BY t.term_text, t.datatype_id, d.datatype_uri "
            f"LIMIT 5"
        )
    if typed_rows:
        print(f"\n  Typed literals found:")
        for r in typed_rows:
            print(f"    value={str(r['term_text'])[:50]}  dt_id={r['datatype_id']}  dt_uri={r['datatype_uri']}")
    else:
        print("  No typed literals found!")

    # Use a general query for typed literals
    sparql1 = f"""
    SELECT ?s ?p ?o WHERE {{
        ?s ?p ?o .
        FILTER(isLiteral(?o) && datatype(?o) != <http://www.w3.org/2001/XMLSchema#string>)
    }} LIMIT 5
    """
    r1 = await run_sparql_v2(space_id, sparql1, sidecar_url, pool)
    if "error" in r1:
        print(f"  Error: {r1['error']}")
    else:
        print(f"  var_map: {r1['var_map']}")
        print(f"  {len(r1['raw_rows'])} rows")
        # Check raw rows for __datatype
        obj_sql = None
        for vn, sn in r1["var_map"].items():
            if sn == "o":
                obj_sql = vn
                break
        if obj_sql and r1["raw_rows"]:
            for i, row in enumerate(r1["raw_rows"][:5]):
                val = row.get(obj_sql)
                dt = row.get(f"{obj_sql}__datatype")
                typ = row.get(f"{obj_sql}__type")
                print(f"  row[{i}]: value={str(val)[:50]!r}  __type={typ!r}  __datatype={dt!r}")
        # Check bindings
        for i, b in enumerate(r1["bindings"][:5]):
            obj = b.get("o", {})
            print(f"  binding[{i}]: value={obj.get('value','?')[:50]}  "
                  f"has_datatype={'datatype' in obj}  "
                  f"dt={obj.get('datatype','MISSING')}")

    # --- Test 2: UNION+BIND query (the exact pattern from _build_delete_quads_for_entity) ---
    # Need an entity URI first
    entity_uri = None
    graph_id = None
    if r1.get("bindings"):
        entity_uri = r1["bindings"][0].get("s", {}).get("value")
    if entity_uri:
        # Find graph for this entity
        sparql_g = f"""
        SELECT ?g WHERE {{
            GRAPH ?g {{ <{entity_uri}> ?p ?o . }}
        }} LIMIT 1
        """
        rg = await run_sparql_v2(space_id, sparql_g, sidecar_url, pool)
        if rg.get("bindings"):
            graph_id = rg["bindings"][0].get("g", {}).get("value")

    if entity_uri and graph_id:
        print(f"\n{'='*70}")
        print(f"  Test 2: UNION+BIND delete-pattern query")
        print(f"  entity: {entity_uri[:70]}")
        print(f"  graph:  {graph_id[:70]}")
        print(f"{'='*70}")

        sparql2 = f"""
        SELECT DISTINCT ?subject ?predicate ?object WHERE {{
            GRAPH <{graph_id}> {{
                {{
                    <{entity_uri}> ?predicate ?object .
                    BIND(<{entity_uri}> AS ?subject)
                }}
                UNION
                {{
                    ?subject <http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI> <{entity_uri}> .
                    ?subject ?predicate ?object .
                }}
            }}
        }}
        """
        r2 = await run_sparql_v2(space_id, sparql2, sidecar_url, pool)
        if "error" in r2:
            print(f"  Error: {r2['error']}")
        else:
            print(f"  var_map: {r2['var_map']}")
            print(f"  {len(r2['raw_rows'])} rows")
            print(f"  Generated SQL length: {len(r2['sql'])} chars")

            # Find the object column
            obj_sql = None
            for vn, sn in r2["var_map"].items():
                if sn == "object":
                    obj_sql = vn
                    break

            dt_ok = 0
            dt_missing = 0
            dt_na = 0
            if obj_sql:
                for i, row in enumerate(r2["raw_rows"]):
                    val = row.get(obj_sql)
                    dt = row.get(f"{obj_sql}__datatype")
                    typ = row.get(f"{obj_sql}__type")
                    is_literal = (typ == "L")
                    val_str = str(val) if val else ""
                    looks_like_dt = "T" in val_str and ("+" in val_str or "Z" in val_str)

                    if is_literal and looks_like_dt:
                        if dt:
                            dt_ok += 1
                            if i < 5:
                                print(f"  row[{i}]: OK  value={val_str[:50]}  dt={dt}")
                        else:
                            dt_missing += 1
                            print(f"  row[{i}]: MISSING DATATYPE  value={val_str[:50]}  dt={dt!r}")
                    else:
                        dt_na += 1

            # Also check bindings
            b_ok = 0
            b_missing = 0
            for b in r2["bindings"]:
                obj = b.get("object", {})
                val = obj.get("value", "")
                if "T" in val and ("+" in val or "Z" in val):
                    if "datatype" in obj:
                        b_ok += 1
                    else:
                        b_missing += 1
                        print(f"  BINDING MISSING DATATYPE: {val[:60]}")

            print(f"\n  Raw rows: {dt_ok} datetime with dt, {dt_missing} datetime without dt, {dt_na} non-datetime")
            print(f"  Bindings: {b_ok} datetime with dt, {b_missing} datetime without dt")

            if dt_missing > 0 or b_missing > 0:
                print(f"\n  >>> BUG CONFIRMED: UNION query drops __datatype for datetime literals <<<")
            elif dt_ok > 0:
                print(f"\n  >>> Pipeline works correctly for this query — __datatype is populated <<<")
            else:
                print(f"\n  >>> No datetime literals found in results <<<")
    else:
        print("\n  Skipping Test 2: no entity or graph found")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
