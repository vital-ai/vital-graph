# VitalGraph UI Development & Deployment Plan

## Implementation Status Summary

| Step | Description | Status |
|------|-------------|--------|
| 1 | Split Build Script (`build:only` / `deploy:local`) | ✅ Done |
| 2 | Multi-Stage Dockerfile (3-stage, no Node.js in final) | ✅ Done |
| 3 | Frontend Asset Serving (SPA fallback, StaticFiles) | 🟡 Partial — works but uses fragile Path traversal |
| 4 | `docker-compose.dev.yml` (sidecar + MinIO for dev) | ❌ Not created |
| 5 | Complete `docker-compose.yml` (add PostgreSQL, env vars) | 🟡 Partial — no PostgreSQL service, missing env vars |
| 6 | Update `.dockerignore` | ✅ Done |
| 7 | Document Workflows (`DEVELOPMENT.md`, README) | ❌ Not created (`.env.example` is comprehensive) |

**Config modernization**: The config system now uses profile-based env vars
(`VITALGRAPH_ENVIRONMENT` + `LOCAL_*` / `PROD_*` / etc.) rather than the simple
`DATABASE_URL` pattern originally proposed. The docker-compose files should align
with this system.

---

## 1. Current Problems

### 1.1 ~~Awkward Frontend Build Artifact Copying~~ ✅ RESOLVED

**Fixed**: `frontend/package.json` now has separate scripts:
- `build:only` — pure `tsc -b && vite build` (output stays in `frontend/dist/`)
- `deploy:local` — copies `dist/` into the Python package tree (for local non-Docker testing)
- `build` — calls both (backward compatible)

The Docker build uses `build:only` and copies the output via `COPY --from=frontend-build`.
The cross-directory copy side effect is now opt-in (`deploy:local`) rather than default.

### 1.2 ~~Single-Stage Dockerfile with Node.js~~ ✅ RESOLVED

**Fixed**: Dockerfile rewritten as a proper 3-stage multi-stage build:

```dockerfile
# Stage 1: node:20-slim — npm ci + npm run build:only
# Stage 2: python:3.12-slim — pip install deps only (with gcc)
# Stage 3: python:3.12-slim — final production image (no Node.js, no gcc)
#   COPY --from=python-deps site-packages
#   COPY --from=frontend-build /frontend/dist → vitalgraph/api/frontend/dist/
```

Benefits achieved:
- No Node.js in final image (~200MB+ saved)
- Frontend and Python layers cache independently
- Frontend-only changes rebuild only Stage 1 + final COPY (~30s)
- Python-only changes skip Stage 1 entirely

### 1.3 Incomplete Docker Compose — 🟡 PARTIALLY RESOLVED

`docker-compose.yml` still has no **PostgreSQL** service. It has VitalGraph +
Jena sidecar + MinIO, but no database. The vitalgraph service is also missing
`SIDECAR_URL` and database config env vars, so `docker compose up` does not
produce a fully working system without manual `.env` configuration.

**What works**: The 3-stage Dockerfile builds correctly. MinIO has a healthcheck.
The Jena sidecar is included. `.env` file is referenced.

**Still needed**: Add PostgreSQL service, add `depends_on` conditions for
postgres + sparql-compiler, add database/sidecar env vars, align with the
profile-based config system (`VITALGRAPH_ENVIRONMENT` + `LOCAL_*` vars).

### 1.4 Development Workflow Friction — 🟡 PARTIALLY RESOLVED

To develop locally, a developer must:
1. Start PostgreSQL (manually, or via a separate Docker command)
2. Start the Jena sidecar (manually or Docker)
3. Start the Python backend: `/opt/homebrew/anaconda3/envs/vital-graph/bin/python -m vitalgraph.cmd.vitalgraphdb_cmd`
4. Start the Vite dev server: `cd frontend && npm run dev`
5. Know that the Vite proxy at `:5173` forwards `/api` to `:8001`

**What works**: Vite proxy is configured (`vite.config.ts` proxies `/api` and `/health`
to `localhost:8001`). HMR works. `.env.example` is comprehensive with profile-based
config (`VITALGRAPH_ENVIRONMENT` + `LOCAL_*` vars), client config, and multi-profile docs.

**Still needed**: No `docker-compose.dev.yml` for auxiliary services. No
`DEVELOPMENT.md` documenting the setup workflow.

---

## 2. Proposed Architecture

### 2.1 Multi-Stage Docker Build

Replace the single-stage Dockerfile with a proper multi-stage build. The
frontend builds in a Node.js stage, and only the static `dist/` output is
copied into the slim Python production image.

```dockerfile
# ---- Stage 1: Build frontend ----
FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build:only   # tsc + vite build, no copy

# ---- Stage 2: Install Python dependencies ----
FROM python:3.12-slim AS python-deps
WORKDIR /app
RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev unixodbc unixodbc-dev libodbccr2 libodbc2 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
RUN mkdir -p vitalgraph && touch vitalgraph/__init__.py \
    && pip install --no-cache-dir ".[server]" \
    && rm -rf vitalgraph

# ---- Stage 3: Final production image ----
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages
COPY --from=python-deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-deps /usr/local/bin /usr/local/bin

# Copy VitalSigns config and pre-warm
COPY vitalhome/ ./vitalhome/
ENV VITAL_HOME=/app/vitalhome
RUN python -c "from vital_ai_vitalsigns.vitalsigns import VitalSigns; VitalSigns()"

# Copy application code
COPY vitalgraph/ ./vitalgraph/
RUN pip install --no-cache-dir --no-deps "."

# Copy frontend build output (from Stage 1)
COPY --from=frontend-build /frontend/dist ./vitalgraph/api/frontend/dist/

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_MODE=production PORT=8001 HOST=0.0.0.0
EXPOSE 8001
CMD ["python", "-m", "vitalgraph.cmd.vitalgraphdb_cmd"]
```

**Benefits**:
- No Node.js in the final image
- Frontend and Python dependency layers cache independently
- Final image is ~300MB smaller
- Frontend-only changes rebuild only Stage 1 + Stage 3 COPY (fast)
- Python-only changes skip Stage 1 entirely (cached)

### 2.2 Decouple Build Script from Copy

Split the frontend build into two npm scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build:only": "tsc -b && vite build",
    "build": "npm run build:only && npm run deploy:local",
    "deploy:local": "mkdir -p ../vitalgraph/api/frontend && cp -r dist ../vitalgraph/api/frontend/",
    "lint": "eslint .",
    "preview": "vite preview",
    "format": "prettier . --write",
    "format:check": "prettier . --check",
    "postinstall": "flowbite-react patch"
  }
}
```

- `build:only` — pure build, output stays in `frontend/dist/`. Used by Docker
  Stage 1 and CI.
- `deploy:local` — copies `dist/` into the Python package tree. Only needed
  for local non-Docker production testing.
- `build` — does both (backwards compatible with current workflow).

### 2.3 Robust Frontend Asset Serving — 🟡 PARTIALLY DONE

**Current state**: SPA fallback works via `catch_all()` in `vitalgraphapp_impl.py`.
`_setup_static_files()` mounts `StaticFiles` at `/static`. The `catch_all()` route
serves static files for direct paths and falls back to `index.html` for SPA routing,
correctly excluding `/api/`, `/static/`, `/docs`, `/openapi.json`.

**Still uses** `Path(__file__).parent.parent.parent` traversal (fragile). The mount
is at `/static` rather than `/assets` (Vite outputs to `assets/`).

**Proposed** (original plan — cleaner but not yet implemented):

```python
# In _init_frontend_routes():
if self.app_mode == "production":
    # Determine frontend dist path from config or well-known location
    frontend_dist = Path(__file__).parent.parent / "api" / "frontend" / "dist"
    if frontend_dist.exists():
        # Mount static assets (JS, CSS, images) under /assets
        self.app.mount(
            "/assets",
            StaticFiles(directory=frontend_dist / "assets"),
            name="static-assets"
        )
        # SPA fallback for all other routes
        @self.app.get("/{path:path}")
        async def spa_fallback(path: str):
            # Serve API/docs paths normally
            if path.startswith(("api/", "docs", "openapi.json", "health")):
                raise HTTPException(status_code=404)
            return FileResponse(frontend_dist / "index.html")
    else:
        self.app.get("/")(self.api_root)
```

**Benefits**:
- `StaticFiles` handles caching headers, MIME types, and directory traversal
  protection automatically
- No manual `Path` juggling for every static file request
- Single `index.html` fallback for SPA routing
- Graceful fallback to API-only mode if frontend isn't built

### 2.4 Docker Compose for Development Services — ❌ NOT YET CREATED

Local development uses **local PostgreSQL** (not Docker) — the database runs
natively on the developer's machine. Docker Compose only provides the
auxiliary services that are harder to install locally.

**Status**: `docker-compose.dev.yml` does not exist yet. Developers start
the Jena sidecar and MinIO manually or via the main `docker-compose.yml`.

**Proposed**:

```yaml
# docker-compose.dev.yml — auxiliary services for local development
services:
  sparql-compiler:
    build:
      context: ./vitalgraph-jena-sidecar
      dockerfile: Dockerfile
    ports: ["7070:7070"]
    environment:
      PORT: 7070

  minio:
    image: minio/minio:latest
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_dev:/data

volumes:
  minio_dev:
```

PostgreSQL is expected to be running locally (e.g., via Homebrew
`brew services start postgresql@17` or the Postgres.app).

Usage:
```bash
# Start auxiliary services (sidecar + MinIO)
docker compose -f docker-compose.dev.yml up -d

# PostgreSQL is already running locally on port 5432

# Start Python backend (in terminal 1)
cd /path/to/vital-graph
/opt/homebrew/anaconda3/envs/vital-graph/bin/python -m vitalgraph.cmd.vitalgraphdb_cmd

# Start frontend dev server (in terminal 2)
cd frontend && npm run dev

# Open browser at http://localhost:5173
```

> **Note**: For automated testing (E2E, integration), a Docker PostgreSQL
> instance is used instead — see `docker-compose.e2e.yml` in
> `planning_ui/ui_testing_plan.md`. This keeps the test database isolated
> from the developer's local data.

### 2.5 Production Docker Compose — 🟡 PARTIALLY DONE

In real deployments (ECS, Kubernetes, etc.), PostgreSQL is an **external
managed service** (e.g., AWS RDS, Cloud SQL) — not a Docker container.
Similarly, object storage would be S3 rather than a local MinIO container.
The Docker Compose file is therefore used only for **local production testing**
and **CI**, not as the actual production deployment mechanism.

**Current state**: `docker-compose.yml` exists with VitalGraph + Jena sidecar +
MinIO. Missing: PostgreSQL service, `depends_on` condition for sparql-compiler,
database/sidecar env vars in vitalgraph service.

**Note**: The config system has been modernized to use **profile-based env vars**
(`VITALGRAPH_ENVIRONMENT=local` with `LOCAL_DB_HOST`, `LOCAL_DB_PORT`, etc.)
rather than the simple `DATABASE_URL` pattern shown below. The docker-compose
should be updated to align with this profile system.

**Proposed** (needs update to match profile-based config):

```yaml
# docker-compose.yml — local production testing / CI
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-vitalgraph}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      retries: 5
    networks:
      - vitalgraph_network

  vitalgraph:
    build: .
    depends_on:
      postgres: { condition: service_healthy }
      sparql-compiler: { condition: service_started }
      minio: { condition: service_started }
    ports:
      - "${PORT:-8001}:${PORT:-8001}"
    environment:
      APP_MODE: production
      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-vitalgraph}
      SIDECAR_URL: http://sparql-compiler:7070
      MINIO_ENDPOINT: minio:9000
      JWT_SECRET_KEY: ${JWT_SECRET_KEY:?Set JWT_SECRET_KEY}
      PORT: ${PORT:-8001}
      HOST: 0.0.0.0
    env_file:
      - .env
    restart: unless-stopped
    networks:
      - vitalgraph_network

  sparql-compiler:
    build:
      context: ./vitalgraph-jena-sidecar
      dockerfile: Dockerfile
    environment:
      PORT: 7070
    restart: unless-stopped
    networks:
      - vitalgraph_network

  minio:
    image: minio/minio:latest
    environment:
      MINIO_ROOT_USER: ${MINIO_USER:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD:-minioadmin}
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      retries: 3
    networks:
      - vitalgraph_network

volumes:
  pgdata:
  minio_data:

networks:
  vitalgraph_network:
```

### 2.6 ECS / Cloud Deployment

In an ECS deployment, only the **VitalGraph** and **Jena sidecar** containers
are deployed as ECS tasks. External services are managed separately:

| Component | ECS | Managed Service |
|---|---|---|
| VitalGraph (front+back end) | ECS Fargate task | — |
| Jena SPARQL compiler | ECS Fargate task (sidecar) | — |
| PostgreSQL | — | **AWS RDS** (PostgreSQL 17) |
| Object storage | — | **AWS S3** |

The VitalGraph container connects to RDS and S3 via profile-based environment variables:
```
VITALGRAPH_ENVIRONMENT=prod
PROD_DB_HOST=mydb.xxxx.us-east-1.rds.amazonaws.com
PROD_DB_PORT=5432
PROD_DB_NAME=vitalgraph
PROD_DB_USERNAME=postgres
PROD_DB_PASSWORD=<from secrets manager>
PROD_STORAGE_BACKEND=s3
PROD_STORAGE_BUCKET=vitalgraph-files-prod
PROD_STORAGE_REGION=us-east-1
```

The Docker image is the same multi-stage image used everywhere — only the
environment variables change between local, CI, and cloud deployments.

---

## 3. Development Workflow

### 3.1 First-Time Setup

```bash
# 1. Clone and install
git clone <repo>
cd vital-graph

# 2. Ensure local PostgreSQL is running
#    macOS: brew services start postgresql@17
#    Or use Postgres.app

# 3. Create the dev database (if needed)
createdb vitalgraph_dev

# 4. Start auxiliary services (Jena sidecar + MinIO)
#    NOTE: docker-compose.dev.yml does not exist yet (Step 4 pending).
#    For now, use: docker compose up -d  (starts sidecar + MinIO from main compose)

# 5. Install Python deps (conda)
conda activate vital-graph
pip install -e ".[server]"

# 6. Install frontend deps
cd frontend && npm install && cd ..

# 7. Configure
cp .env.example .env
# Edit .env with local DB credentials, JWT secret, etc.
```

### 3.2 Daily Development

```bash
# Ensure local PostgreSQL is running
# Ensure auxiliary services are up
#    NOTE: docker-compose.dev.yml pending. Use: docker compose up -d
docker compose -f docker-compose.dev.yml up -d  # once created

# Terminal 1: Backend
/opt/homebrew/anaconda3/envs/vital-graph/bin/python -m vitalgraph.cmd.vitalgraphdb_cmd

# Terminal 2: Frontend (HMR)
cd frontend && npm run dev

# Browser: http://localhost:5173
```

### 3.3 Frontend-Only Changes

With Vite HMR, frontend changes are reflected instantly at `localhost:5173`
without restarting anything. The Vite dev server proxies `/api` requests to
the backend at `localhost:8001`.

### 3.4 Backend-Only Changes

Restart the Python process in Terminal 1. Frontend dev server stays running
and continues to proxy API calls.

### 3.5 Full Production Build (Local)

```bash
# Build frontend + copy to Python package tree
cd frontend && npm run build && cd ..

# Run in production mode
APP_MODE=production /opt/homebrew/anaconda3/envs/vital-graph/bin/python -m vitalgraph.cmd.vitalgraphdb_cmd
# Visit http://localhost:8001 (frontend served by FastAPI)
```

### 3.6 Docker Production Build

```bash
docker compose build
docker compose up -d
# Visit http://localhost:8001
```

---

## 4. Deployment Environments

### 4.1 Environment Matrix

| Environment | Frontend | Backend | Database | How to start |
|---|---|---|---|---|
| **Local dev** | Vite HMR (:5173) | Python process (:8001) | Local PG | `docker-compose.dev.yml` (sidecar+MinIO) + 2 terminals |
| **Local prod** | Built into FastAPI | Python process (:8001) | Local PG | `npm run build` → `APP_MODE=production` |
| **Docker (local)** | Built into image | Docker container (:8001) | Docker PG | `docker compose up` (local testing) |
| **CI / E2E** | Built into image | Docker container (:8001) | Docker PG | `docker-compose.e2e.yml` |
| **AWS ECS** | Built into image | ECS Fargate task | **RDS** PostgreSQL | ECS task def, RDS instance |
| **AWS (storage)** | — | — | — | **S3** replaces MinIO |

### 4.2 Environment Variables

**Note**: The config system now uses **profile-based env vars**. Set
`VITALGRAPH_ENVIRONMENT` to select a profile (`local`, `dev`, `staging`, `prod`),
then each config value is read from `{PROFILE}_*` variables. See `.env.example`
for the full reference (320 lines covering server config, client config,
Keycloak auth, entity registry, Weaviate, import/export, and SPARQL-SQL profiles).

| Variable | Dev default | Required in prod | Purpose |
|---|---|---|---|
| `APP_MODE` | `development` | `production` | Controls frontend serving, logging |
| `VITALGRAPH_ENVIRONMENT` | `local` | `prod` | Selects config profile |
| `LOCAL_DB_HOST` / `PROD_DB_HOST` | `localhost` | Yes (via profile) | PostgreSQL host |
| `LOCAL_DB_PORT` / `PROD_DB_PORT` | `5432` | Yes (via profile) | PostgreSQL port |
| `LOCAL_DB_NAME` / `PROD_DB_NAME` | `vitalgraph` | Yes (via profile) | Database name |
| `LOCAL_DB_USERNAME` / `PROD_DB_USERNAME` | `postgres` | Yes (via profile) | Database user |
| `LOCAL_DB_PASSWORD` / `PROD_DB_PASSWORD` | (local pw) | Yes (via profile) | Database password |
| `LOCAL_SIDECAR_URL` | `http://localhost:7070` | Yes (via profile) | Jena SPARQL compiler |
| `LOCAL_STORAGE_ENDPOINT` | `http://minio:9000` | Yes (via profile) | File storage (MinIO/S3) |
| `JWT_SECRET_KEY` | (generate locally) | Yes | Auth token signing |
| `PORT` | `8001` | No | Server port |
| `WORKERS` | `1` | No | Uvicorn workers |

---

## 5. Implementation Steps

### Step 1: Split Build Script ✅
- ✅ Added `build:only` script to `frontend/package.json` (tsc + vite build only)
- ✅ Added `deploy:local` script for the cross-directory copy
- ✅ `build` calls `build:only` then `deploy:local` (backward compatible)
- ✅ Dockerfile Stage 1 uses `build:only`

### Step 2: Multi-Stage Dockerfile ✅
- ✅ Rewrote Dockerfile with 3 stages (frontend build → Python deps → final)
- ✅ No Node.js in the final image (only in `frontend-build` stage)
- ✅ Frontend dist copied via `COPY --from=frontend-build` into final image
- ✅ Python deps installed in separate stage, copied via `COPY --from=python-deps`
- ✅ Final image only has runtime libs (libpq5, libodbc2, curl)
- Test that `docker compose build` produces a working image
- Verify image size reduction

### Step 3: Fix Frontend Asset Serving 🟡
- ✅ SPA fallback route exists (`catch_all()` in `vitalgraphapp_impl.py`) — correctly excludes `/api/`, `/static/`, `/docs`, `/openapi.json`
- ✅ `_setup_static_files()` mounts `StaticFiles` at `/static` in production mode
- ✅ Production mode serves UI correctly (tested)
- ✅ API routes work without conflict with catch-all
- ⬛ Still uses `Path(__file__).parent.parent.parent` traversal (should use relative path from module)
- ⬛ Mount is at `/static` but Vite outputs to `assets/` — consider aligning

### Step 4: Create docker-compose.dev.yml ❌
- ⬛ Sidecar and MinIO only (PostgreSQL runs locally) — file not yet created
- ⬛ Document dev workflow in README or a `DEVELOPMENT.md` file — not yet created

### Step 5: Complete docker-compose.yml 🟡
- ✅ MinIO included with healthcheck
- ✅ Jena sidecar included
- ✅ VitalGraph service with `env_file: .env` and restart policy
- ⬛ Add PostgreSQL service with healthcheck
- ⬛ Add `depends_on` with condition for sparql-compiler and postgres
- ⬛ Add database/sidecar env vars (or align with profile-based config: `VITALGRAPH_ENVIRONMENT`, `LOCAL_*`)
- Note: ECS deployments use RDS + S3 instead (same image, different env vars)

### Step 6: Update .dockerignore ✅
- ✅ `frontend/node_modules` ignored (already was)
- ✅ `frontend/dist/` ignored (build happens inside Docker)
- ✅ `vitalgraph/api/frontend/dist/` ignored (Docker produces its own)
- ✅ Added `planning*/`, `test_scripts/`, `debug_scripts/`, and all test dirs

### Step 7: Document Workflows ❌
- ⬛ Add `DEVELOPMENT.md` with setup instructions
- ⬛ Add deployment section to `README.md`
- ✅ `.env.example` is comprehensive (320 lines, profile-based config, client config, multi-environment docs)

---

## 6. Build Caching Strategy

### Docker Layer Caching

With the multi-stage Dockerfile, changes to different parts of the codebase
invalidate only the relevant layers:

| Change | Layers rebuilt | Time |
|---|---|---|
| Frontend source only | Stage 1 (npm build) + Stage 3 (COPY dist) | ~30s |
| Python deps only | Stage 2 (pip install) + Stage 3 | ~60s |
| Python source only | Stage 3 (COPY + pip install --no-deps) | ~15s |
| Everything | All stages | ~2–3 min |

### CI Caching

```yaml
# In GitHub Actions
- uses: docker/build-push-action@v5
  with:
    cache-from: type=gha
    cache-to: type=gha,mode=max
```

This caches each stage independently, so frontend-only PRs skip the Python
stages entirely.

---

## 7. Relationship to Other Plans

- **UI Completion Plan** (`planning_ui/ui_completion_plan.md`): This plan
  fixes the build/deploy infrastructure that the UI completion plan depends
  on. Steps 1–3 here should be done in Phase 1 of the UI plan.
- **UI Testing Plan** (`planning_ui/ui_testing_plan.md`): The
  `docker-compose.e2e.yml` defined in the testing plan builds on the
  multi-stage Dockerfile defined here. Step 2 here is a prerequisite.
- **Testing Plan** (`planning_testing/testing_plan.md`): The CI pipeline
  defined there benefits from the multi-stage Docker build for faster API
  test harness startup.
