"""Every script and suite resolves the SAME database, from one place (issues/055).

`VG_TEST_PG_PORT` had two defaults across the tree: the fixture loaders wrote to
5433 and the test conftests read 5432, so with nothing set a fixture landed in
one cluster and the tests looked in the other. The host carries same-named
spaces, so the queries answered — with stale data — and eighteen assertions
failed a long way from the cause (`issues/099`).

That was fixed for the suites. It was NOT fixed for the nineteen maintenance
scripts, which kept their own copies of the five defaults across TWO env
families:

    VG_TEST_PG_*   10 scripts, all defaulting to port 5432
    VG_PG_*         7 scripts, all defaulting to port 5432
    (the loaders)   2 scripts, defaulting to 5433 — and the tests read 5433

Neither family saw the other's variables, so exporting the one the tests use
left half the scripts pointed at the other cluster. Hit twice in one session:
`migrate_space_schema.py` needed `VG_TEST_PG_PORT=5433` exported and
`repair_derived_tables.py` ignored it, needing `--port 5433` passed by hand.

FOR A MIGRATION SCRIPT THIS IS WORSE THAN FOR A LOADER. A loader writes a
fixture where nobody looks. A migration ALTERS whichever cluster it reached, and
because the host carries same-named spaces it succeeds and reports success.

These tests pin the fix at the level it can regress: the next script to be
written will copy an existing one, and if any existing one still has its own
default, the copy inherits it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = sorted(REPO.glob("scripts/*.py"))

# A hand-rolled default for any of the five connection fields, in either family.
HAND_ROLLED = re.compile(
    r"""os\.environ\.get\(\s*["']VG_(?:TEST_)?PG_"""
    r"""(?:HOST|PORT|DATABASE|USER|PASSWORD)["']""")


def _connects(path: Path) -> bool:
    """Does this script open a database connection at all?"""
    src = path.read_text()
    return ("asyncpg" in src or "psycopg" in src) and "connect" in src


class TestNoScriptKeepsItsOwnDefault:

    def test_the_inventory_is_not_empty(self):
        """The guard on the guard: a glob that matches nothing passes every
        test below while checking nothing."""
        assert len(SCRIPTS) > 20, f"only found {len(SCRIPTS)} scripts"
        assert any(_connects(p) for p in SCRIPTS)

    @pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
    def test_no_hand_rolled_connection_default(self, path):
        hits = HAND_ROLLED.findall(path.read_text())
        assert not hits, (
            f"{path.name} reads VG_*_PG_* directly ({len(hits)} site(s)). Use "
            f"`add_pg_arguments(parser)` or `pg_kwargs()` from "
            f"vitalgraph_sparql_sql_dev.db, so this script cannot disagree "
            f"with the suites about which cluster it is touching.")


class TestTheResolverHonoursBothFamilies:
    """`VG_PG_*` existed only in the scripts and `VG_TEST_PG_*` only in the
    suites. Folding the scripts onto the shared resolver would have silently
    ignored anyone's existing `VG_PG_PORT` had it not learned that family."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for fam in ("VG_TEST_PG", "VG_PG"):
            for f in ("HOST", "PORT", "DATABASE", "USER", "PASSWORD"):
                monkeypatch.delenv(f"{fam}_{f}", raising=False)
        for n in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD",
                  "LOCAL_DB_HOST", "LOCAL_DB_PORT", "LOCAL_DB_NAME",
                  "LOCAL_DB_USERNAME", "LOCAL_DB_PASSWORD"):
            monkeypatch.delenv(n, raising=False)

    def test_the_default_is_the_docker_test_stack(self):
        from vitalgraph_sparql_sql_dev.db import get_connection_params
        assert get_connection_params()["port"] == 5433, (
            "the default must match what the test conftests read, or an unset "
            "environment splits fixtures across two clusters again")

    @pytest.mark.parametrize("var", ["VG_TEST_PG_PORT", "VG_PG_PORT", "PGPORT"])
    def test_each_family_can_override(self, monkeypatch, var):
        from vitalgraph_sparql_sql_dev.db import get_connection_params
        monkeypatch.setenv(var, "5999")
        assert get_connection_params()["port"] == 5999

    def test_the_test_family_wins_over_the_script_family(self, monkeypatch):
        """Precedence has to be decided rather than incidental: with both set,
        the one the suites use is the more specific statement of intent."""
        from vitalgraph_sparql_sql_dev.db import get_connection_params
        monkeypatch.setenv("VG_PG_PORT", "5432")
        monkeypatch.setenv("VG_TEST_PG_PORT", "5433")
        assert get_connection_params()["port"] == 5433

    def test_an_empty_password_is_still_a_value(self):
        """Trust auth is a real configuration, so "" must not fall through to
        the default the way an empty host would."""
        import os
        from vitalgraph_sparql_sql_dev.db import get_connection_params
        os.environ["VG_PG_PASSWORD"] = ""
        try:
            assert get_connection_params()["password"] == ""
        finally:
            del os.environ["VG_PG_PASSWORD"]


class TestTheTargetIsNamed:
    """A script doing the right thing to the wrong database is the failure mode.
    Naming the cluster is what makes it visible without reading the code."""

    @pytest.mark.parametrize("port,expected", [
        (5433, "docker test stack"),
        (5432, "host cluster"),
        (6000, "unrecognised cluster"),
    ])
    def test_it_says_which_cluster(self, port, expected):
        from vitalgraph_sparql_sql_dev.db import describe_target
        got = describe_target({"host": "localhost", "port": port,
                               "dbname": "sparql_sql_graph"})
        assert expected in got and str(port) in got

    def test_it_accepts_argparse_namespaces_and_dicts(self):
        """Scripts hold one or the other; a helper that only takes one gets
        reimplemented in the scripts that hold the other."""
        import argparse
        from vitalgraph_sparql_sql_dev.db import describe_target
        ns = argparse.Namespace(host="h", port=5433, database="d")
        assert "docker test stack" in describe_target(ns)
        assert "docker test stack" in describe_target(
            {"host": "h", "port": 5433, "dbname": "d"})
