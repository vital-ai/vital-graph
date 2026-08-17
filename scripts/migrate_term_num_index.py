#!/usr/bin/env python
"""Add the num_val generated column + index to existing spaces (issues/040 W4).

REQUIRED, not optional. The numeric range push-down now emits `num_val >= t`,
so a space without the column fails any numeric range query outright with
`column "num_val" does not exist`. Loud rather than silent, but it does mean
every existing space must be migrated before that code is deployed.

New spaces get the column and index from the schema at creation.

A STORED generated column, not an expression index. PostgreSQL does not consult
statistics for an indexed expression when estimating this predicate — measured
on a 10.4M-term space it estimated 3,489,209 rows against 99 actual, exactly 1/3
of the table, and then hashed the whole entity population instead of driving
from the selective leaf. An ordinary column gets ordinary statistics and an
accurate estimate, and the plan follows: 36,483 buffers/470ms became
7,802/57ms, with cost per matched row at 53.8 against an equality baseline of
52.0.

ADD COLUMN ... STORED rewrites the table: 3m16s for 10.4M terms, 12s for 1.05M.
Plan for that on large spaces — it takes an ACCESS EXCLUSIVE lock for the
duration, so it is not an online migration.

    python scripts/migrate_term_num_index.py --dsn "..." --dry-run
    python scripts/migrate_term_num_index.py --dsn "..." --space wordnet_frames
    python scripts/migrate_term_num_index.py --dsn "..."            # all spaces
    python scripts/migrate_term_num_index.py --dsn "..." --min-terms 100000

Not an online migration: ADD COLUMN ... STORED holds ACCESS EXCLUSIVE while it
rewrites the table. Size the window from the figures above.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vitalgraph_sparql_sql_dev.db import get_connection_params  # noqa: E402

from vitalgraph.db.sparql_sql.sparql_sql_schema import (  # noqa: E402
    numeric_term_column, NUMERIC_TERM_COLUMN)


def _dsn_from_env() -> str:
    """The shared target as a DSN. See `add_pg_arguments` for why the
    defaults are not spelled out here (issues/055)."""
    p = get_connection_params()
    return (f"postgresql://{p['user']}:{p['password']}@"
            f"{p['host']}:{p['port']}/{p['dbname']}")


async def find_targets(conn, only_space: str | None):
    """Return [(space_id, term_table, n_terms, has_index)]."""
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename LIKE '%\\_term' "
        "ORDER BY tablename")
    out = []
    for r in rows:
        table = r["tablename"]
        space = table[:-len("_term")]
        if only_space and space != only_space:
            continue
        has = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name=$1 AND column_name='num_val'", table)
        n = await conn.fetchval(
            f'SELECT count(*) FROM "{table}" WHERE term_type = \'L\'')
        out.append((space, table, n, bool(has)))
    return out


async def check_invalid(conn) -> list[str]:
    rows = await conn.fetch(
        "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE NOT i.indisvalid AND c.relname LIKE '%\\_term\\_num'")
    return [r["relname"] for r in rows]


async def run(dsn: str, only_space: str | None, dry_run: bool,
              min_terms: int) -> int:
    conn = await asyncpg.connect(dsn)      # autocommit — CONCURRENTLY needs it
    try:
        db = await conn.fetchval("SELECT current_database()")
        host = await conn.fetchval("SELECT inet_server_addr()::text")
        print(f"target: {db} on {host or 'local socket'}"
              f"{'  [DRY RUN]' if dry_run else ''}\n")

        invalid = await check_invalid(conn)
        if invalid:
            print("⚠️  INVALID indexes from an interrupted run — drop these "
                  "before retrying:")
            for name in invalid:
                print(f"      DROP INDEX CONCURRENTLY {name};")
            return 2

        targets = await find_targets(conn, only_space)
        if not targets:
            print("no *_term tables found"
                  + (f" for space {only_space}" if only_space else ""))
            return 0

        todo = [t for t in targets if not t[3] and t[2] >= min_terms]
        done = [t for t in targets if t[3]]
        small = [t for t in targets if not t[3] and t[2] < min_terms]

        print(f"{len(targets)} space(s): {len(todo)} to build, "
              f"{len(done)} already present, {len(small)} below "
              f"--min-terms={min_terms:,}\n")
        for space, _t, n, _h in done:
            print(f"  ⏭️  {space}: already has idx_{space}_term_num "
                  f"({n:,} literals)")
        for space, _t, n, _h in small:
            print(f"  ⏭️  {space}: {n:,} literals, below threshold")

        for space, table, n, _h in todo:
            add_col = (f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                       f"{numeric_term_column()}")
            # CONCURRENTLY cannot follow ADD COLUMN in the same transaction-less
            # sequence on a table just rewritten; the column add already took an
            # exclusive lock, so a plain CREATE INDEX costs nothing extra here.
            mk_idx = (f"CREATE INDEX IF NOT EXISTS idx_{space}_term_num "
                      f"ON {table} ({NUMERIC_TERM_COLUMN})")
            print(f"  ➕ {space}: adding num_val + index ({n:,} literals)")
            if dry_run:
                print(f"    would run: {add_col[:110]}…")
                print(f"    would run: {mk_idx}")
                continue
            t0 = time.time()
            await conn.execute(add_col)
            await conn.execute(mk_idx)
            await conn.execute(f"ANALYZE {table}")
            size = await conn.fetchval(
                "SELECT pg_size_pretty(pg_relation_size($1::regclass))",
                f"idx_{space}_term_num")
            print(f"    ✅ {space}: built in {time.time() - t0:.1f}s ({size})")

        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=None,
                    help="postgresql://... (defaults to VG_TEST_PG_* env)")
    ap.add_argument("--space", default=None, help="only this space")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-terms", type=int, default=0,
                    help="skip spaces with fewer literal terms than this — the "
                         "index cannot pay for itself on a tiny space")
    a = ap.parse_args()
    return asyncio.run(run(a.dsn or _dsn_from_env(), a.space, a.dry_run,
                           a.min_terms))


if __name__ == "__main__":
    sys.exit(main())
