#!/usr/bin/env python3
"""Drop per-space tables that the schema has RETIRED, from spaces that still have them.

Deleting a space already removes these — `sparql_sql_schema.drop_space_tables`
names the retired ones explicitly and then sweeps anything else matching the
space prefix. But a space that STAYS ALIVE keeps them forever: nothing on the
normal path revisits an existing space's table list when a table is retired.

Measured on the dev stack: `vector_mapping` and `vector_mapping_property` were
still present on **17 of 40 spaces**, superseded by `search_mapping` long ago.

DEFAULT IS A DRY RUN.

    scripts/migrate_drop_retired_tables.py --all                  # report
    scripts/migrate_drop_retired_tables.py --all --apply          # drop
    scripts/migrate_drop_retired_tables.py --all --report-drift   # triage the unknown

WHY AN EXPLICIT LIST AND NOT "ANYTHING NOT IN THE SCHEMA".

Dropping every unrecognised table would be a data-loss bug waiting for its
first victim: `{space}_fts_<name>` and `{space}_vec_<name>` are created per
INDEX with names chosen by the user, so they are unrecognisable by construction
and entirely legitimate. A newer application version's tables would look the
same to an older copy of this script.

So retirement is a decision recorded here, and `--report-drift` exists to show
what is unrecognised WITHOUT touching it, so a human can triage and add to the
list deliberately.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema  # noqa: E402

logger = logging.getLogger("migrate_drop_retired_tables")

async def _spaces(conn, only: str | None) -> list:
    if only:
        return [only]
    return [r["space_id"] for r in
            await conn.fetch("SELECT space_id FROM space ORDER BY space_id")]


async def _tables_for(conn, space_id: str) -> list:
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE $1 ORDER BY tablename", f"{space_id}\\_%")
    return [r["tablename"] for r in rows]


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_pg_arguments(ap)
    ap.add_argument("--space", help="one space; default is every space")
    ap.add_argument("--all", action="store_true", help="every space (explicit)")
    ap.add_argument("--apply", action="store_true",
                    help="actually drop; omitted means dry run")
    ap.add_argument("--report-drift", action="store_true",
                    help="also list tables that are neither schema nor retired")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not (args.space or args.all):
        ap.error("pass --space <id> or --all")

    print(describe_target(args))
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password)
    try:
        spaces = await _spaces(conn, args.space)

        total_dropped = 0
        drift: dict = {}
        seen: set = set()
        for sid in spaces:
            for table in await _tables_for(conn, sid):
                if table in seen:
                    continue
                # THE SCHEMA DECIDES. This script used to carry its own copy of
                # the known suffixes, the dynamic prefixes and the retired
                # names — and a duplicate is how a table comes to be retired in
                # one place and live in another. It also attributes by the
                # LONGEST space id, which is what a plain prefix match gets
                # wrong when one space id extends another.
                info = SparqlSQLSchema.classify_space_table(table, spaces)
                if info["space_id"] != sid:
                    continue          # belongs to a space whose id extends this one
                seen.add(table)
                role = info["role"]
                if role == "retired":
                    if args.apply:
                        await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                        print(f"  dropped {table}   ({info['reason']})")
                    else:
                        print(f"  WOULD DROP {table}   ({info['reason']})")
                    total_dropped += 1
                elif role == "unknown" and args.report_drift:
                    drift.setdefault(info["suffix"], []).append(sid)

        verb = "dropped" if args.apply else "would drop"
        print(f"\n{verb} {total_dropped} retired table(s) across {len(spaces)} space(s)")
        if not args.apply and total_dropped:
            print("DRY RUN — re-run with --apply")

        if args.report_drift:
            if not drift:
                print("\nno drift: every other table is schema or a named index")
            else:
                print("\nUNRECOGNISED (not dropped — triage, then retire it in\n  SparqlSQLSchema._RETIRED_TABLE_SUFFIXES, not here):")
                for base, sids in sorted(drift.items(), key=lambda kv: -len(kv[1])):
                    print(f"  {base:32s} {len(sids)} space(s)  e.g. {sids[:2]}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
