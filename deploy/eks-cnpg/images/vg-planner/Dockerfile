# The vg_planner extension as a CloudNativePG IMAGE VOLUME extension
# (PostgreSQL 18 extension_control_path / dynamic_library_path).
#
# The image holds only:
#     /lib/vg_planner.so
#     /share/extension/vg_planner.control, vg_planner--*.sql
# and is mounted read-only at /extensions/vg-planner in each PostgreSQL pod.
#
# BUILT AGAINST THE OPERAND IMAGE ITSELF. CloudNativePG requires an extension
# image to match the cluster's PostgreSQL major version, OS distribution and
# CPU architecture, and vg_planner is pinned to a MINOR (src/pg18_joinsearch.c
# is generated from REL_18_4): so the build stage IS the operand image, and its
# server-dev package is pinned to the server's exact package version. A base
# image whose PostgreSQL is not 18.4 fails the build here.
#
# The regression suite (inert, core-equivalence, advice) runs against a
# throwaway cluster in that same image; a failing suite fails the build.
#
# Build context is the REPO ROOT:
#   docker build -f deploy/eks-cnpg/images/vg-planner/Dockerfile \
#     --build-arg BASE=ghcr.io/cloudnative-pg/postgresql:18.4-minimal-trixie \
#     -t vg-planner-ext:0.2.0-18.4-trixie .

ARG BASE=ghcr.io/cloudnative-pg/postgresql:18.4-minimal-trixie
ARG PG_MINOR=18.4

FROM ${BASE} AS compiled
ARG PG_MINOR
USER root
RUN set -eux; \
    have="$(pg_config --version | awk '{print $2}')"; \
    [ "$have" = "${PG_MINOR}" ] || { echo "base image is PostgreSQL $have, vg_planner is built for ${PG_MINOR}"; exit 1; }; \
    v="$(dpkg-query -W -f='${Version}' postgresql-18)"; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential "postgresql-server-dev-18=$v"; \
    rm -rf /var/lib/apt/lists/*
COPY pg_extensions/vg_planner /src/vg_planner
WORKDIR /src/vg_planner
RUN make USE_PGXS=1 clean \
    && make USE_PGXS=1 \
    && make USE_PGXS=1 install \
    && make USE_PGXS=1 install DESTDIR=/out
COPY pg_extensions/vg_planner/run_regress_in_container.sh /usr/local/bin/vgp-regress

FROM compiled AS tested
RUN PATH="/usr/lib/postgresql/18/bin:$PATH" vgp-regress /src/vg_planner > /tmp/regress.log 2>&1 \
    || { cat /tmp/regress.log; exit 1; }; cat /tmp/regress.log

# The image-volume layout, with a manifest of what was built and tested.
FROM compiled AS layout
COPY --from=tested /tmp/regress.log /tmp/regress.log
RUN set -eux; \
    mkdir -p /image/lib /image/share/extension; \
    cp "/out$(pg_config --pkglibdir)/vg_planner.so" /image/lib/; \
    cp "/out$(pg_config --sharedir)/extension/"vg_planner* /image/share/extension/; \
    { echo "postgresql=$(pg_config --version)"; \
      echo "package=$(dpkg-query -W -f='${Version}' postgresql-18)"; \
      echo "arch=$(dpkg --print-architecture)"; \
      echo "vg_planner.so.sha256=$(sha256sum /image/lib/vg_planner.so | cut -d' ' -f1)"; \
      echo "regression=$(grep -E 'tests? passed|failed' /tmp/regress.log | tail -1 | sed 's/^# //')"; } > /image/BUILD-INFO; \
    cat /image/BUILD-INFO

FROM scratch
COPY --from=layout /image/ /
LABEL org.opencontainers.image.title="vg_planner" \
      org.opencontainers.image.description="VitalGraph planner extension for PostgreSQL 18.4 (CloudNativePG image volume)"
