#!/usr/bin/env python3
"""
Setup kgtype_default FTS vector index for framenet_kgtypes_test space.

Uses the VitalGraph REST API endpoints to:
1. Create the kgtype_default vector index (if not exists)
2. Create a vector_mapping for KGType objects
3. Trigger reindex to populate search_text + tsvector from KGType data

This is the correct production-path approach — the API handles:
- Table creation with GENERATED ALWAYS tsv column
- HNSW + GIN index creation
- search_text population from mapped properties
- Vectorization via configured provider

Prerequisites:
  - VitalGraph service running at http://localhost:8001
  - framenet_kgtypes_test space loaded with FrameNet KG types

Usage:
  python test_scripts/data/setup_kgtype_fts_index.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
SPACE_ID = "framenet_kgtypes_test"
INDEX_NAME = "kgtype_default"
GRAPH_URI = "urn:vitalgraph:framenet_kgtypes_test:kg_types"


async def setup_fts_index():
    """Create vector index and trigger reindex via REST API."""
    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        # ── Step 1: Create vector index (if not exists) ─────────────────
        logger.info("Step 1: Creating vector index '%s'...", INDEX_NAME)
        try:
            result = await client.vector_indexes.create_index(
                space_id=SPACE_ID,
                index_name=INDEX_NAME,
                dimensions=384,
                distance_metric="cosine",
                provider="vitalsigns",
                model_name="paraphrase-multilingual-MiniLM-L12-v2",
                description="KGType embeddings for type search (name + description)",
            )
            logger.info("  Created: index_id=%s, dimensions=%d", result.index_id, result.dimensions)
        except Exception as e:
            if "409" in str(e) or "already exists" in str(e).lower():
                logger.info("  Index '%s' already exists (OK)", INDEX_NAME)
            else:
                raise

        # ── Step 2: Create vector mapping for KGTypes ───────────────────
        logger.info("Step 2: Creating vector mapping for kgtype...")
        try:
            mapping_result = await client.search_mappings.create_mapping(
                space_id=SPACE_ID,
                mapping_type="kgtype",
                type_uri=None,  # class-level: all KGType instances
                index_name=INDEX_NAME,
                source_type="default",  # uses hasKGraphDescription
                enabled=True,
            )
            logger.info("  Created mapping: id=%s", mapping_result.mapping_id)
        except Exception as e:
            if "409" in str(e) or "already exists" in str(e).lower():
                logger.info("  Mapping already exists (OK)")
            else:
                logger.warning("  Mapping creation: %s (continuing anyway)", e)

        # ── Step 3: Trigger reindex ─────────────────────────────────────
        logger.info("Step 3: Triggering reindex for graph '%s'...", GRAPH_URI)
        reindex_result = await client.vector_indexes.reindex(
            space_id=SPACE_ID,
            index_name=INDEX_NAME,
            graph_uri=GRAPH_URI,
            mapping_type="kgtype",
        )
        logger.info(
            "  Reindex complete: %d subjects processed, %d embeddings stored",
            reindex_result.subjects_processed,
            reindex_result.embeddings_stored,
        )

        # ── Step 4: Verify via the API ──────────────────────────────────
        logger.info("Step 4: Verifying index status...")
        idx_info = await client.vector_indexes.get_index(SPACE_ID, INDEX_NAME)
        logger.info(
            "  Index '%s': %d embeddings, provider=%s, model=%s",
            idx_info.index_name, idx_info.embedding_count or 0,
            idx_info.provider, idx_info.model_name,
        )

        # ── Step 5: Quick FTS test via SPARQL ───────────────────────────
        logger.info("Step 5: Quick FTS test via search_types...")
        resp = await client.kgtypes.search_types(
            SPACE_ID, GRAPH_URI, query="commerce buying", search_mode="fts"
        )
        logger.info("  FTS 'commerce buying': %d results", resp.count)
        if resp.types:
            names = [t['name'] for t in resp.types[:5]]
            logger.info("  Top results: %s", names)

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(setup_fts_index())
