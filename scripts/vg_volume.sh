#!/usr/bin/env bash
# vg_volume.sh — PostgreSQL data volumes for the vg test and vg planner stacks.
#
# Each dataset lives in its own NAMED volume (vgtest_core, vgdata_lead100k, ...).
# A volume that is not needed right now is kept as a compressed snapshot of the
# stopped cluster's data directory (tar + zstd): restoring one is an untar, minutes,
# where reloading the dataset re-runs COPY, index builds, ANALYZE and resync (up to
# an hour for the 74M-quad lead space).
#
#   vg_volume.sh show                          what each stack is on; the dataset volumes
#   vg_volume.sh switch test|planner <volume> [--build] [--new]
#                                              clean-stop the stack, start it on <volume>;
#                                              a missing volume is restored from
#                                              $VG_SNAPSHOT_DIR/<volume>.tar.zst if present
#   vg_volume.sh stop test|planner             clean stop (stop -t 300), keeps the volume
#   vg_volume.sh snapshot <volume> [file]      volume -> <file>.tar.zst (+ .json sidecar)
#   vg_volume.sh restore <file> <volume>       snapshot -> NEW volume <volume>
#   vg_volume.sh verify <volume> <volume>      byte-compare two volumes (every file)
#
# Snapshots default to $VG_SNAPSHOT_DIR or ~/vg-snapshots; the archive copy lives on
# Google Drive (see planning/planning_test_data/). A snapshot is only restorable into
# the SAME PostgreSQL major (18) and architecture, with the same extensions available;
# the sidecar records the cluster's PG_VERSION and the image ids it was taken with.
#
# Rules this script enforces:
#   - never `down -v`, never removes a volume;
#   - only one of the two stacks runs at a time (switch refuses if the other is up);
#   - a snapshot is taken only of a volume no running container mounts, whose
#     cluster was shut down cleanly (pg_controldata: "shut down");
#   - restore refuses an existing volume; switch refuses a volume that does not
#     exist (it would come up as an EMPTY cluster) unless --new is given.
set -euo pipefail
cd "$(dirname "$0")/.."

SNAPDIR="${VG_SNAPSHOT_DIR:-$HOME/vg-snapshots}"
PGIMAGE_TEST=vg-test-postgres
PGIMAGE_PLANNER=vg-planner-postgres

die() { echo "vg_volume: $*" >&2; exit 1; }

stack_files() {
  case "$1" in
    test)    echo "-f docker-compose.test.yml -f docker-compose.test.persist.yml" ;;
    planner) echo "-f docker-compose.planner.yml -f docker-compose.planner.persist.yml --profile app" ;;
    *) die "stack must be 'test' or 'planner'" ;;
  esac
}
stack_pg()      { [ "$1" = test ] && echo vitalgraph-test-pg || echo vitalgraph-planner-pg; }
stack_prefix()  { [ "$1" = test ] && echo vitalgraph-test- || echo vitalgraph-planner-; }
stack_envvar()  { [ "$1" = test ] && echo VGTEST_PGDATA || echo VGPLANNER_PGDATA; }
other_stack()   { [ "$1" = test ] && echo planner || echo test; }

mounted_volume() {   # volume behind a stack's PG container (running or not)
  docker inspect "$(stack_pg "$1")" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true
}
stack_running() { [ -n "$(docker ps -q --filter "name=^$(stack_prefix "$1")")" ]; }
vol_exists()    { docker volume inspect "$1" >/dev/null 2>&1; }
vol_in_use()    { [ -n "$(docker ps -q --filter "volume=$1")" ]; }

cluster_state() {    # pg_controldata of a stopped volume, without starting a server
  docker run --rm -m 256m --entrypoint '' -u postgres -v "$1":/var/lib/postgresql:ro \
    "$PGIMAGE_TEST" sh -c 'pg_controldata /var/lib/postgresql/18/docker' 2>/dev/null \
    | sed -n 's/^Database cluster state: *//p'
}

cmd_show() {
  for s in test planner; do
    local st="stopped"; stack_running "$s" && st="RUNNING"
    echo "$s: $st on volume '$(mounted_volume "$s")'"
  done
  echo "dataset volumes:"
  docker volume ls --format '{{.Name}}' | grep -E '^(vgtest_|vgdata_|vgplanner_)' | sed 's/^/  /' || true
  echo "snapshots in $SNAPDIR:"
  ls -l "$SNAPDIR"/*.tar.zst 2>/dev/null | awk '{printf "  %8.1f GB  %s\n", $5/1e9, $NF}' || true
}

cmd_stop() {
  local s="$1"
  # stop's default 10 s ends in SIGKILL before PostgreSQL's shutdown checkpoint; the
  # next start then spends ~30 s in crash recovery, and a snapshot would not be clean.
  # shellcheck disable=SC2046
  docker compose $(stack_files "$s") stop -t 300 >/dev/null
  echo "$s stack stopped (volume '$(mounted_volume "$s")' kept)"
}

cmd_switch() {
  local s="$1" vol="$2"; shift 2
  local build="" new=false
  for a in "$@"; do case "$a" in --build) build=--build ;; --new) new=true ;; *) die "unknown flag $a" ;; esac; done
  stack_running "$(other_stack "$s")" && die "the $(other_stack "$s") stack is running; stop it first (one stack at a time)"
  if ! vol_exists "$vol" && ! $new; then
    if [ -f "$SNAPDIR/$vol.tar.zst" ]; then
      echo "volume '$vol' absent; restoring it from $SNAPDIR/$vol.tar.zst"
      cmd_restore "$SNAPDIR/$vol.tar.zst" "$vol"
    else
      die "volume '$vol' does not exist (it would start EMPTY) and there is no $SNAPDIR/$vol.tar.zst; copy the snapshot from Drive, or pass --new for an empty cluster"
    fi
  fi
  local files; files="$(stack_files "$s")"
  # shellcheck disable=SC2086
  docker compose $files stop -t 300 >/dev/null 2>&1 || true
  local var; var="$(stack_envvar "$s")"
  # shellcheck disable=SC2086
  env "$var=$vol" docker compose $files up -d $build postgres >/dev/null
  local pg; pg="$(stack_pg "$s")"
  for _ in $(seq 1 300); do
    docker exec "$pg" psql -U postgres -d sparql_sql_graph -Atc "select 1" >/dev/null 2>&1 && break
    sleep 2
  done
  local n; n="$(docker exec "$pg" psql -U postgres -d sparql_sql_graph -Atc "select count(*) from space" 2>/dev/null || echo '?')"
  # shellcheck disable=SC2086
  env "$var=$vol" docker compose $files up -d $build --wait >/dev/null
  echo "$s stack now on volume '$vol' ($n spaces)"
  [ "$(mounted_volume "$s")" = "$vol" ] || die "container mounted '$(mounted_volume "$s")', expected '$vol'"
}

cmd_snapshot() {
  local vol="$1" out="${2:-$SNAPDIR/$1.tar.zst}"
  vol_exists "$vol" || die "no volume '$vol'"
  vol_in_use "$vol" && die "volume '$vol' is mounted by a running container; stop the stack first"
  [ -e "$out" ] && die "$out exists"
  local state; state="$(cluster_state "$vol")"
  [ "$state" = "shut down" ] || die "cluster in '$vol' is '$state', not 'shut down'; start and cleanly stop it first"
  mkdir -p "$(dirname "$out")"
  local t0; t0=$(date +%s)
  docker run --rm -m 256m -v "$vol":/v:ro busybox tar -C /v -cf - . | zstd -q -T0 -10 -o "$out.partial"
  mv "$out.partial" "$out"
  local secs=$(( $(date +%s) - t0 ))
  local pgv; pgv="$(docker run --rm -m 128m -v "$vol":/v:ro busybox cat /v/18/docker/PG_VERSION)"
  local bytes; bytes="$(docker run --rm -m 128m -v "$vol":/v:ro busybox du -sb /v | cut -f1)"
  local sha; sha="$(shasum -a 256 "$out" | cut -d' ' -f1)"
  cat > "$out.json" <<EOF
{
  "volume": "$vol",
  "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pg_version": "$pgv",
  "cluster_state": "$state",
  "uncompressed_bytes": $bytes,
  "file_bytes": $(stat -f %z "$out"),
  "sha256": "$sha",
  "snapshot_seconds": $secs,
  "image_test_postgres": "$(docker image inspect $PGIMAGE_TEST --format '{{.Id}}' 2>/dev/null)",
  "image_planner_postgres": "$(docker image inspect $PGIMAGE_PLANNER --format '{{.Id}}' 2>/dev/null)",
  "repo_commit": "$(git rev-parse --short HEAD)"
}
EOF
  echo "snapshot $out ($(stat -f %z "$out") bytes, ${secs}s)"
}

cmd_restore() {
  local f="$1" vol="$2"
  [ -f "$f" ] || die "no file $f"
  vol_exists "$vol" && die "volume '$vol' already exists; restore into a new name"
  if [ -f "$f.json" ]; then
    local want; want="$(sed -n 's/.*"sha256": "\([0-9a-f]*\)".*/\1/p' "$f.json")"
    [ -z "$want" ] || [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "$want" ] || die "sha256 of $f does not match its sidecar"
    # The Docker VM's disk is a fixed size (Docker Desktop -> Resources), separate
    # from the Mac's free space; a restore that overruns it fails half-written.
    local need free
    need="$(sed -n 's/.*"uncompressed_bytes": \([0-9]*\).*/\1/p' "$f.json")"
    free="$(docker run --rm -m 128m -v /var/lib/docker:/d:ro busybox df -k /d | awk 'NR==2{print $4*1024}')"
    if [ -n "$need" ] && [ -n "$free" ] && [ "$need" -gt $(( free - 10*1024*1024*1024 )) ]; then
      die "restore needs $(( need/1024/1024/1024 )) GB; the Docker VM disk has $(( free/1024/1024/1024 )) GB free (keeping 10 GB headroom)"
    fi
  fi
  local t0; t0=$(date +%s)
  docker volume create "$vol" >/dev/null
  zstd -dc -q "$f" | docker run -i --rm -m 256m -v "$vol":/v busybox tar -C /v -xf -
  echo "restored $f -> volume '$vol' in $(( $(date +%s) - t0 ))s; cluster state: $(cluster_state "$vol")"
}

cmd_verify() {
  local a="$1" b="$2" sa sb
  for v in "$a" "$b"; do vol_exists "$v" || die "no volume '$v'"; done
  local sum='cd /v && find . -type f | sort | xargs md5sum | md5sum'
  sa="$(docker run --rm -m 256m -v "$a":/v:ro busybox sh -c "$sum")"
  sb="$(docker run --rm -m 256m -v "$b":/v:ro busybox sh -c "$sum")"
  [ "$sa" = "$sb" ] && echo "identical: $a == $b" || die "DIFFERENT: $a ($sa) vs $b ($sb)"
}

case "${1:-show}" in
  show)     cmd_show ;;
  stop)     [ $# -eq 2 ] || die "usage: stop test|planner"; cmd_stop "$2" ;;
  switch)   [ $# -ge 3 ] || die "usage: switch test|planner <volume> [--build] [--new]"; shift; cmd_switch "$@" ;;
  snapshot) [ $# -ge 2 ] || die "usage: snapshot <volume> [file]"; cmd_snapshot "$2" "${3:-}" ;;
  restore)  [ $# -eq 3 ] || die "usage: restore <file> <volume>"; cmd_restore "$2" "$3" ;;
  verify)   [ $# -eq 3 ] || die "usage: verify <volume> <volume>"; cmd_verify "$2" "$3" ;;
  *) die "unknown command '$1' (show|switch|stop|snapshot|restore|verify)" ;;
esac
