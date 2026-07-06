# VitalGraph Background Task & Signal Catalog

Comprehensive reference of all background tasks, scheduled jobs, signal
listeners, and startup-time subsystems initialized by
`VitalGraphAppImpl.startup_event()`.

---

## 1. ProcessScheduler Jobs

These jobs are registered with `ProcessScheduler` and benefit from:
- Distributed advisory locking (one instance runs at a time)
- Centralized monitoring via `get_status()`
- On-demand triggering via `trigger_now()`

| # | Job Name | Class | File | Interval | Process Type | Purpose |
|---|----------|-------|------|----------|-------------|---------|
| 1 | `db_maintenance` | `MaintenanceJob` | `vitalgraph/process/maintenance_job.py` | 300 s (5 min) | `maintenance` | Scores all spaces for ANALYZE / VACUUM need, runs at most one of each per cycle. Also handles vector index REINDEX (HNSW bloat detection) and process record cleanup (daily). |
| 2 | `space_analytics` | `AnalyticsJob` | `vitalgraph/process/analytics_job.py` | 86400 s (daily) | `analytics` | Computes entity, frame, relation, and property analytics per space via SQL. Stores results as JSONB in `space_analytics` table. Supports on-demand per-space and per-graph triggers. |
| 3 | `metrics_rollup` | `MetricsRollupJob` | `vitalgraph/process/metrics_rollup_job.py` | 3600 s (hourly) | `metrics` | Aggregates minute-granularity `query_metrics` rows into hourly summaries. Purges minute rows after rollup. Purges `slow_query_log` entries older than 7 days. |
| 4 | `import_export_cleanup` | `ImportExportCleanupJob` | `vitalgraph/process/import_export_cleanup_job.py` | 86400 s (daily) | `maintenance` | Deletes completed/failed/cancelled `import_export_job` rows older than retention period (default 30 days). Removes corresponding staged files from S3. |

**Startup**: `vitalgraphapp_impl.py` lines ~358–444.  
**Shutdown**: `process_scheduler.stop()` at line ~704.

---

## 2. Standalone Background Tasks

These run as independent `asyncio.Task` instances, outside `ProcessScheduler`.

### 2.1 BackfillServerPropertiesTask

| Item | Detail |
|------|--------|
| **Class** | `BackfillServerPropertiesTask` |
| **File** | `vitalgraph/tasks/backfill_server_properties_task.py` |
| **Core logic** | `vitalgraph/kg_impl/kg_server_properties.py` |
| **Startup** | `vitalgraphapp_impl.py` line ~659 — `self._backfill_task.start()` |
| **Shutdown** | `await self._backfill_task.stop()` at line ~722 |
| **Interval** | 60 s active, 600 s idle (no work remaining) |
| **Batch size** | 200 entities |
| **Locking** | Own `pg_try_advisory_lock` per (space, graph) |

**Purpose**: Finds KGEntity subjects missing any of four server-managed
properties (`hasObjectCreationTime`, `hasObjectModificationDateTime`,
`hasObjectStatusType`, `hasKGEntityType`) and inserts default values via
direct SQL. Covers data loaded through raw import paths that bypass the
entity endpoint's inline stamping.

**Planned improvement**: Event-driven nudge model — see
`background_task_review_plan.md` §2.5.

### 2.2 SegmentationWorker

| Item | Detail |
|------|--------|
| **Class** | `SegmentationWorker` |
| **File** | `vitalgraph/document/segmentation_worker.py` |
| **Startup** | `vitalgraphapp_impl.py` line ~649 — `asyncio.create_task(worker.run())` |
| **Shutdown** | `worker.stop()` + `await task` at line ~712 |
| **Concurrency** | Up to 4 concurrent segmentation tasks (`_MAX_CONCURRENT`) |
| **Wake mechanism** | `LISTEN` / `NOTIFY` on PostgreSQL + 30 s safety-net poll |

**Purpose**: Polls the `segmentation_jobs` table for pending jobs, claims
them via `SELECT ... FOR UPDATE SKIP LOCKED`, and runs the document
segmentation pipeline. Event-driven — wakes instantly on NOTIFY.

### 2.3 Space Cache Periodic Refresh

| Item | Detail |
|------|--------|
| **Method** | `SpaceManager.start_periodic_refresh()` |
| **Startup** | `vitalgraphapp_impl.py` line ~455 |
| **Shutdown** | `space_manager.stop_periodic_refresh()` at line ~698 |
| **Interval** | Configurable (`space_cache.refresh_interval_seconds`, default 60 s) |

**Purpose**: Periodically re-reads the space list from the database to keep
the in-memory `SpaceManager` cache current across instances.

### 2.4 PostgresMetricsCollector

| Item | Detail |
|------|--------|
| **Class** | `PostgresMetricsCollector` |
| **File** | `vitalgraph/metrics/postgres_metrics_collector.py` |
| **Startup** | `vitalgraphapp_impl.py` line ~406 — `await metrics_collector.start()` |
| **Flush interval** | 5 s (buffered writes) |
| **Buffer size** | 50 records |

**Purpose**: Buffers per-request metrics from `MetricsMiddleware` and
flushes them to the `query_metrics` PostgreSQL table periodically. Not a
"job" in the ProcessScheduler sense — it's a flush loop for the metrics
pipeline.

### 2.5 EventLoopMonitor

| Item | Detail |
|------|--------|
| **Class** | `EventLoopMonitor` |
| **Startup** | `vitalgraphapp_impl.py` line ~685 — `await event_loop_monitor.start()` |
| **Shutdown** | `await event_loop_monitor.stop()` at line ~731 |
| **Check interval** | 50 ms |
| **Threshold** | 100 ms stall |

**Purpose**: Detects event loop stalls by scheduling a callback and
measuring actual vs expected delay. Logs warnings when the loop is blocked
beyond the threshold.

---

## 3. NOTIFY / LISTEN Signal Channels

The `SignalManager` (`vitalgraph/signal/signal_manager.py`) maintains a
dedicated `LISTEN` connection and dispatches notifications to registered
callbacks.

| Channel | Constant | Registered Callbacks | Purpose |
|---------|----------|---------------------|---------|
| `vitalgraph_users` | `CHANNEL_USERS` | NotificationBridge, default logging | User collection changes → WebSocket |
| `vitalgraph_user` | `CHANNEL_USER` | NotificationBridge, default logging | Individual user changes → WebSocket |
| `vitalgraph_spaces` | `CHANNEL_SPACES` | NotificationBridge, default logging | Space collection changes → WebSocket |
| `vitalgraph_space` | `CHANNEL_SPACE` | NotificationBridge, SpaceManager sync, entity cache invalidation, default logging | Individual space changes → WebSocket + cache |
| `vitalgraph_graphs` | `CHANNEL_GRAPHS` | NotificationBridge, default logging | Graph collection changes → WebSocket |
| `vitalgraph_graph` | `CHANNEL_GRAPH` | NotificationBridge, entity cache invalidation, default logging | Individual graph changes → WebSocket + cache |
| `vitalgraph_entity_fuzzy` | `CHANNEL_ENTITY_FUZZY` | EntityRegistryImpl fuzzy sync | Cross-worker fuzzy index synchronization |
| `vitalgraph_process` | `CHANNEL_PROCESS` | (default logging) | Process status changes |
| `vitalgraph_cache_invalidate` | `CHANNEL_CACHE_INVALIDATE` | Datatype + stats cache invalidation | Cross-instance SQL generator cache sync |
| `vitalgraph_entity_graph` | `CHANNEL_ENTITY_GRAPH` | Entity graph + count cache invalidation | Cross-instance entity cache sync |
| `vitalgraph_token_version` | `CHANNEL_TOKEN_VERSION` | Auth token cache invalidation | Cross-instance token revocation |

**Startup**: Signal callbacks registered at lines ~493–608. Listener started
at line ~616 via `signal_manager.start_listening()`.  
**Shutdown**: `signal_manager.stop_listening()` at line ~747.

---

## 4. Startup-Only Subsystem Initialization

These run once during startup (not recurring) but are important to catalog:

| Subsystem | Purpose | Startup Line |
|-----------|---------|-------------|
| **SpaceManager.initialize_from_database()** | Load all spaces into memory | ~285 |
| **Fuseki auto-register** | Ensure Fuseki datasets exist for all spaces | ~296 |
| **EntityRegistryImpl** | Entity registry + fuzzy index + Weaviate index | ~304–336 |
| **AgentRegistryImpl** | Agent registry initialization | ~344–356 |
| **NotificationBridge** | PostgreSQL NOTIFY → WebSocket bridge | ~464–491 |
| **Audit logging** | Configure DB-backed audit log | ~623–636 |
| **ImportExportJobManager** | Import/export job lifecycle management | ~638–642 |
| **gc.freeze()** | Freeze gen-2 objects to reduce GC pauses | ~678–681 |

---

## 5. Shutdown Sequence

Ordered as implemented in `shutdown_event()`:

1. Space cache periodic refresh → `stop_periodic_refresh()`
2. ProcessScheduler → `stop()` (stops all 4 registered jobs)
3. SegmentationWorker → `stop()` + await task
4. BackfillServerPropertiesTask → `stop()`
5. EventLoopMonitor → `stop()`
6. ImportExportJobManager → `shutdown()`
7. SignalManager → `stop_listening()`
8. Database connections → `disconnect()`
9. Resource cleanup → `cleanup_resources()`

---

## 6. Configuration Summary

| Setting | Source | Default | Affects |
|---------|--------|---------|---------|
| `maintenance.interval_seconds` | config YAML | 300 | db_maintenance job |
| `maintenance.enabled` | config YAML | true | ProcessScheduler enabled flag |
| `analytics.interval_seconds` | config YAML | 86400 | space_analytics job |
| `import_export.job_retention_days` | config YAML | 30 | import_export_cleanup job |
| `import_export.cleanup_interval_seconds` | config YAML | 86400 | import_export_cleanup job |
| `space_cache.refresh_interval_seconds` | config YAML | 60 | Space cache refresh |
| `BACKFILL_ENABLED` | env var | true | Backfill task on/off |
| `BACKFILL_INTERVAL_SECONDS` | env var | 60 | Backfill active interval |
| `BACKFILL_BATCH_SIZE` | env var | 200 | Backfill entities per batch |
| `BACKFILL_IDLE_INTERVAL_SECONDS` | env var | 600 | Backfill idle interval |
