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
    # The last of sparql10, wired 2026-08-24/25. These are the 98-failure
    # backlog the note further down describes; every category the corpus has is
    # now here. Our failures across them went 25 -> 1, and the one that remains
    # is not ours (`issues/132`, the sidecar's PNAME expansion).
    #
    # Two of the three biggest wins were HARNESS defects rather than engine
    # ones, and both had hidden working code behind a category that could not
    # be wired:
    #   sort    10 failures, all on the ORACLE, one cause — the RDF/XML and
    #           TriG parsers never checked for the rs: result-set vocabulary,
    #           so `.rdf` expectations were compared as raw triples. Our sort
    #           needed no change at all.
    #   graph    4 — one was the runner declaring `default_graph` only when
    #           named graphs existed; the other three were `GRAPH {}` not
    #           enumerating.
    #   cast     6 — the cast emitters were already right; `datatype()` fell
    #           through to the static inference and reported the target type
    #           for casts that had failed.
    #
    # `issues/128` carries the per-category detail, including the three filed
    # causes that turned out to be wrong.
    "sparql10/algebra",
    "sparql10/basic",
    "sparql10/cast",
    "sparql10/construct",
    "sparql10/distinct",
    "sparql10/expr-equals",
    "sparql10/expr-ops",
    "sparql10/graph",
    "sparql10/i18n",
    "sparql10/optional-filter",
    "sparql10/reduced",
    "sparql10/regex",
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
    # The rest of sparql10 that passed CLEAN on 2026-08-23 — 68 cases, zero
    # failures, measured rather than assumed. At the time the remaining 16
    # evaluation categories collected 98 failures and were deliberately left
    # out, because 98 xfails would have destroyed the signal this list carries.
    # That backlog is now cleared and they are wired above; `issues/128` has
    # the measurement per category.
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
# Cases where WE differ from the corpus and the difference has been hand-checked.
#
# Empty since 2026-08-25. It held eight -- three `sparql10/open-world`, five
# `sparql10/expr-builtin` -- every one of them recorded as "we match the
# corpus, the ORACLE does not". That was true, and it was never a reason to
# stop testing us: the runner used to compare us only to pyoxigraph, so an
# oracle that disagreed with the .srx took our backend out of the run with it.
#
# Since the runner consults the .srx directly when the oracle is not the
# authority, all eight pass. Removed rather than left as documentation --
# `pytest.xfail()` is imperative and STOPS the test, so an entry here is not a
# note, it is a hole.
KNOWN_FAILURES: dict = {}



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
    # sparql10 categories wired 2026-08-24, ORACLE half. pyoxigraph
    # canonicalises numeric lexical forms, so it collapses literals that
    # DISTINCT and REDUCED must keep apart, and it loses CONSTRUCT bnode
    # isomorphism on five cases. We match the corpus on all of these -- the
    # runner now checks that directly and passes us, which is why none of them
    # appear in XFAIL_SQL_V2_EXEC.
    ("sparql10/construct", "dawg-construct-identity"):
        "pyoxigraph CONSTRUCT bnode isomorphism",
    ("sparql10/construct", "dawg-construct-optional"):
        "pyoxigraph CONSTRUCT with OPTIONAL",
    ("sparql10/construct", "dawg-construct-reification-1"):
        "pyoxigraph CONSTRUCT bnode isomorphism",
    ("sparql10/construct", "dawg-construct-reification-2"):
        "pyoxigraph CONSTRUCT bnode isomorphism",
    ("sparql10/construct", "dawg-construct-subgraph"):
        "pyoxigraph CONSTRUCT bnode isomorphism",
    ("sparql10/distinct", "All: Distinct"):
        "pyoxigraph canonicalises lexical forms; DISTINCT is over TERMS",
    ("sparql10/distinct", "Numbers: Distinct"):
        "pyoxigraph canonicalises lexical forms; DISTINCT is over TERMS",
    ("sparql10/reduced", "SELECT REDUCED *"):
        "pyoxigraph canonicalises lexical forms; REDUCED is over TERMS",
    ("sparql10/reduced", "SELECT REDUCED ?x with strings"):
        "pyoxigraph canonicalises lexical forms; REDUCED is over TERMS",
    ("sparql10/expr-equals", "Equality 1-1 -- graph"):
        "pyoxigraph differs from the .srx; we match it",
    ("sparql10/expr-equals", "Equality 1-2 -- graph"):
        "pyoxigraph differs from the .srx; we match it",
    ("sparql10/optional-filter", "dawg-optional-filter-005-not-simplified"):
        "pyoxigraph differs from the .srx on a computed numeric's lexical form",
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
    # --- sparql10 categories wired 2026-08-24 -------------------------------
    # `[^b]` must match a newline while `.` must not. PostgreSQL has no mode
    # that gives both: `p` and `n` exclude newline from bracket negation AND
    # from `.`, `w` includes it in both. Emulating XPath means dropping the
    # option and rewriting `.` to `[^\n]` in the pattern instead -- a change
    # to the shared flag mapping in `regex_flags`, whose 2x2 is measured and
    # documented, so not made in passing.
    
    # Two operands of an arithmetic sign where the corpus keeps the operand's
    # own lexical form (`"3"`), and we return the canonical one. Same family as
    # the csv03 note above -- lexical identity of a computed numeric -- but on
    # OUR side, and it needs the promotion work to say which form is right.
            

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
            }

# Cases where OUR output differs from the manifest AND so does pyoxigraph -- the
# runner reports these as `ACCEPTED` rather than `FAIL`, meaning it could not
# attribute the difference. Distinct from XFAIL_TESTS_V2 (oracle wrong, we are
# right) and from XFAIL_SQL_V2_EXEC (we are wrong, known gap).
#
# Kept separate so the count of "our backend is not being measured here" stays
# visible and small. These two are the entire list; everything else previously
# excused by the oracle table is now actually run.
# Empty since 2026-08-25. It held the two GROUP_CONCAT cases, filed as "both
# engines differ from the manifest; attribution unresolved". The attribution
# was resolvable all along -- the runner just had no way to ask. Comparing to
# the .srx directly answers it, and both pass.
#
# The count this dict exists to keep "visible and small" is now zero: there is
# no case anywhere in the suite where our backend goes unmeasured.
XFAIL_SQL_V2_ACCEPTED: dict = {}


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
