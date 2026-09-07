#!/usr/bin/env python3
"""Create the block table and seed blocks from existing coverage rows.

`issues/167`. The read paths now consult a BLOCK-LIST: a row means "known at
risk", and ABSENCE MEANS SERVE. That inverts the failure mode —

    allow-list   forget to mark COMPLETE   ->  slow, correct
    block-list   forget to mark AT RISK    ->  fast, WRONG

— so every type ALREADY KNOWN to be short must have a block before the
inversion takes effect, or it goes from "declined and slow" to "served and
wrong" the moment the new code runs.

That is exactly the state a deployment is in at upgrade: `slot_sort_coverage`
holds rows with `complete = false` recorded by the previous version, and
`slot_sort_block` is empty because it did not exist. Measured on the test
database at the time of writing: seven spaces, twenty-seven short types.

IDEMPOTENT. Re-running seeds nothing new; the block insert is an upsert keyed on
(space_id, entity_type_uuid).

DOES NOT RELEASE ANYTHING. A type recorded complete is left alone rather than
having a block removed, because absence already means serve — there is nothing
to release, and inventing a release would be the one operation this script must
never perform without measuring.

    python scripts/migrate_slot_sort_blocks.py --dry-run
    python scripts/migrate_slot_sort_blocks.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from devtools.target import add_pg_arguments, describe_target  # noqa: E402

logger = logging.getLogger("migrate_slot_sort_blocks")

async def _ensure_admin_tables(conn) -> list:
    """Create the global admin tables, FROM THE SCHEMA, before reading any.

    THIS SCRIPT USED TO ASSUME `slot_sort_coverage` EXISTED. It read it to find
    short types and only afterwards created `slot_sort_block` — so on a database
    that has neither, it failed with `relation "slot_sort_coverage" does not
    exist` before creating anything. Caught by a deploy rehearsal against a
    clean RDS instance, NOT by testing here: both local stacks already had the
    coverage table, so every run exercised the case where the precondition
    already held.

    That is also why the DDL is taken from `SparqlSQLSchema.ADMIN_TABLE_DDL`
    rather than written out here. A copy in this file is a second source of
    truth that drifts silently, and the rehearsal had to hand-copy the DDL into
    psql to get past the failure — which is the same drift one step further out.

    Creates every admin table, not just the two this script needs: they are one
    group, `CREATE TABLE IF NOT EXISTS` is idempotent, and a database missing
    one is likely missing its siblings.
    """
    created = []
    from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
    sch = SparqlSQLSchema()
    for name, _ in sch.ADMIN_TABLE_DDL:
        bare = name.strip('"')
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename=$1",
            bare)
        if not exists:
            created.append(bare)
    for ddl in sch.create_admin_tables_sql():
        await conn.execute(ddl)
    for ddl in sch.create_admin_indexes_sql():
        try:
            await conn.execute(ddl)
        except Exception:
            # An index on a table this database does not use is not a reason to
            # fail the migration the caller actually asked for.
            pass
    return created


async def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    add_pg_arguments(ap)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"\U0001F5C4  target: {describe_target(args)}", flush=True)

    import asyncpg
    conn = await asyncpg.connect(host=args.host, port=args.port,
                                 database=args.database, user=args.user,
                                 password=args.password or None)
    try:
        # BEFORE ANY READ. See `_ensure_admin_tables`.
        if not args.dry_run:
            made = await _ensure_admin_tables(conn)
            if made:
                logger.info("  created admin table(s): %s", ", ".join(made))
        elif not await conn.fetchval(
                "SELECT 1 FROM pg_tables WHERE schemaname='public' "
                "AND tablename='slot_sort_coverage'"):
            logger.info("  [dry-run] slot_sort_coverage is ABSENT; a real run "
                        "would create the admin tables first, and there would "
                        "be no coverage rows to seed blocks from — every space "
                        "would take a whole-space block instead")
            return 0

        short = await conn.fetch(
            "SELECT space_id, entity_type_uuid, entities_in_table,"
            "       entities_of_type"
            "  FROM slot_sort_coverage WHERE NOT complete ORDER BY space_id")
        by_space: dict = {}
        for r in short:
            by_space.setdefault(r["space_id"], 0)
            by_space[r["space_id"]] += 1

        if args.dry_run:
            for sp, n in sorted(by_space.items()):
                logger.info("  [dry-run] %s: %d short type(s) would be blocked",
                            sp, n)
            logger.info("\n%d type(s) across %d space(s)", len(short),
                        len(by_space))
            return 0

        # NEVER-MEASURED SPACES GET A WHOLE-SPACE BLOCK.
        #
        # A short type is blocked above. A space whose coverage probe has NEVER
        # RUN has no rows at all, so under a block-list it would be SERVED — and
        # if its `entity_slot_sort` was created by a schema migration onto
        # existing data and never backfilled, serving it returns a subset.
        # That is the "table created but never populated" case: incomplete, not
        # being worked on, and with nobody to flag it.
        #
        # Blocked at the space level because the types are not known until
        # something measures them, which is precisely what has not happened.
        # `backfill_slot_sort_coverage.py` measures and releases.
        never = [r[0] for r in await conn.fetch(
            "SELECT replace(tablename,'_entity_slot_sort','') AS sp"
            "  FROM pg_tables WHERE schemaname='public'"
            "   AND tablename LIKE '%\\_entity\\_slot\\_sort'"
            "   AND replace(tablename,'_entity_slot_sort','') NOT IN"
            "       (SELECT space_id FROM slot_sort_coverage)"
            "   AND replace(tablename,'_entity_slot_sort','') IN"
            "       (SELECT space_id FROM space)"
            " ORDER BY 1")]
        for sp in never:
            await conn.execute(
                "INSERT INTO slot_sort_block (space_id, entity_type_uuid, reason)"
                " VALUES ($1, NULL, $2)"
                " ON CONFLICT (space_id, entity_type_uuid) DO NOTHING",
                sp, "coverage never measured (seeded at upgrade)")
            logger.info("  %s: never measured — whole space blocked", sp)

        for r in short:
            await conn.execute(
                "INSERT INTO slot_sort_block (space_id, entity_type_uuid, reason)"
                " VALUES ($1, $2, $3)"
                " ON CONFLICT (space_id, entity_type_uuid) DO UPDATE"
                "   SET reason = EXCLUDED.reason, created_at = NOW()",
                r["space_id"], r["entity_type_uuid"],
                f"coverage {r['entities_in_table']}/{r['entities_of_type']} "
                f"(seeded at upgrade)")
        for sp, n in sorted(by_space.items()):
            logger.info("  %s: %d short type(s) blocked", sp, n)
        held = await conn.fetchval("SELECT count(*) FROM slot_sort_block")
        logger.info("\n%d block(s) held. Clear them by running "
                    "scripts/backfill_slot_sort_coverage.py per space — a block "
                    "is released only by a job that has MEASURED coverage.",
                    held)
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
