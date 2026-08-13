"""The import/export cleanup job must actually run.

It failed on EVERY scheduler cycle with

    asyncpg.exceptions.UndefinedFunctionError: operator does not exist: uuid = text

because the delete cast the id list to `text[]` while `import_export_job.job_id`
is `uuid`. Terminal-state job rows therefore accumulated forever, and the staged
files they reference were never removed from object storage.

A type mismatch like this cannot be caught by a unit test with a fake
connection — the fake accepts any SQL. It needs a real database, which is why
this lives in the integration suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]


class _SingleConnPool:
    """Adapts one connection to the `async with pool.acquire()` shape."""

    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


async def _seed(conn, space_id, status, age_days):
    job_id = uuid.uuid4()
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    try:
        await conn.execute(
            """
            INSERT INTO import_export_job
                (job_id, job_type, space_id, status, mode, created_at)
            VALUES ($1, 'export', $4, $2, 'append', $3)
            """,
            job_id, status, created, space_id)
    except Exception as e:
        # `space_id` has a FK to `space`, so this uses the real `test_space`
        # fixture rather than inventing an id — spaces are explicitly managed
        # in this codebase and must not be conjured by a data path.
        pytest.skip(f"import_export_job not usable here: {e}")
    return job_id


async def test_cleanup_purges_old_terminal_jobs(pg_conn, test_space):
    """The delete must execute — this is what the uuid/text mismatch broke."""
    from vitalgraph.process.import_export_cleanup_job import ImportExportCleanupJob

    old_done = await _seed(pg_conn, test_space, "completed", age_days=60)
    recent = await _seed(pg_conn, test_space, "completed", age_days=1)

    job = ImportExportCleanupJob(_SingleConnPool(pg_conn), retention_days=30)
    await job.run()          # must not raise

    still_there = await pg_conn.fetchval(
        "SELECT count(*) FROM import_export_job WHERE job_id = $1", old_done)
    kept = await pg_conn.fetchval(
        "SELECT count(*) FROM import_export_job WHERE job_id = $1", recent)

    assert still_there == 0, (
        "a 60-day-old completed job survived a 30-day retention — the purge did "
        "not run, which is how terminal jobs accumulated forever")
    assert kept == 1, "a 1-day-old job was purged under a 30-day retention"

    await pg_conn.execute("DELETE FROM import_export_job WHERE job_id = $1", recent)


async def test_running_jobs_are_never_purged(pg_conn, test_space):
    """Only terminal states are eligible. Deleting a RUNNING job would orphan
    work that is still in flight."""
    from vitalgraph.process.import_export_cleanup_job import ImportExportCleanupJob

    running = await _seed(pg_conn, test_space, "running", age_days=365)

    job = ImportExportCleanupJob(_SingleConnPool(pg_conn), retention_days=0)
    await job.run()

    survived = await pg_conn.fetchval(
        "SELECT count(*) FROM import_export_job WHERE job_id = $1", running)
    assert survived == 1, (
        "a RUNNING job was purged; only completed/failed/cancelled are eligible")

    await pg_conn.execute("DELETE FROM import_export_job WHERE job_id = $1", running)
