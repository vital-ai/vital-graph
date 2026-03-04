"""
End-to-end: SPARQL → Sidecar → AST Mapper → SQL Generator → PostgreSQL SQL.

Sends real SPARQL through the full pipeline and prints the generated SQL.
Verifies that each step succeeds and the SQL is non-empty.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sidecar_client import SidecarClient
from vitalgraph_sparql_sql.jena_ast_mapper import map_compile_response
from vitalgraph_sparql_sql.jena_sql_generator import generate_sql

SPACE = "lead_test"

QUERIES = [
    (
        "Simple SELECT",
        "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10",
    ),
    (
        "SELECT with URI predicate",
        """SELECT ?s ?name WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        } LIMIT 5""",
    ),
    (
        "SELECT DISTINCT with FILTER",
        """SELECT DISTINCT ?s WHERE {
            ?s <http://vital.ai/ontology/vital-core#vitaltype> ?t .
            FILTER(?t = <http://vital.ai/ontology/haley-ai-kg#KGEntity>)
        }""",
    ),
    (
        "OPTIONAL pattern",
        """SELECT ?s ?name WHERE {
            ?s a <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
            OPTIONAL { ?s <http://vital.ai/ontology/vital-core#hasName> ?name }
        } LIMIT 20""",
    ),
    (
        "UNION",
        """SELECT ?s WHERE {
            { ?s a <http://vital.ai/ontology/haley-ai-kg#KGTextSlot> }
            UNION
            { ?s a <http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot> }
        } LIMIT 5""",
    ),
    (
        "ORDER BY with LIMIT/OFFSET",
        """SELECT ?s ?name WHERE {
            ?s <http://vital.ai/ontology/vital-core#hasName> ?name
        } ORDER BY ?name LIMIT 10 OFFSET 5""",
    ),
    (
        "GRAPH scoped",
        """SELECT ?s ?p ?o WHERE {
            GRAPH <urn:lead_test> { ?s ?p ?o }
        } LIMIT 5""",
    ),
    (
        "INSERT DATA",
        'INSERT DATA { <http://ex.org/s> <http://ex.org/p> "hello" }',
    ),
]


def main():
    passed = 0
    failed = 0

    print("=" * 70)
    print("End-to-End: SPARQL → Sidecar → Mapper → SQL Generator")
    print("=" * 70)

    with SidecarClient() as client:
        for label, sparql in QUERIES:
            print(f"\n{'=' * 60}")
            print(f"  {label}")
            print(f"{'=' * 60}")
            print(f"SPARQL: {sparql.strip()[:80]}...")

            try:
                # Step 1: Sidecar
                raw = client.compile(sparql)
                result = map_compile_response(raw)
                if not result.ok:
                    print(f"  FAIL: sidecar error: {result.error}")
                    failed += 1
                    continue

                # Step 2: Generate SQL
                sql = generate_sql(result, SPACE)
                if not sql or len(sql.strip()) < 10:
                    print(f"  FAIL: empty or trivial SQL")
                    failed += 1
                    continue

                print(f"\nGenerated SQL:\n{sql}")
                passed += 1

            except Exception as e:
                print(f"  FAIL: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                failed += 1

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'=' * 70}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
