# PostgreSQL 18.4 + PostGIS + pgvector + the vg_planner extension.
# Used by docker-compose.planner.yml: a SEPARATE stack (project vg-planner) for
# developing and measuring the planner extension. Nothing here changes the vg
# test stack (docker/test-pg), whose image this mirrors apart from the plugin.
#
# PINNED TO THE SAME ENGINE AS docker/test-pg AND PRODUCTION (18.4). A plan
# difference between the two stacks must be the plugin's doing, never a version
# difference, so re-pin the two together or not at all.
#
# Build context is the REPO ROOT (the image needs pg_extensions/);
# docker/planner-pg/Dockerfile.dockerignore keeps the context to what it uses.

FROM postgres:18.4 AS compiled
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential postgresql-server-dev-18 \
    && rm -rf /var/lib/apt/lists/*
COPY pg_extensions/vg_planner /src/vg_planner
WORKDIR /src/vg_planner
RUN make USE_PGXS=1 \
    && make USE_PGXS=1 install \
    && make USE_PGXS=1 install DESTDIR=/out
COPY pg_extensions/vg_planner/run_regress_in_container.sh /usr/local/bin/vgp-regress

# The regression suite runs against a throwaway cluster with the library
# preloaded, as the stack runs it. A failing suite fails the build, so an image
# that exists has passed it.
FROM compiled AS tested
RUN vgp-regress /src/vg_planner

FROM postgres:18.4
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       postgresql-18-postgis-3 \
       postgresql-18-pgvector \
    && rm -rf /var/lib/apt/lists/*
COPY --from=tested /out/ /
# Same extensions as the test stack, plus the plugin. Runs on first init only.
COPY docker/planner-pg/init-extensions.sql /docker-entrypoint-initdb.d/00-extensions.sql
