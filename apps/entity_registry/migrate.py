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

Against a database named explicitly (production, the AWS test env):

    LIVE_DB_HOST=... LIVE_DB_PORT=5432 LIVE_DB_NAME=... LIVE_DB_USER=vitalgraph_user \
    LIVE_DB_PASSWORD=... python apps/entity_registry/migrate.py --db LIVE --ssl require --migrate-only

WHY `--db`. Without it the target comes from the VitalGraph config profile, and
for production that is WRONG TWICE: `.env`'s `PROD_DB_HOST` names a different,
unrelated instance, and its `PROD_DB_PASSWORD` is stale. The live cluster's host
is only in the ECS task definition and its password only in the task's secret,
so a production migration must name them. The target is printed before anything
runs.

Run as the role that OWNS the registry tables (`vitalgraph_user` on production):
objects created by another role are unreadable to the server.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the repo root to the FRONT of sys.path so the local `vitalgraph` source
# wins over any stale copy installed in site-packages. This file lives at
# apps/entity_registry/migrate.py, so the repo root is three parents up — NOT
# parent.parent (which is apps/). Inserting at 0 also beats the script-dir entry
# Python prepends when run as `python apps/entity_registry/migrate.py`.
project_root = Path(__file__).resolve().parents[2]
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


# A migration may backfill a large table (`is_placeholder_name` took 15.7 s on
# 1.28M production rows) and production caps statements at 60 s, so the cap is
# lifted for this session. A SHORT lock timeout instead: if a running transaction
# holds a table, fail fast and re-run (every migration is idempotent) rather than
# queue an exclusive lock that stalls the live service behind it.
SESSION_SETTINGS = {'statement_timeout': '0', 'lock_timeout': '5s'}


def connect_kwargs(prefix=None, ssl=None, environ=os.environ) -> dict:
    """asyncpg connection arguments: from `PREFIX_DB_*` if a prefix is given, else the config profile."""
    if prefix:
        def env(key, *alts, default=None):
            for k in (key,) + alts:
                v = environ.get(f"{prefix}_DB_{k}")
                if v:
                    return v
            if default is None:
                raise SystemExit(f"--db {prefix}: {prefix}_DB_{key} is not set")
            return default
        kw = dict(host=env('HOST'), port=int(env('PORT', default='5432')),
                  database=env('NAME', 'DATABASE'), user=env('USER', 'USERNAME'),
                  password=env('PASSWORD'))
    else:
        db_config = VitalGraphConfig().get_database_config()
        kw = dict(host=db_config.get('host', 'localhost'),
                  port=int(db_config.get('port', 5432)),
                  database=db_config.get('database', 'vitalgraph'),
                  user=db_config.get('username', 'postgres'),
                  password=db_config.get('password', ''))
    # asyncpg's own default is `prefer` (SSL if offered, else plain). `require`
    # refuses to fall back, which is what a production run should say.
    if ssl:
        kw['ssl'] = ssl
    return kw


async def get_pool(kw: dict = None, server_settings: dict = None) -> asyncpg.Pool:
    """A pool on `kw` (default: the config profile). Other apps import this with no
    arguments; only `main` below passes the migration session settings."""
    return await asyncpg.create_pool(**(kw or connect_kwargs()), min_size=1, max_size=3,
                                     server_settings=server_settings)


async def describe_target(pool: asyncpg.Pool, host: str) -> None:
    """Say which database this is about to change, before it changes anything."""
    row = await pool.fetchrow(
        "SELECT inet_server_addr()::text AS addr, current_database() AS db, current_user AS usr, "
        "current_setting('server_version') AS ver, "
        "(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()) AS ssl")
    print(f"TARGET: host={host} ({row['addr']}) db={row['db']} user={row['usr']} "
          f"server={row['ver']} ssl={row['ssl']}")


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
    parser.add_argument('--db', metavar='PREFIX',
                        help='connect with PREFIX_DB_HOST/_PORT/_NAME/_USER/_PASSWORD instead '
                             'of the config profile (required for production; see the docstring)')
    parser.add_argument('--ssl', choices=['disable', 'prefer', 'require', 'verify-ca', 'verify-full'],
                        help="SSL mode (default: asyncpg's, prefer); use require for production")
    args = parser.parse_args()

    schema = EntityRegistrySchema()
    kw = connect_kwargs(args.db, args.ssl)
    pool = await get_pool(kw, SESSION_SETTINGS)

    try:
        await describe_target(pool, kw['host'])
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
