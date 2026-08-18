"""Every suite resolves the SAME sidecar, and nothing defaults to another one.

The sibling of `test_pg_target_is_shared` (issues/055), for the other service a
test can silently point somewhere else. The database case was found because a
fixture landed in one cluster and the tests read the other. The sidecar case is
quieter, because the sidecar is a stateless compiler: talking to the wrong one
returns a plausible AST rather than an error, and the run reports green.

Two things can go wrong, and they need separate checks.

THE NAME. `VG_TEST_SIDECAR_URL` is how the suite is redirected.
`test_kg_query_builder_escaping` read `VG_SIDECAR_URL` instead. Both defaulted to
localhost:7071, so with nothing exported it worked — which is what made it
invisible. Anyone pointing the suite at another stack would have had that one
file keep talking to their local one.

THE PORT, which is worse and was live. `scripts/probe_semijoin_entity_query.py`
defaulted to **7070**. The test sidecar container publishes host 7071 and maps it
to its own 7070, so host 7070 is a SEPARATE, host-run dev sidecar — that probe
compiled against dev while its `PROBE_DSN` was free to name the test cluster.
Version skew between the two would land as a query-shape mystery.

The name check covers `tests/`, where uniformity is the point. Scripts may keep
their own override (that probe takes every input as `PROBE_*`), so for them what
is pinned is the DEFAULT: whatever the variable is called, an unset environment
must reach the test stack.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CANONICAL = "VG_TEST_SIDECAR_URL"
TEST_SIDECAR_PORT = "7071"

# Deliberately broad: the failure being prevented is a NEW name, so matching only
# the names already known would blind the check to what it exists to catch.
SIDECAR_VAR = re.compile(r"[\"']([A-Z][A-Z0-9_]*SIDECAR[A-Z0-9_]*)[\"']")

# Keyed on the URL, NOT on the variable name. The first version of this check
# required the word "sidecar" on the line, which let
# `SIDE = os.environ.get("TSIDE", "http://localhost:7070")` through in three
# scripts — the check reported clean over a directory it was not really reading.
# Host 7070 is the dev sidecar; the test stack publishes 7071 and maps it to the
# container's own 7070, so `sparql-compiler:7070` inside the compose network is
# correct and must NOT be flagged.
LOCAL_7070 = re.compile(r"https?://(?:localhost|127\.0\.0\.1):7070")


def _sources(root: str):
    """Shell counts: `probe_semijoin_entity_query.sh` exported the dev sidecar,
    and a Python-only sweep never looked at it."""
    return sorted([p for pat in ("*.py", "*.sh") for p in (REPO / root).rglob(pat)])


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _sidecar_vars(path: Path):
    return set(SIDECAR_VAR.findall(_text(path)))


def _dev_sidecar_urls(path: Path):
    """Lines naming the host-run dev sidecar, ignoring prose in docstrings."""
    hits = []
    for n, line in enumerate(_text(path).splitlines(), 1):
        if LOCAL_7070.search(line) and not line.lstrip().startswith("#"):
            hits.append(f"{n}: {line.strip()}")
    return hits


NAME_FILES = sorted((p for p in _sources("tests") if _sidecar_vars(p)),
                    key=lambda p: p.relative_to(REPO).as_posix())
PORT_FILES = sorted(_sources("tests") + _sources("scripts"),
                    key=lambda p: p.relative_to(REPO).as_posix())


class TestTheVariableName:

    def test_the_inventory_is_not_empty(self):
        """Otherwise the parametrised check passes by asserting nothing."""
        assert NAME_FILES, "no test file reads a sidecar variable — the sweep is broken"

    @pytest.mark.parametrize("path", NAME_FILES,
                             ids=[p.relative_to(REPO).as_posix() for p in NAME_FILES])
    def test_only_the_canonical_variable_is_read(self, path):
        rogue = _sidecar_vars(path) - {CANONICAL}
        assert not rogue, (
            f"{path.relative_to(REPO)} reads {sorted(rogue)} instead of {CANONICAL}; "
            f"exporting {CANONICAL} would not redirect this file")


class TestTheDefaultTarget:

    def test_the_inventory_is_not_empty(self):
        assert len(PORT_FILES) > 50, (
            f"only {len(PORT_FILES)} files swept — the glob is not reaching the tree")

    def test_nothing_points_at_the_dev_sidecar(self):
        """One test over the whole tree: a per-file parametrisation would list
        only the files that already match, which is the shape that hid the three
        `TSIDE` scripts."""
        offenders = {p.relative_to(REPO).as_posix(): _dev_sidecar_urls(p)
                     for p in PORT_FILES if _dev_sidecar_urls(p)}
        assert not offenders, (
            "these reach the host-run DEV sidecar on 7070; the test stack is "
            f"{TEST_SIDECAR_PORT} (7070 is also the container's OWN port, which "
            "is why it gets copied):\n" + "\n".join(
                f"  {f}\n    " + "\n    ".join(v) for f, v in sorted(offenders.items())))
