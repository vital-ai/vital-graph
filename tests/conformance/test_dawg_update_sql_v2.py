"""DAWG SPARQL 1.1 **Update** conformance — executed against the SQL backend.

Closes the structural gap in
``issues/023_values_clause_ignored_in_sparql_update.md``: update WHERE patterns
had no conformance coverage in pytest at all. A complete runner already existed
(``dawg_test_impl/dawg_update_test.py``, driven by ``dawg_test_runner.py``) but
lived outside ``testpaths`` and was never collected, so the
``mf:UpdateEvaluationTest`` entries — 9 in ``delete-insert`` alone — were parsed
and discarded.

Each case runs through the **real SPARQL→SQL translation**: load the pre-state,
execute the update, compare the resulting graph to the manifest's expected
post-state. ``test_dawg_sql_v2.py`` does the equivalent for queries — though
only from 2026-08-04; before that it ran the pyoxigraph oracle alone and never
touched the SQL pipeline, so neither queries nor updates had real conformance
coverage.

Requires PostgreSQL + Jena sidecar; auto-skips without them.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Tuple

import pytest

from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_manifest_parser import (
    get_manifest_path,
)
from vitalgraph_sparql_sql_dev.dawg_test_impl.dawg_update_test import (
    DawgUpdateTestCase,
    parse_update_manifest,
    run_single_update_test_v2,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAWG_ROOT = _PROJECT_ROOT / "tests" / "conformance" / "dawg_data"

# Mirrors dawg_test_runner.UPDATE_CATEGORIES — every category whose manifest
# holds mf:UpdateEvaluationTest entries.
UPDATE_CATEGORIES = [
    "add",
    "basic-update",
    "clear",
    "copy",
    "delete",
    "delete-data",
    "delete-insert",
    "delete-where",
    "drop",
    "move",
    "update-silent",
]

# The TEST-stack sidecar (vitalgraph-test-sidecar, host 7071 -> 7070 in the
# container), not the dev one on 7070. tests/performance already defaulted
# here; integration and conformance did not, so they silently checked a
# sidecar belonging to the other stack — and skipped themselves when it was
# down, which reads as "infrastructure absent" rather than "wrong port".
SIDECAR_URL = os.environ.get("VG_TEST_SIDECAR_URL", "http://localhost:7071")


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

def _check_sidecar() -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{SIDECAR_URL}/v1/sparql/compile",
            data=b'{"sparql":"SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _check_pg() -> bool:
    try:
        import asyncpg
        from vitalgraph_sparql_sql_dev import db as devdb

        async def _try():
            conn = await asyncpg.connect(**devdb._asyncpg_connect_kwargs())
            await conn.close()
            return True

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_try())
        finally:
            loop.close()
    except Exception:
        return False


HAS_INFRASTRUCTURE = _check_sidecar() and _check_pg()

pytestmark = [
    pytest.mark.dawg,
    pytest.mark.sql_v2,
    pytest.mark.skipif(
        not HAS_INFRASTRUCTURE,
        reason="Requires PostgreSQL + Jena sidecar (localhost:7070)",
    ),
]


# ---------------------------------------------------------------------------
# Known failures
#
# Each entry is a real gap in the update pipeline, kept visible rather than
# excluded from collection. Removing an entry must make its test pass.
# ---------------------------------------------------------------------------

XFAIL_UPDATES: dict = {}


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _collect() -> List[Tuple[str, DawgUpdateTestCase]]:
    if not DAWG_ROOT.exists():
        return []
    out: List[Tuple[str, DawgUpdateTestCase]] = []
    for category in UPDATE_CATEGORIES:
        manifest = get_manifest_path(DAWG_ROOT, category)
        if not manifest.exists():
            continue
        for tc in parse_update_manifest(manifest, category=category):
            out.append((f"{category}/{tc.name}", tc))
    return out


_UPDATE_TESTS = _collect()


# ---------------------------------------------------------------------------
# Shared DB connection — module-scoped, driven by an explicit loop so this
# module does not depend on pytest-asyncio loop scoping.
# ---------------------------------------------------------------------------

# The DB connection and event loop are session-scoped and shared with the
# query-side suite — see tests/conformance/conftest.py for why they must be.


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _UPDATE_TESTS, reason="No DAWG update manifests found")
class TestDawgUpdateSqlV2:
    """Each manifest entry: load pre-state, run the update through the real
    SPARQL→SQL pipeline, compare the resulting graph to the expected
    post-state."""

    @pytest.mark.parametrize(
        "name,tc", _UPDATE_TESTS, ids=[t[0] for t in _UPDATE_TESTS],
    )
    def test_update(self, name: str, tc: DawgUpdateTestCase, dawg_conn, dawg_loop):
        key = (tc.category, tc.name)
        if key in XFAIL_UPDATES:
            pytest.xfail(XFAIL_UPDATES[key])

        result = dawg_loop.run_until_complete(
            run_single_update_test_v2(tc, dawg_conn)
        )

        if result.status == "SKIP":
            pytest.skip(result.error_message or "runner skipped")
        if result.status != "PASS":
            pytest.fail(
                f"{result.status}: {result.error_message}\n"
                f"  category={tc.category} test={tc.name}\n"
                f"  request={tc.request_file}"
            )


def test_update_manifests_are_actually_collected():
    """Guard the gap that hid issue 023.

    The update manifests were parsed and silently discarded for so long that
    the absence looked like 'no update tests exist'. If collection breaks
    again, fail loudly here rather than reporting a green run of zero tests.
    """
    assert _UPDATE_TESTS, (
        "No mf:UpdateEvaluationTest cases collected — update conformance has "
        "silently stopped running"
    )
    categories = {tc.category for _, tc in _UPDATE_TESTS}
    assert "delete-insert" in categories, (
        f"delete-insert update tests missing; got categories: {sorted(categories)}"
    )
