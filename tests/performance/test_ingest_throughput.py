"""L2 ingest-throughput benchmark: drop→COPY→rebuild vs executemany.

P2 gate. Classifies one synthetic quad batch, then loads the identical term/quad
rows into two fresh (empty) spaces — one via executemany (incremental,
index-live), one via the drop-secondary-indexes → COPY → rebuild bulk path — and
asserts the bulk path is meaningfully faster end-to-end and lands identical
counts.

Honest gates (see planning/planning_performance/scaling_implementation_plan.md
"Phase 2"): the bulk path is ~2.7x end-to-end here (index rebuild is the tax);
raw COPY data movement is ~6x, but rebuilding the secondary indexes pulls the
net down. The >=5x figure applies to data movement, not the full load. Both are
in the cache-resident regime; the advantage widens once indexes exceed RAM.
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.bulk_load import (
    insert_terms_quads_executemany, insert_terms_quads_copy)
from .conftest import skip_no_pg

pytestmark = [pytest.mark.performance, pytest.mark.slow, skip_no_pg,
              pytest.mark.asyncio(loop_scope="session")]

N_QUADS = 400_000       # large enough that ratios are stable (100k is noisy)
MIN_COPY_SPEEDUP = 5.0  # COPY data movement vs executemany (~6x measured, robust)
MIN_E2E_SPEEDUP = 1.5   # full load incl. index rebuild (~2.7x measured, noisier)


def _synth_rows(n_quads):
    """Deterministic term rows + quad rows (~n_quads quads, terms shared like
    real data: few predicates, 1 context, 4 quads/subject, unique object)."""
    terms = {}

    def term(text, ttype="U"):
        u = uuid.uuid5(uuid.NAMESPACE_URL, f"{ttype}:{text}")
        if u not in terms:
            terms[u] = (u, text, ttype, None, None)
        return u

    ctx = term("urn:graph:bench")
    preds = [term(f"urn:pred:{i}") for i in range(20)]
    quads = []
    for i in range(n_quads):
        s = term(f"urn:subj:{i // 4}")
        o = term(f"literal value number {i}", "L")
        quads.append((s, preds[i % 20], o, ctx))
    return list(terms.values()), quads


@pytest_asyncio.fixture(loop_scope="session")
async def two_spaces(perf_pool):
    sids = [f"perf_ingest_{k}_{uuid.uuid4().hex[:8]}" for k in ("em", "bulk")]
    async with perf_pool.acquire() as conn:
        for sid in sids:
            await SparqlSQLSchema.create_space(conn, sid)
    yield sids
    async with perf_pool.acquire() as conn:
        for sid in sids:
            await SparqlSQLSchema.drop_space(conn, sid)


async def test_bulk_rebuild_beats_executemany(perf_pool, two_spaces):
    em_sid, bulk_sid = two_spaces
    term_args, quad_rows = _synth_rows(N_QUADS)
    schema = SparqlSQLSchema()

    # Baseline: executemany, indexes live.
    tn = SparqlSQLSchema.get_table_names(em_sid)
    async with perf_pool.acquire() as conn:
        async with conn.transaction():
            t0 = time.monotonic()
            await insert_terms_quads_executemany(conn, tn, term_args, quad_rows)
            em_t = time.monotonic() - t0

    # Bulk path, phases timed separately: drop 2ndary idx → COPY → rebuild.
    tb = SparqlSQLSchema.get_table_names(bulk_sid)
    async with perf_pool.acquire() as conn:
        async with conn.transaction():
            for s in schema.drop_space_indexes_sql(bulk_sid):
                await conn.execute(s)
            t0 = time.monotonic()
            await insert_terms_quads_copy(conn, tb, term_args, quad_rows,
                                          terms_direct=True)  # fresh space
            copy_t = time.monotonic() - t0        # data-movement phase
            t0 = time.monotonic()
            for s in schema.create_space_indexes_sql(bulk_sid):
                await conn.execute(s)
            rebuild_t = time.monotonic() - t0      # index rebuild tax
    bulk_t = copy_t + rebuild_t

    copy_speedup = em_t / copy_t if copy_t else float("inf")
    e2e_speedup = em_t / bulk_t if bulk_t else float("inf")
    print(f"\ningest {len(quad_rows)} quads / {len(term_args)} terms:"
          f"\n  executemany       = {em_t:6.3f}s ({len(quad_rows)/em_t:>8,.0f} q/s)"
          f"\n  COPY (data move)  = {copy_t:6.3f}s ({len(quad_rows)/copy_t:>8,.0f} q/s)  "
          f"= {copy_speedup:.1f}x"
          f"\n  index rebuild     = {rebuild_t:6.3f}s"
          f"\n  bulk end-to-end   = {bulk_t:6.3f}s ({len(quad_rows)/bulk_t:>8,.0f} q/s)  "
          f"= {e2e_speedup:.1f}x")

    # Identical landing: both spaces hold the same term/quad counts.
    async with perf_pool.acquire() as conn:
        for sid in (em_sid, bulk_sid):
            t = SparqlSQLSchema.get_table_names(sid)
            terms = await conn.fetchval(f"SELECT count(*) FROM {t['term']}")
            quads = await conn.fetchval(f"SELECT count(*) FROM {t['rdf_quad']}")
            assert terms == len(term_args), (sid, terms, len(term_args))
            assert quads == len(quad_rows), (sid, quads, len(quad_rows))

    # Primary gate: COPY data movement is the robust, mechanism-level win.
    assert copy_speedup >= MIN_COPY_SPEEDUP, (
        f"COPY only {copy_speedup:.1f}x executemany (want >= {MIN_COPY_SPEEDUP}x)")
    # Secondary: the full load (incl. rebuild) still beats executemany.
    assert e2e_speedup >= MIN_E2E_SPEEDUP, (
        f"bulk end-to-end only {e2e_speedup:.1f}x (want >= {MIN_E2E_SPEEDUP}x)")
