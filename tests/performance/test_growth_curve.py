"""Growth-curve test — prove the entity page keeps its complexity class as data
grows, using synthetic data at several sizes (see scaling_test_strategy.md §3.3).

Loads the *same* fast-page query at 3 sizes and asserts the buffer cost stays
**flat/log** (O(page)), not linear (O(N)). This is the portable, container-
runnable scaling proof — it needs no pre-existing large space.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from test_scripts.data.generate_scale_data import (
    load_scale_space, VITALTYPE, KGENTITY)
from .conftest import skip_no_pg
from .harness import explain_json, total_shared_buffers, assert_growth_class

pytestmark = [pytest.mark.performance, pytest.mark.slow, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "perf_scale"
GRAPH = "urn:perf"
SIZES = [50_000, 150_000, 450_000]   # 9x total growth
# The 4 KGEntity subclass objects the real fast page filters on (only KGEntity
# is generated, but the query shape must match production).
KGENTITY_TYPES = [
    KGENTITY,
    "http://vital.ai/ontology/haley-ai-kg#KGNewsEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGProductEntity",
    "http://vital.ai/ontology/haley-ai-kg#KGWebEntity",
]


def _fast_page_sql(space_id: str) -> str:
    return (
        f"SELECT tt.term_text AS uri "
        f"FROM (SELECT DISTINCT subject_uuid FROM {space_id}_rdf_quad "
        f"      WHERE predicate_uuid = $1 AND object_uuid = ANY($2::uuid[]) "
        f"      AND context_uuid = $3 "
        f"      ORDER BY subject_uuid LIMIT $4 OFFSET $5) sub "
        f"JOIN {space_id}_term tt ON tt.term_uuid = sub.subject_uuid "
        f"ORDER BY sub.subject_uuid"
    )


async def test_entity_page_growth_is_flat(perf_pool):
    p_uuid = _generate_term_uuid(VITALTYPE, "U")
    obj_uuids = [_generate_term_uuid(u, "U") for u in KGENTITY_TYPES]
    g_uuid = _generate_term_uuid(GRAPH, "U")
    sql = _fast_page_sql(SPACE)

    points = {}
    for n in SIZES:
        await load_scale_space(perf_pool, SPACE, n, graph_uri=GRAPH, drop_first=True)
        async with perf_pool.acquire() as conn:
            plan = await explain_json(conn, sql, p_uuid, obj_uuids, g_uuid, 25, 0)
            points[n] = float(total_shared_buffers(plan))

    print(f"\nentity-page buffers by entity count: {points}")
    # O(page): buffers must not grow ~linearly with entity count.
    assert_growth_class(points, allowed=["flat", "log"])

    # Clean up the synthetic space.
    async with perf_pool.acquire() as conn:
        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        try:
            await SparqlSQLSchema.drop_space(conn, SPACE)
        except Exception:
            pass
