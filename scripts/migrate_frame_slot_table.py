#!/usr/bin/env python3
"""Create and populate `{space}_frame_slot` for existing spaces.

`frame_entity` names two `hasKGSlotType` VALUES in its columns
(`source_entity_uuid`, `dest_entity_uuid`) and its builder filters to them, so a
frame schema using different role values — or more than two slots — gets no
collapse and no warning (`issues/183`). `frame_slot` holds the role as data, one
row per (frame, slot), and the rewrite reads the role constants out of the
query.

A space that is NOT migrated keeps working: `ensure_frame_slot_table` reports the
table absent, the rewrite declines, and queries fall back to the quad joins —
correct, just without the collapse.

Cost on `wordnet_frames` (8.9M quads, 285,348 frames): 570,696 rows in ~8.8 s.

DEFAULT IS A DRY RUN.
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

logger = logging.getLogger("migrate_frame_slot_table")


async def migrate_space(conn, space_id: str, apply: bool) -> dict:
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    t_fs = f"{space_id}_frame_slot"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            f"{space_id}_rdf_quad"):
        return {"space": space_id, "status": "not a space (no rdf_quad)"}
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            f"{space_id}_edge"):
        return {"space": space_id, "status": "no edge table — build that first"}

    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", t_fs)
    if exists:
        n = await conn.fetchval(f"SELECT count(*) FROM {t_fs}")
        if n and not apply:
            return {"space": space_id, "status": f"already present, {n} rows"}
    if not apply:
        return {"space": space_id,
                "status": "would create + populate" if not exists
                          else "would repopulate"}

    sch = SparqlSQLSchema()
    if not exists:
        # Partitioning follows the space's own quad table rather than a default,
        # or the new table is shaped unlike everything beside it.
        parts = await conn.fetchval(
            "SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhparent"
            " WHERE c.relname=$1", f"{space_id}_rdf_quad") or 0
        for stmt in sch.create_space_tables_sql(space_id, partition_quads=parts):
            if "_frame_slot" in stmt:
                await conn.execute(stmt)
    for stmt in sch.create_space_indexes_sql(space_id):
        if "_frame_slot" in stmt:
            await conn.execute(stmt)

    from vitalgraph.db.sparql_sql.sync_frame_slot_table import resync_frame_slot_table
    t0 = time.monotonic()
    built = await resync_frame_slot_table(conn, space_id)
    return {"space": space_id, "rows": built,
            "ms": round((time.monotonic() - t0) * 1000)}


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="create and populate (default is a dry run)")
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
        await conn.execute("SET statement_timeout='1800s'")
        spaces = ([r[0] for r in await conn.fetch(
            "SELECT replace(tablename,'_rdf_quad','') FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_quad' "
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
