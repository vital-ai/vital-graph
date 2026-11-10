#!/usr/bin/env python
"""Rebuild the edge endpoint indexes as COVERING indexes.

    idx_{space}_edge_dst_src  (dest_node_uuid, source_node_uuid)
 -> (dest_node_uuid, source_node_uuid) INCLUDE (context_uuid, edge_uuid, edge_type_uuid)

and the same for idx_{space}_edge_src_dst.

Why: a hop reads the edge's context and edge uuid, which the old indexes did
not carry, so every hop fetched the heap row. Walking three hops up from
100,000 slots (lead 100k, `high_rated_edge_count`) re-read ~400,000 heap pages
on EVERY run: 15-20 s steady state, 4.5 s with the covering index, the plan
otherwise unchanged. Size: 320 MB -> 524 MB per index on 5.3M edges.

Safety, as `migrate_quad_ctx_pred_index.py`:

  * CREATE INDEX CONCURRENTLY / DROP INDEX CONCURRENTLY, no write-blocking
    lock, each step outside a transaction block.
  * The replacement is built under a temporary name, then the old index is
    dropped and the new one renamed. The space always has a usable index.
  * Idempotent: an index that already has the INCLUDE clause is skipped.
  * --dry-run prints the plan and touches nothing.
  * INVALID leftovers from an interrupted run are reported, not reused.
  * A PARTITIONED edge table is reported and skipped: PostgreSQL cannot build
    an index CONCURRENTLY on a partitioned parent.

    python scripts/migrate_edge_endpoint_covering.py --dsn "..." --dry-run
    python scripts/migrate_edge_endpoint_covering.py --dsn "..." --space <space>
    python scripts/migrate_edge_endpoint_covering.py --dsn "..."          # all spaces

Run it as the APP ROLE: the index must be owned by the role that owns the
table, and objects the RDS master creates are unusable by the app role.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# The repo root ahead of site-packages, as the sibling migrations do: the
# installed package resolves another cluster's defaults.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402
from devtools.target import dsn  # noqa: E402
from vitalgraph.db.sparql_sql.space_names import space_id_for_prefix, space_prefix  # noqa: E402
from vitalgraph.db.sparql_sql.space_storage_key import load_storage_keys  # noqa: E402
from vitalgraph.db.sparql_sql.sparql_sql_schema import EDGE_ENDPOINT_INCLUDE  # noqa: E402

#: index suffix -> its key columns
INDEXES = {
    "_edge_dst_src": "(dest_node_uuid, source_node_uuid)",
    "_edge_src_dst": "(source_node_uuid, dest_node_uuid)",
}


async def find_targets(conn, only_space: str | None):
    """[(space_id, index_name, key_columns, already_covering)]"""
    out = []
    for suffix, keys in INDEXES.items():
        rows = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname LIKE $1 ORDER BY indexname",
            "idx\\_%" + suffix.replace("_", "\\_"))
        for r in rows:
            idx = r["indexname"]
            space = space_id_for_prefix(idx[len("idx_"):-len(suffix)])
            if not space or (only_space and space != only_space):
                continue
            out.append((space, idx, keys, "INCLUDE" in r["indexdef"]))
    return out


async def check_invalid(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE NOT i.indisvalid AND (c.relname LIKE '%edge\\_dst\\_src%' "
        "OR c.relname LIKE '%edge\\_src\\_dst%')")
    return [r["relname"] for r in rows]


async def migrate_index(conn, space: str, index_name: str, table: str, keys: str,
                        dry_run: bool) -> None:
    tmp = f"{index_name}_migrating"
    steps = [
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {tmp} ON {table} {keys} "
        f"INCLUDE {EDGE_ENDPOINT_INCLUDE}",
        f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}",
        f"ALTER INDEX {tmp} RENAME TO {index_name}",
    ]
    if dry_run:
        for s in steps:
            print(f"    would run: {s}")
        return
    t0 = time.time()
    for s in steps:
        await conn.execute(s)
    size = await conn.fetchval(
        "SELECT pg_size_pretty(pg_relation_size($1::regclass))", index_name)
    print(f"    done {space}: {index_name} rebuilt in {time.time() - t0:.1f}s "
          f"(now {size})")



#: The maintenance job's fences (`maintenance_job.maintenance_timeouts`): the
#: role's read-path defaults (production: 60 s statement, 10 s lock) would
#: abort this script's long statements part-way.
async def _lift_timeouts(conn) -> None:
    from vitalgraph.process.maintenance_job import (
        MAINTENANCE_LOCK_TIMEOUT_MS, MAINTENANCE_STATEMENT_TIMEOUT_MS)
    await conn.execute(f"SET statement_timeout = {MAINTENANCE_STATEMENT_TIMEOUT_MS}")
    await conn.execute(f"SET lock_timeout = {MAINTENANCE_LOCK_TIMEOUT_MS}")


async def run(target: str, only_space: str | None, dry_run: bool) -> int:
    # autocommit: CONCURRENTLY cannot run inside a transaction block.
    conn = await asyncpg.connect(target)
    # Before anything: a CREATE INDEX CONCURRENTLY cut off by a statement
    # timeout leaves an INVALID index behind, to be dropped by hand.
    await _lift_timeouts(conn)
    await load_storage_keys(conn)
    try:
        db = await conn.fetchval("SELECT current_database()")
        host = await conn.fetchval("SELECT inet_server_addr()::text")
        print(f"target: {db} on {host or 'local socket'}"
              f"{'  [DRY RUN]' if dry_run else ''}\n")

        invalid = await check_invalid(conn)
        if invalid:
            print("INVALID indexes from an interrupted run; drop these before retrying:")
            for name in invalid:
                print(f"      DROP INDEX CONCURRENTLY {name};")
            return 2

        targets = await find_targets(conn, only_space)
        if not targets:
            print("no edge endpoint indexes found"
                  + (f" for space {only_space}" if only_space else ""))
            return 0
        todo = [t for t in targets if not t[3]]
        print(f"{len(targets)} index(es): {len(todo)} to rebuild, "
              f"{len(targets) - len(todo)} already covering\n")

        for space, idx, keys, _ in todo:
            table = f"{space_prefix(space)}_edge"
            kind = await conn.fetchval(
                "SELECT relkind FROM pg_class WHERE relname = $1", table)
            if kind is None:
                print(f"  skip {space}: {table} missing")
                continue
            if kind == "p":
                print(f"  skip {space}: {table} is partitioned; CONCURRENTLY "
                      f"cannot build on a partitioned parent")
                continue
            size = await conn.fetchval(
                "SELECT pg_size_pretty(pg_relation_size($1::regclass))", idx)
            print(f"  {space}: rebuilding {idx} (currently {size})")
            await migrate_index(conn, space, idx, table, keys, dry_run)
        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=None,
                    help="postgresql://... (defaults to VG_TEST_PG_* env)")
    ap.add_argument("--space", action="append", help="migrate only this space")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.space and len(a.space) > 1:
        ap.error("--space was given more than once; this script works on one space")
    return asyncio.run(run(a.dsn or dsn(), a.space[0] if a.space else None, a.dry_run))


if __name__ == "__main__":
    sys.exit(main())
