# VitalGraph Import/Export — Implementation Plan

## 1. Current State Assessment

### 1.1 What Exists and Works

**CLI bulk import for `sparql_sql` backend** (`vitalgraphdb_admin_cmd.py` lines 2561–2793)
- Two-pass N-Triples loader using PostgreSQL `COPY`
- Pass 1: Parse `.nt` with `pyoxigraph`, collect unique terms + deterministic UUIDs
- Pass 2: Re-parse file, `COPY` quads in batches (default 50,000)
- Drops non-PK indexes before load, recreates after
- Calls `resync_all_auxiliary_tables()` (edge, frame_entity, stats)
- Registers graph in admin tables, verifies counts
- This is the **proven, production-quality** import path

**CLI interactive import wizard** (`vitalgraphdb_admin_cmd.py` lines 721–1204)
- Full parameter collection with interactive prompts and validation
- Delegates to `GraphImportOp` which currently only validates (does NOT insert data)

**Entity Registry JSONL import/export** (`entity_registry/` — standalone scripts)
- Two-pass processing: validate-all then batch-INSERT
- Handles entities, relationships, reference types, aliases, identifiers, categories, locations
- Export includes Weaviate vector export
- Round-trippable JSONL format

**RDF utilities** (`vitalgraph/rdf/rdf_utils.py`)
- Format detection, validation, streaming N-Triples/N-Quads parsing
- Gzipped file support

**S3/MinIO file manager** (`vitalgraph/storage/s3_file_manager.py`)
- Upload, download, stream, delete, presigned URLs, list, metadata
- Configurable for both AWS S3 and local MinIO
- `create_s3_file_manager_from_config()` factory from YAML config

**Process scheduler** (`vitalgraph/process/process_scheduler.py`)
- Periodic asyncio job runner with distributed advisory-lock gating
- Designed for ECS multi-instance environments

**Signal manager** (`vitalgraph/signal/signal_manager.py`)
- PostgreSQL NOTIFY/LISTEN for inter-process communication
- Channels for users, spaces, graphs, processes, cache invalidation, etc.

**Backfill task pattern** (`vitalgraph/tasks/backfill_server_properties_task.py`)
- In-process periodic background coroutine
- Processes small batches to remain non-blocking
- Config via environment variables

**Pydantic models** — complete for both import and export jobs
- `vitalgraph/model/import_model.py`: ImportJob, ImportStatus, ImportType, all response models
- `vitalgraph/model/export_model.py`: ExportJob, ExportStatus, ExportFormat, all response models

**Frontend UI** — tabbed Data Management page with mock data
- `frontend/src/pages/Data.tsx`: Tabbed view (Import, Export, Migrate, Tracking, Checkpoint)
- `frontend/src/pages/DataImport.tsx`, `DataExport.tsx`: Standalone list pages
- `frontend/src/pages/DataImportDetail.tsx`, `DataExportDetail.tsx`: Detail pages
- `frontend/src/mock/data.ts`: TypeScript interfaces and sample data
- All use `mockDataImports`/`mockDataExports` — no real API calls yet

### 1.2 What Exists but Doesn't Work

**REST API endpoints** — NO-OP placeholders
- `vitalgraph/endpoint/import_endpoint.py`: 9 endpoints, all return simulated data
- `vitalgraph/endpoint/export_endpoint.py`: 8 endpoints, all return simulated data

**Implementation files** — empty
- `vitalgraph/endpoint/impl/data_import_impl.py`: empty
- `vitalgraph/endpoint/impl/data_export_impl.py`: empty

**GraphImportOp** (`vitalgraph/ops/graph_import_op.py`)
- `_perform_database_import()` raises `NotImplementedError`
- References archived `PostgreSQLSpaceDBImport` (V1 code, no longer present)
- Partition and traditional import paths are dead code

**Task infrastructure** — stubs only
- `vitalgraph/task/task_inf.py`: Empty class with comments about Celery
- `vitalgraph/task/task_manager.py`: Empty class with comments about websocket notifications

### 1.3 What's Missing

- No export implementation at all (no CLI export, no REST export, no export query)
- No background task execution for import/export via REST
- No progress tracking persisted to database
- No S3 integration for import/export file staging
- No VitalSigns block file (`.vital`) handling (VitalSigns JSONL is the actual format)
- No job persistence table — import/export jobs exist only in memory
- Config template has no `file_storage` section yet

---

## 2. Architecture Decisions

### 2.1 Two Execution Modes

| Mode | Use case | Technique | Risk tolerance |
|------|----------|-----------|----------------|
| **CLI batch** | Offline bulk loads, migrations | Aggressive: drop indexes, COPY, truncate-and-rebuild aux tables | High — service not live |
| **REST/UI driven** | Production runtime, user-initiated | Conservative: batched INSERT with ON CONFLICT, incremental aux table updates | Low — service must stay responsive |

### 2.2 Import Strategy Selection

**Selected: Two-pass COPY (CLI) / Batched upsert (REST)**

The CLI `_cli_import_sparql_sql()` method is the proven import path. We adopt it as the reference implementation and create a REST-safe variant:

- **CLI mode**: Drop indexes → COPY terms → COPY quads → Recreate indexes → Resync aux tables → ANALYZE. Same as current.
- **REST mode**: Parse in streaming fashion → Batch INSERT ... ON CONFLICT for terms → Batch INSERT for quads → Incremental edge/frame_entity updates → ANALYZE affected tables. No index drops. Smaller batches (1,000–5,000). Yields control between batches.

### 2.3 Export Strategy

Export from `sparql_sql` is a SQL query against `{space_id}_rdf_quad` joined to `{space_id}_term`, streamed to file:

```sql
SELECT ts.term_text AS subject,
       tp.term_text AS predicate,
       to_.term_text AS object,
       to_.term_type AS object_type,
       to_.lang AS object_lang,
       tc.term_text AS graph
FROM {space}_rdf_quad q
JOIN {space}_term ts ON ts.term_uuid = q.subject_uuid
JOIN {space}_term tp ON tp.term_uuid = q.predicate_uuid
JOIN {space}_term to_ ON to_.term_uuid = q.object_uuid
JOIN {space}_term tc ON tc.term_uuid = q.context_uuid
WHERE tc.term_text = $1  -- optional graph filter
```

Output formats: N-Triples (streaming), N-Quads (streaming), Turtle (buffered via rdflib).

### 2.4 File Staging via S3/MinIO

```
Upload:   Client → REST upload → S3 staging bucket → import worker reads from S3
Export:   Export worker writes to S3 → Client downloads via presigned URL
```

The existing `S3FileManager` handles all S3 operations. Key paths:
- Import staging: `imports/{job_id}/{filename}`
- Export output: `exports/{job_id}/{filename}`

### 2.5 Background Task Execution

Use **asyncio tasks** managed by a lightweight in-process job manager (not Celery).

Rationale:
- The service is already async (FastAPI + asyncpg)
- Import/export are I/O-bound (DB + S3), not CPU-bound
- Celery adds operational complexity (broker, workers) for minimal benefit here
- The `ProcessScheduler` + `SignalManager` pattern already works for background work

The job manager:
1. Persists job state to a PostgreSQL `import_export_job` table
2. Runs import/export as `asyncio.Task` in the service process
3. Updates progress in the database periodically
4. Publishes progress via `SignalManager` (PostgreSQL NOTIFY)
5. Frontend polls `/status` endpoint (or later: WebSocket via signal channel)

### 2.6 Data Formats

| Format | Import | Export | Notes |
|--------|--------|--------|-------|
| N-Triples (`.nt`, `.nt.gz`) | ✅ CLI + REST | ✅ Streaming | Primary format, most efficient |
| N-Quads (`.nq`, `.nq.gz`) | ✅ CLI + REST | ✅ Streaming | Multi-graph support |
| Turtle (`.ttl`) | ✅ REST (rdflib parse) | ✅ Buffered | Human-readable |
| JSONL Quads (`.jsonl`) | Phase 5 | Phase 5 | Flat `{s,p,o,g}` quads — general-purpose bulk transfer |
| VitalSigns Block (`.vital`, `.vital.bz2`) | Phase 5 | Phase 5 | KG entities only — groups entity + frames + slots + edges per block |

---

## 3. Implementation Plan

### Phase 1: Core Import/Export Engine (Backend)

#### Task 1.1: Job persistence table ✅
- [x] Create `import_export_job` table DDL (in admin schema, not per-space)
- [x] Fields: job_id, job_type, space_id, graph_uri, status, mode, progress_pct, records_done, records_total, file_s3_key, file_name, file_size, file_format, config, checkpoint_offset, checkpoint_batch, error_message, log_entries, created_by, created_at, started_at, completed_at, updated_at
- [x] Added to `ADMIN_TABLE_DDL`, `ADMIN_INDEX_DDL`, `ADMIN_DROP_ORDER` in `sparql_sql_schema.py`
- [x] Updated `sql_scripts/init-sparql-sql.sql` reference script

#### Task 1.2: Import engine (`data_import_impl.py`) ✅
- [x] `ImportEngine` class with two strategies:
  - `import_ntriples_bulk()` — CLI-aggressive path (COPY, index drop/recreate)
  - `import_ntriples_incremental()` — REST-safe path (INSERT ON CONFLICT, no index drops, yields between batches, checkpoint resume)
- [x] Shared `_term_uuid()`, `_classify_node()`, `_parse_ntriples_terms()` helpers
- [x] `ImportProgress` dataclass + `ProgressCallback` type alias
- [x] Cancellation via `asyncio.Event`
- [x] `ImportMode` enum (BULK / INCREMENTAL)

#### Task 1.3: Export engine (`data_export_impl.py`) ✅
- [x] `ExportEngine` class:
  - `export_ntriples()` — streaming N-Triples output
  - `export_nquads()` — streaming N-Quads output (includes graph URI)
- [x] Server-side cursor via `conn.cursor()` + `cursor.fetch(batch_size)`
- [x] `ExportProgress` dataclass + `ProgressCallback` type alias
- [x] Cancellation via `asyncio.Event`
- [x] Gzip compression support, stdout support

#### Task 1.4: Background job manager ✅
- [x] `ImportExportJobManager` in `vitalgraph/jobs/import_export_manager.py`
- [x] `create_job()` — insert job row, return UUID
- [x] `start_job(job_id, file_path)` — launch background `asyncio.Task`
- [x] `get_job(job_id)` / `list_jobs(space_id?, status?, job_type?)`
- [x] `cancel_job(job_id)` — cooperative cancellation via `asyncio.Event`
- [x] `restart_job(job_id, file_path)` — resume from last checkpoint
- [x] `delete_job(job_id)` — cancel if running, delete DB row
- [x] Progress updates via `_update_progress()` → DB + `SignalManager` on `CHANNEL_PROCESS`
- [x] Configurable concurrency limit (default 2)
- [x] `shutdown()` for graceful service stop

#### Task 1.5: Checkpoint and progress tracking ✅
- [x] `checkpoint_offset` (BIGINT) and `checkpoint_batch` (INT) columns in job table
- [x] Incremental import: `f.tell()` after each batch → persisted to DB
- [x] On cancel: return current offset + batch number in result dict → stored by manager
- [x] On restart: `import_ntriples_incremental(checkpoint_offset=...)` → `f.seek(offset)`
- [x] Each batch flush → `_update_progress()` writes checkpoint to DB
- [x] `ImportProgress` / `ExportProgress` dataclasses carry records_done, records_total, bytes_done, rate, phase, elapsed

### Phase 2: REST API Endpoints ✅

#### Task 2.1: Wire import endpoints ✅
- [x] `POST /import` — Create job via `ImportExportJobManager`, return job_id
- [x] `POST /import/execute?job_id=...` — Start background import task
- [x] `GET /import/status?job_id=...` — Return current progress from DB
- [x] `GET /import/log?job_id=...` — Return log entries
- [x] `DELETE /import?job_id=...` — Cancel if running, delete job + staged file
- [x] `POST /import/upload?job_id=...` — Multipart file upload to local staging dir

#### Task 2.2: Wire export endpoints ✅
- [x] `POST /export` — Create export job with auto-generated output path
- [x] `POST /export/execute?job_id=...` — Start background export task
- [x] `GET /export/status?job_id=...` — Return current progress
- [x] `GET /export/download?job_id=...` — Stream completed export file
- [x] `DELETE /export?job_id=...` — Cancel if running, delete job + staged file

#### Task 2.3: Update Pydantic models ✅
- [x] Align `ImportJob`/`ExportJob` models with actual DB schema (`job_id`, `JobStatus`, `ImportMode`, `FileFormat`)
- [x] Add file staging fields (`file_s3_key`, `file_name`, `file_size`, `file_format`)
- [x] Add `ImportJobCreate`/`ExportJobCreate` request models
- [x] Update client interface, client endpoints, mock endpoints, and client facade methods
- [x] Wire `ImportExportJobManager` in `vitalgraphapp_impl.py` with pool + signal_manager
- [x] Add graceful shutdown for job manager in server shutdown sequence
- [x] Refactored to lazy manager init: routers registered at init, `ImportExportJobManager` created in startup event after DB pool is available
- [x] Endpoints receive `app_impl` (not `job_manager` directly); resolve manager lazily via `self.app_impl.import_export_manager` property (returns 503 if DB not connected)

### Phase 3: CLI Commands

#### Task 3.1: Standalone `vitalgraphimport` CLI ✅
- [x] Create `vitalgraph/cmd/vitalgraph_import_cmd.py` — standalone import script
- [x] Connects directly to PostgreSQL (like `vitalgraphadmin`), no REST server needed
- [x] Calls `ImportEngine` directly (same engine used by REST endpoints)
- [x] Arguments:
  - `--space-id` / `-s` (required)
  - `--graph-uri` / `-g` (optional, defaults to `urn:{space_id}`)
  - `--file` / `-f` (required, local file path)
  - `--format` (optional, auto-detect from extension: nt, nq, ttl, jsonl)
  - `--batch-size` / `-b` (default 50,000)
  - `--mode` (default `bulk` — options: `bulk` for aggressive COPY, `incremental` for INSERT ON CONFLICT)
  - `--yes` / `-y` (force truncate if tables not empty)
  - `--config` / `-c` (path to vitalgraphdb-config.yaml, defaults to env/standard locations)
  - `--dry-run` (validate only, no writes)
- [x] Progress output: phase indicators, record counts, rates, elapsed time
- [x] Exit code 0 on success, 1 on failure, 2 on cancel
- [x] Add `bin/vitalgraphimport` shell wrapper: `python -m vitalgraph.cmd.vitalgraph_import_cmd "$@"`
- [x] Add `pyproject.toml` console_scripts entry: `vitalgraphimport = "vitalgraph.cmd.vitalgraph_import_cmd:main"`

#### Task 3.2: Standalone `vitalgraphexport` CLI ✅
- [x] Create `vitalgraph/cmd/vitalgraph_export_cmd.py` — standalone export script
- [x] Connects directly to PostgreSQL, no REST server needed
- [x] Calls `ExportEngine` directly
- [x] Arguments:
  - `--space-id` / `-s` (required)
  - `--graph-uri` / `-g` (optional, export all graphs if omitted)
  - `--file` / `-f` (required, output file path; use `-` for stdout)
  - `--format` (optional, auto-detect from extension: nt, nq, ttl, jsonl)
  - `--batch-size` / `-b` (default 50,000 for cursor fetch size)
  - `--config` / `-c` (path to vitalgraphdb-config.yaml)
  - `--compress` / `-z` (gzip output, or auto if file ends in `.gz`)
- [x] Progress output: record counts, file size, elapsed time
- [x] Exit code 0 on success, 1 on failure, 2 on cancel
- [x] Add `bin/vitalgraphexport` shell wrapper: `python -m vitalgraph.cmd.vitalgraph_export_cmd "$@"`
- [x] Add `pyproject.toml` console_scripts entry: `vitalgraphexport = "vitalgraph.cmd.vitalgraph_export_cmd:main"`

#### Task 3.3: Remove import/export from vitalgraphadmin ✅
- [x] Extract core logic from `_cli_import_sparql_sql()` into `ImportEngine.import_ntriples_bulk()` before removing
- [x] Remove `import` command from `execute_cli_command()` dispatch
- [x] Remove `_cli_import_sparql_sql()` method
- [x] Remove `cmd_import()` and all its helpers: `_parse_import_args`, `_complete_import_params_interactive`, `_handle_non_interactive_params`, `_handle_interactive_params`, `_collect_space_id_interactive`, `_collect_file_path_interactive`, `_collect_file_format_interactive`, `_collect_batch_size_interactive`, `_collect_pre_validate_interactive`, `_confirm_import_interactive`, `_validate_import_params`, `_execute_import` (lines ~721–1204)
- [x] Remove `import` subparser from `parse_args()`
- [x] Do NOT add `export` to vitalgraphadmin — import and export are handled exclusively by the standalone `vitalgraphimport` and `vitalgraphexport` scripts
- [x] Update help text / README to point users to the standalone scripts

### Phase 4: VitalSigns Format Support

There are two additional serialization formats beyond N-Triples/N-Quads:

1. **JSONL Quads** — the REST API wire format. Each line is a JSON quad `{s, p, o, g}`
   representing a single RDF statement. This is a flat, low-level format suitable for
   bulk triple/quad transfer and is already supported by the N-Quads/JSON-Quads
   format adapter (`quad_format_utils.py`, `format_adapter.py`).

2. **VitalSigns Block format** (`.vital`, `.vital.bz2`) — a file format defined in
   `vital_ai_vitalsigns.block`. A `.vital` file has:
   - A **header**: first line is `jsonl 1.0.0`, followed by ontology declarations
     (`@<iri> <version>`), optional metadata (`key: value`), and a `|` delimiter line.
   - **Blocks**: groups of VitalSigns JSON objects separated by `|` lines. Each object
     is one line of JSON produced by `GraphObject.to_json()`. A block groups related
     objects together — e.g., for KG entities, a block contains the entity, its frames,
     slots, and edges as a single logical unit.
   - Supports bz2 compression (`.vital.bz2`).
   - Existing classes: `VitalBlockFile`, `VitalBlockReader`, `VitalBlockWriter`,
     `VitalBlock` (in `vital_ai_vitalsigns.block`).

#### Task 4.1: JSONL Quads import ✅
- [x] `ImportEngine.import_jsonl_quads_incremental()` — reads JSONL `{s,p,o,g}` lines
- [x] `_parse_nquads_term_for_import()` helper — parses N-Quads-encoded terms to `(text, type, lang)` tuples
- [x] Same checkpoint / cancel / progress / aux-table-sync semantics as N-Triples incremental
- [x] Wired in `ImportExportJobManager._run_import` — dispatches on `file_format == 'jsonl'`
- [x] Wired in `vitalgraphimport` CLI — auto-detects `.jsonl` extension or `--format jsonl`

#### Task 4.2: JSONL Quads export ✅
- [x] `ExportEngine.export_jsonl_quads()` — streams `{"s":..,"p":..,"o":..,"g":..}` lines
- [x] `_format_term_nquads()` helper — formats DB terms to N-Quads encoding
- [x] Cursor-based batching, gzip support, progress/cancel
- [x] Wired in `ImportExportJobManager._run_export` — dispatches on `file_format == 'jsonl'`
- [x] Wired in `vitalgraphexport` CLI — auto-detects `.jsonl` extension or `--format jsonl`

#### Task 4.3: VitalSigns Block format import (`.vital`) ✅
- [x] `ImportEngine.import_vital_block_incremental()` — reads `.vital` / `.vital.bz2` files
- [x] Uses `graphobjects_to_quad_list()` (fast property-map path, no rdflib) to convert blocks → quads
- [x] Reuses `_parse_nquads_term_for_import()` for term parsing
- [x] Same batch/checkpoint/cancel/progress/aux-table-sync semantics as other importers
- [x] Wired in `ImportExportJobManager._run_import` — dispatches on `file_format == 'vital'`
- [x] Wired in `vitalgraphimport` CLI — auto-detects `.vital` / `.vital.bz2` extension or `--format vital`

#### Task 4.4: VitalSigns Block format export (`.vital`) ✅
- [x] `ExportEngine.export_vital_block()` — exports KG entities to `.vital` files
- [x] INNER JOINs on `hasKGGraphURI` — only objects that belong to a KG entity are exported
- [x] Orders by grouping UUID so all members of a logical entity graph stream together
- [x] Groups all objects sharing the same grouping URI (entity + frames + slots + edges) into a single `VitalBlock`
- [x] Uses `quad_list_to_graphobjects()` (fast `from_property_maps` path, no rdflib) to reconstruct GraphObjects
- [x] Optional `entity_type_uri` filter — restricts export to entities whose `hasKGEntityType` matches (additional JOIN on type quad)
- [x] Optional `graph_uri` filter — restricts to a specific graph context
- [x] Wired in `ImportExportJobManager._run_export` — dispatches on `file_format == 'vital'`, passes `entity_type_uri` from job config
- [x] Wired in `vitalgraphexport` CLI — auto-detects `.vital` extension or `--format vital`, `--entity-type-uri` argument
- [x] Note: `.vital` format is exclusively for KG entity export. Other formats (nt, nq, jsonl) handle full-space and per-graph exports

### Phase 5: Frontend Integration ✅

#### Task 5.1: Connect import UI to real API ✅
- [x] Replace mock data with API calls in `DataImport.tsx` and `Data.tsx`
- [x] Implement file upload with progress bar
- [x] Poll `/import/{id}/status` for live progress updates
- [x] "Add Data Import" form: space selector, graph URI, file format, file picker
- [x] `DataImportDetail.tsx` rewritten: create → upload → execute → poll
- [x] `ImportExportService.ts` frontend service with typed methods

#### Task 5.2: Connect export UI to real API ✅
- [x] Replace mock data with API calls in `DataExport.tsx`
- [x] Poll `/export/{id}/status` for progress
- [x] Download button uses `/export/{id}/download` URL
- [x] "Add Data Export" form: space selector, graph URI, format selector
- [x] `DataExportDetail.tsx` rewritten: create → execute → poll → download

#### Task 5.3: Job log viewer ✅
- [x] `JobLogViewer` shared component with terminal-style dark UI
- [x] Auto-polls every 3s while job is active
- [x] Auto-scrolls to latest entries
- [x] Level-colored badges (error/warning/info)
- [x] Integrated into both `DataImportDetail` and `DataExportDetail`

### Phase 7: API Consistency — No Dynamic Path Parameters ✅

All import/export endpoints migrated from path parameters to query parameters, following the project-wide rule: no dynamic items in URL paths.

#### Task 7.1: Backend endpoint refactor ✅
- [x] `import_endpoint.py` — All `{job_id}` path params removed; `job_id` is a query param on all routes
- [x] `export_endpoint.py` — All `{job_id}` path params removed; `job_id` is a query param on all routes
- [x] Removed `Path` import from both endpoints; uses `Query(...)` exclusively
- [x] Endpoint classes accept `app_impl` instead of `job_manager`; resolve manager lazily

**Before** (path params):
```
GET  /import/{job_id}          POST /import/{job_id}/execute
GET  /import/{job_id}/status    GET  /import/{job_id}/log
DELETE /import/{job_id}         POST /import/{job_id}/upload
```

**After** (query params only):
```
GET  /import/job?job_id=...     POST /import/execute?job_id=...
GET  /import/status?job_id=...  GET  /import/log?job_id=...
DELETE /import?job_id=...       POST /import/upload?job_id=...
```

(Same pattern for all `/export/` routes.)

#### Task 7.2: Python client endpoint refactor ✅
- [x] `vitalgraph/client/endpoint/import_endpoint.py` — All URLs updated to use query params
- [x] `vitalgraph/client/endpoint/export_endpoint.py` — All URLs updated to use query params
- [x] Upload/download use inline `?job_id=...` query string

#### Task 7.3: Server wiring refactor ✅
- [x] `_init_data_routers()` — Registers routers unconditionally at init (receives `self` for lazy manager access)
- [x] `_init_import_export_manager()` — New method; creates `ImportExportJobManager` from pool + signal_manager during startup event
- [x] `self.import_export_manager` attribute set during startup, `None` before DB connected
- [x] Endpoints return HTTP 503 if manager not yet available

### Phase 8: TypeScript Client (`@vital-ai/vitalgraph-client`) ✅

#### Task 8.1: Import endpoint ✅
- [x] `vitalgraph-client-ts/src/endpoint/ImportEndpoint.ts` — Full CRUD + upload + execute + status + log
- [x] All routes use query params (no path params)
- [x] File upload via `FormData` with `Blob`/`ArrayBuffer` support
- [x] Typed response interfaces (`ImportJobResponse`, `ImportCreateResponse`, etc.)

#### Task 8.2: Export endpoint ✅
- [x] `vitalgraph-client-ts/src/endpoint/ExportEndpoint.ts` — Full CRUD + execute + status + download
- [x] All routes use query params
- [x] Download returns `ArrayBuffer` via `requestRaw`
- [x] Typed response interfaces (`ExportJobResponse`, `ExportCreateResponse`, etc.)

### Phase 9: Frontend Migration to TypeScript Client ✅

#### Task 9.1: ImportExportService.ts rewrite ✅
- [x] Replaced all direct `apiService.get/post/delete` calls with `vgClient.imports.*` / `vgClient.exports.*` delegation
- [x] Removed manual `fetch()` for file upload — now delegates to `vgClient.imports.upload()`
- [x] Removed `authService.getAuthHeader()` calls — TS client handles auth internally
- [x] All type interfaces retained for frontend consumption
- [x] `getExportDownloadUrl()` still generates URL string for direct browser download

### Phase 6: Configuration & Operations ✅

#### Task 6.1: Config updates ✅
- [x] `file_storage` section in config loader (minio/s3 settings) — already present
- [x] `import_export` section: `max_concurrent_jobs`, `default_batch_size`, `staging_bucket`, `job_retention_days`, `cleanup_interval_seconds`
- [x] Getter methods: `get_import_export_config()`, `get_file_storage_config()`
- [x] YAML template updated with all sections
- [x] `.env.example` updated with `LOCAL_IMPORT_EXPORT_*` vars

#### Task 6.2: Cleanup job ✅
- [x] `ImportExportCleanupJob` in `vitalgraph/process/import_export_cleanup_job.py`
- [x] Deletes completed/failed/cancelled jobs older than `job_retention_days`
- [x] Removes associated S3/minio staged files via `storage_backend.delete_object()`
- [x] Registered with `ProcessScheduler` in `vitalgraphapp_impl.py` startup

---

## 4. File Map

```
bin/
  vitalgraphimport              # NEW: shell wrapper
  vitalgraphexport              # NEW: shell wrapper
  vitalgraph                    # Existing: client REPL
  vitalgraphadmin               # Existing: admin REPL
  vitalgraphdb                  # Existing: server

vitalgraph/
  cmd/
    vitalgraph_import_cmd.py    # NEW: standalone import CLI
    vitalgraph_export_cmd.py    # NEW: standalone export CLI
  endpoint/
    import_endpoint.py          # REST routes (query params only, lazy manager)
    export_endpoint.py          # REST routes (query params only, lazy manager)
    impl/
      data_import_impl.py       # ImportEngine (populate)
      data_export_impl.py       # ExportEngine (populate)
  jobs/
    import_export_manager.py    # NEW: Background job manager
    import_export_models.py     # NEW: Internal job state dataclasses
  model/
    import_model.py             # Pydantic models (update)
    export_model.py             # Pydantic models (update)
  ops/
    graph_import_op.py          # Existing (refactor to use ImportEngine)
    graph_op.py                 # Base class (keep)
    database_op.py              # Maintenance ops (keep)
  storage/
    s3_file_manager.py          # S3/MinIO client (keep, already works)
  task/
    task_inf.py                 # Stub (eventually implement)
    task_manager.py             # Stub (eventually implement)
  admin_cmd/
    vitalgraphdb_admin_cmd.py   # Existing (remove import command + helpers)
  db/sparql_sql/
    resync_all.py               # Aux table sync (keep, used by import)
    sparql_sql_schema.py        # Table DDL (add job table)

vitalgraph-client-ts/src/
  endpoint/
    ImportEndpoint.ts           # TS client: import CRUD + upload + execute + status + log
    ExportEndpoint.ts           # TS client: export CRUD + execute + status + download

frontend/src/
  services/
    ImportExportService.ts      # API service (delegates to vgClient, typed methods)
  components/
    JobLogViewer.tsx            # Shared log viewer (auto-poll, terminal UI)
  pages/
    Data.tsx                    # Main tabbed page (delegates to sub-pages)
    DataImport.tsx              # Import list (real API, polling)
    DataExport.tsx              # Export list (real API, polling)
    DataImportDetail.tsx        # Import detail (create/upload/execute/poll/log)
    DataExportDetail.tsx        # Export detail (create/execute/poll/download/log)
```

---

## 5. Job Table DDL

```sql
CREATE TABLE IF NOT EXISTS import_export_job (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type        TEXT NOT NULL CHECK (job_type IN ('import', 'export')),
    space_id        TEXT NOT NULL REFERENCES space(space_id),
    graph_uri       TEXT,
    status          TEXT NOT NULL DEFAULT 'created'
                    CHECK (status IN ('created','pending','running','completed','failed','cancelled')),
    progress_pct    REAL NOT NULL DEFAULT 0,
    records_done    BIGINT NOT NULL DEFAULT 0,
    records_total   BIGINT,
    file_s3_key     TEXT,           -- S3 object key for staged file
    file_name       TEXT,           -- Original filename
    file_size       BIGINT,         -- File size in bytes
    file_format     TEXT,           -- nt, nq, ttl, jsonl
    config          JSONB,          -- Extra options (batch_size, etc.)
    checkpoint_offset BIGINT DEFAULT 0, -- byte offset for resume
    checkpoint_batch  INT DEFAULT 0,    -- last committed batch number
    error_message   TEXT,
    log_entries     JSONB DEFAULT '[]'::jsonb,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_iej_space_status ON import_export_job (space_id, status);
CREATE INDEX idx_iej_created ON import_export_job (created_at DESC);
```

---

## 6. Priority Order

1. **Phase 1** (Tasks 1.1–1.5): Core engine + checkpoint tracking — enables both CLI and REST paths
2. **Phase 3** (Tasks 3.1–3.3): Standalone `vitalgraphimport`/`vitalgraphexport` CLIs + remove import/export from vitalgraphadmin — immediately useful, validates engine
3. **Phase 2** (Tasks 2.1–2.3): REST endpoints — connects backend to frontend
4. **Phase 4** (Tasks 4.1–4.4): VitalSigns format support — JSONL quads + Block format, needed before frontend ships
5. **Phase 5** (Tasks 5.1–5.3): Frontend — makes it user-visible
6. **Phase 6** (Tasks 6.1–6.2): Config + cleanup — operational polish

---

## 7. Decisions (Resolved)

1. **Concurrency limits**: **2 concurrent jobs** per service instance (configurable via YAML config).

2. **Large file handling**: **Both CLI and REST**. CLI reads local files directly. REST uploads to S3 staging first, then the background worker reads from S3 — REST server never holds the full file in memory.

3. **Graph URI policy**: **Auto-create** graph record on import if it doesn't exist (current behavior). The space must already exist — that's the authorization boundary.

4. **Incremental vs. replace**: **Both via `--mode` flag**. `append` (default for REST) adds to existing graph. `replace` (default for CLI bulk) clears graph first then imports.

5. **Export scope**: **Single graph and all-graphs-in-space**. SPARQL query-based export is out of scope for this plan.

6. **VitalSigns JSONL priority**: **Before frontend**. Phase 5 moves ahead of Phase 4 in priority order. JSONL is needed for the production import/export workflow.

7. **Migration tab**: **Out of scope**. Remove from this plan. Migration is a higher-level operation that composes export + import and deserves its own plan.

8. **Progress tracking / checkpoint**: **In scope**. Import/export jobs track progress incrementally by batch offset in the S3 source file. Jobs can be halted, cancelled, and restarted from the last committed checkpoint. This is enabled by batch-based incremental consumption from S3 files. The frontend Tracking tab will display live progress for active jobs.

9. **No dynamic path parameters**: All import/export endpoints use query parameters exclusively (`?job_id=...`). URL paths are static route segments only. This matches the project-wide API consistency rule.

10. **Lazy manager initialization**: `ImportExportJobManager` is created during the startup event (after DB pool is available), not at router registration time. Endpoints resolve the manager lazily via `app_impl.import_export_manager`. Returns HTTP 503 if the database is not yet connected.

11. **Frontend delegates to TypeScript client**: `ImportExportService.ts` delegates all API calls to `@vital-ai/vitalgraph-client` via `vgClient.imports.*` / `vgClient.exports.*`. No direct `fetch()` or `apiService` calls remain.

---

## 8. Client Libraries

### Python Client (`vitalgraph/client/endpoint/`)

| File | Status | Notes |
|------|--------|-------|
| `import_endpoint.py` | ✅ Done | All routes use query params |
| `export_endpoint.py` | ✅ Done | All routes use query params |
| `vitalgraph_client.py` | ✅ Done | Delegation methods for import/export |
| `vitalgraph_client_inf.py` | ✅ Done | Abstract methods for import/export |

### TypeScript Client (`vitalgraph-client-ts/src/endpoint/`)

| File | Status | Notes |
|------|--------|-------|
| `ImportEndpoint.ts` | ✅ Done | list, get, create, delete, execute, status, log, upload |
| `ExportEndpoint.ts` | ✅ Done | list, get, create, delete, execute, status, download |

### Frontend Service (`frontend/src/services/`)

| File | Status | Notes |
|------|--------|-------|
| `ImportExportService.ts` | ✅ Done | Delegates to `vgClient`, no direct API calls |
