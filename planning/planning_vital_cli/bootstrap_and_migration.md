# VitalGraph Bootstrap & Migration Guide

This document describes the current processes for initializing a fresh VitalGraph deployment, migrating existing databases, and the environment variables / dependencies involved. It concludes with proposed cleanup and improvements.

---

## 1. Overview

VitalGraph requires three layers of initialization before it can serve requests:

| Layer | What | Who Creates It |
|-------|------|----------------|
| **PostgreSQL extensions & functions** | `pg_trgm`, `pgcrypto`, `vector`, `postgis`, `vitalgraph_term_uuid()` | `vitalgraphadmin -c init` or `init-sparql-sql.sql` |
| **Admin tables** | `install`, `space`, `graph`, `user`, `user_space_access`, `process`, `agent_type`, `agent`, `agent_endpoint`, `agent_change_log`, `space_analytics`, `query_metrics`, `slow_query_log`, `import_export_job` (14 tables) | Same as above |
| **Per-space tables** | `{space}_term`, `{space}_rdf_quad`, `{space}_datatype`, `{space}_rdf_pred_stats`, `{space}_rdf_stats`, `{space}_edge`, `{space}_frame_entity`, `{space}_vector_index`, `{space}_vector_mapping`, `{space}_vector_mapping_property`, `{space}_geo_config`, `{space}_geo` (12 tables per space) | `vitalgraphadmin -c create-space` or REST API |

The service **never** creates admin tables at runtime. It only creates per-space tables when a space is created via API.

---

## 2. Current Bootstrap Process

### 2.1 Prerequisites

1. **PostgreSQL 15+** running with superuser access (for `CREATE EXTENSION`).
2. **Database created** — e.g. `sparql_sql_graph` for the `sparql_sql` backend.
3. **Jena sidecar** running (for `sparql_sql` backend only) — default `http://localhost:7070`.
4. **MinIO / S3** running (for file storage) — default `http://localhost:9000`.
5. **Python environment** with `vitalgraph[server]` installed.

### 2.2 Step-by-Step: Fresh Deployment (sparql_sql backend)

#### Step 1: Generate a JWT secret

```bash
python scripts/generate_jwt_secret.py --env-format
# Output: JWT_SECRET_KEY=<base64-encoded-secret>
```

Add the generated key to `.env`.

#### Step 2: Configure environment

Copy `.env.example` to `.env` and set at minimum:

```env
VITALGRAPH_ENVIRONMENT=local          # or prod, dev, staging
LOCAL_BACKEND_TYPE=sparql_sql
LOCAL_DB_HOST=localhost
LOCAL_DB_PORT=5432
LOCAL_DB_NAME=sparql_sql_graph
LOCAL_DB_USERNAME=postgres
LOCAL_DB_PASSWORD=
LOCAL_AUTH_ROOT_USERNAME=admin
LOCAL_AUTH_ROOT_PASSWORD=<strong-password>
LOCAL_SIDECAR_URL=http://localhost:7070
JWT_SECRET_KEY=<from-step-1>
```

#### Step 3: Initialize admin tables

```bash
# Non-interactive:
vitalgraphadmin -c init

# Interactive REPL:
vitalgraphadmin
> connect;
> init;
```

This executes `SparqlSQLAdmin.init_tables()` which:
1. Creates extensions: `pg_trgm`, `pgcrypto`, `vector`, `postgis`
2. Creates the `vitalgraph_term_uuid()` SQL function
3. Checks if admin tables already exist (idempotent)
4. Creates all 14 admin tables via `SparqlSQLSchema.ADMIN_TABLE_DDL`
5. Creates all admin indexes via `SparqlSQLSchema.ADMIN_INDEX_DDL`
6. Seeds initial data: install record + default agent type

**Source files:**
- `vitalgraph/admin_cmd/vitalgraphdb_admin_cmd.py` → `cmd_init()` (line 286)
- `vitalgraph/db/sparql_sql/sparql_sql_admin.py` → `init_tables()` (line 79)
- `vitalgraph/db/sparql_sql/sparql_sql_schema.py` → DDL definitions

#### Step 4: Create the first user

```bash
vitalgraphadmin -c user-add --username admin --password <password> --role admin
```

This calls `_user_add()` which:
1. Hashes the password with bcrypt via `vitalgraph.auth.password.hash_password()`
2. Inserts into the `user` table with `password_hash` and `role`
3. Emits an audit event

#### Step 5: Create a space

```bash
vitalgraphadmin -c create-space -s my_space --space-name "My Space"
```

This calls `_cli_create_space()` which:
1. Inserts a row into the `space` admin table
2. Creates all 12 per-space tables via `SparqlSQLSchema.create_space()`
3. Creates per-space indexes (term, quad, edge, frame_entity, geo)
4. Seeds standard XSD datatypes into `{space}_datatype` (35 entries)

#### Step 6: Start the service

```bash
python -m vitalgraph.cmd.vitalgraphdb_cmd
# or via Docker:
docker compose up
```

At startup, `VitalGraphAppImpl` reads `AUTH_ROOT_USERNAME` / `AUTH_ROOT_PASSWORD` and configures a **bootstrap admin** — an in-memory fallback user that works even if the `user` table is empty. On the first login, the bootstrap admin is used; it should be persisted to the DB.

### 2.3 Alternative: Docker `init-sparql-sql.sql`

The file `sql_scripts/init-sparql-sql.sql` can be mounted into `docker-entrypoint-initdb.d/` for automatic initialization on first PostgreSQL container start. However, this script is **stale** — it only creates 4 admin tables (`install`, `space`, `graph`, `user`) and is missing:
- `user_space_access`
- `process`
- `agent_type`, `agent`, `agent_endpoint`, `agent_change_log`
- `space_analytics`, `query_metrics`, `slow_query_log`
- `import_export_job` (present)
- Extensions: `pgcrypto`, `vector`, `postgis` (missing)
- The `vitalgraph_term_uuid()` function (missing)
- Modern `user` table columns: `password_hash`, `full_name`, `role`, `is_active`, `token_version`, `created_time`, `last_login` (missing)

### 2.4 Alternative: `scripts/init_vitalgraph_fuseki_admin.py`

A legacy script for the `fuseki_postgresql` backend. Creates:
1. Fuseki admin dataset
2. PostgreSQL admin schema (via `FusekiPostgreSQLDbImpl.initialize_schema()`)
3. Optional test space

Not applicable to the `sparql_sql` backend.

---

## 3. Environment Variables & Dependencies

### 3.1 Bootstrap-Critical Environment Variables

| Variable | Default | Used By | Purpose |
|----------|---------|---------|---------|
| `VITALGRAPH_ENVIRONMENT` | `local` | Config loader | Selects profile prefix (`LOCAL_*`, `PROD_*`, etc.) |
| `{PROFILE}_BACKEND_TYPE` | `fuseki_postgresql` | Config loader | Backend selection: `sparql_sql` or `fuseki_postgresql` |
| `{PROFILE}_DB_HOST` | `localhost` | Config loader | PostgreSQL host |
| `{PROFILE}_DB_PORT` | `5432` | Config loader | PostgreSQL port |
| `{PROFILE}_DB_NAME` | `sparql_sql_graph` | Config loader | Database name |
| `{PROFILE}_DB_USERNAME` | `postgres` | Config loader | Database user |
| `{PROFILE}_DB_PASSWORD` | (empty) | Config loader | Database password |
| `{PROFILE}_AUTH_ROOT_USERNAME` | (empty) | App startup | Bootstrap admin username |
| `{PROFILE}_AUTH_ROOT_PASSWORD` | (empty) | App startup | Bootstrap admin password |
| `JWT_SECRET_KEY` | **required** | App startup | JWT signing secret (no profile prefix) |
| `{PROFILE}_SIDECAR_URL` | `http://localhost:7070` | sparql_sql backend | Jena SPARQL compiler sidecar |
| `{PROFILE}_TABLE_PREFIX` | `vg_` | Config loader | Table prefix (currently unused by sparql_sql) |

### 3.2 Runtime Dependencies

| Dependency | Required For | Notes |
|------------|-------------|-------|
| PostgreSQL 15+ | All backends | Must support `CREATE EXTENSION` |
| `pg_trgm` extension | REGEX/CONTAINS text filters | Bundled with PostgreSQL |
| `pgcrypto` extension | `gen_random_uuid()`, `vitalgraph_term_uuid()` | Bundled with PostgreSQL |
| `vector` extension (pgvector) | Vector similarity search | Must be installed separately |
| `postgis` extension | Geo/spatial queries | Must be installed separately |
| Jena sidecar | `sparql_sql` backend | SPARQL→AST compilation |
| MinIO / S3 | File storage, import/export | Optional for bootstrap |
| bcrypt (Python) | Password hashing | `pip install bcrypt` |
| asyncpg (Python) | Migration scripts | `pip install asyncpg` |

### 3.3 Auth Bootstrap Flow

```
┌──────────────────────────────────────────────────┐
│ VitalGraphAppImpl.__init__()                     │
│                                                  │
│  1. Read AUTH_ROOT_USERNAME / AUTH_ROOT_PASSWORD  │
│  2. If both set → auth.set_bootstrap_admin()     │
│     (in-memory bcrypt-hashed admin user)         │
│                                                  │
│  On login attempt:                               │
│  3. Check DB for user → found → verify password  │
│  4. Not found → check bootstrap admin            │
│  5. Bootstrap admin match → allow login          │
│  6. Legacy plaintext password → auto-migrate     │
│     to bcrypt hash                               │
└──────────────────────────────────────────────────┘
```

---

## 4. Migration Scripts for Existing Databases

### 4.1 Auth Schema Migration

**File:** `vitalgraph/db/migrations/migrate_auth_schema.py`

Migrates pre-auth databases to the modern auth system:
1. Adds columns to `user` table: `password_hash`, `full_name`, `role`, `is_active`, `token_version`, `created_time`, `last_login`
2. Creates `user_space_access` table
3. Hashes existing plaintext passwords to bcrypt
4. Promotes the first user to `admin` role if no admin exists
5. Creates `api_key` table
6. Creates `audit_log` table

```bash
python -m vitalgraph.db.migrations.migrate_auth_schema \
  --host localhost --port 5432 --database sparql_sql_graph --user postgres
```

### 4.2 Import/Export Schema Migration

**File:** `vitalgraph/db/migrations/migrate_import_export_schema.py`

Creates the `import_export_job` table for databases that predate the import/export feature.

```bash
python -m vitalgraph.db.migrations.migrate_import_export_schema \
  --host localhost --port 5432 --database sparql_sql_graph --user postgres
```

### 4.3 Metrics Schema Migration

**File:** `vitalgraph/db/migrations/migrate_metrics_schema.py`

Migrates or creates:
1. `query_metrics` table (adds `bucket_granularity` column, expands PK)
2. `space_analytics` table
3. `slow_query_log` table

```bash
python -m vitalgraph.db.migrations.migrate_metrics_schema \
  --host localhost --port 5432 --database sparql_sql_graph --user postgres
```

### 4.4 Vector/Geo Schema Migration

**File:** `vitalgraph/db/migrations/migrate_vector_geo_schema.py`

Adds vector/geo per-space tables to existing spaces:
1. Ensures `vector` and `postgis` extensions
2. Iterates all spaces, creates missing tables: `{space}_vector_index`, `{space}_vector_mapping`, `{space}_vector_mapping_property`, `{space}_geo_config`, `{space}_geo`
3. Supports `--dry-run` mode

```bash
python -m vitalgraph.db.migrations.migrate_vector_geo_schema \
  --host localhost --port 5432 --database sparql_sql_graph --user postgres
# or dry-run first:
python -m vitalgraph.db.migrations.migrate_vector_geo_schema \
  --host localhost --port 5432 --database sparql_sql_graph --user postgres --dry-run
```

### 4.5 Other Maintenance Scripts

| Script | Purpose |
|--------|---------|
| `scripts/generate_jwt_secret.py` | Generate secure JWT secret key |
| `scripts/init_vitalgraph_fuseki_admin.py` | Legacy: Initialize fuseki_postgresql backend |
| `scripts/backfill_entity_server_properties.py` | Backfill server properties on entities |
| `scripts/migrate_dedup_redis_to_pg.py` | Migrate entity dedup index from Redis to PostgreSQL |
| `scripts/sync_dedup_index.py` | Sync entity dedup index |

---

## 5. Schema Drift Analysis

### 5.1 `init-sparql-sql.sql` vs `SparqlSQLSchema`

The SQL init script is **significantly out of date** compared to the authoritative `SparqlSQLSchema` class:

| Item | `init-sparql-sql.sql` | `SparqlSQLSchema` |
|------|----------------------|-------------------|
| Admin tables | 4 (`install`, `space`, `graph`, `user`) | 14 (all above + 10 more) |
| `user` table columns | 5 (basic) | 13 (with auth, role, token_version) |
| Extensions | `pg_trgm` only | `pg_trgm`, `pgcrypto`, `vector`, `postgis` |
| `vitalgraph_term_uuid()` | ❌ Missing | ✅ Present |
| `user_space_access` | ❌ Missing | ✅ Present |
| `process` | ❌ Missing | ✅ Present |
| Agent registry (4 tables) | ❌ Missing | ✅ Present |
| Metrics (3 tables) | ❌ Missing | ✅ Present |
| `import_export_job` | ✅ Present | ✅ Present |
| Admin indexes | 7 | 27 |
| Seed data | Install record only | Install record + default agent type |

### 5.2 Migration Scripts vs `SparqlSQLSchema`

The migration scripts are **additive and idempotent**, but there is no versioning or ordering system. Each migration independently checks for existing tables/columns.

| Migration | Tables Created | Overlaps with Fresh Init? |
|-----------|---------------|---------------------------|
| `migrate_auth_schema` | `user_space_access`, `api_key`, `audit_log` | `user_space_access` yes; `api_key`/`audit_log` **not in SparqlSQLSchema** |
| `migrate_import_export_schema` | `import_export_job` | Yes — already in ADMIN_TABLE_DDL |
| `migrate_metrics_schema` | `query_metrics`, `space_analytics`, `slow_query_log` | Yes — all in ADMIN_TABLE_DDL |
| `migrate_vector_geo_schema` | Per-space vector/geo tables | Yes — all in `create_space_tables_sql()` |

**Key finding:** `api_key` and `audit_log` tables are created by `migrate_auth_schema` but are **not** present in `SparqlSQLSchema.ADMIN_TABLE_DDL`. This means a fresh `init` does not create them — they only appear after running the auth migration.

---

## 6. Proposed Cleanup & Improvements

### 6.1 Critical: Single Source of Truth for Schema

**Problem:** Three independent DDL sources (`init-sparql-sql.sql`, `SparqlSQLSchema`, migration scripts) with drift.

**Proposal:**
1. **Delete `sql_scripts/init-sparql-sql.sql`** or regenerate it from `SparqlSQLSchema` at build time. It misleads anyone trying to use it for Docker init.
2. **Add `api_key` and `audit_log` to `SparqlSQLSchema.ADMIN_TABLE_DDL`** so fresh `init` is complete without needing to run migrations after.
3. Add a `schema_version` column to the `install` table to track which migrations have been applied.

### 6.2 Unified Migration Runner

**Problem:** Migrations must be run individually with raw connection params. No ordering, no idempotent "run all pending" command.

**Proposal:**
1. Add a `vitalgraphadmin -c migrate` CLI command that:
   - Reads the current schema version from `install`
   - Runs all pending migrations in order
   - Updates the schema version
2. Register migrations in order:
   - v1: base schema (install, space, graph, user)
   - v2: auth modernization (user_space_access, api_key, audit_log, user column additions)
   - v3: metrics (query_metrics, space_analytics, slow_query_log)
   - v4: import/export (import_export_job)
   - v5: agent registry (agent_type, agent, agent_endpoint, agent_change_log)
   - v6: vector/geo per-space tables
3. Each migration checks its own preconditions (idempotent), but the runner ensures ordering.

### 6.3 Bootstrap Admin Persistence

**Problem:** The bootstrap admin is in-memory only. If a user logs in via bootstrap admin, nothing is written to the DB. The next restart with `AUTH_ROOT_USERNAME` unset means no admin access.

**Proposal:**
1. On first login via bootstrap admin, **auto-create** the user in the `user` table with `role=admin` and the bcrypt-hashed password.
2. Log a clear message: "Bootstrap admin persisted to database."
3. Consider making `vitalgraphadmin -c init` automatically create the root user from `AUTH_ROOT_USERNAME`/`AUTH_ROOT_PASSWORD` when they are set, removing the need for a separate `user-add` step.

### 6.4 Combine `init` + `user-add` + `create-space` into a Single Bootstrap Command

**Problem:** Fresh deployments require three separate CLI commands.

**Proposal:** Add `vitalgraphadmin -c bootstrap` that:
1. Runs `init` (create admin tables)
2. Creates root user from `AUTH_ROOT_USERNAME`/`AUTH_ROOT_PASSWORD` (if set and user doesn't exist)
3. Optionally creates an initial space (e.g. from `--space-id` / `INITIAL_SPACE_ID` env var)

Example:
```bash
vitalgraphadmin -c bootstrap -s my_space --space-name "My Space"
```

### 6.5 Docker Init Script Regeneration

**Problem:** `init-sparql-sql.sql` is stale and dangerous for Docker deployments.

**Proposal:**
1. Add a build-time script that generates `init-sparql-sql.sql` from `SparqlSQLSchema`:
   ```python
   # scripts/generate_init_sql.py
   from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
   schema = SparqlSQLSchema()
   # Output extensions, function DDL, admin tables, indexes, seed data
   ```
2. Include the generation in CI/CD so the SQL file is always in sync.
3. Or: remove the SQL file entirely and use `vitalgraphadmin -c init` in a Docker entrypoint script.

### 6.6 Environment Variable Cleanup

**Problem:** Overlapping config paths and confusing defaults.

| Issue | Fix |
|-------|-----|
| `AUTH_ROOT_USERNAME`/`AUTH_ROOT_PASSWORD` default to empty in config loader but `_get_default_config()` returns `admin`/`admin` | Remove the defaults from `_get_default_config()` or align them |
| `TABLE_PREFIX` has two defaults: `vg_` (tables section) and `vitalgraph_` (fuseki_postgresql section) | Document which applies to which backend |
| `JWT_SECRET_KEY` has no profile prefix support | Either add `{PROFILE}_JWT_SECRET_KEY` support or document this is intentionally global |
| `DB_NAME` defaults differ: `vitalgraph` (top-level), `sparql_sql_graph` (sparql_sql section) | The sparql_sql section overrides — document this clearly |

### 6.7 Migration Script Improvements

**Problem:** Migration scripts use `asyncpg` directly with raw connection params, while the admin CLI uses the VitalGraph config system.

**Proposal:**
1. Add `--from-env` flag to migration scripts that reads connection info from `VITALGRAPH_ENVIRONMENT`-prefixed env vars (matching the admin CLI).
2. Or: integrate migrations into `vitalgraphadmin -c migrate` so they use the same config system.

### 6.8 Per-Space Migration for Existing Spaces

**Problem:** When new per-space tables are added (e.g. vector/geo), existing spaces don't get them until `migrate_vector_geo_schema` is run manually.

**Proposal:**
1. On space access (first SPARQL query or API call), check if per-space tables are up to date and run missing DDL automatically.
2. Or: add a `vitalgraphadmin -c upgrade-spaces` command that iterates all spaces and ensures they have all current per-space tables.
3. Track per-space schema version in the `space` admin table (add `schema_version INTEGER DEFAULT 1` column).

---

## 7. Complete Bootstrap Sequence (Proposed)

After implementing the above improvements, a fresh deployment would look like:

```bash
# 1. Generate secrets
python scripts/generate_jwt_secret.py --env-format >> .env

# 2. Configure .env (DB_HOST, DB_NAME, AUTH_ROOT_*, etc.)

# 3. Single bootstrap command
vitalgraphadmin -c bootstrap -s my_space --space-name "My Space"
#   → Creates extensions & functions
#   → Creates all admin tables (including api_key, audit_log)
#   → Seeds initial data
#   → Creates root user from AUTH_ROOT_* env vars
#   → Creates initial space with all per-space tables

# 4. Start service
python -m vitalgraph.cmd.vitalgraphdb_cmd
```

For existing deployments:
```bash
# Run all pending migrations
vitalgraphadmin -c migrate
#   → Checks schema_version in install table
#   → Runs auth, metrics, import_export, vector_geo migrations as needed
#   → Updates schema_version
```
