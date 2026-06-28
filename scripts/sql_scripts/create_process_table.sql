-- Migration: Add global process tracking table
-- Run this manually on existing sparql_sql databases that were initialized
-- before the process table was added to the init path.
--
-- Safe to re-run (uses IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS process (
    process_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process_type     VARCHAR(64) NOT NULL,
    process_subtype  VARCHAR(128),
    status           VARCHAR(32) NOT NULL DEFAULT 'pending',
    instance_id      VARCHAR(128),
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    progress_percent REAL DEFAULT 0.0,
    progress_message TEXT,
    error_message    TEXT,
    result_details   JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_process_type_status ON process (process_type, status);
CREATE INDEX IF NOT EXISTS idx_process_created ON process (created_at DESC);
