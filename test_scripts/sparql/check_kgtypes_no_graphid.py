#!/usr/bin/env python3
"""
Quick check: query KG Types via the Python client.
Validates current data in framenet_kgtypes_test space.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

SPACE_ID = "framenet_kgtypes_test"


async def main():
    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    # 1. List KG Types
    print(f"Listing KG Types for space={SPACE_ID}...")
    resp = await client.kgtypes.list_kgtypes(
        space_id=SPACE_ID, page_size=10, offset=0,
    )
    if resp.is_success:
        print(f"✓ List: {resp.count} total types, {len(resp.types)} on page 1")
        for t in resp.types[:5]:
            if isinstance(t, dict):
                name = t.get('name') or t.get('type_name') or t.get('uri', '?')
            else:
                name = getattr(t, 'name', None) or getattr(t, 'type_name', None) or str(getattr(t, 'URI', '?'))
            print(f"    • {name}")
    else:
        print(f"❌ List failed: {resp.error_message}")

    # 2. Search KG Types (keyword)
    print()
    print("Searching 'Commerce' (keyword)...")
    resp = await client.kgtypes.search_types(
        space_id=SPACE_ID,
        query="Commerce", search_mode="keyword",
    )
    if resp.is_success:
        print(f"✓ Search: {resp.count} results")
        for t in (resp.types or [])[:5]:
            name = t.get('name', t.get('uri', '?')) if isinstance(t, dict) else getattr(t, 'name', '?')
            print(f"    • {name}")
    else:
        print(f"❌ Search failed: {resp.error_message}")

    await client.close()
    print()
    print("Done.")
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
