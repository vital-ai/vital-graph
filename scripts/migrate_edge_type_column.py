#!/usr/bin/env python3
"""Add `edge_type_uuid` to a space's edge table and backfill it (issues/060).

The edge table collapses entity -> frame -> slot traversals into single rows,
which is why it exists. But it recorded source, dest and context and NOT the edge
type, so telling Edge_hasKGSlot from Edge_hasEntityKGFrame meant joining back to
rdf_quad on edge_uuid — handing back part of the join reduction the table
provides. Measured on a three-hop backward traversal: 700ms untyped, 22s typed
through quad joins.

Two steps, both online-ish:

  ALTER TABLE ... ADD COLUMN   instant; a nullable column with no default does
                               not rewrite the table.
  UPDATE ... FROM rdf_quad     one pass, ROW EXCLUSIVE only, so readers keep
                               running.

The column is NULLABLE on purpose. An edge with hasEdgeSource and
hasEdgeDestination but no vitaltype triple is still an edge, and backfilling it
with an inner join would silently drop it — changing which rows the table
describes rather than only how fast it answers. This reports how many stayed
NULL rather than hiding them.

    python scripts/migrate_edge_type_column.py --space wordnet_frames
    python scripts/migrate_edge_type_column.py --all --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vitalgraph_sparql_sql_dev.db import pg_kwargs  # noqa: E402


def pg_env() -> dict:
    return dict(
        **pg_kwargs(),
    )


async def migrate_space(conn, space: str, dry_run: bool) -> dict:
    from vitalgraph.db.sparql_sql.sync_edge_table import _VITALTYPE_UUID

    t_edge, t_quad = f"{space}_edge", f"{space}_rdf_quad"

    exists = await conn.fetchval(
        "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
        t_edge)
    if not exists:
        return {"space": space, "skipped": "no edge table"}

    has_col = await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=$1 AND column_name='edge_type_uuid'", t_edge)
    rows = await conn.fetchval(f"SELECT count(*) FROM {t_edge}")

    if dry_run:
        return {"space": space, "rows": rows,
                "column": "present" if has_col else "MISSING"}

    t0 = time.time()
    if not has_col:
        # Nullable, no default: a catalogue change, not a table rewrite.
        await conn.execute(
            f"ALTER TABLE {t_edge} ADD COLUMN edge_type_uuid UUID")

    await conn.execute(f"""
        UPDATE {t_edge} e
           SET edge_type_uuid = vt.object_uuid
          FROM {t_quad} vt
         WHERE vt.subject_uuid = e.edge_uuid
           AND vt.context_uuid = e.context_uuid
           AND vt.predicate_uuid = $1
           AND e.edge_type_uuid IS DISTINCT FROM vt.object_uuid
    """, _VITALTYPE_UUID)

    for stmt in (
        f"CREATE INDEX IF NOT EXISTS idx_{space}_edge_type_dst "
        f"ON {t_edge} (edge_type_uuid, dest_node_uuid)",
        f"CREATE INDEX IF NOT EXISTS idx_{space}_edge_type_src "
        f"ON {t_edge} (edge_type_uuid, source_node_uuid)",
    ):
        await conn.execute(stmt)
    await conn.execute(f"ANALYZE {t_edge}")

    untyped = await conn.fetchval(
        f"SELECT count(*) FROM {t_edge} WHERE edge_type_uuid IS NULL")
    return {"space": space, "rows": rows, "untyped": untyped,
            "seconds": round(time.time() - t0, 1)}


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--space")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import asyncpg
    conn = await asyncpg.connect(**pg_env())
    try:
        if a.all:
            spaces = [r["tablename"][:-5] for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename LIKE '%\\_edge' ORDER BY tablename")]
        else:
            spaces = [a.space]

        worst = 0
        for sp in spaces:
            r = await migrate_space(conn, sp, a.dry_run)
            if "skipped" in r:
                continue
            if a.dry_run:
                print(f"  {r['space']:<28} {r['rows']:>10,} rows  "
                      f"column {r['column']}")
            else:
                pct = (100.0 * r["untyped"] / r["rows"]) if r["rows"] else 0.0
                worst = max(worst, pct)
                flag = "  <-- edges with no vitaltype" if r["untyped"] else ""
                print(f"  {r['space']:<28} {r['rows']:>10,} rows  "
                      f"{r['untyped']:>8,} untyped ({pct:.1f}%)  "
                      f"{r['seconds']}s{flag}")
        if worst > 0:
            print("\nUntyped rows are edges carrying hasEdgeSource and "
                  "hasEdgeDestination but no vitaltype triple. They are kept, "
                  "not dropped — a typed traversal simply will not match them.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
