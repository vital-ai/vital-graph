#!/usr/bin/env python3
"""Add `context_uuid` to a space's rdf_stats — the graph the count is for.

`issues/163`. Every generated query is scoped to one graph, but `rdf_stats`
counted `(predicate, object)` across the whole SPACE, so the planner read a
number no query would ever see — inflated by however many graphs share the
pair. These counts are not a report: `choose_direction` compares two ends, and
two ends inflated by DIFFERENT factors can invert the comparison and send the
walk down the larger one.

NOTHING IS BACKFILLED, BECAUSE NOTHING CAN BE. A stored row is a count summed
over graphs; which graphs contributed, and how much each did, is not recoverable
from it. So the existing rows are DISCARDED and the table is recomputed. That is
the cheap option and the exact one — `recompute_stats_tables` rebuilds from the
quads in 13-20 s on production-sized spaces (`issues/142`) — where any
backfill would have had to invent the split.

TRUNCATE BEFORE THE ALTER, for that reason and one more: `ADD COLUMN ... NOT
NULL` needs a value for every existing row, and there is no honest default. On
an empty table the constraint is trivially satisfied.

THE WINDOW IS REAL AND IS WHY THIS RECOMPUTES IN THE SAME TRANSACTION. Absence
from `rdf_stats` means "not in the top N" to every consumer, so a committed
truncate without its rebuild reads as a confident "no selective pairs exist"
rather than as missing data (`issues/103`).

Cost is unchanged for single-graph spaces, and that is measured rather than
assumed: adding the context to the recompute's GROUP BY produced an IDENTICAL
row count on all sixteen single-graph fixtures, up to 1,086,774 pairs. The
three-graph `e2e_test_space` went 9 -> 7 — splitting by graph pushes thin pairs
below the minimum, so the table can shrink.

    python scripts/migrate_rdf_stats_context_column.py --space wordnet_frames --dry-run
    python scripts/migrate_rdf_stats_context_column.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.sync_stats_tables import (  # noqa: E402
    recompute_stats_tables,
)

logger = logging.getLogger("migrate_rdf_stats_context_column")


async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=$1 AND column_name=$2", table, column))


async def migrate_space(conn, space_id: str, dry_run: bool = True) -> dict:
    t = f"{space_id}_rdf_stats"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            t):
        return {"space": space_id, "status": "no such table"}

    if await _has_column(conn, t, "context_uuid"):
        return {"space": space_id, "status": "already migrated"}

    before = await conn.fetchval(f"SELECT count(*) FROM {t}")
    if dry_run:
        return {"space": space_id, "status": "would migrate",
                "rows_discarded": before}

    async with conn.transaction():
        await conn.execute(f"TRUNCATE {t}")
        await conn.execute(f"ALTER TABLE {t} ADD COLUMN context_uuid UUID NOT NULL")
        # The primary key names itself after the table, not after its columns,
        # so it is dropped by discovering it rather than by guessing a name.
        pk = await conn.fetchval(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = to_regclass($1) AND contype = 'p'", t)
        if pk:
            await conn.execute(f'ALTER TABLE {t} DROP CONSTRAINT "{pk}"')
        await conn.execute(
            f"ALTER TABLE {t} ADD PRIMARY KEY "
            f"(predicate_uuid, object_uuid, context_uuid)")
        await recompute_stats_tables(conn, space_id)

    after = await conn.fetchval(f"SELECT count(*) FROM {t}")
    graphs = await conn.fetchval(
        f"SELECT count(DISTINCT context_uuid) FROM {space_id}_rdf_quad")
    return {"space": space_id, "status": "migrated", "graphs": graphs,
            "rows_before": before, "rows_after": after}


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space", help="space id to migrate")
    ap.add_argument("--all", action="store_true", help="every space in the database")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.space and not args.all:
        ap.error("one of --space or --all is required")

    print(f"\U0001F5C4  target: {describe_target(args)}", flush=True)
    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        if args.all:
            spaces = [r[0] for r in await conn.fetch(
                "SELECT replace(tablename,'_rdf_stats','') FROM pg_tables "
                "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_stats' "
                "ORDER BY 1")]
        else:
            spaces = [args.space]
        for sp in spaces:
            logger.info("  %s", await migrate_space(conn, sp, dry_run=args.dry_run))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
