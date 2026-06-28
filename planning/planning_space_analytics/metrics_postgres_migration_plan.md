# Metrics: Redis → PostgreSQL-Only Migration Plan

## 1. Motivation

The current metrics system uses a two-tier architecture (Redis hot tier → PostgreSQL cold tier). This adds operational complexity:
- Extra Redis/MemoryDB dependency for metrics (separate from entity dedup)
- 10+ environment variables for Redis config (`QUERY_METRICS_REDIS_*`)
- A rollup job to bridge the two tiers
- Two code paths in the metrics endpoint (Redis for realtime/24h, PostgreSQL for 7d/30d)

PostgreSQL can handle the write volume trivially (~1 UPSERT per request). The simplification removes an entire dependency from the metrics subsystem.

---

## 2. Design

### 2.1 Schema Changes

Replace the current hourly-only `query_metrics` table with a dual-granularity approach:

```sql
-- Per-minute rows (hot, auto-purged after 25h)
-- Per-hour rows (cold, kept 30d+)
-- Same table, differentiated by bucket_granularity

CREATE TABLE IF NOT EXISTS query_metrics (
    space_id          TEXT NOT NULL,
    bucket_start      TIMESTAMPTZ NOT NULL,
    bucket_granularity TEXT NOT NULL DEFAULT 'minute',  -- 'minute' or 'hour'
    endpoint          TEXT NOT NULL,
    request_count     BIGINT NOT NULL DEFAULT 0,
    error_count       BIGINT NOT NULL DEFAULT 0,
    total_ms          BIGINT NOT NULL DEFAULT 0,
    max_ms            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (space_id, bucket_start, endpoint, bucket_granularity)
);

CREATE INDEX IF NOT EXISTS idx_query_metrics_time
    ON query_metrics (bucket_start DESC);
CREATE INDEX IF NOT EXISTS idx_query_metrics_space_gran
    ON query_metrics (space_id, bucket_granularity, bucket_start DESC);
```

New slow query log table:

```sql
CREATE TABLE IF NOT EXISTS slow_query_log (
    id              BIGSERIAL PRIMARY KEY,
    space_id        TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    duration_ms     INTEGER NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB,
    CONSTRAINT fk_slow_space FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_slow_query_space_time
    ON slow_query_log (space_id, recorded_at DESC);
```

### 2.2 New Collector: `PostgresMetricsCollector`

Replaces `QueryMetricsCollector`. Same `record()` interface, but writes to PostgreSQL.

```python
class PostgresMetricsCollector:
    """Collects per-request metrics directly into PostgreSQL.
    
    Uses fire-and-forget asyncio tasks to avoid blocking the request path.
    Batches writes for efficiency (flush every 5s or 50 records).
    """

    def __init__(self, pool, slow_threshold_ms=500, slow_log_size=200):
        self._pool = pool
        self._slow_threshold_ms = slow_threshold_ms
        self._slow_log_size = slow_log_size
        self._buffer = []        # list of pending metric records
        self._flush_task = None  # periodic flush task
        self._enabled = True

    def record(self, space_id, endpoint, duration_ms, error=False, metadata=None):
        """Non-blocking metric recording. Appends to in-memory buffer."""
        ...

    async def _flush(self):
        """Batch-UPSERT buffered metrics into query_metrics table."""
        ...

    async def start(self):
        """Start periodic flush loop (every 5 seconds)."""
        ...

    async def stop(self):
        """Flush remaining buffer and stop."""
        ...
```

**Key design choices:**
- **Buffered writes**: Accumulate metrics in-memory, flush every 5s or when buffer hits 50 entries. This means ~1 SQL statement per 5s per endpoint (not per request).
- **UPSERT aggregation**: Each flush does `INSERT ... ON CONFLICT DO UPDATE SET request_count = request_count + $N` on the current minute bucket.
- **Async fire-and-forget**: `record()` is synchronous (just appends to list). The flush is async in a background task.
- **No Redis dependency**: Only needs the existing asyncpg pool.

### 2.3 Rollup Job (Simplified)

Instead of Redis→PostgreSQL rollup, the new job:
1. Aggregates completed hourly minute-rows into a single hour-row
2. Purges minute-rows older than 25h
3. Purges slow_query_log entries older than 7d
4. Runs hourly (same schedule as before)

```python
class MetricsRollupJob:
    """Aggregates minute rows → hour rows, purges old minute data."""

    async def run(self):
        # 1. Find completed hours with minute-granularity data
        # 2. INSERT hour-level aggregate (SUM counts, MAX max_ms)
        # 3. DELETE minute rows for that hour
        # 4. DELETE slow_query_log WHERE recorded_at < now() - interval '7 days'
```

### 2.4 Metrics Endpoint Changes

Currently the endpoint has two code paths:
- `realtime`/`24h` → reads from Redis
- `7d`/`30d` → reads from PostgreSQL

After migration, **all ranges read from PostgreSQL**:
- `realtime` → `WHERE bucket_granularity = 'minute' AND bucket_start >= now() - interval '60 min'`
- `24h` → `WHERE bucket_granularity = 'minute' AND bucket_start >= now() - interval '24 hours'`
- `7d` → `WHERE bucket_granularity = 'hour' AND bucket_start >= now() - interval '7 days'`
- `30d` → `WHERE bucket_granularity = 'hour' AND bucket_start >= now() - interval '30 days'`

Slow query log reads from `slow_query_log` table instead of Redis LIST.

### 2.5 App Wiring Changes

Remove:
- `QueryMetricsCollector.from_env()` (Redis initialization)
- All `QUERY_METRICS_REDIS_*` env var handling
- Redis client creation for metrics

Add:
- `PostgresMetricsCollector(pool)` initialization after pool is available
- `await collector.start()` in startup
- `await collector.stop()` in shutdown

---

## 3. Migration Steps

| # | Task | Files |
|---|------|-------|
| 1 | Create `PostgresMetricsCollector` class | `vitalgraph/metrics/postgres_metrics_collector.py` (new) |
| 2 | Add `slow_query_log` table to schema | `vitalgraph/db/sparql_sql/sparql_sql_schema.py` |
| 3 | Update PK on `query_metrics` to include `bucket_granularity` | Schema migration |
| 4 | Rewrite `MetricsRollupJob` to aggregate minute→hour + purge | `vitalgraph/process/metrics_rollup_job.py` |
| 5 | Update `MetricsEndpoint` to read all ranges from PostgreSQL | `vitalgraph/endpoint/metrics_endpoint.py` |
| 6 | Update app wiring to use `PostgresMetricsCollector` | `vitalgraph/impl/vitalgraphapp_impl.py` |
| 7 | Keep `query_metrics.py` (Redis version) for backward compat, but stop importing it | No deletion yet |
| 8 | Update planning docs | `planning_space_analytics/query_tracking_plan.md` |
| 9 | Remove Redis env vars from `.env.example` / docs | Various |

---

## 4. Performance Analysis

### Write Path

| Metric | Redis (current) | PostgreSQL (proposed) |
|--------|-----------------|---------------------|
| Per-request overhead | ~6 Redis pipeline commands | Append to in-memory list (O(1)) |
| Actual I/O | 1 Redis round-trip per request | 1 SQL UPSERT per 5s per active (space, minute, endpoint) tuple |
| Worst-case latency added to request | <1ms | 0ms (fully async, buffered) |

At 100 req/s across 5 endpoints in 1 space: 5 UPSERTs every 5 seconds = 1 UPSERT/s. Trivial.

### Read Path

| Query | Redis (current) | PostgreSQL (proposed) |
|-------|-----------------|---------------------|
| Realtime (60 min) | 180 HGETALL calls (3 per minute × 60) | 1 SQL query with WHERE + ORDER |
| 24h | 4,320 HGETALL calls | 1 SQL query |
| 7d | 1 SQL query | 1 SQL query (same) |

**PostgreSQL reads are actually faster** for realtime/24h because it's 1 indexed query vs thousands of Redis round-trips.

### Storage

- Minute rows: ~10 endpoints × 1440 min/day × 1 space = 14,400 rows/space/day (purged after 25h → ~15k rows max per space)
- Hour rows: ~10 endpoints × 24 hours × 30 days = 7,200 rows/space/month
- Slow queries: capped at 7 days, ~100-200 per space typical

Total: negligible for PostgreSQL.

---

## 5. Backward Compatibility

- The `query_metrics` table already exists. The PK needs to be expanded to include `bucket_granularity`.
- Existing hourly rows remain valid (they already have `bucket_granularity = 'hour'`).
- Frontend is unaffected — the API response shape is identical.
- The Redis-based collector remains in the codebase but is no longer instantiated.

---

## 6. What Stays in Redis

| Feature | Stays in Redis? | Why |
|---------|-----------------|-----|
| Entity dedup index | **No** → PostgreSQL | Migrated to PostgreSQL (`ENTITY_DEDUP_BACKEND=postgresql`). MinHash LSH + RapidFuzz now backed by PG tables (`entity_dedup_band`, `entity_dedup_phonetic_band`, `entity_dedup_hash`). |
| Query metrics | **No** → PostgreSQL | Simplification, adequate write volume |

**Redis/MemoryDB is no longer required** for any VitalGraph component. Both metrics and entity dedup have been fully migrated to PostgreSQL.

---

## 7. Implementation Status — ALL COMPLETE ✓

- [x] Step 1: Create `PostgresMetricsCollector` → `vitalgraph/metrics/postgres_metrics_collector.py`
- [x] Step 2: Schema updates (`slow_query_log` table, PK includes `bucket_granularity`) → `sparql_sql_schema.py`
- [x] Step 3: Rewrite `MetricsRollupJob` (no Redis dependency) → `vitalgraph/process/metrics_rollup_job.py`
- [x] Step 4: Update `MetricsEndpoint` (all ranges from PG) → `vitalgraph/endpoint/metrics_endpoint.py`
- [x] Step 5: Update app wiring (PostgresMetricsCollector + start/stop) → `vitalgraph/impl/vitalgraphapp_impl.py`
- [x] Step 6: Update middleware import → `vitalgraph/metrics/metrics_middleware.py`
- [x] Step 7: Verify frontend still works (no API shape change) — ApiService delegates to TS client; response shape unchanged
- [x] Step 8: API consistency migration — routes moved from `/api/spaces/{space_id}/metrics` to `/api/metrics?space_id=...` (query params only)

**Verification**: All backend files parse cleanly. Frontend compiles cleanly (`tsc --noEmit`). All three client libraries (Python, TypeScript, Frontend) synced to new query-param routes.
