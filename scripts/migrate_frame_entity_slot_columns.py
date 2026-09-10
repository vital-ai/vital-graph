#!/usr/bin/env python3
"""Add `source_slot_uuid` / `dest_slot_uuid` to `{space}_frame_entity` and repopulate.

`frame_entity` collapses six tables into one row per frame, and until now it
discarded the SLOT nodes it passed through. A query that projects `?sourceSlot`
therefore could not use the collapse at all: the rewrite emptied the variable,
which returned a column of NULLs (`issues/178`), so the projection guard has to
decline and the query loses the traversal table.

The values were always in hand — the slot node IS `edge.dest_node_uuid`, joined
on twice to reach the slot's type and its value — and were simply not projected.

Priced in `issues/182`, in combination with dropping redundant type constraints
and the text push of `issues/179`: the reference CONSTRUCT goes
15,736,126 -> 12,924 buffers. Alone it is worth far less; the three compose.

A space that is NOT migrated keeps working: the columns are absent, the rewrite
finds no mapping, the guard declines, and the query is correct but slower —
exactly today's behaviour.

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

logger = logging.getLogger("migrate_frame_entity_slot_columns")


async def migrate_space(conn, space_id: str, apply: bool) -> dict:
    t_fe = f"{space_id}_frame_entity"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", t_fe):
        return {"space": space_id, "status": "no frame_entity table"}

    have = await conn.fetchval(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name=$1 AND column_name IN ('source_slot_uuid','dest_slot_uuid')",
        t_fe)
    if have == 2:
        stale = await conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM {t_fe} "
            f"WHERE source_slot_uuid IS NULL AND dest_slot_uuid IS NULL)")
        if not stale:
            return {"space": space_id, "status": "already migrated and populated"}
        if not apply:
            return {"space": space_id, "status": "columns present, would REPOPULATE"}
    elif not apply:
        return {"space": space_id, "status": "would add columns + repopulate"}

    if have < 2:
        await conn.execute(f"ALTER TABLE {t_fe} ADD COLUMN IF NOT EXISTS source_slot_uuid UUID")
        await conn.execute(f"ALTER TABLE {t_fe} ADD COLUMN IF NOT EXISTS dest_slot_uuid UUID")

    # Repopulate through the ONE code path that knows how to build this table.
    # Writing a second builder here is what let `edge_type_uuid` drift in
    # `issues/060`: two sources for one schema, and the inline copy missing a
    # column nothing said was missing.
    from vitalgraph.db.sparql_sql.sync_frame_entity_table import resync_frame_entity_table
    t0 = time.monotonic()
    built = await resync_frame_entity_table(conn, space_id)
    return {"space": space_id, "rows": built,
            "ms": round((time.monotonic() - t0) * 1000)}


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="add columns and repopulate (default is a dry run)")
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
            "SELECT replace(tablename,'_frame_entity','') FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE '%\\_frame\\_entity' "
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
