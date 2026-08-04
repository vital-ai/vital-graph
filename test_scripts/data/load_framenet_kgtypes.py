#!/usr/bin/env python3
"""
Load FrameNet KG Types .vital file into sp_kg_types.

Reads objects from the .vital block file and batch-creates them
via the KG Types REST endpoint, 100 at a time.

Run delete_framenet_kgtypes.py first if you need to clear existing data.

Usage:
  python test_scripts/data/load_framenet_kgtypes.py

  # Specify a custom .vital file
  python test_scripts/data/load_framenet_kgtypes.py --input path/to/file.vital
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
CREATE_BATCH_SIZE = 100
EDGE_CONCURRENCY = 10


def read_nodes_and_edges(vital_path: str):
    """Read all GraphObjects from a .vital block file, separated into nodes and edges."""
    from vital_ai_vitalsigns.block.vital_block_file import VitalBlockFile
    from vital_ai_vitalsigns.block.vital_block_reader import VitalBlockReader
    from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

    nodes = []
    edges = []
    block_file = VitalBlockFile(vital_path)
    reader = VitalBlockReader(block_file)

    for block in reader:
        for obj in block.objects:
            if isinstance(obj, VITAL_Edge):
                edges.append(obj)
            else:
                nodes.append(obj)

    return nodes, edges


async def create_nodes_in_batches(client: VitalGraphClient, nodes: list) -> int:
    """Create KG type nodes in batches via the KG Types endpoint."""
    total_created = 0

    for i in range(0, len(nodes), CREATE_BATCH_SIZE):
        batch = nodes[i:i + CREATE_BATCH_SIZE]

        resp = await client.kgtypes.create_kgtypes(
            space_id=TARGET_SPACE_ID,
            objects=batch,
        )

        if not resp.is_success:
            logger.error("  Batch %d failed: %s", i // CREATE_BATCH_SIZE + 1, resp.message)
            raise RuntimeError(f"Create batch failed at offset {i}: {resp.message}")

        total_created += len(batch)
        logger.info("  Created batch of %d (total: %d / %d)",
                    len(batch), total_created, len(nodes))

    return total_created


async def create_edges(client: VitalGraphClient, edges: list) -> tuple[int, int]:
    """Create edges in parallel via the KG Types relationships endpoint."""
    semaphore = asyncio.Semaphore(EDGE_CONCURRENCY)
    total_created = 0
    total_failed = 0
    lock = asyncio.Lock()

    async def create_one(edge):
        nonlocal total_created, total_failed
        source_uri = str(edge.edgeSource)
        target_uri = str(edge.edgeDestination)
        edge_type = f"http://vital.ai/ontology/haley-ai-kg#{type(edge).__name__}"

        async with semaphore:
            resp = await client.kgtypes.create_type_relationship(
                space_id=TARGET_SPACE_ID,
                type_uri=source_uri,
                edge_type=edge_type,
                target_uri=target_uri,
            )

        async with lock:
            if resp.is_success:
                total_created += 1
            else:
                total_failed += 1
                if total_failed <= 5:
                    logger.error("  FAILED: %s -[%s]-> %s : %s",
                                 source_uri, type(edge).__name__, target_uri, resp.message)
                elif total_failed == 6:
                    logger.error("  ... suppressing further error details")

            done = total_created + total_failed
            if done % 100 == 0:
                logger.info("  Progress: %d / %d (created: %d, failed: %d)",
                            done, len(edges), total_created, total_failed)

    await asyncio.gather(*[create_one(edge) for edge in edges])
    return total_created, total_failed


async def main():
    parser = argparse.ArgumentParser(
        description="Load FrameNet KG Types .vital file into sp_kg_types via batch create"
    )
    parser.add_argument("--input", "-i", type=str, default=DEFAULT_VITAL_FILE,
                        help=f"Input .vital file path (default: {DEFAULT_VITAL_FILE})")
    args = parser.parse_args()

    vital_path = Path(args.input)
    if not vital_path.exists():
        print(f"Error: .vital file not found: {vital_path}")
        sys.exit(1)

    print("=" * 70)
    print("Load FrameNet KG Types → sp_kg_types")
    print("=" * 70)
    print(f"  Space: {TARGET_SPACE_ID}")
    print(f"  Source: {vital_path}")
    print(f"  Batch size (nodes): {CREATE_BATCH_SIZE}")
    print()

    print("Reading objects from .vital file...")
    nodes, edges = read_nodes_and_edges(str(vital_path))
    print(f"  Found {len(nodes)} nodes and {len(edges)} edges")
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    try:
        # Pass 1: Create nodes (KGFrameType, KGSlotType) in batches
        print("Pass 1: Creating nodes...")
        node_count = await create_nodes_in_batches(client, nodes)
        print(f"  ✓ Created {node_count} nodes")
        print()

        # Pass 2: Create edges in parallel
        print("Pass 2: Creating edges...")
        edges_created, edges_failed = await create_edges(client, edges)
        print(f"  ✓ Created {edges_created} edges")
        if edges_failed:
            print(f"  ✗ Failed {edges_failed} edges")
    finally:
        await client.close()

    print()
    print(f"✅ Loaded {node_count + edges_created} objects into {TARGET_SPACE_ID}")
    if edges_failed:
        print(f"⚠️  {edges_failed} edges failed — check logs above")


if __name__ == "__main__":
    asyncio.run(main())
