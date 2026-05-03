#!/usr/bin/env python3
"""
Diagnose entities present in PostgreSQL but missing from Weaviate.

Fetches all active entity_ids from PostgreSQL, all entity_ids from Weaviate,
and reports the diff.

Usage:
    python entity_registry/check_weaviate_missing.py
    python entity_registry/check_weaviate_missing.py --output missing_ids.txt
    python entity_registry/check_weaviate_missing.py --sync          # actually sync the missing ones
    python entity_registry/check_weaviate_missing.py --sync --dry-run
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

import asyncpg
from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

LINE = "=" * 70


async def create_pool() -> asyncpg.Pool:
    from vitalgraph.config.config_loader import VitalGraphConfig
    config = VitalGraphConfig()
    db_config = config.get_database_config()
    return await asyncpg.create_pool(
        host=db_config.get('host', 'localhost'),
        port=int(db_config.get('port', 5432)),
        database=db_config.get('database', 'vitalgraph'),
        user=db_config.get('username', 'postgres'),
        password=db_config.get('password', ''),
        min_size=1,
        max_size=5,
    )


async def fetch_pg_entity_ids(pool: asyncpg.Pool) -> set:
    """Fetch all active entity_ids from PostgreSQL."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT entity_id FROM entity WHERE status = 'active' ORDER BY entity_id"
        )
    return {r['entity_id'] for r in rows}


async def fetch_weaviate_entity_ids(weaviate_index: EntityWeaviateIndex) -> set:
    """Fetch all entity_ids from the Weaviate EntityIndex collection."""
    await weaviate_index._ensure_connected()
    entity_ids = set()
    cursor_uuid = None
    while True:
        kwargs = {
            "limit": 1000,
            "include_vector": False,
            "return_properties": ["entity_id"],
        }
        if cursor_uuid:
            kwargs["after"] = cursor_uuid
        response = await weaviate_index.collection.query.fetch_objects(**kwargs)
        if not response.objects:
            break
        for obj in response.objects:
            eid = obj.properties.get('entity_id')
            if eid:
                entity_ids.add(eid)
            cursor_uuid = obj.uuid
    return entity_ids


async def fetch_pg_location_ids(pool: asyncpg.Pool) -> set:
    """Fetch all active location_ids from PostgreSQL."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT location_id FROM entity_location WHERE status = 'active' ORDER BY location_id"
        )
    return {r['location_id'] for r in rows}


async def fetch_weaviate_location_ids(weaviate_index: EntityWeaviateIndex) -> set:
    """Fetch all location_ids from the Weaviate LocationIndex collection."""
    await weaviate_index._ensure_connected()
    location_ids = set()
    cursor_uuid = None
    while True:
        kwargs = {
            "limit": 1000,
            "include_vector": False,
            "return_properties": ["location_id"],
        }
        if cursor_uuid:
            kwargs["after"] = cursor_uuid
        response = await weaviate_index.location_collection.query.fetch_objects(**kwargs)
        if not response.objects:
            break
        for obj in response.objects:
            lid = obj.properties.get('location_id')
            if lid is not None:
                # Normalize to int for consistent comparison with PG
                try:
                    location_ids.add(int(lid))
                except (ValueError, TypeError):
                    location_ids.add(lid)
            cursor_uuid = obj.uuid
    return location_ids


async def sync_missing_entities(weaviate_index: EntityWeaviateIndex, pool: asyncpg.Pool,
                                 missing_ids: set, dry_run: bool = False,
                                 batch_size: int = 100):
    """Sync only the missing entities from PostgreSQL to Weaviate."""
    from vitalgraph.entity_registry.entity_weaviate_schema import (
        entity_id_to_weaviate_uuid, entity_to_weaviate_properties,
    )
    from weaviate.classes.data import DataObject

    missing_list = sorted(missing_ids)
    total = len(missing_list)
    logger.info(f"Syncing {total:,} missing entities to Weaviate...")

    if dry_run:
        logger.info("DRY RUN — no changes will be made")
        # Show a sample
        sample = missing_list[:20]
        for eid in sample:
            logger.info(f"  Would sync: {eid}")
        if total > 20:
            logger.info(f"  ... and {total - 20:,} more")
        return 0

    await weaviate_index.ensure_collection()

    entity_data_sql = (
        "SELECT e.entity_id, e.primary_name, e.description, e.country, "
        "e.region, e.locality, e.website, e.latitude, e.longitude, e.status, "
        "et.type_key, et.type_label, et.type_description, "
        "ea.alias_name, ea.alias_type, "
        "ec.category_key, ec.category_label "
        "FROM entity e "
        "JOIN entity_type et ON e.entity_type_id = et.type_id "
        "LEFT JOIN entity_alias ea ON ea.entity_id = e.entity_id AND ea.status = 'active' "
        "LEFT JOIN entity_category_map ecm ON ecm.entity_id = e.entity_id AND ecm.status = 'active' "
        "LEFT JOIN category ec ON ec.category_id = ecm.category_id "
        "WHERE e.entity_id = ANY($1) "
        "ORDER BY e.entity_id"
    )

    upserted = 0
    t0 = time.time()

    # Process in chunks
    for chunk_start in range(0, total, batch_size):
        chunk_ids = missing_list[chunk_start:chunk_start + batch_size]

        async with pool.acquire() as conn:
            rows = await conn.fetch(entity_data_sql, chunk_ids)

            # Also fetch locations and identifiers
            loc_rows = await conn.fetch(
                "SELECT el.entity_id, el.location_name, el.formatted_address, "
                "el.locality, el.admin_area_1, el.country "
                "FROM entity_location el "
                "WHERE el.entity_id = ANY($1) AND el.status = 'active' "
                "ORDER BY el.entity_id, el.is_primary DESC, el.location_id",
                chunk_ids
            )
            id_rows = await conn.fetch(
                "SELECT entity_id, identifier_namespace, identifier_value "
                "FROM entity_identifier "
                "WHERE entity_id = ANY($1) AND status = 'active' "
                "ORDER BY entity_id",
                chunk_ids
            )

        # Group locations and identifiers by entity_id
        loc_map = {}
        for lr in loc_rows:
            loc_map.setdefault(lr['entity_id'], []).append(dict(lr))
        id_map = {}
        for ir in id_rows:
            id_map.setdefault(ir['entity_id'], []).append(dict(ir))

        # Build entity dicts from joined rows
        entities = {}
        for row in rows:
            eid = row['entity_id']
            if eid not in entities:
                entities[eid] = {
                    'entity_id': eid,
                    'primary_name': row['primary_name'],
                    'description': row['description'],
                    'country': row['country'],
                    'region': row['region'],
                    'locality': row['locality'],
                    'website': row['website'],
                    'latitude': row['latitude'],
                    'longitude': row['longitude'],
                    'status': row['status'],
                    'type_key': row['type_key'],
                    'type_label': row['type_label'],
                    'type_description': row['type_description'],
                    'aliases': [],
                    'categories': [],
                    'locations': loc_map.get(eid, []),
                    'identifiers': id_map.get(eid, []),
                }

            entity = entities[eid]
            alias_name = row['alias_name']
            if alias_name:
                seen = {a['alias_name'] for a in entity['aliases']}
                if alias_name not in seen:
                    entity['aliases'].append({
                        'alias_name': alias_name,
                        'alias_type': row['alias_type'],
                    })
            cat_key = row['category_key']
            if cat_key:
                seen = {c['category_key'] for c in entity['categories']}
                if cat_key not in seen:
                    entity['categories'].append({
                        'category_key': cat_key,
                        'category_label': row['category_label'],
                    })

        # Batch insert to Weaviate
        objects = []
        for entity in entities.values():
            try:
                obj_uuid = entity_id_to_weaviate_uuid(entity['entity_id'])
                properties = entity_to_weaviate_properties(entity)
                objects.append(DataObject(properties=properties, uuid=obj_uuid))
            except Exception as e:
                logger.error(f"Failed to prepare entity {entity.get('entity_id')}: {e}")

        if objects:
            # Trigger lazy reconnect if the token-refresh thread prepared a new client
            await weaviate_index._ensure_connected()
            response = await weaviate_index.collection.data.insert_many(objects)
            inserted = len(objects) - len(response.errors) if response.errors else len(objects)
            upserted += inserted
            if response.has_errors:
                for i, err in enumerate(response.errors):
                    logger.error(f"Insert error at index {i}: {err}")

        elapsed = time.time() - t0
        rate = upserted / elapsed if elapsed > 0 else 0
        logger.info(f"  Progress: {upserted:,}/{total:,} synced ({rate:.0f}/s)")

    logger.info(f"Sync complete: {upserted:,} entities inserted in {time.time() - t0:.1f}s")
    return upserted


async def sync_missing_locations(weaviate_index: EntityWeaviateIndex, pool: asyncpg.Pool,
                                 missing_ids: set, dry_run: bool = False,
                                 batch_size: int = 200):
    """Sync only the missing locations from PostgreSQL to Weaviate."""
    from vitalgraph.entity_registry.entity_weaviate_schema import (
        location_id_to_weaviate_uuid, location_to_weaviate_properties,
        entity_id_to_weaviate_uuid,
    )
    from weaviate.classes.data import DataObject

    missing_list = sorted(missing_ids)
    total = len(missing_list)
    logger.info(f"Syncing {total:,} missing locations to Weaviate...")

    if dry_run:
        logger.info("DRY RUN — no changes will be made")
        sample = missing_list[:20]
        for lid in sample:
            logger.info(f"  Would sync location_id: {lid}")
        if total > 20:
            logger.info(f"  ... and {total - 20:,} more")
        return 0

    await weaviate_index.ensure_collection()

    location_sql = (
        "SELECT el.location_id, el.entity_id, el.location_name, el.formatted_address, "
        "el.address_line_1, el.address_line_2, el.locality, el.admin_area_1, el.admin_area_2, "
        "el.country, el.country_code, el.postal_code, el.latitude, el.longitude, "
        "el.is_primary, el.status, "
        "lt.type_key AS location_type_key, lt.type_label AS location_type_label "
        "FROM entity_location el "
        "JOIN entity_location_type lt ON el.location_type_id = lt.location_type_id "
        "WHERE el.location_id = ANY($1) AND el.status = 'active'"
    )

    upserted = 0
    t0 = time.time()

    for chunk_start in range(0, total, batch_size):
        chunk_ids = missing_list[chunk_start:chunk_start + batch_size]

        async with pool.acquire() as conn:
            rows = await conn.fetch(location_sql, chunk_ids)

        objects = []
        for row in rows:
            try:
                loc = dict(row)
                obj_uuid = location_id_to_weaviate_uuid(loc['location_id'])
                entity_uuid = entity_id_to_weaviate_uuid(loc['entity_id'])
                properties = location_to_weaviate_properties(loc)
                objects.append(DataObject(
                    properties=properties,
                    uuid=obj_uuid,
                    references={"entity": entity_uuid},
                ))
            except Exception as e:
                logger.error(f"Failed to prepare location {row.get('location_id')}: {e}")

        if objects:
            await weaviate_index._ensure_connected()
            response = await weaviate_index.location_collection.data.insert_many(objects)
            inserted = len(objects) - len(response.errors) if response.errors else len(objects)
            upserted += inserted
            if response.has_errors:
                for i, err in enumerate(response.errors):
                    logger.error(f"Location insert error at index {i}: {err}")

        elapsed = time.time() - t0
        rate = upserted / elapsed if elapsed > 0 else 0
        logger.info(f"  Progress: {upserted:,}/{total:,} locations synced ({rate:.0f}/s)")

    logger.info(f"Location sync complete: {upserted:,} locations inserted in {time.time() - t0:.1f}s")
    return upserted


async def main():
    parser = argparse.ArgumentParser(
        description='Find entities in PostgreSQL missing from Weaviate and optionally sync them',
    )
    parser.add_argument('--output', '-o', help='Write missing entity_ids to a file')
    parser.add_argument('--sync', action='store_true', help='Sync missing entities to Weaviate')
    parser.add_argument('--dry-run', action='store_true', help='With --sync: show what would be synced')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for sync (default: 100)')
    parser.add_argument('--locations', action='store_true', help='Also check locations')
    args = parser.parse_args()

    # Connect
    weaviate_index = await EntityWeaviateIndex.from_env()
    if not weaviate_index:
        logger.error("Failed to connect to Weaviate. Check ENTITY_WEAVIATE_ENABLED and WEAVIATE_* env vars.")
        sys.exit(1)

    pool = await create_pool()

    try:
        print(LINE)
        print("PostgreSQL ↔ Weaviate Entity-Level Diff")
        print(LINE)

        # Fetch entity IDs from both sources
        t0 = time.time()
        print("\nFetching entity_ids from PostgreSQL...")
        pg_ids = await fetch_pg_entity_ids(pool)
        print(f"  PostgreSQL active entities: {len(pg_ids):,}")

        print("Fetching entity_ids from Weaviate...")
        wv_ids = await fetch_weaviate_entity_ids(weaviate_index)
        print(f"  Weaviate entities:          {len(wv_ids):,}")

        elapsed = time.time() - t0
        print(f"  (fetched in {elapsed:.1f}s)")

        # Compute diffs
        missing_from_weaviate = pg_ids - wv_ids
        extra_in_weaviate = wv_ids - pg_ids

        print(f"\n--- Entity Diff ---")
        print(f"  Missing from Weaviate (in PG but not WV): {len(missing_from_weaviate):,}")
        print(f"  Extra in Weaviate (in WV but not PG):     {len(extra_in_weaviate):,}")

        if missing_from_weaviate:
            sample = sorted(missing_from_weaviate)[:25]
            print(f"\n  Sample missing entity_ids (first 25):")
            for eid in sample:
                print(f"    {eid}")
            if len(missing_from_weaviate) > 25:
                print(f"    ... and {len(missing_from_weaviate) - 25:,} more")

        if extra_in_weaviate:
            sample = sorted(extra_in_weaviate)[:10]
            print(f"\n  Sample extra entity_ids in Weaviate (first 10):")
            for eid in sample:
                print(f"    {eid}")
            if len(extra_in_weaviate) > 10:
                print(f"    ... and {len(extra_in_weaviate) - 10:,} more")

        # Optionally check locations
        if args.locations:
            print(f"\n--- Location Diff ---")
            print("Fetching location_ids from PostgreSQL...")
            pg_loc_ids = await fetch_pg_location_ids(pool)
            print(f"  PostgreSQL active locations: {len(pg_loc_ids):,}")

            print("Fetching location_ids from Weaviate...")
            wv_loc_ids = await fetch_weaviate_location_ids(weaviate_index)
            print(f"  Weaviate locations:          {len(wv_loc_ids):,}")

            missing_locs = pg_loc_ids - wv_loc_ids
            extra_locs = wv_loc_ids - pg_loc_ids
            print(f"  Missing from Weaviate: {len(missing_locs):,}")
            print(f"  Extra in Weaviate:     {len(extra_locs):,}")

            if args.sync and missing_locs:
                print(f"\n{LINE}")
                await sync_missing_locations(
                    weaviate_index, pool, missing_locs,
                    dry_run=args.dry_run, batch_size=args.batch_size,
                )
            elif args.sync and not missing_locs:
                print("\nNo missing locations to sync.")

        # Write missing IDs to file
        if args.output and missing_from_weaviate:
            with open(args.output, 'w') as f:
                for eid in sorted(missing_from_weaviate):
                    f.write(eid + '\n')
            print(f"\nWrote {len(missing_from_weaviate):,} missing entity_ids to {args.output}")

        # Sync missing entities
        if args.sync and missing_from_weaviate:
            print(f"\n{LINE}")
            await sync_missing_entities(
                weaviate_index, pool, missing_from_weaviate,
                dry_run=args.dry_run, batch_size=args.batch_size,
            )
        elif args.sync and not missing_from_weaviate:
            print("\nNo missing entities to sync.")

        if not args.sync and missing_from_weaviate:
            print(f"\nTo sync missing entities, re-run with --sync")
            print(f"  python entity_registry/check_weaviate_missing.py --sync --dry-run")
            print(f"  python entity_registry/check_weaviate_missing.py --sync")

        print(LINE)

    finally:
        await pool.close()
        await weaviate_index.close()


if __name__ == '__main__':
    asyncio.run(main())
