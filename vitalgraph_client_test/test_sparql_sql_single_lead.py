#!/usr/bin/env python3
"""
SPARQL-SQL Backend — Single Lead Entity Load (Profile)

Creates a test space, loads ONE lead entity graph via the REST API,
and reports timing. Use this to measure end-to-end insert overhead.

Usage:
    python -m vitalgraph_client_test.test_sparql_sql_single_lead
    python -m vitalgraph_client_test.test_sparql_sql_single_lead --file lead_test_data/lead_0042.nt
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph.model.spaces_model import Space
from vitalgraph_client_test.entity_graph_lead.case_load_lead_graph import LoadLeadGraphTester

TEST_SPACE_ID = "sp_sql_single_lead"
TEST_GRAPH_ID = "urn:sql_single_lead"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default=None)
    args = parser.parse_args()

    if args.file:
        lead_file = Path(args.file)
    else:
        lead_files = sorted((project_root / "lead_test_data").glob("lead_*.nt"))
        if not lead_files:
            print("No lead .nt files found"); return
        lead_file = lead_files[0]

    if not lead_file.exists():
        print(f"Not found: {lead_file}"); return

    print("\n" + "=" * 70)
    print("  Single Lead Entity Load (REST API)")
    print("=" * 70)
    print(f"  File:  {lead_file.name}")
    print(f"  Space: {TEST_SPACE_ID}")
    print(f"  Graph: {TEST_GRAPH_ID}")

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        print("Failed to connect"); return

    try:
        # Cleanup + create space
        resp = await client.spaces.list_spaces()
        existing = [s.space for s in resp.spaces] if resp.is_success else []
        if TEST_SPACE_ID in existing:
            await client.spaces.delete_space(TEST_SPACE_ID)

        space = Space(space=TEST_SPACE_ID, space_name="Single Lead Profile",
                      space_description="Profile single lead insert")
        await client.spaces.create_space(space)
        await client.graphs.create_graph(TEST_SPACE_ID, TEST_GRAPH_ID)
        print(f"  Space ready\n")

        # Load
        t0 = time.monotonic()
        load_tester = LoadLeadGraphTester(client)
        results = await load_tester.run_tests(TEST_SPACE_ID, TEST_GRAPH_ID, str(lead_file))
        t_total = time.monotonic() - t0

        print(f"\n--- Results ---")
        print(f"  Entity URI:   {results.get('entity_uri', 'N/A')}")
        print(f"  Triple count: {results.get('triple_count', 'N/A')}")
        print(f"  Tests:        {results['tests_passed']}/{results['tests_run']}")
        print(f"  Wall-clock:   {t_total:.3f}s")
        print(f"\n  (Check server logs for ⏱️ timing breakdown)")

        # Cleanup
        await client.spaces.delete_space(TEST_SPACE_ID)
        print(f"  Space deleted")

    finally:
        await client.close()

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
