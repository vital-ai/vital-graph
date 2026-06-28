#!/usr/bin/env python3
"""
kgquery_perf_bench.py — Benchmark KGQuery SPARQL patterns via v2 pipeline.

Runs the problematic R1, R4, R8 relation queries (and optionally others)
through: Jena sidecar → v2 SQL generation → PostgreSQL execution,
printing timing breakdowns and EXPLAIN ANALYZE for each.

Requires:
  1. kgquery_perf space populated (run kgquery_perf_setup.py first)
  2. Jena sidecar running (default http://localhost:7070)

Usage:
    python vitalgraph_sparql_sql/scripts/kgquery_perf_bench.py
    python vitalgraph_sparql_sql/scripts/kgquery_perf_bench.py --query R4
    python vitalgraph_sparql_sql/scripts/kgquery_perf_bench.py --query all --explain
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.db.jena_sparql.jena_sidecar_client import SidecarClient
from vitalgraph.db.jena_sparql.jena_ast_mapper import map_compile_response
from vitalgraph.db.sparql_sql.generator import generate_sql as v2_generate, warm_stats_cache, _stats_cache
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import SparqlSQLSpaceImpl
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql import db_provider
from vitalgraph_sparql_sql import db
from vitalgraph_sparql_sql.db import DevDbImpl

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)

SPACE_ID = "kgquery_perf"
GRAPH_URI = "urn:kgquery_perf"

# ===================================================================
# Hard-coded SPARQL queries (from mv_to_maintained_table_plan.md,
# adjusted: GRAPH <urn:sql_kgqueries> → GRAPH <urn:kgquery_perf>)
# ===================================================================

QUERIES = {}

# R1: All MakesProduct relations (simple, no frame filter)
# Edge pairs: 1
QUERIES["R1"] = f"""
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {{
    GRAPH <{GRAPH_URI}> {{
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type {{ <http://vital.ai/test/kgtype/MakesProductRelation> }}
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        FILTER(?source_entity != ?destination_entity)
    }}
}}
ORDER BY ?source_entity ?destination_entity
"""

# R4: MakesProduct from Technology companies (1 frame + 1 slot filter)
# Edge pairs: 3 (relation, frame, slot)
QUERIES["R4"] = f"""
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {{
    GRAPH <{GRAPH_URI}> {{
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type {{ <http://vital.ai/test/kgtype/MakesProductRelation> }}
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        ?source_frame_edge_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?source_frame_edge_0 vital:hasEdgeSource ?source_entity .
        ?source_frame_edge_0 vital:hasEdgeDestination ?source_frame_0 .
        ?source_frame_0 haley:hasKGFrameType <http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame> .
        ?source_slot_edge_0_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
        ?source_slot_edge_0_0 vital:hasEdgeSource ?source_frame_0 .
        ?source_slot_edge_0_0 vital:hasEdgeDestination ?source_slot_0_0 .
        ?source_slot_0_0 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#IndustrySlot> .
        ?source_slot_0_0 haley:hasTextSlotValue ?source_slot_value_0_0 .
        FILTER(?source_slot_value_0_0 = 'Technology')
        FILTER(?source_entity != ?destination_entity)
    }}
}}
ORDER BY ?source_entity ?destination_entity
"""

# R8: MakesProduct from large Tech companies (industry + employee filter)
# Edge pairs: 4 (relation, frame, industry slot, employee slot)
QUERIES["R8"] = f"""
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {{
    GRAPH <{GRAPH_URI}> {{
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type {{ <http://vital.ai/test/kgtype/MakesProductRelation> }}
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        ?source_frame_edge_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?source_frame_edge_0 vital:hasEdgeSource ?source_entity .
        ?source_frame_edge_0 vital:hasEdgeDestination ?source_frame_0 .
        ?source_frame_0 haley:hasKGFrameType <http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame> .
        ?source_slot_edge_0_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
        ?source_slot_edge_0_0 vital:hasEdgeSource ?source_frame_0 .
        ?source_slot_edge_0_0 vital:hasEdgeDestination ?source_slot_0_0 .
        ?source_slot_0_0 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#IndustrySlot> .
        ?source_slot_0_0 haley:hasTextSlotValue ?source_slot_value_0_0 .
        FILTER(?source_slot_value_0_0 = 'Technology')
        ?source_slot_edge_0_1 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
        ?source_slot_edge_0_1 vital:hasEdgeSource ?source_frame_0 .
        ?source_slot_edge_0_1 vital:hasEdgeDestination ?source_slot_0_1 .
        ?source_slot_0_1 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#EmployeeCountSlot> .
        ?source_slot_0_1 haley:hasIntegerSlotValue ?source_slot_value_0_1 .
        FILTER(?source_slot_value_0_1 >= 500)
        FILTER(?source_entity != ?destination_entity)
    }}
}}
ORDER BY ?source_entity ?destination_entity
"""

# R3: All CompetitorOf relations (simple)
# Edge pairs: 1
QUERIES["R3"] = f"""
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {{
    GRAPH <{GRAPH_URI}> {{
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        VALUES ?relation_type {{ <http://vital.ai/test/kgtype/CompetitorOfRelation> }}
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        FILTER(?source_entity != ?destination_entity)
    }}
}}
ORDER BY ?source_entity ?destination_entity
"""

# R5: Relations from large companies (employee >= 500, any relation type)
# Edge pairs: 3 (relation, frame, employee slot)
QUERIES["R5"] = f"""
PREFIX haley: <http://vital.ai/ontology/haley-ai-kg#>
PREFIX vital: <http://vital.ai/ontology/vital-core#>

SELECT DISTINCT ?source_entity ?destination_entity ?relation_edge ?relation_type
WHERE {{
    GRAPH <{GRAPH_URI}> {{
        ?source_entity vital:vitaltype ?source_vitaltype .
        ?relation_edge vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGRelation> .
        ?relation_edge vital:hasEdgeSource ?source_entity .
        ?relation_edge vital:hasEdgeDestination ?destination_entity .
        ?relation_edge haley:hasKGRelationType ?relation_type .
        ?destination_entity vital:vitaltype ?dest_vitaltype .
        ?source_frame_edge_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasEntityKGFrame> .
        ?source_frame_edge_0 vital:hasEdgeSource ?source_entity .
        ?source_frame_edge_0 vital:hasEdgeDestination ?source_frame_0 .
        ?source_frame_0 haley:hasKGFrameType <http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame> .
        ?source_slot_edge_0_0 vital:vitaltype <http://vital.ai/ontology/haley-ai-kg#Edge_hasKGSlot> .
        ?source_slot_edge_0_0 vital:hasEdgeSource ?source_frame_0 .
        ?source_slot_edge_0_0 vital:hasEdgeDestination ?source_slot_0_0 .
        ?source_slot_0_0 haley:hasKGSlotType <http://vital.ai/ontology/haley-ai-kg#EmployeeCountSlot> .
        ?source_slot_0_0 haley:hasIntegerSlotValue ?source_slot_value_0_0 .
        FILTER(?source_slot_value_0_0 >= 500)
        FILTER(?source_entity != ?destination_entity)
    }}
}}
ORDER BY ?source_entity ?destination_entity
"""

# ===================================================================
# Formatting helpers
# ===================================================================

def _format_sql(sql: str) -> str:
    sql = re.sub(r'\s+', ' ', sql.strip())
    for kw in ['FROM', 'JOIN', 'LEFT JOIN', 'WHERE', 'GROUP BY',
               'ORDER BY', 'LIMIT', 'ON ', 'AND ']:
        sql = sql.replace(f' {kw}', f'\n  {kw}')
    sql = sql.replace('WITH ', 'WITH\n  ')
    sql = sql.replace(') SELECT ', ')\nSELECT ')
    return sql


# ===================================================================
# Run a single query — direct v2 pipeline (benchmark default)
# ===================================================================

async def _run_query(label: str, sparql: str, sidecar: SidecarClient,
                     show_explain: bool = False, show_sql: bool = False,
                     save_dir: str = None) -> dict:
    """Compile → generate → execute → EXPLAIN ANALYZE one SPARQL query."""
    print(f"\n{'─' * 70}")
    print(f"  {label}")
    print(f"{'─' * 70}")

    # 1. Compile via sidecar
    t0 = time.monotonic()
    raw_json = sidecar.compile(sparql)
    sidecar_ms = (time.monotonic() - t0) * 1000

    cr = map_compile_response(raw_json)
    if not cr.ok:
        print(f"  ❌ Sidecar error: {cr.error}")
        return {"label": label, "error": cr.error}

    async with db.get_connection() as conn:
        # 2. Generate SQL
        t0 = time.monotonic()
        gen = await v2_generate(cr, SPACE_ID, conn=conn)
        gen_ms = (time.monotonic() - t0) * 1000

        sql = gen.sql
        var_map = gen.var_map or {}

        # MV usage detection
        mv_count = sql.count('_edge') + sql.count('_frame_entity')
        quad_count_sql = sql.count('_rdf_quad')
        print(f"\n  SQL ({len(sql)} chars, {quad_count_sql} quad refs, {mv_count} MV refs)")

        if save_dir:
            safe_label = label.split(':')[0].strip()
            sql_path = os.path.join(save_dir, f"{safe_label}.sql")
            with open(sql_path, 'w') as f:
                f.write(_format_sql(sql))
            print(f"  \u2192 SQL written to {sql_path}")
        elif show_sql:
            print(_format_sql(sql))

        # 3. Execute
        t0 = time.monotonic()
        rows = await db.execute_query(sql, conn=conn)
        exec_ms = (time.monotonic() - t0) * 1000

        # 4. EXPLAIN ANALYZE
        explain_rows = []
        try:
            raw = await db.execute_query(f"EXPLAIN ANALYZE {sql}", conn=conn)
            explain_rows = [list(r.values())[0] for r in raw]
        except Exception as e:
            explain_rows = [f"EXPLAIN failed: {e}"]

    total_ms = sidecar_ms + gen_ms + exec_ms

    # Timing summary
    print(f"\n  {'Metric':<20} {'Value':>12}")
    print(f"  {'─' * 34}")
    print(f"  {'Rows':<20} {len(rows):>12}")
    print(f"  {'Sidecar':<20} {sidecar_ms:>11.0f}ms")
    print(f"  {'Generate (v2)':<20} {gen_ms:>11.0f}ms")
    print(f"  {'Execute':<20} {exec_ms:>11.0f}ms")
    print(f"  {'Total':<20} {total_ms:>11.0f}ms")
    print(f"  {'SQL chars':<20} {len(sql):>12}")
    print(f"  {'─' * 34}")

    if save_dir:
        safe_label = label.split(':')[0].strip()
        explain_path = os.path.join(save_dir, f"{safe_label}_explain.txt")
        with open(explain_path, 'w') as f:
            for line in explain_rows:
                f.write(line + '\n')
        print(f"  \u2192 EXPLAIN written to {explain_path}")
    elif show_explain:
        print(f"\n  EXPLAIN ANALYZE:")
        print(f"  {'─' * 66}")
        for line in explain_rows:
            print(f"  {line}")

    # Remap columns to SPARQL variable names for display
    remap = {opaque: sparql_name.lower() for opaque, sparql_name in var_map.items()}
    remapped = [{remap.get(k, k): v for k, v in row.items()} for row in rows]

    # Show first few rows
    if remapped:
        print(f"\n  Sample rows (first {min(5, len(remapped))}):")
        for row in remapped[:5]:
            parts = [f"{k}={v}" for k, v in row.items() if v is not None]
            print(f"    {', '.join(parts)}")

    return {
        "label": label,
        "rows": len(rows),
        "sidecar_ms": sidecar_ms,
        "gen_ms": gen_ms,
        "exec_ms": exec_ms,
        "total_ms": total_ms,
        "sql_chars": len(sql),
        "explain": explain_rows,
    }


# ===================================================================
# Run a single query — full server pipeline (execute_sparql_query)
# Matches the exact code path in SparqlSQLSpaceImpl
# ===================================================================

async def _run_query_pipeline(label: str, sparql: str,
                               space_impl: SparqlSQLSpaceImpl) -> dict:
    """Run query through SparqlSQLSpaceImpl.execute_sparql_query() — same as server."""
    print(f"\n{'─' * 70}")
    print(f"  {label}  [pipeline mode]")
    print(f"{'─' * 70}")

    t0 = time.monotonic()
    result = await space_impl.execute_sparql_query(SPACE_ID, sparql)
    total_ms = (time.monotonic() - t0) * 1000

    bindings = result.get('results', {}).get('bindings', [])
    sql = result.get('sql', '')
    row_count = len(bindings)

    print(f"\n  {'Metric':<20} {'Value':>12}")
    print(f"  {'─' * 34}")
    print(f"  {'Rows':<20} {row_count:>12}")
    print(f"  {'Total (pipeline)':<20} {total_ms:>11.0f}ms")
    print(f"  {'SQL chars':<20} {len(sql):>12}")
    print(f"  {'─' * 34}")

    if bindings:
        print(f"\n  Sample rows (first {min(3, len(bindings))}):")
        for b in bindings[:3]:
            parts = [f"{k}={v.get('value','')}" for k, v in b.items() if v]
            print(f"    {', '.join(parts)}")

    return {
        "label": label,
        "rows": row_count,
        "total_ms": total_ms,
        "sql_chars": len(sql),
    }


# ===================================================================
# Main
# ===================================================================

async def _fresh_setup(run_analyze: bool = False):
    """Drop, recreate, and reload space. Optionally run ANALYZE. Returns quad count."""
    from vitalgraph_sparql_sql.scripts.kgquery_perf_setup import (
        build_all_objects, objects_to_quads, GRAPH_URI,
    )
    from vitalgraph.db.sparql_sql import db_provider

    pool = await db.get_pool()
    async with pool.acquire() as conn:
        if await SparqlSQLSchema.space_tables_exist(conn, SPACE_ID):
            await SparqlSQLSchema.drop_space(conn, SPACE_ID)
        await SparqlSQLSchema.create_space(conn, SPACE_ID)

    all_objects, *_ = build_all_objects()
    quads = objects_to_quads(all_objects, GRAPH_URI)

    dev = db.DevDbImpl()
    await dev.connect()

    # Configure db_provider so edge table / frame_entity table work
    db_provider.configure(dev)

    pg_cfg = db.get_connection_params()
    space_impl = SparqlSQLSpaceImpl(pg_cfg)
    space_impl.db_impl = dev
    space_impl.schema = SparqlSQLSchema()

    inserted = await space_impl.add_rdf_quads_batch_bulk(SPACE_ID, quads)
    _stats_cache.clear()

    if run_analyze:
        t = SparqlSQLSchema.get_table_names(SPACE_ID)
        async with pool.acquire() as conn:
            for tbl in (t['rdf_quad'], t['term']):
                await conn.execute(f"ANALYZE {tbl}")

    return inserted


async def run(query_filter: str = "slow", show_explain: bool = False,
              show_sql: bool = False, pipeline: bool = False,
              fresh: bool = False, analyze: bool = False,
              save_dir: str = None):
    mode = "fresh" if fresh else ("pipeline" if pipeline else "direct")
    print(f"kgquery_perf_bench — space={SPACE_ID}, mode={mode}")
    print(f"  query={query_filter}, explain={show_explain}")

    # Configure db_provider so edge table / frame_entity table work
    if not db_provider.is_configured():
        dev_impl = DevDbImpl()
        await dev_impl.connect()
        db_provider.configure(dev_impl)

    if fresh:
        inserted = await _fresh_setup(run_analyze=analyze)
        label = "with ANALYZE" if analyze else "no ANALYZE"
        print(f"  Fresh space: {inserted} quads loaded ({label})")
        quad_count = inserted
    else:
        async with db.get_connection() as conn:
            quad_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {SPACE_ID}_rdf_quad"
            )
        if quad_count == 0:
            print("  ❌ No quads found. Run kgquery_perf_setup.py first.")
            return
        print(f"  Space has {quad_count} quads")

    # Select queries to run
    if query_filter == "all":
        query_keys = ["R1", "R3", "R4", "R5", "R8"]
    elif query_filter == "slow":
        query_keys = ["R1", "R4", "R8"]
    else:
        query_keys = [k.strip() for k in query_filter.upper().split(",")]
        for k in query_keys:
            if k not in QUERIES:
                print(f"  ❌ Unknown query: {k}. Available: {', '.join(QUERIES.keys())}")
                return

    results = []

    if pipeline:
        # ── Pipeline mode: use SparqlSQLSpaceImpl.execute_sparql_query() ──
        pg_cfg = db.get_connection_params()
        space_impl = SparqlSQLSpaceImpl(pg_cfg)
        await space_impl.connect()
        try:
            for key in query_keys:
                info = await _run_query_pipeline(
                    f"{key}: {_query_description(key)}",
                    QUERIES[key],
                    space_impl,
                )
                results.append(info)
        finally:
            await space_impl.disconnect()

        # Summary
        print(f"\n{'=' * 70}")
        print(f"  SUMMARY  [pipeline mode — matches server execute_sparql_query]")
        print(f"{'=' * 70}")
        print(f"  {'Query':<8} {'Rows':>6} {'Total':>12}")
        print(f"  {'─' * 28}")
        for r in results:
            if "error" in r:
                print(f"  {r['label']:<8} {'ERROR':>6}")
                continue
            print(f"  {r['label'].split(':')[0]:<8} {r['rows']:>6} {r['total_ms']:>11.0f}ms")
        print()

    else:
        # ── Direct mode: manual sidecar + v2 generate + execute ──
        sidecar = SidecarClient()

        for key in query_keys:
            info = await _run_query(
                f"{key}: {_query_description(key)}",
                QUERIES[key],
                sidecar,
                show_explain=show_explain,
                show_sql=show_sql,
                save_dir=save_dir,
            )
            results.append(info)

        # Summary
        print(f"\n{'=' * 70}")
        print(f"  SUMMARY  [direct mode]")
        print(f"{'=' * 70}")
        print(f"  {'Query':<8} {'Rows':>6} {'Sidecar':>10} {'Generate':>10} {'Execute':>10} {'Total':>10}")
        print(f"  {'─' * 56}")
        for r in results:
            if "error" in r:
                print(f"  {r['label']:<8} {'ERROR':>6}")
                continue
            print(f"  {r['label'].split(':')[0]:<8} {r['rows']:>6} "
                  f"{r['sidecar_ms']:>9.0f}ms {r['gen_ms']:>9.0f}ms "
                  f"{r['exec_ms']:>9.0f}ms {r['total_ms']:>9.0f}ms")
        print()


def _query_description(key: str) -> str:
    descs = {
        "R1": "All MakesProduct (simple)",
        "R3": "All CompetitorOf (simple)",
        "R4": "MakesProduct from Tech companies (1 frame+slot)",
        "R5": "Relations from large companies (employee>=500)",
        "R8": "MakesProduct from large Tech (industry+employee)",
    }
    return descs.get(key, key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark KGQuery SPARQL patterns")
    parser.add_argument("--query", default="slow",
                        help="Which queries: 'slow' (R1,R4,R8), 'all', or comma-separated (e.g. R4,R8)")
    parser.add_argument("--explain", action="store_true", help="Show EXPLAIN ANALYZE output")
    parser.add_argument("--sql", action="store_true", help="Show generated SQL")
    parser.add_argument("--pipeline", action="store_true",
                        help="Use SparqlSQLSpaceImpl.execute_sparql_query() (matches server path)")
    parser.add_argument("--fresh", action="store_true",
                        help="Drop/create/load data then query immediately (no ANALYZE, reproduces server conditions)")
    parser.add_argument("--analyze", action="store_true",
                        help="Run ANALYZE after fresh load (use with --fresh to test the fix)")
    parser.add_argument("--save-dir", default=None,
                        help="Directory to write SQL and EXPLAIN files")
    args = parser.parse_args()
    save_dir = args.save_dir
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
    asyncio.run(run(query_filter=args.query, show_explain=args.explain,
                    show_sql=args.sql, pipeline=args.pipeline,
                    fresh=args.fresh, analyze=args.analyze,
                    save_dir=save_dir))
