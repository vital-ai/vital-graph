#!/usr/bin/env bash
# Build and load the KG-relation fixture (issues/061) end to end.
#
# This is the only fixture with relation edges. Every other one is tree-shaped:
# sp_lead_synth_100k has the three containment edge types and wordnet_frames has
# only Edge_hasKGSlot, so neither can refute a traversal rule that is wrong for
# relations — where an entity may be source OR destination in many, and no
# direction is safe.
#
# It also carries both frame form types, including assertion frames that leave
# hasKGFormType UNSET, since unset defaults to assertion and a fixture that
# always states it cannot catch a reader that requires the explicit triple.
#
# Defaults target the cluster tests/performance/conftest.py reads, NOT the one
# perf_seed_data.py writes to — those disagree, and a fixture built with plain
# defaults lands where the tests never look (issues/055).
set -euo pipefail

cd "$(dirname "$0")/.."

export VG_TEST_PG_HOST="${VG_TEST_PG_HOST:-localhost}"
export VG_TEST_PG_PORT="${VG_TEST_PG_PORT:-5432}"
export VG_TEST_PG_DATABASE="${VG_TEST_PG_DATABASE:-sparql_sql_graph}"
export VG_TEST_PG_USER="${VG_TEST_PG_USER:-postgres}"
export VG_TEST_PG_PASSWORD="${VG_TEST_PG_PASSWORD-}"

SPACE="${REL_SPACE:-sp_kg_rel}"
GRAPH="${REL_GRAPH:-urn:sp_kg_rel}"
ENTITIES="${REL_ENTITIES:-5000}"
OUT_DIR="internal_data/kg_rel"
CSV="test_data/kg_rel.csv"

if [[ "${1:-}" == "--regenerate" ]] || ! compgen -G "$OUT_DIR"/kg_rel_*.nt > /dev/null; then
    echo "▶ 1/4 generate ${ENTITIES} entities with relations and both form types"
    python scripts/generate_relation_dataset.py --out "$OUT_DIR" --entities "$ENTITIES"
else
    echo "▶ 1/4 reusing $OUT_DIR (pass --regenerate to rebuild)"
fi

echo "▶ 2/4 convert to slim CSV"
python scripts/convert_nt_to_csv.py "$OUT_DIR"/kg_rel_*.nt \
    --out "$CSV" --graph "$GRAPH" --dataset kg_rel

echo "▶ 3/4 create space $SPACE"
python - "$SPACE" <<'PY'
import asyncio, os, sys
sys.path.insert(0, os.getcwd())
from scripts.perf_seed_data import ensure_space, pg_params  # noqa: E402

space_id = sys.argv[1]
asyncio.run(ensure_space(space_id, pg_params()))
print(f"   space {space_id} ready")
PY

echo "▶ 4/4 bulk load"
python scripts/load_wordnet_csv.py --space "$SPACE" \
    --quads-csv "$CSV" --terms-csv "${CSV%.csv}_terms.csv"

echo "✅ $SPACE loaded from $GRAPH"
