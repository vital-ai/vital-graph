#!/usr/bin/env python3
"""
Step 5: Delete Space & Registry Data (Cleanup / Reset)

Deletes the semantic search test space and cleans up global entity registry
and agent registry data created by step_03. Use this to clean up after
testing or to reset the environment before re-running the setup steps.
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
    TEST_SPACE_ID, ER_ENTITY_TYPE_KEY, ER_AGENT_URI,
)


async def main():
    print("\n" + "=" * 70)
    print("  Step 5: Delete Space & Registry Data (Cleanup)")
    print("=" * 70)

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("Failed to connect to VitalGraph server")
        return False
    logger.info("Connected to VitalGraph server\n")

    try:
        resp = await client.spaces.list_spaces()
        existing_ids = [s.space for s in resp.spaces] if resp.is_success else []

        if TEST_SPACE_ID not in existing_ids:
            logger.info(f"  Space '{TEST_SPACE_ID}' does not exist — skipping space deletion.")
        else:
            logger.info(f"  Deleting space '{TEST_SPACE_ID}'...")
            del_resp = await client.spaces.delete_space(TEST_SPACE_ID)
            if del_resp.is_success:
                logger.info(f"  Space '{TEST_SPACE_ID}' deleted successfully.")
            else:
                logger.error(f"  Failed to delete space: {del_resp.error_message}")

        # ---------------------------------------------------------------
        # Clean up Entity Registry data (global tables)
        # ---------------------------------------------------------------
        print("\n  --- Entity Registry Cleanup ---")
        reg = client.entity_registry

        # Find and delete entities created by this test (search by type)
        try:
            search_resp = await reg.search_entities(
                type_key=ER_ENTITY_TYPE_KEY, page_size=100)
            if search_resp.success and search_resp.entities:
                for ent in search_resp.entities:
                    try:
                        await reg.delete_entity(ent.entity_id)
                        logger.info(f"  Deleted entity: {ent.primary_name} ({ent.entity_id})")
                    except Exception as e:
                        logger.warning(f"  Failed to delete entity {ent.entity_id}: {e}")
            else:
                logger.info(f"  No entity registry entities with type '{ER_ENTITY_TYPE_KEY}' found")
        except Exception as e:
            logger.warning(f"  Entity registry cleanup error: {e}")

        # ---------------------------------------------------------------
        # Clean up Agent Registry data (global tables)
        # ---------------------------------------------------------------
        print("\n  --- Agent Registry Cleanup ---")
        ar = client.agent_registry

        try:
            agent_resp = await ar.get_agent_by_uri(ER_AGENT_URI)
            if agent_resp.agents:
                agent = agent_resp.agents[0]
                await ar.delete_agent(agent.agent_id)
                logger.info(f"  Deleted agent: {agent.agent_name} ({agent.agent_id})")
            else:
                logger.info(f"  Agent '{ER_AGENT_URI}' not found — nothing to delete")
        except Exception as e:
            logger.warning(f"  Agent registry cleanup error: {e}")

        print("\n  Step 5 complete.")
        return True

    finally:
        await client.close()
        logger.info("  Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
