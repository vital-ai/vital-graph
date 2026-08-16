"""Every DAWG category is either run or explicitly declined — no third option.

WHAT THIS DEFENDS. The conformance suites select categories from HARDCODED
LISTS, and the DAWG corpus is a directory tree that grows when someone syncs it.
Nothing compared the two. On 2026-08-16 that gap was measured: 15 of the 34
`sparql11` categories were not wired into anything, and 162 of those cases
needed no new harness at all — four of them needed nothing but a line in a list.

The reason it lasted is that the failure mode is ABSENCE. A category nobody runs
produces no failing test, no warning, and no line in the output. "The
conformance suite is green" was true and meant less than it sounded, and there
was no artifact in the repo from which you could tell the difference.

No individual test case can defend against that, because the thing that went
wrong is that a test case did not exist. So this asserts the property directly:
every category directory is accounted for, by being run or by being declined in
writing with a reason. A new manifest appearing in the tree fails this test until
someone chooses. Silence stops being available.

Same principle as the structural test in `test_regex_dialect.py` that neither
regex emitter re-grows its own flag mapping — both guard a property of the code
as a whole rather than the behaviour of one path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPARQL11_ROOT = (
    _PROJECT_ROOT / "vitalgraph_sparql_sql_dev" / "dawg_tests" / "sparql" / "sparql11"
)

# Categories deliberately NOT run, each with the reason. An entry here is a
# DECISION; the point of writing it down is that an unexplained gap in a
# conformance list is indistinguishable from an oversight, which is precisely
# how the original 15 came about.
DECLINED = {
    "entailment":
        "Out of scope: RDFS/OWL entailment regimes are a different product. "
        "70 cases become available if that ever changes.",
    "service":
        "Out of scope while SERVICE federation is unimplemented. Note "
        "syntax-fed IS run — we parse federation we cannot execute.",
    "service-description":
        "Out of scope: we do not serve a service-description document.",
    "http-rdf-update":
        "Deferred: Graph Store HTTP Protocol, a REST surface for graph "
        "management we do not currently expose.",
}


def _wired_categories() -> set:
    """Read the category lists out of the suites that actually run them."""
    from tests.conformance.test_dawg_sql_v2 import P0_CATEGORIES
    from tests.conformance.test_dawg_update_sql_v2 import UPDATE_CATEGORIES
    from tests.conformance.test_dawg_syntax import (
        MIXED_CATEGORIES,
        SYNTAX_CATEGORIES,
    )
    from tests.conformance.test_dawg_protocol import PROTOCOL_CATEGORIES

    return (
        set(P0_CATEGORIES)
        | set(UPDATE_CATEGORIES)
        | set(SYNTAX_CATEGORIES)
        | set(MIXED_CATEGORIES)
        | set(PROTOCOL_CATEGORIES)
    )


def _corpus_categories() -> set:
    if not SPARQL11_ROOT.exists():
        return set()
    return {
        d.name
        for d in SPARQL11_ROOT.iterdir()
        if d.is_dir() and (d / "manifest.ttl").exists()
    }


@pytest.mark.skipif(
    not SPARQL11_ROOT.exists(), reason="DAWG corpus not present"
)
class TestDAWGCoverage:

    def test_every_category_is_run_or_declined(self):
        corpus = _corpus_categories()
        accounted = _wired_categories() | set(DECLINED)

        unaccounted = sorted(corpus - accounted)
        assert not unaccounted, (
            f"{len(unaccounted)} DAWG categories are neither run nor declined: "
            f"{unaccounted}\n"
            f"Add each to a suite's category list, or to DECLINED in this file "
            f"with the reason. A category that nothing runs produces no failing "
            f"test and no output line, so leaving it unlisted is invisible."
        )

    def test_declined_entries_still_exist(self):
        """A decline for a category that is gone is stale, not cautious."""
        corpus = _corpus_categories()
        stale = sorted(set(DECLINED) - corpus)
        assert not stale, (
            f"DECLINED names categories not in the corpus: {stale}. "
            f"Remove them so the list keeps meaning what it says."
        )

    def test_nothing_is_both_run_and_declined(self):
        """A category that got implemented but kept its decline reads as a gap.

        `protocol` was declined as "deferred, needs a live-server fixture" and
        then got one. Without this, the stale decline would sit there implying
        34 cases are unmeasured while they run on every CI pass.
        """
        both = sorted(_wired_categories() & set(DECLINED))
        assert not both, (
            f"Declined AND run: {both}. Remove the DECLINED entry — a decline "
            f"that is no longer true understates coverage."
        )

    def test_declined_reasons_are_substantive(self):
        for category, reason in DECLINED.items():
            assert len(reason) > 40, (
                f"DECLINED[{category!r}] gives no usable reason. The value of "
                f"this list is the reasoning, not the key."
            )

    def test_wired_categories_exist_in_the_corpus(self):
        """A category listed but absent from disk collects zero tests, silently.

        `syntax-update-1` collected zero for a different reason — an unhandled
        manifest type — and zero collected tests looks exactly like zero
        failures in every count pytest prints.
        """
        corpus = _corpus_categories()
        missing = sorted(_wired_categories() - corpus)
        assert not missing, (
            f"Suites reference categories with no manifest on disk: {missing}"
        )
