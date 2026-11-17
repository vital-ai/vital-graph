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
ARG PG_MINOR=18.4

# THE FROM LINE ALONE DOES NOT HOLD THE PIN (issues/347). The extension packages
# were installed unversioned, and once pgvector was rebuilt for 18.7
# (0.8.7-1.pgdg13+2: Depends postgresql-18 >> 18.7) apt upgraded the SERVER inside
# this image: it ran 18.7 while saying 18.4, and the 2026-11-15 baselines were
# recorded on it. So the server packages are held, the extensions are pinned to
# builds that accept 18.4, and the build FAILS if the server is not ${PG_MINOR}.
# PostGIS 3.6.4 matches the CloudNativePG profile.
RUN set -eux; \
    apt-mark hold postgresql-18 postgresql-client-18 libpq5 postgresql-18-jit; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
       postgresql-18-pgvector=0.8.7-1.pgdg13+1 \
       postgresql-18-postgis-3=3.6.4+dfsg-2.pgdg13+1 \
       postgresql-18-postgis-3-scripts=3.6.4+dfsg-2.pgdg13+1; \
    rm -rf /var/lib/apt/lists/*; \
    have="$(postgres --version | awk '{print $3}')"; \
    [ "$have" = "${PG_MINOR}" ] || { echo "image runs PostgreSQL $have, pinned ${PG_MINOR}"; exit 1; }

# Create the required extensions on DB init (no volumes → runs every `up`).
COPY init-extensions.sql /docker-entrypoint-initdb.d/00-extensions.sql
