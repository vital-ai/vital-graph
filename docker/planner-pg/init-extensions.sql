-- Extensions created on first init (an empty data directory).
-- The first three match docker/test-pg/init-extensions.sql; vg_planner is the
-- plugin (its library is preloaded by docker-compose.planner.yml's command).
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vg_planner;
