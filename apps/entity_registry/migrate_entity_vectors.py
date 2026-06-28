#!/usr/bin/env python3
"""
Entity Registry Vector/FTS/Geo Schema Migration Script.

Creates the pgvector, PostGIS, and FTS tables used by the entity registry's
search system (replacing Weaviate).

Usage:
    python entity_registry/migrate_entity_vectors.py                # Full setup
    python entity_registry/migrate_entity_vectors.py --drop         # Drop and recreate
    python entity_registry/migrate_entity_vectors.py --status       # Show table status
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg

from vitalgraph.config.config_loader import VitalGraphConfig
from vitalgraph.entity_registry.entity_registry_vector_schema import (
    create_tables_sql, drop_tables_sql, seed_default_index_sql,
    ENTITY_VECTOR_TABLE, LOCATION_VECTOR_TABLE, GEO_TABLE,
    FTS_ENTITY_TABLE, FTS_LOCATION_TABLE, VECTOR_INDEX_TABLE,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

LINE = '─' * 60


async def show_status(pool):
    """Show current table status."""
    tables = [
        VECTOR_INDEX_TABLE, ENTITY_VECTOR_TABLE, LOCATION_VECTOR_TABLE,
        GEO_TABLE, FTS_ENTITY_TABLE, FTS_LOCATION_TABLE,
    ]
    print(f"\n{LINE}")
    print("Entity Registry Vector/FTS/Geo Table Status")
    print(LINE)

    async with pool.acquire() as conn:
        for table in tables:
            exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = $1)",
                table,
            )
            if exists:
                count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                print(f"  ✅ {table:45s} ({count:,} rows)")
            else:
                print(f"  ❌ {table:45s} (not created)")

    # Check extensions
    async with pool.acquire() as conn:
        print(f"\n  Extensions:")
        for ext in ("vector", "postgis"):
            ok = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_extension WHERE extname = $1", ext
            )
            status = "✅" if ok else "❌ MISSING"
            print(f"    {status} {ext}")
    print()


async def create_schema(pool, drop_first: bool = False):
    """Create the vector/FTS/geo tables."""
    async with pool.acquire() as conn:
        # Ensure extensions
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")

        if drop_first:
            print("  Dropping existing tables...")
            for stmt in drop_tables_sql():
                await conn.execute(stmt)
            print("  Dropped.")

        print("  Creating tables...")
        for stmt in create_tables_sql():
            await conn.execute(stmt)
        print("  Tables created.")

        # Seed default index
        await conn.execute(seed_default_index_sql())
        print("  Default vector index seeded.")


async def main():
    parser = argparse.ArgumentParser(description="Entity Registry vector/FTS/geo migration")
    parser.add_argument('--status', action='store_true', help='Show current table status')
    parser.add_argument('--drop', action='store_true', help='Drop and recreate tables')
    args = parser.parse_args()

    config = VitalGraphConfig()
    db_config = config.get_database_config()
    pool = await asyncpg.create_pool(
        host=db_config.get('host', 'localhost'),
        port=db_config.get('port', 5432),
        user=db_config.get('user', 'postgres'),
        password=db_config.get('password', ''),
        database=db_config.get('database', 'vitalgraph'),
        min_size=1, max_size=3,
    )

    try:
        if args.status:
            await show_status(pool)
        else:
            print(f"\n{LINE}")
            print("Entity Registry Vector/FTS/Geo Migration")
            print(LINE)
            await create_schema(pool, drop_first=args.drop)
            print(f"\n  ✅ Migration complete.\n")
            await show_status(pool)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(main())
