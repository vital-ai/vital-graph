"""DAWG SPARQL 1.1 syntax conformance — does our parser accept what it must?

A syntax test asserts one bit: the parser accepts a `PositiveSyntaxTest11` and
rejects a `NegativeSyntaxTest11`. No data is loaded, no results are compared.

WHY THIS IS A REAL CONFORMANCE CLAIM AND NOT A TAUTOLOGY. The obvious objection
to testing a parser against an oracle is that you learn nothing when the oracle
IS the parser. That is not the situation here: the Jena sidecar's
`/v1/sparql/compile` is our **production parse path** — every query the backend
answers goes `jena_sidecar_client` -> `jena_ast_mapper` -> SQL generation. So
`ok: true` / `ok: false` is the accept/reject decision we actually ship, and
these 152 cases measure it. There is no second parser to disagree with.

WHY THESE WERE NOT RUN BEFORE. `P0_CATEGORIES` in `test_dawg_sql_v2.py` is a
hardcoded list, and `syntax-query`, `syntax-update-1`, `syntax-update-2` and
`syntax-fed` were never in it. Additionally `_collect_p0_tests` filters
`test_type == "QueryEvaluation"`, so the nine syntax cases sitting inside
categories that WERE wired (5 in `aggregates`, 2 in `construct`, 2 in
`grouping`) were parsed out of the manifests and then dropped on the floor.
Both are collected here.

`syntax-fed` is included deliberately even though `SERVICE` is unimplemented:
parsing federation we cannot execute is a real and separable property, and
these three cases are the only thing in the corpus that checks it.

Requires the Jena sidecar (VG_TEST_SIDECAR_URL, default 7071).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Tuple

import pytest

from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_manifest_parser import (
    DawgTestCase,
    get_manifest_path,
    parse_manifest,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAWG_ROOT = _PROJECT_ROOT / "tests" / "conformance" / "dawg_data"

# The TEST-stack sidecar (vitalgraph-test-sidecar, host 7071 -> 7070 in the
# container), not the dev one on 7070. tests/performance already defaulted
# here; integration and conformance did not, so they silently checked a
# sidecar belonging to the other stack — and skipped themselves when it was
# down, which reads as "infrastructure absent" rather than "wrong port".
SIDECAR_COMPILE = (os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")
                   + "/v1/sparql/compile")

# Categories that are ENTIRELY syntax tests.
SYNTAX_CATEGORIES = [
    "syntax-query",       # 94: 63 positive, 31 negative
    "syntax-update-1",    # 54: 41 positive, 13 negative
    "syntax-update-2",    # 1 positive
    "syntax-fed",         # 3 positive — SERVICE syntax, unexecutable but parseable
]

# Categories wired elsewhere for their query-evaluation cases, whose syntax
# cases the other suite discards. Nine cases that were being read and ignored.
MIXED_CATEGORIES = [
    "aggregates",
    "construct",
    "grouping",
    "delete-insert",
]

_POSITIVE = {"PositiveSyntax", "PositiveUpdateSyntax"}
_NEGATIVE = {"NegativeSyntax", "NegativeUpdateSyntax"}



# Gated by the shared `dawg_infrastructure` fixture in conftest: skip
# locally, FAIL under VG_REQUIRE_INFRA so CI cannot pass by measuring
# nothing. The module's own probe is gone; there were three and they
# disagreed with each other and with the port they actually used.
DAWG_NEEDS_PG = False

pytestmark = [
    pytest.mark.dawg,
    pytest.mark.usefixtures("dawg_infrastructure"),
]


# Cases where our parser disagrees with the manifest. All three are
# OVER-ACCEPTANCE — we admit a query the grammar forbids — and all three are
# Jena's decision, upstream of anything in this repo. See issues/095.
#
# Over-acceptance is the mild direction of a syntax defect: we answer queries
# that should have been refused, rather than refusing valid ones. But
# `SELECT * ... GROUP BY` has no defined answer, so what we return for it is
# undefined behaviour rather than a documented extension.
KNOWN_SYNTAX_FAILURES = {
    # syn-bad-01/04/05 removed 2026-08-16 — the sidecar now rejects them in
    # SparqlCompiler.grammarViolation. An entry that starts passing is DELETED,
    # not left as a permanent xfail.
    #
    # `CONSTRUCT WHERE { GRAPH ... }` stays, knowingly. The short form takes a
    # bare TriplesTemplate and the grammar does not admit GRAPH inside it, but
    # telling the short form from the long one needs syntax-level state Jena
    # does not expose on Query — and the harm is a template that behaves
    # sensibly, not an undefined answer. See issues/095.
    ("construct", "constructwhere06.rq"):
        "issues/095 — CONSTRUCT WHERE with GRAPH; needs syntax-level state "
        "Jena does not expose, and the result is well-defined",
}


def _collect() -> List[Tuple[str, DawgTestCase, bool]]:
    """Every syntax case in the corpus, as (id, case, should_be_accepted)."""
    if not DAWG_ROOT.exists():
        return []

    collected: List[Tuple[str, DawgTestCase, bool]] = []
    for category in SYNTAX_CATEGORIES + MIXED_CATEGORIES:
        manifest = get_manifest_path(DAWG_ROOT, category)
        if not manifest.exists():
            continue
        for tc in parse_manifest(manifest, category=category):
            if tc.test_type in _POSITIVE:
                collected.append((f"{category}/{tc.name}", tc, True))
            elif tc.test_type in _NEGATIVE:
                collected.append((f"{category}/{tc.name}", tc, False))
    return collected


_SYNTAX_TESTS = _collect()


def _parses(sparql: str) -> Tuple[bool, str]:
    """Ask the production parse path whether this is valid SPARQL.

    Returns `(accepted, detail)`. A transport failure raises rather than
    returning False — "the sidecar is down" must not read as "the parser
    correctly rejected this", which would turn an outage into a green negative
    suite.
    """
    req = urllib.request.Request(
        SIDECAR_COMPILE,
        data=json.dumps({"sparql": sparql}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)

    if payload.get("ok") is True:
        return True, ""
    error = payload.get("error") or {}
    return False, f"{error.get('code', '?')}: {(error.get('message') or '')[:200]}"


class TestDAWGSyntax:
    """Accept/reject conformance for the SPARQL 1.1 grammar."""

    @pytest.mark.parametrize(
        "name,tc,should_accept",
        _SYNTAX_TESTS,
        ids=[t[0] for t in _SYNTAX_TESTS],
    )
    def test_syntax(self, name: str, tc: DawgTestCase, should_accept: bool):
        key = (tc.category, tc.query_file.name if tc.query_file else tc.name)
        if key in KNOWN_SYNTAX_FAILURES:
            pytest.xfail(KNOWN_SYNTAX_FAILURES[key])

        if tc.query_file is None or not tc.query_file.exists():
            pytest.skip("Query file missing")

        sparql = tc.query_file.read_text(encoding="utf-8")
        accepted, detail = _parses(sparql)

        if should_accept and not accepted:
            pytest.fail(
                f"Valid SPARQL was REJECTED: {tc.name}\n"
                f"  file={tc.query_file}\n"
                f"  error={detail}"
            )
        if not should_accept and accepted:
            pytest.fail(
                f"Invalid SPARQL was ACCEPTED: {tc.name}\n"
                f"  file={tc.query_file}\n"
                f"  the grammar forbids this, so whatever we compute for it is "
                f"undefined rather than merely permissive"
            )

    def test_corpus_is_not_empty(self):
        """Guard the thing that actually went wrong.

        `syntax-update-1` parsed to ZERO tests until the manifest parser learned
        `PositiveUpdateSyntaxTest11` — and a category yielding no tests is
        indistinguishable from a category that passes, in every count pytest
        prints. This asserts each syntax category contributes cases, so the
        failure mode is a red test rather than a smaller number nobody reads.
        """
        by_category: dict = {}
        for _, tc, _accept in _SYNTAX_TESTS:
            by_category[tc.category] = by_category.get(tc.category, 0) + 1

        expected_minimum = {
            "syntax-query": 90,
            "syntax-update-1": 50,
            "syntax-update-2": 1,
            "syntax-fed": 3,
        }
        for category, minimum in expected_minimum.items():
            found = by_category.get(category, 0)
            assert found >= minimum, (
                f"{category} contributed {found} syntax cases, expected >= {minimum}. "
                f"A category that collects nothing looks exactly like one that passes."
            )
