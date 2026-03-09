#!/usr/bin/env python3
"""
SPARQL-SQL Backend Agent Registry Test

Standalone runner for Agent Registry CRUD test case against the sparql_sql backend.
Does NOT require a space or graph — agent registry tables are global admin tables.
"""

import asyncio
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
from vitalgraph_client_test.sparql_sql.case_agent_registry_crud import AgentRegistryCrudTester


# ===========================================================================
# Main
# ===========================================================================
async def main():
    print("\n" + "=" * 80)
    print("  SPARQL-SQL Backend — Agent Registry CRUD Test")
    print("=" * 80)

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("❌ Failed to connect to VitalGraph server")
        return False
    logger.info("\n✅ Connected to VitalGraph server\n")

    t0 = time.time()

    try:
        # Run Agent Registry CRUD tests
        tester = AgentRegistryCrudTester(client)
        results = await tester.run_tests()

        elapsed = time.time() - t0
        passed = results["tests_passed"]
        total = results["tests_run"]

        print("\n" + "=" * 80)
        print(f"  RESULTS: {passed}/{total} passed")
        print("=" * 80)
        if results["errors"]:
            for e in results["errors"]:
                print(f"  ❌ {e}")
        print(f"\n⏱️  Total elapsed: {elapsed:.2f}s")

        return results["tests_failed"] == 0

    finally:
        await client.close()
        logger.info(f"  ✅ Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
