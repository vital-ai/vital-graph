"""The wheel must not ship development or test trees.

`vitalgraph_sparql_sql_dev` shipped for as long as the include glob has been
`vitalgraph*`, because it matches that glob and the seventeen-entry exclude list
names every OTHER test tree explicitly. Six subpackages went into the wheel,
including the DAWG harness and the W3C test corpus.

That was not merely untidy. The package installs, so a stale copy sits in
site-packages, and any script without a `sys.path` insert imports THAT rather
than the repo — `migrate_quad_ctx_pred_index.py` did, and the installed copy
still resolves the host cluster with an empty password, so a migration would
have altered the wrong database and reported success (issues/055).

The exclusion is a glob interaction, not a typo: adding a new `vitalgraph_*_dev`
or `vitalgraph_*_test` tree re-creates it silently, since the include glob will
pick it up and nobody edits the exclude list for a directory they just made.
Hence a rule about the SHAPE of the name rather than a list of known offenders.
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


def test_the_experimental_sparql_package_is_not_shipped():
    shipped = [p for p in PACKAGED if p.startswith("vitalgraph_sparql_sql_dev")]
    assert not shipped, (
        "the experimental package is back in the wheel: " + ", ".join(shipped))


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
