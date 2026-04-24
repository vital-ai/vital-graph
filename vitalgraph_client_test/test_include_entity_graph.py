#!/usr/bin/env python3
"""Test include_entity_graph on entity query against lead dataset."""
import asyncio, sys, json
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / '.env')

import logging
logging.basicConfig(level=logging.WARNING)

from vitalgraph.client.vitalgraph_client import VitalGraphClient

SPACE = "space_lead_dataset_test"
GRAPH = "urn:lead_entity_graph_dataset"


async def main():
    c = VitalGraphClient()
    await c.open()

    print("=== Test 1: Entity query WITHOUT include_entity_graph ===")
    r1 = await c.kgqueries.query_entities(
        space_id=SPACE, graph_id=GRAPH, page_size=3, offset=0
    )
    print(f"  entity_uris: {len(r1.entity_uris or [])}")
    print(f"  entity_graphs: {r1.entity_graphs}")
    print(f"  total_count: {r1.total_count}")

    print("\n=== Test 2: Entity query WITH include_entity_graph ===")
    r2 = await c.kgqueries.query_entities(
        space_id=SPACE, graph_id=GRAPH, page_size=3, offset=0,
        include_entity_graph=True
    )
    print(f"  entity_uris: {len(r2.entity_uris or [])}")
    print(f"  entity_graphs present: {r2.entity_graphs is not None}")
    print(f"  total_count: {r2.total_count}")

    if r2.entity_graphs:
        for uri, objects in r2.entity_graphs.items():
            print(f"\n  Entity: {uri[:70]}...")
            print(f"    graph objects: {len(objects)}")
            for obj in objects[:5]:
                obj_type = obj.get('type', '?').split('#')[-1]
                obj_uri = obj.get('uri', '?')[-40:]
                n_props = len(obj.get('properties', {}))
                print(f"      {obj_type} ({n_props} props) ...{obj_uri}")
            if len(objects) > 5:
                print(f"      ... and {len(objects) - 5} more")

    # Verify: entity_graphs keys should match entity_uris
    if r2.entity_graphs and r2.entity_uris:
        keys_match = set(r2.entity_graphs.keys()) == set(r2.entity_uris)
        print(f"\n  entity_graphs keys match entity_uris: {keys_match}")
        has_objects = all(len(v) > 0 for v in r2.entity_graphs.values())
        print(f"  all entities have >=1 graph object: {has_objects}")

    await c.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
