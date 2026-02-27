#!/usr/bin/env python3
"""
Entity Registry Schema Migration Script.

Creates tables, indexes, seed data, and applies schema migrations.
This is the ONLY way schema changes should be applied — the running
service never modifies the database schema.

Usage:
    python entity_registry/migrate.py                  # Full setup (create + migrate)
    python entity_registry/migrate.py --dry-run        # Show what would run
    python entity_registry/migrate.py --migrate-only   # Only run ALTER TABLE migrations
    python entity_registry/migrate.py --create-only    # Only create tables/indexes/seeds
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg

from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.entity_registry.entity_registry_schema import EntityRegistrySchema

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
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


async def run_create(pool: asyncpg.Pool, schema: EntityRegistrySchema, dry_run: bool):
    """Create tables, indexes, and seed data."""
    print("\n📋 CREATE: Tables, indexes, and seed data")
    print(LINE)

    stmts = []
    stmts += [(sql.strip(), 'table') for sql in schema.create_tables_sql()]
    stmts += [(sql, 'index') for sql in schema.create_indexes_sql()]
    stmts += [(sql.strip(), 'view') for sql in schema.create_views_sql()]
    stmts += [(schema.seed_entity_types_sql().strip(), 'seed')]
    stmts += [(schema.seed_entity_categories_sql().strip(), 'seed')]
    stmts += [(schema.seed_location_types_sql().strip(), 'seed')]
    stmts += [(schema.seed_relationship_types_sql().strip(), 'seed')]

    for sql, kind in stmts:
        label = sql[:80].replace('\n', ' ').strip()
        if dry_run:
            print(f"  [DRY RUN] ({kind}) {label}...")
        else:
            await pool.execute(sql)
            print(f"  ✅ ({kind}) {label}...")

    count = len(stmts)
    if dry_run:
        print(f"\nDRY RUN — {count} statements would be executed.")
    else:
        print(f"\n✅ {count} statements executed.")


async def run_migrations(pool: asyncpg.Pool, schema: EntityRegistrySchema, dry_run: bool):
    """Run ALTER TABLE and other schema migrations."""
    migrations = schema.migrations_sql()

    print(f"\n📋 MIGRATE: {len(migrations)} migration(s)")
    print(LINE)

    if not migrations:
        print("  No migrations to run.")
        return

    for i, sql in enumerate(migrations, 1):
        if dry_run:
            print(f"  [DRY RUN] {i}. {sql}")
        else:
            await pool.execute(sql)
            print(f"  ✅ {i}. {sql}")

    if dry_run:
        print(f"\nDRY RUN — {len(migrations)} migrations would be applied.")
    else:
        print(f"\n✅ {len(migrations)} migrations applied.")


async def check_status(pool: asyncpg.Pool):
    """Show current schema status."""
    print("\n📋 SCHEMA STATUS")
    print(LINE)

    tables = [
        'entity_type', 'entity', 'entity_identifier', 'entity_alias',
        'entity_same_as', 'category', 'entity_category_map', 'entity_change_log',
        'entity_location_type', 'entity_location', 'entity_location_category_map',
        'relationship_type', 'entity_relationship',
    ]

    for table in tables:
        exists = await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
            table,
        )
        if exists:
            count = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"  ✅ {table:<25} ({count:,} rows)")
        else:
            print(f"  ❌ {table:<25} (missing)")

    # Check for new entity columns
    new_cols = ['latitude', 'longitude', 'metadata', 'verified', 'verified_by', 'verified_time']
    print()
    for col in new_cols:
        has_col = await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'entity' AND column_name = $1)", col
        )
        print(f"  {col:<20} {'✅ exists' if has_col else '❌ missing (run migrate)'}")

    # Check views
    for view_name in ['entity_location_view', 'entity_relationship_view']:
        has_view = await pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.views WHERE table_name = $1)",
            view_name,
        )
        print(f"  {view_name:<20} {'✅ exists' if has_view else '❌ missing (run create)'}")

    # Check for legacy entity_category table (should be renamed to category)
    has_legacy = await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'entity_category')"
    )
    if has_legacy:
        print(f"\n  ⚠️  Legacy 'entity_category' table still exists (run migrate to rename to 'category')")



async def main():
    parser = argparse.ArgumentParser(
        prog='migrate',
        description='Entity Registry schema migration tool',
    )
    parser.add_argument('--dry-run', action='store_true', help='Show what would run without executing')
    parser.add_argument('--create-only', action='store_true', help='Only create tables/indexes/seeds')
    parser.add_argument('--migrate-only', action='store_true', help='Only run ALTER TABLE migrations')
    parser.add_argument('--status', action='store_true', help='Show current schema status')
    args = parser.parse_args()

    schema = EntityRegistrySchema()
    pool = await get_pool()

    try:
        if args.status:
            await check_status(pool)
            return

        if args.create_only:
            await run_create(pool, schema, args.dry_run)
        elif args.migrate_only:
            await run_migrations(pool, schema, args.dry_run)
        else:
            # Full setup: create + migrate
            await run_create(pool, schema, args.dry_run)
            await run_migrations(pool, schema, args.dry_run)

        if not args.dry_run:
            print()
            await check_status(pool)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
