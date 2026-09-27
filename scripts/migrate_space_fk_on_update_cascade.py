#!/usr/bin/env python3
"""Give every `space(space_id)` foreign key `ON UPDATE CASCADE` (`issues/232`).

WHY. `space.space_id` IS the primary key — the id string, with no numeric
surrogate anywhere. Eleven admin tables reference it `ON DELETE CASCADE` and none
declares `ON UPDATE CASCADE`, so `UPDATE space SET space_id = …` is REJECTED and a
rename cannot be a catalogue operation. Adding it is what lets the rename update
one row and have the children follow, instead of repointing eleven tables by hand
in the right order.

AND `user_space_access` GETS THE FK IT NEVER HAD. It holds `space_id VARCHAR(255)
NOT NULL` with no reference at all, so unlike the eleven it would NOT reject a
rename that forgot it — it would silently keep rows pointing at an id nobody
uses. That is a silent revocation of every user's access to the renamed space, and
it is the one failure in `issues/232` that is both invisible and
security-relevant.

MEASURED BEFORE WRITING THIS: `user_space_access` is EMPTY on both the vg test
stack and production, so the consequence is latent rather than active today and
the FK can be added without a cleanup pass. It is still worth adding, precisely so
it cannot become active later.

DROP AND RE-ADD, which is the only way to change a foreign key's action.
Catalogue-only for the eleven: the constraint already exists and the data already
satisfies it, so `ADD CONSTRAINT ... NOT VALID` is unnecessary — but each re-add
does take a brief `SHARE ROW EXCLUSIVE` on the child and `ACCESS SHARE` on
`space`, so this is a maintenance-window operation on a busy system rather than a
free one.

IDEMPOTENT. A constraint that already has `ON UPDATE CASCADE` is skipped, and the
`user_space_access` FK is added only when absent. Safe to run twice.

REFUSES rather than deletes if `user_space_access` holds grants for spaces that do
not exist. Those rows are access records; discarding them silently to make a
migration pass is not this script's decision to make.

    python scripts/migrate_space_fk_on_update_cascade.py --dsn ... [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg

#: The referencing table for the FK this migration ADDS (as opposed to fixes).
_MISSING_FK_TABLE = "user_space_access"


def _cascades_on_update(confupdtype) -> bool:
    """Is this FK's update action CASCADE?

    `pg_constraint.confupdtype` is PostgreSQL's `"char"` type, which asyncpg hands
    back as BYTES — `b'c'`, not `'c'`. Comparing it to a str is always False, so
    the first version of this reported all twelve constraints as still needing the
    change immediately after successfully changing them, and its claim to be
    idempotent was untrue: a second run would have dropped and re-added every
    already-correct constraint.
    """
    if isinstance(confupdtype, bytes):
        confupdtype = confupdtype.decode()
    return confupdtype == "c"


async def _fks_to_space(conn):
    """Every FK referencing `space(space_id)`, with its current update action.

    `confupdtype`: 'a' = NO ACTION (the default, and what all eleven had),
    'c' = CASCADE. See `_cascades_on_update` for why it is not compared directly.
    """
    return await conn.fetch("""
        SELECT con.conname, rel.relname AS child, con.confupdtype
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_class ref ON ref.oid = con.confrelid
         WHERE con.contype = 'f' AND ref.relname = 'space'
         ORDER BY rel.relname, con.conname
    """)


async def _columns(conn, conname: str):
    row = await conn.fetchrow("""
        SELECT pg_get_constraintdef(con.oid) AS def
          FROM pg_constraint con WHERE con.conname = $1
    """, conname)
    return row["def"] if row else None


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="write; without this the script only reports")
    a = ap.parse_args()

    conn = await asyncpg.connect(a.dsn)
    try:
        existing = await _fks_to_space(conn)
        need_fix = [r for r in existing
                    if not _cascades_on_update(r["confupdtype"])]
        already = [r for r in existing
                   if _cascades_on_update(r["confupdtype"])]

        print(f"foreign keys referencing space(space_id): {len(existing)}")
        print(f"  already ON UPDATE CASCADE: {len(already)}")
        print(f"  needing the change:        {len(need_fix)}")
        for r in need_fix:
            print(f"      {r['child']}.{r['conname']}")

        has_missing = any(r["child"] == _MISSING_FK_TABLE for r in existing)
        orphans = await conn.fetchval(f"""
            SELECT count(*) FROM {_MISSING_FK_TABLE} u
             LEFT JOIN space s ON s.space_id = u.space_id
             WHERE s.space_id IS NULL
        """)
        if not has_missing:
            print(f"\n{_MISSING_FK_TABLE}: NO foreign key on space_id — will add "
                  f"one (ON DELETE CASCADE ON UPDATE CASCADE)")
            print(f"  grants referencing a non-existent space: {orphans}")
            if orphans:
                print("\nREFUSING: those rows are access records and would have "
                      "to be deleted for the FK to be accepted. Decide what they "
                      "mean before this migration runs; it will not discard them "
                      "to make itself pass.")
                return 2
        else:
            print(f"\n{_MISSING_FK_TABLE}: foreign key already present")

        if not a.apply:
            print("\n--apply not given; nothing was written")
            return 0

        async with conn.transaction():
            for r in need_fix:
                definition = await _columns(conn, r["conname"])
                if definition is None:
                    print(f"  SKIP {r['conname']}: definition unreadable")
                    continue
                # `pg_get_constraintdef` gives the whole clause; append the
                # action rather than reconstructing the column list, so a
                # multi-column or oddly-named FK cannot be rebuilt wrongly.
                new_def = definition
                if "ON UPDATE" not in new_def:
                    new_def = f"{new_def} ON UPDATE CASCADE"
                await conn.execute(
                    f'ALTER TABLE "{r["child"]}" '
                    f'DROP CONSTRAINT "{r["conname"]}"')
                await conn.execute(
                    f'ALTER TABLE "{r["child"]}" '
                    f'ADD CONSTRAINT "{r["conname"]}" {new_def}')
                print(f"  fixed {r['child']}.{r['conname']}")

            if not has_missing:
                await conn.execute(f"""
                    ALTER TABLE {_MISSING_FK_TABLE}
                      ADD CONSTRAINT {_MISSING_FK_TABLE}_space_id_fkey
                      FOREIGN KEY (space_id) REFERENCES space(space_id)
                      ON DELETE CASCADE ON UPDATE CASCADE
                """)
                print(f"  added {_MISSING_FK_TABLE}_space_id_fkey")

        after = await _fks_to_space(conn)
        remaining = [r for r in after
                     if not _cascades_on_update(r["confupdtype"])]
        print(f"\nafter: {len(after)} FKs, {len(remaining)} still without "
              f"ON UPDATE CASCADE")
        return 0 if not remaining else 1
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
