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

# Retired per-space tables, newest first. A table belongs here once nothing
# reads it AND its replacement is deployed everywhere that matters.
#
# Order within the list matters only where one references another; these do not,
# and CASCADE covers dependent objects either way.
RETIRED = [
    # `frame_entity` named two `hasKGSlotType` VALUES in its COLUMNS, so a
    # frame schema using different roles got no collapse and no warning.
    # Replaced by `frame_slot`, which carries the role as data (`issues/183`).
    ("frame_entity", "issues/183 — superseded by frame_slot"),
    # Superseded by `search_mapping` / `search_mapping_property`. The
    # `/api/vector-mappings` routes are legacy and already delegate there.
    ("vector_mapping_property", "superseded by search_mapping_property"),
    ("vector_mapping", "superseded by search_mapping"),
]

# Prefixes that are legitimately unrecognisable: one table per user-named index.
DYNAMIC_PREFIXES = ("fts_", "vec_")


async def _spaces(conn, only: str | None) -> list:
    if only:
        return [only]
    return [r["space_id"] for r in
            await conn.fetch("SELECT space_id FROM space ORDER BY space_id")]


async def _tables_for(conn, space_id: str, all_spaces: list) -> list:
    r"""This space's tables, attributed by the LONGEST matching space id.

    `LIKE '<space>\_%'` alone is wrong whenever one space id is a prefix of
    another. With spaces `cardiff_kg` and `cardiff_kg_test`, every table of the
    second matches the first, and `cardiff_kg` then reports `test_frame_entity`
    AND `test_rdf_quad` as unrecognised drift — the second being an ordinary
    schema table.

    The DROP itself survives that (the suffix `test_frame_entity` does not equal
    `frame_entity`, so nothing is removed), but the REPORT is the hazard: it
    invites someone to add `test_frame_entity` to `RETIRED`, and that entry
    would then drop another live space's table. Attribution has to be exact
    before the list can be trusted.
    """
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename LIKE $1 ORDER BY tablename", f"{space_id}\\_%")
    longer = [s for s in all_spaces
              if s != space_id and s.startswith(space_id + "_")]
    out = []
    for r in rows:
        t = r["tablename"]
        if any(t.startswith(s + "_") for s in longer):
            continue          # belongs to a space whose id extends this one
        out.append(t)
    return out


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
        known = set(SparqlSQLSchema().get_table_names("X").keys())
        retired = {name for name, _ in RETIRED}

        total_dropped = 0
        drift: dict = {}
        for sid in spaces:
            present = await _tables_for(conn, sid, spaces)
            suffixes = {t[len(sid) + 1:]: t for t in present}

            for name, why in RETIRED:
                # Partition children are `<table>_p<N>` and CASCADE from the
                # parent, so matching the parent is enough — but the suffix
                # after `_p` must be DIGITS. `startswith(name + "_p")` alone
                # matched `vector_mapping_property` against the `vector_mapping`
                # rule, listing it twice and inflating the count from 34 to 51.
                # Any retired name that is a prefix of another would collide.
                def _is_child(suf: str) -> bool:
                    if not suf.startswith(name + "_p"):
                        return False
                    return suf[len(name) + 2:].isdigit()

                hit = [t for suf, t in suffixes.items()
                       if suf == name or _is_child(suf)]
                for table in sorted(hit):
                    if args.apply:
                        await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                        print(f"  dropped {table}   ({why})")
                    else:
                        print(f"  WOULD DROP {table}   ({why})")
                    total_dropped += 1

            if args.report_drift:
                for suf in suffixes:
                    base = suf.rsplit("_p", 1)[0] if suf.rsplit("_p", 1)[-1].isdigit() else suf
                    if base in known or base in retired:
                        continue
                    if base.startswith(DYNAMIC_PREFIXES):
                        continue
                    drift.setdefault(base, []).append(sid)

        verb = "dropped" if args.apply else "would drop"
        print(f"\n{verb} {total_dropped} retired table(s) across {len(spaces)} space(s)")
        if not args.apply and total_dropped:
            print("DRY RUN — re-run with --apply")

        if args.report_drift:
            if not drift:
                print("\nno drift: every other table is schema or a named index")
            else:
                print("\nUNRECOGNISED (not dropped — triage before adding to RETIRED):")
                for base, sids in sorted(drift.items(), key=lambda kv: -len(kv[1])):
                    print(f"  {base:32s} {len(sids)} space(s)  e.g. {sids[:2]}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
