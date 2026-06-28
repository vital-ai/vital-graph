#!/usr/bin/env python3
"""
Benchmark: correlated vs non-correlated multi-vector SQL patterns.

Creates temporary vector tables with synthetic data at various scales,
then compares:
  A) Correlated CTE — current implementation (per-entity lookup)
  B) Non-correlated UNION+INTERSECT — candidate-driven (top-K oversample)

Usage:
    python test_scripts_misc/benchmark_multi_vector_sql.py [--scales 100,1000,10000]

Requires: asyncpg, pgvector extension in the target database.
"""

import argparse
import asyncio
import logging
import math
import random
import statistics
import sys
import time
import uuid
from typing import List, Tuple

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_DSN = "postgresql://postgres:postgres@localhost:5432/sparql_sql_graph"
BENCH_PREFIX = "__bench_mv_"  # temporary table prefix
VEC_DIM = 64                  # small enough to be fast, large enough to be realistic
TOP_K = 20
OVERSAMPLE_FACTORS = [1, 3, 5, 10]
WEIGHTS = [0.4, 0.6]         # two-index benchmark
NUM_ITERATIONS = 5            # repeat each query for stable timing
FUSION_STRATEGIES = ["weighted_sum", "relative_score", "ranked"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def random_unit_vector(dim: int) -> List[float]:
    """Generate a random unit vector."""
    raw = [random.gauss(0, 1) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


def vec_literal(v: List[float]) -> str:
    """Format vector as pgvector literal."""
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------
async def create_bench_tables(conn: asyncpg.Connection, scale: int) -> Tuple[str, str, str]:
    """Create two vector tables + populate with synthetic data.

    Returns (table_a, table_b, context_uuid_literal).
    """
    suffix = f"{scale}"
    table_a = f"{BENCH_PREFIX}vec_a_{suffix}"
    table_b = f"{BENCH_PREFIX}vec_b_{suffix}"
    ctx_uuid = uuid.uuid4()

    for tbl in (table_a, table_b):
        await conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        await conn.execute(f"""
            CREATE UNLOGGED TABLE {tbl} (
                subject_uuid UUID NOT NULL,
                context_uuid UUID NOT NULL,
                embedding vector({VEC_DIM}) NOT NULL,
                PRIMARY KEY (subject_uuid, context_uuid)
            )
        """)

    # Generate entity UUIDs (shared between both tables for INTERSECT to work)
    entity_uuids = [uuid.uuid4() for _ in range(scale)]

    # Bulk insert via multi-row VALUES in batches of 500
    BATCH = 500

    async def _bulk_insert(tbl: str, uuids, ctx: uuid.UUID):
        for start in range(0, len(uuids), BATCH):
            batch = uuids[start:start + BATCH]
            parts = []
            args = []
            for j, eid in enumerate(batch):
                base = j * 3
                parts.append(f"(${base+1}, ${base+2}, ${base+3}::vector)")
                args.extend([eid, ctx, vec_literal(random_unit_vector(VEC_DIM))])
            sql = f"INSERT INTO {tbl} (subject_uuid, context_uuid, embedding) VALUES " + ", ".join(parts)
            await conn.execute(sql, *args)

    t_ins = time.perf_counter()
    await _bulk_insert(table_a, entity_uuids, ctx_uuid)

    overlap = int(scale * 0.8)
    await _bulk_insert(table_b, entity_uuids[:overlap], ctx_uuid)
    log.info(f"  Inserted data in {(time.perf_counter() - t_ins)*1000:.0f}ms")

    # Build indexes AFTER data load (much faster for HNSW)
    t_idx = time.perf_counter()
    for tbl in (table_a, table_b):
        await conn.execute(f"""
            CREATE INDEX ON {tbl}
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        await conn.execute(f"CREATE INDEX ON {tbl} (subject_uuid)")
    log.info(f"  Built indexes in {(time.perf_counter() - t_idx)*1000:.0f}ms")

    await conn.execute("ANALYZE " + table_a)
    await conn.execute("ANALYZE " + table_b)

    log.info(f"  Created {table_a} ({scale} rows), {table_b} ({overlap} rows)")
    return table_a, table_b, str(ctx_uuid)


async def drop_bench_tables(conn: asyncpg.Connection, scale: int):
    suffix = f"{scale}"
    for name in (f"{BENCH_PREFIX}vec_a_{suffix}", f"{BENCH_PREFIX}vec_b_{suffix}"):
        await conn.execute(f"DROP TABLE IF EXISTS {name}")


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------
def build_correlated_sql(
    table_a: str, table_b: str,
    vec_a: str, vec_b: str,
    ctx_uuid: str,
    uuid_col: str,  # the outer entity UUID expression
    w0: float, w1: float,
    strategy: str = "weighted_sum",
) -> str:
    """Build correlated CTE SQL (current implementation pattern)."""
    total = w0 + w1
    nw0, nw1 = w0 / total, w1 / total

    cte0 = (
        f"__mv_v0 AS (\n"
        f"  SELECT subject_uuid, 1 - (embedding <=> '{vec_a}'::vector) AS score\n"
        f"  FROM {table_a}\n"
        f"  WHERE subject_uuid = {uuid_col}\n"
        f"    AND context_uuid = '{ctx_uuid}'::uuid\n"
        f"  LIMIT 1\n"
        f")"
    )
    cte1 = (
        f"__mv_v1 AS (\n"
        f"  SELECT subject_uuid, 1 - (embedding <=> '{vec_b}'::vector) AS score\n"
        f"  FROM {table_b}\n"
        f"  WHERE subject_uuid = {uuid_col}\n"
        f"    AND context_uuid = '{ctx_uuid}'::uuid\n"
        f"  LIMIT 1\n"
        f")"
    )

    if strategy == "relative_score":
        norm0 = (
            f"__mv_n0 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 1.0\n"
            f"         ELSE (score - MIN(score) OVER ()) / (MAX(score) OVER () - MIN(score) OVER ())\n"
            f"    END AS score\n"
            f"  FROM __mv_v0\n"
            f")"
        )
        norm1 = (
            f"__mv_n1 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 1.0\n"
            f"         ELSE (score - MIN(score) OVER ()) / (MAX(score) OVER () - MIN(score) OVER ())\n"
            f"    END AS score\n"
            f"  FROM __mv_v1\n"
            f")"
        )
        score_expr = f"{nw0:.6f} * __mv_n0.score + {nw1:.6f} * __mv_n1.score"
        null_check = "__mv_n0.score IS NOT NULL AND __mv_n1.score IS NOT NULL"
        return (
            f"WITH {cte0},\n{cte1},\n{norm0},\n{norm1}\n"
            f"SELECT CASE WHEN {null_check} THEN {score_expr} ELSE NULL END\n"
            f"FROM __mv_n0, __mv_n1"
        )
    elif strategy == "ranked":
        rank0 = (
            f"__mv_r0 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    1.0 / (ROW_NUMBER() OVER (ORDER BY score DESC) + 60) AS rank_score\n"
            f"  FROM __mv_v0\n"
            f")"
        )
        rank1 = (
            f"__mv_r1 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    1.0 / (ROW_NUMBER() OVER (ORDER BY score DESC) + 60) AS rank_score\n"
            f"  FROM __mv_v1\n"
            f")"
        )
        score_expr = f"{nw0:.6f} * __mv_r0.rank_score + {nw1:.6f} * __mv_r1.rank_score"
        null_check = "__mv_r0.rank_score IS NOT NULL AND __mv_r1.rank_score IS NOT NULL"
        return (
            f"WITH {cte0},\n{cte1},\n{rank0},\n{rank1}\n"
            f"SELECT CASE WHEN {null_check} THEN {score_expr} ELSE NULL END\n"
            f"FROM __mv_r0, __mv_r1"
        )
    else:
        score_expr = f"{nw0:.6f} * __mv_v0.score + {nw1:.6f} * __mv_v1.score"
        null_check = "__mv_v0.score IS NOT NULL AND __mv_v1.score IS NOT NULL"
        return (
            f"WITH {cte0},\n{cte1}\n"
            f"SELECT CASE WHEN {null_check} THEN {score_expr} ELSE NULL END\n"
            f"FROM __mv_v0, __mv_v1"
        )


def build_noncorrelated_sql(
    table_a: str, table_b: str,
    vec_a: str, vec_b: str,
    ctx_uuid: str,
    oversample: int,
    w0: float, w1: float,
    top_k: int,
    strategy: str = "weighted_sum",
) -> str:
    """Build non-correlated UNION+INTERSECT SQL (candidate-driven pattern).

    This fetches top oversample*top_k candidates from each index independently,
    INTERSECTs them, then computes weighted scores.
    """
    total = w0 + w1
    nw0, nw1 = w0 / total, w1 / total
    candidate_limit = oversample * top_k

    cte0 = (
        f"__mv_v0 AS (\n"
        f"  SELECT subject_uuid, 1 - (embedding <=> '{vec_a}'::vector) AS score\n"
        f"  FROM {table_a}\n"
        f"  WHERE context_uuid = '{ctx_uuid}'::uuid\n"
        f"  ORDER BY embedding <=> '{vec_a}'::vector\n"
        f"  LIMIT {candidate_limit}\n"
        f")"
    )
    cte1 = (
        f"__mv_v1 AS (\n"
        f"  SELECT subject_uuid, 1 - (embedding <=> '{vec_b}'::vector) AS score\n"
        f"  FROM {table_b}\n"
        f"  WHERE context_uuid = '{ctx_uuid}'::uuid\n"
        f"  ORDER BY embedding <=> '{vec_b}'::vector\n"
        f"  LIMIT {candidate_limit}\n"
        f")"
    )

    if strategy == "relative_score":
        norm0 = (
            f"__mv_n0 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 1.0\n"
            f"         ELSE (score - MIN(score) OVER ()) / (MAX(score) OVER () - MIN(score) OVER ())\n"
            f"    END AS score\n"
            f"  FROM __mv_v0\n"
            f")"
        )
        norm1 = (
            f"__mv_n1 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    CASE WHEN MAX(score) OVER () = MIN(score) OVER () THEN 1.0\n"
            f"         ELSE (score - MIN(score) OVER ()) / (MAX(score) OVER () - MIN(score) OVER ())\n"
            f"    END AS score\n"
            f"  FROM __mv_v1\n"
            f")"
        )
        candidates = (
            f"__candidates AS (\n"
            f"  SELECT subject_uuid FROM __mv_n0\n"
            f"  INTERSECT\n"
            f"  SELECT subject_uuid FROM __mv_n1\n"
            f")"
        )
        score_expr = f"{nw0:.6f} * n0.score + {nw1:.6f} * n1.score"
        return (
            f"WITH {cte0},\n{cte1},\n{norm0},\n{norm1},\n{candidates}\n"
            f"SELECT c.subject_uuid, {score_expr} AS combined_score\n"
            f"FROM __candidates c\n"
            f"JOIN __mv_n0 n0 ON n0.subject_uuid = c.subject_uuid\n"
            f"JOIN __mv_n1 n1 ON n1.subject_uuid = c.subject_uuid\n"
            f"ORDER BY combined_score DESC\n"
            f"LIMIT {top_k}"
        )
    elif strategy == "ranked":
        rank0 = (
            f"__mv_r0 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    1.0 / (ROW_NUMBER() OVER (ORDER BY score DESC) + 60) AS rank_score\n"
            f"  FROM __mv_v0\n"
            f")"
        )
        rank1 = (
            f"__mv_r1 AS (\n"
            f"  SELECT subject_uuid,\n"
            f"    1.0 / (ROW_NUMBER() OVER (ORDER BY score DESC) + 60) AS rank_score\n"
            f"  FROM __mv_v1\n"
            f")"
        )
        candidates = (
            f"__candidates AS (\n"
            f"  SELECT subject_uuid FROM __mv_r0\n"
            f"  INTERSECT\n"
            f"  SELECT subject_uuid FROM __mv_r1\n"
            f")"
        )
        score_expr = f"{nw0:.6f} * r0.rank_score + {nw1:.6f} * r1.rank_score"
        return (
            f"WITH {cte0},\n{cte1},\n{rank0},\n{rank1},\n{candidates}\n"
            f"SELECT c.subject_uuid, {score_expr} AS combined_score\n"
            f"FROM __candidates c\n"
            f"JOIN __mv_r0 r0 ON r0.subject_uuid = c.subject_uuid\n"
            f"JOIN __mv_r1 r1 ON r1.subject_uuid = c.subject_uuid\n"
            f"ORDER BY combined_score DESC\n"
            f"LIMIT {top_k}"
        )
    else:
        candidates = (
            f"__candidates AS (\n"
            f"  SELECT subject_uuid FROM __mv_v0\n"
            f"  INTERSECT\n"
            f"  SELECT subject_uuid FROM __mv_v1\n"
            f")"
        )
        score_expr = f"{nw0:.6f} * v0.score + {nw1:.6f} * v1.score"
        return (
            f"WITH {cte0},\n{cte1},\n{candidates}\n"
            f"SELECT c.subject_uuid, {score_expr} AS combined_score\n"
            f"FROM __candidates c\n"
            f"JOIN __mv_v0 v0 ON v0.subject_uuid = c.subject_uuid\n"
            f"JOIN __mv_v1 v1 ON v1.subject_uuid = c.subject_uuid\n"
            f"ORDER BY combined_score DESC\n"
            f"LIMIT {top_k}"
        )


# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------
async def time_query(conn: asyncpg.Connection, sql: str, iterations: int) -> List[float]:
    """Run a query multiple times, return list of elapsed ms."""
    # Warm up
    await conn.fetch(sql)
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        await conn.fetch(sql)
        times.append((time.perf_counter() - t0) * 1000)
    return times


async def run_explain(conn: asyncpg.Connection, sql: str) -> str:
    """Run EXPLAIN ANALYZE and return the plan text."""
    rows = await conn.fetch(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) {sql}")
    return "\n".join(r[0] for r in rows)


async def benchmark_scale(conn: asyncpg.Connection, scale: int, strategies: List[str]):
    """Run benchmarks for a given data scale."""
    log.info(f"\n{'='*70}")
    log.info(f"SCALE: {scale:,} entities per vector index")
    log.info(f"{'='*70}")

    table_a, table_b, ctx_uuid = await create_bench_tables(conn, scale)

    # Generate query vectors
    query_vec_a = vec_literal(random_unit_vector(VEC_DIM))
    query_vec_b = vec_literal(random_unit_vector(VEC_DIM))

    # Pick a random entity UUID from table_a (for correlated queries)
    row = await conn.fetchrow(f"SELECT subject_uuid FROM {table_a} ORDER BY random() LIMIT 1")
    sample_uuid = str(row['subject_uuid'])

    w0, w1 = WEIGHTS

    for strategy in strategies:
        log.info(f"\n  --- Strategy: {strategy} ---")

        # A) Correlated (single entity lookup)
        corr_sql = build_correlated_sql(
            table_a, table_b, query_vec_a, query_vec_b,
            ctx_uuid, f"'{sample_uuid}'::uuid", w0, w1, strategy=strategy,
        )
        corr_times = await time_query(conn, corr_sql, NUM_ITERATIONS)
        corr_p50 = statistics.median(corr_times)
        log.info(f"  [A] Correlated (1 entity):  p50={corr_p50:.2f}ms  "
                 f"all={[f'{t:.2f}' for t in corr_times]}")

        # B) Non-correlated at various oversample factors
        for osf in OVERSAMPLE_FACTORS:
            nc_sql = build_noncorrelated_sql(
                table_a, table_b, query_vec_a, query_vec_b,
                ctx_uuid, osf, w0, w1, TOP_K, strategy=strategy,
            )
            nc_times = await time_query(conn, nc_sql, NUM_ITERATIONS)
            nc_p50 = statistics.median(nc_times)
            candidate_count = osf * TOP_K
            log.info(f"  [B] NonCorr oversample={osf}x ({candidate_count} candidates): "
                     f"p50={nc_p50:.2f}ms  all={[f'{t:.2f}' for t in nc_times]}")

        # EXPLAIN ANALYZE for the default oversample=5 non-correlated
        log.info(f"\n  EXPLAIN ANALYZE (non-correlated, oversample=5, {strategy}):")
        nc_explain_sql = build_noncorrelated_sql(
            table_a, table_b, query_vec_a, query_vec_b,
            ctx_uuid, 5, w0, w1, TOP_K, strategy=strategy,
        )
        plan = await run_explain(conn, nc_explain_sql)
        for line in plan.split("\n"):
            log.info(f"    {line}")

    # Also benchmark: correlated across N entities (simulating the real workload)
    log.info(f"\n  --- Correlated across multiple entities (weighted_sum) ---")
    # Fetch 20 random entity UUIDs
    rows = await conn.fetch(
        f"SELECT subject_uuid FROM {table_a} ORDER BY random() LIMIT 20")
    entity_uuids = [str(r['subject_uuid']) for r in rows]

    # Build a query that evaluates the correlated CTE for each entity
    # This simulates what happens when the SPARQL pipeline processes 20 results
    batch_times = []
    for _ in range(NUM_ITERATIONS):
        t0 = time.perf_counter()
        for eid in entity_uuids:
            corr_sql = build_correlated_sql(
                table_a, table_b, query_vec_a, query_vec_b,
                ctx_uuid, f"'{eid}'::uuid", w0, w1,
            )
            await conn.fetch(corr_sql)
        batch_times.append((time.perf_counter() - t0) * 1000)

    batch_p50 = statistics.median(batch_times)
    log.info(f"  [A] Correlated × 20 entities: p50={batch_p50:.2f}ms  "
             f"per-entity={batch_p50/20:.2f}ms  "
             f"all={[f'{t:.1f}' for t in batch_times]}")

    # Compare with single non-correlated query returning 20 results
    nc_sql = build_noncorrelated_sql(
        table_a, table_b, query_vec_a, query_vec_b,
        ctx_uuid, 5, w0, w1, TOP_K,
    )
    nc_times = await time_query(conn, nc_sql, NUM_ITERATIONS)
    nc_p50 = statistics.median(nc_times)
    log.info(f"  [B] NonCorr (1 query, 20 results): p50={nc_p50:.2f}ms")
    log.info(f"  Speedup: {batch_p50/nc_p50:.1f}x" if nc_p50 > 0 else "  (N/A)")

    # Cleanup
    await drop_bench_tables(conn, scale)


async def main():
    parser = argparse.ArgumentParser(description="Multi-vector SQL benchmark")
    parser.add_argument(
        "--scales", default="100,1000,10000",
        help="Comma-separated entity counts (default: 100,1000,10000)")
    parser.add_argument(
        "--dsn", default=DB_DSN,
        help=f"PostgreSQL DSN (default: {DB_DSN})")
    parser.add_argument(
        "--strategies", default="weighted_sum",
        help=f"Comma-separated fusion strategies (default: weighted_sum)")
    parser.add_argument(
        "--dim", type=int, default=VEC_DIM,
        help=f"Vector dimension (default: {VEC_DIM})")
    args = parser.parse_args()

    scales = [int(s.strip()) for s in args.scales.split(",")]
    strategies = [s.strip() for s in args.strategies.split(",")]

    log.info("Multi-Vector SQL Benchmark")
    log.info(f"  DSN: {args.dsn}")
    log.info(f"  Scales: {scales}")
    log.info(f"  Strategies: {strategies}")
    log.info(f"  Dimension: {VEC_DIM}")
    log.info(f"  TOP_K: {TOP_K}")
    log.info(f"  Iterations per query: {NUM_ITERATIONS}")

    conn = await asyncpg.connect(args.dsn)
    try:
        # Verify pgvector
        await conn.execute("SELECT '[1,2,3]'::vector")
        log.info("  pgvector: OK")

        for scale in scales:
            await benchmark_scale(conn, scale, strategies)

        log.info(f"\n{'='*70}")
        log.info("BENCHMARK COMPLETE")
        log.info(f"{'='*70}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
