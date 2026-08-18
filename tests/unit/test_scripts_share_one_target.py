"""Nothing chooses its own target — one resolver owns the stack.

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
import subprocess
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

# A target written as a FALLBACK — `os.environ.get(X, "postgresql://...")` or an
# argparse `default=`. This is the shape that misroutes: the variable is never
# exported, the literal wins, and the script connects to whatever its author had
# running. Five scripts defaulted to the host cluster this way while the suites
# used the test stack, and the host carries same-named spaces, so they answered.
# A DSN built from a value discovered at runtime is NOT this and is not matched.
DSN_DEFAULT = re.compile(
    r"(?:os\.environ\.get\([^)]*,\s*|default\s*=\s*)[\"']postgresql://")


def _tracked() -> set:
    """Files git knows about.

    The sweep asserts a property of the REPOSITORY, so it must not read the
    developer's untracked scratch — those fail here and do not exist in CI,
    which is a difference that teaches people to ignore the test. A new file is
    caught the moment it is added to git, which is when it becomes repo content.
    """
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):   # pragma: no cover
        return set()
    return {(REPO / n).resolve() for n in out.split("\0") if n}


_TRACKED = _tracked()


def _sources(root: str):
    """Shell counts: `probe_semijoin_entity_query.sh` exported the dev sidecar,
    and a Python-only sweep never looked at it."""
    found = [p for pat in ("*.py", "*.sh") for p in (REPO / root).rglob(pat)]
    return sorted(p for p in found if not _TRACKED or p.resolve() in _TRACKED)


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
# This file spells the forbidden patterns in order to search for them, so it
# matches itself. Excluded by identity rather than by name so a rename cannot
# quietly reintroduce the self-match.
_SELF = Path(__file__).resolve()
# `test_scripts/` is the scratch tree, and it was excluded here at first on the
# grounds that it is ad-hoc. That was wrong: 33 of its files carried their own
# `SIDECAR_URL` name defaulting to the DEV sidecar on 7070, which made it the
# only tree still disagreeing with everything else. Scratch scripts are the ones
# most likely to be copied into something permanent.
PORT_FILES = sorted((p for p in _sources("tests") + _sources("scripts")
                     + _sources("test_scripts")
                     if p.resolve() != _SELF),
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


class TestNoScriptOwnsItsTarget:
    """The database half of the same rule (issues/055).

    `devtools.target` resolves the stack — `dsn()`, `pg_kwargs()`,
    `add_pg_arguments()`. A script that writes its own fallback opts out of that
    silently, and the failure is a successful run against the wrong cluster.
    """

    @pytest.mark.parametrize("path", PORT_FILES,
                             ids=[p.relative_to(REPO).as_posix() for p in PORT_FILES])
    def test_no_hardcoded_connection_default(self, path):
        # Searched over the WHOLE file, not line by line. The first version
        # matched single lines and stayed silent on
        #     DSN = os.environ.get("TDSN",
        #                          "postgresql://...")
        # which is how `register_dataset_graphs.py` actually spelled it — the
        # check missed the very file that motivated it, and was only caught by
        # reintroducing the original two-line form to see whether it fired.
        text = _text(path)
        hits = [f"line {text.count(chr(10), 0, m.start()) + 1}: "
                f"{m.group(0).split(chr(10))[0].strip()}"
                for m in DSN_DEFAULT.finditer(text)]
        assert not hits, (
            f"{path.relative_to(REPO)} defaults its own connection string; use "
            f"`devtools.target.dsn()` so one place owns the target:\n"
            + "\n".join(f"    {h}" for h in hits))


# `devtools` counts too: the resolver moved there precisely so it could not be
# reached through a stale install, and that only holds if the repo root wins.
REPO_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(?:vitalgraph|vitalgraph_sparql_sql_dev|devtools)\b",
    re.MULTILINE)

SCRIPTS = [p for p in sorted((REPO / "scripts").glob("*.py"))
           if REPO_IMPORT.search(_text(p))]


class TestScriptsImportTheRepoNotTheInstalledCopy:
    """A stale `pip install` of this package is a THIRD way to reach the wrong
    stack, and the one the other checks cannot see.

    `migrate_quad_ctx_pred_index.py` had no `sys.path` insert, so it imported
    `vitalgraph_sparql_sql_dev` from site-packages. That copy still resolves
    port 5432 with an empty password — the pre-issues/055 defaults — while the
    repo resolves 5433. Nothing about the script's own text was wrong; it read a
    DIFFERENT RESOLVER. For a MIGRATION script this is the worst case in
    `test_pg_target_is_shared`'s docstring made real: it alters whichever cluster
    it reaches, and the host carries same-named spaces, so it succeeds.
    """

    def test_the_inventory_is_not_empty(self):
        assert SCRIPTS, "no script imports the repo packages — the sweep is broken"

    @pytest.mark.parametrize("path", SCRIPTS,
                             ids=[p.relative_to(REPO).as_posix() for p in SCRIPTS])
    def test_the_repo_root_is_put_ahead_of_site_packages(self, path):
        text = _text(path)
        insert = text.find("sys.path.insert")
        assert insert != -1, (
            f"{path.relative_to(REPO)} imports the repo packages with no "
            f"sys.path insert, so an installed copy shadows the repo")
        first_import = REPO_IMPORT.search(text).start()
        assert insert < first_import, (
            f"{path.relative_to(REPO)} inserts the repo root AFTER importing "
            f"from it, which is too late to matter")
