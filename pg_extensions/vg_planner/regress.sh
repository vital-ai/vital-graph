#!/bin/sh
# Dev loop: compile in the image's build stage, then run the regression suite
# with this directory bind-mounted, so test/results/*.out land here.
#   pg_extensions/vg_planner/regress.sh            run the suite
#   pg_extensions/vg_planner/regress.sh --accept   copy results over expected
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
docker build -q -f "$ROOT/docker/planner-pg/Dockerfile" --target compiled \
  -t vg-planner-compiled:dev "$ROOT" >/dev/null
rc=0
docker run --rm -v "$HERE:/src/vg_planner" vg-planner-compiled:dev \
  vgp-regress /src/vg_planner || rc=$?
if [ "$1" = "--accept" ]; then
  for f in "$HERE"/test/results/*.out; do cp "$f" "$HERE/test/expected/"; done
  echo "accepted: $(ls "$HERE"/test/results/*.out | xargs -n1 basename | tr '\n' ' ')"
  exit 0
fi
exit $rc
