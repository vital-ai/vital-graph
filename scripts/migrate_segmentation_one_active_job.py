#!/usr/bin/env python3
"""One active segmentation job per document. `issues/174` item 3.

`SegmentationJobManager.enqueue` cancels any pending/in_progress job for a
document and then inserts, as two statements. Under READ COMMITTED a second
enqueue does not see the first one's uncommitted INSERT, so its cancel matches
nothing and both rows land — two active jobs for one document, which
`claim_next` will hand to two workers. Its `FOR UPDATE SKIP LOCKED` prevents two
workers taking the SAME job; it cannot prevent them taking two jobs that should
never have coexisted.

A partial unique index is the right shape here, unlike the one withdrawn in
`issues/175`. That one tried to constrain a general quad store, where any
predicate may legitimately be multi-valued and a unique index would have
silently discarded correct data. This is a job queue the KG layer owns outright:
the invariant is ours to declare and nothing can contradict it.

New spaces get the index from `SparqlSQLSchema`. This adds it to existing ones.
Reports and skips a space whose data already violates it rather than forcing —
duplicates would have to be resolved by choosing which job is authoritative, and
that is not a decision to make silently.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_seg_one_active")


async def migrate_space(conn, space_id: str, apply: bool) -> dict:
    table = f"{space_id}_segmentation_jobs"
    name = f"{table}_one_active_per_document_idx"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            table):
        return {"space": space_id, "status": "no segmentation_jobs table"}
    if await conn.fetchval(
            "SELECT 1 FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid "
            " WHERE c.relname=$1 AND i.indisvalid", name):
        return {"space": space_id, "status": "already enforced"}

    dupes = await conn.fetchval(
        f"SELECT count(*) FROM (SELECT document_uri FROM {table}"
        f" WHERE status IN ('pending','in_progress')"
        f" GROUP BY 1 HAVING count(*) > 1) x")
    if dupes:
        return {"space": space_id, "status": f"BLOCKED — {dupes} document(s) "
                f"already have more than one active job; decide which is "
                f"authoritative and cancel the rest, then re-run"}
    if not apply:
        return {"space": space_id, "status": "would enforce (0 violations)"}

    # CONCURRENTLY: this table is written by a live worker pool, and it cannot
    # run inside a transaction. A failed build leaves an INVALID index that
    # enforces nothing, so it is checked for rather than assumed.
    await conn.execute(
        f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {name} "
        f"ON {table} (document_uri) "
        f"WHERE status IN ('pending', 'in_progress')")
    ok = await conn.fetchval(
        "SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid"
        " WHERE c.relname=$1", name)
    return {"space": space_id,
            "status": "ENFORCED" if ok else f"built INVALID — drop {name} and retry"}


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="create the index (default is a dry run)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.space and not args.all:
        ap.error("one of --space or --all is required")

    print(f"\U0001F5C4  target: {describe_target(args)}", flush=True)
    logger.info("%s", "APPLY" if args.apply else "DRY RUN")

    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        spaces = ([r[0] for r in await conn.fetch(
            "SELECT replace(tablename,'_segmentation_jobs','') FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE '%\\_segmentation\\_jobs' "
            "ORDER BY 1")] if args.all else [args.space])
        for sp in spaces:
            logger.info("  %s", await migrate_space(conn, sp, args.apply))
        if not args.apply:
            logger.info("\nDry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
