#!/usr/bin/env python3
"""Measure real entity fuzzy-query latency against a live database.

`get_candidate_ids` escalates in three stages — primary LSH bands, then phonetic
if fewer than DEFAULT_MIN_CANDIDATES were found, then up to 50 typo variants —
so there is no single "typical" number. This times each shape separately:

  exact      a name that is in the registry (stage 1 satisfies it)
  typo       one character changed (forces escalation)
  rare       a long unusual name (likely all three stages)
  placeholder  issues/249's collapsed names, if present

Read-only: find_similar issues SELECTs only.

Usage: entity_query_latency.py <host> <db> <user>   (password in PGPASSWORD)
"""
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

import asyncpg

from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG

RUNS = 5


async def timed(idx, name, runs=RUNS):
    """Return (min, median, max, n_results) in ms. First call is reported apart."""
    samples = []
    n = 0
    for _ in range(runs):
        t0 = time.perf_counter()
        res = await idx.find_similar_by_name(name=name, limit=10, min_score=50.0)
        samples.append((time.perf_counter() - t0) * 1000)
        n = len(res)
    return min(samples), statistics.median(samples), max(samples), n


async def main():
    host, db, user = sys.argv[1], sys.argv[2], sys.argv[3]
    pool = await asyncpg.create_pool(
        host=host, port=5432, database=db, user=user,
        password=os.environ['PGPASSWORD'], ssl='require',
        min_size=1, max_size=4, statement_cache_size=0,
    )
    try:
        async with pool.acquire() as conn:
            common = await conn.fetch(
                "SELECT primary_name FROM entity WHERE status='active' "
                "AND length(primary_name) BETWEEN 10 AND 30 "
                "ORDER BY entity_id LIMIT 3")
            longish = await conn.fetch(
                "SELECT primary_name FROM entity WHERE status='active' "
                "AND length(primary_name) > 40 ORDER BY entity_id LIMIT 2")
            placeholder = await conn.fetch(
                "SELECT primary_name FROM entity WHERE status='active' "
                "AND primary_name ~ '^company-[0-9]+$' LIMIT 2")

        cases = []
        for r in common:
            cases.append(('exact', r['primary_name']))
        for r in common[:2]:
            nm = r['primary_name']
            mid = len(nm) // 2
            cases.append(('typo', nm[:mid] + ('x' if nm[mid] != 'x' else 'y') + nm[mid + 1:]))
        for r in longish:
            cases.append(('rare/long', r['primary_name']))
        for r in placeholder:
            cases.append(('placeholder(249)', r['primary_name']))

        # One cold pass: a fresh index, empty _entity_cache, as a new worker sees it.
        cold_idx = EntityFuzzyIndexPG.from_env(pool)
        if cases:
            label, nm = cases[0]
            t0 = time.perf_counter()
            res = await cold_idx.find_similar_by_name(name=nm, limit=10, min_score=50.0)
            cold_ms = (time.perf_counter() - t0) * 1000
            print(f"COLD first query in a fresh process: {cold_ms:8.1f} ms  "
                  f"({len(res)} results)  [{label}] {nm[:40]!r}")
            print()

        idx = EntityFuzzyIndexPG.from_env(pool)
        print(f"{'shape':<18} {'min':>9} {'med':>9} {'max':>9}  {'res':>4}  name")
        print('-' * 88)
        for label, nm in cases:
            lo, md, hi, n = await timed(idx, nm)
            print(f"{label:<18} {lo:9.1f} {md:9.1f} {hi:9.1f}  {n:4d}  {nm[:38]!r}")
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
