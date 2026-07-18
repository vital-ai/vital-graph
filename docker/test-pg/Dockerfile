# PostgreSQL 18 with PostGIS and pgvector extensions
# Used by docker-compose.test.yml for the ephemeral test database.
#
# Pinned to the PostgreSQL major available on AWS RDS (18.x; RDS latest minor
# 18.4 as of 2026-07) so tests run on the same version as production — plan
# shapes reflect PG 18 features (async I/O, skip-scan, UUIDv7, improved
# partition-pruning cost model). Re-pin when RDS advances (e.g. PG 19 GA).
FROM postgres:18

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-18-postgis-3 \
       postgresql-18-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Create the required extensions on DB init (no volumes → runs every `up`).
COPY init-extensions.sql /docker-entrypoint-initdb.d/00-extensions.sql
