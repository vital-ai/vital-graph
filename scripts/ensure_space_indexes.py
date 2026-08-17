#!/usr/bin/env python3
"""Create any index a space is missing relative to the schema.

The schema is the definition; this replays it. `CREATE INDEX IF NOT EXISTS` is
idempotent, so the safe thing is to run every statement rather than to compute
a diff and run the subset — a diff is one more place to be wrong, and mine was:
a scratch version of this reported "0 to create" for an index that provably did
not exist, and the fixture stayed six indexes short through two more runs.

Why this is needed at all: bulk loading drops secondary indexes and rebuilds
them at the end (`load_wordnet_csv.py`). A load that is interrupted between
those two steps leaves the space indexed by nothing but its primary keys, and
nothing announces it. `sp_lead_synth_100k` sat that way through a full
comparator sweep whose numbers were then reported as results — without
`term_tt`, one predicate-URI lookup inside an EXISTS body seq-scanned 3.5M rows.

    python scripts/ensure_space_indexes.py --space sp_lead_synth_100k
    python scripts/ensure_space_indexes.py --space sp_lead_synth_100k --dry-run

Connection comes from the VG_TEST_PG_* variables, same as
tests/performance/conftest.py. See issues/055 for why that matters.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vitalgraph_sparql_sql_dev.db import pg_kwargs  # noqa: E402

_NAME_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>\w+)\s+ON\s+(?P<table>\S+?)[\s(]",
    re.IGNORECASE)


def _mentions_present_table(stmt: str, tables: set) -> bool:
    """Does a non-CREATE-INDEX statement target a table this space has?

    Used for the ALTER TABLE ... SET STATISTICS and CREATE STATISTICS forms,
    where the table name is not in a fixed position. Matching by containment is
    good enough because every name here is space-prefixed and therefore unique.
    """
    return any(t in stmt for t in tables)


def pg_env() -> dict:
    return dict(
        **pg_kwargs(),
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what is missing without creating anything")
    ap.add_argument("--no-analyze", action="store_true",
                    help="skip the ANALYZE afterwards")
    a = ap.parse_args()

    import asyncpg
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

    conn = await asyncpg.connect(**pg_env())
    try:
        stmts = SparqlSQLSchema().create_space_indexes_sql(a.space)

        have = {r["indexname"] for r in await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
            "AND tablename LIKE $1", f"{a.space}%")}
        tables = {r["tablename"] for r in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename LIKE $1", f"{a.space}%")}

        missing, skipped = [], []
        for stmt in stmts:
            m = _NAME_RE.search(stmt)
            if not m:
                continue
            if m.group("table") not in tables:
                skipped.append((m.group("name"), m.group("table")))
            elif m.group("name") not in have:
                missing.append(m.group("name"))

        print(f"{a.space}: {len(stmts)} schema indexes, "
              f"{len(missing)} missing, {len(skipped)} on absent tables")
        for name in missing:
            print(f"   missing: {name}")
        for name, table in skipped:
            print(f"   skipped: {name} (no table {table})")

        if a.dry_run:
            return 1 if missing else 0

        # Replay everything, not just the diff, and NOT only the CREATE INDEX
        # statements — and do it even when no index is missing.
        # `create_space_indexes_sql` also emits CREATE STATISTICS and
        # ALTER TABLE ... SET STATISTICS, which matter as much as the indexes:
        # without a raised target on the very sparse num_val, range estimation
        # collapses to rows=1 at 100k and a 25-row page times out (issues/056).
        # An earlier revision returned early on "0 missing" and therefore never
        # applied those to a space whose indexes were already complete, which is
        # the common case and the one that needed them.
        created, failed = 0, []
        for stmt in stmts:
            m = _NAME_RE.search(stmt)
            if m and m.group("table") not in tables:
                continue        # index for a table this space does not have
            if not m and not _mentions_present_table(stmt, tables):
                continue        # ALTER/CREATE STATISTICS for an absent table
            t0 = time.time()
            try:
                await conn.execute(stmt)
            except Exception as exc:
                # Keep going and report at the end. A space predating a column
                # (sp_lead_synth_10k has no dt_val) should not stop every later
                # statement from being applied — but it must not be silent
                # either, so it is reported and the exit code is non-zero.
                failed.append((" ".join(stmt.split())[:90], str(exc).strip()))
                continue
            if m and m.group("name") in missing:
                created += 1
                print(f"   created {m.group('name')} in {time.time()-t0:.1f}s",
                      flush=True)

        if not a.no_analyze:
            for table in sorted(tables):
                await conn.execute(f"ANALYZE {table}")
            print(f"analyzed {len(tables)} tables")

        # Verify rather than trust the loop — the failure this script exists to
        # prevent was a create path that reported success while doing nothing.
        still = {r["indexname"] for r in await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
            "AND tablename LIKE $1", f"{a.space}%")}
        unresolved = [n for n in missing if n not in still]

        for stmt, err in failed:
            print(f"FAILED: {stmt}\n        {err}", file=sys.stderr)
        if unresolved:
            print(f"STILL MISSING after create: {unresolved}", file=sys.stderr)
        if unresolved or failed:
            return 1
        print(f"✅ {created} index(es) created, {len(stmts)} statements applied, "
              f"all verified present")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
