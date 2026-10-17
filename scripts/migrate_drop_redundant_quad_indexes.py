#!/usr/bin/env python
"""Drop the quad indexes another index already covers — issues/270, 271.

    idx_{space}_quad_pred  (predicate_uuid)                 covered by quad_po / quad_ps
    idx_{space}_quad_ctx   (context_uuid)                   covered by quad_ctx_pred
    idx_{space}_quad_sp    (subject_uuid, predicate_uuid)   covered by the pkey (s, p, o, c)

Why: every quad insert maintains every index on the table, at a random page
each (the keys are UUIDs). Production's main KG space carried 9 indexes, ~32 GB,
on an 8.8 GB heap, and a bulk load drove the database to its IOPS limit through
index maintenance alone. These two were the least used of the nine (26k and 385k
scans against hundreds of millions to billions for the rest) and a composite
index with the same LEADING column serves the same lookups: a B-tree on
(predicate_uuid, object_uuid) answers `predicate_uuid = X` as well as a B-tree on
(predicate_uuid) does. `quad_sp` (issues/271) is heavily scanned, but every
scan it serves the primary key serves too, since (s, p) is the pkey's leading
prefix. All three dropped leaves 6 index writes per quad instead of 9 and
~6.4 GB less to keep in cache on that space.

Verified on the vg test stack before any production run: the full query-tier
perf suite with the indexes dropped on every space against runs with them in
place (see issues/270 and issues/271 for the comparisons).

Safety, because this is meant to be run against production:

  * DRY RUN BY DEFAULT. `--apply` drops; without it the script prints each
    index, its size and its scan count, and touches nothing.
  * An index is dropped only if its COVERING composite exists AND is valid on
    the same space. A space missing the composite keeps its single-column index.
  * DROP INDEX CONCURRENTLY: no lock that blocks reads or writes. It cannot run
    in a transaction, so each index is its own statement. A PARTITIONED quad
    table's index (relkind `I`) cannot be dropped concurrently, so it gets a
    plain DROP INDEX, which takes a short ACCESS EXCLUSIVE lock on the parent
    and drops each partition's index with it.
  * Candidates come from the catalog, not `pg_stat_user_indexes`: that view does
    not list partitioned indexes, so a partitioned space was silently skipped.
  * Run as the role that OWNS the tables (`vitalgraph_user` on production);
    another role cannot drop the index.
  * Reversible: `scripts/ensure_space_indexes.py` (or the schema's
    `create_space_indexes_sql`) recreates any index that is missing, and these
    two are no longer in that list once the schema change ships.

    python scripts/migrate_drop_redundant_quad_indexes.py --dsn "..."                 # dry run, all spaces
    python scripts/migrate_drop_redundant_quad_indexes.py --dsn "..." --space prod_kg
    python scripts/migrate_drop_redundant_quad_indexes.py --dsn "..." --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg  # noqa: E402

from devtools.target import dsn  # noqa: E402

#: index suffix -> the covering indexes, any ONE of which makes it redundant.
#: `{s}` is the space id. quad_sp's cover is the primary key, whose name has no
#: `idx_` prefix.
REDUNDANT = {
    "quad_pred": ("idx_{s}_quad_po", "idx_{s}_quad_ps"),
    "quad_ctx": ("idx_{s}_quad_ctx_pred",),
    "quad_sp": ("{s}_rdf_quad_pkey",),
}


async def _valid_index(conn, name: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = $1", name))


async def plan(conn, only_space: str | None):
    """[(space, index, size, scans, covered_by or None, partitioned)] per candidate."""
    rows = await conn.fetch(
        "SELECT c.relname AS idx, c.relkind = 'I' AS partitioned, "
        "       COALESCE(s.idx_scan, 0) AS scans, "
        "       pg_size_pretty(pg_total_relation_size(c.oid)) AS size "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "LEFT JOIN pg_stat_all_indexes s ON s.indexrelid = c.oid "
        "WHERE n.nspname = 'public' AND c.relkind IN ('i', 'I') "
        "  AND c.relname ~ '^idx_.+_quad_(pred|ctx|sp)$' ORDER BY c.relname")
    out = []
    for r in rows:
        idx = r["idx"]
        suffix = next(k for k in REDUNDANT if idx.endswith("_" + k))
        space = idx[len("idx_"):-len("_" + suffix)]
        if only_space and space != only_space:
            continue
        covered_by = None
        for comp in REDUNDANT[suffix]:
            name = comp.format(s=space)
            if await _valid_index(conn, name):
                covered_by = name
                break
        out.append((space, idx, r["size"], r["scans"], covered_by, r["partitioned"]))
    return out


async def run(target: str, only_space: str | None, apply: bool) -> int:
    conn = await asyncpg.connect(target)          # autocommit: CONCURRENTLY needs it
    try:
        who = await conn.fetchval("SELECT current_user || '@' || current_database()")
        print(f"target: {who} ({'APPLY' if apply else 'dry run'})")
        items = await plan(conn, only_space)
        if not items:
            print("nothing to do: no quad_pred / quad_ctx / quad_sp indexes")
            return 0
        kept = 0
        for space, idx, size, scans, covered_by, partitioned in items:
            if not covered_by:
                kept += 1
                print(f"  KEEP  {idx:48} {size:>8} scans={scans:>12,}  "
                      f"(no valid covering composite on {space})")
                continue
            if not apply:
                print(f"  drop  {idx:48} {size:>8} scans={scans:>12,}  covered by {covered_by}")
                continue
            t0 = time.time()
            how = "" if partitioned else "CONCURRENTLY "
            await conn.execute(f'DROP INDEX {how}IF EXISTS "{idx}"')
            print(f"  ✅ dropped {idx} ({size}) in {time.time() - t0:.1f}s; "
                  f"covered by {covered_by}")
        if kept:
            print(f"{kept} kept for want of a covering index")
        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=None, help="postgresql://... (defaults to VG_TEST_PG_* env)")
    ap.add_argument("--space", default=None, help="only this space")
    ap.add_argument("--apply", action="store_true", help="drop; without it, report only")
    a = ap.parse_args()
    return asyncio.run(run(a.dsn or dsn(), a.space, a.apply))


if __name__ == "__main__":
    sys.exit(main())
