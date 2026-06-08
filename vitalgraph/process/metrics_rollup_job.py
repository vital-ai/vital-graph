"""
Metrics rollup job — aggregates per-minute PostgreSQL rows into hourly
summaries and purges stale minute data.

Registered with ProcessScheduler to run every hour.
"""

import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Keep minute-granularity data for 25 hours (slightly over 24h for safety)
MINUTE_RETENTION_HOURS = 25
# Keep slow query log for 7 days
SLOW_LOG_RETENTION_DAYS = 7


class MetricsRollupJob:
    """Aggregates minute-level metrics into hourly rows and purges old data.

    1. Finds completed hours that still have minute-granularity rows.
    2. Aggregates them into a single hour-level row per (space, endpoint).
    3. Deletes the original minute rows for that hour.
    4. Purges slow_query_log entries older than 7 days.
    """

    def __init__(self, pool):
        """
        Args:
            pool: asyncpg connection pool for PostgreSQL reads/writes.
        """
        self._pool = pool

    async def run(self):
        """Execute one rollup cycle."""
        start = time.perf_counter()
        now = int(time.time())

        # The most recently completed hour boundary
        current_hour_start = (now // 3600) * 3600
        cutoff = datetime.fromtimestamp(current_hour_start, tz=timezone.utc)

        async with self._pool.acquire() as conn:
            # 1. Aggregate completed-hour minute rows → hour rows
            rows_rolled = await conn.fetchval(
                """
                WITH hourly_agg AS (
                    SELECT
                        space_id,
                        date_trunc('hour', bucket_start) AS hour_start,
                        endpoint,
                        SUM(request_count) AS request_count,
                        SUM(error_count) AS error_count,
                        SUM(total_ms) AS total_ms,
                        MAX(max_ms) AS max_ms
                    FROM query_metrics
                    WHERE bucket_granularity = 'minute'
                      AND bucket_start < $1
                    GROUP BY space_id, date_trunc('hour', bucket_start), endpoint
                ),
                inserted AS (
                    INSERT INTO query_metrics
                        (space_id, bucket_start, bucket_granularity, endpoint,
                         request_count, error_count, total_ms, max_ms)
                    SELECT space_id, hour_start, 'hour', endpoint,
                           request_count, error_count, total_ms, max_ms
                    FROM hourly_agg
                    ON CONFLICT (space_id, bucket_start, endpoint, bucket_granularity)
                    DO UPDATE SET
                        request_count = query_metrics.request_count + EXCLUDED.request_count,
                        error_count = query_metrics.error_count + EXCLUDED.error_count,
                        total_ms = query_metrics.total_ms + EXCLUDED.total_ms,
                        max_ms = GREATEST(query_metrics.max_ms, EXCLUDED.max_ms)
                    RETURNING 1
                )
                SELECT COUNT(*) FROM inserted
                """,
                cutoff,
            )

            # 2. Delete the minute rows we just rolled up
            deleted_minutes = await conn.fetchval(
                """
                DELETE FROM query_metrics
                WHERE bucket_granularity = 'minute'
                  AND bucket_start < $1
                RETURNING 1
                """,
                cutoff,
            )

            # 3. Purge old slow query log entries
            slow_cutoff = datetime.fromtimestamp(
                now - SLOW_LOG_RETENTION_DAYS * 86400, tz=timezone.utc
            )
            deleted_slow = await conn.fetchval(
                """
                DELETE FROM slow_query_log
                WHERE recorded_at < $1
                RETURNING 1
                """,
                slow_cutoff,
            )

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(
            "Metrics rollup: %s hour rows upserted, %s minute rows purged, "
            "%s slow log entries purged (%.0fms)",
            rows_rolled or 0, deleted_minutes or 0, deleted_slow or 0, elapsed,
        )
