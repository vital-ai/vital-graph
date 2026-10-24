#!/bin/sh
# Render the canonical PostgreSQL configuration (deploy/postgres) into every
# overlay at the size its `# SIZE:` line states, and the bootstrap SQL into base.
#   render_all.sh          write
#   render_all.sh --check  fail if any overlay or the bootstrap SQL differs (CI)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
R="$HERE/../postgres/render_config.py"
mode="--write"; [ "$1" = "--check" ] && mode="--check"
rc=0
for f in "$HERE"/manifests/overlays/*/cluster-size.yaml; do
  size="$(sed -n 's/^# SIZE: //p' "$f")"
  mem="$(echo "$size" | sed -n 's/.*mem_mb=\([0-9]*\).*/\1/p')"
  cpu="$(echo "$size" | sed -n 's/.*vcpu=\([0-9]*\).*/\1/p')"
  [ -n "$mem" ] && [ -n "$cpu" ] || { echo "$f: no '# SIZE: mem_mb=N vcpu=N' line"; exit 1; }
  "$PY" "$R" --mem-mb "$mem" --vcpu "$cpu" --format cnpg "$mode" "$f" || rc=1
done
sql="$HERE/manifests/base/bootstrap.sql"
if [ "$mode" = "--check" ]; then
  "$PY" "$R" --mem-mb 1 --vcpu 1 --format sql | cmp -s - "$sql" \
    && echo "$sql: matches the canonical configuration" \
    || { echo "$sql: differs from the canonical configuration"; rc=1; }
else
  "$PY" "$R" --mem-mb 1 --vcpu 1 --format sql > "$sql"; echo "$sql: written"
fi
exit $rc
