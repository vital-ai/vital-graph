#!/usr/bin/env python3
"""Add `object_count` to a space's rdf_pred_stats: distinct objects per predicate.

`issues/293`, stage 1 of its general solution. `row_count / object_count` is a
predicate's mean subjects per object, which is what a probe BY OBJECT returns.
PostgreSQL cannot see it: its statistics are per column, so it estimated a
`hasKGGraphURI` probe at ~10 rows where each returns ~1,000 graph members, and
drove 1,159 decisions into 1,261,467 rows. The generator reads this column to
price that probe itself.

The column is NULLABLE and added empty: NULL means "not yet counted", and the
generator falls back to what it had. `ADD COLUMN` without a default is a
catalog change, so the ACCESS EXCLUSIVE lock is momentary. A recompute then
fills it. That is the FULL `recompute_stats_tables`, not just this column: the
column adds 8.1 s to it on a 74.2M-quad space (vg test stack), but the whole
recompute takes ~40 s there and was cancelled by production's 60 s
`statement_timeout` on its large spaces, so it runs with the timeout off
(`issues/304`). `--no-recompute` leaves
the column to the next maintenance cycle.

Run as the role that owns the tables (`vitalgraph_user` on production): ALTER
needs ownership, and `issues/` records what objects owned by the RDS master
cost the app.

    python scripts/migrate_pred_stats_object_count.py --space wordnet_frames --dry-run
    python scripts/migrate_pred_stats_object_count.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.space_names import space_prefix  # noqa: E402
from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys  # noqa: E402
from vitalgraph.db.sparql_sql.sync_stats_tables import recompute_stats_tables  # noqa: E402

logger = logging.getLogger("migrate_pred_stats_object_count")


async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=$1 AND column_name=$2", table, column))


async def migrate_space(conn, space_id: str, dry_run: bool, recompute: bool) -> dict:
    t = f"{space_prefix(space_id)}_rdf_pred_stats"
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", t):
        return {"space": space_id, "status": "no such table"}
    has = await _has_column(conn, t, "object_count")
    filled = has and bool(await conn.fetchval(
        f"SELECT bool_and(object_count IS NOT NULL) FROM {t}"))
    if has and (filled or not recompute):
        return {"space": space_id, "status": "already migrated"}
    if dry_run:
        return {"space": space_id,
                "status": "would recompute" if has else "would add column"}

    import asyncpg
    if not has:
        # A live app reads this table on every query plan (100 ms lock timeout
        # on its side). Bound our wait too, and retry: the lock is momentary.
        for attempt in range(1, 6):
            try:
                async with conn.transaction():
                    await conn.execute("SET LOCAL lock_timeout = '5s'")
                    await conn.execute(
                        f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS object_count BIGINT")
                break
            except (asyncpg.LockNotAvailableError, asyncpg.DeadlockDetectedError) as exc:
                if attempt == 5:
                    raise
                logger.warning("  %s: %s on attempt %d/5; retrying in %ds",
                               space_id, type(exc).__name__, attempt, attempt * 2)
                await asyncio.sleep(attempt * 2)
    out = {"space": space_id, "status": "column added" if not has else "column present"}
    if recompute:
        t0 = time.monotonic()
        async with conn.transaction():
            # The FULL stats recompute, not just this column, so it scans the
            # whole quad table. Production's parameter group sets 60 s and a
            # 76M-quad space takes longer (issues/304). LOCAL so it ends with
            # the transaction; the recompute's own becomes a savepoint.
            await conn.execute("SET LOCAL statement_timeout = 0")
            counts = await recompute_stats_tables(conn, space_id)
        out.update(status="migrated", recompute_s=round(time.monotonic() - t0, 1),
                   predicates=counts.get("pred_stats"),
                   counted=await conn.fetchval(
                       f"SELECT count(*) FROM {t} WHERE object_count IS NOT NULL"))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space", help="space id to migrate")
    g.add_argument("--all", action="store_true", help="every space in the `space` table")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-recompute", action="store_true",
                    help="add the column only; the next maintenance recompute fills it")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(args)}", flush=True)

    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    await load_storage_keys(conn)
    try:
        spaces = ([r[0] for r in await conn.fetch(
                      "SELECT space_id FROM space ORDER BY space_id")]
                  if args.all else [args.space])
        for sp in spaces:
            logger.info("  %s", await migrate_space(
                conn, sp, dry_run=args.dry_run, recompute=not args.no_recompute))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
