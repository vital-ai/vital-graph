# Query Tracking & Time-Series Analytics

## Overview

Track API/query activity over time per space, leveraging the existing MemoryDB (Redis Cluster)
infrastructure already used for entity dedup. This gives real-time counters and recent history
without burdening PostgreSQL with high-frequency writes.

---

## Architecture: Two-Tier Storage

```
 Request → Middleware → Redis (hot, per-minute buckets) ─┐
                                                          │  Rollup job (hourly)
 Frontend ← API ← PostgreSQL (cold, hourly/daily agg.) ←─┘
```

### Tier 1: Redis/MemoryDB (hot, ~24h retention)

**Why Redis?**
- Already deployed (entity dedup uses MemoryDB cluster with TLS + auth)
- Sub-ms writes — zero impact on request latency
- Native time-series data structures (sorted sets, hash expiry)
- Shared across all workers/containers automatically

**Data structures per space:**

| Key pattern | Type | Content |
|---|---|---|
| `{metrics}:{space_id}:qpm:{minute_ts}` | HASH | endpoint → count |
| `{metrics}:{space_id}:latency:{minute_ts}` | HASH | endpoint → sum_ms, count, max_ms |
| `{metrics}:{space_id}:errors:{minute_ts}` | HASH | endpoint → count |
| `{metrics}:{space_id}:slow_log` | LIST (capped) | Recent slow queries (>500ms) as JSON |
| `{metrics}:global:active_spaces` | SET | Space IDs seen in last hour |

All minute-bucket keys use `EXPIRE 86400` (auto-cleanup after 24h).

Hash tags `{metrics}` ensure all keys for a logical group land on the same shard
(same pattern as the dedup index).

### Tier 2: PostgreSQL (cold, permanent)

New table in admin schema (alongside `space_analytics`):

```sql
CREATE TABLE IF NOT EXISTS query_metrics (
    space_id        TEXT NOT NULL REFERENCES space(space_id),
    bucket_start    TIMESTAMPTZ NOT NULL,  -- hour boundary
    bucket_granularity TEXT NOT NULL DEFAULT 'hour',  -- 'hour' or 'day'
    endpoint        TEXT NOT NULL,         -- e.g. 'sparql_query', 'kgentities_list'
    request_count   BIGINT NOT NULL DEFAULT 0,
    error_count     BIGINT NOT NULL DEFAULT 0,
    total_ms        BIGINT NOT NULL DEFAULT 0,      -- sum of latencies
    max_ms          INTEGER NOT NULL DEFAULT 0,
    p95_ms          INTEGER,               -- optional, from histogram
    PRIMARY KEY (space_id, bucket_start, endpoint)
);

CREATE INDEX idx_query_metrics_time ON query_metrics (bucket_start DESC);
```

---

## Collection Layer (Middleware)

A lightweight FastAPI middleware or dependency that fires after each request:

```python
class QueryMetricsCollector:
    """Collects per-request metrics and writes to Redis asynchronously."""

    def __init__(self, redis_client):
        self._redis = redis_client
        self._enabled = True

    async def record(self, space_id: str, endpoint: str, duration_ms: float, error: bool):
        """Fire-and-forget metric recording."""
        minute_ts = int(time.time()) // 60 * 60  # round to minute
        pipe = self._redis.pipeline()
        
        # Request count
        qpm_key = f"{{metrics}}:{space_id}:qpm:{minute_ts}"
        pipe.hincrby(qpm_key, endpoint, 1)
        pipe.expire(qpm_key, 86400)
        
        # Latency accumulator
        lat_key = f"{{metrics}}:{space_id}:latency:{minute_ts}"
        pipe.hincrby(lat_key, f"{endpoint}:sum", int(duration_ms))
        pipe.hincrby(lat_key, f"{endpoint}:count", 1)
        # Track max via Lua or separate HSET with compare
        pipe.expire(lat_key, 86400)
        
        # Error count
        if error:
            err_key = f"{{metrics}}:{space_id}:errors:{minute_ts}"
            pipe.hincrby(err_key, endpoint, 1)
            pipe.expire(err_key, 86400)
        
        # Slow query log (>500ms)
        if duration_ms > 500:
            slow_key = f"{{metrics}}:{space_id}:slow_log"
            entry = json.dumps({"ts": time.time(), "endpoint": endpoint, "ms": duration_ms})
            pipe.lpush(slow_key, entry)
            pipe.ltrim(slow_key, 0, 99)  # keep last 100
        
        await pipe.execute()
```

**Endpoint classification** (derived from route path):
- `sparql_query` — SPARQL SELECT/CONSTRUCT/ASK
- `kgentities_list`, `kgentities_get`, `kgentities_create`, `kgentities_update`
- `kgframes_*`, `kgrelations_*`
- `triples_list`, `triples_add`, `triples_delete`
- `graphs_list`, `graphs_create`

---

## Rollup Job (ProcessScheduler)

Runs hourly via existing `ProcessScheduler` (same as maintenance + analytics jobs):

```python
class MetricsRollupJob:
    """Rolls up per-minute Redis metrics into hourly PostgreSQL aggregates."""
    
    async def run(self):
        # For each space seen in last hour:
        #   1. SCAN minute-bucket keys for the previous hour
        #   2. Aggregate: sum counts, sum latencies, find max
        #   3. UPSERT into query_metrics table
        #   4. (Keys auto-expire from Redis after 24h)
        pass
```

**Daily rollup** (optional, for long-term storage efficiency):
- Aggregate hourly rows into daily summaries
- Keep hourly detail for 30 days, daily for 1 year

---

## API Endpoints

### `GET /api/spaces/{space_id}/metrics`

Returns recent metrics. Two modes:

```
?range=realtime  →  reads directly from Redis (last 60 minutes, per-minute)
?range=24h       →  reads from Redis (all available minute buckets)
?range=7d        →  reads from PostgreSQL (hourly aggregates)
?range=30d       →  reads from PostgreSQL (daily aggregates)
```

Response shape:
```json
{
  "space_id": "my_space",
  "range": "24h",
  "granularity": "minute",
  "series": {
    "sparql_query": {
      "timestamps": ["2026-06-06T18:00:00Z", ...],
      "counts": [12, 8, 15, ...],
      "avg_ms": [45, 62, 38, ...],
      "max_ms": [120, 340, 95, ...]
    },
    "kgentities_list": { ... }
  },
  "totals": {
    "total_requests": 1247,
    "total_errors": 3,
    "avg_latency_ms": 52,
    "p95_latency_ms": 180
  }
}
```

### `GET /api/spaces/{space_id}/metrics/slow`

Returns recent slow queries from the Redis capped list.

---

## Frontend Integration

Add a **"Metrics"** tab to the SpaceDetail page (alongside Settings and Analytics):

- **Real-time dashboard**: Line chart (ApexCharts) showing requests/min over last hour
- **Latency chart**: Area chart with avg and p95 bands
- **Endpoint breakdown**: Stacked bar chart by endpoint type
- **Slow query table**: Sortable list of recent slow queries
- **Error rate**: Small alert-colored indicator

---

## Configuration

Reuses existing `get_scoped_env` pattern:

| Env var | Default | Description |
|---|---|---|
| `QUERY_METRICS_ENABLED` | `true` | Kill switch |
| `QUERY_METRICS_REDIS_HOST` | (from dedup config) | Can share the dedup Redis |
| `QUERY_METRICS_REDIS_PORT` | `6379` | |
| `QUERY_METRICS_SLOW_THRESHOLD_MS` | `500` | Slow query threshold |
| `QUERY_METRICS_RETENTION_DAYS` | `30` | PostgreSQL hourly retention |

**Sharing the dedup Redis**: Since MemoryDB is already deployed, metrics can use
the same cluster with a different hash tag prefix (`{metrics}` vs `{dedup}`).
No additional infrastructure needed.

---

## Architecture Update — Redis → PostgreSQL (June 2026)

The original two-tier architecture (Redis hot → PostgreSQL cold) has been simplified to
**PostgreSQL-only**. See `metrics_postgres_migration_plan.md` for the full rationale.

**Key changes:**
- `PostgresMetricsCollector` replaces `QueryMetricsCollector` (buffered writes, no Redis)
- `MetricsRollupJob` simplified (aggregates minute→hour in PG, no Redis scanning)
- `MetricsEndpoint` reads all ranges from PostgreSQL (minute rows for realtime/24h, hour rows for 7d/30d)
- Redis dependency removed from metrics subsystem
- Entity dedup has also been migrated to PostgreSQL (`ENTITY_DEDUP_BACKEND=postgresql`) — Redis/MemoryDB is no longer required for any VitalGraph component
- API response shape is **unchanged** — frontend requires no modifications

---

## API Consistency Update (June 2026)

All REST endpoints have been migrated to **static URL paths with query parameters only** — no dynamic path segments (`{param}`). This applies to metrics and spaces endpoints:

**Metrics routes (before → after):**
```
GET /api/spaces/{space_id}/metrics   →  GET /api/metrics?space_id=...
GET /api/spaces/{space_id}/metrics/slow  →  GET /api/metrics/slow?space_id=...
```

**Spaces routes (before → after):**
```
GET /api/spaces/{space_id}           →  GET /api/spaces/space?space_id=...
GET /api/spaces/{space_id}/info      →  GET /api/spaces/info?space_id=...
GET /api/spaces/{space_id}/analytics →  GET /api/spaces/analytics?space_id=...
```

**Middleware patterns** in `metrics_middleware.py` updated accordingly — SPARQL/graph endpoints now use static path patterns with `space_id` extracted from query params.

**Frontend** — `ApiService.ts` now delegates all calls to the typed TypeScript client (`vgClient.*`). No raw `fetch` calls remain in ApiService.

---

## Implementation Status — COMPLETE ✓

All components have been implemented and integrated:

| # | Component | File(s) | Status |
|---|-----------|---------|--------|
| 1 | PostgreSQL metrics collector | `vitalgraph/metrics/postgres_metrics_collector.py` | ✓ Done |
| 2 | Metrics middleware | `vitalgraph/metrics/metrics_middleware.py` | ✓ Done (static paths, query-param space_id) |
| 3 | Rollup job | `vitalgraph/process/metrics_rollup_job.py` | ✓ Done (PG-only, no Redis) |
| 4 | PostgreSQL schema | `vitalgraph/db/sparql_sql/sparql_sql_schema.py` | ✓ Done |
| 5 | API endpoints | `vitalgraph/endpoint/metrics_endpoint.py` | ✓ Done (`/api/metrics?space_id=...`) |
| 6 | App wiring | `vitalgraph/impl/vitalgraphapp_impl.py` | ✓ Done |
| 7 | Frontend component | `frontend/src/components/SpaceMetrics.tsx` | ✓ Done |
| 8 | Frontend API service | `frontend/src/services/ApiService.ts` | ✓ Done (delegates to TS client `vgClient.metrics.*`) |
| 9 | Frontend tab integration | `frontend/src/pages/SpaceDetail.tsx` | ✓ Done |
| 10 | Legacy Redis collector | `vitalgraph/metrics/query_metrics.py` | Legacy — no longer instantiated |

### Implementation Details

**1. PostgresMetricsCollector** (`vitalgraph/metrics/postgres_metrics_collector.py`)
- Buffered writes to PostgreSQL (flush every 5s or 50 entries)
- UPSERT aggregation into per-minute `query_metrics` buckets
- Slow query log stored in `slow_query_log` table
- `get_realtime_series()` for reading minute-level data back
- No Redis dependency — only needs asyncpg pool

**1b. Legacy Redis Collector** (`vitalgraph/metrics/query_metrics.py`)
- Original Redis-based collector — **no longer instantiated**
- Kept in codebase for backward compatibility reference only

**2. MetricsMiddleware** (`vitalgraph/metrics/metrics_middleware.py`)
- Starlette `BaseHTTPMiddleware` subclass
- Reads collector from `request.app.state.metrics_collector`
- Classifies requests by regex patterns → (space_id, endpoint)
- All endpoint patterns use static paths; `space_id` extracted from query params for SPARQL/graph/KG endpoints
- Skips health checks, static files, auth endpoints
- Records timing + error status after each request

**3. MetricsRollupJob** (`vitalgraph/process/metrics_rollup_job.py`)
- Registered with ProcessScheduler (1-hour interval)
- Aggregates minute-granularity PostgreSQL rows into hourly rows
- Purges minute rows older than 25h, slow_query_log entries older than 7d
- No Redis dependency

**4. PostgreSQL Schema**
- Table: `query_metrics` with composite PK `(space_id, bucket_start, endpoint, bucket_granularity)`
- Table: `slow_query_log` with auto-increment PK, cascading FK to space
- Indexes: `idx_query_metrics_time`, `idx_query_metrics_space_gran`, `idx_slow_query_space_time`
- Added to `ADMIN_DROP_ORDER`

**5. MetricsEndpoint** (`vitalgraph/endpoint/metrics_endpoint.py`)
- `GET /api/metrics?space_id=...&range=realtime|24h|7d|30d`
- `GET /api/metrics/slow?space_id=...&limit=50`
- All ranges read from PostgreSQL (minute rows for realtime/24h, hourly for 7d/30d)
- Returns structured JSON with timestamps, per-endpoint series, and totals

**6. App Wiring** (`vitalgraph/impl/vitalgraphapp_impl.py`)
- `MetricsMiddleware` registered via `app.add_middleware()`
- `PostgresMetricsCollector` initialized after DB pool is available and stored on `app.state`
- Rollup job registered with ProcessScheduler
- Metrics router included at `/api` prefix
- Segmentation worker started/stopped in startup/shutdown
- ImportExportJobManager created lazily after DB pool available

**7. Frontend** (`frontend/src/components/SpaceMetrics.tsx`)
- ApexCharts area chart for requests over time (stacked by endpoint)
- Line chart for avg + max latency
- Summary stat cards (total requests, errors, avg latency, endpoint count)
- Slow query table with duration highlighting
- Time range selector (realtime, 24h, 7d, 30d)
- Auto-refresh every 30s in realtime mode
- `ApiService.ts` delegates to `vgClient.metrics.getMetrics()` / `vgClient.metrics.getSlowQueries()`

---

## Cost/Impact Analysis

- **PostgreSQL (minute rows)**: ~10 endpoints × 1440 min/day × N spaces = ~14,400 rows/space/day (purged after 25h → ~15k rows max per space)
- **PostgreSQL (hourly rows)**: ~10 endpoints × 24 hours × 30 days = 7,200 rows/space/month
- **Slow queries**: capped at 7 days, ~100-200 per space typical
- **Latency impact**: Append to in-memory buffer (O(1)). Batch UPSERT every 5s — zero impact on request path.
- **No Redis dependency**: All metrics stored in PostgreSQL. Entity dedup also migrated to PG.

---

## Verification

- **Python**: All backend files parse cleanly (`ast.parse` — 0 errors)
- **TypeScript**: Frontend compiles cleanly (`npx tsc --noEmit` — 0 errors)
- **Tab order**: Overview → Settings → Analytics → Metrics
- **API consistency**: All endpoints use static paths with query params only (no `{space_id}` in path)
- **Client libraries**: Python client, TypeScript client, and frontend ApiService all synced to query-param routes
