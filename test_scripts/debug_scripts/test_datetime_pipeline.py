"""Test: run UNION+BIND delete-pattern query through V2 pipeline
specifically checking xsd:dateTime __datatype propagation."""
import asyncio
import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(name)s - %(message)s")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")


async def run_sparql_v2(space_id, sparql, sidecar_url, pool):
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

    h = os.environ.get("LOCAL_DB_HOST", "localhost")
    p = os.environ.get("LOCAL_DB_PORT", "5432")
    d = os.environ.get("LOCAL_DB_NAME", "sparql_sql_graph")
    u = os.environ.get("LOCAL_DB_USERNAME", "postgres")
    pw = os.environ.get("LOCAL_DB_PASSWORD", "")
    url = f"postgresql://{u}:{pw}@{h}:{p}/{d}"
    sidecar_url = os.environ.get("SIDECAR_URL", "http://localhost:7070")

    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)
    space_id = "space_multi_org_crud_test"

    # Find an entity that has ObjectModificationDateTime
    async with pool.acquire() as conn:
        entity_row = await conn.fetchrow(
            f"SELECT st.term_text AS subject, pt.term_text AS predicate, "
            f"ot.term_text AS object_val, ot.datatype_id "
            f"FROM {space_id}_rdf_quad q "
            f"JOIN {space_id}_term st ON q.subject_uuid = st.term_uuid "
            f"JOIN {space_id}_term pt ON q.predicate_uuid = pt.term_uuid "
            f"JOIN {space_id}_term ot ON q.object_uuid = ot.term_uuid "
            f"WHERE pt.term_text LIKE '%ObjectModificationDateTime' "
            f"LIMIT 1"
        )

    if not entity_row:
        print("No ObjectModificationDateTime found!")
        await pool.close()
        return

    entity_uri = entity_row["subject"]
    print(f"Entity: {entity_uri}")
    print(f"Predicate: {entity_row['predicate']}")
    print(f"DateTime value: {entity_row['object_val']}")
    print(f"Datatype ID: {entity_row['datatype_id']}")

    # Find graph for this entity
    async with pool.acquire() as conn:
        graph_row = await conn.fetchrow(
            f"SELECT ct.term_text AS graph_uri "
            f"FROM {space_id}_rdf_quad q "
            f"JOIN {space_id}_term st ON q.subject_uuid = st.term_uuid "
            f"JOIN {space_id}_term ct ON q.context_uuid = ct.term_uuid "
            f"WHERE st.term_text = $1 LIMIT 1", entity_uri
        )
    graph_id = graph_row["graph_uri"] if graph_row else None
    print(f"Graph: {graph_id}")

    if not graph_id:
        print("No graph found!")
        await pool.close()
        return

    # ---- Test 1: Simple BGP query for this entity's dateTime ----
    print(f"\n{'='*70}")
    print(f"  Test 1: Simple BGP — dateTime for entity")
    print(f"{'='*70}")

    sparql1 = f"""
    SELECT ?o WHERE {{
        GRAPH <{graph_id}> {{
            <{entity_uri}> <{entity_row['predicate']}> ?o .
        }}
    }}
    """
    r1 = await run_sparql_v2(space_id, sparql1, sidecar_url, pool)
    if "error" in r1:
        print(f"  Error: {r1['error']}")
    else:
        print(f"  var_map: {r1['var_map']}")
        print(f"  {len(r1['raw_rows'])} rows")
        obj_sql = None
        for vn, sn in r1["var_map"].items():
            if sn == "o":
                obj_sql = vn
                break
        if obj_sql:
            for i, row in enumerate(r1["raw_rows"]):
                val = row.get(obj_sql)
                dt = row.get(f"{obj_sql}__datatype")
                typ = row.get(f"{obj_sql}__type")
                num = row.get(f"{obj_sql}__num")
                dt_col = row.get(f"{obj_sql}__dt")
                print(f"  row[{i}]: value={str(val)[:50]!r}  type(val)={type(val).__name__}  __type={typ!r}  __datatype={dt!r}")
                print(f"           __num={num!r}  __dt={dt_col!r}  type(__dt)={type(dt_col).__name__ if dt_col else 'N/A'}")
        for i, b in enumerate(r1["bindings"]):
            obj = b.get("o", {})
            print(f"  binding[{i}]: value={obj.get('value','?')[:50]}  has_datatype={'datatype' in obj}  dt={obj.get('datatype','MISSING')}")

    # ---- Test 2: UNION+BIND delete-pattern query ----
    print(f"\n{'='*70}")
    print(f"  Test 2: UNION+BIND (exact _build_delete_quads_for_entity pattern)")
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
        print(f"  {len(r2['raw_rows'])} rows, SQL length: {len(r2['sql'])} chars")

        obj_sql = None
        for vn, sn in r2["var_map"].items():
            if sn == "object":
                obj_sql = vn
                break

        dt_ok = 0
        dt_missing = 0
        all_ok = 0
        all_missing = 0
        if obj_sql:
            for i, row in enumerate(r2["raw_rows"]):
                val = row.get(obj_sql)
                dt = row.get(f"{obj_sql}__datatype")
                typ = row.get(f"{obj_sql}__type")
                val_str = str(val) if val else ""
                is_literal = (typ == "L")
                looks_like_dt = "T" in val_str and ("+" in val_str or "Z" in val_str or val_str.count("-") >= 2)

                if is_literal and dt:
                    all_ok += 1
                elif is_literal and not dt:
                    all_missing += 1

                if is_literal and looks_like_dt:
                    if dt:
                        dt_ok += 1
                        print(f"  row[{i}]: OK  value={val_str[:50]}  dt={dt}")
                    else:
                        dt_missing += 1
                        print(f"  row[{i}]: MISSING DATATYPE  value={val_str[:50]}  __type={typ}  __datatype={dt!r}")

        # Check bindings too
        b_ok = 0
        b_missing = 0
        for b in r2["bindings"]:
            obj = b.get("object", {})
            val = obj.get("value", "")
            if obj.get("type") == "literal" and "T" in val:
                if "datatype" in obj:
                    b_ok += 1
                else:
                    b_missing += 1
                    print(f"  BINDING MISSING: {val[:60]}")

        print(f"\n  Summary:")
        print(f"    All literals: {all_ok} with datatype, {all_missing} without")
        print(f"    DateTime-like: {dt_ok} with datatype, {dt_missing} without")
        print(f"    Bindings datetime: {b_ok} with datatype, {b_missing} without")

        if dt_missing > 0 or b_missing > 0:
            print(f"\n  >>> BUG CONFIRMED: datetime literals lose __datatype <<<")
        elif dt_ok > 0:
            print(f"\n  >>> PASS: All datetime literals have correct __datatype <<<")
        else:
            print(f"\n  >>> No datetime-like literals found in UNION results <<<")

    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
