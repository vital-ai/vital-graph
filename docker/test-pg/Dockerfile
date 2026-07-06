# PostgreSQL 17 with PostGIS and pgvector extensions
# Used by docker-compose.test.yml for the ephemeral test database
FROM postgres:17

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-17-postgis-3 \
       postgresql-17-pgvector \
    && rm -rf /var/lib/apt/lists/*
