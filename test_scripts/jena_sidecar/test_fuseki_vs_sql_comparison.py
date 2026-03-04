"""
Fuseki vs SQL Generator — Side-by-Side Comparison

Runs the same SPARQL queries against both:
  1. Fuseki SPARQL endpoint (HTTP, reference implementation)
  2. SQL generator pipeline (Jena sidecar → AST → SQL → PostgreSQL)

Compares: result counts, result values (normalized), and timing.

Requires:
  - Fuseki running at localhost:3030 with vitalgraph_space_lead_test dataset
  - Jena sidecar running at localhost:7070
  - PostgreSQL with lead_test space data

Usage:
  python test_scripts/jena_sidecar/test_fuseki_vs_sql_comparison.py
"""

import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FUSEKI_URL = "http://localhost:3030"
FUSEKI_DATASET = "vitalgraph_space_lead_test"
SPACE_ID = "lead_test"
GRAPH_URI = "urn:lead_test"

# ---------------------------------------------------------------------------
# Fuseki client (simple HTTP, no auth for localhost)
# ---------------------------------------------------------------------------

def query_fuseki(sparql: str, timeout: int = 30, fuseki_dataset: str = None) -> Optional[Dict[str, Any]]:
    """Execute a SPARQL query against Fuseki and return raw JSON result."""
    ds = fuseki_dataset or FUSEKI_DATASET
    url = f"{FUSEKI_URL}/{ds}/query"
    data = urllib.parse.urlencode({"query": sparql}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Accept": "application/sparql-results+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def fuseki_select_rows(raw: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract flat {var: value} rows from Fuseki SELECT JSON results."""
    if "error" in raw:
        return []
    bindings = raw.get("results", {}).get("bindings", [])
    rows = []
    for b in bindings:
        row = {}
        for var, info in b.items():
            row[var] = info.get("value", "")
        rows.append(row)
    return rows


def fuseki_ask_result(raw: Dict[str, Any]) -> Optional[bool]:
    """Extract boolean from Fuseki ASK JSON result."""
    if "error" in raw:
        return None
    return raw.get("boolean")

# ---------------------------------------------------------------------------
# Result normalization for comparison
# ---------------------------------------------------------------------------

def normalize_rows(rows: List[Dict[str, Any]], keys: Optional[List[str]] = None) -> List[Tuple]:
    """Normalize rows to sorted list of tuples for comparison.

    - Picks only the specified keys (or all if None)
    - Strips whitespace, converts to string
    - Sorts the list
    - Case-insensitive key lookup (PostgreSQL lowercases aliases)
    """
    if not rows:
        return []
    if keys is None:
        keys = sorted(rows[0].keys())
    # Filter out internal columns (__uuid, __type)
    keys = [k for k in keys if not k.endswith("__uuid") and not k.endswith("__type")]
    result = []
    for row in rows:
        # Build case-insensitive lookup
        lc_row = {k.lower(): v for k, v in row.items()}
        vals = tuple(str(lc_row.get(k.lower(), "")).strip() for k in keys)
        result.append(vals)
    result.sort()
    return result

# ---------------------------------------------------------------------------
# Comparison queries — adapted from test_inspect_lead_data.py patterns
#
# All queries use GRAPH <urn:lead_test> { ... } so that both Fuseki and the
# SQL pipeline scope to the same named graph. The SQL generator translates
# OpGraph into a context_uuid filter on the quad table.
# ---------------------------------------------------------------------------

G = GRAPH_URI  # shorthand

# Lead dataset config (for direct property queries)
LD_FUSEKI_DATASET = "vitalgraph_space_space_lead_dataset_test"
LD_SPACE_ID = "lead_dataset_exp"
LD_GRAPH = "urn:lead_entity_graph_dataset"

COMPARISON_QUERIES = [
    # ---- Basic SELECT ----
    {
        "label": "Simple triple scan LIMIT 5",
        "sparql": f"SELECT ?s ?p ?o WHERE {{ GRAPH <{G}> {{ ?s ?p ?o }} }} LIMIT 5",
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # no ORDER BY, row choice is non-deterministic
    },
    {
        "label": "Count all triples (data sync check)",
        "sparql": f"SELECT (COUNT(*) AS ?count) WHERE {{ GRAPH <{G}> {{ ?s ?p ?o }} }}",
        "type": "SELECT",
        "compare_count": False,  # datasets may differ
        "compare_values": False,
        "data_sync": True,  # report as informational
        "keys": ["count"],
    },
    # ---- Type queries (from test_inspect_lead_data.py count_entities pattern) ----
    {
        "label": "Count KGEntity instances (data sync check)",
        "sparql": f"""
            SELECT (COUNT(?s) AS ?count) WHERE {{
                GRAPH <{G}> {{
                    ?s <http://vital.ai/ontology/vital-core#vitaltype>
                       <http://vital.ai/ontology/haley-ai-kg#KGEntity>
                }}
            }}
        """,
        "type": "SELECT",
        "compare_count": False,  # datasets may differ
        "compare_values": False,
        "data_sync": True,
        "keys": ["count"],
    },
    # ---- DISTINCT (no ORDER BY → non-deterministic subset) ----
    {
        "label": "DISTINCT predicates LIMIT 20",
        "sparql": f"SELECT DISTINCT ?p WHERE {{ GRAPH <{G}> {{ ?s ?p ?o }} }} LIMIT 20",
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # no ORDER BY, arbitrary 20 of ~36
    },
    # ---- OPTIONAL (no ORDER BY → non-deterministic) ----
    {
        "label": "Entity with optional name LIMIT 10",
        "sparql": f"""
            SELECT ?s ?name WHERE {{
                GRAPH <{G}> {{
                    ?s <http://vital.ai/ontology/vital-core#vitaltype>
                       <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                    OPTIONAL {{ ?s <http://vital.ai/ontology/vital-core#hasName> ?name }}
                }}
            }} LIMIT 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # no ORDER BY
    },
    # ---- GROUP BY + COUNT (no ORDER BY → non-deterministic subset) ----
    {
        "label": "Entity types with counts (GROUP BY)",
        "sparql": f"""
            SELECT ?type (COUNT(?s) AS ?count) WHERE {{
                GRAPH <{G}> {{
                    ?s <http://vital.ai/ontology/vital-core#vitaltype> ?type
                }}
            }}
            GROUP BY ?type
            LIMIT 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # datasets differ + no ORDER BY
    },
    # ---- FILTER with CONTAINS (no ORDER BY) ----
    {
        "label": "FILTER CONTAINS on name",
        "sparql": f"""
            SELECT ?s ?name WHERE {{
                GRAPH <{G}> {{
                    ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
                    FILTER(CONTAINS(?name, "Lead"))
                }}
            }} LIMIT 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # no ORDER BY
    },
    # ---- UNION (no ORDER BY) ----
    {
        "label": "UNION of two types LIMIT 10",
        "sparql": f"""
            SELECT ?s WHERE {{
                GRAPH <{G}> {{
                    {{
                        ?s <http://vital.ai/ontology/vital-core#vitaltype>
                           <http://vital.ai/ontology/haley-ai-kg#KGEntity>
                    }} UNION {{
                        ?s <http://vital.ai/ontology/vital-core#vitaltype>
                           <http://vital.ai/ontology/haley-ai-kg#KGFrame>
                    }}
                }}
            }} LIMIT 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # no ORDER BY
    },
    # ---- ORDER BY with OFFSET (deterministic!) ----
    {
        "label": "ORDER BY + OFFSET",
        "sparql": f"""
            SELECT ?s ?p WHERE {{
                GRAPH <{G}> {{
                    ?s ?p <http://vital.ai/ontology/haley-ai-kg#KGEntity>
                }}
            }} ORDER BY ?s LIMIT 5 OFFSET 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # ORDER BY is deterministic but datasets differ
        "keys": ["s", "p"],
    },
    # ---- Subquery (inner has no ORDER BY → non-deterministic) ----
    {
        "label": "Subquery: inner LIMIT joined to outer",
        "sparql": f"""
            SELECT ?s ?name WHERE {{
                GRAPH <{G}> {{
                    ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
                    {{
                        SELECT ?s WHERE {{
                            ?s <http://vital.ai/ontology/vital-core#vitaltype>
                               <http://vital.ai/ontology/haley-ai-kg#KGEntity>
                        }} LIMIT 5
                    }}
                }}
            }}
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # inner subquery has no ORDER BY
    },
    # ---- Multi-join (no ORDER BY) ----
    {
        "label": "Frame + slot type join (5 triple patterns)",
        "sparql": f"""
            SELECT ?frame ?slotType WHERE {{
                GRAPH <{G}> {{
                    ?frame <http://vital.ai/ontology/vital-core#vitaltype>
                           <http://vital.ai/ontology/haley-ai-kg#KGFrame> .
                    ?frame <http://vital.ai/ontology/haley-ai-kg#hasKGFrameType> ?frameType .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeSource> ?frame .
                    ?edge <http://vital.ai/ontology/vital-core#hasEdgeDestination> ?slot .
                    ?slot <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType> ?slotType .
                }}
            }} LIMIT 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,  # no ORDER BY
    },
    # ---- ASK ----
    {
        "label": "ASK: KGEntity exists",
        "sparql": f"""
            ASK {{
                GRAPH <{G}> {{
                    ?s <http://vital.ai/ontology/vital-core#vitaltype>
                       <http://vital.ai/ontology/haley-ai-kg#KGEntity>
                }}
            }}
        """,
        "type": "ASK",
        "compare_count": False,
        "compare_values": False,
    },
    # ---- CONSTRUCT ----
    {
        "label": "CONSTRUCT: entity labels",
        "sparql": f"""
            CONSTRUCT {{ ?s <http://example.org/label> ?name }}
            WHERE {{
                GRAPH <{G}> {{
                    ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
                    ?s <http://vital.ai/ontology/vital-core#vitaltype>
                       <http://vital.ai/ontology/haley-ai-kg#KGEntity>
                }}
            }} LIMIT 5
        """,
        "type": "CONSTRUCT",
        "compare_count": True,
        "compare_values": False,  # triple formats differ between Fuseki RDF/JSON and our format
    },
    # ==================================================================
    # Direct property queries (lead_dataset_exp, with materialized quads)
    # ==================================================================

    # ---- Count materialized direct properties ----
    {
        "label": "Count direct hasEntityFrame triples",
        "sparql": f"""
            SELECT (COUNT(*) AS ?count) WHERE {{
                GRAPH <{LD_GRAPH}> {{
                    ?entity <http://vital.ai/vitalgraph/direct#hasEntityFrame> ?frame
                }}
            }}
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": True,
        "keys": ["count"],
        "space_id": LD_SPACE_ID,
        "fuseki_dataset": LD_FUSEKI_DATASET,
    },
    # ---- Direct: Entity → Frame → Slot path ----
    {
        "label": "Direct: entity-frame-slot path LIMIT 10",
        "sparql": f"""
            SELECT ?entity ?frame ?slot WHERE {{
                GRAPH <{LD_GRAPH}> {{
                    ?entity <http://vital.ai/vitalgraph/direct#hasEntityFrame> ?frame .
                    ?frame <http://vital.ai/vitalgraph/direct#hasSlot> ?slot .
                }}
            }} LIMIT 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,
        "space_id": LD_SPACE_ID,
        "fuseki_dataset": LD_FUSEKI_DATASET,
    },
    # ---- Direct: Entity → Frame with frame type filter ----
    {
        "label": "Direct: entity frames with type filter",
        "sparql": f"""
            SELECT ?entity ?frame WHERE {{
                GRAPH <{LD_GRAPH}> {{
                    ?entity <http://vital.ai/vitalgraph/direct#hasEntityFrame> ?frame .
                    ?frame <http://vital.ai/ontology/haley-ai-kg#hasKGFrameType>
                           <urn:cardiff:kg:frame:LeadStatusFrame> .
                }}
            }} LIMIT 10
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": False,
        "space_id": LD_SPACE_ID,
        "fuseki_dataset": LD_FUSEKI_DATASET,
    },
    # ---- Direct: Full MQL-style query (entity → parent frame → child frame → slot with value) ----
    {
        "label": "Direct: MQL query (entity→frame→frame→slot+value)",
        "sparql": f"""
            SELECT DISTINCT ?entity ?parentFrame ?childFrame ?slot WHERE {{
                GRAPH <{LD_GRAPH}> {{
                    ?entity <http://vital.ai/ontology/vital-core#vitaltype>
                            <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
                    ?entity <http://vital.ai/vitalgraph/direct#hasEntityFrame> ?parentFrame .
                    ?parentFrame <http://vital.ai/vitalgraph/direct#hasFrame> ?childFrame .
                    ?childFrame <http://vital.ai/vitalgraph/direct#hasSlot> ?slot .
                    ?slot <http://vital.ai/ontology/haley-ai-kg#hasKGSlotType>
                          <urn:cardiff:kg:slot:MQLv2> .
                    ?slot <http://vital.ai/ontology/haley-ai-kg#hasBooleanSlotValue> true .
                }}
            }}
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": True,
        "keys": ["entity", "parentFrame", "childFrame", "slot"],
        "space_id": LD_SPACE_ID,
        "fuseki_dataset": LD_FUSEKI_DATASET,
    },
    # ---- Direct: Count all three direct predicate types ----
    {
        "label": "Direct: count by predicate type",
        "sparql": f"""
            SELECT ?p (COUNT(*) AS ?count) WHERE {{
                GRAPH <{LD_GRAPH}> {{
                    ?s ?p ?o .
                    FILTER(?p IN (
                        <http://vital.ai/vitalgraph/direct#hasEntityFrame>,
                        <http://vital.ai/vitalgraph/direct#hasFrame>,
                        <http://vital.ai/vitalgraph/direct#hasSlot>
                    ))
                }}
            }} GROUP BY ?p ORDER BY ?p
        """,
        "type": "SELECT",
        "compare_count": True,
        "compare_values": True,
        "keys": ["p", "count"],
        "space_id": LD_SPACE_ID,
        "fuseki_dataset": LD_FUSEKI_DATASET,
    },
]

# ---------------------------------------------------------------------------
# Main comparison runner
# ---------------------------------------------------------------------------

def run_comparison():
    passed = 0
    failed = 0
    errors = []

    data_syncs = []

    print("=" * 78)
    print("Fuseki vs SQL Generator — Side-by-Side Comparison")
    print(f"  Fuseki:     {FUSEKI_URL}/{FUSEKI_DATASET}")
    print(f"  SQL space:  {SPACE_ID}")
    print(f"  Graph:      {GRAPH_URI}")
    print("=" * 78)

    # Track orchestrators per space_id so we reuse connections
    orchestrators = {}

    def get_orch(sid):
        if sid not in orchestrators:
            orchestrators[sid] = SparqlOrchestrator(space_id=sid)
        return orchestrators[sid]

    try:
      for q in COMPARISON_QUERIES:
        label = q["label"]
        sparql = q["sparql"]
        qtype = q["type"]
        # Per-query overrides
        q_space = q.get("space_id", SPACE_ID)
        q_fuseki = q.get("fuseki_dataset", FUSEKI_DATASET)
        orch = get_orch(q_space)
        print(f"\n--- {label} ---")

        # ---- Fuseki execution (same SPARQL) ----
        t0 = time.monotonic()
        if qtype == "ASK":
            fuseki_raw = query_fuseki(sparql, fuseki_dataset=q_fuseki)
            fuseki_ms = (time.monotonic() - t0) * 1000
            fuseki_bool = fuseki_ask_result(fuseki_raw)
            fuseki_err = fuseki_raw.get("error") if isinstance(fuseki_raw, dict) and "error" in fuseki_raw else None
            fuseki_rows = []
            fuseki_count = 1 if fuseki_bool is not None else 0
        elif qtype == "CONSTRUCT":
            # Fuseki CONSTRUCT returns RDF/JSON; use different Accept header
            url = f"{FUSEKI_URL}/{q_fuseki}/query"
            data = urllib.parse.urlencode({"query": sparql}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Accept": "application/rdf+json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    fuseki_raw = json.loads(resp.read().decode("utf-8"))
                fuseki_ms = (time.monotonic() - t0) * 1000
                fuseki_err = None
                # Count triples from RDF/JSON
                fuseki_count = sum(
                    len(objs)
                    for preds in fuseki_raw.values()
                    for objs in preds.values()
                )
            except Exception as e:
                fuseki_ms = (time.monotonic() - t0) * 1000
                fuseki_err = str(e)
                fuseki_count = 0
            fuseki_rows = []
            fuseki_bool = None
        else:
            fuseki_raw = query_fuseki(sparql, fuseki_dataset=q_fuseki)
            fuseki_ms = (time.monotonic() - t0) * 1000
            fuseki_err = fuseki_raw.get("error") if isinstance(fuseki_raw, dict) and "error" in fuseki_raw else None
            fuseki_rows = fuseki_select_rows(fuseki_raw)
            fuseki_count = len(fuseki_rows)
            fuseki_bool = None

        # ---- SQL pipeline execution ----
        t0 = time.monotonic()
        sql_result = orch.execute(sparql, include_sql=False)
        sql_ms = (time.monotonic() - t0) * 1000
        sql_err = sql_result.error

        if qtype == "ASK":
            sql_bool = sql_result.boolean
            sql_count = 1 if sql_bool is not None else 0
            sql_rows = []
        elif qtype == "CONSTRUCT":
            sql_count = len(sql_result.triples)
            sql_rows = []
            sql_bool = None
        else:
            sql_rows = sql_result.rows
            sql_count = sql_result.row_count
            sql_bool = None

        # ---- Display ----
        ok = True

        if fuseki_err:
            print(f"  Fuseki ERROR: {fuseki_err}")
            ok = False
        if sql_err:
            print(f"  SQL ERROR:    {sql_err}")
            ok = False

        print(f"  Fuseki: {fuseki_count:>6} rows  {fuseki_ms:>8.1f} ms")
        print(f"  SQL:    {sql_count:>6} rows  {sql_ms:>8.1f} ms")

        if fuseki_ms > 0:
            speedup = fuseki_ms / sql_ms if sql_ms > 0 else float('inf')
            if speedup > 1:
                print(f"  Speed:  SQL is {speedup:.1f}x faster")
            else:
                print(f"  Speed:  Fuseki is {1/speedup:.1f}x faster")

        # ---- ASK comparison ----
        if qtype == "ASK" and ok:
            if fuseki_bool != sql_bool:
                print(f"  MISMATCH: Fuseki={fuseki_bool}, SQL={sql_bool}")
                ok = False
            else:
                print(f"  Boolean: {sql_bool}")

        # ---- Data sync check (informational, not pass/fail) ----
        if q.get("data_sync") and ok:
            if fuseki_rows and sql_rows:
                f_val = list(fuseki_rows[0].values())[0] if fuseki_rows else "?"
                s_val = list(sql_rows[0].values())[0] if sql_rows else "?"
                if str(f_val) != str(s_val):
                    print(f"  DATA DIFF:  Fuseki={f_val}, SQL={s_val}")
                    data_syncs.append((label, f_val, s_val))
                else:
                    print(f"  DATA SYNC:  both={f_val}")

        # ---- Count comparison ----
        if q.get("compare_count") and ok:
            if fuseki_count != sql_count:
                print(f"  COUNT MISMATCH: Fuseki={fuseki_count}, SQL={sql_count}")
                ok = False

        # ---- Value comparison ----
        if q.get("compare_values") and ok and fuseki_rows and sql_rows:
            keys = q.get("keys")
            fuseki_norm = normalize_rows(fuseki_rows, keys)
            sql_norm = normalize_rows(sql_rows, keys)
            if fuseki_norm != sql_norm:
                # Show first difference
                diff_count = 0
                for i, (f_row, s_row) in enumerate(zip(fuseki_norm, sql_norm)):
                    if f_row != s_row:
                        if diff_count == 0:
                            print(f"  VALUE MISMATCH at row {i}:")
                            print(f"    Fuseki: {f_row}")
                            print(f"    SQL:    {s_row}")
                        diff_count += 1
                if diff_count > 1:
                    print(f"  ... and {diff_count - 1} more differences")
                if len(fuseki_norm) != len(sql_norm):
                    print(f"  Row count: Fuseki={len(fuseki_norm)}, SQL={len(sql_norm)}")
                ok = False
            else:
                print(f"  Values:  MATCH ({len(fuseki_norm)} rows)")

        if ok:
            print(f"  OK")
            passed += 1
        else:
            print(f"  FAIL")
            failed += 1
            errors.append(label)

    finally:
        for o in orchestrators.values():
            o.close()

    print("\n" + "=" * 78)
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if errors:
        print(f"Failed: {', '.join(errors)}")
    if data_syncs:
        print(f"\nData sync differences (Fuseki vs SQL):")
        for lbl, fv, sv in data_syncs:
            print(f"  {lbl}: Fuseki={fv}, SQL={sv}")
    print("=" * 78)

    return failed == 0


if __name__ == "__main__":
    success = run_comparison()
    sys.exit(0 if success else 1)
