#!/usr/bin/env python3
"""Add `pred_rows` to a space's rdf_value_stats — the freshness reference.

`estimate_range` multiplies a fraction read off the bucket boundaries by the row
count the histogram was built from. Without a reference count there is no way to
tell how far the data has moved since, so a stale histogram is used at face
value. Measured on a scratch space: at 2.00x drift `score >= 10` estimated
53,750 against an actual 107,861, and every error is an UNDERESTIMATE — the
direction that makes a criterion look selective and get applied last.

WHY pred_rows AND NOT total_rows

`total_rows` counts quads with a value in THIS LANE; `rdf_pred_stats` counts
every quad for the predicate. On a mixed-type predicate the two diverge
permanently, which would read as permanently stale. The reference has to be
compared with like, so the pred_stats value as of the build is what gets stored.

BACKFILL IS AN APPROXIMATION, AND SAYS SO

For an existing histogram the count it was built from is not recoverable — that
moment has passed. Backfilling from the CURRENT pred_stats asserts "fresh as of
now", which is wrong by exactly however much has been written since the last
resync. That is the safe direction (it under-reports drift rather than
over-reporting it, so nothing is wrongly declared stale) and it self-corrects on
the next `resync_value_stats`, which writes a true reference.

`--resync` does that rebuild instead, and is preferred where the cost is
acceptable: it is exact rather than approximate. Measured rebuild cost is
seconds, not minutes.

    python scripts/migrate_value_stats_pred_rows.py --space wordnet_frames --dry-run
    python scripts/migrate_value_stats_pred_rows.py --all --resync
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_value_stats_pred_rows")


async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=$1 AND column_name=$2", table, column))


async def migrate_space(conn, space_id: str, dry_run: bool = True,
                        resync: bool = False) -> dict:
    t_vs = f"{space_id}_rdf_value_stats"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            t_vs):
        return {"space": space_id, "skipped": "no rdf_value_stats table"}

    rows = await conn.fetchval(f"SELECT count(*) FROM {t_vs}")
    added = not await _has_column(conn, t_vs, "pred_rows")
    missing = rows if added else await conn.fetchval(
        f"SELECT count(*) FROM {t_vs} WHERE pred_rows IS NULL")
    if not added and not missing:
        return {"space": space_id, "skipped": "already current"}

    summary = {"space": space_id, "rows": rows, "added_column": added,
               "unfilled_before": missing, "mode": "resync" if resync else "backfill"}
    if dry_run:
        return summary

    if added:
        # Nullable with no default: metadata-only on PG11+, no table rewrite.
        await conn.execute(
            f"ALTER TABLE {t_vs} ADD COLUMN IF NOT EXISTS pred_rows BIGINT")

    if resync:
        from vitalgraph.db.sparql_sql.sync_value_stats import resync_value_stats
        summary["resync"] = await resync_value_stats(conn, space_id)
    else:
        await conn.execute(f"""
            UPDATE {t_vs} vs SET pred_rows = ps.row_count
            FROM {space_id}_rdf_pred_stats ps
            WHERE ps.predicate_uuid = vs.predicate_uuid
              AND vs.pred_rows IS DISTINCT FROM ps.row_count
        """)
    await conn.execute(f"ANALYZE {t_vs}")
    summary["unfilled_after"] = await conn.fetchval(
        f"SELECT count(*) FROM {t_vs} WHERE pred_rows IS NULL")
    return summary


async def spaces_on(conn):
    return [r["tablename"][: -len("_rdf_value_stats")] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_rdf\\_value\\_stats' ORDER BY tablename")]


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resync", action="store_true",
                    help="rebuild the histograms instead of backfilling — exact "
                         "rather than approximate")
    add_pg_arguments(ap)
    args = ap.parse_args()
    print(f"🗄  target: {describe_target(args)}", flush=True)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        targets = await spaces_on(conn) if args.all else [args.space]
        changed = 0
        for sid in targets:
            s = await migrate_space(conn, sid, dry_run=args.dry_run,
                                    resync=args.resync)
            if s.get("skipped"):
                continue
            changed += 1
            logger.info("%s%s: %d rows, %s, %d unfilled%s",
                        "[dry-run] " if args.dry_run else "", sid, s["rows"],
                        "ADD COLUMN" if s["added_column"] else "column present",
                        s["unfilled_before"],
                        "" if args.dry_run
                        else f" -> {s['unfilled_after']} still NULL ({s['mode']})")
        logger.info("\n%d space(s) %s of %d examined", changed,
                    "need migration" if args.dry_run else "migrated", len(targets))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
