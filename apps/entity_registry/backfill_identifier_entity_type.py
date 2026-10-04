#!/usr/bin/env python3
"""Fill `entity_identifier.entity_type_id` for existing rows — `issues/227`.

The column is added by `migrate.py`; rows written since carry it
(`_insert_identifier`). This fills the rest from `entity.entity_type_id`, which is
safe to copy because an entity's type never changes. Batched by
`identifier_id`, one short statement per batch, so no single statement comes
near a 60 s `statement_timeout`; re-runnable, since it only touches NULLs.

A declaration (`declare_unique_identifiers.py`) refuses to build while any row in
its namespace is still NULL: such a row would sit outside the partial index and
escape the uniqueness it promises.

    python apps/entity_registry/backfill_identifier_entity_type.py [--batch 20000] [--dry-run]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from apps.entity_registry.migrate import get_pool  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--batch", type=int, default=20000)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    pool = await get_pool()
    try:
        null = await pool.fetchval(
            "SELECT count(*) FROM entity_identifier WHERE entity_type_id IS NULL")
        print(f"rows without entity_type_id: {null:,}")
        if a.dry_run or not null:
            return 0
        lo = await pool.fetchval("SELECT min(identifier_id) FROM entity_identifier "
                                 "WHERE entity_type_id IS NULL")
        hi = await pool.fetchval("SELECT max(identifier_id) FROM entity_identifier "
                                 "WHERE entity_type_id IS NULL")
        done = 0
        start = lo
        while start <= hi:
            r = await pool.execute(
                "UPDATE entity_identifier ei SET entity_type_id = e.entity_type_id "
                "FROM entity e WHERE e.entity_id = ei.entity_id "
                "AND ei.entity_type_id IS NULL "
                "AND ei.identifier_id >= $1 AND ei.identifier_id < $2",
                start, start + a.batch)
            done += int(r.split()[-1])
            start += a.batch
        left = await pool.fetchval(
            "SELECT count(*) FROM entity_identifier WHERE entity_type_id IS NULL")
        print(f"filled {done:,}; still NULL: {left:,}"
              + (" (rows whose entity is missing)" if left else ""))
        return 0 if not left else 1
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
