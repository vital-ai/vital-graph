#!/usr/bin/env python3
"""
Delete FrameNet KG Types from sp_kg_types.

Reads URIs from the existing .vital block file and batch-deletes them
via the KG Types REST endpoint, 100 at a time.

Usage:
  python test_scripts/data/delete_framenet_kgtypes.py

  # Specify a custom .vital file
  python test_scripts/data/delete_framenet_kgtypes.py --input path/to/file.vital
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
TARGET_SPACE_ID = "sp_kg_types"
DEFAULT_VITAL_FILE = "generated_instances/framenet_kgtypes.vital"
DELETE_BATCH_SIZE = 100


def read_uris_from_vital_file(vital_path: str) -> list[str]:
    """Read all object URIs from a .vital block file."""
    from vital_ai_vitalsigns.block.vital_block_file import VitalBlockFile
    from vital_ai_vitalsigns.block.vital_block_reader import VitalBlockReader

    uris = []
    block_file = VitalBlockFile(vital_path)
    reader = VitalBlockReader(block_file)

    for block in reader:
        for obj in block.objects:
            uri = str(obj.URI) if hasattr(obj, 'URI') else None
            if uri:
                uris.append(uri)

    return uris


async def delete_kgtypes_by_uris(client: VitalGraphClient, uris: list[str]) -> int:
    """Delete KG types in batches via the KG Types endpoint."""
    total_deleted = 0

    for i in range(0, len(uris), DELETE_BATCH_SIZE):
        batch = uris[i:i + DELETE_BATCH_SIZE]
        uri_list = ','.join(batch)

        del_resp = await client.kgtypes.delete_kgtypes_batch(
            space_id=TARGET_SPACE_ID,
            uri_list=uri_list,
        )

        total_deleted += len(batch)
        logger.info("  Deleted batch of %d (total: %d / %d)",
                     len(batch), total_deleted, len(uris))

    return total_deleted


async def main():
    parser = argparse.ArgumentParser(
        description="Delete FrameNet KG Types from sp_kg_types using URIs from .vital file"
    )
    parser.add_argument("--input", "-i", type=str, default=DEFAULT_VITAL_FILE,
                        help=f"Input .vital file to read URIs from (default: {DEFAULT_VITAL_FILE})")
    args = parser.parse_args()

    vital_path = Path(args.input)
    if not vital_path.exists():
        print(f"Error: .vital file not found: {vital_path}")
        sys.exit(1)

    print("=" * 70)
    print("Delete FrameNet KG Types from sp_kg_types")
    print("=" * 70)
    print(f"  Space: {TARGET_SPACE_ID}")
    print(f"  Source: {vital_path}")
    print(f"  Batch size: {DELETE_BATCH_SIZE}")
    print()

    print("Reading URIs from .vital file...")
    uris = read_uris_from_vital_file(str(vital_path))
    print(f"  Found {len(uris)} URIs to delete")
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        total = await delete_kgtypes_by_uris(client, uris)
    finally:
        await client.close()

    print()
    print(f"✅ Deleted {total} objects from {TARGET_SPACE_ID}")


if __name__ == "__main__":
    asyncio.run(main())
