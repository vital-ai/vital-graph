#!/usr/bin/env python3
"""
Migrate FrameNet KG Types from framenet_kgtypes_test → sp_kg_types.

1. Imports generated_instances/framenet_kgtypes.vital into sp_kg_types
2. Deletes the framenet_kgtypes_test space

Usage:
  python test_scripts/data/migrate_framenet_to_sp_kg_types.py
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
OLD_SPACE_ID = "framenet_kgtypes_test"
TARGET_SPACE_ID = "sp_kg_types"
TARGET_GRAPH_ID = "urn:vitalgraph:sp_kg_types:kg_types"
VITAL_FILE = "generated_instances/framenet_kgtypes.vital"


async def import_to_sp_kg_types(client: VitalGraphClient):
    """Import the FrameNet .vital file into sp_kg_types."""
    from vitalgraph.model.import_model import ImportJobCreate, ImportMode, FileFormat

    vital_path = Path(VITAL_FILE)
    if not vital_path.exists():
        raise FileNotFoundError(f"FrameNet data file not found: {VITAL_FILE}")

    print(f"Step 1: Importing {vital_path.name} ({vital_path.stat().st_size / 1024:.0f} KB) into {TARGET_SPACE_ID}...")

    job_create = ImportJobCreate(
        space_id=TARGET_SPACE_ID,
        graph_uri=TARGET_GRAPH_ID,
        file_format=FileFormat.VITAL,
        mode=ImportMode.APPEND,
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


async def delete_old_space(client: VitalGraphClient):
    """Delete the framenet_kgtypes_test space."""
    print(f"Step 2: Deleting old space '{OLD_SPACE_ID}'...")
    try:
        resp = await client.spaces.delete_space(OLD_SPACE_ID)
        logger.info("  Deleted space '%s': %s", OLD_SPACE_ID, getattr(resp, 'message', resp))
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            logger.info("  Space '%s' not found (already deleted)", OLD_SPACE_ID)
        else:
            raise


async def main():
    print("=" * 70)
    print("Migrate FrameNet KG Types → sp_kg_types")
    print("=" * 70)
    print(f"  Source file: {VITAL_FILE}")
    print(f"  Target:      {TARGET_SPACE_ID} / {TARGET_GRAPH_ID}")
    print(f"  Delete:      {OLD_SPACE_ID}")
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        await import_to_sp_kg_types(client)
        await delete_old_space(client)
    finally:
        await client.close()

    print()
    print("✅ Migration complete")
    print(f"   FrameNet data is now in {TARGET_SPACE_ID}")
    print(f"   Old space {OLD_SPACE_ID} has been deleted")


if __name__ == "__main__":
    asyncio.run(main())
