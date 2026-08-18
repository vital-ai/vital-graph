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

# The PRIMARY KEY has to go, and only for this space.
#
# `rdf_quad` gained a PK on (subject, predicate, object, context) —
# `scripts/migrate_quad_pk_dedup.py` — and this fixture's whole content is rows
# that key forbids: 200 deliberately duplicated anchor quads. With the PK in
# place the COPY dies on line 94 and the space is left empty, so the two benches
# that read it skip, and skipping reads as green (issues/104).
#
# A pre-PK space is exactly what this fixture models, the same way
# `test_migrate_nonpartitioned_space_preserves_data` drops the constraint to
# model the space that migration exists to convert. It is dropped rather than
# never created because `ensure_space` builds the current schema, and a fixture
# that quietly used a different table definition would be worse than one that
# visibly removes a constraint.
#
# It is NOT restored afterwards. Re-adding it would fail on the very rows this
# fixture exists to hold, and would delete them if it succeeded — which is what
# happened on the host cluster, where sp_lead_dup holds 252,850 quads and ZERO
# duplicate groups, its purpose silently migrated away.
echo "▶ 4/5 drop the quad primary key (this fixture stores duplicates BY DESIGN)"
python - "$SPACE" <<'PY3'
import asyncio, os, sys
sys.path.insert(0, os.getcwd())
import asyncpg
from scripts.perf_seed_data import pg_params  # noqa: E402

async def main(space_id):
    conn = await asyncpg.connect(**pg_params())
    try:
        name = await conn.fetchval(
            "SELECT conname FROM pg_constraint c JOIN pg_class r "
            "ON r.oid = c.conrelid WHERE r.relname = $1 AND c.contype = 'p'",
            f"{space_id}_rdf_quad")
        if name:
            await conn.execute(
                f'ALTER TABLE {space_id}_rdf_quad DROP CONSTRAINT "{name}"')
            print(f"   dropped {name}")
        else:
            print("   no primary key present — already a pre-PK space")
    finally:
        await conn.close()

asyncio.run(main(sys.argv[1]))
PY3

echo "▶ 5/5 bulk load"
python scripts/load_wordnet_csv.py --space "$SPACE" \
    --quads-csv "$CSV" --terms-csv "${CSV%.csv}_terms.csv"

# The point of the fixture, asserted here rather than trusted: if the duplicates
# did not survive the load there is nothing to guard the DISTINCT and the benches
# would pass while measuring data that cannot fail them.
python - "$SPACE" <<'PY4'
import asyncio, os, sys
sys.path.insert(0, os.getcwd())
import asyncpg
from scripts.perf_seed_data import pg_params  # noqa: E402

async def main(space_id):
    conn = await asyncpg.connect(**pg_params())
    try:
        dups = await conn.fetchval(
            f"SELECT count(*) FROM (SELECT 1 FROM {space_id}_rdf_quad "
            f"GROUP BY subject_uuid, predicate_uuid, object_uuid, context_uuid "
            f"HAVING count(*) > 1) d")
        if not dups:
            raise SystemExit(
                f"FAILED: {space_id} holds no duplicate quads. This fixture "
                f"exists only to hold them (issues/046); without them the "
                f"benches reading it cannot fail.")
        print(f"   verified {dups} duplicated quad(s) survived the load")
    finally:
        await conn.close()

asyncio.run(main(sys.argv[1]))
PY4

echo "✅ $SPACE loaded from $GRAPH"
