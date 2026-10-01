#!/usr/bin/env python3
"""Separate network round-trip cost from server time for an entity fuzzy query.

Measured from a laptop to RDS, `find_similar` latency is dominated by RTT:
`query_bands_progressive` issues one statement per batch of 3 bands, across up to
three escalating stages, and each is a separate round trip. The server runs in
the same region as the database and pays a fraction of this.

Reports: baseline RTT, the number of round trips a query actually makes, and the
implied server-side time.

Usage: entity_query_roundtrips.py <host> <db> <user>   (password in PGPASSWORD)
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

from vitalgraph.entity_registry import entity_fuzzy_storage as efs
from vitalgraph.entity_registry.entity_fuzzy_pg import EntityFuzzyIndexPG


async def rtt(pool, n=10):
    samples = []
    for _ in range(n):
        async with pool.acquire() as conn:
            t0 = time.perf_counter()
            await conn.fetchval("SELECT 1")
            samples.append((time.perf_counter() - t0) * 1000)
    return min(samples), statistics.median(samples), max(samples)


async def main():
    host, db, user = sys.argv[1], sys.argv[2], sys.argv[3]
    pool = await asyncpg.create_pool(
        host=host, port=5432, database=db, user=user,
        password=os.environ['PGPASSWORD'], ssl='require',
        min_size=2, max_size=4, statement_cache_size=0,
    )
    try:
        lo, md, hi = await rtt(pool)
        print(f"baseline RTT (SELECT 1, 10 runs): min={lo:.1f} med={md:.1f} max={hi:.1f} ms")
        print()

        # Count round trips by wrapping the two storage methods that issue SQL.
        counter = {'n': 0, 'sql_ms': 0.0}
        orig_qb = efs.PostgreSQLFuzzyStorage.query_bands

        async def counting_query_bands(self, *a, **kw):
            counter['n'] += 1
            t0 = time.perf_counter()
            r = await orig_qb(self, *a, **kw)
            counter['sql_ms'] += (time.perf_counter() - t0) * 1000
            return r

        efs.PostgreSQLFuzzyStorage.query_bands = counting_query_bands

        async with pool.acquire() as conn:
            names = [r['primary_name'] for r in await conn.fetch(
                "SELECT primary_name FROM entity WHERE status='active' "
                "AND length(primary_name) BETWEEN 10 AND 30 ORDER BY entity_id LIMIT 1")]
            ph = [r['primary_name'] for r in await conn.fetch(
                "SELECT primary_name FROM entity WHERE status='active' "
                "AND primary_name ~ '^company-[0-9]+$' LIMIT 1")]

        idx = EntityFuzzyIndexPG.from_env(pool)
        for label, nm in [('exact', names[0])] + ([('placeholder(249)', ph[0])] if ph else []):
            # warm
            await idx.find_similar_by_name(name=nm, limit=10, min_score=50.0)
            for run in range(5):
                counter['n'] = 0
                counter['sql_ms'] = 0.0
                t0 = time.perf_counter()
                res = await idx.find_similar_by_name(name=nm, limit=10, min_score=50.0)
                total = (time.perf_counter() - t0) * 1000
                trips = counter['n']
                print(f"{label:<18} run{run+1}  total={total:8.1f} ms  "
                      f"band_queries={trips:3d}  in_band_sql={counter['sql_ms']:8.1f} ms  "
                      f"est_rtt_overhead={trips * md:7.1f} ms  results={len(res)}")
            print()
    finally:
        efs.PostgreSQLFuzzyStorage.query_bands = orig_qb
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
