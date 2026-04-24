#!/usr/bin/env python3
"""
Frame Query WordNet Test

Explores WordNet frame data structure and tests frame_query with entity_refs.

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python vitalgraph_client_test/test_frame_query_wordnet.py
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.WARNING, format='%(message)s')

env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.sparql_model import SPARQLQueryRequest


SPACE_ID = "wordnet_frames"
GRAPH_ID = "urn:wordnet_frames"


async def main():
    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        print("Connection failed")
        return

    # Test the frame_query endpoint
    print("=== Frame Query Endpoint Test ===\n")
    r = await client.kgqueries.query_frames(
        space_id=SPACE_ID,
        graph_id=GRAPH_ID,
        page_size=5,
        offset=0
    )
    print(f"total: {r.total_count}, page: {len(r.results or [])}")
    has_refs = sum(1 for fr in (r.results or []) if fr.entity_refs)
    print(f"frames with entity_refs: {has_refs}")
    for fr in (r.results or [])[:3]:
        print(f"  frame: {fr.frame_uri[:70]}")
        print(f"  type: {fr.frame_type_uri}")
        print(f"  entity_refs: {len(fr.entity_refs)}")
        for er in fr.entity_refs[:3]:
            print(f"    slot_type: {er.slot_type_uri}")
            print(f"    entity: {er.entity_uri[:70]}")
        print()

    await client.close()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
