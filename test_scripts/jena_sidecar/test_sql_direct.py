"""
Direct SQL testing against PostgreSQL.

Generates SQL from SPARQL via the sidecar, then runs each SQL statement
directly against the database with timing. Use this to isolate slow queries.

Usage:
    python test_scripts/jena_sidecar/test_sql_direct.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sidecar_client import SidecarClient
from vitalgraph_sparql_sql.jena_ast_mapper import map_compile_response
from vitalgraph_sparql_sql.jena_sql_generator import generate_sql
from vitalgraph_sparql_sql import db

SPACE = "lead_test"

# --------------------------------------------------------------------------
# Test queries: (label, sql, timeout_seconds)
# Start simple, build up complexity
# --------------------------------------------------------------------------

RAW_SQL_TESTS = [
    ("Row count", "SELECT COUNT(*) AS cnt FROM lead_test_rdf_quad", 5),
    ("Term count", "SELECT COUNT(*) AS cnt FROM lead_test_term", 5),
    ("Raw quad LIMIT 3", "SELECT subject_uuid, predicate_uuid, object_uuid FROM lead_test_rdf_quad LIMIT 3", 2),
    ("1 JOIN LIMIT 5",
     """SELECT t.term_text AS s
        FROM lead_test_rdf_quad q
        JOIN lead_test_term t ON q.subject_uuid = t.term_uuid
        LIMIT 5""", 5),
    ("3 JOINs LIMIT 5",
     """SELECT t0.term_text AS s, t1.term_text AS p, t2.term_text AS o
        FROM lead_test_rdf_quad q
        JOIN lead_test_term t0 ON q.subject_uuid = t0.term_uuid
        JOIN lead_test_term t1 ON q.predicate_uuid = t1.term_uuid
        JOIN lead_test_term t2 ON q.object_uuid = t2.term_uuid
        LIMIT 5""", 10),
    ("ORDER BY 1 JOIN LIMIT 5",
     """SELECT q.subject_uuid, t1.term_text AS p
        FROM lead_test_rdf_quad q
        JOIN lead_test_term t1 ON q.predicate_uuid = t1.term_uuid
        ORDER BY t1.term_text
        LIMIT 5 OFFSET 10""", 30),
    ("DISTINCT 1 JOIN LIMIT 20",
     """SELECT DISTINCT t1.term_text AS p
        FROM lead_test_rdf_quad q
        JOIN lead_test_term t1 ON q.predicate_uuid = t1.term_uuid
        LIMIT 20""", 30),
]

SPARQL_TESTS = [
    ("Simple LIMIT 5",
     "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 5"),
    ("COUNT",
     "SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }"),
    ("Entities by type LIMIT 10",
     """SELECT ?s WHERE {
         ?s <http://vital.ai/ontology/vital-core#vitaltype>
            <http://vital.ai/ontology/haley-ai-kg#KGEntity>
     } LIMIT 10"""),
    ("OPTIONAL LIMIT 10",
     """SELECT ?s ?name WHERE {
         ?s <http://vital.ai/ontology/vital-core#vitaltype>
            <http://vital.ai/ontology/haley-ai-kg#KGEntity> .
         OPTIONAL {
             ?s <http://vital.ai/ontology/vital-core#hasName> ?name
         }
     } LIMIT 10"""),
    ("DISTINCT predicates LIMIT 20",
     "SELECT DISTINCT ?p WHERE { ?s ?p ?o } LIMIT 20"),
    ("ORDER BY LIMIT 5 OFFSET 10",
     "SELECT ?s ?p WHERE { ?s ?p ?o } ORDER BY ?p LIMIT 5 OFFSET 10"),
    ("UNION LIMIT 10",
     """SELECT ?s WHERE {
         { ?s <http://vital.ai/ontology/vital-core#vitaltype>
              <http://vital.ai/ontology/haley-ai-kg#KGTextSlot> }
         UNION
         { ?s <http://vital.ai/ontology/vital-core#vitaltype>
              <http://vital.ai/ontology/haley-ai-kg#KGIntegerSlot> }
     } LIMIT 10"""),
    ("FILTER CONTAINS LIMIT 10",
     """SELECT ?s ?name WHERE {
         ?s <http://vital.ai/ontology/vital-core#hasName> ?name .
         FILTER(CONTAINS(?name, "test"))
     } LIMIT 10"""),
]


def run_raw_sql(label, sql, timeout):
    print(f"\n--- {label} ---")
    print(f"  SQL: {sql[:120].strip()}...")
    try:
        t0 = time.time()
        rows = db.execute_query(sql)
        elapsed = (time.time() - t0) * 1000
        print(f"  OK: {len(rows)} rows, {elapsed:.0f}ms")
        for r in rows[:3]:
            vals = {k: str(v)[:50] for k, v in r.items()}
            print(f"    {vals}")
        if len(rows) > 3:
            print(f"    ... ({len(rows) - 3} more)")
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def run_sparql_to_sql(label, sparql, client):
    print(f"\n--- {label} ---")
    print(f"  SPARQL: {sparql[:80].strip()}...")

    # Generate SQL
    try:
        raw = client.compile(sparql)
        result = map_compile_response(raw)
        sql = generate_sql(result, SPACE)
    except Exception as e:
        print(f"  GENERATE ERROR: {e}")
        return False

    print(f"  SQL: {sql[:200].strip()}")

    # Execute SQL
    try:
        t0 = time.time()
        rows = db.execute_query(sql)
        elapsed = (time.time() - t0) * 1000
        print(f"  OK: {len(rows)} rows, {elapsed:.0f}ms")
        for r in rows[:3]:
            vals = {k: str(v)[:60] for k, v in r.items()}
            print(f"    {vals}")
        if len(rows) > 3:
            print(f"    ... ({len(rows) - 3} more)")
        return True
    except Exception as e:
        print(f"  EXECUTE ERROR: {e}")
        print(f"  FULL SQL:\n{sql}")
        return False


def main():
    print("=" * 70)
    print("Direct SQL Testing Against PostgreSQL")
    print(f"Space: {SPACE}")
    print("=" * 70)

    # Part 1: Raw SQL tests
    print("\n### PART 1: Raw SQL (no SPARQL) ###")
    raw_pass = 0
    raw_fail = 0
    for label, sql, timeout in RAW_SQL_TESTS:
        if run_raw_sql(label, sql, timeout):
            raw_pass += 1
        else:
            raw_fail += 1

    # Part 2: SPARQL → SQL → Execute
    print("\n\n### PART 2: SPARQL → SQL → PostgreSQL ###")
    client = SidecarClient()
    sparql_pass = 0
    sparql_fail = 0
    for label, sparql in SPARQL_TESTS:
        if run_sparql_to_sql(label, sparql, client):
            sparql_pass += 1
        else:
            sparql_fail += 1
    client.close()

    # Summary
    print(f"\n{'=' * 70}")
    print(f"Raw SQL:   {raw_pass} passed, {raw_fail} failed")
    print(f"SPARQL→SQL: {sparql_pass} passed, {sparql_fail} failed")
    print(f"{'=' * 70}")
    return 0 if (raw_fail + sparql_fail) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
