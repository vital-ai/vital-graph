#!/usr/bin/env python3
"""Check what the KG Types API returns for the type URI picker."""
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from vitalgraph.client.vitalgraph_client import VitalGraphClient


async def main():
    client = VitalGraphClient()
    await client.open()

    # Get entity types
    print("=== KGEntityType instances ===")
    resp = await client.kgtypes.list_kgtypes(
        space_id="sp_semantic_search_test",
        page_size=50,
        type_uri="http://vital.ai/ontology/haley-ai-kg#KGEntityType",
    )
    print(f"Response type: {type(resp)}")
    print(f"is_success: {resp.is_success}")
    print(f"count: {resp.count}")
    if resp.types:
        for t in resp.types:
            print(f"  URI={t.URI}  name={getattr(t, 'name', '?')}")

    # Get frame types
    print("\n=== KGFrameType instances ===")
    resp2 = await client.kgtypes.list_kgtypes(
        space_id="sp_semantic_search_test",
        page_size=50,
        type_uri="http://vital.ai/ontology/haley-ai-kg#KGFrameType",
    )
    print(f"count: {resp2.count}")
    if resp2.types:
        for t in resp2.types:
            print(f"  URI={t.URI}  name={getattr(t, 'name', '?')}")

    # Also check all types (no filter)
    print("\n=== All KG Types ===" )
    resp3 = await client.kgtypes.list_kgtypes(
        space_id="sp_semantic_search_test",
        page_size=50,
    )
    print(f"count: {resp3.count}")
    if resp3.types:
        for t in resp3.types[:10]:
            vt = getattr(t, 'vitaltype', '?')
            print(f"  URI={t.URI}  name={getattr(t, 'name', '?')}  vitaltype={vt}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
