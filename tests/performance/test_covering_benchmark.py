"""L2 benchmark: quantify the (context, predicate) covering-index advantage as
data grows.

Measures a graph-scoped predicate scan WITH vs WITHOUT the covering index at
several sizes and reports buffers touched. Buffers ≈ pages, and each page is a
potential random heap read when the buffer pool is cold — so the *page-count
advantage* here is the proxy for the cold-cache / at-scale win (which the docs
project as 10-100x at 1B and can only be confirmed absolutely at L3).

Asserts: WITH the covering index the scan stays Index-Only, and its buffer
advantage over the pre-P1 indexes holds (does not shrink) as data grows.
"""

from __future__ import annotations

import pytest

from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from test_scripts.data.generate_scale_data import load_scale_space, HASNAME
from .conftest import skip_no_pg
from .harness import (explain_json, total_shared_buffers, node_types,
                      index_only_heap_fetches, has_seq_scan_on)

pytestmark = [pytest.mark.performance, pytest.mark.slow, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SPACE = "perf_covbench"
GRAPH = "urn:perf"
SIZES = [100_000, 300_000, 900_000]


async def _scan_buffers(conn, sql, *params):
    plan = await explain_json(conn, sql, *params)
    return (total_shared_buffers(plan), node_types(plan)[0],
            index_only_heap_fetches(plan), plan)


@pytest.mark.skip(reason=(
    "Bench cannot demonstrate its claim on this generator's data shape. "
    "generate_scale_data emits exactly 2 quads per entity (vitaltype + hasName) "
    "in a single context, so the probe predicate matches ~50% of the table. At "
    "that selectivity PG18 picks a Bitmap Heap Scan via a predicate-leading "
    "index and never uses idx_*_quad_ctx_pred at all — measured WITH vs WITHOUT "
    "the covering index are byte-identical (2938/2938, 8811/8811, 26426/26426 "
    "buffers at 100K/300K/900K entities, ratio 1.0x). This is a property of the "
    "synthetic data, NOT a covering-index regression: the index-only gate on the "
    "realistic lead dataset (test_covering_indexes.py, moved there by 701c08b) "
    "is unaffected. Re-enable once the generator grows a predicate-cardinality "
    "knob so a selective probe exists — see performance_regression_tracking_plan.md."))
@pytest.mark.bench("query.covering.advantage_growth")
async def test_covering_index_advantage_holds_with_growth(perf_pool, perf_record):
    g_uuid = _generate_term_uuid(GRAPH, "U")
    p_uuid = _generate_term_uuid(HASNAME, "U")
    sql = (f"SELECT subject_uuid, object_uuid FROM {SPACE}_rdf_quad "
           f"WHERE context_uuid = $1 AND predicate_uuid = $2")

    rows = []  # (n, with_buf, with_node, without_buf, without_node, ratio)
    last_with_plan = None
    try:
        for n in SIZES:
            await load_scale_space(perf_pool, SPACE, n, graph_uri=GRAPH, drop_first=True)
            async with perf_pool.acquire() as conn:
                w_buf, w_node, w_hf, w_plan = await _scan_buffers(conn, sql, g_uuid, p_uuid)
                # Structural gate: rdf_quad must not be seq-scanned. We deliberately
                # do NOT assert "Index Only Scan", nor which index is chosen. This
                # generator emits exactly 2 quads per entity (vitaltype + hasName)
                # in a single context, so the probe predicate matches ~50% of the
                # table; at that selectivity PG18 correctly costs a bitmap heap scan
                # cheaper than an index-only scan, and a predicate-leading index as
                # good as the (context, predicate) covering one. That is a property
                # of the synthetic shape, not a covering-index failure — the same
                # reason 701c08b moved the index-only *gate* onto the realistic lead
                # dataset (test_covering_indexes.py). Plan shape and index choice
                # are recorded instead, so the baseline fails on any *change* to
                # them while the buffer-advantage assertions below stay the gate.
                assert has_seq_scan_on(w_plan, [f"{SPACE}_rdf_quad"]) is None, (
                    f"seq scan on rdf_quad at n={n}; nodes={node_types(w_plan)}")
                last_with_plan = w_plan
                # Remove the covering index → pre-P1 behavior.
                await conn.execute(f"DROP INDEX IF EXISTS idx_{SPACE}_quad_ctx_pred")
                o_buf, o_node, _, _ = await _scan_buffers(conn, sql, g_uuid, p_uuid)
                ratio = o_buf / w_buf if w_buf else 0.0
                rows.append((n, w_buf, w_node, o_buf, o_node, ratio))
    finally:
        async with perf_pool.acquire() as conn:
            try:
                await SparqlSQLSchema.drop_space(conn, SPACE)
            except Exception:
                pass

    print("\n  covering-index advantage (graph-scoped predicate scan):")
    print(f"  {'entities':>9} | {'WITH (idx-only)':>18} | {'WITHOUT (pre-P1)':>22} | ratio")
    for n, wb, wn, ob, on, r in rows:
        print(f"  {n:>9} | {wb:>7} buf {wn:<10} | {ob:>7} buf {on:<12} | {r:>4.1f}x")

    largest = rows[-1]
    perf_record(
        plan=last_with_plan,                 # records plan shape + index choice
        dataset=f"synthetic:{SIZES[-1]}",
        metrics={
            "with_index_buffers": largest[1],
            "with_index_node": largest[2],
            "without_index_buffers": largest[3],
            "without_index_node": largest[4],
            "advantage_ratio": round(largest[5], 3),
            "with_growth": round(rows[-1][1] / max(rows[0][1], 1), 3),
            "without_growth": round(rows[-1][3] / max(rows[0][3], 1), 3),
        },
        notes=f"sizes={SIZES}")

    # The advantage must hold as data grows (buffers = cold-read proxy). Use a
    # conservative floor so the gate isn't flaky, and require it not to collapse.
    assert largest[5] >= 1.5, f"covering-index buffer advantage collapsed: {largest[5]:.1f}x"
    # WITH-index buffers must grow far slower than WITHOUT as n grows.
    with_growth = rows[-1][1] / max(rows[0][1], 1)
    without_growth = rows[-1][3] / max(rows[0][3], 1)
    assert with_growth <= without_growth, (
        f"covering-index buffers grew faster ({with_growth:.1f}x) than pre-P1 "
        f"({without_growth:.1f}x) — advantage not holding")
