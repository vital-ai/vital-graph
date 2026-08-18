#!/usr/bin/env bash
# Build and load the all-datatypes fixture (issues/053) end to end.
#
# This is the fixture every comparator assertion runs against: it carries each
# slot datatype with a graded, exactly-tallied distribution, so `gte` on an
# integer slot has an expected NUMBER rather than "more than zero". Without it
# tests/performance/test_comparator_coverage.py skips all 26 cases.
#
# It has gone missing once already, and the skip is silent — which is how the
# `gt` cast defect (issues/053) survived a green run. Hence a script: rebuilding
# it should be one command, not an afternoon of reconstructing arguments.
#
# Generation is skipped when the .nt is already present, because it is the slow
# step and the manifest beside it is the ground truth for every assertion —
# regenerating with a different seed would silently invalidate the counts.
# Pass --regenerate to force it.
#
#   ./scripts/load_lead_types_dataset.sh
#   ./scripts/load_lead_types_dataset.sh --regenerate
set -euo pipefail

cd "$(dirname "$0")/.."

# Default to the cluster tests/performance/conftest.py reads, NOT the one
# perf_seed_data.py writes to. Those two disagree — seeding defaults to port
# 5433 and the tests to 5432 — so a fixture built with plain defaults lands in
# a cluster the tests that need it never look in. That is not hypothetical:
# sp_lead_types was built into 5433, every comparator case skipped against
# 5432, and the skip is silent, so a `gt` that timed out at 60s looked green
# (issues/053). Override these for the container stack.
export VG_TEST_PG_HOST="${VG_TEST_PG_HOST:-localhost}"
# Defaults to 5433, the docker test stack, matching every Python entry
# point (`vitalgraph_sparql_sql_dev.db`) and all three test conftests.
# It defaulted to 5432 and this script REPORTED SUCCESS while loading the
# host cluster, where nothing reads it — the perf suite then skipped its
# five relation benches saying "sp_kg_rel not loaded" (issues/055).
export VG_TEST_PG_PORT="${VG_TEST_PG_PORT:-5433}"
export VG_TEST_PG_DATABASE="${VG_TEST_PG_DATABASE:-sparql_sql_graph}"
export VG_TEST_PG_USER="${VG_TEST_PG_USER:-postgres}"
# testpass, because the port above now defaults to the docker stack and
# an empty password is refused there. The two defaults have to move
# together or the script trades a silent wrong target for a hard failure.
export VG_TEST_PG_PASSWORD="${VG_TEST_PG_PASSWORD-testpass}"

SPACE="${TYPES_SPACE:-sp_lead_types}"
GRAPH="${TYPES_GRAPH:-urn:lead_types}"
ENTITIES="${TYPES_ENTITIES:-2000}"
OUT_DIR="internal_data/lead_types"
CSV="test_data/lead_types.csv"

if [[ "${1:-}" == "--regenerate" ]] || ! compgen -G "$OUT_DIR"/lead_syn_*.nt > /dev/null; then
    echo "▶ 1/4 generate ${ENTITIES} entities across every slot datatype"
    python scripts/generate_lead_dataset.py --out "$OUT_DIR" --entities "$ENTITIES"
else
    echo "▶ 1/4 reusing $OUT_DIR (pass --regenerate to rebuild)"
fi

echo "▶ 2/4 convert to slim CSV"
python scripts/convert_nt_to_csv.py "$OUT_DIR"/lead_syn_*.nt \
    --out "$CSV" --graph "$GRAPH" --dataset lead_types

echo "▶ 3/4 create space $SPACE"
python - "$SPACE" <<'PY'
import asyncio, os, sys
sys.path.insert(0, os.getcwd())
from scripts.perf_seed_data import ensure_space, pg_params  # noqa: E402

space_id = sys.argv[1]
params = pg_params()
asyncio.run(ensure_space(space_id, params))
print(f"   space {space_id} ready")
PY

# Register the graph the data is loaded under. ensure_space creates the space
# and tables; loading quads with a context puts the data IN a graph; neither
# REGISTERS one. Until this was added every generated fixture had data and no
# `graph` row, so none was reachable through the API (issues/061).
python - "$SPACE" "$GRAPH" <<'PY2'
import asyncio, os, sys
sys.path.insert(0, os.getcwd())
from scripts.perf_seed_data import ensure_graph, pg_params  # noqa: E402
asyncio.run(ensure_graph(sys.argv[1], sys.argv[2], pg_params()))
PY2

echo "▶ 4/4 bulk load"
python scripts/load_wordnet_csv.py --space "$SPACE" \
    --quads-csv "$CSV" --terms-csv "${CSV%.csv}_terms.csv"

echo "✅ $SPACE loaded from $GRAPH"
