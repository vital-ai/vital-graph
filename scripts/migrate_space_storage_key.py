#!/usr/bin/env python3
"""Add `space.storage_key` to an existing database (storage-key Stage 2).

New installs get the column from `ADMIN_TABLE_DDL`; this adds the same clause,
`sparql_sql_schema.STORAGE_KEY_COLUMN_SQL`, where it is missing:

    storage_key VARCHAR(16) UNIQUE, CHECK (storage_key ~ '^[a-z2-7]{8}$')

NULLABLE, AND NOTHING IS BACKFILLED. A key is not the space id, and existing
spaces get theirs from the re-key (`scripts/rekey_space.py`), which renames
their objects onto it at the same moment. From this migration on, every newly
created space is given one when its row is written.

ALSO REPORTS existing space ids with a key's shape (8 characters of [a-z2-7]).
Space creation and rename now refuse such ids; one that already exists must be
renamed before the cutover, or it could one day equal another space's key.

A catalogue change: `ADD COLUMN` with no default takes a brief ACCESS EXCLUSIVE
lock on `space` and rewrites nothing. Idempotent. RUN AS THE TABLE'S OWNER.

DEFAULT IS A DRY RUN.

    python scripts/migrate_space_storage_key.py
    python scripts/migrate_space_storage_key.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.space_storage_key import key_shaped_space_ids  # noqa: E402
from vitalgraph.db.sparql_sql.sparql_sql_schema import STORAGE_KEY_COLUMN_SQL  # noqa: E402


async def column_present(conn) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'space' "
        "AND column_name = 'storage_key')")


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="add the column (default is a dry run)")
    add_pg_arguments(ap)
    a = ap.parse_args()
    print(f"\U0001F5C4  target: {describe_target(a)}", flush=True)
    print("APPLY" if a.apply else "DRY RUN")

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        present = await column_present(conn)
        total = await conn.fetchval("SELECT count(*) FROM space")
        print(f"space rows: {total}")
        if present:
            keyed = await conn.fetchval(
                "SELECT count(*) FROM space WHERE storage_key IS NOT NULL")
            print(f"space.storage_key: present; {keyed} of {total} space(s) "
                  f"have a key")
        else:
            print("space.storage_key: ABSENT")
            if a.apply:
                await conn.execute(
                    f"ALTER TABLE space ADD COLUMN IF NOT EXISTS "
                    f"{STORAGE_KEY_COLUMN_SQL}")
                print("  added")
            else:
                print("  would add: " + STORAGE_KEY_COLUMN_SQL)

        shaped = await key_shaped_space_ids(conn)
        if shaped:
            print(f"\n{len(shaped)} existing space id(s) have a storage key's "
                  f"shape and must be renamed before the cutover:")
            for sid in shaped:
                print(f"    {sid}")
        else:
            print("\nno existing space id has a storage key's shape")

        if not a.apply and not present:
            print("\nDry run. Re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
