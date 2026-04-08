#!/usr/bin/env python3
"""
Weaviate Admin Script for Entity Registry.

Inspect and manage Weaviate collections: list, status, delete, load, check.

Usage:
    python entity_registry/weaviate_admin.py status
    python entity_registry/weaviate_admin.py collections
    python entity_registry/weaviate_admin.py delete
    python entity_registry/weaviate_admin.py load
    python entity_registry/weaviate_admin.py check
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

# Force native DNS resolver for async gRPC — the default c-ares resolver
# does not respect VPN/system DNS on some platforms.
os.environ.setdefault('GRPC_DNS_RESOLVER', 'native')

# Add project root to Python path
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
    format='%(asctime)s %(levelname)s: %(message)s',
)
logger = logging.getLogger(__name__)

LINE = '─' * 60


async def create_pool() -> asyncpg.Pool:
    """Create an asyncpg connection pool from env vars."""
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


# ------------------------------------------------------------------
# collections
# ------------------------------------------------------------------

async def cmd_collections(weaviate_index: EntityWeaviateIndex):
    """List all collections on the Weaviate instance."""
    collections = await weaviate_index.list_all_collections()
    if not collections:
        print("No collections found on the Weaviate instance.")
        return

    print(f"Weaviate Collections ({len(collections)} total)")
    print(LINE)
    for c in sorted(collections, key=lambda x: x['name']):
        obj_str = f"{c['object_count']:,}" if isinstance(c.get('object_count'), int) else '?'
        props = c.get('properties', '?')
        refs = c.get('references', '?')
        print(f"  {c['name']:<45} objects={obj_str:<8} props={props}  refs={refs}")
    print(LINE)


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------

async def cmd_status(weaviate_index: EntityWeaviateIndex):
    """Show detailed status for EntityIndex and LocationIndex."""
    status = await weaviate_index.get_status()

    print("Weaviate Collection Status")
    print(LINE)
    for label, info in status.items():
        display = label.replace('_', ' ').title()
        if info.get('error'):
            print(f"\n  {display}:")
            print(f"    ❌ Error: {info['error'][:120]}")
            continue
        if not info.get('exists'):
            print(f"\n  {display}:")
            print(f"    ⚠️  Does not exist")
            continue

        print(f"\n  {display}:")
        print(f"    Collection:   {info.get('collection_name', 'N/A')}")
        print(f"    Objects:      {info.get('object_count', 0):,}")
        if info.get('properties'):
            props = info['properties']
            print(f"    Properties:   {len(props)}")
            for p in props:
                print(f"      - {p}")
        if info.get('references'):
            print(f"    References:   {', '.join(info['references'])}")
        else:
            print(f"    References:   (none)")
        if info.get('vectorizer'):
            print(f"    Vectorizer:   {info['vectorizer'][:100]}")
    print(LINE)


# ------------------------------------------------------------------
# delete
# ------------------------------------------------------------------

async def cmd_delete(weaviate_index: EntityWeaviateIndex, dry_run: bool = False):
    """Delete EntityIndex and LocationIndex collections (rebuild from scratch)."""
    status = await weaviate_index.get_status()
    ent_info = status.get('entity_index', {})
    loc_info = status.get('location_index', {})

    print("Delete Weaviate Collections")
    print(LINE)

    if ent_info.get('exists'):
        name = ent_info['collection_name']
        count = ent_info.get('object_count', 0)
        print(f"  EntityIndex:  {name}  ({count:,} objects)")
    else:
        print(f"  EntityIndex:  does not exist")

    if loc_info.get('exists'):
        name = loc_info['collection_name']
        count = loc_info.get('object_count', 0)
        print(f"  LocationIndex: {name}  ({count:,} objects)")
    else:
        print(f"  LocationIndex: does not exist")

    if dry_run:
        print(f"\n  DRY RUN — would delete both collections")
        return

    print(f"\n  Rebuilding (drop + recreate with cross-references)...")
    ok = await weaviate_index.rebuild_collection()
    if ok:
        print(f"  ✅ Collections recreated successfully")
        # Verify
        new_status = await weaviate_index.get_status()
        for label, info in new_status.items():
            display = label.replace('_', ' ').title()
            if info.get('exists'):
                refs = ', '.join(info.get('references', [])) or '(none)'
                print(f"    {display}: {info['collection_name']}  refs=[{refs}]")
    else:
        print(f"  ❌ Failed to recreate collections")


# ------------------------------------------------------------------
# load
# ------------------------------------------------------------------

async def cmd_load(weaviate_index: EntityWeaviateIndex, batch_size: int = 100,
                   dry_run: bool = False, vectors_dir: str = None):
    """Load entities and locations from PostgreSQL into Weaviate."""
    pool = await create_pool()
    try:
        async with pool.acquire() as conn:
            pg_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active'"
            )
            pg_locations = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_location WHERE status = 'active'"
            )

        print("Load PostgreSQL → Weaviate")
        print(LINE)
        print(f"  PostgreSQL active entities:  {pg_entities:,}")
        print(f"  PostgreSQL active locations: {pg_locations:,}")

        # Load pre-computed vectors if provided
        entity_vectors = None
        location_vectors = None
        if vectors_dir:
            from vitalgraph.entity_registry.entity_vectorizer import load_vectors_from_jsonl
            vdir = Path(vectors_dir)
            ent_vec_path = vdir / 'entity_vectors.jsonl'
            loc_vec_path = vdir / 'location_vectors.jsonl'
            if ent_vec_path.exists():
                entity_vectors = load_vectors_from_jsonl(ent_vec_path, 'entity_id')
                print(f"  Loaded {len(entity_vectors):,} entity vectors from {ent_vec_path.name}")
            if loc_vec_path.exists():
                location_vectors = load_vectors_from_jsonl(loc_vec_path, 'location_id')
                print(f"  Loaded {len(location_vectors):,} location vectors from {loc_vec_path.name}")
            if not entity_vectors and not location_vectors:
                print(f"  ⚠️  No vector files found in {vdir}")

        if dry_run:
            print(f"\n  DRY RUN — would sync {pg_entities:,} entities and {pg_locations:,} locations")
            return

        # Ensure collections exist with cross-refs
        await weaviate_index.ensure_collection()

        # Sync entities
        vec_label = f", {len(entity_vectors):,} pre-computed vectors" if entity_vectors else ""
        print(f"\n  Syncing entities (batch_size={batch_size}{vec_label})...")
        t0 = time.time()
        ent_upserted, ent_deleted = await weaviate_index.full_sync(
            pool, batch_size=batch_size, entity_vectors=entity_vectors)
        t1 = time.time()
        print(f"  ✅ Entities: {ent_upserted:,} upserted, {ent_deleted:,} stale deleted in {t1-t0:.1f}s")

        # Sync locations
        vec_label = f", {len(location_vectors):,} pre-computed vectors" if location_vectors else ""
        print(f"\n  Syncing locations (batch_size={batch_size * 2}{vec_label})...")
        t2 = time.time()
        loc_upserted, loc_deleted = await weaviate_index.location_sync(
            pool, batch_size=batch_size * 2, location_vectors=location_vectors)
        t3 = time.time()
        print(f"  ✅ Locations: {loc_upserted:,} upserted, {loc_deleted:,} stale deleted in {t3-t2:.1f}s")

        # Final status
        print(f"\n  Total time: {t3-t0:.1f}s")
        new_status = await weaviate_index.get_status()
        for label, info in new_status.items():
            display = label.replace('_', ' ').title()
            if info.get('exists'):
                refs = ', '.join(info.get('references', [])) or '(none)'
                print(f"    {display}: {info.get('object_count', 0):,} objects  refs=[{refs}]")
        print(LINE)
    finally:
        await pool.close()


# ------------------------------------------------------------------
# check
# ------------------------------------------------------------------

async def cmd_check(weaviate_index: EntityWeaviateIndex):
    """Check consistency between Weaviate and PostgreSQL."""
    pool = await create_pool()
    try:
        async with pool.acquire() as conn:
            pg_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entity WHERE status = 'active'"
            )
            pg_locations = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_location WHERE status = 'active'"
            )
    finally:
        await pool.close()

    status = await weaviate_index.get_status()
    ent_info = status.get('entity_index', {})
    loc_info = status.get('location_index', {})
    wv_entities = ent_info.get('object_count', 0) if ent_info.get('exists') else 0
    wv_locations = loc_info.get('object_count', 0) if loc_info.get('exists') else 0

    print("Weaviate ↔ PostgreSQL Consistency Check")
    print(LINE)

    print(f"\n  EntityIndex:")
    print(f"    Collection:         {ent_info.get('collection_name', 'N/A')}")
    print(f"    PostgreSQL active:  {pg_entities:,}")
    print(f"    Weaviate objects:   {wv_entities:,}")
    if ent_info.get('error'):
        print(f"    ❌ Error: {ent_info['error'][:100]}")
    elif not ent_info.get('exists'):
        print(f"    ⚠️  Collection does not exist")
    elif pg_entities == wv_entities:
        print(f"    ✅ Counts match")
    else:
        diff = wv_entities - pg_entities
        direction = "extra in Weaviate" if diff > 0 else "missing from Weaviate"
        print(f"    ⚠️  Mismatch: {abs(diff):,} {direction}")

    if ent_info.get('references'):
        print(f"    References:         {', '.join(ent_info['references'])}")

    print(f"\n  LocationIndex:")
    print(f"    Collection:         {loc_info.get('collection_name', 'N/A')}")
    print(f"    PostgreSQL active:  {pg_locations:,}")
    print(f"    Weaviate objects:   {wv_locations:,}")
    if loc_info.get('error'):
        print(f"    ❌ Error: {loc_info['error'][:100]}")
    elif not loc_info.get('exists'):
        print(f"    ⚠️  Collection does not exist")
    elif pg_locations == wv_locations:
        print(f"    ✅ Counts match")
    else:
        diff = wv_locations - pg_locations
        direction = "extra in Weaviate" if diff > 0 else "missing from Weaviate"
        print(f"    ⚠️  Mismatch: {abs(diff):,} {direction}")

    if loc_info.get('references'):
        print(f"    References:         {', '.join(loc_info['references'])}")

    print(LINE)
    has_mismatch = (pg_entities != wv_entities or pg_locations != wv_locations)
    if has_mismatch and not ent_info.get('error'):
        print("\n  To fix: python entity_registry/weaviate_admin.py load")


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(
        prog='weaviate_admin',
        description='Weaviate administration — inspect, delete, load, and check collections',
    )
    subparsers = parser.add_subparsers(dest='command')
    subparsers.add_parser('status', help='Detailed status of EntityIndex and LocationIndex')
    subparsers.add_parser('collections', help='List all Weaviate collections with stats')

    del_p = subparsers.add_parser('delete', help='Delete and recreate EntityIndex + LocationIndex')
    del_p.add_argument('--dry-run', action='store_true', help='Show what would be deleted')

    load_p = subparsers.add_parser('load', help='Load entities + locations from PostgreSQL into Weaviate')
    load_p.add_argument('--dry-run', action='store_true', help='Show counts without loading')
    load_p.add_argument('--batch-size', type=int, default=100, help='Batch size (default: 100)')
    load_p.add_argument('--vectors', type=str, default=None, metavar='DIR',
                        help='Directory containing entity_vectors.jsonl and/or '
                             'location_vectors.jsonl for pre-computed vectors')

    subparsers.add_parser('check', help='Check consistency between Weaviate and PostgreSQL')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    weaviate_index = await EntityWeaviateIndex.from_env()
    if not weaviate_index:
        print("Failed to connect to Weaviate. Check ENTITY_WEAVIATE_ENABLED and WEAVIATE_* env vars.")
        sys.exit(1)

    try:
        if args.command == 'status':
            await cmd_status(weaviate_index)
        elif args.command == 'collections':
            await cmd_collections(weaviate_index)
        elif args.command == 'delete':
            await cmd_delete(weaviate_index, dry_run=getattr(args, 'dry_run', False))
        elif args.command == 'load':
            await cmd_load(weaviate_index,
                           batch_size=getattr(args, 'batch_size', 100),
                           dry_run=getattr(args, 'dry_run', False),
                           vectors_dir=getattr(args, 'vectors', None))
        elif args.command == 'check':
            await cmd_check(weaviate_index)
    finally:
        await weaviate_index.close()


if __name__ == '__main__':
    asyncio.run(main())
