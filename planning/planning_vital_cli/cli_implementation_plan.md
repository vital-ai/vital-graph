# VitalGraph CLI Implementation Plan

## 1. Current State

### 1.1 Existing CLI Entry Points

| Command | Module | Entry Point | Purpose |
|---------|--------|-------------|---------|
| `vitalgraphdb` | `vitalgraph.cmd.vitalgraphdb_cmd:main` | `pyproject.toml` + `bin/vitalgraphdb` | Start the VitalGraph REST API server |
| `vitalgraphadmin` | `vitalgraph.admin_cmd.vitalgraphdb_admin_cmd:main` | `pyproject.toml` + `bin/vitalgraphadmin` | Database administration (REPL + non-interactive CLI) |
| `vitalgraph` | `vitalgraph.client.cmd.vitalgraph_repl:main` | `pyproject.toml` + `bin/vitalgraph` | Client REPL for interacting with running server |

### 1.2 `vitalgraphadmin` — Current Capabilities (3034 lines)

The admin CLI operates in two modes:
- **Interactive REPL** — prompt-toolkit powered, semicolon-terminated commands, command history
- **Non-interactive CLI** — `vitalgraphadmin -c <command> [options]`

#### Database Lifecycle
| Command | Mode | Status |
|---------|------|--------|
| `connect` | REPL | ✅ Done |
| `disconnect` | REPL | ✅ Done |
| `init` | Both | ✅ Done |
| `purge` | Both | ✅ Done |
| `delete` | Both | ✅ Done |
| `info` | Both | ✅ Done |

#### Space Management
| Command | Mode | Status |
|---------|------|--------|
| `list spaces` | Both | ✅ Done |
| `create-space` | CLI | ✅ Done (sparql_sql + fuseki_postgresql) |
| `drop-space` | CLI | ✅ Done (with --yes bypass) |
| `use <space-id>` | REPL | ✅ Done |
| `unuse` | REPL | ✅ Done |
| `clear <space-id>` | REPL | ✅ Done |

#### Listing Commands
| Command | Mode | Status |
|---------|------|--------|
| `list tables` | Both | ✅ Done |
| `list users` | Both | ✅ Done |
| `list indexes` | REPL | ✅ Done |
| `list graphs` | Both | ✅ Done |
| `list namespaces` | REPL | ✅ Done |

#### Database Maintenance
| Command | Mode | Status |
|---------|------|--------|
| `rebuild indexes [space_id]` | Both | ✅ Done |
| `rebuild stats [space_id]` | Both | ✅ Done |
| `rebuild analyze [space_id]` | Both | ✅ Done |
| `rebuild vacuum [space_id]` | Both | ✅ Done |
| `rebuild resync [space_id]` | Both | ✅ Done |
| `reindex` (alias) | Both | ✅ Done |

#### Data Import
| Command | Mode | Status |
|---------|------|--------|
| `import` | REPL | ❌ Removed — directs users to `vitalgraphimport` |

**Note**: Import has been fully extracted to the standalone `vitalgraphimport` CLI (see Phase 3a). The `import` REPL command now prints a deprecation notice pointing to `vitalgraphimport -s <space_id> -f <file.nt>`. All import helper methods (`_parse_import_args`, `_execute_import`, `_cli_import_sparql_sql`, etc.) have been removed from `vitalgraphdb_admin_cmd.py`.

#### User Management
| Command | Mode | Status |
|---------|------|--------|
| `user list` | REPL | ✅ Done |
| `user add <username> <password> [role]` | REPL | ✅ Done |
| `user delete <username>` | REPL | ✅ Done |
| `user password <username> <newpass>` | REPL | ✅ Done |
| `user role <username> <role>` | REPL | ✅ Done |
| `user deactivate <username>` | REPL | ✅ Done |
| `user activate <username>` | REPL | ✅ Done |
| `user grant <username> <space_id> <rw|r>` | REPL | ✅ Done |
| `user revoke <username> <space_id>` | REPL | ✅ Done |
| `user spaces <username>` | REPL | ✅ Done |

#### API Key Management
| Command | Mode | Status |
|---------|------|--------|
| `apikey list [username]` | REPL | ✅ Done |
| `apikey create <username> <name> [expires_days]` | REPL | ✅ Done |
| `apikey revoke <key_id>` | REPL | ✅ Done |
| `apikey info <key_id>` | REPL | ✅ Done |

#### Audit Log
| Command | Mode | Status |
|---------|------|--------|
| `audit tail [--event] [--user] [--last] [--limit]` | REPL | ✅ Done |
| `audit purge --older-than <duration>` | REPL | ✅ Done |
| `audit count` | REPL | ✅ Done |

#### Migrations
| Command | Mode | Status |
|---------|------|--------|
| `migrate auth` | REPL | ✅ Done |

#### Configuration
| Command | Mode | Status |
|---------|------|--------|
| `set log-level <level>` | REPL | ✅ Done |

### 1.3 `vitalgraphdb` — Server Command

Minimal CLI wrapper: `--host`, `--port`, `--version`. Launches the FastAPI/Uvicorn server via `vitalgraph.main.main.run_server()`.

### 1.4 `vitalgraph` — Client REPL

Basic client REPL with `open`, `close`, `status`, `help`, `exit` commands. Connects to a running VitalGraph server via the `VitalGraphClient` HTTP client. Currently very minimal — does not expose any data operations through the REPL.

### 1.5 Authentication Implementation (Complete)

Files in `vitalgraph/auth/`:
- **`vitalgraph_auth.py`** — `VitalGraphAuth` class: JWT + API key validation, bcrypt passwords, bootstrap admin, token versioning
- **`api_key.py`** — `vg_` prefixed key generation (40 chars), bcrypt hashing
- **`audit.py`** — Structured audit event emitter (Python logger + async DB insert)
- **`role_dependencies.py`** — FastAPI RBAC dependencies (`require_admin`, `require_space_read/write`)
- **`jwt_auth.py`** — JWT token creation/verification
- **`password.py`** — bcrypt hash/verify wrappers
- **`request_context.py`** — Context vars for IP/UA
- **`token_version_cache.py`** — In-memory cache to reduce DB lookups for revocation

### 1.6 Vectorization Implementation (Complete)

Files in `vitalgraph/vectorization/`:
- **`base.py`** — `VectorizationProvider` ABC: `vectorize_text()`, `vectorize_texts()`, `dimensions`, `from_config()`
- **`registry.py`** — Provider registry + factory with instance caching
- **`vitalsigns_provider.py`** — Local ONNX embeddings (384d, `vital-model-paraphrase-MiniLM-onnx`). CPU-only via ONNXRuntime, no HuggingFace downloads or network access required.
- **`openai_provider.py`** — OpenAI API embeddings (1536d/3072d)
- **`search_text_builder.py`** — Composite text construction from RDF properties via mapping rules
- **`vector_populator.py`** — Full re-index + incremental update pipeline → `{space}_vec_{index}` tables
- **`geo_populator.py`** — PostGIS geography point population from lat/long RDF triples
- **`mapping_manager.py`** — CRUD API for `vector_mapping` + `vector_mapping_property` tables

### 1.7 Import/Export Implementation (✅ Complete)

- **Server-side**: `import_endpoint.py` + `export_endpoint.py` (REST API with background job lifecycle)
- **Engine**: `data_import_impl.py` (`ImportEngine` — bulk COPY + incremental INSERT) + `data_export_impl.py` (`ExportEngine` — streaming N-Triples/N-Quads/JSONL/VitalBlock)
- **Job manager**: `vitalgraph/jobs/import_export_manager.py` (`ImportExportJobManager` — asyncio background tasks with checkpoint/cancel)
- **Standalone CLIs**: `vitalgraphimport` + `vitalgraphexport` (direct DB, no server needed)
- **Client-side**: `ImportEndpoint` + `ExportEndpoint` in `vitalgraph/client/endpoint/`
- **Formats**: N-Triples, N-Quads, JSONL Quads, VitalSigns Block (`.vital`, `.vital.bz2`)
- **Cleanup**: `ImportExportCleanupJob` registered with `ProcessScheduler`

### 1.8 Existing REST API Endpoints

The server has endpoints for: vector indexes (with direct vector upsert/get), vector mappings, import/export jobs, entity registry, agent registry, SPARQL (query/update/insert/delete), KG entities/frames/types/relations/queries/documents, objects, files, spaces, users, API keys, triples, graphs, geo config, geo points, metrics, processes, admin.

**API Consistency Policy**: All REST endpoints use static URL paths with query parameters only — no dynamic path segments (`{param}`). See `planning_client/client_api_sync_plan.md §7` for the full policy.

### 1.9 Client Libraries (Complete)

**Three client libraries** are maintained in sync with the server REST API:

| Client | Location | Status |
|--------|----------|--------|
| Python | `vitalgraph/client/endpoint/` | ✅ 25 endpoint classes, all routes synced |
| TypeScript | `vitalgraph-client-ts/src/endpoint/` | ✅ 26 endpoint classes, `tsc --noEmit` passes |
| Frontend | `frontend/src/services/ApiService.ts` | ✅ All calls delegate to TS client (`vgClient.*`) |

All three clients use query parameters exclusively (no path params). The full sync plan is tracked in `planning_client/client_api_sync_plan.md`.

### 1.10 KGDocument Segmentation (Complete)

Dedicated KGDocument CRUD + segmentation pipeline:
- **Endpoint**: `kgdocuments_endpoint.py` — CRUD + segment + segmentation-status + segmentation-configs
- **Segmentation**: Background job queue (PostgreSQL-backed), markdown + plain recursive splitters
- **Architecture**: Three-tier model (original → parent copy → segments), never modifies original
- **Vector**: Dedicated `document_segments` HNSW index, auto-created on space init
- Tracked in `planning_kgdocument/kgdocument_plan.md`

### 1.11 Multi-Vector Query (Complete)

`vg:multiVectorSimilarity` SPARQL function for weighted fusion across multiple vector indexes:
- SPARQL-to-SQL pipeline generates CTE-per-vector + weighted sum
- Three fusion strategies: `weighted_sum`, `relative_score`, `ranked`
- Auto-normalization for mixed embedding models/dimensions
- KG Query Criteria REST API integration (`multi_vector_criteria` field)
- End-to-end tested (7/7 pass)
- Tracked in `planning_multi_vector/multi_vector_query_plan.md`

---

## 2. Gaps and Improvements

### 2.1 Access Path Summary

User and API key management is already available via **three paths**:

| Path | Users | API Keys | Notes |
|------|-------|----------|-------|
| **REST API** (server endpoints) | ✅ Full CRUD (`/api/users`) | ✅ Full CRUD, self-service + admin (`/api/keys`) | Requires running server |
| **Client library** (`VitalGraphClient`) | ✅ `client.users.*` | ✅ (via REST) | Programmatic, requires server |
| **Admin REPL** (direct DB) | ✅ All subcommands | ✅ All subcommands | Interactive only |
| **Admin CLI** (non-interactive `-c`) | ❌ Not exposed | ❌ Not exposed | Gap for offline scripting |

### 2.2 Non-Interactive CLI Gaps in `vitalgraphadmin`

The following commands **exist in REPL mode only** and have no `-c` CLI equivalent:

- `user list/add/delete/password/role/deactivate/activate/grant/revoke/spaces`
- `apikey list/create/revoke/info`
- `audit tail/purge/count`
- `list indexes`, `list namespaces`
- `clear <space-id>`
- `migrate auth`
- `set log-level`
- `use/unuse`

The REST API covers user and API key management when a server is running. The CLI gap matters only for **offline/bootstrap scenarios** (initial setup before the server is running, Docker entrypoints, CI/CD database provisioning, headless migration scripts). For environments where the server is already running, `curl` or the client library can be used instead.

### 2.3 Missing CLI Capabilities

| Area | Gap | Notes |
|------|-----|-------|
| **Vector Indexes** | No CLI for creating/listing/deleting vector indexes | Tables exist, REST endpoint exists, no CLI |
| **Vector Mappings** | No CLI for managing vector mappings | REST endpoint exists, no CLI |
| **Vector Population** | No CLI to trigger re-indexing/population | `vector_populator.py` exists, no CLI |
| **Geo Population** | No CLI to populate geo side-tables | `geo_populator.py` exists, no CLI |
| **Fuzzy/Text Search** | No CLI for testing or configuring text search | tsvector columns exist, no management CLI |
| **Export** | ~~No CLI for triggering data exports~~ | ✅ `vitalgraphexport` standalone CLI implemented |
| **Graph Management** | No CLI for creating/deleting individual graphs within a space | `create-space`/`drop-space` exist, but not graph-level |
| **Config Validation** | No CLI command to validate config file | Would help in deployment scenarios |
| **Health Check** | No CLI command to check server health | Useful for deployment orchestration |

### 2.4 Client REPL Gaps

The `vitalgraph` client REPL is a skeleton — only connection management. No data query, SPARQL execution, space listing, entity browsing, or any other operations are exposed through it. The full `VitalGraphClient` class supports all of these via endpoint objects (`kgentities`, `sparql`, `spaces`, `imports`, `exports`, etc.) but none are wired to REPL commands.

---

## 3. Proposed CLI Architecture

### 3.1 Decision: Separate Focused Binaries

- **`vitalgraphadmin`** — Remains the primary admin CLI. Add non-interactive equivalents for all existing REPL commands. Database lifecycle, user/apikey management, maintenance.
- **`vitalgraphsearchutil`** (new) — Vector index/mapping management, vector population, geo population, vector similarity search, full-text search, fuzzy search. Connects to DB directly.
- **`vitalgraphimport`** (new) — Data import. Supports both direct DB path (bulk COPY) and client API path (REST import jobs).
- **`vitalgraphexport`** (new) — Data export. Supports both direct DB path and client API path (REST export jobs).
- **`vitalgraphentityregistry`** (new) — Entity registry management: entity CRUD, aliases, identifiers, categories, locations, relationships, same-as mappings, dedup operations. Connects to DB directly.
- **`vitalgraphagentregistry`** (new) — Agent registry management: agent CRUD, agent types, endpoints, functions, status management. Connects to DB directly.
- **`vitalgraph`** — Enhance the existing client REPL for interactive data exploration.

### 3.2 Entry Points (pyproject.toml)

```toml
[project.scripts]
vitalgraphdb = "vitalgraph.cmd.vitalgraphdb_cmd:main"
vitalgraphadmin = "vitalgraph.admin_cmd.vitalgraphdb_admin_cmd:main"
vitalgraphagentregistry = "vitalgraph.agent_registry_cmd.vitalgraph_agent_registry_cmd:main"
vitalgraphentityregistry = "vitalgraph.entity_registry_cmd.vitalgraph_entity_registry_cmd:main"
vitalgraphimport = "vitalgraph.cmd.vitalgraph_import_cmd:main"
vitalgraphexport = "vitalgraph.cmd.vitalgraph_export_cmd:main"
vitalgraph = "vitalgraph.client.cmd.vitalgraph_repl:main"
vitalgraphsearchutil = "vitalgraph.search_cmd.vitalgraphsearchutil_cmd:main"
```

---

## 4. Implementation Plan

### Phase 1: Complete `vitalgraphadmin` Non-Interactive CLI

**Goal**: Every REPL command also works as `vitalgraphadmin -c <command> [args]`.

**Why this matters**: The REST API covers user/apikey management when a server is running, but the non-interactive CLI is needed for **offline/bootstrap scenarios** — initial database setup before the server starts, Docker entrypoints, CI/CD provisioning, headless migration scripts.

#### 1a. New argparse choices

Add to the existing `choices=[]` list in `parse_args()`:

```python
choices=[
    # ... existing ...
    "init", "info",
    "list-spaces", "list-users", "list-graphs",
    "create-space", "drop-space",
    "import",
    "rebuild-indexes", "rebuild-stats", "rebuild-analyze", "rebuild-vacuum", "rebuild-resync",
    "purge", "delete",
    # NEW — user management
    "user-list", "user-add", "user-delete", "user-password",
    "user-role", "user-deactivate", "user-activate",
    "user-grant", "user-revoke", "user-spaces",
    # NEW — API key management
    "apikey-list", "apikey-create", "apikey-revoke",
    # NEW — migration & maintenance
    "migrate-auth", "clear-space",
    # Legacy aliases
    "reindex", "stats",
]
```

#### 1b. New argparse arguments

Add after existing `--yes` argument:

```python
# User management options
parser.add_argument("--username", "-u", type=str, help="Username for user/apikey commands")
parser.add_argument("--password", type=str, help="Password for user-add/user-password")
parser.add_argument("--role", type=str, choices=["admin", "user", "reader"], help="Role for user-add/user-role")
parser.add_argument("--level", type=str, choices=["rw", "r"], help="Access level for user-grant")

# API key options
parser.add_argument("--key-name", type=str, help="Name for apikey-create")
parser.add_argument("--key-id", type=str, help="Key ID for apikey-revoke")
parser.add_argument("--expires-days", type=int, help="Expiration in days for apikey-create")
```

#### 1c. Dispatch in `execute_cli_command()`

Each command follows the same pattern — call the existing async REPL method via `_run_async()`:

```python
elif command == 'user-list':
    success = self._run_async(self._user_list())
elif command == 'user-add':
    if not args.username or not args.password:
        print("❌ --username and --password are required for user-add")
        return False
    role = args.role or 'user'
    success = self._run_async(self._user_add(args.username, args.password, role))
# ... etc.
```

#### 1d. Task List

| Task | CLI Command | Uses Existing Method | Priority |
|------|-------------|---------------------|----------|
| 1.1 | `-c user-list` | `_user_list()` | High |
| 1.2 | `-c user-add -u X --password P [--role R]` | `_user_add()` | High |
| 1.3 | `-c user-delete -u X [--yes]` | `_user_delete()` | High |
| 1.4 | `-c user-password -u X --password P` | `_user_password()` | High |
| 1.5 | `-c user-role -u X --role R` | `_user_role()` | Medium |
| 1.6 | `-c user-deactivate -u X` | `_user_deactivate()` | Medium |
| 1.7 | `-c user-activate -u X` | `_user_activate()` | Medium |
| 1.8 | `-c user-grant -u X -s S --level rw\|r` | `_user_grant()` | Medium |
| 1.9 | `-c user-revoke -u X -s S` | `_user_revoke()` | Medium |
| 1.10 | `-c user-spaces -u X` | `_user_spaces()` | Medium |
| 1.11 | `-c apikey-list [-u X]` | `_apikey_list()` | Medium |
| 1.12 | `-c apikey-create -u X --key-name N [--expires-days D]` | `_apikey_create()` | Medium |
| 1.13 | `-c apikey-revoke --key-id K` | `_apikey_revoke()` | Medium |
| 1.14 | `-c migrate-auth` | `_migrate_auth()` | Low |
| 1.15 | `-c clear-space -s S [--yes]` | `cmd_clear()` | Low |

#### 1e. Example Usage (after implementation)

```bash
# Bootstrap: create admin user before server starts
vitalgraphadmin -c init
vitalgraphadmin -c create-space -s production
vitalgraphadmin -c user-add -u admin --password '$ecret' --role admin
vitalgraphadmin -c user-grant -u admin -s production --level rw

# CI/CD: provision service account
vitalgraphadmin -c user-add -u ci_bot --password "$(openssl rand -base64 32)" --role user
vitalgraphadmin -c apikey-create -u ci_bot --key-name "CI pipeline" --expires-days 90

# Docker entrypoint: run migration
vitalgraphadmin -c migrate-auth
```

### Phase 2: `vitalgraphsearchutil` — Vector, Geo, and Search CLI

**Goal**: Manage vector indexes, mappings, population, geo data, and all search modalities (vector similarity, full-text, fuzzy) from a dedicated CLI.

#### Module: `vitalgraph/search_cmd/vitalgraphsearchutil_cmd.py`

**Index & Mapping Management**

| Task | Command | Description |
|------|---------|-------------|
| 2.1 | `index list [-s SPACE]` | List vector indexes for a space |
| 2.2 | `index create -s SPACE --name N --dims D --provider P [--model M]` | Create a vector index |
| 2.3 | `index delete -s SPACE --name N [--yes]` | Drop a vector index |
| 2.4 | `index info -s SPACE --name N` | Show vector index details (row count, dimensions, provider) |
| 2.5 | `mapping list -s SPACE [--index N]` | List vector mappings |
| 2.6 | `mapping create -s SPACE --index N --type kgentity [--source-type default]` | Create mapping |
| 2.7 | `mapping delete -s SPACE --mapping-id M` | Delete mapping |

**Population**

| Task | Command | Description |
|------|---------|-------------|
| 2.8 | `populate -s SPACE --index N [--graph-uri G] [--batch-size B]` | Run vector population |
| 2.9 | `populate-geo -s SPACE [--graph-uri G]` | Populate geo side-table |
| 2.10 | `stats -s SPACE` | Show vector/geo population statistics |

**Search**

| Task | Command | Description |
|------|---------|-------------|
| 2.11 | `search vector -s SPACE --index N --query "text" [--limit L]` | Vector similarity search |
| 2.12 | `search text -s SPACE --query "text" [--limit L]` | Full-text tsvector search |
| 2.13 | `search fuzzy -s SPACE --query "text" [--threshold T] [--limit L]` | Fuzzy/trigram search |
| 2.14 | `search geo -s SPACE --lat LAT --lon LON --radius-km R [--limit L]` | Geo radius search |
| 2.15 | `search combined -s SPACE --query "text" [--index N] [--lat LAT --lon LON --radius-km R]` | Multi-modal search |

**Design**: Both REPL and non-interactive modes, following the same dual-mode pattern as `vitalgraphadmin`. Non-interactive via `-c <command> [args]`, REPL via launching without `-c`. Connects directly to PostgreSQL via `VitalGraphConfig` + `VitalGraphImpl`.

### Phase 3a: `vitalgraphimport` — Data Import CLI (✅ Complete)

**Goal**: Dedicated CLI for data import operations.

#### Module: `vitalgraph/cmd/vitalgraph_import_cmd.py`

| Task | Command | Description | Status |
|------|---------|-------------|--------|
| 3.1 | `vitalgraphimport -s SPACE -f FILE [--format F] [--graph-uri G] [--batch-size B] [--mode bulk|incremental] [--yes] [--dry-run]` | Direct DB import via `ImportEngine` | ✅ Done |
| 3.2 | (via REST API — `ImportExportJobManager`) | Import via REST API (server-side background job) | ✅ Done (server endpoint) |
| 3.3 | `--dry-run` flag | Validate RDF file without importing | ✅ Done |
| 3.4–3.5 | Job list/status | Via REST API (`import_endpoint.py`) | ✅ Done (server) |
| 3.6 | Format conversion | Deferred — not in scope for initial release | ⬜ Deferred |

**Implementation details:**
- Connects directly to PostgreSQL via `VitalGraphConfig` + asyncpg pool (no REST server needed)
- Calls `ImportEngine` directly (same engine used by REST background jobs)
- Supports formats: N-Triples (`.nt`), N-Quads (`.nq`), JSONL Quads (`.jsonl`), VitalSigns Block (`.vital`, `.vital.bz2`)
- Modes: `bulk` (aggressive COPY, index drop/recreate) or `incremental` (INSERT ON CONFLICT, checkpoint resume)
- Progress output: phase indicators, record counts, rates, elapsed time
- Exit codes: 0 success, 1 failure, 2 cancel
- Entry point: `pyproject.toml` → `vitalgraph.cmd.vitalgraph_import_cmd:main`
- Shell wrapper: `bin/vitalgraphimport`

### Phase 3b: `vitalgraphexport` — Data Export CLI (✅ Complete)

**Goal**: Dedicated CLI for data export operations.

#### Module: `vitalgraph/cmd/vitalgraph_export_cmd.py`

| Task | Command | Description | Status |
|------|---------|-------------|--------|
| 3.7 | `vitalgraphexport -s SPACE [--graph-uri G] -f OUTPUT [--format F] [--batch-size B] [--compress]` | Direct DB export via `ExportEngine` | ✅ Done |
| 3.8 | (via REST API — `ImportExportJobManager`) | Export via REST API (server-side background job) | ✅ Done (server endpoint) |
| 3.9–3.10 | Job list/status | Via REST API (`export_endpoint.py`) | ✅ Done (server) |

**Implementation details:**
- Connects directly to PostgreSQL via `VitalGraphConfig` + asyncpg pool
- Calls `ExportEngine` directly (streaming cursor-based export)
- Supports formats: N-Triples (`.nt`), N-Quads (`.nq`), JSONL Quads (`.jsonl`), VitalSigns Block (`.vital`)
- Supports gzip compression (`--compress` or auto-detect `.gz` extension)
- Supports stdout output (`-f -`)
- Progress output: record counts, file size, elapsed time
- Exit codes: 0 success, 1 failure, 2 cancel
- Entry point: `pyproject.toml` → `vitalgraph.cmd.vitalgraph_export_cmd:main`
- Shell wrapper: `bin/vitalgraphexport`

### Phase 3c: Remove import from `vitalgraphadmin` (✅ Complete)

The `import` command and all associated helper methods have been removed from `vitalgraphdb_admin_cmd.py`. The REPL `import` command now prints a deprecation notice directing users to `vitalgraphimport`. The `GraphImportOp` import was removed.

### Phase 4: `vitalgraphentityregistry` — Review & Update Entity Registry CLI

**Goal**: Migrate and improve the existing `entity_registry/entity_admin.py` into the proper `vitalgraphentityregistry` binary, add REPL mode, and fill gaps.

#### Current State (review)

A substantial CLI already exists at `entity_registry/entity_admin.py` (1186 lines, `EntityAdmin` class). It is a standalone script (not a proper package entry point) invoked as `python entity_registry/entity_admin.py <command>`. It uses subparsers and already has:

**Existing commands (already implemented):**
- `stats` — full summary (entities, types, categories, aliases, identifiers, same-as, changelog)
- `stats types` / `stats aliases` / `stats categories` / `stats identifiers` / `stats changelog`
- `search sql --name N [--type-key T] [--category-key C] [--country ...] [--format table|json|csv]`
- `search similar --name N|--entity-id E [--min-score S] [--format table|json]` (MinHash LSH dedup)
- `search topic --query Q [--hybrid] [--type-key T] [--latitude/--longitude/--radius-km]` (Weaviate semantic)
- `dedup status` / `dedup sync [--entity-id E] [--dry-run]` / `dedup check`
- `weaviate status` / `weaviate collections` / `weaviate rebuild` / `weaviate sync` / `weaviate check`
- `export [--format json|csv] [-o FILE] [--type-key T] [--include-aliases] [--include-identifiers]`
- `types list` / `types add --key K --label L`
- `delete by-prefix --prefix P [--dry-run]`
- `migrate [--dry-run]`

**What needs to change:**

#### 4a. Migration to Proper Package Entry Point

| Task | Description |
|------|-------------|
| 4.1 | Move `entity_registry/entity_admin.py` → `vitalgraph/entity_registry_cmd/vitalgraphentityregistry_cmd.py` |
| 4.2 | Remove `sys.path` hacks and `dotenv` manual loading; use `VitalGraphConfig` pattern |
| 4.3 | Add `bin/vitalgraphentityregistry` shell script and `pyproject.toml` entry point |
| 4.4 | Add REPL mode (launch without subcommand → interactive prompt with command history) |
| 4.5 | Add non-interactive `-c <command> [args]` mode matching `vitalgraphadmin` pattern |

#### 4b. Missing CRUD Commands (not in current entity_admin.py)

| Task | Command | Description |
|------|---------|-------------|
| 4.6 | `entity list [--type T] [--limit L] [--offset O]` | Paginated entity listing (currently only via search) |
| 4.7 | `entity get --entity-id E` | Get single entity details with all related data |
| 4.8 | `entity create --name N --type T [--description D]` | Create entity (uses `EntityRegistryImpl`) |
| 4.9 | `entity update --entity-id E [--name N] [--description D]` | Update entity |
| 4.10 | `alias list --entity-id E` | List aliases for entity |
| 4.11 | `alias add --entity-id E --alias A [--type T]` | Add alias |
| 4.12 | `alias delete --alias-id A` | Remove alias |
| 4.13 | `identifier list --entity-id E` | List external identifiers |
| 4.14 | `identifier add --entity-id E --namespace N --value V` | Add identifier |
| 4.15 | `identifier delete --identifier-id I` | Remove identifier |
| 4.16 | `category list` | List all categories |
| 4.17 | `category assign --entity-id E --category-id C` | Assign category |
| 4.18 | `category remove --entity-id E --category-id C` | Remove category assignment |
| 4.19 | `location list --entity-id E` | List entity locations |
| 4.20 | `location add --entity-id E --lat LAT --lon LON [--name N]` | Add location |
| 4.21 | `location delete --location-id L` | Remove location |
| 4.22 | `relationship list --entity-id E` | List relationships |
| 4.23 | `relationship create --from F --to T --type R` | Create relationship |
| 4.24 | `relationship delete --relationship-id R` | Remove relationship |
| 4.25 | `sameas list --entity-id E` | List same-as mappings |
| 4.26 | `sameas assert --entity-id E --target-id T` | Assert same-as |
| 4.27 | `sameas retract --entity-id E --target-id T` | Retract same-as |

#### 4c. Improvements to Existing Commands

| Task | Description |
|------|-------------|
| 4.28 | Use `EntityRegistryImpl` methods instead of raw SQL where possible |
| 4.29 | Add `--format json|table|csv` consistently to all list/search commands |
| 4.30 | Add `--verbose` flag consistently across all commands |
| 4.31 | Consolidate the standalone `entity_registry/*.py` scripts (import, export, generate_vectors, migrate, weaviate_admin, etc.) into subcommands |

**Design**: Both REPL and non-interactive modes. Connects directly to PostgreSQL via the shared asyncpg pool (same as `EntityRegistryImpl`). Also available in `bin/vitalgraphentityregistry`.

### Phase 5: `vitalgraphagentregistry` — Implement Agent Registry CLI

**Goal**: Build the agent registry CLI from scratch. Unlike the entity registry (which has an existing 1186-line admin script), the agent registry currently only has a standalone migration script (`agent_registry/migrate_agents.py`, 328 lines) and no admin CLI.

#### Current State (review)

- `agent_registry/migrate_agents.py` — standalone schema migration (creates `agent_type`, `agent`, `agent_endpoint`, `agent_function`, `agent_change_log` tables + seed data). Not a proper entry point.
- `vitalgraph/agent_registry/agent_registry_impl.py` — full async CRUD implementation (868 lines): agent types, agents, endpoints, functions, change logging, soft-delete, status transitions. All methods already exist.
- `vitalgraph/agent_registry/agent_endpoint.py` — REST API endpoint (505 lines): full CRUD routes already working.
- `vitalgraph/client/endpoint/agent_registry_endpoint.py` — client library endpoint (259 lines): client-side methods for all REST operations.

**The CLI is the missing piece** — all the backend logic (`AgentRegistryImpl`) and REST API exist, but there's no way to manage agents from the command line.

#### Module: `vitalgraph/agent_registry_cmd/vitalgraphagentregistry_cmd.py`

**Agent Types**

| Task | Command | Description |
|------|---------|-------------|
| 5.1 | `type list` | List agent types |
| 5.2 | `type create --key K --label L [--description D]` | Create agent type |

**Agent CRUD**

| Task | Command | Description |
|------|---------|-------------|
| 5.3 | `agent list [--type T] [--status S] [--limit L]` | List agents |
| 5.4 | `agent create --name N --type-key T --uri U [--description D]` | Create agent |
| 5.5 | `agent get --agent-id A` | Get agent details (with endpoints and functions) |
| 5.6 | `agent update --agent-id A [--name N] [--description D]` | Update agent |
| 5.7 | `agent delete --agent-id A [--yes]` | Delete (soft-delete) agent |
| 5.8 | `agent status --agent-id A --status S` | Change agent status (active/inactive/deprecated) |

**Endpoints & Functions**

| Task | Command | Description |
|------|---------|-------------|
| 5.9 | `endpoint list --agent-id A` | List agent endpoints |
| 5.10 | `endpoint create --agent-id A --url U --protocol P [--uri U]` | Add endpoint |
| 5.11 | `endpoint update --endpoint-id E [--url U] [--status S]` | Update endpoint |
| 5.12 | `endpoint delete --endpoint-id E` | Remove endpoint |
| 5.13 | `function list --agent-id A` | List agent functions |
| 5.14 | `function create --agent-id A --name N --function-uri U [--description D]` | Add function |
| 5.15 | `function update --function-id F [--name N] [--status S]` | Update function |
| 5.16 | `function delete --function-id F` | Remove function |

**Stats & Schema**

| Task | Command | Description |
|------|---------|-------------|
| 5.17 | `stats` | Summary: agent counts by type/status, endpoint/function counts |
| 5.18 | `changelog [--agent-id A] [--limit L] [--days D]` | Show agent change history |
| 5.19 | `migrate [--dry-run] [--status]` | Run schema migrations (absorb `agent_registry/migrate_agents.py`) |
| 5.20 | `schema info` | Show table counts and schema status |

**Design**: Both REPL and non-interactive modes. Fresh implementation following the `vitalgraphadmin` dual-mode pattern. All commands delegate to `AgentRegistryImpl` methods (already fully implemented). Also available in `bin/vitalgraphagentregistry`.

### Phase 6: Review and Improve `vitalgraph` Client CLI

**Goal**: Transform the `vitalgraph` client from a minimal connection-test skeleton into a full-featured data exploration CLI.

#### Current State (review)

The REPL at `vitalgraph/client/cmd/vitalgraph_repl.py` (299 lines) has only 5 commands:
- `open` — connect to server (JWT auth)
- `close` — disconnect
- `status` — show connection/auth info
- `help` / `exit`

Meanwhile, `VitalGraphClient` already initializes **17 endpoint objects** that are fully functional but completely unwired:
- `client.spaces`, `client.graphs` — space/graph listing
- `client.kgentities`, `client.kgframes`, `client.kgtypes`, `client.kgrelations` — KG data CRUD
- `client.kgqueries` — KG query execution
- `client.objects` — generic object operations
- `client.sparql` — SPARQL query execution
- `client.files` — file upload/download
- `client.users`, `client.admin` — user/admin operations
- `client.imports`, `client.exports` — import/export jobs
- `client.triples` — triple-level operations
- `client.entity_registry`, `client.agent_registry` — registry operations
- `client.processes` — long-running process tracking

#### Improvements

1. **Add non-interactive mode** (`vitalgraph -c <command> [args]`) matching all other CLIs
2. **Add API key auth** to REPL (`open --api-key vg_...`) — client already supports `api_key=` parameter
3. **Add space context** (`use <space-id>` / `unuse`) for commands that need a space
4. **Wire all useful endpoints** to REPL + CLI commands

#### 6a. Connection & Auth

| Task | Command | Description |
|------|---------|-------------|
| 6.1 | `open [--api-key K]` | Connect (JWT or API key) |
| 6.2 | `close` | Disconnect |
| 6.3 | `status` | Connection + auth status (existing, improve) |
| 6.4 | `whoami` | Show current identity (username, role, token expiry) |
| 6.5 | `use <space-id>` | Set current space context |
| 6.6 | `unuse` | Clear space context |

#### 6b. Space & Graph Exploration

| Task | Command | Description |
|------|---------|-------------|
| 6.7 | `list spaces` | List all spaces (`client.spaces`) |
| 6.8 | `list graphs [--space S]` | List graphs in a space (`client.graphs`) |
| 6.9 | `space info [--space S]` | Space details (quad count, backend type, etc.) |

#### 6c. KG Data Exploration

| Task | Command | Description |
|------|---------|-------------|
| 6.10 | `list entities [--type T] [--search Q] [--limit L]` | List KG entities (`client.kgentities`) |
| 6.11 | `get entity --uri U` | Get entity details |
| 6.12 | `list frames [--entity-uri E] [--limit L]` | List KG frames (`client.kgframes`) |
| 6.13 | `get frame --uri U` | Get frame details |
| 6.14 | `list types [--limit L]` | List KG types (`client.kgtypes`) |
| 6.15 | `list relations [--entity-uri E] [--limit L]` | List relations (`client.kgrelations`) |

#### 6d. Query

| Task | Command | Description |
|------|---------|-------------|
| 6.16 | `sparql <query>` | Execute SPARQL SELECT/ASK (`client.sparql`) |
| 6.17 | `query <MetaQL expression>` | Execute KG query (`client.kgqueries`) |

#### 6e. Import/Export Jobs (via API)

| Task | Command | Description |
|------|---------|-------------|
| 6.18 | `import list [--space S]` | List import jobs (`client.imports`) |
| 6.19 | `import status --job-id J` | Get import job status |
| 6.20 | `export list [--space S]` | List export jobs (`client.exports`) |
| 6.21 | `export status --job-id J` | Get export job status |

#### 6f. Files

| Task | Command | Description |
|------|---------|-------------|
| 6.22 | `file list [--space S] [--graph G]` | List files (`client.files`) |
| 6.23 | `file upload -f FILE [--space S]` | Upload file |
| 6.24 | `file download --file-id F -o OUTPUT` | Download file |

#### 6g. Admin (when authenticated as admin)

| Task | Command | Description |
|------|---------|-------------|
| 6.25 | `user list` | List users (`client.users`) |
| 6.26 | `process list` | List running processes (`client.processes`) |
| 6.27 | `server info` | Server version and config (`client.admin`) |

#### 6h. Output & UX

| Task | Description |
|------|-------------|
| 6.28 | Add `--format json\|table\|csv` output option for all list commands |
| 6.29 | Add tab-completion for commands and space/graph IDs |
| 6.30 | Add `--limit` / `--offset` pagination defaults |
| 6.31 | Multi-line SPARQL input support (detect incomplete query, prompt for continuation) |

---

## 5. Implementation Status Tracking

| Phase | Task | Status | Notes |
|-------|------|--------|-------|
| **Phase 1** | | | |
| 1.1 | CLI: user-list | ✅ Done | |
| 1.2 | CLI: user-add | ✅ Done | |
| 1.3 | CLI: user-delete | ✅ Done | with --yes bypass |
| 1.4 | CLI: user-password | ✅ Done | |
| 1.5 | CLI: user-role | ✅ Done | |
| 1.6 | CLI: user-deactivate | ✅ Done | |
| 1.7 | CLI: user-activate | ✅ Done | |
| 1.8 | CLI: user-grant | ✅ Done | |
| 1.9 | CLI: user-revoke | ✅ Done | |
| 1.10 | CLI: user-spaces | ✅ Done | |
| 1.11 | CLI: apikey-list | ✅ Done | optional --username filter |
| 1.12 | CLI: apikey-create | ✅ Done | optional --expires-days |
| 1.13 | CLI: apikey-revoke | ✅ Done | |
| 1.14 | CLI: migrate-auth | ✅ Done | |
| 1.15 | CLI: clear-space | ✅ Done | with --yes bypass |
| **Phase 2** | | | |
| 2.1 | vitalgraphsearchutil: index list | ✅ Done | Direct SQL on {space}_vector_index |
| 2.2 | vitalgraphsearchutil: index create | ✅ Done | Registry insert + SparqlSQLSchema vec table |
| 2.3 | vitalgraphsearchutil: index delete | ✅ Done | DROP vec table + registry row |
| 2.4 | vitalgraphsearchutil: index info | ✅ Done | Shows dims, provider, row count |
| 2.5 | vitalgraphsearchutil: mapping list | ✅ Done | Via MappingManager |
| 2.6 | vitalgraphsearchutil: mapping create | ✅ Done | Via MappingManager |
| 2.7 | vitalgraphsearchutil: mapping delete | ✅ Done | Via MappingManager |
| 2.8 | vitalgraphsearchutil: populate | ✅ Done | Calls populate_index() |
| 2.9 | vitalgraphsearchutil: populate-geo | ✅ Done | Calls populate_geo() |
| 2.10 | vitalgraphsearchutil: stats | ✅ Done | Vector counts + geo stats |
| 2.11 | vitalgraphsearchutil: search vector | ✅ Done | pgvector cosine via provider |
| 2.12 | vitalgraphsearchutil: search text | ✅ Done | tsvector ts_rank on vec table |
| 2.13 | vitalgraphsearchutil: search fuzzy | ✅ Done | pg_trgm similarity on term table |
| 2.14 | vitalgraphsearchutil: search geo | ✅ Done | PostGIS ST_DWithin radius |
| 2.15 | vitalgraphsearchutil: search combined | ✅ Done | Vector + geo filter combo |
| **Phase 3a** | | | |
| 3.1 | vitalgraphimport: direct DB import | ✅ Done | vitalgraph/cmd/vitalgraph_import_cmd.py — bulk + incremental modes |
| 3.2 | vitalgraphimport: REST API path | ✅ Done | Server-side via ImportExportJobManager |
| 3.3 | vitalgraphimport: validate (--dry-run) | ✅ Done | |
| 3.4–3.5 | vitalgraphimport: job list/status | ✅ Done | Via REST import_endpoint.py |
| 3.6 | vitalgraphimport: convert | ❌ Removed | Out of scope |
| **Phase 3b** | | | |
| 3.7 | vitalgraphexport: direct DB export | ✅ Done | vitalgraph/cmd/vitalgraph_export_cmd.py — streaming + gzip |
| 3.8 | vitalgraphexport: REST API path | ✅ Done | Server-side via ImportExportJobManager |
| 3.9–3.10 | vitalgraphexport: job list/status | ✅ Done | Via REST export_endpoint.py |
| **Phase 3c** | | | |
| 3.11 | Remove import from vitalgraphadmin | ✅ Done | Deprecation notice + all helpers removed |
| **Phase 4** | | | |
| 4.1–4.5 | vitalgraphentityregistry: migrate to package entry point + REPL | ✅ Done | New CLI in vitalgraph/entity_registry_cmd/ with dual-mode |
| 4.6–4.9 | vitalgraphentityregistry: entity CRUD | ✅ Done | list/get/create/update/delete entities |
| 4.10–4.15 | vitalgraphentityregistry: aliases + identifiers | ✅ Done | list/add/retract aliases; list/add/lookup identifiers |
| 4.16–4.21 | vitalgraphentityregistry: categories + locations + vector/geo | ✅ Done | list/assign/remove categories; vector-status/check/rebuild/sync; geo-status/populate/check; search-topic |
| 4.22–4.27 | vitalgraphentityregistry: relationships + same-as | ✅ Done | list-relationship-types/list/create relationships; resolve |
| 4.28–4.31 | vitalgraphentityregistry: refactor + consolidation | ✅ Done | Uses EntityRegistryImpl, consistent format, search/export/stats/migrate |
| **Phase 5** | | | |
| 5.1–5.2 | vitalgraphagentregistry: agent types | ✅ Done | list-types, create-type |
| 5.3–5.8 | vitalgraphagentregistry: agent CRUD + status | ✅ Done | list/get/create/update/delete/set-status |
| 5.9–5.16 | vitalgraphagentregistry: endpoints + functions | ✅ Done | CRUD + discover-by-function |
| 5.17–5.20 | vitalgraphagentregistry: stats, changelog, migrate, schema | ✅ Done | stats, changelog, migrate --dry-run, schema-status |
| **Phase 6** | | | |
| 6.1–6.6 | vitalgraph: connection, auth, space context | ✅ Done | open --api-key, whoami, use/unuse, format |
| 6.7–6.9 | vitalgraph: space & graph exploration | ✅ Done | list spaces, list graphs, space info |
| 6.10–6.15 | vitalgraph: KG data exploration | ✅ Done | entities, frames, types, relations |
| 6.16–6.17 | vitalgraph: SPARQL query | ✅ Done | SPARQL SELECT + multiline; MetaQL removed from scope |
| 6.18–6.21 | vitalgraph: import/export job monitoring | ✅ Done | import list/status, export list/status/download |
| 6.22–6.24 | vitalgraph: file operations | ✅ Done | file list/upload/download |
| 6.25–6.27 | vitalgraph: admin commands | ✅ Done | user list, process list, server info |
| 6.28–6.31 | vitalgraph: output formats & UX | ✅ Done | json/table/csv + WordCompleter tab-complete + sparql multiline |

### Summary

**All 6 phases are complete.** Every planned CLI binary is implemented, has a `pyproject.toml` entry point, a `bin/` shell script, and supports both REPL and non-interactive modes:

| Binary | Module | Tasks | Status |
|--------|--------|-------|--------|
| `vitalgraphadmin` | `admin_cmd/vitalgraphdb_admin_cmd.py` | 1.1–1.15 | ✅ All 15 done |
| `vitalgraphsearchutil` | `search_cmd/vitalgraphsearchutil_cmd.py` | 2.1–2.15 | ✅ All 15 done |
| `vitalgraphimport` | `cmd/vitalgraph_import_cmd.py` | 3.1–3.5 | ✅ All done (3.6 removed) |
| `vitalgraphexport` | `cmd/vitalgraph_export_cmd.py` | 3.7–3.10 | ✅ All 4 done |
| `vitalgraphentityregistry` | `entity_registry_cmd/vitalgraph_entity_registry_cmd.py` | 4.1–4.31 | ✅ All 31 done |
| `vitalgraphagentregistry` | `agent_registry_cmd/vitalgraph_agent_registry_cmd.py` | 5.1–5.20 | ✅ All 20 done |
| `vitalgraph` | `client/cmd/vitalgraph_repl.py` | 6.1–6.31 | ✅ All 31 done |

---

## 6. Technical Notes

### 6.1 Shared Infrastructure

All new CLI apps should reuse:
- `VitalGraphConfig` for DB connection configuration
- `VitalGraphImpl` + `get_db_impl()` for database access
- `_run_async()` pattern for running async code from sync CLI context
- `prompt-toolkit` for REPL mode with history
- `tabulate` for table formatting
- `argparse` for non-interactive CLI argument parsing

### 6.2 Database Connection Pattern

```python
# Standard connection pattern used by vitalgraphadmin
config = VitalGraphConfig()
vital_graph_impl = VitalGraphImpl(config=config)
backend_type = config.get_backend_config().get('type', 'postgresql')

if backend_type == 'sparql_sql':
    space_backend = vital_graph_impl.space_backend
    await space_backend.connect()
    db_impl = space_backend.db_impl
else:
    db_impl = vital_graph_impl.get_db_impl()
    await db_impl.connect()
```

### 6.3 Vector/Geo Tables (per-space)

From `vector_geo_plan.md` and existing code:
- `{space}_vector_index` — index registry (dimensions, provider, model)
- `{space}_vec_{index_name}` — per-index vector data (subject_uuid, embedding, search_text)
- `{space}_vector_mapping` — mapping rules (source_type, separator, etc.)
- `{space}_vector_mapping_property` — child property URIs per mapping
- `{space}_geo` — PostGIS geography points (subject_uuid, location, lat, lon)

### 6.4 File Layout for New CLIs

```
vitalgraph/
  cmd/
    __init__.py
    vitalgraphdb_cmd.py                        # server launch (existing)
    vitalgraph_import_cmd.py                   # ✅ standalone import CLI
    vitalgraph_export_cmd.py                   # ✅ standalone export CLI
  admin_cmd/
    __init__.py
    vitalgraphdb_admin_cmd.py                  # ✅ admin REPL (import removed)
  search_cmd/
    __init__.py
    vitalgraphsearchutil_cmd.py                # ✅ vector/geo/text/fuzzy search management
  entity_registry_cmd/
    __init__.py
    vitalgraph_entity_registry_cmd.py          # ✅ entity registry management
  agent_registry_cmd/
    __init__.py
    vitalgraph_agent_registry_cmd.py           # ✅ agent registry management
```

### 6.5 Shell Scripts in `bin/`

All CLIs get corresponding shell scripts in `bin/` (matching existing pattern):

```
bin/
  vitalgraph                   # ✅ existing — client REPL
  vitalgraphadmin              # ✅ existing — admin REPL
  vitalgraphdb                 # ✅ existing — server
  vitalgraphagentregistry      # ✅ done
  vitalgraphentityregistry     # ✅ done
  vitalgraphimport             # ✅ done
  vitalgraphexport             # ✅ done
  vitalgraphsearchutil         # ✅ done
```

Each follows the same pattern:
```bash
#!/bin/bash
python -m vitalgraph.<module>.<cmd_file> "$@"
```

---

## 7. Open Questions

1. ~~Should `vitalgraphvec` and `vitalgraphdata` also support REPL mode?~~ **Decision: Yes, both REPL and non-interactive modes** for all new CLIs, consistent with `vitalgraphadmin`.

2. ~~Should export support all RDF formats?~~ **Decision: Yes** — N-Triples, N-Quads, JSONL Quads, VitalSigns Block (`.vital`). Turtle deferred.

3. ~~Should the client REPL (`vitalgraph`) support API key auth?~~ **Decision: Yes** — `open --api-key vg_...` implemented in Phase 6.

4. ~~Naming~~ **Decision: Separate focused binaries** — `vitalgraphsearchutil` (vector/geo/text/fuzzy search), `vitalgraphimport` (import), `vitalgraphexport` (export). Each has its own REPL + non-interactive mode.

5. ~~Should we add a `vitalgraphadmin -c user-*` family?~~ **Decision: Yes** — Phase 1 completed, all user/apikey commands available as `-c` CLI.

6. ~~Should `vitalgraphsearchutil` also manage fuzzy search configuration?~~ **Decision: Query-time only.** Trigram indexes are created automatically during space init. Similarity thresholds are passed as `--threshold` at search time. No persistent config needed.

7. ~~Should `vitalgraphsearchutil` be split?~~ **Decision: Keep both.** `vitalgraphentityregistry` has entity-registry-specific vector/geo commands (vector-status/rebuild/sync, geo-populate/check tied to entity registry tables). `vitalgraphsearchutil` operates on the general-purpose vector/geo/text infrastructure (any space, any index) and supports combined multi-modal search. They coexist without overlap.
