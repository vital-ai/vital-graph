"""`devtools/vg-test.env` must name every selector the suites actually read.

The file exists so the target stops depending on things that are not choices —
import order, and which script you happened to run. That only holds while it
covers the full set, and the set grows: a new conftest reading a new variable is
invisible until something answers from the wrong cluster and passes.

The specific live hazard it closes: `tests/api/conftest.py` reads
`LOCAL_CLIENT_SERVER_URL` and falls back to :8002, while `.env` sets that same
variable to :8001 — the DEV server on the HOST cluster, which is up and answers
200. Any `load_dotenv()` reached before that conftest is imported moves the whole
API suite onto the dev stack. Today's import order happens to be safe; nothing
enforces it. An exported value beats `.env`, because python-dotenv does not
override what is already in the environment — which is what sourcing this file
buys, and why it must be complete.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "devtools" / "vg-test.env"

# Where a suite-level target is chosen. Not every test file — only the places
# that decide a stack for everything under them.
CONFTESTS = [
    ROOT / "tests" / "api" / "conftest.py",
    ROOT / "tests" / "integration" / "conftest.py",
    ROOT / "tests" / "performance" / "conftest.py",
    ROOT / "devtools" / "target.py",
]

# Read by these files but deliberately NOT pinned, with the reason.
NOT_A_TARGET = {
    "VG_PERF_RECORD",            # opt-in behaviour, not a stack selector
    "VITALGRAPH_CLIENT_ENVIRONMENT",  # profile name, not an address
    "VG_PG_HOST", "VG_PG_PORT", "VG_PG_DATABASE",   # lower-precedence aliases
    "VG_PG_USER", "VG_PG_PASSWORD",
    "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD",  # libpq fallbacks
}

_ENV_READ = re.compile(r"""os\.(?:environ\.get|getenv|environ)\(?\[?["']([A-Z][A-Z0-9_]{3,})["']""")


def _declared() -> dict:
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_the_file_exists_and_parses():
    assert ENV_FILE.is_file(), f"{ENV_FILE} is what makes the target explicit"
    assert _declared(), "no assignments parsed"


def test_every_selector_a_suite_reads_is_pinned():
    declared = _declared()
    missing = {}
    for path in CONFTESTS:
        if not path.exists():
            continue
        for name in set(_ENV_READ.findall(path.read_text())):
            if name in NOT_A_TARGET or name in declared:
                continue
            missing.setdefault(name, []).append(path.relative_to(ROOT).as_posix())
    assert not missing, (
        "these decide a stack but are not pinned in devtools/vg-test.env, so "
        "sourcing it leaves them to a default and to import order: "
        + "; ".join(f"{k} ({', '.join(v)})" for k, v in sorted(missing.items())))


class TestItSelectsTheTestStackAndNotTheDevOne:
    """The values, not just the names. Each wrong one answers rather than fails."""

    def test_the_database_is_the_docker_stack(self):
        d = _declared()
        assert d["VG_TEST_PG_PORT"] == "5433", "5432 is the host cluster, which " \
            "carries same-named spaces — so it answers and reports success"

    def test_the_sidecar_is_the_test_container(self):
        assert _declared()["VG_TEST_SIDECAR_URL"].endswith(":7071"), \
            "7070 is the dev sidecar, and also the test container's OWN internal " \
            "port, which is how that value gets copied"

    @pytest.mark.parametrize("var", ["LOCAL_CLIENT_SERVER_URL", "VG_TEST_API_URL"])
    def test_both_api_variables_name_the_test_app(self, var):
        """The suites disagree about which variable names the server. Setting one
        leaves the other free to reach :8001."""
        assert _declared()[var].endswith(":8002")

    def test_it_overrides_what_dotenv_would_set(self):
        """`.env` names the dev server for the variable tests/api reads. If this
        file did not also name it, sourcing would not help."""
        env_path = ROOT / ".env"
        if not env_path.exists():
            pytest.skip(".env is local and not present")
        for line in env_path.read_text().splitlines():
            if line.startswith("LOCAL_CLIENT_SERVER_URL="):
                assert "LOCAL_CLIENT_SERVER_URL" in _declared(), (
                    f".env sets {line.strip()} and nothing here overrides it")
                return
