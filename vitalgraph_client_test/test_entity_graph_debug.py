#!/usr/bin/env python3
"""
Debug script: reproduce include_entity_graph=True returning zero objects
while direct SPARQL finds data.
"""

import asyncio
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.DEBUG, format='%(message)s')
logger = logging.getLogger(__name__)

env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient


async def main():
    SPACE_ID = "lead_test"
    GRAPH_ID = "urn:lead_test"
    ENTITY_URI = "http://vital.ai/cardiff/kgentity/lead/7bad756d-07bc-45ff-a575-b971963cdef3"

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        print("❌ Connection failed!")
        return

    print(f"\n{'='*60}")
    print(f"  Debug: include_entity_graph for entity")
    print(f"  Space: {SPACE_ID}")
    print(f"  Graph: {GRAPH_ID}")
    print(f"  Entity: {ENTITY_URI}")
    print(f"{'='*60}\n")

    # --- Test 1: GET without entity graph ---
    print("--- Test 1: GET entity (include_entity_graph=False) ---")
    resp1 = await client.kgentities.get_kgentity(
        space_id=SPACE_ID,
        graph_id=GRAPH_ID,
        uri=ENTITY_URI,
        include_entity_graph=False
    )
    print(f"  is_success: {resp1.is_success}")
    print(f"  objects: {resp1.objects}")
    if resp1.objects:
        print(f"  type: {type(resp1.objects)}")
        if hasattr(resp1.objects, 'count'):
            print(f"  count: {resp1.objects.count}")

    # --- Test 2: GET with entity graph (raw HTTP first) ---
    print("\n--- Test 2a: Raw HTTP response for include_entity_graph=True ---")
    import json
    try:
        import httpx
        # Get auth token from client
        token = getattr(client, '_access_token', None) or getattr(client, 'access_token', None)
        headers = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        async with httpx.AsyncClient() as http:
            raw_resp = await http.get(
                "http://localhost:8001/api/graphs/kgentities",
                params={
                    'space_id': SPACE_ID,
                    'graph_id': GRAPH_ID,
                    'uri': ENTITY_URI,
                    'include_entity_graph': 'true'
                },
                headers=headers,
                timeout=30
            )
            print(f"  HTTP status: {raw_resp.status_code}")
            raw_data = raw_resp.json()
            if isinstance(raw_data, dict):
                print(f"  Response keys: {list(raw_data.keys())}")
                if '@graph' in raw_data:
                    print(f"  @graph length: {len(raw_data['@graph'])}")
                    if raw_data['@graph']:
                        print(f"  @graph[0] keys: {list(raw_data['@graph'][0].keys()) if isinstance(raw_data['@graph'][0], dict) else type(raw_data['@graph'][0])}")
                if 'graph' in raw_data:
                    print(f"  graph length: {len(raw_data['graph'])}")
                raw_str = json.dumps(raw_data, indent=2, default=str)
                print(f"  Response size: {len(raw_str)} chars")
                print(f"  First 2000 chars:\n{raw_str[:2000]}")
            else:
                print(f"  Response type: {type(raw_data)}")
    except Exception as e:
        print(f"  Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n--- Test 2b: GET entity (include_entity_graph=True) via client ---")
    resp2 = await client.kgentities.get_kgentity(
        space_id=SPACE_ID,
        graph_id=GRAPH_ID,
        uri=ENTITY_URI,
        include_entity_graph=True
    )
    print(f"  is_success: {resp2.is_success}")
    print(f"  objects: {resp2.objects}")
    if resp2.objects:
        print(f"  type: {type(resp2.objects)}")
        if hasattr(resp2.objects, 'count'):
            print(f"  count: {resp2.objects.count}")
        if hasattr(resp2.objects, 'graph_objects'):
            print(f"  graph_objects: {len(resp2.objects.graph_objects)} items")
            for i, obj in enumerate(resp2.objects.graph_objects[:5]):
                print(f"    [{i}] {type(obj).__name__}: {getattr(obj, 'URI', '?')}")

    # --- Test 3: GET frames for this entity ---
    print("\n--- Test 3: GET frames for entity ---")
    resp3 = await client.kgentities.get_kgentity_frames(
        space_id=SPACE_ID,
        graph_id=GRAPH_ID,
        entity_uri=ENTITY_URI,
    )
    print(f"  is_success: {resp3.is_success}")
    print(f"  objects: {resp3.objects}")
    if resp3.objects:
        print(f"  count: {len(resp3.objects)}")
        for i, obj in enumerate(resp3.objects[:5]):
            print(f"    [{i}] {type(obj).__name__}: {getattr(obj, 'URI', '?')}")

    # --- Test 4: LIST entities (small page) to check if entity exists ---
    print("\n--- Test 4: LIST entities (page_size=5) ---")
    resp4 = await client.kgentities.list_kgentities(
        space_id=SPACE_ID,
        graph_id=GRAPH_ID,
        page_size=5,
        include_entity_graph=False
    )
    print(f"  is_success: {resp4.is_success}")
    if hasattr(resp4, 'objects') and resp4.objects:
        print(f"  count: {len(resp4.objects)}")
        for i, obj in enumerate(resp4.objects[:5]):
            print(f"    [{i}] {type(obj).__name__}: {getattr(obj, 'URI', '?')}")

    await client.close()
    print("\n✅ Client closed")


if __name__ == "__main__":
    asyncio.run(main())
