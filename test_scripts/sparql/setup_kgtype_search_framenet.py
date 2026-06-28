#!/usr/bin/env python3
"""
Setup script for FrameNet KGType search tests.

Creates the space, imports data, creates search infrastructure (shared
search mapping, vector index, FTS index), and triggers async population.
Polls until both indexes are ready.

Usage:
  python test_scripts/sparql/setup_kgtype_search_framenet.py
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
SPACE_ID = "framenet_kgtypes_test"
GRAPH_ID = "urn:vitalgraph:framenet_kgtypes_test:kg_types"
INDEX_NAME = "kgtype_default"
VITAL_FILE = "generated_instances/framenet_kgtypes.vital"


async def _ensure_idempotent(coro, label: str, *, ignore_errors: bool = False):
    """Run an async call, swallowing 409/already-exists errors."""
    try:
        result = await coro
        logger.info("  Created %s", label)
        return result
    except Exception as e:
        msg = str(e).lower()
        if "409" in str(e) or "already exists" in msg or "duplicate" in msg:
            logger.info("  %s already exists (skipped)", label)
            return None
        if ignore_errors:
            logger.warning("  %s: %s (continuing)", label, e)
            return None
        raise


async def create_space(client: VitalGraphClient):
    """Delete and recreate the space, then import FrameNet data."""
    from vitalgraph.model.spaces_model import Space
    from vitalgraph.model.import_model import ImportJobCreate, ImportMode, FileFormat

    # Delete existing space
    print("Step 1: Deleting existing space...")
    try:
        resp = await client.spaces.delete_space(SPACE_ID)
        logger.info("  Deleted space '%s': %s", SPACE_ID, getattr(resp, 'message', resp))
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            logger.info("  Space '%s' not found (clean start)", SPACE_ID)
        else:
            raise

    # Create fresh space
    print("Step 2: Creating fresh space...")
    space = Space(
        space=SPACE_ID,
        space_name="FrameNet KGTypes Test",
        space_description="Test space for FrameNet-based KG type search validation",
    )
    await client.spaces.create_space(space)
    logger.info("  Created space '%s'", SPACE_ID)

    # Import FrameNet data
    vital_path = Path(VITAL_FILE)
    if not vital_path.exists():
        raise FileNotFoundError(f"FrameNet data file not found: {VITAL_FILE}")

    print(f"Step 3: Importing {vital_path.name} ({vital_path.stat().st_size / 1024:.0f} KB)...")
    job_create = ImportJobCreate(
        space_id=SPACE_ID,
        graph_uri=GRAPH_ID,
        file_format=FileFormat.VITAL,
        mode=ImportMode.REPLACE,
    )
    create_resp = await client.imports.create_import_job(job_create)
    job_id = create_resp.job.job_id
    logger.info("  Import job created: %s", job_id)

    await client.imports.upload_import_file(job_id, str(vital_path))
    logger.info("  File uploaded")

    await client.imports.execute_import_job(job_id)
    logger.info("  Import execution started")

    for _ in range(120):
        status_resp = await client.imports.get_import_status(job_id)
        status_str = str(status_resp.status).lower()
        if 'completed' in status_str or 'done' in status_str:
            logger.info("  Import completed: %s records", status_resp.records_done)
            break
        if 'failed' in status_str or 'error' in status_str:
            raise RuntimeError(f"Import failed: {status_resp.error_message}")
        await asyncio.sleep(1)
    else:
        raise RuntimeError("Import timed out after 120s")


async def create_indexes(client: VitalGraphClient):
    """Create search mappings (base + type-specific), vector index, and FTS index."""
    print("Step 4: Creating search infrastructure...")

    # ── Search mappings ─────────────────────────────────────────────────
    # Base mapping: hasName + hasKGraphDescription (covers KGType, KGRelationType, KGSlotRoleType)
    await _create_mapping_with_properties(
        client,
        type_uri=None,
        properties=[
            ("http://vital.ai/ontology/vital-core#hasName", 1),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", 2),
        ],
        label="base (all KGTypes)",
    )

    # KGEntityType: + entity-specific description
    await _create_mapping_with_properties(
        client,
        type_uri="http://vital.ai/ontology/haley-ai-kg#KGEntityType",
        properties=[
            ("http://vital.ai/ontology/vital-core#hasName", 1),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", 2),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription", 3),
        ],
        label="KGEntityType",
    )

    # KGFrameType: + frame-specific description
    await _create_mapping_with_properties(
        client,
        type_uri="http://vital.ai/ontology/haley-ai-kg#KGFrameType",
        properties=[
            ("http://vital.ai/ontology/vital-core#hasName", 1),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", 2),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription", 3),
        ],
        label="KGFrameType",
    )

    # KGSlotType: + slot name + label
    await _create_mapping_with_properties(
        client,
        type_uri="http://vital.ai/ontology/haley-ai-kg#KGSlotType",
        properties=[
            ("http://vital.ai/ontology/vital-core#hasName", 1),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeName", 2),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeLabel", 3),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription", 4),
        ],
        label="KGSlotType",
    )

    # ── Vector index ────────────────────────────────────────────────────
    await _ensure_idempotent(
        client.vector_indexes.create_index(
            space_id=SPACE_ID,
            index_name=INDEX_NAME,
            dimensions=384,
            distance_metric="cosine",
            provider="vitalsigns",
            model_name="paraphrase-multilingual-MiniLM-L12-v2",
            description="KGType embeddings for type search",
        ),
        f"vector index '{INDEX_NAME}'",
    )

    # ── FTS index ───────────────────────────────────────────────────────
    await _ensure_idempotent(
        client.fts_indexes.create_index(
            space_id=SPACE_ID,
            index_name=INDEX_NAME,
            languages=["english"],
        ),
        f"FTS index '{INDEX_NAME}'",
    )


async def _create_mapping_with_properties(
    client: VitalGraphClient,
    type_uri,
    properties: list,
    label: str,
):
    """Create a search mapping with source_type='properties' and add property URIs."""
    result = await _ensure_idempotent(
        client.search_mappings.create_mapping(
            space_id=SPACE_ID,
            index_name=INDEX_NAME,
            mapping_type="kgtype",
            type_uri=type_uri,
            source_type="properties",
            enabled=True,
            separator=". ",
            include_pred_name=False,
            include_type_desc=False,
        ),
        f"search mapping ({label})",
        ignore_errors=True,
    )
    if result is None:
        # Already exists — skip adding properties
        return
    mapping_id = result.mapping_id
    for prop_uri, ordinal in properties:
        await client.search_mappings.add_property(
            space_id=SPACE_ID,
            mapping_id=mapping_id,
            property_uri=prop_uri,
            ordinal=ordinal,
        )
    logger.info("  Added %d properties to mapping %d (%s)", len(properties), mapping_id, label)


async def populate_indexes(client: VitalGraphClient):
    """Trigger async vector + FTS population and poll until ready."""
    print("Step 5: Populating indexes...")

    # Check current state
    idx_info = await client.vector_indexes.get_index(SPACE_ID, INDEX_NAME)
    vec_ready = idx_info.embedding_count and idx_info.embedding_count > 0

    try:
        fts_stats = await client.fts_indexes.get_stats(SPACE_ID, INDEX_NAME)
        fts_count = getattr(fts_stats, 'total_rows', 0) or getattr(fts_stats, 'row_count', 0) or 0
    except Exception:
        fts_count = 0
    fts_ready = fts_count > 0

    if vec_ready and fts_ready:
        logger.info("  Indexes already populated (vec=%d, fts=%d)",
                     idx_info.embedding_count, fts_count)
        return

    # Fire off async population
    if not vec_ready:
        logger.info("  Triggering vector reindex (async)...")
        result = await client.vector_indexes.reindex(
            space_id=SPACE_ID, index_name=INDEX_NAME,
            graph_uri=GRAPH_ID, mapping_type="kgtype",
        )
        logger.info("  Server: %s", result.message)

    if not fts_ready:
        logger.info("  Triggering FTS populate (async)...")
        fts_result = await client.fts_indexes.populate(
            space_id=SPACE_ID, index_name=INDEX_NAME,
            graph_uri=GRAPH_ID, mapping_type="kgtype",
        )
        logger.info("  Server: %s", fts_result.message)

    # Poll until counts stabilize (stop changing for 2 consecutive polls)
    print("Step 6: Waiting for indexes to be populated...")
    t0 = time.time()
    poll_interval = 5
    timeout = 600
    prev_vec = -1
    prev_fts = -1
    stable_count = 0
    while time.time() - t0 < timeout:
        vec_count = 0
        fts_count = 0

        try:
            idx = await client.vector_indexes.get_index(SPACE_ID, INDEX_NAME)
            vec_count = idx.embedding_count or 0
        except Exception:
            pass

        try:
            stats = await client.fts_indexes.get_stats(SPACE_ID, INDEX_NAME)
            fts_count = getattr(stats, 'total_rows', 0) or getattr(stats, 'row_count', 0) or 0
        except Exception:
            pass

        elapsed = time.time() - t0

        if vec_count > 0 and fts_count > 0:
            if vec_count == prev_vec and fts_count == prev_fts:
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= 2:
                logger.info("  Indexes ready: vec=%d, fts=%d (%.0fs)", vec_count, fts_count, elapsed)
                return

        prev_vec = vec_count
        prev_fts = fts_count
        logger.info("  Waiting... vec=%d, fts=%d (%.0fs)", vec_count, fts_count, elapsed)
        await asyncio.sleep(poll_interval)

    raise RuntimeError(f"Indexes not populated after {timeout}s — check server logs")


async def main():
    print("=" * 70)
    print("FrameNet KGType Search — Setup")
    print("=" * 70)
    print(f"  Space: {SPACE_ID}")
    print(f"  Graph: {GRAPH_ID}")
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        await create_space(client)
        await create_indexes(client)
        await populate_indexes(client)
    finally:
        await client.close()

    print()
    print("✅ Setup complete — ready to run tests:")
    print(f"   python test_scripts/sparql/test_kgtype_search_framenet.py")


if __name__ == "__main__":
    asyncio.run(main())
