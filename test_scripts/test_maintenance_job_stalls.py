#!/usr/bin/env python3
"""
Integration test for the MaintenanceJob thread-offload fix.

Verifies that both code paths (psycopg thread-offloaded and asyncpg fallback)
correctly connect, run ANALYZE / VACUUM, and produce identical stats results
against a real local PostgreSQL instance.

What this tests:
  1. _sync_fetch_space_stats (psycopg)  returns the same space aggregations
     as _async_fetch_space_stats (asyncpg).
  2. _sync_run_tables (psycopg + psycopg.sql.Identifier) successfully runs
     ANALYZE and VACUUM on real tables with autocommit=True.
  3. _async_run_tables (asyncpg fallback) does the same.
  4. A full MaintenanceJob.run() cycle completes via the thread-offloaded path,
     picking the right space and running both ANALYZE and VACUUM.

Usage:
    PYTHONPATH=. python test_scripts/test_maintenance_job_stalls.py \\
        [--db-host HOST] [--db-port PORT] [--db-name NAME] \\
        [--db-user USER] [--db-password PW]
"""

import argparse
import asyncio
import logging
import time
from typing import Dict, List, Optional

import asyncpg

# ---------------------------------------------------------------------------
TEST_SPACE_ID = "__maint_test"
TABLE_SUFFIXES = [
    "_term", "_rdf_quad", "_datatype", "_rdf_pred_stats",
    "_rdf_stats", "_edge", "_frame_entity",
]
FILLER_ROWS = 500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_maintenance")

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        logger.info("  ✅ %s%s", label, f" — {detail}" if detail else "")
    else:
        failed += 1
        logger.error("  ❌ %s%s", label, f" — {detail}" if detail else "")


# ═══════════════════════════════════════════════════════════════════════════
# Table setup / teardown
# ═══════════════════════════════════════════════════════════════════════════
async def setup_tables(pool: asyncpg.Pool, baseline_analyze: bool = True):
    """Create 7 test tables and populate.

    Args:
        baseline_analyze: If True, run ANALYZE after initial insert so
            pg_stat_user_tables has last_analyze timestamps.  Set to False
            for full-cycle tests so last_analyze=None → the scoring treats
            the space as stale and actually triggers maintenance.
    """
    async with pool.acquire() as conn:
        for suffix in TABLE_SUFFIXES:
            t = f"{TEST_SPACE_ID}{suffix}"
            await conn.execute(f"DROP TABLE IF EXISTS {t}")
            await conn.execute(f"""
                CREATE TABLE {t} (
                    id serial PRIMARY KEY, data text,
                    ts timestamptz DEFAULT now())
            """)
            await conn.execute(f"""
                INSERT INTO {t} (data)
                SELECT md5(random()::text) FROM generate_series(1, {FILLER_ROWS})
            """)
            if baseline_analyze:
                await conn.execute(f"ANALYZE {t}")

        # Dirty: insert more + delete some → dead tuples for VACUUM
        for suffix in TABLE_SUFFIXES:
            t = f"{TEST_SPACE_ID}{suffix}"
            await conn.execute(f"""
                INSERT INTO {t} (data)
                SELECT md5(random()::text) FROM generate_series(1, {FILLER_ROWS})
            """)
            await conn.execute(f"DELETE FROM {t} WHERE id % 3 = 0")

    # Force stats collector flush (PG 16+) so pg_stat_user_tables is current
    async with pool.acquire() as conn:
        try:
            await conn.execute("SELECT pg_stat_force_next_flush()")
        except Exception:
            pass  # older PG versions — fall back to sleep
    await asyncio.sleep(1.0)


async def teardown_tables(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        for suffix in TABLE_SUFFIXES:
            await conn.execute(f"DROP TABLE IF EXISTS {TEST_SPACE_ID}{suffix}")


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════
async def test_stats_parity(pool, pg_config):
    """_sync_fetch_space_stats and _async_fetch_space_stats return same data."""
    from vitalgraph.process.maintenance_job import MaintenanceJob

    job = MaintenanceJob(pool, postgresql_config=pg_config)

    sync_stats = await asyncio.to_thread(job._sync_fetch_space_stats)
    async_stats = await job._async_fetch_space_stats()

    check("sync stats found test space", TEST_SPACE_ID in sync_stats)
    check("async stats found test space", TEST_SPACE_ID in async_stats)

    if TEST_SPACE_ID in sync_stats and TEST_SPACE_ID in async_stats:
        s = sync_stats[TEST_SPACE_ID]
        a = async_stats[TEST_SPACE_ID]
        check("n_mod_since_analyze matches",
              s["n_mod_since_analyze"] == a["n_mod_since_analyze"],
              f"sync={s['n_mod_since_analyze']} async={a['n_mod_since_analyze']}")
        check("n_dead_tup matches",
              s["n_dead_tup"] == a["n_dead_tup"],
              f"sync={s['n_dead_tup']} async={a['n_dead_tup']}")
        check("last_analyze present in both",
              s["last_analyze"] is not None and a["last_analyze"] is not None)


async def test_sync_analyze_vacuum(pool, pg_config):
    """_sync_run_tables runs ANALYZE and VACUUM via psycopg."""
    from vitalgraph.process.maintenance_job import MaintenanceJob

    job = MaintenanceJob(pool, postgresql_config=pg_config)
    tables = MaintenanceJob._space_tables(TEST_SPACE_ID)

    count_a = await asyncio.to_thread(job._sync_run_tables, "ANALYZE", tables)
    check("sync ANALYZE ran on all tables", count_a == len(tables),
          f"{count_a}/{len(tables)}")

    count_v = await asyncio.to_thread(job._sync_run_tables, "VACUUM", tables)
    check("sync VACUUM ran on all tables", count_v == len(tables),
          f"{count_v}/{len(tables)}")


async def test_async_analyze_vacuum(pool):
    """_async_run_tables runs ANALYZE and VACUUM via asyncpg."""
    from vitalgraph.process.maintenance_job import MaintenanceJob

    job = MaintenanceJob(pool, postgresql_config=None)
    tables = MaintenanceJob._space_tables(TEST_SPACE_ID)

    count_a = await job._async_run_tables("ANALYZE", tables)
    check("async ANALYZE ran on all tables", count_a == len(tables),
          f"{count_a}/{len(tables)}")

    count_v = await job._async_run_tables("VACUUM", tables)
    check("async VACUUM ran on all tables", count_v == len(tables),
          f"{count_v}/{len(tables)}")


async def test_full_cycle_thread(pool, pg_config):
    """Full MaintenanceJob.run() via the thread-offloaded path."""
    from vitalgraph.process.maintenance_job import MaintenanceJob

    job = MaintenanceJob(pool, postgresql_config=pg_config)

    t0 = time.monotonic()
    summary = await job.run()
    elapsed_ms = (time.monotonic() - t0) * 1000

    analyze = summary.get("analyze")
    vacuum = summary.get("vacuum")

    check("full cycle (thread): ANALYZE ran",
          analyze is not None and "tables_analyzed" in (analyze or {}),
          f"{analyze}")
    check("full cycle (thread): VACUUM ran",
          vacuum is not None and "tables_vacuumed" in (vacuum or {}),
          f"{vacuum}")
    check("full cycle (thread): targeted a space",
          (analyze or {}).get("space_id") is not None,
          f"space={(analyze or {}).get('space_id')}")
    logger.info("  ⏱  Full cycle elapsed: %.0fms", elapsed_ms)


async def test_full_cycle_async(pool):
    """Full MaintenanceJob.run() via the asyncpg fallback path."""
    from vitalgraph.process.maintenance_job import MaintenanceJob

    job = MaintenanceJob(pool, postgresql_config=None)

    t0 = time.monotonic()
    summary = await job.run()
    elapsed_ms = (time.monotonic() - t0) * 1000

    analyze = summary.get("analyze")
    vacuum = summary.get("vacuum")

    check("full cycle (async): ANALYZE ran",
          analyze is not None and "tables_analyzed" in (analyze or {}),
          f"{analyze}")
    check("full cycle (async): VACUUM ran",
          vacuum is not None and "tables_vacuumed" in (vacuum or {}),
          f"{vacuum}")
    check("full cycle (async): targeted a space",
          (analyze or {}).get("space_id") is not None,
          f"space={(analyze or {}).get('space_id')}")
    logger.info("  ⏱  Full cycle elapsed: %.0fms", elapsed_ms)


# ═══════════════════════════════════════════════════════════════════════════
async def main(args):
    pg_config = {
        "host": args.db_host,
        "port": args.db_port,
        "database": args.db_name,
        "username": args.db_user,
        "password": args.db_password,
    }

    pool = await asyncpg.create_pool(
        host=pg_config["host"], port=pg_config["port"],
        database=pg_config["database"], user=pg_config["username"],
        password=pg_config["password"] or None,
        min_size=2, max_size=10,
    )

    try:
        async with pool.acquire() as conn:
            ver = await conn.fetchval("SELECT version()")
        logger.info("Connected to %s:%s/%s — %s",
                     pg_config["host"], pg_config["port"],
                     pg_config["database"], ver[:50])

        # ── 1. Stats parity ──────────────────────────────────────
        logger.info("\n--- Test: stats parity (psycopg vs asyncpg) ---")
        await setup_tables(pool)
        await test_stats_parity(pool, pg_config)

        # ── 2. Sync ANALYZE / VACUUM ─────────────────────────────
        logger.info("\n--- Test: sync ANALYZE / VACUUM (psycopg) ---")
        await test_sync_analyze_vacuum(pool, pg_config)

        # ── 3. Async ANALYZE / VACUUM ────────────────────────────
        logger.info("\n--- Test: async ANALYZE / VACUUM (asyncpg) ---")
        await teardown_tables(pool)
        await setup_tables(pool)
        await test_async_analyze_vacuum(pool)

        # ── 4. Full cycle — thread path ──────────────────────────
        # No baseline ANALYZE → last_analyze=None → space scored as stale
        logger.info("\n--- Test: full cycle — thread-offloaded ---")
        await teardown_tables(pool)
        await setup_tables(pool, baseline_analyze=False)
        await test_full_cycle_thread(pool, pg_config)

        # ── 5. Full cycle — async fallback ───────────────────────
        logger.info("\n--- Test: full cycle — async fallback ---")
        await teardown_tables(pool)
        await setup_tables(pool, baseline_analyze=False)
        await test_full_cycle_async(pool)

    finally:
        await teardown_tables(pool)
        await pool.close()

    # ── Summary ──────────────────────────────────────────────────
    print()
    total = passed + failed
    print(f"{'=' * 50}")
    print(f"  {passed}/{total} checks passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print("  — all good ✅")
    print(f"{'=' * 50}")
    return 1 if failed else 0


def parse_args():
    p = argparse.ArgumentParser(
        description="Integration test for MaintenanceJob thread-offload fix")
    p.add_argument("--db-host", default="localhost")
    p.add_argument("--db-port", type=int, default=5432)
    p.add_argument("--db-name", default="fuseki_sql_graph")
    p.add_argument("--db-user", default="postgres")
    p.add_argument("--db-password", default="")
    return p.parse_args()


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main(parse_args())))
