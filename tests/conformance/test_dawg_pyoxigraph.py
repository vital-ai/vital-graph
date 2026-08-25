"""DAWG SPARQL 1.1 conformance tests — pyoxigraph baseline.

Wraps the existing DAWG test runner as pytest parameterized tests.
Each test case from the W3C manifest becomes a separate pytest item.
No database or sidecar required — runs entirely in-memory via pyoxigraph.

Known failures are marked xfail so the suite stays green while we track
conformance progress.

Usage:
    # Run all P0 categories
    pytest tests/conformance/test_dawg_pyoxigraph.py -v

    # Run a specific category
    pytest tests/conformance/test_dawg_pyoxigraph.py -k "bind"

    # Show xfail details
    pytest tests/conformance/test_dawg_pyoxigraph.py -v --runxfail
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import pytest

from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_manifest_parser import (
    DawgTestCase,
    parse_manifest,
    get_manifest_path,
    discover_categories,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_oxigraph_executor import (
    execute_query,
    SparqlExecutionError,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_srx_parser import (
    UnsupportedResultFormat,
    parse_result_file,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_result_comparator import (
    compare_results,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAWG_ROOT = _PROJECT_ROOT / "tests" / "conformance" / "dawg_data"
JENA_ARQ_ROOT = _PROJECT_ROOT / "jena-main-source" / "jena-arq" / "testing" / "ARQ"

# ---------------------------------------------------------------------------
# P0 categories — most relevant to our SQL pipeline correctness
# ---------------------------------------------------------------------------

P0_CATEGORIES = [
    "bind",
    "aggregates",
    "functions",
    "negation",
    "exists",
    "grouping",
]

# All query categories
QUERY_CATEGORIES = P0_CATEGORIES + [
    "bindings",
    "cast",
    "construct",
    "csv-tsv-res",
    "json-res",
    "project-expression",
    "property-path",
    "subquery",
]

# Known xfail tests: (category, test_name) -> reason
# These are tests where pyoxigraph has known limitations or the test
# exercises features outside our scope. Update as conformance improves.
XFAIL_TESTS = {
    # Exposed 2026-08-24 when the result parser and query executor were given a
    # base IRI (issues/130). Both were SKIPPING before -- their result file and
    # query use relative IRIs, so neither could be read at all. Both are the
    # same ORACLE defect: pyoxigraph does not enumerate a named graph that is
    # empty, so it returns one row fewer than the manifest requires. The
    # aggregates manifest states the rule outright -- "counting no results
    # without grouping always returns a single result per named graph".
    ("aggregates", "COUNT: no GROUP BY inside of GRAPH"):
        "pyoxigraph omits the empty named graph; the manifest counts it",
    ("bindings", "VALUES inside GRAPH binding the same variable as the graph name"):
        "pyoxigraph omits the empty named graph; the manifest counts it",
    # --- aggregates ---
    ("aggregates", "GROUP_CONCAT with one element"):
        "pyoxigraph GROUP_CONCAT separator handling",
    ("aggregates", "GROUP_CONCAT with same language tag"):
        "pyoxigraph GROUP_CONCAT language tag propagation",
    ("aggregates", "HAVING: multiple conditions"):
        "pyoxigraph HAVING multi-condition evaluation",
    # --- csv-tsv-res ---
    # This suite has listed csv-tsv-res and json-res in QUERY_CATEGORIES all
    # along; they were skipping silently because parse_result_file returned None
    # for .csv/.tsv. With the parsers added (2026-08-16) they run, and this one
    # exposes pyoxigraph canonicalising `"1.0E6"^^xsd:double` to `1000000`.
    # RDF 1.1 makes the lexical form part of a literal's identity, so the
    # manifest is right and the oracle is not. Our SQL pipeline returns `1.0E6`
    # and passes the same case.
    ("csv-tsv-res", "csv03 - CSV Result Format"):
        "pyoxigraph canonicalises xsd:double lexical form; the manifest preserves it",
    # --- negation ---
    ("negation", "outer GRAPH operator does not affect MINUS disjointness"):
        "pyoxigraph GRAPH + MINUS interaction",
    # --- exists ---
    ("exists", "Exists within graph pattern"):
        "pyoxigraph EXISTS within GRAPH pattern",
    # --- cast ---
    ("cast", "xsd:boolean cast"):
        "pyoxigraph XSD cast handling differs from spec",
    ("cast", "xsd:decimal cast"):
        "pyoxigraph XSD cast handling differs from spec",
    ("cast", "xsd:double cast"):
        "pyoxigraph XSD cast handling differs from spec",
    ("cast", "xsd:float cast"):
        "pyoxigraph XSD cast handling differs from spec",
    ("cast", "xsd:integer cast"):
        "pyoxigraph XSD cast handling differs from spec",
    ("cast", "xsd:string cast"):
        "pyoxigraph XSD cast handling differs from spec",
    # --- construct ---
    ("construct", "constructwhere04 - CONSTRUCT WHERE"):
        "pyoxigraph CONSTRUCT WHERE edge case",
    # --- property-path ---
    ("property-path", "(pp34) Named Graph 1"):
        "pyoxigraph property-path in named graph",
    ("property-path", "(pp35) Named Graph 2"):
        "pyoxigraph property-path in named graph",
    ("property-path", "* with end being a constant on the empty dataset"):
        "pyoxigraph * path on empty dataset",
    ("property-path", "* with start being a constant on the empty dataset"):
        "pyoxigraph * path on empty dataset",
    ("property-path", "? with end being a constant on the empty dataset"):
        "pyoxigraph ? path on empty dataset",
    ("property-path", "? with start being a constant on the empty dataset"):
        "pyoxigraph ? path on empty dataset",
    # --- subquery ---
    ("subquery", "sq12 - Subquery in CONSTRUCT with built-ins"):
        "pyoxigraph subquery + CONSTRUCT interaction",
    ("subquery", "sq14 - limit by resource"):
        "pyoxigraph subquery LIMIT edge case",
}

# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------


def _collect_dawg_tests(categories: List[str]) -> List[Tuple[str, DawgTestCase]]:
    """Discover all DAWG tests across the specified categories."""
    if not DAWG_ROOT.exists():
        return []

    tests = []
    for category in categories:
        manifest_path = get_manifest_path(DAWG_ROOT, category)
        if not manifest_path.exists():
            continue
        for tc in parse_manifest(manifest_path, category=category):
            tests.append((f"{category}/{tc.name}", tc))
    return tests


def _collect_jena_tests(categories: List[str]) -> List[Tuple[str, DawgTestCase]]:
    """Discover Jena ARQ tests across the specified categories."""
    if not JENA_ARQ_ROOT.exists():
        return []

    tests = []
    for category in categories:
        manifest = JENA_ARQ_ROOT / category / "manifest.ttl"
        if not manifest.exists():
            continue
        for tc in parse_manifest(manifest, category=f"jena/{category}"):
            tests.append((f"jena/{category}/{tc.name}", tc))
    return tests


# Collect at module load for parametrize
_DAWG_TESTS = _collect_dawg_tests(QUERY_CATEGORIES)
_JENA_ARQ_CATEGORIES = [
    "Ask", "Construct", "Describe", "Optional", "Union",
    "Negation", "GroupBy", "SubQuery", "Paths", "Basic",
    "Bound", "Distinct", "Sort", "Select", "SelectExpr", "Assign",
]
_JENA_TESTS = _collect_jena_tests(_JENA_ARQ_CATEGORIES)


# ---------------------------------------------------------------------------
# Test execution helper
# ---------------------------------------------------------------------------


def _run_dawg_test(tc: DawgTestCase) -> None:
    """Execute a single DAWG test case and assert it passes."""
    # Skip non-query tests
    if tc.test_type != "QueryEvaluation":
        pytest.skip(f"Test type: {tc.test_type} (only QueryEvaluation supported)")

    if tc.query_file is None or not tc.query_file.exists():
        pytest.skip("Query file missing")

    if tc.result_file is None or not tc.result_file.exists():
        pytest.skip("Result file missing")

    # A format we cannot read at all is a skip; a file we SHOULD be able
    # to read and cannot is a failure. Collapsing the two is what hid six
    # unreadable dataset expectations behind a green category (issues/130).
    try:
        expected = parse_result_file(tc.result_file)
    except UnsupportedResultFormat as e:
        pytest.skip(str(e))

    sparql = tc.query_file.read_text(encoding="utf-8")

    try:
        actual = execute_query(
            sparql,
            data_file=tc.data_file,
            named_graph_files=tc.named_graph_files or None,
            base_iri=f"file://{tc.query_file}",
        )
    except SparqlExecutionError as e:
        pytest.fail(f"Execution error: {e}")

    comparison = compare_results(actual, expected)
    if not comparison.match:
        pytest.fail(
            f"Result mismatch: {comparison.message} "
            f"(expected {comparison.expected_count} rows, got {comparison.actual_count})"
        )


# ---------------------------------------------------------------------------
# DAWG Tests
# ---------------------------------------------------------------------------


@pytest.mark.dawg
class TestDAWGConformance:
    """W3C DAWG SPARQL 1.1 conformance tests run against pyoxigraph."""

    @pytest.mark.parametrize(
        "name,tc",
        _DAWG_TESTS,
        ids=[t[0] for t in _DAWG_TESTS],
    )
    def test_dawg(self, name: str, tc: DawgTestCase):
        # Apply xfail for known failures
        key = (tc.category, tc.name)
        if key in XFAIL_TESTS:
            pytest.xfail(XFAIL_TESTS[key])

        _run_dawg_test(tc)


# ---------------------------------------------------------------------------
# Jena ARQ Tests
# ---------------------------------------------------------------------------


@pytest.mark.jena_arq
class TestJenaARQConformance:
    """Apache Jena ARQ test suite run against pyoxigraph."""

    @pytest.mark.parametrize(
        "name,tc",
        _JENA_TESTS,
        ids=[t[0] for t in _JENA_TESTS],
    )
    def test_jena_arq(self, name: str, tc: DawgTestCase):
        key = (tc.category, tc.name)
        if key in XFAIL_TESTS:
            pytest.xfail(XFAIL_TESTS[key])

        _run_dawg_test(tc)
