"""DAWG SPARQL 1.1 conformance tests — SQL v2 pipeline.

Runs DAWG test cases through the full v2 SPARQL→SQL pipeline,
comparing results against pyoxigraph as the oracle.

Requires:
  - PostgreSQL running with dawg_test space provisioned
  - Jena sidecar (VG_TEST_SIDECAR_URL, default 7071)

Skip these tests in CI without infrastructure:
    pytest tests/conformance/test_dawg_sql_v2.py  # auto-skips if no DB

Usage (local with DB + sidecar):
    pytest tests/conformance/test_dawg_sql_v2.py -v -k "bind"
"""

from __future__ import annotations

import asyncio
import os
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
    UnsupportedResultFormat,
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
DAWG_ROOT = _PROJECT_ROOT / "tests" / "conformance" / "dawg_data"

P0_CATEGORIES = [
    "sparql10/graph",
    "sparql10/cast",
    "sparql10/sort",
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
    # The only DAWG coverage of langMatches, str, lang, datatype, isIRI,
    # isLiteral and sameTerm — and it sits under sparql10, which
    # `get_manifest_path` could not reach by any spelling until `issues/125`.
    # `issues/120` shipped a langMatches that did no prefix matching while
    # q-langMatches-2.rq, literally the failing query, sat on disk unrun.
    "sparql10/expr-builtin",
    # The rest of sparql10 that passes CLEAN, wired 2026-08-23. 68 more cases,
    # zero failures. Measured, not assumed — the other 16 evaluation
    # categories collect 98 failures across at least six distinct causes and
    # are NOT wired, because 98 xfails would destroy the signal this list
    # exists to carry. `issues/128` records the measurement per category.
    "sparql10/ask",
    "sparql10/bnode-coreference",
    "sparql10/bound",
    "sparql10/dataset",
    "sparql10/optional",
    "sparql10/solution-seq",
    "sparql10/triple-match",
    "sparql10/open-world",
    # Wired once XSD promotion landed — 22 cases, one cause (issues/128).
    "sparql10/type-promotion",
    "sparql10/boolean-effective-value",
]

# Cases that fail today, kept RUNNING rather than removed so the count stays
# honest and a fix flips them to passing without anyone re-adding a category.
# Each names the issue; an entry that starts passing should be deleted, not
# left as a permanent xfail.
KNOWN_FAILURES = {
    # --- sparql10/open-world, hand-triaged 2026-08-24 ---------------------
    # WE MATCH THE CORPUS on all three; the ORACLE does not, and test_sql_v2
    # compares against the oracle. Verified by reading the data and the
    # expected SRX by hand — the check that cleared str-1/str-2. The ACCEPTED
    # label only means the oracle ALSO differs; it never means we are right,
    # and reading it that way had two of these filed as "not our bug" when
    # they WERE, until date-2 and date-3 were fixed (dd97082, cca66e2).
    #
    #   date-2      != over xsd:date, needing XSD's 14-hour partial order.
    #   date-3      > across xsd:date and xsd:dateTime, a type error.
    #   open-eq-01  a TRIPLE PATTERN, so it matches by RDF TERM. No term
    #               carries the lexical form "001", so zero rows — the
    #               manifest says so itself: "graph match - no lexical form in
    #               data (assumes no value matching)". pyoxigraph returns 2.
    ("sparql10/open-world", "date-2"):
        "oracle disagrees with the corpus; WE match the .ttl",
    ("sparql10/open-world", "date-3"):
        "oracle disagrees with the corpus; WE match the .ttl",
    ("sparql10/open-world", "open-eq-01"):
        "oracle value-matches in a graph pattern; WE match the .ttl",

    # issues/093 (sq01-sq03) removed 2026-08-16 — fixed, and an entry that
    # starts passing must be DELETED rather than left as a permanent xfail, or
    # the number stops meaning anything.

    # --- sparql10/expr-builtin, wired 2026-08-23 (issues/125) --------------
    # Wiring it took the category from 29 failures of 48 to 10, and the ten
    # are five cases seen by two test functions each. They are NOT one kind,
    # and the difference is the whole point of listing them separately.

    # WAS our gap (issues/127, `?v1 = ?v2` between two VARIABLES compared
    # term_text). FIXED — the lane is now chosen per row. `sameTerm-not-eq`
    # went from 0 rows to 18, which is exactly what the .ttl expects, and all
    # three now match the corpus while pyoxigraph does not:
    #
    #     case              .ttl   pyoxigraph   us
    #     sameTerm-eq        24        14       24
    #     sameTerm-not-eq    18        28       18
    #     sameTerm-simple    24        14       24
    #
    # They stay listed because `test_sql_v2` compares against the ORACLE, and
    # the oracle is the one that is wrong here. Deleting them would report a
    # pass we are not getting; keeping the old reason would claim a bug we no
    # longer have.
    ("sparql10/expr-builtin", "sameTerm-eq"):
        "oracle disagrees with the corpus; WE match the .ttl since issues/127",
    ("sparql10/expr-builtin", "sameTerm-not-eq"):
        "oracle disagrees with the corpus; WE match the .ttl since issues/127",
    ("sparql10/expr-builtin", "sameTerm-simple"):
        "oracle disagrees with the corpus; WE match the .ttl since issues/127",

    # EXPECTATION DISAGREEMENT, not ours. pyoxigraph differs from the .ttl
    # too, and reading the data by hand agrees with US: str-1 asks for
    # `str(?v) = "1"`, and the four lexical "1"s in data-builtin-1.ttl are
    # exactly what we return. Kept running rather than deleted so that if the
    # corpus or the comparator changes, the disagreement resurfaces.
    ("sparql10/expr-builtin", "str-1"): "expectation disagrees with both engines",
    ("sparql10/expr-builtin", "str-2"): "expectation disagrees with both engines",
}



# Gated by the shared `dawg_infrastructure` fixture in conftest: skip
# locally, FAIL under VG_REQUIRE_INFRA so CI cannot pass by measuring
# nothing. The module's own probe is gone; there were three and they
# disagreed with each other and with the port they actually used.
DAWG_NEEDS_PG = True

pytestmark = [
    pytest.mark.sql_v2,
    pytest.mark.usefixtures("dawg_infrastructure"),
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
    # sparql10/graph, wired 2026-08-24. The ORACLE half: pyoxigraph disagrees
    # with these three .srx expectations. `graph-optional` is oracle-only --
    # our backend matches the corpus on it.
    ("sparql10/graph", "graph-not-exist"):
        "pyoxigraph differs from the .srx on an empty group in a missing graph",
    ("sparql10/graph", "graph-optional"):
        "pyoxigraph differs from the .srx on OPTIONAL inside GRAPH",
    ("sparql10/graph", "graph-variable-scope"):
        "pyoxigraph differs from the .srx on a FILTER-only group in GRAPH",
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
    # sparql10/open-world — the ORACLE half. pyoxigraph differs from these
    # expectations; we match them. See KNOWN_FAILURES for the hand-check.
    ("sparql10/open-world", "date-2"):
        "pyoxigraph differs from the .ttl expectation",
    ("sparql10/open-world", "date-3"):
        "pyoxigraph differs from the .ttl expectation",
    ("sparql10/open-world", "open-eq-01"):
        "pyoxigraph value-matches in a graph pattern",

    # --- sparql10/expr-builtin, wired 2026-08-23 (issues/125) --------------
    # The ORACLE half. pyoxigraph disagrees with these .ttl expectations, so
    # they say nothing about our backend — that is exactly what this baseline
    # exists to separate. Reading data-builtin-1.ttl by hand agrees with both
    # engines against the file for str-1: `str(?v) = "1"` has four lexical
    # matches, not seven.
    #
    # sameTerm-* appear here AND in KNOWN_FAILURES, and for different reasons:
    # the oracle disagrees with the corpus, and independently we have a real
    # gap (issues/127). Both entries are needed; deleting either would hide
    # half of the picture.
    ("sparql10/expr-builtin", "sameTerm-eq"):
        "pyoxigraph differs from the .ttl expectation",
    ("sparql10/expr-builtin", "sameTerm-not-eq"):
        "pyoxigraph differs from the .ttl expectation",
    ("sparql10/expr-builtin", "sameTerm-simple"):
        "pyoxigraph differs from the .ttl expectation",
    ("sparql10/expr-builtin", "str-1"):
        "pyoxigraph differs from the .ttl expectation; hand-reading agrees with the engines",
    ("sparql10/expr-builtin", "str-2"):
        "pyoxigraph differs from the .ttl expectation; hand-reading agrees with the engines",

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
# executing. Empty again, twice over now: the four aggregate failures it first
# found (issue 029) are fixed, and so are the fifteen it held between
# 2026-08-24 and the end of that day -- thirteen were FROM/FROM NAMED being
# ignored (named_graph_semantics §4.1) and two were blank node labels merging
# across documents (issues/131).
#
# Kept as the place for the next one, with the rule that removing an entry
# must make its test pass. Note that `pytest.xfail()` is imperative and STOPS
# the test, so an entry here can never surface as an XPASS -- the only way to
# learn that a gap has closed is to delete the entry and run it. That is the
# rule's real cost, and it is why these are listed individually.
XFAIL_SQL_V2_EXEC: dict = {
    # sparql10/graph, wired 2026-08-24. All three are ONE gap: a graph-scoped
    # group with NO triple pattern must be evaluated against the named graphs,
    # and we treat `{}` as a no-op that matches once regardless.
    #
    #   GRAPH ?g {}                   one solution per named graph, ?g bound
    #   GRAPH ex:unknown {}           no solutions -- the graph is not there
    #   GRAPH ?g { FILTER(BOUND(?g)) }  same, the group has only a FILTER
    #
    # We bind no ?g at all (the harness reports it as a missing variable) and
    # answer one row for the non-existent graph. Enumerating requires a source
    # for the graph variable when no quad scan supplies one -- see
    # named_graph_semantics §4.3, which flags that enumeration is unbounded
    # work and should not be assumed cheap.
    ("sparql10/graph", "graph-empty"):
        "GRAPH with an empty group pattern does not enumerate graphs",
    ("sparql10/graph", "graph-not-exist"):
        "GRAPH with an empty group pattern does not enumerate graphs",
    ("sparql10/graph", "graph-variable-scope"):
        "GRAPH with an empty group pattern does not enumerate graphs",
}

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
