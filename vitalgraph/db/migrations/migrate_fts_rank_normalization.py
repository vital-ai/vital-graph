"""Add ``rank_normalization`` to every ``{space}_fts_index`` table.

WHY. `ts_rank_cd`'s normalization argument defaults to 0, which IGNORES
document length. On short text that discards the main signal separating
documents: measured on a 321,276-row message index, the term `app` matched
118,702 documents and norm=0 gave them THREE distinct scores — so a "top 25 by
relevance" was arbitrary. norm=1 (divide by log(length)) gave 101.

The value is stored PER INDEX rather than hardcoded for two reasons: it changes
every score an index produces, so it cannot be switched globally without
invalidating anything holding a threshold; and it is an editorial choice —
dividing by length favours short documents, which on a mixed SMS/email corpus
ranks SMS above email at equal term density.

DEFAULT 0, so this migration changes no behaviour on its own. Existing indexes
keep emitting exactly the SQL they emitted before (the emitter omits the
argument entirely at 0), which keeps recorded plans and baselines comparable.
Opting an index in is a separate, deliberate UPDATE.

    python -m vitalgraph.db.migrations.migrate_fts_rank_normalization \\
        --dsn postgresql://... [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def run(dsn: str, apply: bool) -> int:
    import asyncpg
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("""
            SELECT c.relname AS tbl
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND c.relname LIKE '%\\_fts\\_index'
            ORDER BY 1
        """)
        todo = []
        for r in rows:
            tbl = r["tbl"]
            has = await conn.fetchval("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = $1 AND column_name = 'rank_normalization'
            """, tbl)
            (print(f"  ok      {tbl}") if has else todo.append(tbl))
        print(f"\n{len(rows)} fts_index table(s); {len(todo)} need the column")
        if not todo:
            return 0
        if not apply:
            for t in todo:
                print(f"  WOULD ALTER {t}")
            print("\nre-run with --apply")
            return 0
        for t in todo:
            await conn.execute(
                f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS "
                f"rank_normalization INTEGER NOT NULL DEFAULT 0")
            print(f"  ALTERED {t}")
        return 0
    finally:
        await conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    return asyncio.run(run(a.dsn, a.apply))


if __name__ == "__main__":
    sys.exit(main())
