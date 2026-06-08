"""
Import/Export Cleanup Job — removes old completed/failed jobs and their staged files.

Registered with ProcessScheduler; default interval: daily (86400s).

Behaviour:
    1. Delete rows from ``import_export_job`` where status is 'completed' or
       'failed' and the row is older than ``job_retention_days``.
    2. For each deleted row that has a ``file_s3_key``, remove the object from
       the staging bucket.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class ImportExportCleanupJob:
    """Periodic cleanup of stale import/export job records and staged files.

    Constructor args:
        pool: asyncpg connection pool.
        retention_days: Delete jobs older than this many days (default 30).
        storage_backend: Optional async object with
            ``async delete_object(bucket, key)`` for removing staged files.
        staging_bucket: Bucket name used by import/export staging.
    """

    def __init__(
        self,
        pool,
        retention_days: int = 30,
        storage_backend=None,
        staging_bucket: str = "vitalgraph-staging",
    ):
        self._pool = pool
        self._retention_days = retention_days
        self._storage = storage_backend
        self._bucket = staging_bucket

    async def run(self):
        """Execute one cleanup cycle."""
        import asyncpg

        start = time.perf_counter()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)

        async with self._pool.acquire() as conn:
            # Fetch rows to delete (need file_s3_key for cleanup)
            try:
                rows = await conn.fetch(
                    """
                    SELECT job_id, file_s3_key
                    FROM import_export_job
                    WHERE status IN ('completed', 'failed', 'cancelled')
                      AND created_at < $1
                    """,
                    cutoff,
                )
            except asyncpg.exceptions.UndefinedTableError:
                logger.debug("Import/export cleanup: import_export_job table does not exist, skipping")
                return

            if not rows:
                logger.debug("Import/export cleanup: nothing to purge")
                return

            job_ids = [r['job_id'] for r in rows]
            s3_keys = [r['file_s3_key'] for r in rows if r['file_s3_key']]

            # Delete job rows
            await conn.execute(
                """
                DELETE FROM import_export_job
                WHERE job_id = ANY($1::text[])
                """,
                job_ids,
            )

        # Remove staged files from object storage
        files_removed = 0
        if self._storage and s3_keys:
            for key in s3_keys:
                try:
                    await self._storage.delete_object(self._bucket, key)
                    files_removed += 1
                except Exception as e:
                    logger.warning("Failed to delete staged file %s: %s", key, e)

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "Import/export cleanup: %d jobs purged, %d staged files removed (%.0fms)",
            len(job_ids), files_removed, elapsed,
        )
