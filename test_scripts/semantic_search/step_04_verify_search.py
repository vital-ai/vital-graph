#!/usr/bin/env python3
"""
Step 4: Verify Search — Comprehensive Search Tests

Thin runner that delegates to individual verify modules in the verify/ subfolder.

Coverage matrix:
  Data Types:     KG Entity, KG Type, KG Document, KG Frame,
                  Entity Registry, Agent Registry
  Search Modes:   Vector, FTS, Hybrid, Fuzzy, Keyword, Geo

Run after step_03_insert_data.py and before step_05_delete_space.py.
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

from test_scripts.semantic_search.config import TEST_SPACE_ID, TEST_GRAPH_ID
from test_scripts.semantic_search.verify import SearchVerifier

from test_scripts.semantic_search.verify.verify_keyword import test_kgentities_list
from test_scripts.semantic_search.verify.verify_vector import test_vector_search
from test_scripts.semantic_search.verify.verify_fts import test_fts_search
from test_scripts.semantic_search.verify.verify_hybrid import test_hybrid_search
from test_scripts.semantic_search.verify.verify_fuzzy import test_fuzzy_search
from test_scripts.semantic_search.verify.verify_geo import test_geo_search
from test_scripts.semantic_search.verify.verify_kg_types import (
    test_kg_types, test_kg_frames_documents,
)
from test_scripts.semantic_search.verify.verify_entity_registry import (
    test_entity_registry_search,
)
from test_scripts.semantic_search.verify.verify_agent_registry import (
    test_agent_registry_search,
)
from test_scripts.semantic_search.verify.verify_kgdocuments import (
    test_kgdocuments, test_kgdocument_segmentation, test_kgdocument_vector_search,
)


# ===========================================================================
# Main
# ===========================================================================

async def main():
    print("\n" + "=" * 70)
    print("  Step 4: Verify Search — Comprehensive Coverage")
    print("=" * 70)
    print(f"  Space:  {TEST_SPACE_ID}")
    print(f"  Graph:  {TEST_GRAPH_ID}")

    client = VitalGraphClient()
    await client.open()
    if not client.is_connected():
        logger.error("Failed to connect to VitalGraph server")
        return False
    logger.info("Connected to VitalGraph server")

    try:
        v = SearchVerifier(client)

        # KG Entity tests
        await test_kgentities_list(v)
        await test_vector_search(v)
        await test_fts_search(v)
        await test_hybrid_search(v)
        await test_fuzzy_search(v)
        await test_geo_search(v)

        # KG Type / Frame / Document tests
        await test_kg_types(v)
        await test_kg_frames_documents(v)

        # KG Document tests
        await test_kgdocuments(v)
        await test_kgdocument_segmentation(v)
        await test_kgdocument_vector_search(v)

        # Registry tests
        await test_entity_registry_search(v)
        await test_agent_registry_search(v)

        # Summary
        total = v.passed + v.failed
        print(f"\n{'=' * 70}")
        if v.failed == 0:
            print(f"  ✅ ALL PASSED: {v.passed}/{total} tests")
        else:
            print(f"  ⚠️  {v.passed}/{total} passed, {v.failed} FAILED")
            for err in v.errors:
                print(f"     ❌ {err}")
        print(f"{'=' * 70}")

        print("\n  Step 4 complete.")
        return v.failed == 0

    finally:
        await client.close()
        logger.info("  Client closed")


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
