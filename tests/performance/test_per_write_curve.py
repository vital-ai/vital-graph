"""L2 per-write curve: a small write's cost stays flat as the table grows.

P2 validation. The incremental write path (executemany + scoped edge/frame/stats
sync) must be O(batch), not O(table): the aux-sync scans only the touched
subjects via ANY($), so inserting a fixed probe into a 900k-quad table should
cost about what it costs into a 100k-quad table. Asserts the latency growth
class is sub-linear, and structurally that the edge-sync scan never seq-scans
rdf_quad.
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.sparql_sql_space_impl import _generate_term_uuid
from vitalgraph.db.sparql_sql.bulk_load import insert_terms_quads_executemany
from vitalgraph.db.sparql_sql.sync_edge_table import (
    sync_edge_table_after_insert, _EDGE_SRC_UUID, _EDGE_DST_UUID)
from vitalgraph.db.sparql_sql.sync_frame_entity_table import (
    sync_frame_entity_after_edge_insert)
from vitalgraph.db.sparql_sql.sync_stats_tables import sync_stats_after_insert
from test_scripts.data.generate_scale_data import load_scale_space, HASNAME
from .conftest import skip_no_pg
from .harness import explain_json, has_seq_scan_on, assert_growth_class, node_types

pytestmark = [pytest.mark.performance, pytest.mark.slow, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

SIZES = [50_000, 150_000, 450_000]   # entities (2 quads each); 9x range
PROBE = 300
GRAPH = "urn:perf"


def _probe_rows():
    """(term_args[5-col], quad_rows[4-col], subjects) for a fresh probe batch."""
    p_name = _generate_term_uuid(HASNAME, "U")
    g = _generate_term_uuid(GRAPH, "U")
    terms = {p_name: (p_name, HASNAME, "U", None, None),
             g: (g, GRAPH, "U", None, None)}
    quads = []
    for i in range(PROBE):
        uri, name = f"urn:perf:probe:{i}", f"probe name {i}"
        e = _generate_term_uuid(uri, "U")
        nm = _generate_term_uuid(name, "L")
        terms[e] = (e, uri, "U", None, None)
        terms[nm] = (nm, name, "L", None, None)
        quads.append((e, p_name, nm, g))
    return list(terms.values()), quads, [q[0] for q in quads]


async def _probe_latency(pool, sid, term_args, quad_rows, subjects, repeats=3):
    """Min latency of the incremental write path; each run rolled back so the
    probe never persists (repeatable on the same-sized space)."""
    t = SparqlSQLSchema.get_table_names(sid)
    best = float("inf")
    async with pool.acquire() as conn:
        for _ in range(repeats):
            tr = conn.transaction()
            await tr.start()
            t0 = time.monotonic()
            await insert_terms_quads_executemany(conn, t, term_args, quad_rows)
            await sync_edge_table_after_insert(conn, sid, subjects)
            await sync_frame_entity_after_edge_insert(conn, sid, subjects)
            await sync_stats_after_insert(conn, sid, quad_rows)
            best = min(best, time.monotonic() - t0)
            await tr.rollback()
    return best


async def test_per_write_cost_stays_flat(perf_pool):
    term_args, quad_rows, subjects = _probe_rows()
    sid = f"perf_perwrite_{uuid.uuid4().hex[:8]}"
    points = {}
    try:
        for n_ent in SIZES:
            n_quads = await load_scale_space(perf_pool, sid, n_ent, graph_uri=GRAPH)
            points[n_quads] = await _probe_latency(
                perf_pool, sid, term_args, quad_rows, subjects)

        # Structural: at the largest size the edge-sync scan is index-driven.
        async with perf_pool.acquire() as conn:
            plan = await explain_json(conn, f"""
                SELECT src.subject_uuid, src.object_uuid, dst.object_uuid, src.context_uuid
                FROM {sid}_rdf_quad src
                JOIN {sid}_rdf_quad dst
                  ON dst.subject_uuid = src.subject_uuid
                  AND dst.context_uuid = src.context_uuid
                WHERE src.predicate_uuid = $1 AND dst.predicate_uuid = $2
                  AND src.subject_uuid = ANY($3)
            """, _EDGE_SRC_UUID, _EDGE_DST_UUID, subjects, analyze=False)
        assert has_seq_scan_on(plan, [f"{sid}_rdf_quad"]) is None, node_types(plan)

        print(f"\nper-write latency vs table size: "
              + "  ".join(f"{n:,}q={ms*1000:.1f}ms" for n, ms in sorted(points.items())))
        cls = assert_growth_class(points, ["flat", "log"])
        print(f"growth class: {cls}")
    finally:
        async with perf_pool.acquire() as conn:
            await SparqlSQLSchema.drop_space(conn, sid)
