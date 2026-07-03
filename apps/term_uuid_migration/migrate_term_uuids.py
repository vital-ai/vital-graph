#!/usr/bin/env python3
"""
Migrate legacy plain-literal term UUIDs to deterministic UUID v5.

Background:
    The old `_term_upsert()` in emit_update.py used `gen_random_uuid()` for
    term insertion. This means plain untyped literals (lang=NULL, datatype_id=NULL)
    may have non-deterministic UUIDs in the term table. The current code uses
    deterministic UUID v5 via `_generate_term_uuid()`, but a subquery fallback
    exists in `_term_uuid_subquery()` to handle these legacy rows.

    This script re-keys all affected term rows to their deterministic UUID and
    cascades the change to all rdf_quad references. After running, the subquery
    fallback in `_term_uuid_subquery()` can be safely removed.

Prerequisites:
    - The `vitalgraph_term_uuid()` PostgreSQL function must already exist
      (created by `vitalgraphdb init` via sparql_sql_admin.py)
    - The service should be STOPPED during migration (direct DB access, no
      concurrent writes)

Usage:
    # Dry run — show affected row counts per space:
    python -m apps.term_uuid_migration.migrate_term_uuids --dry-run

    # Run migration:
    python -m apps.term_uuid_migration.migrate_term_uuids

    # Single space only:
    python -m apps.term_uuid_migration.migrate_term_uuids --space my_space
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg

from vitalgraph.config.config_loader import VitalGraphConfig

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

LINE = '─' * 60


async def get_pool() -> asyncpg.Pool:
    config = VitalGraphConfig()
    db_config = config.get_database_config()
    return await asyncpg.create_pool(
        host=db_config.get('host', 'localhost'),
        port=int(db_config.get('port', 5432)),
        database=db_config.get('database', 'vitalgraph'),
        user=db_config.get('username', 'postgres'),
        password=db_config.get('password', ''),
        min_size=1,
        max_size=3,
    )


async def get_spaces(pool: asyncpg.Pool) -> list[str]:
    """Get all space_id values from the space table."""
    rows = await pool.fetch(
        "SELECT space_id FROM space ORDER BY space_id"
    )
    return [r['space_id'] for r in rows]


async def check_function_exists(pool: asyncpg.Pool) -> bool:
    """Verify that vitalgraph_term_uuid() function exists."""
    row = await pool.fetchrow(
        "SELECT 1 FROM pg_proc WHERE proname = 'vitalgraph_term_uuid'"
    )
    return row is not None


async def count_affected_terms(pool: asyncpg.Pool, space_id: str) -> int:
    """Count plain-literal terms with non-deterministic UUIDs."""
    term_table = f"{space_id}_term"
    row = await pool.fetchrow(f"""
        SELECT COUNT(*) AS cnt
        FROM {term_table}
        WHERE term_type = 'L'
          AND lang IS NULL
          AND datatype_id IS NULL
          AND term_uuid != vitalgraph_term_uuid(term_text, term_type, lang, datatype_id)
    """)
    return row['cnt'] if row else 0


async def migrate_space(pool: asyncpg.Pool, space_id: str, dry_run: bool) -> dict:
    """Migrate a single space's term UUIDs. Returns stats."""
    term_table = f"{space_id}_term"
    quad_table = f"{space_id}_rdf_quad"

    affected = await count_affected_terms(pool, space_id)
    if affected == 0:
        return {'space_id': space_id, 'terms': 0, 'quads': 0, 'skipped': True}

    if dry_run:
        return {'space_id': space_id, 'terms': affected, 'quads': '?', 'skipped': False}

    t0 = time.time()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Step 1: Build mapping of old_uuid → new_uuid for affected terms
            # We use a temp table to hold the mapping for efficient joins
            await conn.execute("""
                CREATE TEMP TABLE _term_uuid_migration (
                    old_uuid UUID NOT NULL,
                    new_uuid UUID NOT NULL
                ) ON COMMIT DROP
            """)

            await conn.execute(f"""
                INSERT INTO _term_uuid_migration (old_uuid, new_uuid)
                SELECT term_uuid,
                       vitalgraph_term_uuid(term_text, term_type, lang, datatype_id)
                FROM {term_table}
                WHERE term_type = 'L'
                  AND lang IS NULL
                  AND datatype_id IS NULL
                  AND term_uuid != vitalgraph_term_uuid(term_text, term_type, lang, datatype_id)
            """)

            # Step 2: Update rdf_quad object_uuid references
            quad_result = await conn.execute(f"""
                UPDATE {quad_table} q
                SET object_uuid = m.new_uuid
                FROM _term_uuid_migration m
                WHERE q.object_uuid = m.old_uuid
            """)
            quads_updated = int(quad_result.split()[-1]) if quad_result else 0

            # Step 3: Update rdf_quad subject_uuid references (unlikely for
            # literals, but handle edge cases)
            subj_result = await conn.execute(f"""
                UPDATE {quad_table} q
                SET subject_uuid = m.new_uuid
                FROM _term_uuid_migration m
                WHERE q.subject_uuid = m.old_uuid
            """)
            quads_updated += int(subj_result.split()[-1]) if subj_result else 0

            # Step 4: Update term_uuid in the term table itself
            await conn.execute(f"""
                UPDATE {term_table} t
                SET term_uuid = m.new_uuid
                FROM _term_uuid_migration m
                WHERE t.term_uuid = m.old_uuid
            """)

    elapsed = time.time() - t0
    return {
        'space_id': space_id,
        'terms': affected,
        'quads': quads_updated,
        'skipped': False,
        'elapsed': f"{elapsed:.1f}s",
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate legacy plain-literal term UUIDs to deterministic UUID v5."
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help="Show affected counts without making changes."
    )
    parser.add_argument(
        '--space', type=str, default=None,
        help="Migrate a single space only (default: all spaces)."
    )
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print("  Term UUID Migration: legacy random → deterministic v5")
    print(f"{'=' * 60}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'LIVE MIGRATION'}")
    print(f"  Target: {args.space or 'all spaces'}")
    print(f"{LINE}\n")

    pool = await get_pool()

    try:
        # Verify prerequisite function exists
        if not await check_function_exists(pool):
            print("ERROR: vitalgraph_term_uuid() function not found in database.")
            print("       Run `vitalgraphdb init` first to create it.")
            sys.exit(1)

        # Get spaces
        if args.space:
            spaces = [args.space]
        else:
            spaces = await get_spaces(pool)

        if not spaces:
            print("No spaces found.")
            return

        print(f"Found {len(spaces)} space(s) to check.\n")

        total_terms = 0
        total_quads = 0

        for space_id in spaces:
            result = await migrate_space(pool, space_id, args.dry_run)

            if result['skipped']:
                print(f"  ✓ {space_id}: no legacy terms (already deterministic)")
            elif args.dry_run:
                print(f"  ⚠ {space_id}: {result['terms']} terms need migration")
                total_terms += result['terms']
            else:
                print(f"  ✅ {space_id}: migrated {result['terms']} terms, "
                      f"updated {result['quads']} quad refs ({result['elapsed']})")
                total_terms += result['terms']
                total_quads += result['quads']

        print(f"\n{LINE}")
        if args.dry_run:
            print(f"  DRY RUN COMPLETE: {total_terms} terms would be migrated")
            print(f"  Run without --dry-run to apply changes.")
        else:
            print(f"  MIGRATION COMPLETE: {total_terms} terms, {total_quads} quad refs updated")
        print()

    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
