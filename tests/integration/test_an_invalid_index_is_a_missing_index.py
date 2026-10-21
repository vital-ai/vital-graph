"""An index left INVALID by a failed concurrent build counts as missing — issues/272.

A `CREATE INDEX CONCURRENTLY` (or `REINDEX CONCURRENTLY`) that fails or is
cancelled leaves its index in the catalog with `indisvalid = false`. The planner
never uses it; every write still maintains it. The `issues/156` check matched
indexes by NAME, so it reported such a space as complete — and every repair is
`CREATE INDEX IF NOT EXISTS`, which skips the name, so nothing could fix it.
Production had one on 2026-10-17 (an empty space's `term_dt`), and the
release's own cancelled `DROP INDEX CONCURRENTLY` left another until its re-run.

The invalid index here is made the way production's was: a concurrent build
that fails part-way (a UNIQUE build over duplicate values), not a catalog edit.
"""

from __future__ import annotations

import logging

import asyncpg
import pytest
import pytest_asyncio
from rdflib import Literal, URIRef

from .conftest import skip_no_infra
from vitalgraph.db.sparql_sql.space_names import space_prefix

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


async def _break(pg_conn, space: str) -> str:
    """Replace the space's `term_dt` with an INVALID index of the same name."""
    name = f"idx_{space_prefix(space)}_term_dt"
    await pg_conn.execute(f'DROP INDEX IF EXISTS "{name}"')
    with pytest.raises(asyncpg.UniqueViolationError):
        await pg_conn.execute(
            f'CREATE UNIQUE INDEX CONCURRENTLY "{name}" ON {space_prefix(space)}_term (term_type)')
    assert await pg_conn.fetchval(
        "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c "
        "ON c.oid = i.indexrelid WHERE c.relname = $1", name), (
        "the failed concurrent build did not leave an invalid index")
    return name


@pytest_asyncio.fixture(loop_scope="session")
async def broken(test_space, space_impl, pg_conn):
    g = URIRef("urn:t272:g")
    await space_impl.add_rdf_quads_batch(test_space, [
        (URIRef(f"urn:t272:s{i}"), URIRef("urn:t272:p"), Literal(f"v{i}"), g)
        for i in range(5)])
    name = await _break(pg_conn, test_space)
    yield name
    from vitalgraph.db.sparql_sql.space_indexes import restore_space_indexes
    await restore_space_indexes(pg_conn, test_space)


async def test_the_check_reports_an_invalid_index_as_missing(test_space, pg_conn, broken):
    from vitalgraph.db.sparql_sql.space_indexes import (
        invalid_space_indexes, missing_space_indexes)
    assert broken in [n for n, _ in await missing_space_indexes(pg_conn, test_space)]
    assert await invalid_space_indexes(pg_conn, test_space) == [broken]


async def test_the_restore_rebuilds_it_valid_and_as_the_schema_defines_it(
        test_space, pg_conn, broken):
    from vitalgraph.db.sparql_sql.space_indexes import (
        missing_space_indexes, restore_space_indexes)
    assert broken in await restore_space_indexes(pg_conn, test_space)
    row = await pg_conn.fetchrow(
        "SELECT i.indisvalid, pg_get_indexdef(c.oid) AS ddl FROM pg_index i "
        "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = $1", broken)
    assert row["indisvalid"]
    assert "UNIQUE" not in row["ddl"] and "(dt_val)" in row["ddl"], row["ddl"]
    assert await missing_space_indexes(pg_conn, test_space) == []


async def test_maintenance_warns_that_it_is_invalid(test_space, pg_pool, broken, caplog):
    from vitalgraph.process import maintenance_job as M
    M.reset_watch_schedule()
    with caplog.at_level(logging.WARNING, logger="vitalgraph.process.maintenance_job"):
        result = await M.MaintenanceJob(pg_pool)._run_space_index_check([test_space])
    assert result and broken in result["spaces"][test_space]
    msgs = [r.getMessage() for r in caplog.records]
    assert any("INVALID" in m and broken in m for m in msgs), msgs
    assert not any("MISSING" in m and broken in m for m in msgs), (
        "an invalid index must get the invalid message, not the missing one")
