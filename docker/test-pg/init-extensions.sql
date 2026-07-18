-- Extensions the VitalGraph schema requires, created on DB init.
-- The vg-test container has no volumes, so this runs on every `up` (clean DB).
-- Without this the app's init would create them; the perf/integration runner
-- starts only postgres+sidecar (no app), so the image self-provisions them.
CREATE EXTENSION IF NOT EXISTS postgis;   -- geography/geometry types (geo tables)
CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector (embedding columns)
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram GIN on term_text
