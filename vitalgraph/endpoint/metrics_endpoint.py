"""
API endpoints for query metrics retrieval.

All metrics are stored in PostgreSQL (query_metrics + slow_query_log tables).
No Redis dependency.

GET /api/metrics?space_id=... — time-series request metrics
GET /api/metrics/slow?space_id=... — recent slow queries
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)


class MetricsEndpoint:
    """Handles query metrics API routes.

    All data is read from PostgreSQL. Per-minute data is available for realtime/24h,
    hourly aggregates for 7d/30d.
    """

    def __init__(self, api):
        self.api = api
        self.router = APIRouter()
        self._setup_routes()

    def _setup_routes(self):
        @self.router.get("/metrics")
        async def get_space_metrics(
            space_id: str = Query(..., description="Space ID"),
            range: str = Query("realtime", description="Time range: realtime, 24h, 7d, 30d"),
        ):
            return await self.get_metrics(space_id, range)

        @self.router.get("/metrics/slow")
        async def get_slow_queries(
            space_id: str = Query(..., description="Space ID"),
            limit: int = Query(50, ge=1, le=100),
        ):
            return await self.get_slow_log(space_id, limit)

    async def get_metrics(self, space_id: str, time_range: str) -> Dict[str, Any]:
        """Get metrics for a space over a given time range.

        - 'realtime': last 60 minutes (per-minute granularity)
        - '24h': last 24 hours (per-minute granularity)
        - '7d': last 7 days (hourly granularity)
        - '30d': last 30 days (hourly granularity)
        """
        collector = self._get_collector()

        if time_range in ('realtime', '24h'):
            if not collector:
                return self._empty_response(space_id, time_range)

            minutes = 60 if time_range == 'realtime' else 1440
            data = await collector.get_realtime_series(space_id, minutes=minutes)

            return {
                "success": True,
                "space_id": space_id,
                "range": time_range,
                "granularity": "minute",
                "timestamps": [
                    datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                    for ts in data["timestamps"]
                ],
                "series": data["series"],
                "totals": data["totals"],
            }

        elif time_range in ('7d', '30d'):
            days = 7 if time_range == '7d' else 30
            return await self._get_pg_metrics(space_id, time_range, days)

        else:
            return {"success": False, "message": f"Invalid range: {time_range}"}

    async def get_slow_log(self, space_id: str, limit: int) -> Dict[str, Any]:
        """Get recent slow queries from PostgreSQL."""
        collector = self._get_collector()
        if not collector:
            return {
                "success": True,
                "space_id": space_id,
                "slow_queries": [],
                "message": "Metrics collection not enabled",
            }

        entries = await collector.get_slow_log(space_id, limit=limit)
        return {
            "success": True,
            "space_id": space_id,
            "slow_queries": entries,
        }

    async def _get_pg_metrics(
        self, space_id: str, time_range: str, days: int
    ) -> Dict[str, Any]:
        """Read hourly metrics from PostgreSQL."""
        pool = self._get_pool()
        if not pool:
            return self._empty_response(space_id, time_range)

        since = datetime.now(timezone.utc) - timedelta(days=days)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT bucket_start, endpoint, request_count, error_count,
                       total_ms, max_ms
                FROM query_metrics
                WHERE space_id = $1
                  AND bucket_granularity = 'hour'
                  AND bucket_start >= $2
                ORDER BY bucket_start ASC
                """,
                space_id, since,
            )

        # Organize into per-endpoint time series
        series: Dict[str, Dict[str, List]] = {}
        timestamps_set: Dict[str, int] = {}

        for row in rows:
            ts_iso = row['bucket_start'].isoformat()
            endpoint = row['endpoint']

            if ts_iso not in timestamps_set:
                timestamps_set[ts_iso] = len(timestamps_set)

            if endpoint not in series:
                series[endpoint] = {
                    "counts": [],
                    "avg_ms": [],
                    "max_ms": [],
                    "errors": [],
                }

        # Fill in data aligned to timestamps
        timestamps = sorted(timestamps_set.keys())
        ts_index = {ts: i for i, ts in enumerate(timestamps)}

        for ep in series:
            n = len(timestamps)
            series[ep] = {
                "counts": [0] * n,
                "avg_ms": [0] * n,
                "max_ms": [0] * n,
                "errors": [0] * n,
            }

        for row in rows:
            ts_iso = row['bucket_start'].isoformat()
            idx = ts_index[ts_iso]
            endpoint = row['endpoint']

            if endpoint not in series:
                continue

            series[endpoint]["counts"][idx] = row['request_count']
            series[endpoint]["errors"][idx] = row['error_count']
            series[endpoint]["max_ms"][idx] = row['max_ms']
            avg = int(row['total_ms'] / row['request_count']) if row['request_count'] > 0 else 0
            series[endpoint]["avg_ms"][idx] = avg

        # Totals
        total_requests = sum(sum(d["counts"]) for d in series.values())
        total_errors = sum(sum(d["errors"]) for d in series.values())
        all_avg = [v for d in series.values() for v in d["avg_ms"] if v > 0]
        avg_latency = int(sum(all_avg) / len(all_avg)) if all_avg else 0

        return {
            "success": True,
            "space_id": space_id,
            "range": time_range,
            "granularity": "hour",
            "timestamps": timestamps,
            "series": series,
            "totals": {
                "total_requests": total_requests,
                "total_errors": total_errors,
                "avg_latency_ms": avg_latency,
            },
        }

    def _get_collector(self):
        """Get the PostgresMetricsCollector from the API instance."""
        return getattr(self.api, '_metrics_collector', None)

    def _get_pool(self):
        """Get the asyncpg pool from the API instance."""
        if hasattr(self.api, 'space_manager'):
            sm = self.api.space_manager
            if hasattr(sm, '_db') and hasattr(sm._db, '_pool'):
                return sm._db._pool
        if hasattr(self.api, '_pool'):
            return self.api._pool
        return None

    def _empty_response(self, space_id: str, time_range: str) -> Dict[str, Any]:
        return {
            "success": True,
            "space_id": space_id,
            "range": time_range,
            "granularity": "minute" if time_range in ('realtime', '24h') else "hour",
            "timestamps": [],
            "series": {},
            "totals": {
                "total_requests": 0,
                "total_errors": 0,
                "avg_latency_ms": 0,
            },
        }
