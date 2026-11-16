"""SPARQL vector top-K returns K rows when the child pattern is selective.

`ORDER BY DESC(?score) LIMIT K` over `vg:vectorSimilarity` / `vg:vectorNearby`
is served by a driving subquery (`vg_functions.vector_top_k_driving_sql`):

    SELECT subject_uuid, ... FROM <space>_vec_<index>
    WHERE subject_uuid IN (<child pattern's subjects>)
    ORDER BY embedding <=> q LIMIT K

Its comment said the IN filter "guarantees the top-K results will all survive
the downstream INNER JOIN", which is true of the rows it returns. But from HNSW
the scan yields `hnsw.ef_search` (40) candidates and the IN runs on those, so a
child pattern matching 1% of the index got 0-1 of its K rows. The executor now
turns on iterative scan when `GenerateResult.vector_top_k` is set
(`vectorization/hnsw_scan.py`), and the threshold sits outside the scan.

The SQL here is the generator's own, emitted by `_try_vector_driving_extend`
and run against TEMP tables carrying the names it reads, inside a transaction
that is rolled back. The control runs the same SQL without the setting and must
come back short, or the test proves nothing.
"""

from __future__ import annotations

import random
import uuid

import pytest
import pytest_asyncio

from .conftest import skip_no_infra

pytestmark = [
    pytest.mark.integration,
    skip_no_infra,
    pytest.mark.asyncio(loop_scope="session"),
]

DIM = 32
N_ROWS = 5000
N_CHILD = 50          # 1% of the index
K = 20


def _unit(v):
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def _lit(v):
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def _driving_sql(query_vec, threshold=None):
    """The statement the generator emits for a top-K vectorNearby."""
    from tests.unit.sparql_sql.emit_helpers import _make_ctx, _leaf_bgp, _var, _func
    from tests.unit.sparql_sql.emit_helpers import _lit as _sparql_lit
    from vitalgraph.db.sparql_sql.ir import PlanV2, KIND_EXTEND
    from vitalgraph.db.sparql_sql.emit_extend import _try_vector_driving_extend
    from vitalgraph.db.sparql_sql.vg_functions import VG_VECTOR_NEARBY

    ctx = _make_ctx({"entity": "text"})
    expr = _func("vectorNearby", _var("entity"), _sparql_lit(_lit(query_vec)),
                 _sparql_lit("idx"), function_iri=VG_VECTOR_NEARBY)
    hints = {"vg_top_k": {"limit": K}}
    if threshold is not None:
        hints["vg_threshold"] = threshold
    plan = PlanV2(kind=KIND_EXTEND, extend_var="score", extend_expr=expr,
                  hints=hints, children=[_leaf_bgp()])
    # `subj` repeats the child's uuid under a name the score's columns cannot
    # shadow: the stub context allocates the score variable `v0` as well.
    sql = _try_vector_driving_extend(
        plan, ctx, "SELECT v0, v0__uuid, v0__uuid AS subj FROM test_space_child")
    assert sql is not None and "test_space_vec_idx" in sql
    assert ctx.vector_top_k, "the executor would not turn iterative scan on"
    return sql


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def seeded(pg_pool):
    rng = random.Random(1115)
    q = _unit([rng.gauss(0, 1) for _ in range(DIM)])
    async with pg_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(
                f"CREATE TEMP TABLE test_space_vec_idx "
                f"(subject_uuid uuid PRIMARY KEY, embedding vector({DIM})) ON COMMIT DROP")
            await conn.execute(
                "CREATE TEMP TABLE test_space_child (v0 text, v0__uuid uuid) ON COMMIT DROP")
            rows, child, dist = [], [], {}
            for i in range(N_ROWS):
                u = uuid.uuid4()
                v = _unit([a + rng.uniform(0.3, 1.2) * rng.gauss(0, 1) / DIM ** 0.5 for a in q])
                rows.append((u, _lit(v)))
                if i % (N_ROWS // N_CHILD) == 0:
                    child.append((f"urn:e{i}", u))
                    dist[u] = 1.0 - sum(a * b for a, b in zip(q, v))
            await conn.executemany(
                "INSERT INTO test_space_vec_idx VALUES ($1, $2::vector)", rows)
            await conn.executemany("INSERT INTO test_space_child VALUES ($1, $2)", child)
            await conn.execute(
                "CREATE INDEX ON test_space_vec_idx USING hnsw (embedding vector_cosine_ops)")
            await conn.execute("ANALYZE test_space_vec_idx")
            await conn.execute("ANALYZE test_space_child")
            # Exact service (child subjects -> PK -> sort) is cheaper at this
            # size and hides the defect; large spaces get the HNSW plan.
            await conn.execute("SET LOCAL enable_sort = off")
            yield conn, q, dist
        finally:
            await tx.rollback()


async def _run(conn, sql, iterative):
    from vitalgraph.vectorization.hnsw_scan import hnsw_iterative_scan
    if not iterative:
        return await conn.fetch(sql)
    async with conn.transaction():
        async with hnsw_iterative_scan(conn) as applied:
            assert applied, "pgvector < 0.8.0 on the test stack"
            return await conn.fetch(sql)


def _nearest(dist, k=K, threshold=None):
    ranked = sorted(dist.items(), key=lambda kv: kv[1])
    if threshold is not None:
        ranked = [kv for kv in ranked if 1 - kv[1] > threshold]
    return {u for u, _ in ranked[:k]}


class TestVectorTopK:

    async def test_control_without_iterative_scan_is_short(self, seeded):
        conn, q, _ = seeded
        rows = await _run(conn, _driving_sql(q), iterative=False)
        assert len(rows) < K // 2, (
            f"{len(rows)} of {K} without iterative scan: the plan was not HNSW, "
            "so the other tests here prove nothing")

    async def test_selective_child_gets_its_nearest_k(self, seeded):
        conn, q, dist = seeded
        rows = await _run(conn, _driving_sql(q), iterative=True)
        got = {r["subj"] for r in rows}
        assert len(rows) == K
        assert len(got & _nearest(dist)) / K >= 0.9

    async def test_threshold_applies_to_the_top_k(self, seeded):
        """A threshold fewer than K rows pass: exactly those rows."""
        conn, q, dist = seeded
        sims = sorted((1 - d for d in dist.values()), reverse=True)
        threshold = round((sims[4] + sims[5]) / 2, 6)       # 5 pass
        rows = await _run(conn, _driving_sql(q, threshold), iterative=True)
        assert {r["subj"] for r in rows} == _nearest(dist, threshold=threshold)
