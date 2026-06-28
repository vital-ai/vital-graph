# Process Tracking & Distributed Job Coordination Plan

## 1. Problem Statement

VitalGraph deployed as N instances on ECS needs the ability to:
1. **Track long-running processes** (data import, export, database maintenance like ANALYZE/VACUUM)
2. **Run periodic maintenance jobs** (PostgreSQL ANALYZE, VACUUM, stats rebuild)
3. **Coordinate across instances** so only one instance runs a given job at a time

Currently there is no persistent process tracking table, no periodic job scheduler, and no distributed job locking. The pieces that exist are scaffolding and partial implementations.

**Scope note:** This plan covers global process tracking and database maintenance operations. Materialized view management (edge_mv, frame_entity_mv) is a separate concern handled by `ensure_mv.py` and the MV-to-maintained-table plan.

---

## 2. Current State of the Codebase

### 2.1 Existing Process/Job Models (NO-OP Scaffolds)

**Import/Export models and endpoints exist but are NO-OP scaffolds:**

| Component | File | Status |
|-----------|------|--------|
| Import model | `vitalgraph/model/import_model.py` | Pydantic models only — `ImportJob`, `ImportStatus`, `ImportStatusResponse` |
| Export model | `vitalgraph/model/export_model.py` | Pydantic models only — `ExportJob`, `ExportStatus`, `ExportStatusResponse` |
| Import endpoint | `vitalgraph/endpoint/import_endpoint.py` | NO-OP — returns hardcoded sample data |
| Export endpoint | `vitalgraph/endpoint/export_endpoint.py` | NO-OP — returns hardcoded sample data |
| Graph import op | `vitalgraph/ops/graph_import_op.py` | Real implementation with RDF validation + bulk loading |
| Graph op base | `vitalgraph/ops/graph_op.py` | Abstract base — `OperationStatus`, `OperationResult`, `GraphOp` |

**Key observation:** `GraphOp` tracks status in-memory only (no database persistence). Import/export endpoints have no real job storage — they return fake data. The `ImportJob`/`ExportJob` Pydantic models define a job lifecycle (CREATED → PENDING → RUNNING → COMPLETED/FAILED/CANCELLED) that could be reused.

### 2.2 PostgreSQL LISTEN/NOTIFY Infrastructure (Working)

Two signal manager implementations exist and are actively used:

| Component | File | Purpose |
|-----------|------|---------|
| `SignalManager` | `vitalgraph/signal/signal_manager.py` | psycopg3-based NOTIFY/LISTEN for the PostgreSQL backend |
| `PostgreSQLSignalManager` | `vitalgraph/db/fuseki_postgresql/postgresql_signal_manager.py` | asyncpg-based NOTIFY/LISTEN for the fuseki_postgresql backend |

**Channels currently in use:**
- `vitalgraph_users`, `vitalgraph_user` — user CRUD notifications
- `vitalgraph_spaces`, `vitalgraph_space` — space CRUD notifications
- `vitalgraph_graphs`, `vitalgraph_graph` — graph CRUD notifications
- `vitalgraph_entity_dedup` — cross-worker dedup index sync

**Pattern:** Both managers use dedicated connections (not from the pool), JSON payloads, and async callback dispatch. The entity dedup system (`entity_dedup_ops.py`) already uses NOTIFY for cross-worker coordination — a proven pattern we can extend.

### 2.3 Advisory Lock Infrastructure (Working)

| Component | File | Purpose |
|-----------|------|---------|
| `EntityLockManager` | `vitalgraph/db/fuseki_postgresql/entity_lock_manager.py` | Per-entity PG advisory locks for cross-instance serialization |

**Pattern:** Uses `pg_try_advisory_lock` / `pg_advisory_unlock` on a dedicated asyncpg connection. Two-layer locking: asyncio.Lock (intra-process) + PG advisory lock (cross-instance). Timeout-based polling. This is the exact pattern needed for distributed job locking.

### 2.4 Background Tasks & Periodic Jobs (None)

**No periodic job scheduler exists.** The app currently:
- Runs startup initialization in `vitalgraphapp_impl.py` `startup_event()`
- Runs the `EventLoopMonitor` as a background asyncio task
- Has no periodic timer, no cron-like scheduler, no background task queue

### 2.5 Maintenance Operations (Partial / Manual-Only)

| Operation | Current State |
|-----------|--------------|
| PostgreSQL ANALYZE | Not implemented anywhere in the app |
| PostgreSQL VACUUM | Not implemented anywhere in the app |
| Stats tables (rdf_pred_stats, rdf_stats) | Created by schema DDL (`sparql_sql_schema.py`), loaded by generator on first query. No periodic refresh. |
| Index rebuild | Scaffolded in admin CLI (`cmd_rebuild_indexes`) — TODO stub |
| Stats rebuild | Scaffolded in admin CLI (`cmd_rebuild_stats`) — TODO stub |

---

## 3. Proposed Design

### 3.1 Process Tracking Table

A global `process` table (alongside `install`, `space`, `graph`, `user`) to track all long-running operations. Created during system initialization (same as other admin tables), **not** at app startup. Shared across all PostgreSQL-backed backends (fuseki_postgresql, sparql_sql):

```sql
CREATE TABLE IF NOT EXISTS process (
    process_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process_type     VARCHAR(64) NOT NULL,    -- 'analyze', 'vacuum', 'import', 'export', 'stats_rebuild', 'index_rebuild'
    process_subtype  VARCHAR(128),            -- e.g. space_id, table name
    status           VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    instance_id      VARCHAR(128),            -- ECS task/container ID that owns this process
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    progress_percent REAL DEFAULT 0.0,
    progress_message TEXT,
    error_message    TEXT,
    result_details   JSONB,                   -- flexible structured results
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_process_type_status ON process (process_type, status);
CREATE INDEX idx_process_created ON process (created_at DESC);
```

**Process types (initial):**

| `process_type` | `process_subtype` | Description |
|----------------|-------------------|-------------|
| `analyze` | `{space_id}` | PostgreSQL ANALYZE on one space's tables |
| `vacuum` | `{space_id}` | PostgreSQL VACUUM on one space's tables |
| `stats_rebuild` | `{space_id}` | Rebuild rdf_pred_stats / rdf_stats tables |
| `import` | `{space_id}/{graph_id}` | Data import job |
| `export` | `{space_id}/{graph_id}` | Data export job |
| `index_rebuild` | `{space_id}` | Rebuild space indexes |

### 3.2 Distributed Job Lock via PG Advisory Locks

Reuse the proven `EntityLockManager` pattern but for job-level locks:

```python
class ProcessLockManager:
    """
    Cross-instance job locking using PG advisory locks.
    
    Each (process_type, process_subtype) maps to a stable 64-bit lock key.
    Only one instance can hold the lock at a time.
    Uses pg_try_advisory_lock (non-blocking) so instances that lose the
    race simply skip the job.
    """
    
    async def try_acquire(self, process_type: str, process_subtype: str) -> bool:
        """Try to acquire lock. Returns True if acquired, False if another instance holds it."""
        ...
    
    async def release(self, process_type: str, process_subtype: str):
        """Release the lock."""
        ...
```

**Why advisory locks instead of row-level locks:**
- Advisory locks auto-release on connection drop (crash safety)
- No contention on the process table itself
- Already proven in `EntityLockManager`
- Non-blocking `pg_try_advisory_lock` allows losers to skip gracefully

### 3.3 NOTIFY Channel for Job Coordination

Add a new channel `vitalgraph_process` for broadcasting job state changes:

```python
CHANNEL_PROCESS = "vitalgraph_process"

# Payload structure:
{
    "action": "started" | "completed" | "failed",
    "process_type": "analyze",
    "process_subtype": "space_001",
    "instance_id": "ecs-task-abc123",
    "process_id": "uuid",
    "timestamp": 1234567890.123
}
```

**Use cases:**
- Instance A starts ANALYZE → broadcasts "started" → Instance B skips its own ANALYZE attempt
- Instance A completes ANALYZE → broadcasts "completed" → all instances can update their local caches
- On NOTIFY receipt, each instance updates its in-memory view of running processes

### 3.4 Periodic Scheduler

A lightweight asyncio-based periodic scheduler integrated into the app lifecycle:

```python
class ProcessScheduler:
    """
    Periodic job scheduler running as asyncio background tasks.
    
    Each registered job has:
    - interval_seconds: how often to attempt the job
    - process_type + process_subtype: identifies the job for locking
    - handler: async callable that does the actual work
    """
    
    async def start(self):
        """Start all periodic jobs as background tasks."""
        ...
    
    async def stop(self):
        """Cancel all background tasks."""
        ...
    
    def register_job(self, name, interval_seconds, process_type, process_subtype, handler):
        """Register a periodic job."""
        ...
```

**Job execution flow:**
1. Timer fires
2. Try `ProcessLockManager.try_acquire(type, subtype)` — if fails, skip this cycle
3. Insert row into `process` with status='running'
4. NOTIFY `vitalgraph_process` with "started"
5. Execute the handler
6. Update row: status='completed' (or 'failed'), set completed_at
7. NOTIFY `vitalgraph_process` with "completed"/"failed"
8. Release advisory lock

### 3.5 DatabaseOp — Operations Class for DB Maintenance

A new `DatabaseOp` subclass of `GraphOp` specifically for PostgreSQL maintenance operations (ANALYZE, VACUUM, stats rebuild). This keeps database maintenance ops separate from data operations like import/export. Applies to all PostgreSQL-backed backends (fuseki_postgresql, sparql_sql) — the target tables vary by backend but the operations are the same.

**File location:** `vitalgraph/ops/database_op.py`

**Important:** Both `ANALYZE` and `VACUUM` must be executed **outside a transaction block** (autocommit mode). With asyncpg, this means using a raw connection with `await conn.execute()` rather than a transaction context. This applies to both local PostgreSQL and AWS RDS.

```python
class DatabaseOp(GraphOp):
    """
    Base class for PostgreSQL database maintenance operations.
    
    Each op targets a specific space's tables.
    """
    
    def __init__(self, space_id: str, operation_id: Optional[str] = None):
        super().__init__(operation_id)
        self.space_id = space_id

    def _get_target_tables(self) -> list:
        """Get tables for the target space.
        
        Table names depend on backend:
        - fuseki_postgresql: {space_id}_term, {space_id}_rdf_quad
        - sparql_sql: {space_id}_term, {space_id}_rdf_quad, {space_id}_datatype,
                      {space_id}_rdf_pred_stats, {space_id}_rdf_stats
        Resolved at runtime from the active backend's schema.
        """
        ...


class AnalyzeOp(DatabaseOp):
    """Run PostgreSQL ANALYZE on one space's tables to update planner statistics."""
    
    def get_operation_name(self) -> str:
        return f"ANALYZE: {self.space_id}"
    
    async def execute(self) -> OperationResult:
        tables = self._get_target_tables()
        for table in tables:
            self.update_progress(f"Analyzing {table}...")
            await self.conn.execute(f"ANALYZE {table}")
        return OperationResult(status=OperationStatus.SUCCESS, message=f"Analyzed {len(tables)} tables")


class VacuumOp(DatabaseOp):
    """Run PostgreSQL VACUUM on one space's tables to reclaim dead tuple storage."""
    
    def get_operation_name(self) -> str:
        return f"VACUUM: {self.space_id}"
    
    async def execute(self) -> OperationResult:
        tables = self._get_target_tables()
        for table in tables:
            self.update_progress(f"Vacuuming {table}...")
            await self.conn.execute(f"VACUUM {table}")
        return OperationResult(status=OperationStatus.SUCCESS, message=f"Vacuumed {len(tables)} tables")


class StatsRebuildOp(DatabaseOp):
    """Rebuild rdf_pred_stats and rdf_stats tables for query optimizer."""
    
    def get_operation_name(self) -> str:
        return f"Stats Rebuild: {self.space_id}"
    
    async def execute(self) -> OperationResult:
        space_id = self.space_id
        self.update_progress("Rebuilding predicate stats...")
        await self.conn.execute(f"TRUNCATE {space_id}_rdf_pred_stats")
        await self.conn.execute(f"""
            INSERT INTO {space_id}_rdf_pred_stats (predicate_uuid, row_count)
            SELECT predicate_uuid, COUNT(*) FROM {space_id}_rdf_quad
            GROUP BY predicate_uuid
        """)
        self.update_progress("Rebuilding predicate-object stats...")
        # Similar for rdf_stats...
        return OperationResult(status=OperationStatus.SUCCESS, message="Stats rebuilt")
```

### 3.6 Global Maintenance Job — "Pick the Worst Space" Strategy

A **single global maintenance job** runs every **5 minutes**. Each run evaluates two independent cases:

1. **ANALYZE case:** Pick the space most in need of ANALYZE (high `n_mod_since_analyze`, stale `last_analyze`). Run `AnalyzeOp` on that space if it exceeds the freshness threshold.
2. **VACUUM case:** Pick the space most in need of VACUUM (high `n_dead_tup`, stale `last_vacuum`). Run `VacuumOp` on that space if it exceeds the freshness threshold.

The two cases are independent — a single cycle may run:
- **Zero ops** — all spaces are fresh for both ANALYZE and VACUUM
- **One op** — one space needs ANALYZE but all are fresh for VACUUM (or vice versa)
- **Two ops** — one space needs ANALYZE and one (possibly different) space needs VACUUM

Over time, all spaces get rotated through for both operations.

```python
class MaintenanceJob:
    """
    Global periodic job that evaluates ANALYZE and VACUUM needs independently.
    
    Runs every 5 minutes. Each invocation:
    1. Queries pg_stat_user_tables for all space tables
    2. Evaluates ANALYZE need (n_mod_since_analyze, last_analyze staleness)
    3. Evaluates VACUUM need (n_dead_tup, last_vacuum staleness)
    4. Runs at most one AnalyzeOp and/or one VacuumOp (possibly on different spaces)
    5. Records results in process table, then exits
    """
    
    async def pick_worst_for_analyze(self) -> Optional[str]:
        """Pick the space most in need of ANALYZE.
        
        Scoring factors:
        - n_mod_since_analyze: modifications since last ANALYZE
        - last_analyze / last_autoanalyze: time since last ANALYZE
        
        Returns None if all spaces are fresh enough.
        """
        ...
    
    async def pick_worst_for_vacuum(self) -> Optional[str]:
        """Pick the space most in need of VACUUM.
        
        Scoring factors:
        - n_dead_tup: dead tuple count
        - last_vacuum / last_autovacuum: time since last VACUUM
        
        Returns None if all spaces are fresh enough.
        """
        ...
    
    async def run(self):
        """Single maintenance cycle."""
        # ANALYZE case
        analyze_space = await self.pick_worst_for_analyze()
        if analyze_space:
            analyze_op = AnalyzeOp(analyze_space)
            await analyze_op.run()
            # record in process table...
        
        # VACUUM case (independent — may be a different space)
        vacuum_space = await self.pick_worst_for_vacuum()
        if vacuum_space:
            vacuum_op = VacuumOp(vacuum_space)
            await vacuum_op.run()
            # record in process table...
```

**Scoring query** (from `pg_stat_user_tables`):
```sql
SELECT
    relname,
    n_dead_tup,
    n_mod_since_analyze,
    last_analyze,
    last_autoanalyze,
    last_vacuum,
    last_autovacuum
FROM pg_stat_user_tables
WHERE relname LIKE '%_rdf_quad' OR relname LIKE '%_term';
```

The space_id is extracted from the table name prefix. Each space is scored separately for ANALYZE need and VACUUM need.

### 3.7 Process Record Cleanup Job

A separate periodic job deletes `process` records older than 30 days:

```python
async def cleanup_old_processes(self):
    """Delete process records older than 30 days."""
    await conn.execute(
        "DELETE FROM process WHERE created_at < now() - INTERVAL '30 days'"
    )
```

- **Interval:** Once per day (or piggyback on the 5-minute maintenance cycle with a daily check)
- **Non-blocking:** Simple DELETE, no locking concerns
- **Distributed lock:** Uses the same advisory lock mechanism so only one instance runs cleanup

### 3.8 AWS RDS Compatibility

- **ANALYZE / VACUUM (plain)** work identically on RDS — same commands, non-blocking
- **Autovacuum is always on** in RDS — our maintenance job is an additional layer with faster response to workload changes; the two don't conflict
- **No superuser needed** — ANALYZE and VACUUM only require table ownership, which the app user has
- **VACUUM FULL is not used** — avoids exclusive locks and EBS I/O storms on RDS
- **Advisory locks and LISTEN/NOTIFY** work normally on RDS
- **Tuning:** `maintenance_work_mem` should be increased via RDS Parameter Group for large tables (default 64MB)

---

## 4. Integration Points

### 4.1 App Lifecycle (`vitalgraphapp_impl.py`)

In `startup_event()`, after database connection and space manager initialization:
```python
# Initialize process tracking (process table already exists from system init)
self.process_scheduler = ProcessScheduler(db_impl, signal_manager)

# Register single global maintenance job
self.process_scheduler.register_job(
    name="db_maintenance",
    interval_seconds=300,  # 5 minutes
    process_type="maintenance",
    handler=MaintenanceJob(db_impl, space_manager)
)

await self.process_scheduler.start()
```

In `shutdown_event()`:
```python
await self.process_scheduler.stop()
```

### 4.2 On-Demand Triggers

After large data operations (import, bulk import, bulk entity creation), trigger immediate maintenance for the affected space (bypasses freshness check and "pick worst" scoring):
```python
# After import/bulk import completes:
await process_scheduler.trigger_now("analyze", space_id)
await process_scheduler.trigger_now("vacuum", space_id)
await process_scheduler.trigger_now("stats_rebuild", space_id)
```

### 4.3 Admin CLI Integration

Wire the existing `cmd_rebuild_stats` and `cmd_rebuild_indexes` stubs to the real implementations.

### 4.4 REST API Endpoint (Optional)

Expose process status via API for monitoring:
```
GET /api/processes                    — list recent processes
GET /api/processes/{process_id}       — get process details
POST /api/processes/trigger           — manually trigger a maintenance job
```

---

## 5. Configuration

Add to `vitalgraphdb-config.yaml`:
```yaml
maintenance:
  interval_seconds: 300                # 5 minutes — how often the global maintenance job runs
  process_retention_days: 30           # delete process records older than this
  enabled: true                        # master switch
  instance_id: "auto"                  # auto-detect from ECS metadata or hostname
```

---

## 6. New Files

| File | Purpose |
|------|---------|
| `vitalgraph/ops/database_op.py` | `DatabaseOp` base + `AnalyzeOp`, `VacuumOp`, `StatsRebuildOp` |
| `vitalgraph/process/process_tracker.py` | ProcessTracker class — CRUD on `process` table |
| `vitalgraph/process/process_lock_manager.py` | ProcessLockManager — advisory lock coordination |
| `vitalgraph/process/process_scheduler.py` | ProcessScheduler — periodic asyncio job runner |
| `vitalgraph/process/__init__.py` | Package init |

---

## 7. Implementation Phases

### Phase 0: Manual Migration (sparql_sql — current backend)
- Manually run `CREATE TABLE IF NOT EXISTS process (...)` on the existing sparql_sql PostgreSQL database
- This is needed because the database was already initialized before the `process` table was added to the init path
- SQL script provided in section 3.1

### Phase 1: Foundation
- Add `process` table DDL to both init paths (admin tables are defined in two places):
  1. **`_init_sparql_sql_backend()`** in `vitalgraphdb_admin_cmd.py` (sparql_sql — priority)
  2. **`FusekiPostgreSQLSchema.ADMIN_TABLES`** in `postgresql_schema.py` (fuseki_postgresql)
  3. Update `sparql_sql_db_impl.py` verification query to check for 5 admin tables (was 4)
- Create ProcessTracker CRUD class
- Create `DatabaseOp` base class + `AnalyzeOp`, `VacuumOp`, `StatsRebuildOp` in `vitalgraph/ops/database_op.py`
- Create ProcessLockManager (adapted from EntityLockManager)
- Add `vitalgraph_process` NOTIFY channel to signal managers

### Phase 2: Scheduler
- Create ProcessScheduler with asyncio background tasks
- Wire into app startup/shutdown lifecycle
- Configuration support

### Phase 3: Maintenance Jobs
- Wire `AnalyzeOp`, `VacuumOp`, `StatsRebuildOp` into ProcessScheduler
- Implement stats table rebuild logic
- Wire admin CLI stubs (`cmd_rebuild_stats`, `cmd_rebuild_indexes`) to real implementations

### Phase 4: Observability ✅ DONE
- REST API for process listing/status (`vitalgraph/endpoint/process_endpoint.py`)
  - `GET /api/processes` — list with type/status filters + pagination
  - `GET /api/processes/detail?process_id=...` — single process detail
  - `GET /api/processes/scheduler` — scheduler health/status
  - `POST /api/processes/trigger` — manually trigger analyze/vacuum/stats_rebuild
- Process record cleanup in MaintenanceJob (delete records older than 30 days)
- Wired into `_setup_all_endpoints()` in `vitalgraphapp_impl.py`

### Phase 5: Client & Testing ✅ DONE
- Created `vitalgraph/client/endpoint/process_endpoint.py`
  - `ProcessClientEndpoint` extending `BaseEndpoint`
  - Methods: `list_processes`, `get_process`, `get_scheduler_status`, `trigger`
  - Base path: `/api/processes`
- Wired into `vitalgraph/client/vitalgraph_client.py`
  - `self.processes = ProcessClientEndpoint(self)`
- Created `vitalgraph_client_test/sparql_sql/case_process_endpoint.py`
  - `ProcessEndpointTester` class (same pattern as `KGEntitiesCrudTester`)
  - 10 test cases covering:
    1. Get scheduler status
    2. List processes (initial)
    3. List with type filter
    4. List with status filter
    5. List with pagination
    6. Trigger maintenance (analyze)
    7. List after trigger (verify record)
    8. Get process by ID
    9. Trigger with space_id
    10. Get non-existent process (404)
- Created `vitalgraph_client_test/test_sparql_sql_process_endpoint.py`
  - Standalone runner (same pattern as `test_sparql_sql_kgentities.py`)
  - No space/graph needed — process tracking uses global admin tables

---

## 8. Resolved Decisions

1. **Instance ID:** Use ECS task ID from `ECS_CONTAINER_METADATA_URI_V4` endpoint (`/task` → `TaskARN` → extract task ID). Fallback to `socket.gethostname()` for local dev.
2. **Process retention:** 30 days, configurable via `process_retention_days`.
3. **ANALYZE scope:** Per-table, at the space level (N tables per space). Table names resolved from backend schema. Never whole-database ANALYZE.
4. **VACUUM strategy:** Plain VACUUM only (separate from ANALYZE, independently scored). Never use VACUUM FULL.
5. **Import/Export integration:** Unify `ImportJob`/`ExportJob` with the `process` table. Import/export-specific fields (records_processed, output_files, etc.) go in `result_details` JSONB column.
6. **On-demand triggers:** Yes, maintenance jobs are triggerable from REST API (for admin use) at the **space level** — triggers ANALYZE/VACUUM on all tables within the specified space. Also triggered automatically by the scheduler, post-import hooks, and after bulk imports.
7. **Freshness thresholds:**
   - **ANALYZE skip if:** `n_mod_since_analyze < 10,000` AND `last_analyze` or `last_autoanalyze` < 10 minutes ago
   - **VACUUM skip if:** `n_dead_tup < 10,000` AND `last_vacuum` or `last_autovacuum` < 30 minutes ago
   - After a **bulk import**, ANALYZE and stats rebuild are triggered immediately for the affected space (bypasses freshness check).

8. **`@with_db_retry()` on ProcessTracker:** Added to all 8 `ProcessTracker` methods (`create_process`, `get_process`, `list_processes`, `mark_running`, `mark_completed`, `mark_failed`, `update_progress`, `cleanup_old_processes`) for consistency with `EntityRegistryImpl` and `AgentRegistryImpl`. `MaintenanceJob` execution helpers (`_run_analyze`, `_run_vacuum`, `_run_stats_rebuild`) intentionally NOT wrapped — they use manual acquire/release for autocommit and have their own try/except with `mark_failed()` fallback; the scheduler retries on the next cycle.
9. **db_impl None at startup:** Not an issue for process tracking — `ProcessScheduler` initializes inside `startup_event()` after `connect_database()` refreshes `self.db_impl`, same location as the entity/agent registry init that was already fixed.

## 9. Open Questions

All major questions resolved.
