#!/usr/bin/env python3
"""
Weaviate Schema Update — add missing properties to existing collections in place.

This script compares the current Weaviate collection schemas against the
expected schemas defined in entity_weaviate_schema.py and adds any missing
properties without dropping or recreating the collections.

Usage:
    python entity_registry/weaviate_schema_update.py --dry-run   # preview changes
    python entity_registry/weaviate_schema_update.py             # apply changes
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

import weaviate.classes.config as wvc

from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex
from vitalgraph.entity_registry.entity_weaviate_schema import (
    get_collection_config,
    get_location_collection_config,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
)
logger = logging.getLogger(__name__)

LINE = '─' * 60


def _extract_expected_properties(config: dict) -> dict:
    """Extract {name: Property} from a collection config dict."""
    props = {}
    for p in config.get('properties', []):
        props[p.name] = p
    return props


async def _get_existing_property_names(collection) -> set:
    """Get set of property names already on a Weaviate collection."""
    config = await collection.config.get()
    return {p.name for p in config.properties}


async def update_collection_schema(
    weaviate_index: EntityWeaviateIndex,
    dry_run: bool = False,
):
    """Compare expected vs actual schemas and add missing properties."""
    await weaviate_index._ensure_connected()

    results = []

    # --- EntityIndex ---
    ent_config = get_collection_config(weaviate_index.collection_name)
    expected_ent = _extract_expected_properties(ent_config)
    try:
        existing_ent = await _get_existing_property_names(weaviate_index.collection)
    except Exception as e:
        print(f"  ❌ Could not read EntityIndex schema: {e}")
        existing_ent = set()

    missing_ent = {k: v for k, v in expected_ent.items() if k not in existing_ent}

    print(f"\n  EntityIndex ({weaviate_index.collection_name})")
    print(f"    Expected properties:  {len(expected_ent)}")
    print(f"    Existing properties:  {len(existing_ent)}")
    print(f"    Missing properties:   {len(missing_ent)}")
    if missing_ent:
        for name in sorted(missing_ent):
            print(f"      + {name}")

    # --- LocationIndex ---
    loc_config = get_location_collection_config(weaviate_index.location_collection_name)
    expected_loc = _extract_expected_properties(loc_config)
    try:
        existing_loc = await _get_existing_property_names(weaviate_index.location_collection)
    except Exception as e:
        print(f"  ❌ Could not read LocationIndex schema: {e}")
        existing_loc = set()

    missing_loc = {k: v for k, v in expected_loc.items() if k not in existing_loc}

    print(f"\n  LocationIndex ({weaviate_index.location_collection_name})")
    print(f"    Expected properties:  {len(expected_loc)}")
    print(f"    Existing properties:  {len(existing_loc)}")
    print(f"    Missing properties:   {len(missing_loc)}")
    if missing_loc:
        for name in sorted(missing_loc):
            print(f"      + {name}")

    total_missing = len(missing_ent) + len(missing_loc)
    if total_missing == 0:
        print(f"\n  ✅ All schemas are up to date — nothing to do")
        return

    if dry_run:
        print(f"\n  DRY RUN — would add {total_missing} properties total")
        return

    # --- Apply EntityIndex additions ---
    for name, prop in missing_ent.items():
        try:
            await weaviate_index.collection.config.add_property(prop)
            print(f"    ✅ Added '{name}' to EntityIndex")
            results.append(('EntityIndex', name, True, None))
        except Exception as e:
            print(f"    ❌ Failed to add '{name}' to EntityIndex: {e}")
            results.append(('EntityIndex', name, False, str(e)))

    # --- Apply LocationIndex additions ---
    for name, prop in missing_loc.items():
        try:
            await weaviate_index.location_collection.config.add_property(prop)
            print(f"    ✅ Added '{name}' to LocationIndex")
            results.append(('LocationIndex', name, True, None))
        except Exception as e:
            print(f"    ❌ Failed to add '{name}' to LocationIndex: {e}")
            results.append(('LocationIndex', name, False, str(e)))

    # --- Summary ---
    succeeded = sum(1 for _, _, ok, _ in results if ok)
    failed = sum(1 for _, _, ok, _ in results if not ok)
    print(f"\n  Done: {succeeded} added, {failed} failed")


async def main():
    parser = argparse.ArgumentParser(
        prog='weaviate_schema_update',
        description='Add missing properties to existing Weaviate collections in place',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be added without making changes')
    args = parser.parse_args()

    print("Weaviate Schema Update")
    print(LINE)

    weaviate_index = await EntityWeaviateIndex.from_env()
    if not weaviate_index:
        print("Failed to connect to Weaviate. Check ENTITY_WEAVIATE_ENABLED and WEAVIATE_* env vars.")
        sys.exit(1)

    try:
        await update_collection_schema(weaviate_index, dry_run=args.dry_run)
    finally:
        await weaviate_index.close()

    print(LINE)


if __name__ == '__main__':
    asyncio.run(main())
