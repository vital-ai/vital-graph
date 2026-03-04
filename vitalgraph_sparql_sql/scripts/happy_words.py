#!/usr/bin/env python3
"""
happy_words.py — Find WordNet words related to "happy" via SPARQL-to-SQL.

Queries the KGFrame graph structure to find all entities connected to
entities named "happy", then pretty-prints the relationships as:

    happy ---Hyponym---> blissful
    happy ---Hypernym---> feeling

Usage:
    python vitalgraph_sparql_sql/scripts/happy_words.py
    python -m vitalgraph_sparql_sql.scripts.happy_words [--limit 50]
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

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


def _format_sql(sql: str, width: int = 100) -> str:
    """Lightly format SQL for display: collapse whitespace, indent keywords."""
    import re
    sql = re.sub(r'\s+', ' ', sql.strip())
    for kw in ['FROM', 'JOIN', 'LEFT JOIN', 'WHERE', 'GROUP BY',
               'ORDER BY', 'LIMIT', 'ON ', 'AND ']:
        sql = sql.replace(f' {kw}', f'\n  {kw}')
    # Wrap WITH/SELECT at top
    sql = sql.replace('WITH ', 'WITH\n  ')
    sql = sql.replace(') SELECT ', ')\nSELECT ')
    return sql


def _print_timing(label: str, timing: dict, wall_ms: float, row_count: int):
    """Print timing breakdown for a run."""
    gd = timing.get("generate_detail", {})
    opt_ms = gd.get("optimize_ms", 0)
    print(f"  {label}:")
    print(f"    rows={row_count}, wall={wall_ms:.0f}ms")
    print(f"    sidecar={timing.get('sidecar_ms', 0):.0f}ms, "
          f"generate={timing.get('generate_ms', 0):.0f}ms, "
          f"execute={timing.get('execute_ms', 0):.0f}ms")
    print(f"    generate detail: "
          f"collect={gd.get('collect_ms', 0):.1f}ms, "
          f"materialize={gd.get('materialize_ms', 0):.1f}ms, "
          f"resolve={gd.get('resolve_ms', 0):.1f}ms, "
          f"emit={gd.get('emit_ms', 0):.1f}ms, "
          f"substitute={gd.get('substitute_ms', 0):.1f}ms, "
          f"optimize={opt_ms:.1f}ms")


def run(limit: int = 50, verbose: bool = False):
    """Query for words related to 'happy' and pretty-print the graph."""

    sparql = f"""
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
        }} LIMIT {limit}
    """

    print(f"Querying WordNet for words related to 'happy' (limit {limit})...")
    print()

    # Warm the connection pool before timing
    from vitalgraph_sparql_sql import db
    with db.get_connection() as _:
        pass

    results = {}

    for opt_flag in [False, True]:
        label = "optimize=ON" if opt_flag else "optimize=OFF"
        with SparqlOrchestrator(space_id=SPACE_ID, optimize=opt_flag) as orch:
            # Phase 1: get SQL only (no execution)
            sql_result = orch.execute(sparql, sql_only=True)
            if not sql_result.ok:
                print(f"ERROR ({label}): {sql_result.error}")
                return 1

            # Phase 2: execute FIRST — before EXPLAIN, so PG plan cache
            # is cold and we measure the real optimizer benefit.
            t0 = time.monotonic()
            result = orch.execute(sparql, include_sql=True)
            wall_ms = (time.monotonic() - t0) * 1000

            if not result.ok:
                print(f"ERROR ({label}): {result.error}")
                return 1

            # Phase 3: EXPLAIN ANALYZE — runs after for analysis only
            explain_rows = []
            try:
                explain_sql = f"EXPLAIN ANALYZE {sql_result.sql}"
                raw = db.execute_query(explain_sql)
                explain_rows = [list(r.values())[0] for r in raw]
            except Exception as e:
                explain_rows = [f"EXPLAIN failed: {e}"]

            results[label] = {
                "sql": sql_result.sql,
                "explain": explain_rows,
                "result": result,
                "wall_ms": wall_ms,
            }

    # ── SQL Analysis ──────────────────────────────────────────────────────
    print("=" * 70)
    print("SQL Analysis")
    print("=" * 70)

    for label in ["optimize=OFF", "optimize=ON"]:
        info = results[label]
        sql = info["sql"]
        print(f"\n{'─' * 70}")
        print(f"  {label}  ({len(sql)} chars)")
        print(f"{'─' * 70}")
        if verbose:
            print(_format_sql(sql))
        else:
            formatted = _format_sql(sql)
            if len(formatted) > 500:
                print(formatted[:500])
                print(f"    ... ({len(formatted) - 500} more chars, use -v for full SQL)")
            else:
                print(formatted)
        print()

    # ── Query Plans ───────────────────────────────────────────────────────
    print("=" * 70)
    print("Query Plans (EXPLAIN ANALYZE)")
    print("=" * 70)

    for label in ["optimize=OFF", "optimize=ON"]:
        info = results[label]
        print(f"\n{'─' * 70}")
        print(f"  {label}")
        print(f"{'─' * 70}")
        for line in info["explain"]:
            print(f"  {line}")
        print()

    # ── Timing Comparison ─────────────────────────────────────────────────
    print("=" * 70)
    print("Timing Comparison")
    print("=" * 70)

    for label in ["optimize=OFF", "optimize=ON"]:
        info = results[label]
        r = info["result"]
        _print_timing(label, r.timing or {}, info["wall_ms"], r.row_count)
        print()

    # Summary table
    off = results["optimize=OFF"]
    on = results["optimize=ON"]
    off_exec = (off["result"].timing or {}).get("execute_ms", 0)
    on_exec = (on["result"].timing or {}).get("execute_ms", 0)
    speedup = off_exec / on_exec if on_exec > 0 else 0

    print(f"{'─' * 70}")
    print(f"  {'Metric':<20} {'optimize=OFF':>14} {'optimize=ON':>14} {'Speedup':>10}")
    print(f"  {'─' * 58}")
    print(f"  {'Rows':<20} {off['result'].row_count:>14} {on['result'].row_count:>14} {'':>10}")
    print(f"  {'Execute ms':<20} {off_exec:>13.0f}ms {on_exec:>13.0f}ms {speedup:>9.1f}x")
    print(f"  {'Wall ms':<20} {off['wall_ms']:>13.0f}ms {on['wall_ms']:>13.0f}ms {off['wall_ms']/on['wall_ms'] if on['wall_ms'] > 0 else 0:>9.1f}x")
    print(f"  {'SQL chars':<20} {len(off['sql']):>14} {len(on['sql']):>14} {'':>10}")
    print(f"{'─' * 70}")
    print()

    # ── Relationships ─────────────────────────────────────────────────────
    # Use the optimized result for display
    result = on["result"]

    if not result.rows:
        print("No relationships found.")
        return 0

    print(f"Relationships ({result.row_count} found):")
    print()

    by_relation: dict = {}
    for row in result.rows:
        src = row.get("srcname", "?")
        rel = row.get("relationtype", "?")
        dst = row.get("dstname", "?")
        rel_short = rel
        if rel_short.startswith("Edge_Wordnet"):
            rel_short = rel_short[len("Edge_Wordnet"):]
        elif rel_short.startswith("Edge_"):
            rel_short = rel_short[len("Edge_"):]
        by_relation.setdefault(rel_short, []).append((src, dst))

    for rel_type in sorted(by_relation.keys()):
        pairs = by_relation[rel_type]
        print(f"  {rel_type} ({len(pairs)})")
        print(f"  {'─' * (len(rel_type) + len(str(len(pairs))) + 3)}")
        for src, dst in sorted(pairs, key=lambda x: (x[0], x[1])):
            print(f"    {src} ---{rel_type}---> {dst}")
        print()

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Find WordNet words related to 'happy' via SPARQL-to-SQL"
    )
    parser.add_argument("--limit", type=int, default=50,
                        help="Max number of relationships to return (default: 50)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show generated SQL")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
    )
    sys.exit(run(limit=args.limit, verbose=args.verbose))


if __name__ == "__main__":
    main()
