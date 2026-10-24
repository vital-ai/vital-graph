-- rendered by deploy/postgres/render_config.py from postgresql.vitalgraph.yaml; do not edit
ALTER ROLE vitalgraph_user SET statement_timeout = '60s';
ALTER DATABASE sparql_sql_graph SET lock_timeout = '10s';
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_prewarm;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS vg_planner;
