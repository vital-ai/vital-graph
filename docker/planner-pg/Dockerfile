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
ARG PG_MINOR=18.4
# The headers must be the SERVER'S OWN version: vg_planner's pg18_joinsearch.c is
# REL_18_4's join search, and an unpinned server-dev package also pulled the
# server forward to 18.7 (issues/347). Same pattern as
# deploy/eks-cnpg/images/vg-planner/Dockerfile.
RUN set -eux; \
    apt-mark hold postgresql-18 postgresql-client-18 libpq5 postgresql-18-jit; \
    v="$(dpkg-query -W -f='${Version}' postgresql-18)"; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential "postgresql-server-dev-18=$v" "libpq-dev=$v"; \
    rm -rf /var/lib/apt/lists/*; \
    have="$(pg_config --version | awk '{print $2}')"; \
    [ "$have" = "${PG_MINOR}" ] || { echo "building against PostgreSQL $have, pinned ${PG_MINOR}"; exit 1; }
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
COPY --from=tested /out/ /
# Same extensions as the test stack, plus the plugin. Runs on first init only.
COPY docker/planner-pg/init-extensions.sql /docker-entrypoint-initdb.d/00-extensions.sql
