#!/usr/bin/env bash
# Derive the tenant-specific identifiers from the restored space itself and run
# the probe, so none of them are written into the repo.
set -euo pipefail

cd "$(dirname "$0")/.."

DB="${PROBE_DB:-$(psql -U hadfield -d postgres -tAc \
  "SELECT datname FROM pg_database WHERE datname LIKE '%\\_kg\\_local' LIMIT 1")}"
DB="${DB// /}"
[ -n "$DB" ] || { echo "no restored space database found" >&2; exit 1; }

SPACE="${DB%_local}"
Q="${SPACE}_rdf_quad"
T="${SPACE}_term"

term() {  # exact-ish lookup of a single term by suffix
  psql -U hadfield -d "$DB" -tAc \
    "SELECT term_text FROM $T WHERE term_text LIKE '$1' LIMIT 1" | tr -d ' '
}

export PROBE_DSN="postgresql://hadfield@localhost:5432/$DB"
export PROBE_SPACE="$SPACE"
export PROBE_GRAPH="$(psql -U hadfield -d "$DB" -tAc \
  "SELECT term_text FROM $T WHERE term_uuid = (SELECT context_uuid FROM $Q LIMIT 1)" | tr -d ' ')"
export PROBE_ENTITY_TYPE="${PROBE_ENTITY_TYPE:-$(term '%:kg:entity:NurtureAction')}"
export PROBE_FRAME_TYPE="$(term '%:kg:frame:NurtureActionInfoFrame')"
export PROBE_SLOT_TYPE="$(term '%:kg:slot:NurtureCampaignURI')"
export PROBE_SLOT_VALUE="$(term '%:campaign:nurture_lead')"
export PROBE_SIDECAR="${PROBE_SIDECAR:-${VG_TEST_SIDECAR_URL:-http://localhost:7071}}"

for v in PROBE_GRAPH PROBE_ENTITY_TYPE PROBE_FRAME_TYPE PROBE_SLOT_TYPE PROBE_SLOT_VALUE; do
  [ -n "${!v}" ] || { echo "$v not found in $DB" >&2; exit 1; }
done

exec python scripts/probe_semijoin_entity_query.py "$@"
