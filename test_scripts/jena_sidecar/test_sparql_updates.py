"""
Live integration test: SPARQL Update operations against PostgreSQL.

Tests INSERT DATA, DELETE DATA, DELETE/INSERT WHERE, INSERT WHERE,
CLEAR, DROP, CREATE, COPY, MOVE, ADD against crud_test_exp tables.

Requires:
  - Jena sidecar running at localhost:7070
  - PostgreSQL with crud_test_exp_rdf_quad / crud_test_exp_term tables
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph_sparql_sql.jena_sparql_orchestrator import SparqlOrchestrator

SPACE = "crud_test_exp"

# Graph URIs used by tests — all cleaned up at the end
TEST_GRAPHS = [
    "urn:test:insert",
    "urn:test:delete",
    "urn:test:modify",
    "urn:test:tmpl",
    "urn:test:src",
    "urn:test:dst",
    "urn:test:moved",
    "urn:test:newgraph",
    "urn:test:delwhere",
]


def count_graph(orch, graph_uri):
    """Return the number of triples in a named graph."""
    r = orch.execute(
        f'SELECT (COUNT(*) AS ?cnt) WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}'
    )
    if r.ok and r.rows:
        return r.rows[0].get("cnt", 0)
    return -1


def query_graph(orch, graph_uri, limit=20):
    """Return rows from a named graph as list of (s, p, o) text tuples."""
    r = orch.execute(
        f'SELECT ?s ?p ?o WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }} '
        f'ORDER BY ?s ?p ?o LIMIT {limit}'
    )
    if r.ok:
        return [(row["s"], row["p"], row["o"]) for row in r.rows]
    return []


def cleanup(orch):
    """Clear all test graphs."""
    for g in TEST_GRAPHS:
        orch.execute(f"CLEAR GRAPH <{g}>")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_insert_data(orch):
    """INSERT DATA with graph, plain literal, and lang-tagged literal."""
    sparql = '''
    INSERT DATA {
        GRAPH <urn:test:insert> {
            <http://ex.org/p1> <http://ex.org/name> "Alice" .
            <http://ex.org/p1> <http://ex.org/label> "Alice"@en .
            <http://ex.org/p2> <http://ex.org/name> "Bob" .
        }
    }'''
    result = orch.execute(sparql)
    assert result.ok, f"INSERT DATA failed: {result.error}"

    cnt = count_graph(orch, "urn:test:insert")
    assert cnt == 3, f"Expected 3 rows, got {cnt}"

    rows = query_graph(orch, "urn:test:insert")
    subjects = {r[0] for r in rows}
    assert "http://ex.org/p1" in subjects
    assert "http://ex.org/p2" in subjects
    return True


def test_delete_data(orch):
    """DELETE DATA removes a specific triple."""
    # Setup
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:delete> {
            <http://ex.org/a> <http://ex.org/p> "val1" .
            <http://ex.org/a> <http://ex.org/p> "val2" .
            <http://ex.org/b> <http://ex.org/p> "val3" .
        }
    }''')
    assert count_graph(orch, "urn:test:delete") == 3

    # Delete one triple
    result = orch.execute('''
    DELETE DATA {
        GRAPH <urn:test:delete> {
            <http://ex.org/a> <http://ex.org/p> "val1" .
        }
    }''')
    assert result.ok, f"DELETE DATA failed: {result.error}"
    assert count_graph(orch, "urn:test:delete") == 2

    # Verify the right triple was deleted
    rows = query_graph(orch, "urn:test:delete")
    objects = {r[2] for r in rows}
    assert "val1" not in objects, "val1 should have been deleted"
    assert "val2" in objects
    assert "val3" in objects
    return True


def test_delete_insert_where(orch):
    """DELETE/INSERT WHERE renames a predicate while preserving other data."""
    # Setup
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:modify> {
            <http://ex.org/p1> <http://ex.org/old_name> "Alice" .
            <http://ex.org/p1> <http://ex.org/old_name> "Alice2" .
            <http://ex.org/p2> <http://ex.org/old_name> "Bob" .
            <http://ex.org/p2> <http://ex.org/keep> "keep_me" .
        }
    }''')
    assert count_graph(orch, "urn:test:modify") == 4

    # Rename predicate
    result = orch.execute('''
    DELETE { GRAPH <urn:test:modify> { ?s <http://ex.org/old_name> ?o } }
    INSERT { GRAPH <urn:test:modify> { ?s <http://ex.org/new_name> ?o } }
    WHERE  { GRAPH <urn:test:modify> { ?s <http://ex.org/old_name> ?o } }
    ''')
    assert result.ok, f"DELETE/INSERT WHERE failed: {result.error}"

    # Verify: same count, predicates changed
    assert count_graph(orch, "urn:test:modify") == 4

    rows = query_graph(orch, "urn:test:modify")
    predicates = {r[1] for r in rows}
    assert "http://ex.org/old_name" not in predicates, "old_name should be gone"
    assert "http://ex.org/new_name" in predicates, "new_name should exist"
    assert "http://ex.org/keep" in predicates, "keep should be preserved"

    # Verify all values preserved
    objects = sorted(r[2] for r in rows)
    assert objects == ["Alice", "Alice2", "Bob", "keep_me"]
    return True


def test_insert_where_template(orch):
    """INSERT WHERE derives new triples from existing data."""
    # Setup
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:tmpl> {
            <http://ex.org/x> <http://ex.org/name> "Xavier" .
            <http://ex.org/y> <http://ex.org/name> "Yara" .
        }
    }''')
    assert count_graph(orch, "urn:test:tmpl") == 2

    # Derive label from name
    result = orch.execute('''
    INSERT { GRAPH <urn:test:tmpl> { ?s <http://ex.org/label> ?n } }
    WHERE  { GRAPH <urn:test:tmpl> { ?s <http://ex.org/name> ?n } }
    ''')
    assert result.ok, f"INSERT WHERE failed: {result.error}"

    # Should now have 4 triples (2 name + 2 label)
    assert count_graph(orch, "urn:test:tmpl") == 4

    rows = query_graph(orch, "urn:test:tmpl")
    predicates = {r[1] for r in rows}
    assert "http://ex.org/label" in predicates
    assert "http://ex.org/name" in predicates
    return True


def test_clear_graph(orch):
    """CLEAR GRAPH removes all triples from a specific graph."""
    # Setup
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:insert> {
            <http://ex.org/a> <http://ex.org/p> "x" .
        }
    }''')
    assert count_graph(orch, "urn:test:insert") >= 1

    result = orch.execute("CLEAR GRAPH <urn:test:insert>")
    assert result.ok, f"CLEAR GRAPH failed: {result.error}"
    assert count_graph(orch, "urn:test:insert") == 0
    return True


def test_create_graph(orch):
    """CREATE GRAPH ensures the graph term exists."""
    result = orch.execute("CREATE GRAPH <urn:test:newgraph>")
    assert result.ok, f"CREATE GRAPH failed: {result.error}"
    return True


def test_drop_graph(orch):
    """DROP GRAPH removes all data from a graph."""
    # Setup
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:dst> {
            <http://ex.org/a> <http://ex.org/p> "x" .
        }
    }''')
    assert count_graph(orch, "urn:test:dst") >= 1

    result = orch.execute("DROP GRAPH <urn:test:dst>")
    assert result.ok, f"DROP GRAPH failed: {result.error}"
    assert count_graph(orch, "urn:test:dst") == 0
    return True


def test_copy(orch):
    """COPY source TO dest replaces dest with source contents."""
    # Setup source
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:src> {
            <http://ex.org/a> <http://ex.org/p> "one" .
            <http://ex.org/b> <http://ex.org/p> "two" .
        }
    }''')
    assert count_graph(orch, "urn:test:src") == 2

    result = orch.execute("COPY <urn:test:src> TO <urn:test:dst>")
    assert result.ok, f"COPY failed: {result.error}"
    assert count_graph(orch, "urn:test:dst") == 2
    assert count_graph(orch, "urn:test:src") == 2  # source unchanged
    return True


def test_add(orch):
    """ADD source TO dest adds source triples without clearing dest."""
    # Setup: src has 2, dst has 2 (from test_copy)
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:src> {
            <http://ex.org/c> <http://ex.org/p> "three" .
        }
    }''')

    result = orch.execute("ADD <urn:test:src> TO <urn:test:dst>")
    assert result.ok, f"ADD failed: {result.error}"

    # dst should have 2 (from COPY) + 3 (all of src) = 5
    dst_cnt = count_graph(orch, "urn:test:dst")
    assert dst_cnt == 5, f"Expected 5 rows in dst, got {dst_cnt}"
    return True


def test_move(orch):
    """MOVE source TO dest copies then drops source."""
    src_cnt = count_graph(orch, "urn:test:src")
    assert src_cnt > 0, "src should have data before MOVE"

    result = orch.execute("MOVE <urn:test:src> TO <urn:test:moved>")
    assert result.ok, f"MOVE failed: {result.error}"

    assert count_graph(orch, "urn:test:src") == 0, "src should be empty after MOVE"
    assert count_graph(orch, "urn:test:moved") == src_cnt, \
        f"moved should have {src_cnt} rows"
    return True


def test_delete_where_shorthand(orch):
    """DELETE WHERE shorthand deletes matching triples."""
    # Setup
    orch.execute('''
    INSERT DATA {
        GRAPH <urn:test:delwhere> {
            <http://ex.org/a> <http://ex.org/p> "val1" .
            <http://ex.org/a> <http://ex.org/q> "val2" .
            <http://ex.org/b> <http://ex.org/p> "val3" .
        }
    }''')
    assert count_graph(orch, "urn:test:delwhere") == 3

    # DELETE WHERE — remove all triples with subject <http://ex.org/a>
    result = orch.execute(
        'DELETE WHERE { GRAPH <urn:test:delwhere> { <http://ex.org/a> ?p ?o } }'
    )
    assert result.ok, f"DELETE WHERE failed: {result.error}"

    # Only <http://ex.org/b> triple should remain
    cnt = count_graph(orch, "urn:test:delwhere")
    assert cnt == 1, f"Expected 1 row after DELETE WHERE, got {cnt}"

    rows = query_graph(orch, "urn:test:delwhere")
    assert rows[0][0] == "http://ex.org/b", f"Expected subject b, got {rows[0][0]}"
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TESTS = [
    ("INSERT DATA", test_insert_data),
    ("DELETE DATA", test_delete_data),
    ("DELETE WHERE (shorthand)", test_delete_where_shorthand),
    ("DELETE/INSERT WHERE", test_delete_insert_where),
    ("INSERT WHERE (template)", test_insert_where_template),
    ("CLEAR GRAPH", test_clear_graph),
    ("CREATE GRAPH", test_create_graph),
    ("DROP GRAPH", test_drop_graph),
    ("COPY", test_copy),
    ("ADD", test_add),
    ("MOVE", test_move),
]


def main():
    passed = 0
    failed = 0
    errors = []

    print("=" * 70)
    print("SPARQL Update Live Tests")
    print(f"Space: {SPACE}")
    print("=" * 70)

    with SparqlOrchestrator(space_id=SPACE) as orch:
        # Clean slate
        cleanup(orch)

        for label, test_fn in TESTS:
            print(f"\n--- {label} ---")
            try:
                test_fn(orch)
                print(f"  PASS")
                passed += 1
            except AssertionError as e:
                print(f"  FAIL: {e}")
                failed += 1
                errors.append((label, str(e)))
            except Exception as e:
                print(f"  ERROR: {type(e).__name__}: {e}")
                failed += 1
                errors.append((label, f"{type(e).__name__}: {e}"))

        # Final cleanup
        cleanup(orch)

    print(f"\n{'=' * 70}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")

    if errors:
        print(f"\n--- Failures ---")
        for label, err in errors:
            print(f"  [{label}] {err}")

    print(f"{'=' * 70}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
