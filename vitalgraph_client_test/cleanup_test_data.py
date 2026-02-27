#!/usr/bin/env python3
"""
Entity Registry Test Data Cleanup.

Removes all test entities created by load_test_data.py and the test suite.
Uses direct SQL to hard-delete (CASCADE) since the REST API only soft-deletes.

Usage:
    python vitalgraph_client_test/cleanup_test_data.py
    python vitalgraph_client_test/cleanup_test_data.py --dry-run
"""

import argparse
import asyncio
import json
import logging
import os
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).parent / 'test_data_manifest.json'
CREATED_BY = 'test_runner'


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


async def cleanup(dry_run: bool = False):
    pool = await get_pool()

    try:
        async with pool.acquire() as conn:
            # Find all entities created by test_runner
            rows = await conn.fetch(
                "SELECT entity_id, primary_name, status FROM entity WHERE created_by = $1",
                CREATED_BY,
            )
            entity_ids = [r['entity_id'] for r in rows]

            logger.info(f"Found {len(entity_ids)} entities created by '{CREATED_BY}'")
            for r in rows:
                logger.info(f"  {r['entity_id']}  {r['primary_name']:<30}  ({r['status']})")

            if not entity_ids:
                logger.info("Nothing to clean up.")
                return

            if dry_run:
                logger.info(f"\nDRY RUN — would delete {len(entity_ids)} entities (CASCADE)")
                return

            # Remove same-as rows first (no ON DELETE CASCADE on this FK)
            await conn.execute(
                "DELETE FROM entity_same_as WHERE source_entity_id = ANY($1) OR target_entity_id = ANY($1)",
                entity_ids,
            )

            # Hard-delete entities (CASCADE removes identifiers, aliases, category_map, changelog)
            deleted = await conn.execute(
                "DELETE FROM entity WHERE created_by = $1",
                CREATED_BY,
            )
            logger.info(f"\n✅ {deleted}")

            # Clean up vendor_test entity type if it exists and has no remaining entities
            remaining = await conn.fetchval(
                "SELECT COUNT(*) FROM entity e "
                "JOIN entity_type et ON e.entity_type_id = et.type_id "
                "WHERE et.type_key = 'vendor_test'"
            )
            if remaining == 0:
                result = await conn.execute(
                    "DELETE FROM entity_type WHERE type_key = 'vendor_test'"
                )
                if 'DELETE 1' in result:
                    logger.info("✅ Removed entity type 'vendor_test'")

            # Clean up orphaned changelog entries (entity_id set to NULL by CASCADE)
            orphaned = await conn.execute(
                "DELETE FROM entity_change_log WHERE entity_id IS NULL"
            )
            logger.info(f"✅ Cleaned orphaned changelog entries: {orphaned}")

    finally:
        await pool.close()

    # Remove manifest file
    if MANIFEST_PATH.exists() and not dry_run:
        MANIFEST_PATH.unlink()
        logger.info(f"✅ Removed {MANIFEST_PATH}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean up entity registry test data')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be deleted')
    args = parser.parse_args()

    asyncio.run(cleanup(dry_run=args.dry_run))
