# PostgreSQL 18 with PostGIS and pgvector extensions
# Used by docker-compose.test.yml for the ephemeral test database.
#
# Pinned to the PostgreSQL version available on AWS RDS (RDS latest minor 18.4
# as of 2026-07) so tests run on the same version as production — plan shapes
# reflect PG 18 features (async I/O, skip-scan, UUIDv7, improved
# partition-pruning cost model).
#
# THE MINOR IS PINNED, NOT JUST THE MAJOR. This said `postgres:18`, which floats:
# rebuilding the image on 2026-09-04 silently moved the test database from 18.4
# to 18.6, and `perf_compare` correctly refused the run —
#
#     environment differs — pg.server_version:
#       baseline='18.4 (Debian 18.4-1.pgdg13+1)' run='18.6 (Debian 18.6-1.pgdg13+2)'
#
# A performance baseline is a claim about a specific engine. With a floating tag
# the reference environment cannot be reproduced on demand, so the committed
# baseline decays into something no run can be compared against — the tier stops
# gating without ever reporting that it stopped.
#
# Re-pin DELIBERATELY when RDS advances (and when the major moves, e.g. PG 19
# GA), and re-record the baselines on the new pin in the same change. Bumping
# this line without re-recording invalidates every comparison that follows it.
FROM postgres:18.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-18-postgis-3 \
       postgresql-18-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Create the required extensions on DB init (no volumes → runs every `up`).
COPY init-extensions.sql /docker-entrypoint-initdb.d/00-extensions.sql
