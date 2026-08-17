#!/usr/bin/env python3
"""Rebuild each space's edge table from its quads: types the rows, drops orphans.

Does two jobs in one pass, because they have the same fix:

* **Populates `edge_type_uuid`** (`issues/060`). Without it, telling
  Edge_hasKGSlot from Edge_hasEntityKGFrame needs a join back to a 24 GB quad
  table — measured at 700ms untyped vs 22s typed on a three-hop traversal.
* **Removes orphaned rows.** An edge row whose defining quads have been deleted
  survives in the edge table and answers traversals with an edge to nowhere.
  Found on 41 spaces: 20,306 orphans (5.3%) in one production-shaped space, 100
  of 320 in another. Same mechanism as `issues/041`, opposite direction — that
  was edges MISSING, this is edges left behind.

`resync_edge_table` already rebuilds from the quads, which are the source of
truth, so both fall out of running it: a row that no longer has hasEdgeSource /
hasEdgeDestination quads is simply not regenerated, and every row that is gets
its type from the vitaltype quad.

Why rebuild rather than UPDATE in place: the first version of this ALTERed the
column in and ran `UPDATE ... FROM rdf_quad`. On a 5M-row edge table joined
against 22M quads that was still going after 28 minutes — every row rewritten as
a new version plus index maintenance on six indexes. TRUNCATE + INSERT does the
same work without the row-version churn, and it is the only form that also
clears orphans.

The trade-off, stated plainly: `resync_edge_table` TRUNCATEs, so it holds ACCESS
EXCLUSIVE for the rebuild and blocks edge-rewrite queries meanwhile. That is
fine for maintenance on a host with no traffic; against a live system prefer
`backfill_edge_table` (ROW EXCLUSIVE, adds missing edges without blocking) and
schedule the orphan clear separately.

    python scripts/rebuild_edge_tables.py --all
    python scripts/rebuild_edge_tables.py --space wordnet_frames
    python scripts/rebuild_edge_tables.py --all --dry-run
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


async def _ensure_column(conn, space: str) -> None:
    """Add edge_type_uuid if absent. Nullable, no default: catalogue-only."""
    t_edge = f"{space}_edge"
    has = await conn.fetchval(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=$1 AND column_name='edge_type_uuid'", t_edge)
    if not has:
        await conn.execute(
            f"ALTER TABLE {t_edge} ADD COLUMN edge_type_uuid UUID")
    for stmt in (
        f"CREATE INDEX IF NOT EXISTS idx_{space}_edge_type_dst "
        f"ON {t_edge} (edge_type_uuid, dest_node_uuid)",
        f"CREATE INDEX IF NOT EXISTS idx_{space}_edge_type_src "
        f"ON {t_edge} (edge_type_uuid, source_node_uuid)",
    ):
        await conn.execute(stmt)


async def rebuild(conn, space: str, dry_run: bool) -> dict:
    from vitalgraph.db.sparql_sql.sync_edge_table import resync_edge_table

    t_edge = f"{space}_edge"
    if not await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            t_edge):
        return {}

    before = await conn.fetchval(f"SELECT count(*) FROM {t_edge}")
    if dry_run:
        return {"space": space, "before": before, "after": None}

    t0 = time.time()
    await _ensure_column(conn, space)
    after = await resync_edge_table(conn, space)
    untyped = await conn.fetchval(
        f"SELECT count(*) FROM {t_edge} WHERE edge_type_uuid IS NULL")
    return {"space": space, "before": before, "after": after,
            "removed": before - after, "untyped": untyped,
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

        total_removed = still_untyped = 0
        for sp in spaces:
            r = await rebuild(conn, sp, a.dry_run)
            if not r:
                continue
            if a.dry_run:
                print(f"  {r['space']:<30} {r['before']:>10,} rows")
                continue
            total_removed += max(0, r["removed"])
            still_untyped += r["untyped"]
            note = ""
            if r["removed"] > 0:
                note = f"  <-- {r['removed']:,} orphan(s) cleared"
            elif r["removed"] < 0:
                note = f"  <-- {-r['removed']:,} missing edge(s) restored"
            if r["untyped"]:
                note += f"  !! {r['untyped']:,} STILL UNTYPED"
            print(f"  {r['space']:<30} {r['before']:>10,} -> {r['after']:>10,}"
                  f"  {r['seconds']:>6}s{note}", flush=True)

        if not a.dry_run:
            print(f"\ntotal orphan rows cleared: {total_removed:,}")
            # Every graph object carries a vitaltype, so after a rebuild from the
            # quads nothing should be untyped. Anything left is a real anomaly,
            # not the expected state, and saying so is the point of the check.
            print(f"rows still untyped after rebuild: {still_untyped:,}"
                  + ("  <-- unexpected: investigate" if still_untyped else ""))
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
