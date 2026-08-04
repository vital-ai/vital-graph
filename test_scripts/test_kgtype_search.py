"""
Test KG Types search via the Python client.
Tests all search modes with pagination (page_size, offset).
"""
import asyncio
from vitalgraph.client.vitalgraph_client import VitalGraphClient

SP_KG_TYPES = 'sp_kg_types'
SEARCH_TERM = 'certainty'
SEARCH_MODES = ['keyword', 'fts', 'vector', 'hybrid']


def print_results(resp, label):
    print(f"  [{label}]")
    print(f"    is_success: {resp.is_success}")
    count = getattr(resp, 'count', 0)
    total_count = getattr(resp, 'total_count', '?')
    page_size = getattr(resp, 'page_size', '?')
    offset = getattr(resp, 'offset', '?')
    print(f"    count={count}  total_count={total_count}  page_size={page_size}  offset={offset}")
    types = getattr(resp, 'types', []) or []
    for t in types[:3]:
        name = t.get('name', '?') if isinstance(t, dict) else str(t)
        score = t.get('score', '') if isinstance(t, dict) else ''
        print(f"      - {name}  score={score}")
    if len(types) > 3:
        print(f"      ... and {len(types) - 3} more")


async def test_search_paginated(client, mode):
    print(f"\n=== mode='{mode}' ===")
    # Page 1: offset=0, page_size=3
    resp1 = await client.kgtypes.search_types(
        SP_KG_TYPES, SEARCH_TERM, search_mode=mode, page_size=3, offset=0
    )
    print_results(resp1, "page 1 (offset=0, page_size=3)")

    # Page 2: offset=3, page_size=3
    resp2 = await client.kgtypes.search_types(
        SP_KG_TYPES, SEARCH_TERM, search_mode=mode, page_size=3, offset=3
    )
    print_results(resp2, "page 2 (offset=3, page_size=3)")

    # Verify total_count is consistent
    tc1 = getattr(resp1, 'total_count', None)
    tc2 = getattr(resp2, 'total_count', None)
    if tc1 == tc2:
        print(f"  ✓ total_count consistent: {tc1}")
    else:
        print(f"  ✗ total_count MISMATCH: page1={tc1} page2={tc2}")

    # Verify pages don't overlap
    uris1 = {t['uri'] for t in (getattr(resp1, 'types', []) or []) if isinstance(t, dict)}
    uris2 = {t['uri'] for t in (getattr(resp2, 'types', []) or []) if isinstance(t, dict)}
    overlap = uris1 & uris2
    if not overlap:
        print(f"  ✓ no overlap between pages")
    else:
        print(f"  ✗ OVERLAP: {overlap}")


async def main():
    print("Connecting to VitalGraph...")
    client = VitalGraphClient()
    await client.open()
    print("Connected.")

    try:
        for mode in SEARCH_MODES:
            await test_search_paginated(client, mode)
    finally:
        await client.close()
        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
