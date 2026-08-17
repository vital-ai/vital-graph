#!/usr/bin/env python3
"""Remove per-space tables and registry rows belonging to spaces that are gone.

Three kinds of residue, all left by spaces that were dropped before the drop
path knew about every table it had to remove:

  1. ORPHANED TABLES — `{space}_segmentation_jobs` and
     `{space}_document_segmentation_config` for a `{space}` with no
     `{space}_rdf_quad`. These were created ON DEMAND at first use, so
     `drop_space` did not know to remove them: one was added to the explicit
     list, the other was missed entirely. Measured on the local host cluster
     2026-08-15: **1,592 + 47 = 1,639 of 4,366 public tables, 37.5%**, all from
     `inttest_*` / `apitest_*` spaces. The comment in `sparql_sql_schema.py`
     estimated 116 when it was written.

     Both tables are now created with the space and dropped with it, plus a
     self-healing sweep, so nothing new accumulates. This clears the history.

  2. EMPTY ORPHANED SPACES — a full set of per-space tables with no row in
     `space`. Dropped only when they hold NO quads: a space with data and a
     missing registry row is a different problem and this refuses it.

  3. STALE REGISTRY ROWS — a `space` row whose tables are gone.

WHY ABSENCE OF rdf_quad IS THE TEST. Every space gets `{space}_rdf_quad` from
`create_space_tables_sql`, so a per-space table whose sibling `_rdf_quad` does
not exist cannot belong to a live space. That is the whole safety argument, and
it is why this only ever looks at suffixes it knows.

    python scripts/cleanup_orphan_space_tables.py --dry-run          # default
    python scripts/cleanup_orphan_space_tables.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vitalgraph_sparql_sql_dev.db import add_pg_arguments, describe_target  # noqa: E402

def global_tables() -> set[str]:
    """Tables belonging to the GLOBAL registries, not to any space.

    Suffix matching alone has a false-positive mode that nearly cost real data:
    `entity_fuzzy_band` ends in `_fuzzy_band`, `entity_registry_geo` ends in
    `_geo`, and `entity_registry_vector_index` ends in `_vector_index`. All
    three parse as "a space called `entity`/`entity_registry` that no longer
    exists", and the first two hold 37,233 rows each — the entity registry's
    fuzzy-matching index. Dropping them would have been silent data loss.

    Read from the registry schema modules rather than listed, for the same
    reason the suffixes are derived: a hardcoded list is what produced every
    leak this script cleans up.
    """
    names: set[str] = set()
    root = pathlib.Path(__file__).resolve().parent.parent / "vitalgraph"
    for mod in ("entity_registry/entity_registry_schema.py",
                "entity_registry/entity_registry_vector_schema.py",
                "agent_registry/agent_registry_schema.py",
                "agent_registry/agent_registry_vector_schema.py"):
        f = root / mod
        if not f.exists():
            continue
        src = f.read_text(encoding="utf-8")
        names |= set(re.findall(
            r"CREATE TABLE IF NOT EXISTS ([a-z_][a-z_0-9]*)", src))
        # Table names held in constants, e.g. GEO_TABLE = "entity_registry_geo"
        names |= set(re.findall(r'^[A-Z_]+TABLE[A-Z_]* = "([a-z_0-9]+)"',
                                src, re.M))
    # The registries also own anything under their own namespace.
    names |= {"entity_fuzzy_hash", "entity_location", "entity_relationship"}
    return names


def per_space_suffixes() -> list[str]:
    """Every per-space table suffix, DERIVED from the schema, not listed here.

    A hardcoded list is what created this mess. `drop_space` kept one, tables
    were added to the schema without being added to it, and each such table
    leaked once per space dropped thereafter. The first version of THIS script
    repeated the mistake: it listed two suffixes, cleaned 1,639 tables, and left
    25 `_edge_fanout` and 24 `_rdf_value_stats` orphans behind — added to the
    schema later than the spaces that leaked them.

    Deriving from `get_table_names` means a suffix cannot be forgotten. rdf_quad
    is excluded because its presence is what defines a live space.
    """
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    names = SparqlSQLSchema.get_table_names("\x00SPACE\x00")
    out = []
    for full in names.values():
        sfx = full.replace("\x00SPACE\x00", "")
        if sfx and sfx != "_rdf_quad":
            out.append(sfx)
    return sorted(set(out), key=len, reverse=True)


async def survey(conn):
    live = {r["s"] for r in await conn.fetch(
        "SELECT replace(tablename, '_rdf_quad', '') AS s FROM pg_tables "
        "WHERE schemaname='public' AND tablename LIKE '%\\_rdf\\_quad'")}
    all_tables = [r["tablename"] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")]

    # A table is orphaned when it carries a known per-space suffix and the
    # space that prefix names has no rdf_quad. Longest suffix first, so
    # `_rdf_pred_stats` is not mistaken for `_rdf_stats`'s prefix.
    suffixes = per_space_suffixes()
    globals_ = global_tables()
    global_prefixes = ("entity_registry", "agent_registry", "entity_", "agent_")
    orphan_tables = []
    for name in all_tables:
        if name in globals_:
            continue
        for sfx in suffixes:
            if name.endswith(sfx):
                prefix = name[: -len(sfx)]
                if prefix in live:
                    break
                # A global registry table can end in a per-space suffix by
                # coincidence. Never infer a space from one.
                if name.startswith(global_prefixes) and prefix not in live:
                    break
                orphan_tables.append(name)
                break

    orphan_spaces = []
    for r in await conn.fetch(
            """
            SELECT replace(t.tablename, '_rdf_quad', '') AS s
            FROM pg_tables t
            WHERE t.schemaname = 'public' AND t.tablename LIKE '%\\_rdf\\_quad'
              AND NOT EXISTS (SELECT 1 FROM space sp
                              WHERE sp.space_id = replace(t.tablename, '_rdf_quad', ''))
            ORDER BY 1
            """):
        sid = r["s"]
        quads = await conn.fetchval(f'SELECT count(*) FROM "{sid}_rdf_quad"')
        n = await conn.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
            "AND tablename LIKE $1", f"{sid}\\_%")
        orphan_spaces.append({"space": sid, "quads": quads, "tables": n})

    stale_rows = [r["space_id"] for r in await conn.fetch(
        """
        SELECT sp.space_id FROM space sp
        WHERE NOT EXISTS (SELECT 1 FROM pg_tables t WHERE t.schemaname='public'
                          AND t.tablename = sp.space_id || '_rdf_quad')
        ORDER BY sp.space_id
        """)]
    return orphan_tables, orphan_spaces, stale_rows


async def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually drop; default is a report only")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit no-op form of the default, for symmetry "
                         "with the other migrate_* scripts")
    add_pg_arguments(ap)
    a = ap.parse_args()
    print(f"🗄  target: {describe_target(a)}", flush=True)

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        total = await conn.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        tables, spaces, rows = await survey(conn)

        print(f"{a.host}:{a.port}/{a.database} — {total:,} public tables\n")
        print(f"1. orphaned on-demand tables : {len(tables):,}")
        for t in tables[:5]:
            print(f"      {t}")
        if len(tables) > 5:
            print(f"      ... and {len(tables) - 5:,} more")

        empty = [s for s in spaces if s["quads"] == 0]
        with_data = [s for s in spaces if s["quads"] > 0]
        print(f"\n2. orphaned spaces (no space row) : {len(spaces)}")
        for s in spaces:
            mark = "EMPTY, will drop" if s["quads"] == 0 else "HAS DATA — REFUSED"
            print(f"      {s['space']}: {s['quads']:,} quads, "
                  f"{s['tables']} tables  [{mark}]")

        print(f"\n3. stale space rows (no tables) : {len(rows)}")
        for r in rows[:5]:
            print(f"      {r}")
        if len(rows) > 5:
            print(f"      ... and {len(rows) - 5} more")

        if with_data:
            print("\nNOTE: an orphaned space holding data is NOT schema debris. "
                  "It is left alone; decide what it is before removing it.")

        if not a.apply:
            print("\n(dry run — nothing changed; pass --apply to act)")
            return

        print("\napplying...")
        for i, t in enumerate(tables, 1):
            await conn.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')
            if i % 250 == 0:
                print(f"   dropped {i:,}/{len(tables):,}")
        print(f"   dropped {len(tables):,} orphaned table(s)")

        from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
        for s in empty:
            await SparqlSQLSchema.drop_space(conn, s["space"])
            print(f"   dropped empty orphaned space {s['space']}")

        if rows:
            await conn.execute("DELETE FROM space WHERE space_id = ANY($1)", rows)
            print(f"   removed {len(rows)} stale space row(s)")

        now = await conn.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        print(f"\npublic tables: {total:,} -> {now:,} ({total - now:,} removed)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
