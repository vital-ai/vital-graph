#!/usr/bin/env python3
"""Rename the five over-long index names to the short convention (`issues/196`).

WHY. `{space}_document_segmentation_config_doc_type_idx` is 42 bytes of suffix
and alone set the longest space id this schema supports to 21 bytes. Shortening
it and its four `segmentation_jobs` siblings raises that ceiling to 34 for every
space at once, which is the only fix that does not require renaming a space.

RENAME, NOT DROP-AND-CREATE. `ALTER INDEX ... RENAME TO` is a catalogue update:
atomic, instant, and it does not rebuild the index. Dropping and recreating
would rebuild every one of them, and would leave a window with no index on
tables a live system may be querying.

IDEMPOTENT. A space already renamed is skipped, and a space that never had the
old index is skipped. Safe to run twice.

TRUNCATED NAMES ARE INCLUDED, deliberately. Where the intended name exceeded 63
bytes PostgreSQL created it silently shortened, so the old index is present
under a name the schema never asked for — which is the failure the length guard
exists to prevent, already realised. Those are matched by prefix and renamed
too, which is the only way they stop being orphans.
"""
from __future__ import annotations

import argparse
import asyncio
import os

import asyncpg

# (old suffix on the TABLE name, new short name after the space id)
RENAMES = [
    ("_segmentation_jobs_status_idx", "sj_status"),
    ("_segmentation_jobs_document_idx", "sj_doc"),
    ("_segmentation_jobs_space_idx", "sj_space"),
    ("_segmentation_jobs_active_doc_uq", "sj_active_uq"),
    ("_document_segmentation_config_doc_type_idx", "dsc_doctype"),
]
PG_MAX = 63


async def spaces_with_old_names(conn) -> dict:
    """{space_id: [(old_index_name, new_index_name)]} for everything to rename."""
    rows = await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE schemaname='public'")
    have = {r["indexname"] for r in rows}
    out: dict = {}
    for name in sorted(have):
        for suffix, short in RENAMES:
            # The intended name may have been TRUNCATED when created, so match
            # on the longest prefix that survives the byte limit.
            probe = suffix[:PG_MAX] if len(suffix) <= PG_MAX else suffix
            idx = name.find(probe[:min(len(probe), 40)])
            if idx <= 0:
                continue
            space = name[:idx]
            if not name.startswith(space + suffix[:len(name) - idx]):
                continue
            new = f"idx_{space}_{short}"
            if len(new.encode()) > PG_MAX or new in have:
                continue
            out.setdefault(space, []).append((name, new))
            break
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="perform the renames; without it, report only")
    args = ap.parse_args()

    conn = await asyncpg.connect(
        host=os.getenv("VG_TEST_PG_HOST", "localhost"),
        port=int(os.getenv("VG_TEST_PG_PORT", "5433")),
        database=os.getenv("VG_TEST_PG_DATABASE", "sparql_sql_graph"),
        user=os.getenv("VG_TEST_PG_USER", "postgres"),
        password=os.getenv("VG_TEST_PG_PASSWORD", "testpass"))
    try:
        plan = await spaces_with_old_names(conn)
        total = sum(len(v) for v in plan.values())
        print(f"  spaces to migrate : {len(plan)}")
        print(f"  indexes to rename : {total}")
        for space, pairs in list(plan.items())[:2]:
            for old, new in pairs:
                print(f"    {space}: {old}  ->  {new}")
        if not args.apply:
            print("  (report only — pass --apply to perform the renames)")
            return 0
        done = 0
        for space, pairs in plan.items():
            for old, new in pairs:
                async with conn.transaction():
                    await conn.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')
                done += 1
        print(f"  renamed: {done}")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
