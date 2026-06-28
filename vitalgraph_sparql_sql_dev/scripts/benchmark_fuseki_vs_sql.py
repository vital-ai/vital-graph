#!/usr/bin/env python3
"""
benchmark_fuseki_vs_sql.py — Compare Fuseki (native SPARQL) vs PostgreSQL (SPARQL→SQL)
for WordNet KGFrames queries.

Runs the same SPARQL queries against both backends and reports timing.

Usage:
    python vitalgraph_sparql_sql/scripts/benchmark_fuseki_vs_sql.py
    python vitalgraph_sparql_sql/scripts/benchmark_fuseki_vs_sql.py -q 5c
    python vitalgraph_sparql_sql/scripts/benchmark_fuseki_vs_sql.py --backend fuseki
    python vitalgraph_sparql_sql/scripts/benchmark_fuseki_vs_sql.py --backend pg
    python vitalgraph_sparql_sql/scripts/benchmark_fuseki_vs_sql.py --fuseki-timeout 60
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import requests

# Ensure project root is on path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Queries — same SPARQL for both backends
# ---------------------------------------------------------------------------
QUERIES = [
    {
        "label": "1a. Distinct predicates",
        "sparql": "SELECT DISTINCT ?p WHERE { ?s ?p ?o } ORDER BY ?p",
    },
    {
        "label": "2a. Sample KGEntities with names",
        "sparql": """
            SELECT ?entity ?name WHERE {
                ?entity <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
                        <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                ?entity <http://vital.ai/ontology/vital-core#hasName> ?name
            } LIMIT 10
        """,
    },
    {
        "label": "5a. Total triple count",
        "sparql": "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }",
    },
    {
        "label": "5b. Entity degree (outgoing frame count)",
        "sparql": """
            SELECT ?srcEntity (COUNT(?frame) AS ?degree) WHERE {
                ?srcSlot <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType> <urn:hasSourceEntity> .
                ?srcSlot <http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue> ?srcEntity .
                ?srcEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame .
                ?srcEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?srcSlot .
                ?frame <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
                       <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
            } GROUP BY ?srcEntity ORDER BY DESC(?degree) LIMIT 15
        """,
    },
    {
        "label": "5c. Subquery: top-5 entities + relationships",
        "sparql": """
            SELECT ?srcName ?degree ?relationType ?dstName WHERE {
                {
                    SELECT ?srcEntity (COUNT(?frame) AS ?degree) WHERE {
                        ?srcSlot <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType> <urn:hasSourceEntity> .
                        ?srcSlot <http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue> ?srcEntity .
                        ?srcEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame .
                        ?srcEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?srcSlot .
                        ?frame <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
                               <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
                    } GROUP BY ?srcEntity ORDER BY DESC(?degree) LIMIT 5
                }
                ?srcEntity <http://vital.ai/ontology/vital-core#hasName> ?srcName .
                ?frame2 <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
                        <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
                ?frame2 <http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription> ?relationType .
                ?srcSlot2 <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType> <urn:hasSourceEntity> .
                ?srcSlot2 <http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue> ?srcEntity .
                ?srcEdge2 <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame2 .
                ?srcEdge2 <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?srcSlot2 .
                ?dstSlot <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType> <urn:hasDestinationEntity> .
                ?dstSlot <http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue> ?dstEntity .
                ?dstEdge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame2 .
                ?dstEdge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?dstSlot .
                ?dstEntity <http://vital.ai/ontology/vital-core#hasName> ?dstName .
            } LIMIT 20
        """,
    },
]


# ---------------------------------------------------------------------------
# Fuseki runner
# ---------------------------------------------------------------------------
def run_fuseki(fuseki_url: str, dataset: str, sparql: str, timeout: int) -> dict:
    """Execute SPARQL on Fuseki, return {rows, ms, error, timeout}."""
    url = f"{fuseki_url}/{dataset}/sparql"
    headers = {"Accept": "application/sparql-results+json"}
    t0 = time.monotonic()
    try:
        resp = requests.get(url, params={"query": sparql}, headers=headers, timeout=timeout)
        elapsed = (time.monotonic() - t0) * 1000
        if resp.status_code != 200:
            return {"rows": 0, "ms": elapsed, "error": f"HTTP {resp.status_code}", "timeout": False}
        text = resp.text
        # Fuseki appends a timeout notice when it aborts
        if "Query cancelled due to timeout" in text:
            return {"rows": 0, "ms": elapsed, "error": "TIMEOUT", "timeout": True}
        data = resp.json()
        rows = len(data["results"]["bindings"])
        return {"rows": rows, "ms": elapsed, "error": None, "timeout": False}
    except requests.exceptions.Timeout:
        elapsed = (time.monotonic() - t0) * 1000
        return {"rows": 0, "ms": elapsed, "error": "TIMEOUT", "timeout": True}
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        return {"rows": 0, "ms": elapsed, "error": str(e), "timeout": False}


# ---------------------------------------------------------------------------
# PostgreSQL (SPARQL→SQL) runner
# ---------------------------------------------------------------------------
def run_pg(space_id: str, sparql: str) -> dict:
    """Execute SPARQL via the Jena→SQL pipeline, return {rows, ms, error}."""
    try:
        with SparqlOrchestrator(space_id=space_id, optimize=False) as orch:
            t0 = time.monotonic()
            result = orch.execute(sparql)
            elapsed = (time.monotonic() - t0) * 1000
            if not result.ok:
                return {"rows": 0, "ms": elapsed, "error": result.error}
            return {"rows": len(result.rows or []), "ms": elapsed, "error": None}
    except Exception as e:
        return {"rows": 0, "ms": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_benchmark(fuseki_url: str, fuseki_dataset: str, pg_space: str,
                  selected: str = None, backend: str = "both",
                  fuseki_timeout: int = 60, verbose: bool = False):
    """Run benchmark queries and display comparison."""

    queries = QUERIES
    if selected:
        prefixes = [s.strip() for s in selected.split(",")]
        queries = [q for q in QUERIES if any(q["label"].startswith(p) for p in prefixes)]
        if not queries:
            print(f"No queries matched filter: {selected}")
            print(f"Available: {', '.join(q['label'] for q in QUERIES)}")
            return 1

    run_fuseki_flag = backend in ("both", "fuseki")
    run_pg_flag = backend in ("both", "pg")

    # Header
    print("=" * 80)
    print("  Fuseki vs PostgreSQL (SPARQL→SQL) Benchmark")
    print(f"  Dataset: 7M WordNet KGFrame triples")
    if run_fuseki_flag:
        print(f"  Fuseki:  {fuseki_url}/{fuseki_dataset}  (timeout={fuseki_timeout}s)")
    if run_pg_flag:
        print(f"  PG:      space={pg_space}")
    print("=" * 80)
    print()

    results = []

    for q in queries:
        label = q["label"]
        sparql = q["sparql"]
        print(f"━━━ {label} ━━━")

        fuseki_res = None
        pg_res = None

        if run_fuseki_flag:
            fuseki_res = run_fuseki(fuseki_url, fuseki_dataset, sparql, fuseki_timeout)
            if fuseki_res["error"]:
                tag = "TIMEOUT" if fuseki_res["timeout"] else f"ERROR: {fuseki_res['error']}"
                print(f"  Fuseki:  {tag}  ({fuseki_res['ms']:.0f}ms)")
            else:
                print(f"  Fuseki:  {fuseki_res['rows']} rows  {fuseki_res['ms']:.0f}ms")

        if run_pg_flag:
            pg_res = run_pg(pg_space, sparql)
            if pg_res["error"]:
                print(f"  PG:      ERROR: {pg_res['error']}")
            else:
                print(f"  PG:      {pg_res['rows']} rows  {pg_res['ms']:.0f}ms")

        # Comparison
        if fuseki_res and pg_res and not fuseki_res["error"] and not pg_res["error"]:
            if pg_res["ms"] > 0:
                ratio = fuseki_res["ms"] / pg_res["ms"]
                if ratio > 1:
                    print(f"  Winner:  PG {ratio:.1f}x faster")
                else:
                    print(f"  Winner:  Fuseki {1/ratio:.1f}x faster")
        elif fuseki_res and fuseki_res["timeout"] and pg_res and not pg_res["error"]:
            print(f"  Winner:  PG (Fuseki timed out)")

        results.append({"label": label, "fuseki": fuseki_res, "pg": pg_res})
        print()

    # Summary table
    print("=" * 80)
    print("  Summary")
    print("=" * 80)
    print()

    hdr = f"{'Query':<45}"
    if run_fuseki_flag:
        hdr += f" {'Fuseki':>10}"
    if run_pg_flag:
        hdr += f" {'PG':>10}"
    if run_fuseki_flag and run_pg_flag:
        hdr += f" {'Ratio':>8}"
    print(hdr)
    print("-" * len(hdr))

    total_fuseki = 0
    total_pg = 0

    for r in results:
        line = f"{r['label']:<45}"

        f_ms = None
        p_ms = None

        if run_fuseki_flag:
            fr = r["fuseki"]
            if fr and fr["error"]:
                line += f" {'TIMEOUT':>10}" if fr["timeout"] else f" {'ERROR':>10}"
            elif fr:
                f_ms = fr["ms"]
                total_fuseki += f_ms
                line += f" {f_ms:>8.0f}ms"

        if run_pg_flag:
            pr = r["pg"]
            if pr and pr["error"]:
                line += f" {'ERROR':>10}"
            elif pr:
                p_ms = pr["ms"]
                total_pg += p_ms
                line += f" {p_ms:>8.0f}ms"

        if run_fuseki_flag and run_pg_flag:
            if f_ms and p_ms and p_ms > 0:
                ratio = f_ms / p_ms
                if ratio > 1:
                    line += f" PG {ratio:.1f}x"
                else:
                    line += f" F {1/ratio:.1f}x"
            elif r["fuseki"] and r["fuseki"].get("timeout"):
                line += f"   PG >>>>"
            else:
                line += f" {'':>8}"

        print(line)

    print("-" * len(hdr))
    totals = f"{'TOTAL':<45}"
    if run_fuseki_flag:
        totals += f" {total_fuseki:>8.0f}ms"
    if run_pg_flag:
        totals += f" {total_pg:>8.0f}ms"
    if run_fuseki_flag and run_pg_flag and total_pg > 0:
        ratio = total_fuseki / total_pg
        if ratio > 1:
            totals += f" PG {ratio:.1f}x"
        else:
            totals += f" F {1/ratio:.1f}x"
    print(totals)
    print()

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark Fuseki vs PostgreSQL SPARQL→SQL on WordNet KGFrames"
    )
    parser.add_argument("--fuseki-url", default="http://localhost:3030",
                        help="Fuseki server URL (default: http://localhost:3030)")
    parser.add_argument("--fuseki-dataset", default="wordnet-frames",
                        help="Fuseki dataset name (default: wordnet-frames)")
    parser.add_argument("--pg-space", default="wordnet_exp",
                        help="PostgreSQL space ID (default: wordnet_exp)")
    parser.add_argument("-q", "--query", default=None,
                        help="Run only queries matching these prefixes (comma-separated)")
    parser.add_argument("--backend", default="both", choices=["both", "fuseki", "pg"],
                        help="Which backend(s) to run (default: both)")
    parser.add_argument("--fuseki-timeout", type=int, default=60,
                        help="Fuseki HTTP timeout in seconds (default: 60)")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)-30s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    sys.exit(run_benchmark(
        fuseki_url=args.fuseki_url,
        fuseki_dataset=args.fuseki_dataset,
        pg_space=args.pg_space,
        selected=args.query,
        backend=args.backend,
        fuseki_timeout=args.fuseki_timeout,
        verbose=args.verbose,
    ))


if __name__ == "__main__":
    main()
