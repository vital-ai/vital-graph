#!/usr/bin/env python3
"""Create the index sync queue on existing spaces (issues/291).

New spaces get `{space}_index_sync_queue` and `idx_{space}_isq_due` from
`create_space_tables_sql` / `create_space_indexes_sql`. This creates the same
two objects, from those same definitions, on a space that predates them.

Until a space has the table, writes to it are synced the old way, directly in
a background task (`auto_sync._enqueue_sync` logs that once per space), so the
order of this script and the deploy does not matter.

A new, empty table: nothing is locked but the catalog, and nothing is copied.
Idempotent -- a space that has both objects is skipped.

RUN AS THE TABLES' OWNER, which on production is the app role, not the RDS
master: objects the master creates are unreadable by `vitalgraph_user`.

DEFAULT IS A DRY RUN.

    python scripts/migrate_index_sync_queue.py --all
    python scripts/migrate_index_sync_queue.py --space lead_prod --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# The repo root ahead of site-packages: an installed copy resolves a different
# cluster (see `migrate_quad_ctx_pred_index.py`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_index_sync_queue")


def statements(space_id: str) -> list:
    """The table and its index, from the schema's own definitions."""
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    schema = SparqlSQLSchema()
    table = f"{space_id}_index_sync_queue"
    out = [s for s in schema.create_space_tables_sql(space_id)
           if f"CREATE TABLE IF NOT EXISTS {table} (" in s]
    out += [s for s in schema.create_space_indexes_sql(space_id)
            if f"idx_{space_id}_isq_due " in s]
    if len(out) != 2:
        raise RuntimeError(f"expected the table and one index for {space_id}, found {len(out)}")
    return out


async def missing(conn, space_id: str) -> list:
    out = []
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL",
                               f"{space_id}_index_sync_queue"):
        out.append("table")
    if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL",
                               f"idx_{space_id}_isq_due"):
        out.append("index")
    return out


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="create what is missing (default is a dry run)")
    add_pg_arguments(ap)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(a)}", flush=True)
    logger.info("%s", "APPLY" if a.apply else "DRY RUN")

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        spaces = ([r[0] for r in await conn.fetch(
            "SELECT regexp_replace(tablename, '_rdf_quad$', '') FROM pg_tables "
            "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_quad' "
            "ORDER BY 1")] if a.all else [a.space])
        pending = done = 0
        for sp in spaces:
            need = await missing(conn, sp)
            if not need:
                continue
            pending += 1
            logger.info("%s: create %s", sp, " and ".join(need))
            if a.apply:
                async with conn.transaction():
                    for stmt in statements(sp):
                        await conn.execute(stmt)
                done += 1
        logger.info("\n%d of %d space(s) %s", done if a.apply else pending,
                    len(spaces), "migrated" if a.apply else "need migration")
        if not a.apply and pending:
            logger.info("Dry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
