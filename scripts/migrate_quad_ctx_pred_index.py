#!/usr/bin/env python
"""Rebuild idx_{space}_quad_ctx_pred with object_uuid as a KEY column.

    (context_uuid, predicate_uuid) INCLUDE (subject_uuid, object_uuid)
 -> (context_uuid, predicate_uuid, object_uuid) INCLUDE (subject_uuid)

Why: in INCLUDE, object_uuid can only be a filter, so graph+predicate+object
queries — every typed-entity listing and slot-value filter — scan the whole
(context, predicate) range. Measured on wordnet_frames (8.58M quads), 25-row
page: 14,876 buffers / 592ms before, 5 buffers / 0.21ms after. See issues/039.

Safety, because this is meant to be run against prod:

  * CREATE INDEX CONCURRENTLY / DROP INDEX CONCURRENTLY — no write-blocking
    lock. Each space is a separate transaction-less step; CONCURRENTLY cannot
    run inside a transaction block.
  * Builds the replacement under a temporary name, then drops the old and
    renames. At no point is the space without a usable index for this shape.
  * Idempotent: a space already migrated is detected by inspecting the index
    definition and skipped.
  * --dry-run prints the plan and touches nothing.
  * Leftover *_migrating indexes from an interrupted run are detected and
    reported rather than silently reused.

    python scripts/migrate_quad_ctx_pred_index.py --dsn "..." --dry-run
    python scripts/migrate_quad_ctx_pred_index.py --dsn "..." --space wordnet_frames
    python scripts/migrate_quad_ctx_pred_index.py --dsn "..."          # all spaces
    python scripts/migrate_quad_ctx_pred_index.py --dsn "..." --create-missing

`--create-missing` also builds the index on spaces that never had one — those
created before the covering index was introduced. It is opt-in because it is a
different operation from a rebuild: it *adds* an index rather than replacing
one, and on a large space that is real disk (707 MB on an 8.58M-quad space,
~74 bytes/quad) plus an ongoing write cost. On the dev host 32 of 35 spaces are
in this state, so running it unqualified is a much bigger commitment than the
rebuild. `--min-quads` skips small spaces, where the index cannot pay for
itself.

A CONCURRENTLY build can fail and leave an INVALID index behind; the script
reports any it finds so they can be dropped before retrying.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import asyncpg
from vitalgraph_sparql_sql_dev.db import get_connection_params  # noqa: E402

OLD_KEYS = "(context_uuid, predicate_uuid)"
NEW_COLS = "(context_uuid, predicate_uuid, object_uuid) INCLUDE (subject_uuid)"


def _dsn_from_env() -> str:
    """The shared target as a DSN. See `add_pg_arguments` for why the
    defaults are not spelled out here (issues/055)."""
    p = get_connection_params()
    return (f"postgresql://{p['user']}:{p['password']}@"
            f"{p['host']}:{p['port']}/{p['dbname']}")


async def find_targets(conn, only_space: str | None):
    """Return [(space_id, index_name, indexdef, already_migrated)]."""
    rows = await conn.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname LIKE '%\\_quad\\_ctx\\_pred' "
        "ORDER BY tablename")
    out = []
    for r in rows:
        idx = r["indexname"]
        space = idx[len("idx_"):-len("_quad_ctx_pred")] if idx.startswith("idx_") else None
        if not space or (only_space and space != only_space):
            continue
        # Already migrated when object_uuid appears among the key columns, i.e.
        # before the INCLUDE clause.
        keys = r["indexdef"].split("INCLUDE")[0]
        out.append((space, idx, r["indexdef"], "object_uuid" in keys))
    return out


async def find_missing(conn, only_space: str | None):
    """Spaces with an rdf_quad table but no *_quad_ctx_pred index at all.

    These predate the covering index. Returns [(space_id, table, n_quads)].
    """
    rows = await conn.fetch(
        "SELECT t.tablename FROM pg_tables t "
        "WHERE t.schemaname = 'public' AND t.tablename LIKE '%\\_rdf\\_quad' "
        "AND NOT EXISTS (SELECT 1 FROM pg_indexes i "
        "                WHERE i.tablename = t.tablename "
        "                AND i.indexname LIKE '%\\_quad\\_ctx\\_pred') "
        "ORDER BY t.tablename")
    out = []
    for r in rows:
        table = r["tablename"]
        space = table[:-len("_rdf_quad")]
        if only_space and space != only_space:
            continue
        # Exact count: these are one-off provisioning decisions, and a
        # reltuples estimate on a never-analyzed table can be -1 or wildly off.
        n = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
        out.append((space, table, n))
    return out


async def check_invalid(conn) -> list[str]:
    """Indexes left INVALID by a failed CONCURRENTLY build."""
    rows = await conn.fetch(
        "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE NOT i.indisvalid AND c.relname LIKE '%quad_ctx_pred%'")
    return [r["relname"] for r in rows]


async def migrate_space(conn, space: str, index_name: str, table: str,
                        dry_run: bool) -> bool:
    tmp = f"{index_name}_migrating"
    steps = [
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {tmp} ON {table} {NEW_COLS}",
        f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}",
        f"ALTER INDEX {tmp} RENAME TO {index_name}",
    ]
    if dry_run:
        for s in steps:
            print(f"    would run: {s}")
        return True

    t0 = time.time()
    for s in steps:
        await conn.execute(s)
    size = await conn.fetchval(
        "SELECT pg_size_pretty(pg_relation_size($1::regclass))", index_name)
    print(f"    ✅ {space}: rebuilt in {time.time() - t0:.1f}s (index now {size})")
    return True


async def run(dsn: str, only_space: str | None, dry_run: bool,
              create_missing: bool = False, min_quads: int = 0) -> int:
    # autocommit: CONCURRENTLY cannot run inside a transaction block.
    conn = await asyncpg.connect(dsn)
    try:
        db = await conn.fetchval("SELECT current_database()")
        host = await conn.fetchval("SELECT inet_server_addr()::text")
        print(f"target: {db} on {host or 'local socket'}"
              f"{'  [DRY RUN]' if dry_run else ''}\n")

        invalid = await check_invalid(conn)
        if invalid:
            print("⚠️  INVALID indexes from a previous interrupted run — drop "
                  "these before retrying:")
            for name in invalid:
                print(f"      DROP INDEX CONCURRENTLY {name};")
            return 2

        targets = await find_targets(conn, only_space)
        if not targets:
            print("no idx_*_quad_ctx_pred indexes found"
                  + (f" for space {only_space}" if only_space else ""))
            # Do not return here when --create-missing is set: a database where
            # *no* space has the index is exactly the case that flag exists for.
            if not create_missing:
                return 0

        todo = [t for t in targets if not t[3]]
        done = [t for t in targets if t[3]]
        print(f"{len(targets)} space(s): {len(todo)} to migrate, "
              f"{len(done)} already migrated\n")
        for space, idx, _, _ in done:
            print(f"  ⏭️  {space}: already has object_uuid as a key column")

        for space, idx, _, _ in todo:
            table = f"{space}_rdf_quad"
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_tables WHERE tablename = $1", table)
            if not exists:
                print(f"  ⚠️  {space}: {table} missing, skipping")
                continue
            size = await conn.fetchval(
                "SELECT pg_size_pretty(pg_relation_size($1::regclass))", idx)
            print(f"  🔧 {space}: rebuilding {idx} (currently {size})")
            await migrate_space(conn, space, idx, table, dry_run)

        if create_missing:
            missing = await find_missing(conn, only_space)
            skipped = [m for m in missing if m[2] < min_quads]
            build = [m for m in missing if m[2] >= min_quads]
            print(f"\n--create-missing: {len(missing)} space(s) without the "
                  f"index, {len(build)} at or above --min-quads={min_quads:,}")
            for space, _, n in skipped:
                print(f"  ⏭️  {space}: {n:,} quads, below threshold")
            for space, table, n in build:
                idx = f"idx_{space}_quad_ctx_pred"
                print(f"  ➕ {space}: creating {idx} ({n:,} quads)")
                if dry_run:
                    print(f"    would run: CREATE INDEX CONCURRENTLY "
                          f"IF NOT EXISTS {idx} ON {table} {NEW_COLS}")
                    continue
                t0 = time.time()
                await conn.execute(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx} "
                    f"ON {table} {NEW_COLS}")
                size = await conn.fetchval(
                    "SELECT pg_size_pretty(pg_relation_size($1::regclass))", idx)
                print(f"    ✅ {space}: created in {time.time() - t0:.1f}s ({size})")

        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=None,
                    help="postgresql://... (defaults to VG_TEST_PG_* env)")
    ap.add_argument("--space", default=None, help="migrate only this space")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--create-missing", action="store_true",
                    help="also build the index on spaces that never had one")
    ap.add_argument("--min-quads", type=int, default=0,
                    help="with --create-missing, skip spaces below this "
                         "quad count (the index cannot pay for itself on "
                         "a tiny space)")
    a = ap.parse_args()
    return asyncio.run(run(a.dsn or _dsn_from_env(), a.space, a.dry_run,
                           a.create_missing, a.min_quads))


if __name__ == "__main__":
    sys.exit(main())
