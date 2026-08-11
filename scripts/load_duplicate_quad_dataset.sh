#!/usr/bin/env bash
# Build and load the duplicate-anchor-quad fixture (issues/046) end to end.
#
# Kept as one script because the three steps have to agree on the space id,
# graph URI and dataset name, and a mismatch between them produces a space that
# loads cleanly and answers every frame query with zero rows (issues/041).
#
# The space is created by an explicit call here, never as a side effect of the
# load — same rule as every other space.
#
#   ./scripts/load_duplicate_quad_dataset.sh
#   VG_TEST_PG_PORT=5433 VG_TEST_PG_PASSWORD=testpass ./scripts/load_duplicate_quad_dataset.sh
set -euo pipefail

cd "$(dirname "$0")/.."

SPACE="${DUP_SPACE:-sp_lead_dup}"
GRAPH="${DUP_GRAPH:-urn:lead_dup}"
ENTITIES="${DUP_ENTITIES:-500}"
OUT_DIR="internal_data/lead_dup"
CSV="test_data/lead_dup.csv"

echo "▶ 1/4 generate ${ENTITIES} entities with duplicated anchors"
python scripts/generate_duplicate_quad_dataset.py \
    --out "$OUT_DIR" --entities "$ENTITIES"

echo "▶ 2/4 convert to slim CSV"
python scripts/convert_nt_to_csv.py "$OUT_DIR"/lead_syn_*.nt \
    --out "$CSV" --graph "$GRAPH" --dataset lead_dup

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
