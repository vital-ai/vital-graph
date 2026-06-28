# VitalGraph ECS Deployment Guide

> Comprehensive deployment reference for the VitalGraph service on AWS ECS using Docker with the `sparql_sql` backend.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Configuration Sources](#2-configuration-sources)
3. [PostgreSQL Database Setup](#3-postgresql-database-setup)
4. [Docker Image](#4-docker-image)
5. [Jena SPARQL Compiler Sidecar](#5-jena-sparql-compiler-sidecar)
6. [Local Development with Docker Compose](#6-local-development-with-docker-compose)
7. [Frontend Configuration](#7-frontend-configuration)
8. [Authentication](#8-authentication)
9. [External Services](#9-external-services)
10. [PostgreSQL Signals](#10-postgresql-signals)
11. [Process System & Maintenance Jobs](#11-process-system--maintenance-jobs)
12. [Data Wire Format: Quads & Pydantic Models](#12-data-wire-format-quads--pydantic-models)
13. [Python Client: vital-graph\[client\]](#13-python-client-vital-graphclient)
14. [Admin CLI: vitalgraphadmin](#14-admin-cli-vitalgraphadmin)
15. [ECS Task Definition](#15-ecs-task-definition)
16. [ECS Deployment Steps](#16-ecs-deployment-steps)

---

## 1. Architecture Overview

VitalGraph is a FastAPI-based knowledge graph service backed by PostgreSQL. In the `sparql_sql` backend mode, all RDF quad storage, SPARQL query execution, and administrative operations run against a single PostgreSQL database — there is no Apache Jena/Fuseki triple store involved at runtime.

### Runtime Components

| Component | Description | Port |
|---|---|---|
| **VitalGraph App** | Python/FastAPI service (uvicorn) | 8001 |
| **SPARQL Compiler Sidecar** | Java (Jena ARQ) service that parses SPARQL into an algebra IR consumed by the V2 SQL generator | 7070 |
| **PostgreSQL** | Primary data store for quads, admin tables, entity registry, agent registry, process tracking | 5432 |
| **S3 / MinIO** | Object storage for file attachments | 9000 |
| **Weaviate** (optional) | Vector search for entity registry semantic queries | 8080/50051 |
| **MemoryDB / Redis** (optional) | Persistent LSH index for entity dedup across restarts | 6379 |

### Request Flow

```
Client → VitalGraph App (FastAPI)
           ├── SPARQL queries → Sidecar (parse) → V2 SQL generator → PostgreSQL
           ├── REST CRUD       → PostgreSQL (asyncpg pool)
           ├── File uploads    → S3 / MinIO
           └── WebSocket       → PostgreSQL NOTIFY → connected clients
```

---

## 2. Configuration Sources

VitalGraph uses **profile-prefixed environment variables** as the sole configuration source. There are no required YAML config files at runtime.

### 2.1 Profile Selection

The environment variable `VITALGRAPH_ENVIRONMENT` selects the active profile. All subsequent config variables use the profile as a prefix.

```bash
VITALGRAPH_ENVIRONMENT=local   # → looks for LOCAL_DB_HOST, LOCAL_DB_PORT, etc.
VITALGRAPH_ENVIRONMENT=prod    # → looks for PROD_DB_HOST, PROD_DB_PORT, etc.
```

The loader (`VitalGraphConfig`) resolves each key in order:
1. `{PROFILE}_{KEY}` (e.g. `PROD_DB_HOST`)
2. `{KEY}` (e.g. `DB_HOST`)
3. Hard-coded default

### 2.2 Core Environment Variables (sparql_sql backend)

| Variable | Default | Description |
|---|---|---|
| `{P}_BACKEND_TYPE` | `fuseki_postgresql` | Set to **`sparql_sql`** for pure-PostgreSQL mode |
| `{P}_DB_HOST` | `localhost` | PostgreSQL hostname |
| `{P}_DB_PORT` | `5432` | PostgreSQL port |
| `{P}_DB_NAME` | `sparql_sql_graph` | Database name |
| `{P}_DB_USERNAME` | `postgres` | Database user |
| `{P}_DB_PASSWORD` | *(empty)* | Database password |
| `{P}_DB_POOL_SIZE` | `10` | asyncpg connection pool min size |
| `{P}_DB_MAX_OVERFLOW` | `20` | asyncpg max pool size |
| `{P}_DB_POOL_TIMEOUT` | `30` | Pool checkout timeout (seconds) |
| `{P}_DB_POOL_RECYCLE` | `3600` | Connection recycle interval (seconds) |
| `{P}_SIDECAR_URL` | `http://localhost:7070` | SPARQL compiler sidecar endpoint |
| `{P}_LOG_LEVEL` | `INFO` | Application log level |

### 2.3 File Storage Variables

| Variable | Default | Description |
|---|---|---|
| `{P}_STORAGE_BACKEND` | `minio` | `minio` for local / `s3` for AWS |
| `{P}_STORAGE_ENDPOINT` | `http://localhost:9000` | S3/MinIO endpoint URL |
| `{P}_STORAGE_ACCESS_KEY` | `minioadmin` | Access key |
| `{P}_STORAGE_SECRET_KEY` | `minioadmin` | Secret key |
| `{P}_STORAGE_BUCKET` | `vitalgraph-files` | Bucket name |
| `{P}_STORAGE_REGION` | `us-east-1` | AWS region (S3 only) |
| `{P}_STORAGE_USE_SSL` | `false` / `true` | SSL for MinIO / S3 |

### 2.4 Authentication Variables

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET_KEY` | *(required)* | Secret for HS256 JWT signing. **Must be set.** |
| `SESSION_SECRET_KEY` | `your-secret-key-here` | Session middleware secret |
| `{P}_AUTH_ROOT_USERNAME` | `admin` | Root admin username |
| `{P}_AUTH_ROOT_PASSWORD` | `admin` | Root admin password |

### 2.5 Entity Registry Optional Services

#### Weaviate (semantic entity search)

| Variable | Default | Description |
|---|---|---|
| `ENTITY_WEAVIATE_ENABLED` | `false` | Set `true` to enable |
| `ENTITY_WEAVIATE_ENV` | `dev` | Collection prefix (`devxxxEntityIndex`) |
| `WEAVIATE_KEYCLOAK_URL` | — | Keycloak token endpoint for Weaviate auth |
| `WEAVIATE_CLIENT_ID` | — | OAuth client ID |
| `WEAVIATE_CLIENT_SECRET` | — | OAuth client secret |
| `WEAVIATE_USERNAME` | — | Keycloak username |
| `WEAVIATE_PASSWORD` | — | Keycloak password |
| `WEAVIATE_HTTP_HOST` | — | Weaviate HTTP host |
| `WEAVIATE_GRPC_HOST` | — | Weaviate gRPC host |
| `WEAVIATE_GRPC_PORT` | `50051` | Weaviate gRPC port |

#### MemoryDB / Redis (persistent dedup index)

| Variable | Default | Description |
|---|---|---|
| `ENTITY_DEDUP_BACKEND` | `memory` | `memory` (in-process) or `redis` |
| `ENTITY_DEDUP_REDIS_HOST` | `localhost` | Redis / MemoryDB host |
| `ENTITY_DEDUP_REDIS_PORT` | `6379` | Redis port |
| `ENTITY_DEDUP_REDIS_USERNAME` | — | ACL username (MemoryDB) |
| `ENTITY_DEDUP_REDIS_PASSWORD` | — | AUTH password |
| `ENTITY_DEDUP_REDIS_SSL` | `false` | `true` for MemoryDB (TLS required) |
| `ENTITY_DEDUP_NUM_PERM` | `128` | MinHash permutation count |
| `ENTITY_DEDUP_THRESHOLD` | `0.3` | LSH similarity threshold |

### 2.6 VitalSigns Configuration (vitalhome)

VitalSigns is the ontology/schema system. Its config is **baked into the Docker image** at `/app/vitalhome/vital-config/vitalsigns/`. The `VITAL_HOME` environment variable points to this directory.

Contents:
- `vitalsigns_config.yaml` — service definitions, vector database schemas, embedding model references
- `kgraph_weaviate_schema.yaml` — Weaviate collection schemas for KG classes

These files define the domain ontology used for Pydantic model generation and type validation. They are **not modified at deploy time** — changes require a new Docker image build.

---

## 3. PostgreSQL Database Setup

The `sparql_sql` backend uses a single PostgreSQL database containing three layers of tables.

### 3.1 Admin Tables (global)

Created by `vitalgraphadmin init`:

| Table | Purpose |
|---|---|
| `install` | Installation metadata (datetime, active flag) |
| `space` | Graph spaces (multi-tenant isolation unit) |
| `graph` | Named graphs within spaces |
| `"user"` | Application users (username, password hash, email, tenant) |
| `process` | Process tracking (maintenance jobs, imports, etc.) |
| `agent_type` | AI agent type definitions |
| `agent` | Registered AI agents (name, URI, protocol, auth config) |
| `agent_endpoint` | Agent communication endpoints |
| `agent_change_log` | Agent audit trail |

A seed record is inserted into `install` and a default `agent_type` (`urn:vital-ai:agent-type:chat`) is created.

### 3.2 Per-Space Data Tables

When a space is created, seven tables are generated with the space ID as prefix (e.g., `myspace_rdf_quad`):

| Table | Purpose |
|---|---|
| `{space}_term` | Term dictionary — maps UUID → text/type/lang/datatype |
| `{space}_rdf_quad` | RDF quad storage (subject, predicate, object, context UUIDs) |
| `{space}_datatype` | XSD datatype lookup (seeded with 35 standard types) |
| `{space}_rdf_pred_stats` | Predicate-level row counts for query optimizer |
| `{space}_rdf_stats` | Predicate×object row counts for join reordering |
| `{space}_edge` | Denormalized edge table (source→dest relationships) |
| `{space}_frame_entity` | Frame-entity mapping (KGFrame→source/dest entities) |

Extensive indexes are created on each table for the V2 SPARQL-to-SQL pipeline, including:
- Composite indexes on quad columns (`predicate+object`, `predicate+subject`, `subject+predicate`)
- GIN trigram indexes on `term_text` (requires `pg_trgm` extension)
- Edge and frame_entity indexes for graph traversal queries

### 3.3 Entity Registry Tables

Managed separately by `entity_registry/migrate.py`. These are **global** (not per-space):

| Table | Purpose |
|---|---|
| `entity_type` | Entity type definitions (person, business, organization, government) |
| `entity` | Core entity records with name, location, status |
| `entity_identifier` | External identifiers (namespace + value pairs) |
| `entity_alias` | Alternate names / AKAs |
| `entity_same_as` | Same-as entity resolution mappings |
| `category` | Category taxonomy (customer, partner, vendor, etc.) |
| `entity_category_map` | Entity→category assignments |
| `entity_change_log` | Entity audit trail |
| `entity_location_type` | Location type definitions (headquarters, branch, etc.) |
| `entity_location` | Physical locations with geocoding |
| `entity_location_category_map` | Location→category assignments |
| `relationship_type` | Inter-entity relationship type definitions |
| `entity_relationship` | Entity-to-entity relationships |

### 3.4 Required PostgreSQL Extensions

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- Trigram indexes for text search
```

This is automatically created by `vitalgraphadmin init`.

---

## 4. Docker Image

The Dockerfile builds a single image containing the Python backend and the pre-built React frontend.

### Build Stages

```dockerfile
FROM python:3.12-slim

# System deps: Node.js 20 (for frontend build), PostgreSQL client libs
# Python deps: pip install .[server]
# Frontend:    cd frontend && npm install && npm run build
#              → copies dist to vitalgraph/api/frontend/dist/
# VitalSigns:  COPY vitalhome /app/vitalhome
#              ENV VITAL_HOME=/app/vitalhome

EXPOSE 8001
CMD ["python", "-m", "vitalgraph.cmd.vitalgraphdb_cmd"]
```

Key points:
- **Base image**: `python:3.12-slim`
- **Node.js 20** is installed at build time to compile the React frontend; it is not needed at runtime
- The frontend build output is copied to `vitalgraph/api/frontend/dist/` and served by FastAPI in production mode
- `vitalhome/` (VitalSigns config) is copied into the image at `/app/vitalhome`
- The `APP_MODE=production` environment variable is set at runtime to enable frontend serving and SPA routing
- The entrypoint starts uvicorn on `0.0.0.0:8001`

### Building

```bash
docker build -t vitalgraph:latest .
```

---

## 5. Jena SPARQL Compiler Sidecar

The sidecar is a lightweight Java service that parses SPARQL queries into Jena ARQ algebra and returns a JSON IR consumed by the V2 SQL generator.

### Details

| Property | Value |
|---|---|
| **Base image** | `eclipse-temurin:21-jre` |
| **Framework** | Javalin 7 HTTP server |
| **SPARQL engine** | Apache Jena ARQ 6.0.0 |
| **Port** | 7070 |
| **Memory** | `-Xmx256m` |
| **Artifact** | `sparql-compiler-sidecar-1.0.0.jar` (fat jar via maven-shade) |

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `7070` | HTTP listen port |
| `MAX_INPUT_SIZE` | `1048576` | Max SPARQL query size (bytes) |
| `REQUEST_TIMEOUT_MS` | `5000` | Request timeout |

### Building

```bash
cd vitalgraph-jena-sidecar
docker build -t sparql-compiler:latest .
```

### How It Works

1. VitalGraph sends a SPARQL query string to `POST http://sparql-compiler:7070/compile`
2. The sidecar parses it with Jena ARQ and returns a JSON algebra tree
3. The V2 SQL generator in Python translates the algebra to PostgreSQL SQL
4. The generated SQL runs against the asyncpg connection pool

The sidecar is **stateless** and can be scaled independently.

---

## 6. Local Development with Docker Compose

`docker-compose.yml` orchestrates three services for local development:

### Services

```yaml
services:
  vitalgraph:         # Main application (port 8001)
    build: .
    env_file: .env.sparql-sql
    depends_on: [minio]
    environment:
      - JWT_SECRET_KEY=vitalgraph-super-secret-jwt-key-change-in-production-2025
      - APP_MODE=production

  sparql-compiler:    # Jena sidecar (port 7070)
    build: ./vitalgraph-jena-sidecar

  minio:              # S3-compatible storage (ports 9000, 9001)
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
```

### Running Locally

```bash
# Start all services
docker compose up --build

# Or start specific services
docker compose up sparql-compiler minio   # infrastructure only
docker compose up vitalgraph              # app only (after infra is up)
```

### Local .env File

The `.env.sparql-sql` file configures the local profile:

```bash
VITALGRAPH_ENVIRONMENT=local
LOCAL_BACKEND_TYPE=sparql_sql
LOCAL_DB_HOST=host.docker.internal   # or 'postgres' if using a PG container
LOCAL_DB_PORT=5432
LOCAL_DB_NAME=sparql_sql_graph
LOCAL_DB_USERNAME=postgres
LOCAL_DB_PASSWORD=postgres
LOCAL_SIDECAR_URL=http://sparql-compiler:7070
LOCAL_STORAGE_BACKEND=minio
LOCAL_STORAGE_ENDPOINT=http://minio:9000
LOCAL_STORAGE_ACCESS_KEY=minioadmin
LOCAL_STORAGE_SECRET_KEY=minioadmin
```

---

## 7. Frontend Configuration

The frontend is a React + TypeScript SPA using Vite, TailwindCSS 4, and Flowbite React.

### Development Mode

```bash
cd frontend
npm install
npm run dev    # Vite dev server with HMR
```

Vite proxies `/api/*` requests to `http://localhost:8001` (the FastAPI backend):

```typescript
// vite.config.ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8001',
      changeOrigin: true,
      ws: true,  // WebSocket proxy
    },
  },
}
```

### Production Mode

The frontend is built and copied into the Docker image:

```bash
npm run build
# → tsc -b && vite build
# → copies dist/ to ../vitalgraph/api/frontend/dist/
```

When `APP_MODE=production`, FastAPI:
- Mounts `/static` from the `dist/` directory
- Serves `index.html` for all non-API routes (SPA client-side routing)
- API routes under `/api/*` are handled normally

The frontend uses `axios` with interceptors for:
- Automatic `Authorization: Bearer <token>` header injection
- Automatic token refresh on 401 responses
- Redirect to `/login` on refresh failure

---

## 8. Authentication

VitalGraph uses **JWT (HS256)** for API authentication.

### Flow

1. Client sends `POST /api/login` with username/password (OAuth2 form)
2. Server validates credentials against the `"user"` table
3. Server returns `access_token` (30 min) + `refresh_token` (7 days)
4. Client includes `Authorization: Bearer <access_token>` on all requests
5. On 401, client sends `POST /api/refresh` with the refresh token
6. All protected endpoints use a FastAPI dependency (`get_current_user`) that verifies the JWT

### Key Configuration

- **`JWT_SECRET_KEY`** (environment variable, **required**): The HS256 signing secret. Must be identical across all ECS tasks.
- Access token lifetime: 30 minutes
- Refresh token lifetime: 7 days
- The `VitalGraphAuth` class validates users against the database `"user"` table

### Endpoints

| Endpoint | Auth | Description |
|---|---|---|
| `POST /api/login` | None | Authenticate and get tokens |
| `POST /api/logout` | Bearer | Invalidate session |
| `POST /api/refresh` | Bearer (refresh) | Get new access token |
| `GET /health` | None | Health check |

---

## 9. External Services

### 9.1 S3 (Production)

For ECS deployment, use native S3 instead of MinIO:

```bash
PROD_STORAGE_BACKEND=s3
PROD_STORAGE_ENDPOINT=             # empty for native S3
PROD_STORAGE_ACCESS_KEY=<IAM key>  # or use IAM task role
PROD_STORAGE_SECRET_KEY=<IAM secret>
PROD_STORAGE_BUCKET=vitalgraph-files
PROD_STORAGE_REGION=us-east-1
PROD_STORAGE_USE_SSL=true
```

With ECS task IAM roles, you can omit the access/secret keys and let the SDK use instance credentials.

### 9.2 Weaviate (Optional)

Provides semantic vector search over the entity registry. Authenticates via Keycloak OAuth2. See [Section 2.5](#25-entity-registry-optional-services) for configuration.

### 9.3 MemoryDB / Redis (Optional)

Provides persistent MinHash LSH dedup index for the entity registry. When using AWS MemoryDB:
- TLS is required (`ENTITY_DEDUP_REDIS_SSL=true`)
- ACL credentials are passed via `ENTITY_DEDUP_REDIS_USERNAME` / `ENTITY_DEDUP_REDIS_PASSWORD`
- The index key prefix is scoped by `VITALGRAPH_ENVIRONMENT` (e.g., `prod_dedup_bucket_...`)

If using the `memory` backend (default), the dedup index is rebuilt from PostgreSQL on each process start.

---

## 10. PostgreSQL Signals

VitalGraph uses PostgreSQL `NOTIFY` / `LISTEN` for real-time inter-process communication.

### Channels

| Channel | Purpose |
|---|---|
| `vitalgraph_space` | Space create/update/delete → SpaceManager cache sync |
| `vitalgraph_graph` | Graph changes |
| `vitalgraph_user` | User changes |
| `vitalgraph_entity_dedup` | Entity dedup index sync (add/remove/reload_full) |
| `vitalgraph_process` | Process status updates |

### How It Works

The `SignalManager` maintains two persistent psycopg3 connections:
- **Listen connection**: Subscribes to all channels, dispatches to registered callbacks
- **Notify connection**: Sends `NOTIFY channel, 'json_payload'` on data changes

This enables:
- **Cross-instance cache invalidation**: When one ECS task creates a space, all other tasks update their in-memory SpaceManager
- **WebSocket bridge**: PostgreSQL notifications are forwarded to connected WebSocket clients for real-time UI updates
- **Entity dedup sync**: When one task adds an entity, other tasks update their local MinHash index

---

## 11. Process System & Maintenance Jobs

### 11.1 Process Scheduler

The `ProcessScheduler` runs periodic background jobs using asyncio tasks. It uses **PostgreSQL advisory locks** (`pg_try_advisory_lock`) to ensure only one ECS task runs a given job at a time.

```
ProcessScheduler
  └── register_job("db_maintenance", interval=300s)
        └── MaintenanceJob.run()  [gated by advisory lock]
```

### 11.2 Maintenance Job

The `MaintenanceJob` runs every 5 minutes (configurable) and performs:

#### ANALYZE
- Queries `pg_stat_user_tables` for `n_mod_since_analyze` and `last_analyze`
- Skips if < 10,000 modifications AND last analyze < 10 minutes ago
- Runs `ANALYZE` on the space with the worst staleness score
- **Impact**: Updates PostgreSQL query planner statistics, ensuring optimal join ordering and index usage for SPARQL-generated SQL

#### VACUUM
- Queries `pg_stat_user_tables` for `n_dead_tup` and `last_vacuum`
- Skips if < 10,000 dead tuples AND last vacuum < 30 minutes ago
- Runs `VACUUM` on the worst space
- **Impact**: Reclaims dead tuple space, prevents table bloat, maintains index efficiency

#### Stats Rebuild
- Can be triggered on-demand via `rebuild stats` in the admin CLI or via the API
- Rebuilds `rdf_pred_stats` and `rdf_stats` tables used by the V2 query optimizer
- **Impact**: The query generator uses these statistics to reorder joins and select optimal access paths. Stale stats can cause suboptimal query plans.

#### Process Record Cleanup
- Runs once per day
- Deletes process records older than 30 days

### 11.3 Instance Identification

On ECS, the maintenance job resolves the task ID from the `ECS_CONTAINER_METADATA_URI_V4` endpoint. Falls back to `socket.gethostname()` for local development.

### 11.4 Auxiliary Table Sync

On every write operation (insert/delete), the following auxiliary tables are incrementally synced:

| Write Path | Sync Order |
|---|---|
| **Insert** | edge → frame_entity → stats |
| **Delete** | frame_entity → edge → stats → quads |

A full resync can be triggered via `rebuild resync` in the admin CLI.

---

## 12. Data Wire Format: Quads & Pydantic Models

### 12.1 RDF Quad Storage

All data in VitalGraph is stored as RDF quads (subject, predicate, object, context) in PostgreSQL. Each quad component is stored as a UUID referencing the `term` dictionary table.

A **term** can be:
- `U` — URI (e.g., `http://vital.ai/ontology/vital-core#name`)
- `L` — Literal (with optional language tag or datatype)
- `B` — Blank node
- `G` — Graph name

### 12.2 Pydantic Models

The API uses Pydantic models as the primary serialization format. Graph objects (KGEntity, KGFrame, Edge, etc.) are represented as JSON with type information:

```json
{
  "type": "http://vital.ai/ontology/vital-core#KGEntity",
  "URI": "urn:entity:12345",
  "properties": {
    "http://vital.ai/ontology/vital-core#name": "Example Entity",
    "http://vital.ai/ontology/vital-core#hasStatus": "active"
  }
}
```

### 12.3 Wire Format

The client and server exchange data in **JSON quad format**. The client's `ClientWireFormat.JSON_QUADS` mode serializes graph objects into quads for transport and deserializes them back into typed Pydantic models on receipt.

This enables:
- Type-safe graph object manipulation in Python
- Automatic conversion between quad representation and domain models
- Validation of property types against the VitalSigns ontology

---

## 13. Python Client: vital-graph[client]

### Installation

```bash
pip install vital-graph[client]
```

This installs the lightweight client package with dependencies: `httpx`, `pydantic`, plus the VitalSigns model layer.

### Configuration

The client uses its own profile-prefixed environment variables:

```bash
export VITALGRAPH_CLIENT_ENVIRONMENT=prod
export PROD_CLIENT_SERVER_URL=https://vitalgraph.example.com
export PROD_CLIENT_AUTH_USERNAME=admin
export PROD_CLIENT_AUTH_PASSWORD=<password>
export PROD_CLIENT_TIMEOUT=30
export PROD_CLIENT_MAX_RETRIES=3
```

### Usage

```python
from vitalgraph.client.vitalgraph_client import VitalGraphClient

async with VitalGraphClient() as client:
    await client.open()

    # List spaces
    spaces = await client.spaces.list_spaces()

    # SPARQL query
    results = await client.sparql.query("space_id", "SELECT ?s WHERE { ?s a <...> }")

    # KG entity operations
    entity = await client.kgentities.get_entity("space_id", "urn:entity:123")

    # File upload
    await client.files.upload("space_id", "/path/to/file.pdf")

    # Import data
    await client.imports.import_file("space_id", "/path/to/data.nq")

    # Entity registry
    entities = await client.entity_registry.search(name="Acme Corp")

    # Agent registry
    agents = await client.agent_registry.list_agents()
```

### Available Endpoint Objects

| Endpoint | Description |
|---|---|
| `client.spaces` | Space CRUD |
| `client.users` | User management |
| `client.sparql` | SPARQL query/update |
| `client.kgtypes` | KG type browsing |
| `client.kgentities` | KG entity CRUD |
| `client.kgframes` | KG frame CRUD |
| `client.kgrelations` | KG relation CRUD |
| `client.kgqueries` | Structured KG queries |
| `client.objects` | Generic graph object access |
| `client.triples` | Triple-level operations |
| `client.graphs` | Named graph management |
| `client.files` | File upload/download |
| `client.imports` | Bulk data import |
| `client.exports` | Data export |
| `client.entity_registry` | Entity registry operations |
| `client.agent_registry` | Agent registry operations |
| `client.processes` | Process tracking |
| `client.admin` | Admin operations (resync, etc.) |

### Graph Object Conversion

The client automatically converts between JSON quad wire format and typed Python objects. Graph objects returned by the API are deserialized into Pydantic models with full property access.

---

## 14. Admin CLI: vitalgraphadmin

The `vitalgraphadmin` CLI provides an interactive REPL for database administration.

### Starting

```bash
# Installed via pip install vital-graph[server]
vitalgraphadmin

# Or in Docker
docker exec -it <container> python -m vitalgraph.admin_cmd.vitalgraphdb_admin_cmd
```

### Commands

| Command | Description |
|---|---|
| `connect` | Connect to the database using environment variables |
| `disconnect` | Close database connection |
| `init` | Create admin tables, indexes, seed data, and `pg_trgm` extension |
| `purge` | Truncate all tables and re-seed (keeps table structure) |
| `delete` | Drop all VitalGraph tables |
| `info` | Show backend type, connection details, init state, space count |
| `list spaces` | List all graph spaces |
| `list users` | List all users |
| `list graphs` | List named graphs |
| `use <space_id>` | Set current space context |
| `unuse` | Clear current space context |
| `import` | Import data into a space (interactive wizard or flags) |
| `rebuild indexes` | Rebuild all space indexes |
| `rebuild stats [space_id]` | Rebuild query optimizer statistics |
| `rebuild analyze [space_id]` | Run ANALYZE on space tables |
| `rebuild vacuum [space_id]` | Run VACUUM on space tables |
| `rebuild resync [space_id]` | Resync auxiliary tables (edge, frame_entity, stats) |
| `set` | Change runtime settings (e.g., log level) |
| `exit` | Disconnect and exit |

### Initial Database Setup

```bash
# 1. Set environment variables for your target database
export VITALGRAPH_ENVIRONMENT=prod
export PROD_BACKEND_TYPE=sparql_sql
export PROD_DB_HOST=your-rds-endpoint.amazonaws.com
export PROD_DB_NAME=sparql_sql_graph
export PROD_DB_USERNAME=vitalgraph
export PROD_DB_PASSWORD=<password>
export PROD_SIDECAR_URL=http://sparql-compiler:7070

# 2. Start the admin CLI
vitalgraphadmin

# 3. Connect and initialize
> connect
> init
> info
> exit
```

---

## 15. ECS Task Definition

### 15.1 Container Definitions

The ECS task requires **two containers**: the VitalGraph app and the SPARQL compiler sidecar.

```json
{
  "family": "vitalgraph",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [
    {
      "name": "vitalgraph",
      "image": "<account>.dkr.ecr.<region>.amazonaws.com/vitalgraph:latest",
      "portMappings": [{ "containerPort": 8001, "protocol": "tcp" }],
      "essential": true,
      "environment": [
        { "name": "VITALGRAPH_ENVIRONMENT", "value": "prod" },
        { "name": "PROD_BACKEND_TYPE", "value": "sparql_sql" },
        { "name": "PROD_DB_HOST", "value": "<rds-endpoint>" },
        { "name": "PROD_DB_PORT", "value": "5432" },
        { "name": "PROD_DB_NAME", "value": "sparql_sql_graph" },
        { "name": "PROD_DB_POOL_SIZE", "value": "10" },
        { "name": "PROD_DB_MAX_OVERFLOW", "value": "20" },
        { "name": "PROD_SIDECAR_URL", "value": "http://localhost:7070" },
        { "name": "PROD_STORAGE_BACKEND", "value": "s3" },
        { "name": "PROD_STORAGE_BUCKET", "value": "vitalgraph-files" },
        { "name": "PROD_STORAGE_REGION", "value": "us-east-1" },
        { "name": "PROD_STORAGE_USE_SSL", "value": "true" },
        { "name": "PROD_LOG_LEVEL", "value": "INFO" },
        { "name": "APP_MODE", "value": "production" },
        { "name": "WORKERS", "value": "1" }
      ],
      "secrets": [
        { "name": "PROD_DB_USERNAME", "valueFrom": "arn:aws:secretsmanager:<region>:<account>:secret:vitalgraph/db-username" },
        { "name": "PROD_DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:<region>:<account>:secret:vitalgraph/db-password" },
        { "name": "JWT_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:<region>:<account>:secret:vitalgraph/jwt-secret" },
        { "name": "PROD_STORAGE_ACCESS_KEY", "valueFrom": "arn:aws:secretsmanager:<region>:<account>:secret:vitalgraph/s3-access-key" },
        { "name": "PROD_STORAGE_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:<region>:<account>:secret:vitalgraph/s3-secret-key" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/vitalgraph",
          "awslogs-region": "<region>",
          "awslogs-stream-prefix": "vitalgraph"
        }
      },
      "dependsOn": [
        { "containerName": "sparql-compiler", "condition": "START" }
      ]
    },
    {
      "name": "sparql-compiler",
      "image": "<account>.dkr.ecr.<region>.amazonaws.com/sparql-compiler:latest",
      "portMappings": [{ "containerPort": 7070, "protocol": "tcp" }],
      "essential": true,
      "environment": [
        { "name": "PORT", "value": "7070" },
        { "name": "MAX_INPUT_SIZE", "value": "1048576" },
        { "name": "REQUEST_TIMEOUT_MS", "value": "5000" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/vitalgraph",
          "awslogs-region": "<region>",
          "awslogs-stream-prefix": "sparql-compiler"
        }
      }
    }
  ]
}
```

### 15.2 Environment vs Secrets

| Category | Use `environment` | Use `secrets` (Secrets Manager) |
|---|---|---|
| **Non-sensitive** | Backend type, DB host/port/name, sidecar URL, storage bucket, log level, app mode | — |
| **Sensitive** | — | DB username, DB password, JWT secret key, S3 access/secret keys, Weaviate credentials, Redis password |

### 15.3 Sidecar Communication

Because both containers share the same ECS task network namespace (`awsvpc` mode), the VitalGraph app reaches the sidecar at `http://localhost:7070`. Set:

```
PROD_SIDECAR_URL=http://localhost:7070
```

### 15.4 Optional Entity Registry Containers

If using Weaviate or MemoryDB, add the relevant environment variables and secrets to the `vitalgraph` container definition. These are external services (not sidecar containers) — configure security groups to allow access from the ECS task.

---

## 16. ECS Deployment Steps

### Prerequisites

- AWS account with ECR, ECS, RDS, S3, Secrets Manager, VPC
- PostgreSQL 14+ RDS instance (or Aurora PostgreSQL)
- S3 bucket for file storage
- Docker installed locally for building images

### Step-by-Step

#### 1. Create Infrastructure

```bash
# Create RDS PostgreSQL instance
# Create S3 bucket: vitalgraph-files
# Create Secrets Manager secrets:
#   vitalgraph/db-username
#   vitalgraph/db-password
#   vitalgraph/jwt-secret (generate with: python -c "import secrets; print(secrets.token_hex(32))")
#   vitalgraph/s3-access-key (if not using IAM roles)
#   vitalgraph/s3-secret-key
# Create CloudWatch log group: /ecs/vitalgraph
# Create ECS cluster
# Create ALB with target group (port 8001)
```

#### 2. Create PostgreSQL Database

```sql
-- Connect to your RDS instance
CREATE DATABASE sparql_sql_graph;
\c sparql_sql_graph
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

#### 3. Build and Push Docker Images

```bash
# Authenticate to ECR
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <account>.dkr.ecr.<region>.amazonaws.com

# Build and push VitalGraph
docker build -t vitalgraph:latest .
docker tag vitalgraph:latest <account>.dkr.ecr.<region>.amazonaws.com/vitalgraph:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/vitalgraph:latest

# Build and push SPARQL Compiler
cd vitalgraph-jena-sidecar
docker build -t sparql-compiler:latest .
docker tag sparql-compiler:latest <account>.dkr.ecr.<region>.amazonaws.com/sparql-compiler:latest
docker push <account>.dkr.ecr.<region>.amazonaws.com/sparql-compiler:latest
```

#### 4. Initialize Database Tables

```bash
# Run the admin CLI locally (or via a one-off ECS task) pointing at the RDS instance
export VITALGRAPH_ENVIRONMENT=prod
export PROD_BACKEND_TYPE=sparql_sql
export PROD_DB_HOST=<rds-endpoint>
export PROD_DB_PORT=5432
export PROD_DB_NAME=sparql_sql_graph
export PROD_DB_USERNAME=<username>
export PROD_DB_PASSWORD=<password>
export PROD_SIDECAR_URL=http://localhost:7070  # sidecar not needed for init

vitalgraphadmin
> connect
> init        # Creates admin tables, indexes, seed data
> info        # Verify: "Initialization State: Initialized"
> exit

# Also run entity registry migration
python entity_registry/migrate.py
```

#### 5. Register ECS Task Definition

Register the task definition JSON from [Section 15.1](#151-container-definitions), replacing placeholders with your actual values.

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

#### 6. Create ECS Service

```bash
aws ecs create-service \
  --cluster vitalgraph-cluster \
  --service-name vitalgraph \
  --task-definition vitalgraph \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=DISABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=vitalgraph,containerPort=8001"
```

#### 7. Verify Deployment

```bash
# Health check
curl https://vitalgraph.example.com/health

# Login
curl -X POST https://vitalgraph.example.com/api/login \
  -d "username=admin&password=admin"

# Check info via client
pip install vital-graph[client]
export VITALGRAPH_CLIENT_ENVIRONMENT=prod
export PROD_CLIENT_SERVER_URL=https://vitalgraph.example.com
export PROD_CLIENT_AUTH_USERNAME=admin
export PROD_CLIENT_AUTH_PASSWORD=<password>
python -c "
from vitalgraph.client.vitalgraph_client import VitalGraphClient
import asyncio
async def check():
    async with VitalGraphClient() as c:
        await c.open()
        spaces = await c.spaces.list_spaces()
        print(f'Connected! Spaces: {spaces}')
asyncio.run(check())
"
```

#### 8. Post-Deployment

- **Create spaces**: Use the admin CLI or API to create graph spaces for your tenants
- **Import data**: Use `vitalgraphadmin import` or the `/api/data/import` endpoint
- **Monitor maintenance**: Check the `process` table or `/api/processes` endpoint for ANALYZE/VACUUM job history
- **Scale**: Increase ECS desired count; advisory locks ensure only one task runs maintenance at a time

---

## Quick Reference: Port Map

| Service | Port | Protocol |
|---|---|---|
| VitalGraph API | 8001 | HTTP |
| SPARQL Compiler | 7070 | HTTP |
| PostgreSQL | 5432 | TCP |
| S3 / MinIO | 9000 | HTTP |
| MinIO Console | 9001 | HTTP |
| Weaviate HTTP | 8080 | HTTP |
| Weaviate gRPC | 50051 | gRPC |
| Redis / MemoryDB | 6379 | TCP |
