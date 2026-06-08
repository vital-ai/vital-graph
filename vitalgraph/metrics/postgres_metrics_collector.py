"""
Query metrics collection using PostgreSQL directly.

Replaces the Redis-based QueryMetricsCollector. Records per-request metrics
into an in-memory buffer that is flushed to PostgreSQL every few seconds.
This avoids adding latency to the request path while keeping a single
database as the source of truth for all metrics data.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SLOW_THRESHOLD_MS = 500
DEFAULT_SLOW_LOG_MAX_AGE_DAYS = 7
DEFAULT_FLUSH_INTERVAL_SECONDS = 5
DEFAULT_FLUSH_BUFFER_SIZE = 50


class PostgresMetricsCollector:
    """Collects per-request metrics and writes to PostgreSQL in batches.

    Uses an in-memory buffer flushed periodically (every 5s or when buffer
    reaches 50 entries). The flush performs aggregate UPSERTs into the
    query_metrics table at minute granularity.
    """

    def __init__(
        self,
        pool,
        slow_threshold_ms: float = DEFAULT_SLOW_THRESHOLD_MS,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        flush_buffer_size: int = DEFAULT_FLUSH_BUFFER_SIZE,
    ):
        self._pool = pool
        self._slow_threshold_ms = slow_threshold_ms
        self._flush_interval = flush_interval
        self._flush_buffer_size = flush_buffer_size
        self._enabled = True
        self._buffer: List[Dict[str, Any]] = []
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    async def start(self):
        """Start the periodic flush background task."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("PostgresMetricsCollector started (flush_interval=%ss)", self._flush_interval)

    async def stop(self):
        """Stop the flush loop and flush remaining buffer."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        # Final flush
        await self._flush()

    def record(
        self,
        space_id: str,
        endpoint: str,
        duration_ms: float,
        error: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Record a metric. Non-blocking — appends to in-memory buffer.

        If the buffer exceeds flush_buffer_size, a flush is triggered
        asynchronously.
        """
        if not self._enabled:
            return

        minute_ts = int(time.time()) // 60 * 60

        entry: Dict[str, Any] = {
            "space_id": space_id,
            "endpoint": endpoint,
            "minute_ts": minute_ts,
            "duration_ms": duration_ms,
            "error": error,
        }
        self._buffer.append(entry)

        # Slow query log entry
        if duration_ms >= self._slow_threshold_ms:
            slow_entry: Dict[str, Any] = {
                "space_id": space_id,
                "endpoint": endpoint,
                "duration_ms": round(duration_ms, 1),
                "metadata": {},
            }
            if metadata:
                for k, v in metadata.items():
                    if isinstance(v, str) and len(v) > 500:
                        slow_entry["metadata"][k] = v[:500] + "..."
                    else:
                        slow_entry["metadata"][k] = v
            self._buffer.append({"_slow": True, **slow_entry})

        # Trigger immediate flush if buffer is large
        if len(self._buffer) >= self._flush_buffer_size and self._running:
            asyncio.create_task(self._flush())

    async def _flush_loop(self):
        """Periodic flush loop."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Metrics flush loop error (non-fatal): {e}")

    async def _flush(self):
        """Flush buffered metrics to PostgreSQL."""
        if not self._buffer:
            return

        # Swap buffer atomically
        buf = self._buffer
        self._buffer = []

        # Separate metric records from slow query entries
        metric_records: List[Dict[str, Any]] = []
        slow_records: List[Dict[str, Any]] = []

        for entry in buf:
            if entry.get("_slow"):
                slow_records.append(entry)
            else:
                metric_records.append(entry)

        # Aggregate metric records by (space_id, minute_ts, endpoint)
        aggregated: Dict[tuple, Dict[str, int]] = {}
        for rec in metric_records:
            key = (rec["space_id"], rec["minute_ts"], rec["endpoint"])
            if key not in aggregated:
                aggregated[key] = {
                    "request_count": 0,
                    "error_count": 0,
                    "total_ms": 0,
                    "max_ms": 0,
                }
            agg = aggregated[key]
            agg["request_count"] += 1
            agg["total_ms"] += int(rec["duration_ms"])
            agg["max_ms"] = max(agg["max_ms"], int(rec["duration_ms"]))
            if rec.get("error"):
                agg["error_count"] += 1

        try:
            async with self._pool.acquire() as conn:
                # Batch UPSERT metrics
                if aggregated:
                    for (space_id, minute_ts, endpoint), stats in aggregated.items():
                        bucket_start = datetime.fromtimestamp(minute_ts, tz=timezone.utc)
                        await conn.execute(
                            """
                            INSERT INTO query_metrics
                                (space_id, bucket_start, bucket_granularity, endpoint,
                                 request_count, error_count, total_ms, max_ms)
                            VALUES ($1, $2, 'minute', $3, $4, $5, $6, $7)
                            ON CONFLICT (space_id, bucket_start, endpoint, bucket_granularity)
                            DO UPDATE SET
                                request_count = query_metrics.request_count + EXCLUDED.request_count,
                                error_count = query_metrics.error_count + EXCLUDED.error_count,
                                total_ms = query_metrics.total_ms + EXCLUDED.total_ms,
                                max_ms = GREATEST(query_metrics.max_ms, EXCLUDED.max_ms)
                            """,
                            space_id, bucket_start, endpoint,
                            stats["request_count"], stats["error_count"],
                            stats["total_ms"], stats["max_ms"],
                        )

                # Insert slow query entries
                if slow_records:
                    for entry in slow_records:
                        meta_json = json.dumps(entry.get("metadata", {}))
                        await conn.execute(
                            """
                            INSERT INTO slow_query_log
                                (space_id, endpoint, duration_ms, metadata)
                            VALUES ($1, $2, $3, $4::jsonb)
                            """,
                            entry["space_id"], entry["endpoint"],
                            int(entry["duration_ms"]), meta_json,
                        )

        except Exception as e:
            logger.debug(f"Metrics flush to PostgreSQL failed (non-fatal): {e}")

    # ─── Read methods (used by MetricsEndpoint) ───────────────────────────

    async def get_realtime_series(
        self, space_id: str, minutes: int = 60
    ) -> Dict[str, Any]:
        """Get per-minute time-series data for the last N minutes from PostgreSQL."""
        since = datetime.fromtimestamp(
            (int(time.time()) // 60 * 60) - (minutes * 60), tz=timezone.utc
        )

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT bucket_start, endpoint, request_count, error_count,
                       total_ms, max_ms
                FROM query_metrics
                WHERE space_id = $1
                  AND bucket_granularity = 'minute'
                  AND bucket_start >= $2
                ORDER BY bucket_start ASC
                """,
                space_id, since,
            )

        return self._rows_to_series(rows, minutes)

    async def get_slow_log(self, space_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent slow queries from PostgreSQL."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT endpoint, duration_ms, recorded_at, metadata
                FROM slow_query_log
                WHERE space_id = $1
                ORDER BY recorded_at DESC
                LIMIT $2
                """,
                space_id, limit,
            )

        results = []
        for row in rows:
            entry: Dict[str, Any] = {
                "ts": row["recorded_at"].timestamp(),
                "space_id": space_id,
                "endpoint": row["endpoint"],
                "ms": row["duration_ms"],
            }
            if row["metadata"]:
                meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"])
                entry.update(meta)
            results.append(entry)
        return results

    # ─── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _rows_to_series(rows, minutes: int) -> Dict[str, Any]:
        """Convert query result rows to per-endpoint time-series structure."""
        now_minute = int(time.time()) // 60 * 60
        timestamps = [now_minute - (i * 60) for i in range(minutes - 1, -1, -1)]
        ts_index = {ts: i for i, ts in enumerate(timestamps)}

        endpoint_data: Dict[str, Dict[str, List[int]]] = {}

        for row in rows:
            bucket_ts = int(row["bucket_start"].timestamp())
            # Round to nearest minute boundary
            bucket_ts = bucket_ts // 60 * 60
            endpoint = row["endpoint"]

            if endpoint not in endpoint_data:
                endpoint_data[endpoint] = {
                    "counts": [0] * minutes,
                    "avg_ms": [0] * minutes,
                    "max_ms": [0] * minutes,
                    "errors": [0] * minutes,
                }

            idx = ts_index.get(bucket_ts)
            if idx is None:
                continue

            data = endpoint_data[endpoint]
            data["counts"][idx] = row["request_count"]
            data["errors"][idx] = row["error_count"]
            data["max_ms"][idx] = row["max_ms"]
            avg = int(row["total_ms"] / row["request_count"]) if row["request_count"] > 0 else 0
            data["avg_ms"][idx] = avg

        # Compute totals
        total_requests = sum(sum(d["counts"]) for d in endpoint_data.values())
        total_errors = sum(sum(d["errors"]) for d in endpoint_data.values())
        all_avg = [v for d in endpoint_data.values() for v in d["avg_ms"] if v > 0]
        avg_latency = int(sum(all_avg) / len(all_avg)) if all_avg else 0

        return {
            "timestamps": timestamps,
            "series": endpoint_data,
            "totals": {
                "total_requests": total_requests,
                "total_errors": total_errors,
                "avg_latency_ms": avg_latency,
            },
        }
