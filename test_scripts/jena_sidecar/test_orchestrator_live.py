"""
Live integration test: full SPARQL → SQL → PostgreSQL execution.

Requires:
  - Jena sidecar running at localhost:7070
  - PostgreSQL with RDF data (lead_test space)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

SPACE = "lead_test"

QUERIES = [
    # (label, sparql, min_expected_rows, max_expected_rows)
    (
        "Simple triple scan LIMIT 5",
        "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5",
        5, 5,
    ),
    (
        "Count all triples",
        """SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }""",
        1, 1,
    ),
    (
        "Entities by vitaltype",
        """SELECT ?s WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype>
               <http://vital.ai/ontology/haley-ai-kg#KGEntity>
        } LIMIT 10""",
        1, 10,
    ),
    (
        "Entity with name (OPTIONAL)",
        """SELECT ?s ?name WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype>
               <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            OPTIONAL {
                ?s <http://vital.ai/ontology/vital-core#hasName> ?name
            }
        } LIMIT 10""",
        1, 10,
    ),
    (
        "DISTINCT predicates LIMIT 20",
        """SELECT DISTINCT ?p WHERE { ?s ?p ?o } LIMIT 20""",
        1, 20,
    ),
    (
        "ORDER BY with OFFSET",
        """SELECT ?s ?p WHERE { ?s ?p ?o } ORDER BY ?p LIMIT 5 OFFSET 10""",
        5, 5,
    ),
    (
        "GRAPH scoped query",
        """SELECT ?s ?p ?o WHERE {
            GRAPH <urn:lead_test> { ?s ?p ?o }
        } LIMIT 5""",
        0, 5,  # may be 0 if no data in that graph name
    ),
    (
        "UNION of two types",
        """SELECT ?s WHERE {
            { ?s <http://vital.ai/ontology/vital-core#vitaltype>
                 <http://vital.ai/ontology/haley-ai-kg#KGTextSlot> }
            UNION
            { ?s <http://vital.ai/ontology/vital-core#vitaltype>
                 <http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot> }
        } LIMIT 10""",
        1, 10,
    ),
    (
        "FILTER with string comparison",
        """SELECT ?s ?name WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
            FILTER(CONTAINS(?name, "test"))
        } LIMIT 10""",
        0, 10,  # may be 0 if no matching names
    ),
    # ---- Property path queries ----
    (
        "Path: simple link (same as BGP)",
        """SELECT ?s ?o WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> ?o
        } LIMIT 5""",
        1, 5,
    ),
    (
        "Path: alternative (|)",
        """SELECT ?s ?o WHERE {
            ?s (<http://vital.ai/ontology/vital-core#hasName>|<http://vital.ai/ontology/vital-core#vitaltype>) ?o
        } LIMIT 10""",
        1, 10,
    ),
    (
        "Path: sequence (/)",
        """SELECT ?s ?o WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype>/<http://vital.ai/ontology/vital-core#vitaltype> ?o
        } LIMIT 5""",
        0, 5,  # may be 0 if types don't chain
    ),
    (
        "Path: one-or-more (+)",
        """SELECT ?s ?o WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype>+ ?o
        } LIMIT 5""",
        0, 5,
    ),
    (
        "Path: zero-or-one (?)",
        """SELECT ?s ?o WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype>? ?o
        } LIMIT 5""",
        0, 5,
    ),
    (
        "Path: inverse (^)",
        """SELECT ?s ?o WHERE {
            ?s ^<http://vital.ai/ontology/vital-core#vitaltype> ?o
        } LIMIT 5""",
        0, 5,
    ),
    # ---- Subquery tests ----
    (
        "Subquery: inner LIMIT joined to outer",
        """SELECT ?s ?name WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
            {
                SELECT ?s WHERE {
                    ?s <http://vital.ai/ontology/vital-core#vitaltype>
                       <http://vital.ai/ontology/haley-ai-kg#KGEntity>
                } LIMIT 5
            }
        }""",
        1, 5,
    ),
    (
        "Subquery: COUNT in inner",
        """SELECT ?type ?count WHERE {
            {
                SELECT ?type (COUNT(?s) AS ?count) WHERE {
                    ?s <http://vital.ai/ontology/vital-core#vitaltype> ?type
                } GROUP BY ?type LIMIT 5
            }
        }""",
        1, 5,
    ),
    # ---- ASK / CONSTRUCT / DESCRIBE ----
    (
        "ASK: exists",
        """ASK { ?s <http://vital.ai/ontology/vital-core#vitaltype>
                   <http://vital.ai/ontology/haley-ai-kg#KGEntity> }""",
        1, 1,  # ASK always returns 1 row
    ),
    (
        "CONSTRUCT: simple",
        """CONSTRUCT { ?s <http://example.org/label> ?name }
        WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        } LIMIT 5""",
        1, 5,
    ),
    # ---- ORDER BY expression tests ----
    (
        "ORDER BY STRLEN expression",
        """SELECT ?s ?name WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        } ORDER BY STRLEN(?name) LIMIT 5""",
        1, 5,
    ),
    (
        "ORDER BY STRLEN DESC",
        """SELECT ?s ?name (STRLEN(?name) AS ?len) WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        } ORDER BY DESC(STRLEN(?name)) LIMIT 5""",
        1, 5,
    ),
    (
        "ORDER BY UCASE expression",
        """SELECT ?s ?name WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        } ORDER BY UCASE(?name) LIMIT 5""",
        1, 5,
    ),
    (
        "ORDER BY arithmetic expression",
        """SELECT ?s ?name (STRLEN(?name) AS ?len) WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        } ORDER BY (STRLEN(?name) * 2) LIMIT 5""",
        1, 5,
    ),
]


def main():
    passed = 0
    failed = 0
    errors = []

    print("=" * 70)
    print("Live Orchestrator Test: SPARQL → SQL → PostgreSQL")
    print(f"Space: {SPACE}")
    print("=" * 70)

    with SparqlOrchestrator(space_id=SPACE) as orch:
        for label, sparql, min_rows, max_rows in QUERIES:
            print(f"\n--- {label} ---")
            result = orch.execute(sparql, include_sql=True)

            if not result.ok:
                print(f"  FAIL: {result.error}")
                if result.sql:
                    print(f"  SQL:\n{result.sql[:300]}")
                failed += 1
                errors.append((label, result.error, result.sql))
                continue

            print(f"  Rows: {result.row_count}  Columns: {result.columns}")
            if result.timing:
                parts = [f"{k}={v:.1f}" for k, v in result.timing.items()]
                print(f"  Timing: {', '.join(parts)}")

            # Show first 3 rows
            for i, row in enumerate(result.rows[:3]):
                vals = {k: str(v)[:60] for k, v in row.items()}
                print(f"    [{i}] {vals}")
            if result.row_count > 3:
                print(f"    ... ({result.row_count - 3} more)")

            # Check row count bounds
            if min_rows <= result.row_count <= max_rows:
                print(f"  OK")
                passed += 1
            elif result.row_count < min_rows:
                print(f"  FAIL: expected >= {min_rows} rows, got {result.row_count}")
                failed += 1
                errors.append((label, f"too few rows: {result.row_count}", result.sql))
            else:
                print(f"  FAIL: expected <= {max_rows} rows, got {result.row_count}")
                failed += 1
                errors.append((label, f"too many rows: {result.row_count}", result.sql))

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    if errors:
        print(f"\n--- Failures ---")
        for label, err, sql in errors:
            print(f"\n  [{label}] {err}")
            if sql:
                print(f"  SQL:\n{sql[:400]}")

    print(f"{'=' * 70}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
