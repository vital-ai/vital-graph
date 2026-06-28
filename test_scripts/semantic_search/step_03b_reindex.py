#!/usr/bin/env python3
"""
Step 3b: Reindex / Populate Search Indexes

Triggers vector reindex, FTS populate, and fuzzy repopulate for
the semantic search test space.  Run after step_03 (data insertion).
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

from test_scripts.semantic_search.config import (
    TEST_SPACE_ID, TEST_GRAPH_ID,
    VECTOR_INDEX_NAME, FTS_INDEX_NAME,
)


async def main() -> bool:
    print("\n" + "=" * 70)
    print("  Step 3b: Reindex / Populate Search Indexes")
    print("=" * 70)

    client = VitalGraphClient()
    await client.open()
    logger.info("Connected to VitalGraph server\n")

    try:
        # --- Vector index reindex ---
        print("  --- Vector Index ---")
        try:
            vi_resp = await client.vector_indexes.reindex(
                space_id=TEST_SPACE_ID,
                index_name=VECTOR_INDEX_NAME,
                graph_uri=TEST_GRAPH_ID,
                mapping_type="kgentity",
            )
            logger.info(f"  Vector reindex: {vi_resp}")
        except Exception as e:
            logger.warning(f"  Vector reindex failed: {e}")

        # --- FTS index populate ---
        print("  --- FTS Index ---")
        try:
            fts_resp = await client.fts_indexes.populate(
                space_id=TEST_SPACE_ID,
                index_name=FTS_INDEX_NAME,
                graph_uri=TEST_GRAPH_ID,
                mapping_type="kgentity",
            )
            logger.info(f"  FTS populate: {fts_resp}")
        except Exception as e:
            logger.warning(f"  FTS populate failed: {e}")

        # --- Fuzzy mapping repopulate ---
        print("  --- Fuzzy Mapping ---")
        try:
            fm_resp = await client.fuzzy_mappings.list_mappings(space_id=TEST_SPACE_ID)
            mappings = fm_resp.mappings if hasattr(fm_resp, 'mappings') else []
            if mappings:
                fm_id = mappings[0].mapping_id
                await client.fuzzy_mappings.populate(
                    space_id=TEST_SPACE_ID, mapping_id=fm_id)
                logger.info(f"  Fuzzy repopulate: mapping_id={fm_id}")
            else:
                logger.info("  No fuzzy mappings found, skipping")
        except Exception as e:
            logger.warning(f"  Fuzzy repopulate failed: {e}")

        print("\n  Step 3b complete.")
        return True

    finally:
        await client.close()
        logger.info("  Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
