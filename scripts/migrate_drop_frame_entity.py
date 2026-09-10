#!/usr/bin/env python3
"""Drop `{space}_frame_entity`, which nothing builds or reads any more.

`frame_entity` named two `hasKGSlotType` VALUES in its column names
(`source_entity_uuid`, `dest_entity_uuid`) and its builder filtered to them, so
it could only ever serve frames using those two roles. A survey of the local
cluster found **26 of 29 spaces with slot types use other role values** — some
with 180+ distinct ones — so the table has been empty or partial, and the frame
collapse unavailable, for most spaces since it shipped (`issues/183`).

`{space}_frame_slot` replaces it: one row per (frame, slot) with the role as
data, any role value, any arity. The rewrite reads the role constants out of the
query.

ORDER MATTERS. Run `scripts/migrate_frame_slot_table.py --all --apply` FIRST.
This script refuses a space whose `frame_slot` is absent or empty, because
dropping the old table before the new one is built would leave the space with no
collapse at all — correct answers, much slower. That check is why this is a
separate script rather than a step in the other one.

DEFAULT IS A DRY RUN.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_drop_frame_entity")


async def drop_space(conn, space_id: str, apply: bool, force: bool) -> dict:
    t_fe = f"{space_id}_frame_entity"
    t_fs = f"{space_id}_frame_slot"

    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", t_fe):
        return {"space": space_id, "status": "already gone"}

    fs_ok = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", t_fs)
    fs_rows = await conn.fetchval(f"SELECT count(*) FROM {t_fs}") if fs_ok else 0
    fe_rows = await conn.fetchval(f"SELECT count(*) FROM {t_fe}")

    if not fs_rows and not force:
        # A space with no frames at all has neither table populated, and that is
        # fine — but it is indistinguishable here from "the replacement was
        # never built", which is not. --force says you have checked.
        return {"space": space_id,
                "status": f"REFUSED: {t_fs} absent or empty (frame_entity has "
                          f"{fe_rows} rows). Run migrate_frame_slot_table.py "
                          f"first, or --force if this space has no frames."}

    if not apply:
        return {"space": space_id,
                "status": f"would drop ({fe_rows} rows); frame_slot has {fs_rows}"}

    await conn.execute(f"DROP TABLE IF EXISTS {t_fe} CASCADE")
    return {"space": space_id, "dropped": fe_rows, "frame_slot_rows": fs_rows}


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="actually drop (default is a dry run)")
    ap.add_argument("--force", action="store_true",
                    help="drop even when frame_slot is empty (a space with no "
                         "frames); refused otherwise")
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
        refused = 0
        for sp in spaces:
            r = await drop_space(conn, sp, args.apply, args.force)
            refused += 1 if str(r.get("status", "")).startswith("REFUSED") else 0
            logger.info("  %s", r)
        if refused:
            logger.warning("\n%d space(s) REFUSED — build frame_slot there first.", refused)
        if not args.apply:
            logger.info("\nDry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
