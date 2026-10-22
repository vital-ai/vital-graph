#!/usr/bin/env python3
"""Move an install onto storage keys: add `space.storage_key`, re-key every space.

The one migration each install runs for the storage-key change. Idempotent: on
an install already done it reports "nothing to do" and changes nothing.

1. THE COLUMN. New installs get it from `ADMIN_TABLE_DDL`; this adds the same
   clause, `sparql_sql_schema.STORAGE_KEY_COLUMN_SQL`, where it is missing:

       storage_key VARCHAR(16) UNIQUE, CHECK (storage_key ~ '^[a-z2-7]{8}$')

   `ADD COLUMN` with no default is a catalogue change under a brief ACCESS
   EXCLUSIVE lock on `space`; nothing is rewritten.

2. THE RE-KEY. Every registered space whose objects are still named by its id
   is moved onto its key (`vgs_<key>_…`), one transaction per space, by the
   same move as `scripts/rekey_space.py`. Each takes ACCESS EXCLUSIVE on the
   space's objects for well under a second, so RUN WITH WRITERS STOPPED, and
   restart the service afterwards so every instance loads the keys.

   Code before Stage 3 names objects by id only, so on an install still
   running it, run step 1 alone (`--column-only`) and the re-key after the
   upgrade. From Stage 4 (no id fallback) the full migration must run BEFORE
   the new code starts.

REFUSES TO RE-KEY while any space id has a storage key's shape or starts with
`vgs_` — such an id could equal another space's key or sit in the key
namespace. They are listed; rename them first. Unregistered tables (no `space`
row, e.g. the conformance fixture `dawg_test`) are not touched.

RUN AS THE TABLES' OWNER. DEFAULT IS A DRY RUN, which also plans every re-key
(in a rolled-back transaction) so a space that cannot be moved shows up here.

    python scripts/migrate_space_storage_key.py
    python scripts/migrate_space_storage_key.py --apply
    python scripts/migrate_space_storage_key.py --apply --column-only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devtools.target import add_pg_arguments, describe_target  # noqa: E402
from vitalgraph.db.sparql_sql.space_rekey import rekey_space  # noqa: E402
from vitalgraph.db.sparql_sql.space_rename import SpaceRenameRefused  # noqa: E402
from vitalgraph.db.sparql_sql.space_storage_key import (  # noqa: E402
    is_keyed, key_shaped_space_ids, load_storage_keys)
from vitalgraph.db.sparql_sql.sparql_sql_schema import STORAGE_KEY_COLUMN_SQL  # noqa: E402


async def column_present(conn) -> bool:
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'space' "
        "AND column_name = 'storage_key')")


async def classify(conn, present: bool):
    """`(keyed, by_id, no_tables)` space ids."""
    keyed, by_id, no_tables = [], [], []
    for sid in [r["space_id"] for r in await conn.fetch(
            "SELECT space_id FROM space ORDER BY space_id")]:
        if present and await is_keyed(conn, sid):
            keyed.append(sid)
        elif await conn.fetchval("SELECT to_regclass($1) IS NOT NULL",
                                 f"public.{sid}_rdf_quad"):
            by_id.append(sid)
        else:
            no_tables.append(sid)
    return keyed, by_id, no_tables


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write (default is a dry run)")
    ap.add_argument("--column-only", action="store_true",
                    help="add the column and stop; for an install still on "
                         "code that predates Stage 3")
    ap.add_argument("--lock-timeout-ms", type=int, default=5000)
    add_pg_arguments(ap)
    a = ap.parse_args()
    print(f"\U0001F5C4  target: {describe_target(a)}", flush=True)
    print("APPLY" if a.apply else "DRY RUN")

    import asyncpg
    conn = await asyncpg.connect(host=a.host, port=a.port, database=a.database,
                                 user=a.user, password=a.password or None)
    try:
        # 1. the column
        present = await column_present(conn)
        if present:
            print("space.storage_key: present")
        elif a.apply:
            await conn.execute(
                f"ALTER TABLE space ADD COLUMN IF NOT EXISTS {STORAGE_KEY_COLUMN_SQL}")
            present = True
            print("space.storage_key: ADDED")
        else:
            print("space.storage_key: absent — would add: " + STORAGE_KEY_COLUMN_SQL)
        if a.column_only:
            return 0

        # 2. the re-key
        shaped = await key_shaped_space_ids(conn)
        if present:
            await load_storage_keys(conn)
        keyed, by_id, no_tables = await classify(conn, present)
        print(f"\nspaces: {len(keyed) + len(by_id) + len(no_tables)}  "
              f"keyed {len(keyed)}  to re-key {len(by_id)}  "
              f"no tables {len(no_tables)}")
        for sid in no_tables:
            print(f"    no tables, left alone: {sid}")

        if shaped:
            print(f"\nREFUSED: {len(shaped)} space id(s) have a storage key's "
                  f"shape or start with 'vgs_'; rename them, then re-run:")
            for sid in shaped:
                print(f"    {sid}")
            return 2
        if not by_id:
            print("\nnothing to re-key")
            return 0
        if not present:
            print("\nDry run: the column is absent, so the re-keys cannot be "
                  "planned yet. Re-run with --apply.")
            return 0

        failed = []
        for sid in by_id:
            try:
                r = await rekey_space(conn, sid, dry_run=not a.apply,
                                      lock_timeout_ms=a.lock_timeout_ms)
            except SpaceRenameRefused as e:
                failed.append(sid)
                print(f"    {sid}: REFUSED — {e}")
                continue
            done = (f"done in {r['seconds']:.2f}s" if a.apply
                    else "planned")
            print(f"    {sid} -> {r['to_prefix']}  {r['statements']} statements  {done}")

        if failed:
            print(f"\n{len(failed)} space(s) not re-keyed: {', '.join(failed)}")
            return 1
        if a.apply:
            print(f"\nre-keyed {len(by_id)} space(s). Restart the service so "
                  f"every instance loads the keys.")
        else:
            print(f"\nDry run: {len(by_id)} space(s) would be re-keyed. Stop "
                  f"writers and re-run with --apply.")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
