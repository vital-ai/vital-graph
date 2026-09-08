#!/usr/bin/env python3
"""Add `{space}_frame_prop_sort` to existing spaces and populate it.

The frame twin of `migrate_entity_prop_sort.py`, and everything that script
says about ordering applies here: create and populate BEFORE anything reads,
block first because the gate is a block-list, release only after coverage has
been measured.

SCOPED TO TOP-LEVEL (ASSERTION) FRAMES, which is what the frames listing's
Assertion tab shows. The population is the endpoint's own rule -- an explicit
`hasKGFormType` of Assertion, or no form type and no `hasFrameGraphURI`.

Measured cost of the derivation on the test stack:

    wordnet_frames         8,911,591 quads -> 570,696 rows over 285,348 frames   8.9 s
    lead_nurture_grouped  74,465,500 quads ->       0 rows (no Assertions)      38.2 s

The second is the pathological shape -- 1,200,000 frames every one of which
carries `hasFrameGraphURI`, so the whole cost is proving a negative. It is also
why this is a windowed operation rather than something to run casually.

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

logger = logging.getLogger("migrate_frame_prop_sort")


async def _global_tables(conn, apply: bool) -> str:
    """`prop_sort_block` / `prop_sort_coverage`, which are not per-space."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    made = []
    for name, ddl in SparqlSQLSchema.ADMIN_TABLE_DDL:
        if name not in ("prop_sort_block", "prop_sort_coverage"):
            continue
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            name)
        if exists:
            continue
        if apply:
            await conn.execute(ddl)
        made.append(name)
    return ", ".join(made) if made else "already present"


async def migrate_space(conn, space_id: str, apply: bool) -> dict:
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    from vitalgraph.db.sparql_sql.sync_frame_prop_sort import (
        backfill_frame_prop_sort, frame_prop_sort_coverage)

    table = f"{space_id}_frame_prop_sort"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            f"{space_id}_rdf_quad"):
        return {"space": space_id, "status": "not a space (no rdf_quad)"}

    sch = SparqlSQLSchema()
    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1", table)

    if not exists:
        if not apply:
            return {"space": space_id, "status": "would create + populate"}
        # Partitioning follows the space's own quad table rather than a default,
        # or the new table would be shaped unlike everything beside it.
        parts = await conn.fetchval(
            "SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid=i.inhparent"
            " WHERE c.relname=$1", f"{space_id}_rdf_quad") or 0
        for stmt in sch.create_space_tables_sql(space_id, partition_quads=parts):
            if "frame_prop_sort" in stmt:
                await conn.execute(stmt)
        logger.info("  %s: created (%d partitions)", table, parts)

    # A table created by an EARLIER revision of this script lacks `frame_uri`,
    # which is the sort tie-break and the last column of three indexes. Adding it
    # is not cosmetic: without it the fast path breaks ties on `entity_uuid`, a
    # hash, and a tied page comes back in a different order from the SPARQL query
    # it replaces. Backfilled below by the populate, which rewrites every row.
    if exists and apply:
        await conn.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS frame_uri TEXT")

    # BLOCK BEFORE POPULATING. An empty table with no block is served as
    # complete. The block is per-type and this space has no types resolved yet,
    # so the whole-space block in `slot_sort_block` is what covers the window --
    # the prop-sort gate reads that too, precisely so a restore or a migration
    # cannot block one derived table and forget the other.
    if apply:
        await conn.execute(
            "INSERT INTO slot_sort_block (space_id, entity_type_uuid, reason) "
            "VALUES ($1, NULL, $2) ON CONFLICT DO NOTHING",
            space_id, "frame_prop_sort migration in progress")

    for stmt in sch.create_space_indexes_sql(space_id):
        if "frame_prop_sort" in stmt:
            if apply:
                await conn.execute(stmt)

    if not apply:
        return {"space": space_id, "status": "would populate (table exists)"}

    t0 = time.time()
    rows = await backfill_frame_prop_sort(conn, space_id)

    # ANALYZE, and it is NOT housekeeping. A freshly built table has no
    # statistics, so the planner estimated `rows=15` for 570,696 rows and chose
    # a Sort over the ordered index — 490 ms and 23,767 buffers for the first
    # page of 25. After ANALYZE the same query is an Index Only Scan: 0.3 ms and
    # 5 buffers. Without this the fast path is slower than the query it
    # replaces until autovacuum happens to get there.
    await conn.execute(f"ANALYZE {table}")
    elapsed = round(time.time() - t0, 1)

    gaps = await frame_prop_sort_coverage(conn, space_id)
    if gaps:
        return {"space": space_id, "rows": rows, "seconds": elapsed,
                "status": f"LEFT BLOCKED — coverage short on {len(gaps)} type(s): "
                          f"{gaps[:2]}. Investigate before releasing."}

    # Released only now, and only because coverage was measured rather than
    # assumed. `issues/149` had the sibling reporting converged at 1.05%.
    await conn.execute(
        "DELETE FROM slot_sort_block WHERE space_id = $1 AND entity_type_uuid IS NULL "
        "AND reason = $2", space_id, "frame_prop_sort migration in progress")
    return {"space": space_id, "rows": rows, "seconds": elapsed,
            "status": "POPULATED, coverage complete, unblocked"}


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
        logger.info("  global tables: %s", await _global_tables(conn, args.apply))
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
