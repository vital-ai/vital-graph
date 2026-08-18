"""The DAWG corpus must be present, and the suite must not be empty.

This is the check that was missing. The corpus lived in a gitignored directory,
so CI had none of it, and `test_dawg_pyoxigraph.py` collected two tests and
skipped both — "got empty parameter set". The step passed. Conformance had never
run in CI, and nothing said so, because pytest reports an empty parametrisation
as a skip and a skip is not a failure.

Every other DAWG file guards itself with `if not DAWG_ROOT.exists(): return []`,
which is correct behaviour for a collector and is exactly why the absence was
silent. Something has to assert the data IS there, or "no tests" reads as "no
problems" forever.

The minimum counts are deliberately far below the real totals (1,068 collected at
the time of writing). They are a floor against the corpus vanishing or being
truncated, not a ledger to update whenever upstream adds a test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DAWG_DATA = Path(__file__).resolve().parent / "dawg_data"
SPARQL = DAWG_DATA / "sparql"

# Categories the manifest parser resolves under sparql11.
SAMPLE_CATEGORIES = ["aggregates", "bind", "construct", "subquery", "property-path"]

MIN_MANIFESTS = 50
MIN_QUERY_FILES = 500


def test_the_corpus_directory_is_committed():
    assert DAWG_DATA.is_dir(), (
        f"{DAWG_DATA} is missing — the W3C SPARQL suite is committed to this "
        f"repo on purpose; a checkout without it makes every DAWG test collect "
        f"nothing and pass")
    assert (DAWG_DATA / "LICENSE.md").is_file(), (
        "upstream LICENSE.md must ship with the corpus — it governs redistribution")


@pytest.mark.parametrize("version", ["sparql10", "sparql11", "sparql12"])
def test_each_suite_version_is_present(version):
    assert (SPARQL / version).is_dir(), f"{version} missing from the corpus"


@pytest.mark.parametrize("category", SAMPLE_CATEGORIES)
def test_the_manifest_each_test_module_resolves_exists(category):
    """`get_manifest_path` appends exactly this path; if it is wrong, every
    category silently yields zero tests."""
    manifest = SPARQL / "sparql11" / category / "manifest.ttl"
    assert manifest.is_file(), f"no manifest at {manifest}"
    assert manifest.stat().st_size > 0, f"empty manifest at {manifest}"


def test_the_corpus_is_not_truncated():
    manifests = list(SPARQL.rglob("manifest.ttl"))
    queries = list(SPARQL.rglob("*.rq"))
    assert len(manifests) >= MIN_MANIFESTS, (
        f"only {len(manifests)} manifests found, expected at least {MIN_MANIFESTS}")
    assert len(queries) >= MIN_QUERY_FILES, (
        f"only {len(queries)} .rq query files found, expected at least "
        f"{MIN_QUERY_FILES}")


def test_the_pyoxigraph_suite_actually_collects_tests():
    """The specific thing that was passing while empty.

    Imports the module the CI step runs and asserts its parametrisation is
    populated — the same list pytest would turn into two skipped tests if the
    corpus were absent.
    """
    from tests.conformance import test_dawg_pyoxigraph as mod

    assert mod.DAWG_ROOT.exists(), f"{mod.DAWG_ROOT} does not exist"
    assert len(mod._DAWG_TESTS) >= 100, (
        f"pyoxigraph conformance collected only {len(mod._DAWG_TESTS)} cases; "
        f"an empty or tiny parametrisation is reported as a SKIP, which passes")
