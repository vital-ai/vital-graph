"""Standing plan-shape regression tests for the listing fast paths.

Codifies the EXPLAIN checks we did by hand while building the entity/frame/doc
fast pages (see planning/planning_performance/kgentity_listing_render_plan.md):
the `subject_uuid`-ordered page must stay **O(page)** — an index scan, no Seq
Scan on rdf_quad, bounded buffers, bounded rows examined, no spill — regardless
of how many entities/frames the space holds. A regression to the old
`ORDER BY ?s`/text-sort behavior (O(N), hundreds of thousands of buffers) would
fail these.

Runs against whatever real space is loaded (skips if absent). In CI these run
inside the ephemeral vg-test container against a seeded space.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from .conftest import skip_no_pg, space_exists
from .harness import assert_plan, total_shared_buffers, max_actual_rows

pytestmark = [pytest.mark.performance, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

VITALTYPE = "http://vital.ai/ontology/vital-core#vitaltype"
KGENTITY_TYPES = [
    "http://vital.ai/ontology/haley-ai-kg#KGEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGNewsEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGProductEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGWebEntity",
]
KGFRAME_TYPES = ["http://vital.ai/ontology/haley-ai-kg#KGFrame"]

# (space_id, graph_uri, type_uris) — the loaded spaces we assert against.
CASES = [
    ("wordnet_frames", "urn:wordnet_frames", KGENTITY_TYPES),   # ~109K entities
    ("wordnet_frames", "urn:wordnet_frames", KGFRAME_TYPES),    # ~285K frames
]


def _fast_page_sql(space_id: str) -> str:
    """The exact query fast_typed_subject_page issues (order by subject_uuid)."""
    return (
        f"SELECT tt.term_text AS uri "
        f"FROM (SELECT DISTINCT subject_uuid FROM {space_id}_rdf_quad "
        f"      WHERE predicate_uuid = $1 AND object_uuid = ANY($2::uuid[]) "
        f"      AND context_uuid = $3 "
        f"      ORDER BY subject_uuid LIMIT $4 OFFSET $5) sub "
        f"JOIN {space_id}_term tt ON tt.term_uuid = sub.subject_uuid "
        f"ORDER BY sub.subject_uuid"
    )


@pytest.mark.parametrize("space_id,graph_uri,type_uris", CASES)
async def test_fast_page_is_o_page(perf_conn, space_id, graph_uri, type_uris):
    if not await space_exists(perf_conn, space_id):
        pytest.skip(f"space {space_id} not loaded")

    p_uuid = _generate_term_uuid(VITALTYPE, "U")
    obj_uuids = [_generate_term_uuid(u, "U") for u in type_uris]
    g_uuid = _generate_term_uuid(graph_uri, "U")

    # The scaling gate: a 25-row page must NOT seq-scan rdf_quad, must stay under
    # a small buffer bound, must not materialize the whole relation, no spill.
    # These bounds hold at 100K and would hold at 1B; an O(N) regression blows them.
    plan = await assert_plan(
        perf_conn, _fast_page_sql(space_id),
        p_uuid, obj_uuids, g_uuid, 25, 0,
        no_seq_scan_on=[f"{space_id}_rdf_quad"],
        max_shared_buffers=8_000,     # observed ~464 on 109K; O(N) would be ~450K
        max_actual_rows_bound=5_000,  # a page examines a bounded slice, not all rows
        no_spill=True,
    )
    # Informational (helps when tuning bounds / diagnosing regressions).
    print(f"\n[{space_id}/{type_uris[-1].split('#')[-1]}] "
          f"buffers={total_shared_buffers(plan)} max_rows={max_actual_rows(plan)}")


async def test_deep_page_offset_stays_bounded(perf_conn):
    """A deeper page (OFFSET) must still be bounded — guards against a plan that
    re-materializes everything for later pages."""
    space_id, graph_uri, type_uris = CASES[0]
    if not await space_exists(perf_conn, space_id):
        pytest.skip(f"space {space_id} not loaded")

    p_uuid = _generate_term_uuid(VITALTYPE, "U")
    obj_uuids = [_generate_term_uuid(u, "U") for u in type_uris]
    g_uuid = _generate_term_uuid(graph_uri, "U")

    # OFFSET 1000 still bounded (index walk + skip), no seq scan, no spill.
    await assert_plan(
        perf_conn, _fast_page_sql(space_id),
        p_uuid, obj_uuids, g_uuid, 25, 1000,
        no_seq_scan_on=[f"{space_id}_rdf_quad"],
        max_shared_buffers=20_000,
        no_spill=True,
    )
