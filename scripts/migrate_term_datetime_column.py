#!/usr/bin/env python3
"""Add the generated `dt_val` column to a space's term table.

`{space}_term.dt_val` is a STORED GENERATED column holding the parsed timestamp
of a datetime literal. Without it, two things do not work on that space:

  * **Datetime range push-down cannot be estimated.** That is the whole reason
    the column is generated rather than an indexed expression — measured on a
    10.4M-term space, PostgreSQL estimated 3,489,209 rows against 99 actual for
    an indexed EXPRESSION (exactly 1/3 of the table, its hardcoded default for
    a comparison it cannot estimate), while an ordinary column gets ordinary
    statistics and estimated 160. See `numeric_term_column` for the full note;
    `dt_val` is the same argument reached differently.
  * **The dt lane of `rdf_value_stats` cannot be built.** `resync_value_stats`
    reads `t.dt_val IS NOT NULL` to find which predicates carry temporal
    values, so a space without the column gets no temporal histograms and every
    datetime criterion reads as unmeasured.

Found by `migrate_space_schema.py`, which reports it as MANUAL and refuses to
act — correctly, because adding a STORED generated column REWRITES the table
and that is not something a schema reconcile should do implicitly.

WHY GENERATED AND NOT WRITE-PATH MAINTAINED, since the cost is real: it cannot
drift. The schema's own note is blunt about the alternative — "an ordinary
column set on insert is the shape of every derived-data defect in this codebase
(issues/041, 043, and an edge table that was 25% incomplete in production)".

COST. `ALTER TABLE ... ADD COLUMN ... STORED` rewrites the table and holds an
ACCESS EXCLUSIVE lock for the duration. Recorded for the sibling `num_val`
column: 3m16s for 10.4M rows. This reports each table's size before acting so
the cost is known rather than discovered.

REQUIRES `vitalgraph_iso_to_utc`, the immutable parser the expression leans on
(a plain CAST is not immutable and cannot be used in a generated column). It
lives in `sparql_sql_admin._VITALGRAPH_ISO_TO_UTC_DDL` and is checked for here
rather than assumed.

    python scripts/migrate_term_datetime_column.py --all --dry-run
    python scripts/migrate_term_datetime_column.py --space wordnet_frames
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vitalgraph_sparql_sql_dev.db import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_term_datetime_column")


async def _has_column(conn, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=$1 AND column_name=$2", table, column))


async def migrate_space(conn, space_id: str, dry_run: bool = True) -> dict:
    from vitalgraph.db.sparql_sql.sparql_sql_schema import (
        DATETIME_TERM_COLUMN, datetime_term_column)

    t_term = f"{space_id}_term"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            t_term):
        return {"space": space_id, "skipped": "no term table"}
    if await _has_column(conn, t_term, DATETIME_TERM_COLUMN):
        return {"space": space_id, "skipped": "already current"}

    est_rows = await conn.fetchval(
        "SELECT reltuples::bigint FROM pg_class WHERE relname=$1", t_term) or 0
    size = await conn.fetchval(
        f"SELECT pg_size_pretty(pg_total_relation_size('{t_term}'))")
    summary = {"space": space_id, "est_rows": est_rows, "size": size}
    if dry_run:
        return summary

    t0 = time.time()
    # The rewrite. One statement, one ACCESS EXCLUSIVE lock.
    await conn.execute(
        f"ALTER TABLE {t_term} ADD COLUMN {datetime_term_column()}")
    # The companion index and statistics target, both copied from
    # create_space_indexes_sql rather than restated — a second definition of
    # either is how the ensure_* modules drifted from the schema.
    await conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{space_id}_term_dt "
        f"ON {t_term} ({DATETIME_TERM_COLUMN})")
    # Sparse column: the default statistics target samples ~30,000 rows and on a
    # table that is 99.99% NULL catches about two non-NULL values, which is not
    # a histogram (issues/056).
    await conn.execute(
        f"ALTER TABLE {t_term} "
        f"ALTER COLUMN {DATETIME_TERM_COLUMN} SET STATISTICS 10000")
    await conn.execute(f"ANALYZE {t_term}")

    summary["seconds"] = round(time.time() - t0, 1)
    summary["dt_values"] = await conn.fetchval(
        f"SELECT count({DATETIME_TERM_COLUMN}) FROM {t_term}")
    return summary


async def spaces_on(conn):
    return [r["tablename"][: -len("_rdf_quad")] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE '%\\_rdf\\_quad' ORDER BY tablename")]


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    add_pg_arguments(ap)
    a = ap.parse_args()
    print(f"🗄  target: {describe_target(a)}", flush=True)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        if not await conn.fetchval(
                "SELECT count(*) FROM pg_proc WHERE proname='vitalgraph_iso_to_utc'"):
            logger.error(
                "vitalgraph_iso_to_utc is not defined in this database. The "
                "generated column cannot be created without it — a plain CAST "
                "is not immutable. Install the admin DDL first.")
            return 1

        targets = await spaces_on(conn) if a.all else [a.space]
        changed = total_rows = 0
        for sid in targets:
            s = await migrate_space(conn, sid, dry_run=a.dry_run)
            if s.get("skipped"):
                continue
            changed += 1
            total_rows += s["est_rows"]
            if a.dry_run:
                logger.info("[dry-run] %s: ~%s rows, %s — table will be REWRITTEN",
                            sid, f"{s['est_rows']:,}", s["size"])
            else:
                logger.info("%s: ~%s rows, %s -> %ss, %s datetime value(s)",
                            sid, f"{s['est_rows']:,}", s["size"], s["seconds"],
                            f"{s['dt_values']:,}")
        logger.info("\n%d space(s) %s of %d examined (~%s term rows)",
                    changed, "need migration" if a.dry_run else "migrated",
                    len(targets), f"{total_rows:,}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
