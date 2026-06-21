#!/usr/bin/env python3
"""
Multi-Value Property Filter & Slot Comparator Integration Test Runner

Creates test data, runs all multi-value filter tests, then cleans up.
Requires a running VitalGraph server (configured via env vars).

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python vitalgraph_client_test/test_multi_value_filters.py [--query-mode edge|direct]
"""

import asyncio
import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
load_dotenv(project_root / '.env')

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SPACE = "test_multivalue"
GRAPH = "urn:test_multivalue_graph"


async def main(query_mode: str):
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    client = VitalGraphClient()
    await client.open()

    # Ensure space + graph exist (ignore errors if already present)
    try:
        from vitalgraph.model.spaces_model import Space
        await client.spaces.create_space(space=Space(
            space=SPACE, space_name="Multi-Value Test Space"
        ))
        logger.info(f"Created space {SPACE}")
    except Exception:
        logger.info(f"Space {SPACE} already exists")

    try:
        await client.graphs.create_graph(space_id=SPACE, graph_uri=GRAPH)
        logger.info(f"Created graph {GRAPH}")
    except Exception:
        logger.info(f"Graph {GRAPH} already exists")

    from kgqueries.case_multi_value_filters import MultiValueFilterTester

    tester = MultiValueFilterTester(client, query_mode=query_mode)

    # Setup test data
    ok = await tester.setup_data(SPACE, GRAPH)
    if not ok:
        print("\n❌ Data setup failed — aborting tests")
        await client.close()
        sys.exit(1)

    # Run tests
    try:
        results = await tester.run_tests(SPACE, GRAPH)
    finally:
        await tester.teardown_data(SPACE, GRAPH)
        await client.close()

    # Summary
    print(f"\n{'=' * 80}")
    print(f"  Final: {results['tests_passed']}/{results['tests_run']} passed, "
          f"{results['tests_failed']} failed")
    print(f"{'=' * 80}")

    if results["tests_failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-value filter integration tests")
    parser.add_argument("--query-mode", default="edge", choices=["edge", "direct"],
                        help="Query mode for entity queries")
    args = parser.parse_args()
    asyncio.run(main(args.query_mode))
