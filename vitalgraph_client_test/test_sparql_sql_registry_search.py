#!/usr/bin/env python3
"""
SPARQL-SQL Backend — Registry Search Verification Test

Verifies that loaded entity registry and agent registry data is correctly
searchable via the REST API search endpoints. Uses pgvector semantic search,
PostGIS geo search, and BM25 full-text search.

Prerequisite: Entity registry data must be loaded and vector-rebuild must
have been run so that the vector/FTS/geo tables are populated.

This script is designed to run AFTER data loading scripts and BEFORE
the delete/cleanup step in the test sequence.

Usage:
    python vitalgraph_client_test/test_sparql_sql_registry_search.py
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path & env setup
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

# ---------------------------------------------------------------------------
# Imports (after path setup)
# ---------------------------------------------------------------------------
from vitalgraph.client.vitalgraph_client import VitalGraphClient
from vitalgraph_client_test.sparql_sql.case_registry_search_verify import RegistrySearchVerifyTester


# ===========================================================================
# Configuration
# ===========================================================================
MANIFEST_PATH = Path(__file__).parent / "test_data_manifest.json"


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  SPARQL-SQL Backend — Registry Search Verification")
    print("=" * 80)
    print("  Tests: Entity semantic/geo/combined/identifier search,")
    print("         Location geo/semantic/address search,")
    print("         Agent registry search")
    print("=" * 80)

    # Load manifest if available (optional — enables entity-specific assertions)
    entity_ids = None
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text())
        entity_ids = manifest.get("entities")
        logger.info(f"\n  Loaded manifest with {len(entity_ids)} entity IDs")
    else:
        logger.info("\n  No test_data_manifest.json found — running generic tests")

    # Connect
    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("❌ Failed to connect to VitalGraph server")
        return False
    logger.info("  ✅ Connected to VitalGraph server\n")

    t0 = time.time()

    try:
        # Run registry search verification tests
        tester = RegistrySearchVerifyTester(client)
        results = await tester.run_tests(entity_ids=entity_ids)

        elapsed = time.time() - t0
        passed = results["tests_passed"]
        total = results["tests_run"]
        failed = results["tests_failed"]

        print("\n" + "=" * 80)
        status = "✅ ALL PASSED" if failed == 0 else "⚠️  SOME FAILED"
        print(f"  {status}: {passed}/{total} tests passed")
        print("=" * 80)

        if results["errors"]:
            for e in results["errors"]:
                print(f"  ❌ {e}")

        print(f"\n⏱️  Total elapsed: {elapsed:.2f}s")

        return failed == 0

    finally:
        await client.close()
        logger.info("  ✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
