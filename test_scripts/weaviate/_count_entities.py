#!/usr/bin/env python3
"""
Count KGEntities and KGLead entities in production via VitalGraph client.

Usage:
    VITALGRAPH_CLIENT_ENVIRONMENT=prod python test_scripts/weaviate/_count_entities.py
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / '.env')

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

KGLEAD_TYPE = os.getenv("TEST_ENTITY_TYPE", "urn:acme:kg:entity:Lead")


async def main():
    client = VitalGraphClient()
    await client.open()

    space_id = os.getenv("TEST_SPACE_ID", "sp_sql_lead_dataset")
    graph_id = os.getenv("TEST_GRAPH_ID", "urn:lead_entity_graph_dataset")

    try:
        # List spaces to find data
        spaces_resp = await client.spaces.list_spaces()
        if spaces_resp.is_success:
            print(f"Available spaces:")
            for sp in spaces_resp.spaces:
                print(f"  - {sp.space}  ({sp.space_name})")
            # If target space doesn't exist, use first available
            space_names = [sp.space for sp in spaces_resp.spaces]
            if space_id not in space_names and space_names:
                space_id = space_names[0]
                print(f"\n  Using space: {space_id}")

        # Find graph
        graphs_resp = await client.graphs.list_graphs(space_id=space_id)
        if graphs_resp.is_success and graphs_resp.graphs:
            print(f"\nGraphs in {space_id}:")
            for g in graphs_resp.graphs:
                gid = g.graph_id if hasattr(g, 'graph_id') else str(g)
                print(f"  - {gid}")
            # Use first graph if target doesn't exist
            def _gid(g):
                if hasattr(g, 'graph_uri'):
                    return g.graph_uri
                if hasattr(g, 'graph_id'):
                    return g.graph_id
                return str(g)
            available_graphs = [_gid(g) for g in graphs_resp.graphs]
            if graph_id not in available_graphs and available_graphs:
                graph_id = available_graphs[0]

        print(f"\nSpace: {space_id}  Graph: {graph_id}\n")

        # 1. List all entities to get total
        all_resp = await client.kgentities.list_kgentities(
            space_id=space_id, graph_id=graph_id, page_size=1, offset=0
        )
        total = getattr(all_resp, 'total_count', None)
        print(f"Total KGEntities (list): {total}")

        # 2. KGQuery: no entity_type filter (all entities) — tests count query works
        all_query = {
            "criteria": {
                "search_string": None,
                "entity_type": None,
                "frame_type": None
            },
            "page_size": 100,
            "offset": 0
        }
        print(f"\nKGQuery criteria: entity_type=None (all)")
        all_query_resp = await client.kgentities.query_entities(
            space_id=space_id,
            graph_id=graph_id,
            query_criteria=all_query
        )
        all_q_objects = all_query_resp.objects if hasattr(all_query_resp, 'objects') else []
        all_q_info = all_query_resp.query_info if hasattr(all_query_resp, 'query_info') else {}
        all_q_total = all_q_info.get('total_results', len(all_q_objects or []))
        print(f"  total_count (query_info): {all_q_total}")
        print(f"  objects returned: {len(all_q_objects) if all_q_objects else 0}")
        if total and all_q_total:
            match = "✅" if all_q_total == total else "❌ MISMATCH"
            print(f"  list vs query count: {total} vs {all_q_total}  {match}")

        # 3. KGQuery: entity_type = KGLead (or override)
        lead_query = {
            "criteria": {
                "search_string": None,
                "entity_type": KGLEAD_TYPE,
                "frame_type": None
            },
            "page_size": 100,
            "offset": 0
        }
        print(f"\nKGQuery criteria: entity_type={KGLEAD_TYPE}")
        lead_resp = await client.kgentities.query_entities(
            space_id=space_id,
            graph_id=graph_id,
            query_criteria=lead_query
        )
        lead_objects = lead_resp.objects if hasattr(lead_resp, 'objects') else []
        lead_info = lead_resp.query_info if hasattr(lead_resp, 'query_info') else {}
        lead_total = lead_info.get('total_results', len(lead_objects or []))
        print(f"  total_count (query_info): {lead_total}")
        print(f"  objects returned: {len(lead_objects) if lead_objects else 0}")
        if lead_objects:
            print(f"  Sample entities:")
            for obj in lead_objects[:5]:
                name = str(getattr(obj, 'hasName', None) or getattr(obj, 'name', '?'))
                uri = str(getattr(obj, 'URI', '?'))
                print(f"    - {name:40s}  {uri[:60]}")

    finally:
        await client.close()


if __name__ == '__main__':
    asyncio.run(main())
