"""The install migration: add the column, re-key every space, idempotently.

Run as each install's upgrade step, so it is tested the way an operator runs
it — as a subprocess against the database — on a legacy space (tables by id,
no key), the state every install starts in.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from vitalgraph.db.sparql_sql.space_names import space_prefix
from vitalgraph.db.sparql_sql.space_storage_key import is_keyed, load_storage_keys

from .conftest import (PG_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_USER,
                       skip_no_infra)

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_space_storage_key.py"


def _run(*extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--host", PG_HOST, "--port", str(PG_PORT),
         "--database", PG_DATABASE, "--user", PG_USER,
         f"--password={PG_PASSWORD}", *extra],
        capture_output=True, text=True, timeout=600)


async def test_a_legacy_space_is_re_keyed_once(pg_conn, make_legacy_space):
    sp = await make_legacy_space("inttest_mig_lg")

    dry = _run()
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert f"    {sp} -> vgs_" in dry.stdout and "planned" in dry.stdout
    assert not await is_keyed(pg_conn, sp), "a dry run changes nothing"

    applied = _run("--apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert await is_keyed(pg_conn, sp)
    await load_storage_keys(pg_conn, sp)
    assert space_prefix(sp).startswith("vgs_")
    assert await pg_conn.fetchval("SELECT to_regclass($1) IS NULL",
                                  f"public.{sp}_rdf_quad")

    again = _run("--apply")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "nothing to re-key" in again.stdout


async def test_a_reserved_id_stops_the_re_key(pg_conn, make_legacy_space):
    """A `vgs_`-prefixed id predates the rule; it must be renamed first, and
    the migration says so instead of moving anything."""
    sp = await make_legacy_space("vgs_legacyid")
    out = _run()
    assert out.returncode == 2, out.stdout + out.stderr
    assert sp in out.stdout and "REFUSED" in out.stdout
