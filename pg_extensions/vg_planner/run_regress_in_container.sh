#!/bin/sh
# Run the pg_regress suite against a throwaway cluster with vg_planner
# preloaded, as the planner stack runs it. Used by the image build (a failing
# suite fails the build) and by pg_extensions/vg_planner/regress.sh for the dev
# loop, where the source directory is bind-mounted so results land on the host.
set -e
SRC="${1:-/src/vg_planner}"
chown -R postgres "$SRC"
exec su postgres -c "
  set -e
  initdb -D /tmp/pgdata >/dev/null
  pg_ctl -D /tmp/pgdata -l /tmp/pg.log -w \
    -o '-c shared_preload_libraries=vg_planner -c listen_addresses=' start >/dev/null
  cd '$SRC'
  rc=0
  make -s USE_PGXS=1 installcheck PGHOST=/var/run/postgresql || rc=\$?
  pg_ctl -D /tmp/pgdata -w stop >/dev/null
  if [ \$rc -ne 0 ]; then cat test/regression.diffs 2>/dev/null || true; fi
  exit \$rc"
