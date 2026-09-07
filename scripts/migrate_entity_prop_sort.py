#!/usr/bin/env python3
"""Add `{space}_entity_prop_sort` to existing spaces and populate it.

New spaces get the table, its indexes and the two gate tables from
`SparqlSQLSchema`. This adds them to spaces that predate it, then builds the
contents.

TWO PHASES, AND THE ORDER MATTERS. The table is created and populated BEFORE
anything reads it, and the read gate is a BLOCK-LIST (`prop_sort_block`), so a
space is created blocked and only released once its coverage has been verified.
Absence of a block means SERVE; a table that exists but is empty would therefore
be served as if it were complete, which for a FILTER is a plausible subset rather
than an error. `issues/167` inverted the sibling's gate to a block-list for good
reasons, and this is the cost of that inversion: the migration must block first.

DEFAULT IS A DRY RUN, like every migration script here.

The build is a plain `INSERT ... SELECT` over the quads, so it takes ROW
EXCLUSIVE on the new table and reads the quad table without blocking writers.
On a large space it is still one long statement -- run it when the maintenance
window allows, and note that a space's own `resync_all` would do the same work.
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

logger = logging.getLogger("migrate_entity_prop_sort")


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
    from vitalgraph.db.sparql_sql.sync_entity_prop_sort import (
        backfill_entity_prop_sort, entity_prop_sort_coverage)

    table = f"{space_id}_entity_prop_sort"
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
            if "entity_prop_sort" in stmt:
                await conn.execute(stmt)
        logger.info("  %s: created (%d partitions)", table, parts)

    # BLOCK BEFORE POPULATING. An empty table with no block is served as
    # complete. The block is per-type and this space has no types resolved yet,
    # so the whole-space block in `slot_sort_block` is what covers the window --
    # the prop-sort gate reads that too, precisely so a restore or a migration
    # cannot block one derived table and forget the other.
    if apply:
        await conn.execute(
            "INSERT INTO slot_sort_block (space_id, entity_type_uuid, reason) "
            "VALUES ($1, NULL, $2) ON CONFLICT DO NOTHING",
            space_id, "entity_prop_sort migration in progress")

    for stmt in sch.create_space_indexes_sql(space_id):
        if "entity_prop_sort" in stmt:
            if apply:
                await conn.execute(stmt)

    if not apply:
        return {"space": space_id, "status": "would populate (table exists)"}

    t0 = time.time()
    rows = await backfill_entity_prop_sort(conn, space_id)
    elapsed = round(time.time() - t0, 1)

    gaps = await entity_prop_sort_coverage(conn, space_id)
    if gaps:
        return {"space": space_id, "rows": rows, "seconds": elapsed,
                "status": f"LEFT BLOCKED — coverage short on {len(gaps)} type(s): "
                          f"{gaps[:2]}. Investigate before releasing."}

    # Released only now, and only because coverage was measured rather than
    # assumed. `issues/149` had the sibling reporting converged at 1.05%.
    await conn.execute(
        "DELETE FROM slot_sort_block WHERE space_id = $1 AND entity_type_uuid IS NULL "
        "AND reason = $2", space_id, "entity_prop_sort migration in progress")
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
