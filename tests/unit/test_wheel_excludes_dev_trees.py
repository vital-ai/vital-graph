"""The wheel must not ship development or test trees.

TWO GATES DECIDE THIS, AND ONLY ONE IS OBVIOUS. `[tool.setuptools.packages.find]`
lists what is a package; `MANIFEST.in` decides which files are collected. Either
one alone keeps a tree out, so reading only one gives a confident wrong answer.

That is not hypothetical — it is how this file was first written. The reasoning
was: `vitalgraph_sparql_sql_dev` matches the `vitalgraph*` include glob and is
absent from the exclude list, therefore it ships. `find_packages` agrees: it
returns six dev subpackages. But the built wheel contains ZERO of them, because
`MANIFEST.in` has carried `recursive-exclude vitalgraph_sparql_sql_dev *` since
v0.0.33 (2026-06-28). Removing only that line puts 55 files back into the wheel.
So a test asserting on `find_packages` alone would pass while the package
shipped — it would check the gate that was already shut and ignore the one doing
the work.

Both are asserted here, and the ARTIFACT is the ground truth: `test-packaging`
inspects the built wheel, because a third mechanism nobody thought of would
defeat both static checks.

IT REALLY DID SHIP ONCE. The v0.0.38 wheel installed on a developer machine
lists 106 dev-package entries, and that stale copy is what shadowed the repo for
`migrate_quad_ctx_pred_index.py`, which had no `sys.path` insert — the installed
resolver still points at the host cluster with an empty password, so a migration
would have altered the wrong database and reported success (issues/055).

The exclusion is a glob interaction, not a typo: a new `vitalgraph_*_dev` tree
re-creates it silently, since the include glob picks it up and nobody edits the
exclude list for a directory they just made. Hence a rule about the SHAPE of the
name rather than a list of known offenders.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from setuptools import find_packages

REPO = Path(__file__).resolve().parents[2]

with open(REPO / "pyproject.toml", "rb") as fh:
    _FIND = tomllib.load(fh)["tool"]["setuptools"]["packages"]["find"]

PACKAGED = sorted(find_packages(where=str(REPO), include=_FIND["include"],
                                exclude=_FIND["exclude"]))

# A top-level package whose name marks it as development or test tooling.
SUSPECT_MARKERS = ("_dev", "_test", "test_", "_tests", "_scripts")


def test_the_inventory_is_not_empty():
    """A broken glob would empty this and pass every assertion below."""
    assert "vitalgraph" in PACKAGED, f"core package missing from {PACKAGED[:5]}"


MANIFEST = (REPO / "MANIFEST.in").read_text()


def test_the_experimental_sparql_package_is_not_shipped():
    shipped = [p for p in PACKAGED if p.startswith("vitalgraph_sparql_sql_dev")]
    assert not shipped, (
        "the experimental package is back in the packages list: " + ", ".join(shipped))


def test_the_manifest_still_excludes_the_experimental_package():
    """The gate that was actually doing the work, and the one easiest to delete.

    `MANIFEST.in` is edited by people adding data files, not by people thinking
    about packages, so this line can go without anyone connecting it to what
    ships.
    """
    assert "recursive-exclude vitalgraph_sparql_sql_dev *" in MANIFEST, (
        "MANIFEST.in no longer excludes the experimental package; on its own the "
        "packages.find exclude has never been what kept it out of the wheel")


@pytest.mark.parametrize("pkg", [p for p in PACKAGED if "." not in p])
def test_no_top_level_dev_or_test_tree_is_shipped(pkg):
    marked = [m for m in SUSPECT_MARKERS if m in pkg]
    assert not marked, (
        f"'{pkg}' looks like a {marked[0]!r} tree but matches the include glob "
        f"{_FIND['include']}; add it to the exclude list in pyproject.toml")


def test_devtools_is_not_shipped():
    """The stack resolver lives outside any shipped package on purpose.

    If `devtools` ever ships, a stale install can shadow it — which is the exact
    failure it was moved out of `vitalgraph_sparql_sql_dev` to escape.
    """
    assert "devtools" not in PACKAGED
    assert not any(p.startswith("devtools.") for p in PACKAGED)
