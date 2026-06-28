-- PostgreSQL init script for the sparql_sql backend
-- Runs automatically on first container start via docker-entrypoint-initdb.d

-- Required extension for REGEX performance (GIN trigram indexes)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Admin tables (shared schema with fuseki_postgresql)
CREATE TABLE IF NOT EXISTS install (
    id SERIAL PRIMARY KEY,
    install_datetime TIMESTAMP,
    update_datetime TIMESTAMP,
    active BOOLEAN
);

CREATE TABLE IF NOT EXISTS space (
    space_id VARCHAR(255) PRIMARY KEY,
    space_name VARCHAR(255),
    space_description TEXT,
    tenant VARCHAR(255),
    update_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph (
    graph_id SERIAL PRIMARY KEY,
    space_id VARCHAR(255) NOT NULL,
    graph_uri VARCHAR(500),
    graph_name VARCHAR(255),
    created_time TIMESTAMP,
    FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "user" (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255),
    email VARCHAR(255),
    tenant VARCHAR(255),
    update_time TIMESTAMP
);

-- Import/export job tracking
CREATE TABLE IF NOT EXISTS import_export_job (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type        TEXT NOT NULL CHECK (job_type IN ('import', 'export')),
    space_id        VARCHAR(255) NOT NULL REFERENCES space(space_id) ON DELETE CASCADE,
    graph_uri       TEXT,
    status          TEXT NOT NULL DEFAULT 'created'
                    CHECK (status IN ('created','pending','running','completed','failed','cancelled')),
    mode            TEXT NOT NULL DEFAULT 'append'
                    CHECK (mode IN ('append', 'replace')),
    progress_pct    REAL NOT NULL DEFAULT 0,
    records_done    BIGINT NOT NULL DEFAULT 0,
    records_total   BIGINT,
    file_s3_key     TEXT,
    file_name       TEXT,
    file_size       BIGINT,
    file_format     TEXT,
    config          JSONB,
    checkpoint_offset BIGINT DEFAULT 0,
    checkpoint_batch  INT DEFAULT 0,
    error_message   TEXT,
    log_entries     JSONB DEFAULT '[]'::jsonb,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Admin indexes
CREATE INDEX IF NOT EXISTS idx_space_tenant ON space(tenant);
CREATE INDEX IF NOT EXISTS idx_space_update_time ON space(update_time);
CREATE INDEX IF NOT EXISTS idx_graph_space_id ON graph(space_id);
CREATE INDEX IF NOT EXISTS idx_graph_uri ON graph(graph_uri);
CREATE INDEX IF NOT EXISTS idx_user_tenant ON "user"(tenant);
CREATE INDEX IF NOT EXISTS idx_user_username ON "user"(username);
CREATE INDEX IF NOT EXISTS idx_iej_space_status ON import_export_job(space_id, status);
CREATE INDEX IF NOT EXISTS idx_iej_created ON import_export_job(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_iej_type_status ON import_export_job(job_type, status);

-- Seed install record
INSERT INTO install (install_datetime, update_datetime, active)
VALUES (NOW(), NOW(), true)
ON CONFLICT DO NOTHING;
