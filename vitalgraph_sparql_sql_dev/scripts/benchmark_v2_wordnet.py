#!/usr/bin/env python3
"""
benchmark_v2_wordnet.py — Performance benchmark for the v2 SPARQL-to-SQL pipeline
against the WordNet KGFrames dataset.

Measures four execution modes:
  A. Full pipeline   (SPARQL → sidecar → AST → SQL gen → SQL exec)
  B. Cached compile  (reuse sidecar JSON, re-generate SQL)
  C. Cached SQL      (reuse generated SQL string, re-execute)
  D. Prepared stmt   (psycopg3 prepare=True on cached SQL)

Usage:
    python -m vitalgraph_sparql_sql.scripts.benchmark_v2_wordnet
    python -m vitalgraph_sparql_sql.scripts.benchmark_v2_wordnet --runs 10
    python -m vitalgraph_sparql_sql.scripts.benchmark_v2_wordnet --query F1
    python -m vitalgraph_sparql_sql.scripts.benchmark_v2_wordnet --explain
"""

import argparse
import logging
import os
import sys
import time
import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sidecar_client import SidecarClient
from vitalgraph_sparql_sql.jena_ast_mapper import map_compile_response
from vitalgraph_sparql_sql.sparql_sql.generator import generate_sql
from vitalgraph_sparql_sql import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ontology constants
# ---------------------------------------------------------------------------
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VITAL_NAME = "http://vital.ai/ontology/vital-core#hasName"
VITAL_EDGE_SRC = "http://vital.ai/ontology/vital-core#hasEdgeSource"
VITAL_EDGE_DST = "http://vital.ai/ontology/vital-core#hasEdgeDestination"
HALEY_KG_ENTITY = "http://vital.ai/ontology/haley-ai-kg#KGEntity"
HALEY_KG_FRAME = "http://vital.ai/ontology/haley-ai-kg#KGFrame"
HALEY_FRAME_TYPE_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription"
HALEY_KG_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"
HALEY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
HALEY_SLOT_VALUE = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"

SPACE_ID = "wordnet_exp"

# ---------------------------------------------------------------------------
# Query suite
# ---------------------------------------------------------------------------
QUERIES = {
    "S1": {
        "label": "S1: Distinct predicates",
        "sparql": "SELECT DISTINCT ?p WHERE { ?s ?p ?o } ORDER BY ?p",
        "category": "schema",
    },
    "S2": {
        "label": "S2: Class distribution",
        "sparql": f"""
            SELECT ?type (COUNT(?s) AS ?count) WHERE {{
                ?s <{RDF_TYPE}> ?type
            }} GROUP BY ?type ORDER BY DESC(?count)
        """,
        "category": "schema",
    },
    "E1": {
        "label": "E1: Entity by name (happy)",
        "sparql": f"""
            SELECT ?entity ?name WHERE {{
                ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?entity <{VITAL_NAME}> ?name .
                FILTER(CONTAINS(?name, "happy"))
            }} LIMIT 50
        """,
        "category": "entity",
    },
    "E2": {
        "label": "E2: Entity by description (happy)",
        "sparql": f"""
            SELECT ?entity ?desc WHERE {{
                ?entity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?entity <{HALEY_KG_DESC}> ?desc .
                FILTER(CONTAINS(?desc, "happy"))
            }} LIMIT 50
        """,
        "category": "entity",
    },
    "E3": {
        "label": "E3: Entity count by type",
        "sparql": f"""
            SELECT (COUNT(?e) AS ?count) WHERE {{
                ?e <{RDF_TYPE}> <{HALEY_KG_ENTITY}>
            }}
        """,
        "category": "entity",
    },
    "F1": {
        "label": "F1: Relationships for 'happy' (multi-join BGP)",
        "sparql": f"""
            SELECT ?srcName ?relationType ?dstName WHERE {{
                ?srcEntity <{RDF_TYPE}> <{HALEY_KG_ENTITY}> .
                ?srcEntity <{VITAL_NAME}> ?srcName .
                FILTER(CONTAINS(?srcName, "happy"))

                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
                ?frame <{HALEY_FRAME_TYPE_DESC}> ?relationType .

                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .

                ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .

                ?dstEntity <{VITAL_NAME}> ?dstName .
            }} LIMIT 50
        """,
        "category": "frame",
    },
    "F2": {
        "label": "F2: Frame UNION (src OR dst has 'happy')",
        "sparql": f"""
            SELECT ?entity ?frame ?srcEntity ?dstEntity WHERE {{
                {{
                    ?srcEntity <{HALEY_KG_DESC}> ?srcDesc .
                    FILTER(CONTAINS(?srcDesc, "happy"))
                    FILTER(?srcEntity != ?dstEntity)
                    ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                    ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                    ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                    ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                    ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                    ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                    BIND(?srcEntity AS ?entity)
                }}
                UNION
                {{
                    ?dstEntity <{HALEY_KG_DESC}> ?dstDesc .
                    FILTER(CONTAINS(?dstDesc, "happy"))
                    FILTER(?srcEntity != ?dstEntity)
                    ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                    ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                    ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                    ?dstSlot <{HALEY_SLOT_TYPE}> <urn:hasDestinationEntity> .
                    ?dstSlot <{HALEY_SLOT_VALUE}> ?dstEntity .
                    ?dstEdge <{VITAL_EDGE_SRC}> ?frame .
                    ?dstEdge <{VITAL_EDGE_DST}> ?dstSlot .
                    BIND(?dstEntity AS ?entity)
                }}
            }}
            ORDER BY ?entity
            LIMIT 50
        """,
        "category": "frame",
    },
    "F3": {
        "label": "F3: Entity degree (outgoing frames, GROUP BY)",
        "sparql": f"""
            SELECT ?srcEntity (COUNT(?frame) AS ?degree) WHERE {{
                ?srcSlot <{HALEY_SLOT_TYPE}> <urn:hasSourceEntity> .
                ?srcSlot <{HALEY_SLOT_VALUE}> ?srcEntity .
                ?srcEdge <{VITAL_EDGE_SRC}> ?frame .
                ?srcEdge <{VITAL_EDGE_DST}> ?srcSlot .
                ?frame <{RDF_TYPE}> <{HALEY_KG_FRAME}> .
            }} GROUP BY ?srcEntity ORDER BY DESC(?degree) LIMIT 15
        """,
        "category": "frame",
    },
}


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

@dataclass
class PhaseTiming:
    """Timing for a single query execution."""
    sidecar_ms: float = 0.0
    mapper_ms: float = 0.0
    generate_ms: float = 0.0
    execute_ms: float = 0.0
    wall_ms: float = 0.0
    row_count: int = 0
    sql_chars: int = 0
    error: Optional[str] = None

    @property
    def overhead_ms(self) -> float:
        return self.sidecar_ms + self.mapper_ms + self.generate_ms

    @property
    def total_ms(self) -> float:
        return self.overhead_ms + self.execute_ms


@dataclass
class BenchmarkResult:
    """Aggregated results for a query across multiple runs."""
    query_id: str
    label: str
    full_pipeline: List[PhaseTiming] = field(default_factory=list)
    cached_compile: List[PhaseTiming] = field(default_factory=list)
    cached_sql: List[PhaseTiming] = field(default_factory=list)
    prepared_stmt: List[PhaseTiming] = field(default_factory=list)
    explain_rows: List[str] = field(default_factory=list)

    def _median(self, timings: List[PhaseTiming], attr: str) -> float:
        vals = [getattr(t, attr) for t in timings if t.error is None]
        return statistics.median(vals) if vals else 0.0

    def summary_row(self) -> Dict[str, Any]:
        rows = self.full_pipeline[0].row_count if self.full_pipeline else 0
        return {
            "query": self.query_id,
            "label": self.label,
            "rows": rows,
            "full_wall": self._median(self.full_pipeline, "wall_ms"),
            "full_exec": self._median(self.full_pipeline, "execute_ms"),
            "full_overhead": self._median(self.full_pipeline, "overhead_ms"),
            "cached_wall": self._median(self.cached_compile, "wall_ms"),
            "sql_wall": self._median(self.cached_sql, "wall_ms"),
            "prep_wall": self._median(self.prepared_stmt, "wall_ms"),
        }


# ---------------------------------------------------------------------------
# Pipeline execution modes
# ---------------------------------------------------------------------------

def run_full_pipeline(sparql: str, space_id: str, sidecar: SidecarClient,
                      conn) -> Tuple[PhaseTiming, Any, Any]:
    """Mode A: Full pipeline — SPARQL string → results.

    Returns (timing, compile_result, sql_string) for caching by later modes.
    """
    timing = PhaseTiming()
    wall_start = time.monotonic()

    # Phase 1: Sidecar
    t0 = time.monotonic()
    try:
        raw_json = sidecar.compile(sparql)
    except Exception as e:
        timing.error = f"Sidecar error: {e}"
        timing.wall_ms = (time.monotonic() - wall_start) * 1000
        return timing, None, None
    timing.sidecar_ms = (time.monotonic() - t0) * 1000

    # Phase 2: AST mapping
    t0 = time.monotonic()
    compile_result = map_compile_response(raw_json)
    timing.mapper_ms = (time.monotonic() - t0) * 1000

    if not compile_result.ok:
        timing.error = f"Parse error: {compile_result.error}"
        timing.wall_ms = (time.monotonic() - wall_start) * 1000
        return timing, None, None

    # Phase 3: SQL generation
    t0 = time.monotonic()
    gen_result = generate_sql(compile_result, space_id, conn=conn)
    timing.generate_ms = (time.monotonic() - t0) * 1000

    if not gen_result.ok:
        timing.error = f"Generate error: {gen_result.error}"
        timing.wall_ms = (time.monotonic() - wall_start) * 1000
        return timing, compile_result, None

    sql = gen_result.sql
    timing.sql_chars = len(sql)

    # Phase 4: Execute
    t0 = time.monotonic()
    try:
        rows = db.execute_query(sql, conn=conn)
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.row_count = len(rows)
    except Exception as e:
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.error = f"SQL error: {e}"
        try:
            conn.rollback()
        except Exception:
            pass

    timing.wall_ms = (time.monotonic() - wall_start) * 1000
    return timing, compile_result, sql


def run_cached_compile(compile_result, space_id: str, conn) -> PhaseTiming:
    """Mode B: Skip sidecar — reuse cached CompileResult, re-generate SQL."""
    timing = PhaseTiming()
    wall_start = time.monotonic()

    # Phase 3: SQL generation (re-run — constants may differ per connection)
    t0 = time.monotonic()
    gen_result = generate_sql(compile_result, space_id, conn=conn)
    timing.generate_ms = (time.monotonic() - t0) * 1000

    if not gen_result.ok:
        timing.error = f"Generate error: {gen_result.error}"
        timing.wall_ms = (time.monotonic() - wall_start) * 1000
        return timing

    sql = gen_result.sql
    timing.sql_chars = len(sql)

    # Phase 4: Execute
    t0 = time.monotonic()
    try:
        rows = db.execute_query(sql, conn=conn)
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.row_count = len(rows)
    except Exception as e:
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.error = f"SQL error: {e}"
        try:
            conn.rollback()
        except Exception:
            pass

    timing.wall_ms = (time.monotonic() - wall_start) * 1000
    return timing


def run_cached_sql(sql: str, conn) -> PhaseTiming:
    """Mode C: Skip sidecar + generation — reuse cached SQL string."""
    timing = PhaseTiming()
    wall_start = time.monotonic()
    timing.sql_chars = len(sql)

    t0 = time.monotonic()
    try:
        rows = db.execute_query(sql, conn=conn)
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.row_count = len(rows)
    except Exception as e:
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.error = f"SQL error: {e}"
        try:
            conn.rollback()
        except Exception:
            pass

    timing.wall_ms = (time.monotonic() - wall_start) * 1000
    return timing


def run_prepared_stmt(sql: str, conn) -> PhaseTiming:
    """Mode D: Prepared statement — psycopg3 prepare=True on cached SQL."""
    timing = PhaseTiming()
    wall_start = time.monotonic()
    timing.sql_chars = len(sql)

    t0 = time.monotonic()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, prepare=True)
            rows = cur.fetchall()
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.row_count = len(rows)
    except Exception as e:
        timing.execute_ms = (time.monotonic() - t0) * 1000
        timing.error = f"SQL error: {e}"
        try:
            conn.rollback()
        except Exception:
            pass

    timing.wall_ms = (time.monotonic() - wall_start) * 1000
    return timing


def run_explain(sql: str, conn) -> List[str]:
    """Run EXPLAIN ANALYZE on a SQL query."""
    try:
        rows = db.execute_query(f"EXPLAIN ANALYZE {sql}", conn=conn)
        return [list(r.values())[0] for r in rows]
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return [f"EXPLAIN failed: {e}"]


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

def run_benchmark(query_ids: Optional[List[str]] = None, runs: int = 5,
                  explain: bool = False, verbose: bool = False) -> List[BenchmarkResult]:
    """Run the full benchmark suite."""
    if query_ids is None:
        query_ids = list(QUERIES.keys())

    results: List[BenchmarkResult] = []
    sidecar = SidecarClient()

    # Warm the connection pool
    with db.get_connection() as _:
        pass

    print("=" * 72)
    print("  v2 Performance Benchmark — WordNet KGFrames")
    print(f"  Runs per query: {runs}")
    print("=" * 72)
    print()

    with db.get_connection() as conn:
        for qid in query_ids:
            q = QUERIES.get(qid)
            if not q:
                print(f"Unknown query ID: {qid}")
                continue

            sparql = q["sparql"]
            label = q["label"]
            bench = BenchmarkResult(query_id=qid, label=label)

            print(f"─── {label} ───")

            # Mode A: Full pipeline (run 1 = cold, rest = warm)
            cached_compile_result = None
            cached_sql = None

            for i in range(runs):
                timing, cr, sql = run_full_pipeline(sparql, SPACE_ID, sidecar, conn)
                bench.full_pipeline.append(timing)
                if cr is not None and cached_compile_result is None:
                    cached_compile_result = cr
                if sql is not None and cached_sql is None:
                    cached_sql = sql

                if timing.error:
                    print(f"  Full[{i}]: ERROR {timing.error}")
                elif i == 0:
                    print(f"  Full[cold]:  sidecar={timing.sidecar_ms:.0f}ms  "
                          f"gen={timing.generate_ms:.0f}ms  "
                          f"exec={timing.execute_ms:.0f}ms  "
                          f"wall={timing.wall_ms:.0f}ms  "
                          f"rows={timing.row_count}")

            ok_full = [t for t in bench.full_pipeline if t.error is None]
            if runs > 1 and ok_full:
                med = statistics.median(t.wall_ms for t in ok_full)
                print(f"  Full[median]: wall={med:.0f}ms")

            # Mode B: Cached compile (skip sidecar)
            if cached_compile_result:
                for i in range(runs):
                    timing = run_cached_compile(cached_compile_result, SPACE_ID, conn)
                    bench.cached_compile.append(timing)

                ok_cc = [t for t in bench.cached_compile if t.error is None]
                if ok_cc:
                    med = statistics.median(t.wall_ms for t in ok_cc)
                    exec_med = statistics.median(t.execute_ms for t in ok_cc)
                    gen_med = statistics.median(t.generate_ms for t in ok_cc)
                    print(f"  Cached compile[median]: gen={gen_med:.0f}ms  "
                          f"exec={exec_med:.0f}ms  wall={med:.0f}ms")

            # Mode C: Cached SQL (skip sidecar + generation)
            if cached_sql:
                for i in range(runs):
                    timing = run_cached_sql(cached_sql, conn)
                    bench.cached_sql.append(timing)

                ok_cs = [t for t in bench.cached_sql if t.error is None]
                if ok_cs:
                    med = statistics.median(t.wall_ms for t in ok_cs)
                    exec_med = statistics.median(t.execute_ms for t in ok_cs)
                    print(f"  Cached SQL[median]: exec={exec_med:.0f}ms  wall={med:.0f}ms")

            # Mode D: Prepared statement
            if cached_sql:
                for i in range(runs):
                    timing = run_prepared_stmt(cached_sql, conn)
                    bench.prepared_stmt.append(timing)

                ok_ps = [t for t in bench.prepared_stmt if t.error is None]
                if ok_ps:
                    med = statistics.median(t.wall_ms for t in ok_ps)
                    exec_med = statistics.median(t.execute_ms for t in ok_ps)
                    print(f"  Prepared[median]: exec={exec_med:.0f}ms  wall={med:.0f}ms")

            # EXPLAIN ANALYZE
            if explain and cached_sql:
                bench.explain_rows = run_explain(cached_sql, conn)
                if verbose:
                    print(f"  EXPLAIN ANALYZE:")
                    for line in bench.explain_rows:
                        print(f"    {line}")

            # SQL size
            if cached_sql:
                print(f"  SQL: {len(cached_sql)} chars")

            print()
            results.append(bench)

    sidecar.close()

    # Summary table
    _print_summary(results)
    return results


def _print_summary(results: List[BenchmarkResult]):
    """Print the final summary comparison table."""
    print("=" * 90)
    print("  Summary (median wall time in ms)")
    print("=" * 90)
    hdr = (f"  {'Query':<6} {'Label':<40} {'Rows':>5} "
           f"{'Full':>7} {'Cached':>7} {'SQL':>7} {'Prep':>7} {'Speedup':>8}")
    print(hdr)
    print(f"  {'─' * 84}")

    for r in results:
        s = r.summary_row()
        speedup = ""
        if s["full_wall"] > 0 and s["sql_wall"] > 0:
            speedup = f"{s['full_wall'] / s['sql_wall']:.1f}x"
        print(f"  {s['query']:<6} {s['label'][:40]:<40} {s['rows']:>5} "
              f"{s['full_wall']:>6.0f}ms"
              f"{s['cached_wall']:>6.0f}ms"
              f"{s['sql_wall']:>6.0f}ms"
              f"{s['prep_wall']:>6.0f}ms"
              f"{speedup:>8}")

    print(f"  {'─' * 84}")
    print()

    # Overhead analysis
    print("  Overhead Analysis (median, ms):")
    print(f"  {'Query':<6} {'Sidecar':>9} {'Mapper':>8} {'Generate':>10} "
          f"{'Execute':>9} {'Overhead':>10} {'%Overhead':>10}")
    print(f"  {'─' * 66}")
    for r in results:
        fp = [t for t in r.full_pipeline if t.error is None]
        if not fp:
            continue
        sc = statistics.median(t.sidecar_ms for t in fp)
        mp = statistics.median(t.mapper_ms for t in fp)
        gn = statistics.median(t.generate_ms for t in fp)
        ex = statistics.median(t.execute_ms for t in fp)
        oh = sc + mp + gn
        pct = (oh / (oh + ex) * 100) if (oh + ex) > 0 else 0
        print(f"  {r.query_id:<6} {sc:>8.0f}ms {mp:>7.0f}ms {gn:>9.0f}ms "
              f"{ex:>8.0f}ms {oh:>9.0f}ms {pct:>9.0f}%")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark v2 SPARQL-to-SQL pipeline on WordNet KGFrames"
    )
    parser.add_argument("--runs", type=int, default=5,
                        help="Number of runs per query per mode (default: 5)")
    parser.add_argument("--query", "-q", nargs="*", default=None,
                        help="Specific query IDs to run (e.g., S1 F1 F2)")
    parser.add_argument("--explain", action="store_true",
                        help="Run EXPLAIN ANALYZE for each query")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show EXPLAIN output and SQL")
    parser.add_argument("--list", action="store_true",
                        help="List available query IDs and exit")
    args = parser.parse_args()

    if args.list:
        for qid, q in QUERIES.items():
            print(f"  {qid}: {q['label']}  [{q['category']}]")
        return 0

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    query_ids = args.query
    if query_ids and len(query_ids) == 1 and "," in query_ids[0]:
        query_ids = query_ids[0].split(",")

    run_benchmark(query_ids=query_ids, runs=args.runs,
                  explain=args.explain, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
