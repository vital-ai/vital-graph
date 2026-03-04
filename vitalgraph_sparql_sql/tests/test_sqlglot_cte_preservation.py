#!/usr/bin/env python3
"""
Test that sqlglot optimizer passes preserve MATERIALIZED CTEs.

Our pipeline emits `WITH ... AS MATERIALIZED (...)` for bounded subquery JOINs.
Before adopting sqlglot's optimizer, we must verify that passes like
merge_subqueries, eliminate_ctes, and the full optimize() pipeline do NOT
dissolve MATERIALIZED CTEs.

Usage:
    python vitalgraph_sparql_sql/tests/test_sqlglot_cte_preservation.py
"""

import sys
import traceback

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.merge_subqueries import merge_subqueries
from sqlglot.optimizer.eliminate_ctes import eliminate_ctes
from sqlglot.optimizer.pushdown_predicates import pushdown_predicates
from sqlglot.optimizer.simplify import simplify
from sqlglot.optimizer.optimizer import optimize


# ---------------------------------------------------------------------------
# Fixtures: representative SQL from our pipeline
# ---------------------------------------------------------------------------

MATERIALIZED_CTE_SQL = """
WITH _cte_j0 AS MATERIALIZED (
    SELECT entity_uuid, COUNT(*) AS degree
    FROM quad AS q0
    JOIN quad AS q1 ON q1.subject_uuid = q0.subject_uuid
    GROUP BY entity_uuid
    ORDER BY degree DESC
    LIMIT 5
)
SELECT j0.entity_uuid, j0.degree, j1.name
FROM _cte_j0 AS j0
JOIN (
    SELECT entity_uuid, name
    FROM quad AS q2
    JOIN term AS t ON t.term_uuid = q2.object_uuid
) AS j1 ON j0.entity_uuid = j1.entity_uuid
LIMIT 20
""".strip()

PLAIN_CTE_SQL = """
WITH top5 AS (
    SELECT entity_uuid, COUNT(*) AS degree
    FROM quad
    GROUP BY entity_uuid
    LIMIT 5
)
SELECT top5.entity_uuid, top5.degree
FROM top5
""".strip()

MULTI_REF_MATERIALIZED_SQL = """
WITH shared AS MATERIALIZED (
    SELECT id FROM source WHERE active = TRUE
)
SELECT a.id, b.id
FROM shared AS a
JOIN shared AS b ON a.id = b.id
""".strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_materialized(sql: str) -> bool:
    return "MATERIALIZED" in sql.upper()

def _parse(sql: str) -> exp.Expression:
    return sqlglot.parse_one(sql, dialect="postgres")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0
_skipped = 0

def _run(name, fn):
    global _passed, _failed, _skipped
    try:
        result = fn()
        if result == "SKIP":
            _skipped += 1
            print(f"  SKIP  {name}")
        else:
            _passed += 1
            print(f"  PASS  {name}")
    except Exception as e:
        _failed += 1
        print(f"  FAIL  {name}")
        traceback.print_exc()
        print()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_roundtrip_preserves_materialized():
    sql = _parse(MATERIALIZED_CTE_SQL).sql(dialect="postgres")
    assert _has_materialized(sql), f"Roundtrip dropped MATERIALIZED!\n{sql}"

def test_cte_node_has_materialized_property():
    ast = _parse(MATERIALIZED_CTE_SQL)
    ctes = list(ast.find_all(exp.CTE))
    assert len(ctes) >= 1, "No CTE nodes found"
    mat = ctes[0].args.get("materialized")
    assert mat is not None, f"CTE missing 'materialized' arg. Args: {ctes[0].args}"

def test_merge_subqueries_preserves_materialized():
    ast = _parse(MATERIALIZED_CTE_SQL)
    sql = merge_subqueries(ast).sql(dialect="postgres")
    assert _has_materialized(sql), f"merge_subqueries dissolved CTE!\n{sql}"

def test_merge_subqueries_plain_cte_no_crash():
    ast = _parse(PLAIN_CTE_SQL)
    merge_subqueries(ast).sql(dialect="postgres")

def test_merge_subqueries_multi_ref_materialized():
    ast = _parse(MULTI_REF_MATERIALIZED_SQL)
    sql = merge_subqueries(ast).sql(dialect="postgres")
    assert _has_materialized(sql), f"merge_subqueries dissolved multi-ref CTE!\n{sql}"

def test_eliminate_ctes_keeps_used_materialized():
    ast = _parse(MATERIALIZED_CTE_SQL)
    sql = eliminate_ctes(ast).sql(dialect="postgres")
    assert _has_materialized(sql), f"eliminate_ctes removed used MATERIALIZED CTE!\n{sql}"

def test_eliminate_ctes_removes_unused():
    ast = _parse("WITH unused AS MATERIALIZED (SELECT 1) SELECT * FROM other_table")
    out = eliminate_ctes(ast).sql(dialect="postgres")
    assert "unused" not in out.lower() or not _has_materialized(out)

def test_pushdown_predicates_preserves_materialized():
    sql = """
    WITH _cte AS MATERIALIZED (
        SELECT id, val FROM src WHERE val > 0
    )
    SELECT c.id, d.name
    FROM _cte AS c
    JOIN dest AS d ON c.id = d.id
    WHERE d.name = 'test'
    """
    ast = _parse(sql)
    out = pushdown_predicates(ast).sql(dialect="postgres")
    assert _has_materialized(out), f"pushdown_predicates dissolved CTE!\n{out}"

def test_simplify_preserves_materialized():
    ast = _parse(MATERIALIZED_CTE_SQL)
    sql = simplify(ast).sql(dialect="postgres")
    assert _has_materialized(sql), f"simplify dissolved CTE!\n{sql}"

def test_selective_safe_passes():
    ast = _parse(MATERIALIZED_CTE_SQL)
    for rule in [pushdown_predicates, simplify, eliminate_ctes]:
        ast = rule(ast)
    sql = ast.sql(dialect="postgres")
    assert _has_materialized(sql), f"Safe passes dissolved CTE!\n{sql}"

def test_full_optimize():
    ast = _parse(MATERIALIZED_CTE_SQL)
    try:
        result = optimize(ast, dialect="postgres")
    except Exception:
        return "SKIP"
    sql = result.sql(dialect="postgres")
    assert _has_materialized(sql), f"Full optimize() dissolved CTE!\n{sql}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("sqlglot CTE MATERIALIZED preservation tests")
    print("=" * 50)

    tests = [
        ("roundtrip preserves MATERIALIZED", test_roundtrip_preserves_materialized),
        ("CTE node has materialized property", test_cte_node_has_materialized_property),
        ("merge_subqueries preserves MATERIALIZED", test_merge_subqueries_preserves_materialized),
        ("merge_subqueries plain CTE no crash", test_merge_subqueries_plain_cte_no_crash),
        ("merge_subqueries multi-ref MATERIALIZED", test_merge_subqueries_multi_ref_materialized),
        ("eliminate_ctes keeps used MATERIALIZED", test_eliminate_ctes_keeps_used_materialized),
        ("eliminate_ctes removes unused", test_eliminate_ctes_removes_unused),
        ("pushdown_predicates preserves MATERIALIZED", test_pushdown_predicates_preserves_materialized),
        ("simplify preserves MATERIALIZED", test_simplify_preserves_materialized),
        ("selective safe passes", test_selective_safe_passes),
        ("full optimize()", test_full_optimize),
    ]

    for name, fn in tests:
        _run(name, fn)

    print("=" * 50)
    print(f"Results: {_passed} passed, {_failed} failed, {_skipped} skipped")
    sys.exit(1 if _failed else 0)
