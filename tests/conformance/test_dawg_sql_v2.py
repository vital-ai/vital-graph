"""DAWG SPARQL 1.1 conformance tests — SQL v2 pipeline.

Runs DAWG test cases through the full v2 SPARQL→SQL pipeline,
comparing results against pyoxigraph as the oracle.

Requires:
  - PostgreSQL running with dawg_test space provisioned
  - Jena sidecar running on localhost:7070

Skip these tests in CI without infrastructure:
    pytest tests/conformance/test_dawg_sql_v2.py  # auto-skips if no DB

Usage (local with DB + sidecar):
    pytest tests/conformance/test_dawg_sql_v2.py -v -k "bind"
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Tuple

import pytest

from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_manifest_parser import (
    DawgTestCase,
    parse_manifest,
    get_manifest_path,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_oxigraph_executor import (
    execute_query,
    SparqlExecutionError,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_srx_parser import (
    parse_result_file,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_result_comparator import (
    compare_results,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Infrastructure check
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAWG_ROOT = _PROJECT_ROOT / "vitalgraph_sparql_sql_dev" / "dawg_tests"

P0_CATEGORIES = [
    "bind",
    "aggregates",
    "functions",
    "negation",
    "exists",
    "grouping",
    # VALUES. Added for issue 023 — the 11 tests here are the only DAWG
    # coverage of VALUES, and until `test_sql_v2` began actually executing
    # (same issue) they ran against pyoxigraph only, so VALUES had never been
    # exercised against the SQL backend by any test.
    "bindings",
    # CONSTRUCT. Added for issue 025, which implemented the form — before that
    # these would have "passed" by comparing WHERE-pattern bindings.
    "construct",
    # Added 2026-08-16 after counting: 19 of 34 DAWG categories were wired in,
    # so a green run meant "green on the categories someone remembered to add".
    # The manifests had been in the tree the whole time.
    #
    # What running them bought, immediately:
    #   property-path       33 cases, 0 failures — the tracker listed this as
    #                       implemented but unverified; now it is verified
    #   project-expression   7 cases, 0 failures
    #   subquery            14 cases, 3 failures — issues/093, a subquery inside
    #                       GRAPH returns zero rows, silently
    #   cast                 6 cases, 1 failure  — issues/094
    "property-path",
    "subquery",
    "cast",
    "project-expression",
    # Result-format categories, added once the parsers existed to read their
    # expectations. `json-res` needed nothing — dawg_srx_parser has handled
    # `.srj` since it was written, so these four cases were being skipped for
    # want of a list entry. `csv-tsv-res` needed CSV/TSV parsing, and the CSV
    # half compares on VALUES ONLY because the format cannot carry term types;
    # see dawg_srx_parser's module docstring.
    "json-res",
    "csv-tsv-res",
]

# Cases that fail today, kept RUNNING rather than removed so the count stays
# honest and a fix flips them to passing without anyone re-adding a category.
# Each names the issue; an entry that starts passing should be deleted, not
# left as a permanent xfail.
KNOWN_FAILURES = {
    ("subquery", "sq01 - Subquery within graph pattern"): "issues/093",
    ("subquery", "sq02 - Subquery within graph pattern, graph variable is bound"):
        "issues/093",
    ("subquery", "sq03 - Subquery within graph pattern, graph variable is not bound"):
        "issues/093",
    ("cast", "xsd:float cast"): "issues/094",
}


def _check_infrastructure() -> bool:
    """Check if DB + sidecar are available."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:7070/v1/sparql/compile",
            data=b'{"sparql":"SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


HAS_INFRASTRUCTURE = _check_infrastructure()

pytestmark = [
    pytest.mark.sql_v2,
    pytest.mark.skipif(
        not HAS_INFRASTRUCTURE,
        reason="Requires PostgreSQL + Jena sidecar (localhost:7070)",
    ),
]


# ---------------------------------------------------------------------------
# Known xfail for sql_v2 pipeline
# ---------------------------------------------------------------------------

# ORACLE limitations: pyoxigraph disagrees with the manifest. Consulted ONLY by
# `test_oracle_baseline`.
#
# It used to be consulted by `test_sql_v2` as well, and that was quietly
# expensive. Measured 2026-08-16 by removing the deferral: 14 of the 16 entries
# below PASS through the real SQL pipeline. So a table whose whole purpose is
# "the oracle is wrong here" was also switching off the test of OUR backend for
# those cases -- the same failure this whole exercise started from, one level
# down: coverage disappearing silently, with a green count to cover it.
#
# `pytest.xfail()` is imperative, so it does not merely tolerate a failure, it
# STOPS THE TEST. An entry here would never surface as an XPASS no matter how
# right our answer became.
XFAIL_TESTS_V2 = {
    # Tests that fail due to pyoxigraph oracle limitations
    ("aggregates", "GROUP_CONCAT with one element"):
        "pyoxigraph GROUP_CONCAT separator handling",
    ("aggregates", "GROUP_CONCAT with same language tag"):
        "pyoxigraph GROUP_CONCAT language tag propagation",
    ("negation", "outer GRAPH operator does not affect MINUS disjointness"):
        "pyoxigraph GRAPH + MINUS interaction",

    # Added 2026-08-16 with the four new categories. All twelve are the ORACLE
    # disagreeing with the manifest, not us — `test_sql_v2` passes every one of
    # them except the four in KNOWN_FAILURES. Listed individually rather than
    # skipping the categories, so a pyoxigraph upgrade that fixes one turns the
    # xfail into an XPASS and says so.
    ("cast", "xsd:boolean cast"): "pyoxigraph cast lexical form",
    ("cast", "xsd:decimal cast"): "pyoxigraph cast lexical form",
    ("cast", "xsd:double cast"): "pyoxigraph cast lexical form",
    ("cast", "xsd:float cast"): "pyoxigraph cast lexical form",
    ("cast", "xsd:integer cast"): "pyoxigraph cast lexical form",
    ("cast", "xsd:string cast"): "pyoxigraph cast lexical form",
    ("property-path", "* with end being a constant on the empty dataset"):
        "pyoxigraph zero-length path on an empty dataset",
    ("property-path", "* with start being a constant on the empty dataset"):
        "pyoxigraph zero-length path on an empty dataset",
    ("property-path", "? with end being a constant on the empty dataset"):
        "pyoxigraph zero-length path on an empty dataset",
    ("property-path", "? with start being a constant on the empty dataset"):
        "pyoxigraph zero-length path on an empty dataset",
    ("subquery", "sq12 - Subquery in CONSTRUCT with built-ins"):
        "pyoxigraph subquery in CONSTRUCT",
    ("subquery", "sq14 - limit by resource"):
        "pyoxigraph LIMIT-by-resource subquery",

    # Worth reading before trusting the oracle anywhere else in this file.
    # data2.ttl holds `"1.0E6"^^xsd:double` and the CSV expectation preserves
    # that lexical form, as RDF 1.1 requires -- a literal's identity includes
    # its lexical form, so `"1.0E6"^^xsd:double` and `"1000000"^^xsd:double`
    # are DIFFERENT terms. pyoxigraph canonicalises to `1000000` and fails.
    # OUR pipeline returns `1.0E6` and passes: `test_sql_v2` for this same case
    # is green. Measured on the same run, we also preserve
    # `"-3"^^xsd:negativeInteger` where pyoxigraph widens it to xsd:integer.
    ("csv-tsv-res", "csv03 - CSV Result Format"):
        "pyoxigraph canonicalises xsd:double lexical form; ours preserves it",
}

# Real gaps in the SQL pipeline surfaced when test_sql_v2 began actually
# executing. Empty: the four aggregate failures it found (issue 029) are fixed.
# Kept as the place for the next one, with the rule that removing an entry
# must make its test pass.
XFAIL_SQL_V2_EXEC: dict = {}

# Cases where OUR output differs from the manifest AND so does pyoxigraph -- the
# runner reports these as `ACCEPTED` rather than `FAIL`, meaning it could not
# attribute the difference. Distinct from XFAIL_TESTS_V2 (oracle wrong, we are
# right) and from XFAIL_SQL_V2_EXEC (we are wrong, known gap).
#
# Kept separate so the count of "our backend is not being measured here" stays
# visible and small. These two are the entire list; everything else previously
# excused by the oracle table is now actually run.
XFAIL_SQL_V2_ACCEPTED = {
    ("aggregates", "GROUP_CONCAT with one element"):
        "both engines differ from the manifest on GROUP_CONCAT separators; "
        "attribution unresolved",
    ("aggregates", "GROUP_CONCAT with same language tag"):
        "both engines differ from the manifest on GROUP_CONCAT language tags; "
        "attribution unresolved",
}


# ---------------------------------------------------------------------------
# Test collection
# ---------------------------------------------------------------------------


def _collect_p0_tests() -> List[Tuple[str, DawgTestCase]]:
    """Collect P0 DAWG tests for sql_v2 validation."""
    if not DAWG_ROOT.exists():
        return []

    tests = []
    for category in P0_CATEGORIES:
        manifest_path = get_manifest_path(DAWG_ROOT, category)
        if not manifest_path.exists():
            continue
        for tc in parse_manifest(manifest_path, category=category):
            if tc.test_type == "QueryEvaluation":
                tests.append((f"{category}/{tc.name}", tc))
    return tests


_SQL_V2_TESTS = _collect_p0_tests()


# ---------------------------------------------------------------------------
# Async test execution
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def event_loop():
    """Create an event loop for the module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# The DB connection and event loop are session-scoped and shared with the
# update suite — see tests/conformance/conftest.py for why they must be.


@pytest.mark.dawg
class TestDAWGSqlV2:
    """DAWG conformance tests run through the v2 SPARQL→SQL pipeline.

    Compares SQL pipeline output against pyoxigraph as the oracle.
    """

    @pytest.mark.parametrize(
        "name,tc",
        _SQL_V2_TESTS,
        ids=[t[0] for t in _SQL_V2_TESTS],
    )
    def test_oracle_baseline(self, name: str, tc: DawgTestCase):
        """pyoxigraph vs. the manifest's expected results.

        This validates the corpus and the comparator, NOT this project's code.
        Kept as a baseline so a failure in `test_sql_v2` below can be attributed
        — if both fail, suspect the fixture; if only `test_sql_v2` fails, the
        SQL pipeline is wrong.
        """
        key = (tc.category, tc.name)
        if key in XFAIL_TESTS_V2:
            pytest.xfail(XFAIL_TESTS_V2[key])

        if tc.query_file is None or not tc.query_file.exists():
            pytest.skip("Query file missing")
        if tc.result_file is None or not tc.result_file.exists():
            pytest.skip("Result file missing")

        expected = parse_result_file(tc.result_file)
        if expected is None:
            pytest.skip(f"Cannot parse result file: {tc.result_file.suffix}")

        sparql = tc.query_file.read_text(encoding="utf-8")

        try:
            actual = execute_query(
                sparql,
                data_file=tc.data_file,
                named_graph_files=tc.named_graph_files or None,
            )
        except SparqlExecutionError as e:
            pytest.skip(f"pyoxigraph cannot execute: {e}")

        comparison = compare_results(actual, expected)
        if not comparison.match:
            pytest.fail(
                f"Result mismatch: {comparison.message} "
                f"(expected {comparison.expected_count} rows, got {comparison.actual_count})"
            )

    @pytest.mark.parametrize(
        "name,tc",
        _SQL_V2_TESTS,
        ids=[t[0] for t in _SQL_V2_TESTS],
    )
    def test_sql_v2(self, name: str, tc: DawgTestCase, dawg_conn, dawg_loop):
        """Run the query through the **real** SPARQL→SQL pipeline.

        Until 2026-08-04 this module ran only the pyoxigraph baseline above —
        despite its name, its docstring, its `sql_v2` marker and its
        PostgreSQL+sidecar gate, it never touched the SQL backend. The comment
        said "full sql_v2 execution ... is handled by run_single_test_sql_v2 in
        the runner", and that runner was never invoked from pytest. So the
        query side had no SQL conformance coverage either, the same gap issue
        023 identified on the update side.
        """
        if (tc.category, tc.name) in KNOWN_FAILURES:
            pytest.xfail(f"KNOWN: {KNOWN_FAILURES[(tc.category, tc.name)]}")
        key = (tc.category, tc.name)
        if key in XFAIL_SQL_V2_EXEC:
            pytest.xfail(XFAIL_SQL_V2_EXEC[key])
        if key in XFAIL_SQL_V2_ACCEPTED:
            pytest.xfail(XFAIL_SQL_V2_ACCEPTED[key])
        # Deliberately NOT consulting XFAIL_TESTS_V2 -- see the comment on it.

        from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_test_runner import (
            run_single_test_sql_v2,
        )

        result = dawg_loop.run_until_complete(
            run_single_test_sql_v2(tc, dawg_conn)
        )
        if result.status == "SKIP":
            pytest.skip(result.error_message or "runner skipped")
        if result.status != "PASS":
            pytest.fail(
                f"{result.status}: {result.error_message}\n"
                f"  category={tc.category} test={tc.name}\n"
                f"  query={tc.query_file}"
            )
