#!/usr/bin/env python3
"""
SPARQL WordNet Query Test Script

Tests SPARQL queries against the WordNet KGFrame dataset loaded into the
sparql_sql backend. Uses the same query patterns as happy_words.py but
exercised through the VitalGraph REST API via VitalGraphClient.

Test cases:
  sparql/case_wordnet_basic_queries.py        — triple counts, type counts, entity lookup
  sparql/case_wordnet_relationship_queries.py  — happy words relationship traversal
  sparql/case_wordnet_frame_queries.py         — UNION frame queries, ASK, frame types

Prerequisites:
  1. vitalgraphadmin -c init
  2. vitalgraphadmin -c create-space -s wordnet_frames
  3. vitalgraphadmin -c import -s wordnet_frames -f <path>/kgframe-wordnet-0.0.1.nt -g urn:wordnet_frames --yes
  4. Populate stats: rdf_pred_stats, rdf_stats, edge_mv (via SQL or admin CLI)
  5. docker compose up  (server running on localhost:8001)

Usage:
    python vitalgraph_client_test/test_sparql_wordnet.py
"""

import sys
import asyncio
import logging
from pathlib import Path

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

# Test configuration
SPACE_ID = "wordnet_frames"
GRAPH_URI = "urn:wordnet_frames"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> int:
    """Run all WordNet SPARQL query tests."""

    print("🧪 VitalGraph SPARQL WordNet Query Test Suite")
    print(f"   Space: {SPACE_ID}")
    print(f"   Graph: {GRAPH_URI}")
    print("=" * 60)

    # Connect
    print("\n🔐 Connecting to VitalGraph server...")
    client = VitalGraphClient()
    try:
        await client.open()
        print("   ✅ Connected")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        return 1

    try:
        # Import test case classes — exact queries from happy_words.py
        from sparql.case_wordnet_basic_queries import WordNetBasicQueryTester
        from sparql.case_wordnet_relationship_queries import WordNetHappyWordsTester

        suites = [
            ("Basic Queries", WordNetBasicQueryTester(client)),
            ("Happy Words Queries", WordNetHappyWordsTester(client)),
        ]

        all_results = []

        for suite_name, tester in suites:
            print(f"\n{'='*60}")
            print(f"  {suite_name}")
            print(f"{'='*60}")
            result = await tester.run_tests(SPACE_ID)
            all_results.append(result)

        # Summary
        total_run = sum(r["tests_run"] for r in all_results)
        total_passed = sum(r["tests_passed"] for r in all_results)
        total_failed = sum(r["tests_failed"] for r in all_results)

        print(f"\n{'='*60}")
        print("📊 TEST SUMMARY")
        print(f"{'='*60}")

        for r in all_results:
            status = "✅" if r["tests_failed"] == 0 else "❌"
            print(f"  {status} {r['test_name']}: {r['tests_passed']}/{r['tests_run']} passed")
            if r["errors"]:
                for err in r["errors"]:
                    print(f"     ⚠️  {err}")

        print(f"\nOverall: {total_passed}/{total_run} tests passed")

        if total_failed == 0:
            print("🎉 All WordNet SPARQL query tests passed!")
            return 0
        else:
            print(f"⚠️  {total_failed} test(s) failed")
            return 1

    finally:
        await client.close()
        print("\n✅ Client closed")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
