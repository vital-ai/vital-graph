# Background Task Review — Backfill & Scheduled Job Audit

> **Status (July 2025):** Steps 1–3 are **complete**.  The backfill task
> now uses an event-driven nudge model with 0.5 s active polling and
> 1800 s idle timeout.  All in-process and CLI import paths send nudges.
> Step 4 (one-time production backfill) remains pending.

## 1. Summary

The VitalGraph service runs several background tasks at startup. This document
reviews the **server-properties backfill task** and every other recurring job
to assess continued relevance and possible improvements.

The backfill task patches KGEntity objects that are missing server-managed
properties (creation time, modification time, status, entity type).  While
the normal REST endpoint write paths now stamp these properties inline, **raw
data imports will always exist** (JSONL loaders, SPARQL INSERT DATA, bulk
quad insertion, CLI scripts).  Stamping inline on every import path is
impractical — it requires detecting KGEntity subjects within raw quad batches
and injecting additional triples, and every new import path would need to
remember to do the same.  The backfill task is the correct centralized
mechanism for this and should be kept as permanent infrastructure.

---

## 2. The Backfill Task

### 2.1 What it does

| Item | Detail |
|------|--------|
| **File** | `vitalgraph/tasks/backfill_server_properties_task.py` |
| **Core logic** | `vitalgraph/kg_impl/kg_server_properties.py` — `backfill_entity_server_properties_sql()` |
| **Startup** | `vitalgraphapp_impl.py` line ~629 — standalone `asyncio.Task`, **not** registered with `ProcessScheduler` |
| **Interval** | ~~60 s active / 600 s idle~~ → **0.5 s active (nudge-driven), 1800 s idle timeout** |
| **Batch size** | 200 entities per iteration |
| **Properties** | `hasObjectCreationTime`, `hasObjectModificationDateTime`, `hasObjectStatusType`, `hasKGEntityType` |
| **Detection** | Finds KGEntity subjects missing **any** of the four property predicates via direct SQL against `rdf_quad` |
| **Patching** | Inserts missing quads with defaults (epoch sentinel for creation time, current time for modification, `ACTIVE` status, `KGEntityType_KGEntity`) |
| **Locking** | Advisory lock per (space, graph) — safe across multiple instances |
| **Cache** | Invalidates `_entity_graph_cache` and `_count_cache` for patched entities |

### 2.2 Where server properties ARE stamped today

| Path | File | Stamps? |
|------|------|---------|
| **Create entity (single + batch)** | `kgentities_endpoint.py` ~line 817 | ✅ Yes — `stamp_entity_server_properties(..., is_create=True)` |
| **Update entity (single + batch)** | `kgentities_endpoint.py` ~line 886, 1016 | ✅ Yes — fetches existing props, stamps with `is_create=False` |
| **Create processor fallback** | `kgentity_create_impl.py` ~line 88 | ✅ Yes — catches direct callers that bypass endpoint |

### 2.3 Where server properties are NOT stamped (gaps)

| Path | File | Issue |
|------|------|-------|
| **Import endpoint** | `vitalgraph/endpoint/import_endpoint.py` | ❌ No stamping — imports raw quads without server property injection |
| **Import/export manager** | `vitalgraph/jobs/import_export_manager.py` | ❌ No stamping on imported data |
| **Bulk load API** | `sparql_sql_space_impl.py` — `add_rdf_quads_batch_bulk()` | ❌ Raw quad insertion — no entity-level property stamping |
| **CLI / app scripts** | `apps/entity_registry/`, etc. | ❌ External loaders write raw quads |
| **SPARQL UPDATE (INSERT DATA)** | Direct SPARQL inserts | ❌ Raw triple insertion — no server property injection |

### 2.4 Recommendation — Keep as Permanent Infrastructure

Raw data imports (JSONL loaders, SPARQL INSERT DATA, bulk quad insertion,
CLI scripts in `apps/`) will always exist and will never go through the
entity endpoint's stamping logic.  Attempting to add inline stamping to
every import path is:

- **Complex** — raw quad paths would need to scan each batch for
  `rdf:type KGEntity` subjects, then generate and inject four additional
  property triples per entity
- **Fragile** — every new import path would need to remember to do this
- **Incomplete** — SPARQL INSERT DATA can never be intercepted for stamping

The backfill task is the correct centralized solution: it covers all paths,
is lightweight (~200 entities per batch, self-quiesces to 1800 s idle when
nothing to patch), and uses direct SQL with advisory locking for safety
across instances.

**Decision**: Keep `BackfillServerPropertiesTask` as permanent infrastructure.

### 2.5 Improvement Actions

#### Event-driven scheduling (primary improvement)

The current fixed-interval approach (60 s active, 600 s idle) is wasteful
during quiet periods and too slow after large imports.  Replace with an
**event-driven nudge model**:

1. **After any import/bulk-load completes**, the import path calls
   `backfill_task.nudge()` which sets an `asyncio.Event`, waking the
   backfill loop immediately.
2. The backfill task runs its normal small batches (200 entities) at a
   **higher frequency** (e.g. 0.5 s between iterations instead of 60 s),
   incrementally biting through the imported data.  No special "full run"
   mode — same batch size, just shorter sleep between batches.
3. Once a cycle finds nothing to patch, it backs off to a long idle
   interval (e.g. 1800 s or 3600 s) — essentially dormant until the next
   nudge.
4. The long idle poll is a safety net only; in practice the task wakes on
   nudge, incrementally catches up, and goes back to sleep.

**Nudge sources** (implemented — all call `nudge()` or `nudge_backfill()`):
- ✅ `ImportExportJobManager._run_job()` — after successful import job
- ✅ `sparql_insert_endpoint.py` — after successful INSERT DATA
- ✅ `sparql_update_endpoint.py` — after successful SPARQL update
- ✅ Module-level `nudge_backfill()` singleton for any in-process caller

**Out-of-process nudge** (implemented):
- ✅ `vitalgraph_import_cmd.py` — `NOTIFY vitalgraph_backfill_nudge` after
  successful import
- The backfill task listens on that channel via a dedicated `LISTEN`
  connection (same pattern as `SegmentationWorker`) and calls
  `self._nudge_event.set()` on receipt.

**Implementation sketch**:
```python
class BackfillServerPropertiesTask:
    def __init__(self, ...):
        ...
        self._nudge_event = asyncio.Event()
        self.idle_interval = 1800  # back off to 30 min when caught up

    def nudge(self) -> None:
        """Signal that new data may need backfill. Non-blocking, safe to
        call from any coroutine."""
        self._nudge_event.set()

    async def _run_loop(self) -> None:
        await asyncio.sleep(10)  # startup delay
        while self._running:
            did_work = await self._full_cycle()
            if did_work:
                # More work may remain — short delay then re-check
                await asyncio.sleep(0.5)
            else:
                # Caught up — sleep until nudged or idle timeout
                self._nudge_event.clear()
                try:
                    await asyncio.wait_for(
                        self._nudge_event.wait(),
                        timeout=self.idle_interval,
                    )
                except asyncio.TimeoutError:
                    pass  # idle poll — run a cycle just in case
```

#### Other improvements

- [ ] **Migrate to ProcessScheduler** — register as a proper job for
      monitoring (`get_status()`) and on-demand trigger (`trigger_now()`).
- [ ] **Add status to health endpoint** — expose entities patched, last
      cycle time, current state (idle/active) in `/api/process` response.
- [ ] **Add stamping to structured import endpoint** — for the import
      endpoint that handles `GraphObject` lists (not raw quads), call
      `stamp_entity_server_properties` before quad conversion.  This makes
      the common import path produce complete entities immediately,
      reducing backfill work to only the truly raw paths.
- [ ] **Run one-time full backfill** on production to clear legacy backlog.
      Use `backfill_entity_server_properties_sql()` with `max_batches=0`.

---

## 3. Full Audit of All Recurring Jobs

### 3.1 ProcessScheduler jobs (registered in `vitalgraphapp_impl.py`)

| Job | File | Interval | Still Relevant? | Notes |
|-----|------|----------|-----------------|-------|
| **db_maintenance** | `process/maintenance_job.py` | 300 s (5 min) | ✅ Yes | ANALYZE / VACUUM / vector REINDEX scoring — essential for PostgreSQL performance |
| **space_analytics** | `process/analytics_job.py` | 86400 s (daily) | ✅ Yes | Computes entity/frame/relation/property analytics — powers dashboard |
| **metrics_rollup** | `process/metrics_rollup_job.py` | 3600 s (hourly) | ✅ Yes | Aggregates minute→hour metrics, purges stale slow_query_log entries |
| **import_export_cleanup** | `process/import_export_cleanup_job.py` | 86400 s (daily) | ✅ Yes | Purges completed/failed import/export job records and staged S3 files |

### 3.2 Standalone background tasks (asyncio.Task, not via ProcessScheduler)

| Task | File | Still Relevant? | Notes |
|------|------|-----------------|-------|
| **BackfillServerPropertiesTask** | `tasks/backfill_server_properties_task.py` | ✅ Yes — permanent (covers raw import paths) | See §2 above |
| **SegmentationWorker** | `document/segmentation_worker.py` | ✅ Yes | Processes async segmentation jobs — new, actively used |
| **Space cache refresh** | `space_manager.start_periodic_refresh()` | ✅ Yes | Keeps in-memory space list current across instances |

### 3.3 Assessment summary

- **Still essential**: db_maintenance, metrics_rollup, import_export_cleanup,
  segmentation_worker, space_cache_refresh
- **Still useful**: space_analytics (could be made opt-in for small
  deployments but not harmful)
- **Keep permanently**: backfill_server_properties (covers all raw import
  paths that bypass entity endpoint stamping)
- **No missing jobs identified for current functionality** — see §4 for
  future considerations

---

## 4. Potential New Recurring Jobs

Consider whether any of the following warrant a new scheduled job:

| Candidate | Rationale | Priority |
|-----------|-----------|----------|
| **Orphan cleanup** | Detect and remove orphaned slots/edges not linked to any entity or frame. Currently manual via `apps/entity_graph_repair/`. Could be periodic. | Low — manual is fine for now |
| **Vector index staleness check** | Already covered by `MaintenanceJob._run_vector_reindex()`. No separate job needed. | N/A |
| **Document segment re-sync** | If segmentation configs change, existing documents may need re-segmentation. Currently manual. Could add a periodic scan. | Low — on-demand API exists |
| **Geo index refresh** | If geo data changes, the geo side-table may need refresh. Currently handled inline on write. | N/A |
| **Cache warmup after restart** | Pre-populate entity_graph_cache or stats cache on startup. Not a recurring job but a one-shot startup task. | Medium — would reduce cold-start latency |

None of these are urgent enough to implement now. The existing job set is
appropriate for the current maturity level.

---

## 5. Structural Observation

The backfill task runs as a standalone `asyncio.Task` rather than being
registered with `ProcessScheduler`.  This means it:

- Has no advisory-lock gating across ECS instances (it uses its own
  `pg_try_advisory_lock` per space/graph, which is fine)
- Does not appear in `ProcessScheduler.get_status()` monitoring output
- Cannot be triggered on-demand via `ProcessScheduler.trigger_now()`

The task should be migrated to `ProcessScheduler` for consistency so it
appears in monitoring and supports on-demand triggering (see §2.5).

---

## 6. Implementation Plan

### Step 1 — Event-driven nudge in BackfillServerPropertiesTask

Modify `vitalgraph/tasks/backfill_server_properties_task.py`:

- [x] Add `self._nudge_event = asyncio.Event()` to `__init__`
- [x] Add `nudge()` method that sets the event
- [x] Replace the fixed-interval `_run_loop` with the nudge/backoff loop:
  - Active: 0.5 s between batches (normal batch size)
  - Idle: `wait_for(nudge_event, timeout=1800)` — wakes on nudge or 30 min
    safety-net poll
- [x] Add a dedicated `LISTEN vitalgraph_backfill_nudge` connection (follow
  `SegmentationWorker` pattern) so out-of-process loaders can nudge via
  `NOTIFY`
- [x] On NOTIFY receipt, call `self._nudge_event.set()`

**Files**: `backfill_server_properties_task.py`

### Step 2 — Wire in-process nudge sources

After imports/bulk-loads complete, call `backfill_task.nudge()`:

- [x] `vitalgraph/endpoint/import_endpoint.py` — via `ImportExportJobManager`
- [x] `vitalgraph/jobs/import_export_manager.py` — after import job completes
- [x] `vitalgraph/endpoint/sparql_insert_endpoint.py` — after successful INSERT DATA
- [x] `vitalgraph/endpoint/sparql_update_endpoint.py` — after successful SPARQL update
- [x] Module-level `set_backfill_task()` / `nudge_backfill()` singleton in
  `backfill_server_properties_task.py` for convenient access from any endpoint

The backfill task instance is stored on `VitalGraphAppImpl._backfill_task`.
Import endpoint and import/export manager already have access to the app
instance.  For `sparql_sql_space_impl`, the simplest approach is a
module-level `_backfill_task_ref: Optional[BackfillServerPropertiesTask]`
set during startup, with a `nudge_backfill()` convenience function.

**Files**: `import_export_manager.py`, `sparql_insert_endpoint.py`,
`sparql_update_endpoint.py`, `backfill_server_properties_task.py`,
`vitalgraphapp_impl.py`

### Step 3 — Add NOTIFY to CLI loaders

Add `NOTIFY vitalgraph_backfill_nudge` after data loading in external
scripts:

- [x] `vitalgraph/cmd/vitalgraph_import_cmd.py` — NOTIFY after successful import
- [ ] `apps/entity_registry/` scripts (insert into entity registry tables,
  not RDF quads — no nudge needed currently)
- [x] Convention documented in backfill task module docstring

One line per script: `await conn.execute("NOTIFY vitalgraph_backfill_nudge")`
(or sync equivalent).

**Files**: `vitalgraph/cmd/vitalgraph_import_cmd.py`

### Step 4 — Run one-time full backfill on production

- [ ] Clear any legacy backlog using
  `backfill_entity_server_properties_sql(pool, space_id, graph_id, max_batches=0)`
- [ ] Verify all entities have the four managed properties
- [ ] After this, the nudge model handles everything going forward

### Priority

~~**Medium** — Steps 1–2 are the core improvement and should be done together.
Step 3 is low-effort follow-up.~~  Steps 1–3 are **complete**.  Step 4 is
a one-time operational task to clear any legacy backlog.
