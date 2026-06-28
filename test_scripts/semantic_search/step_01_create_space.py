#!/usr/bin/env python3
"""
Step 1: Create Space & Graph

Creates the test space and graph used by all subsequent semantic search test steps.
If the space already exists it is deleted and recreated so the test starts clean.
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path & env setup
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent.parent
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
from vitalgraph.model.spaces_model import Space

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID,
    TEST_SPACE_NAME,
    TEST_GRAPH_ID,
)


async def main():
    print("\n" + "=" * 70)
    print("  Step 1: Create Space & Graph")
    print("=" * 70)

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("Failed to connect to VitalGraph server")
        return False
    logger.info("Connected to VitalGraph server\n")

    try:
        # Delete pre-existing space if present
        resp = await client.spaces.list_spaces()
        existing_ids = [s.space for s in resp.spaces] if resp.is_success else []
        if TEST_SPACE_ID in existing_ids:
            logger.info(f"  Deleting pre-existing space '{TEST_SPACE_ID}'...")
            await client.spaces.delete_space(TEST_SPACE_ID)
            logger.info(f"  Deleted.")

        # Create space
        space = Space(
            space=TEST_SPACE_ID,
            space_name=TEST_SPACE_NAME,
            space_description="Dedicated space for semantic search UI testing",
        )
        cr = await client.spaces.create_space(space)
        if not cr.is_success:
            logger.error(f"Failed to create space: {cr.error_message}")
            return False
        logger.info(f"  Space '{TEST_SPACE_ID}' created")

        # Create graph
        await client.graphs.create_graph(TEST_SPACE_ID, TEST_GRAPH_ID)
        logger.info(f"  Graph '{TEST_GRAPH_ID}' created")

        print("\n  Step 1 complete.")
        return True

    finally:
        await client.close()
        logger.info("  Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
