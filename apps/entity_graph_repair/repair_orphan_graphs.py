#!/usr/bin/env python3
"""Diagnose and repair orphaned KG entity graphs.

When a top-level KGEntity node is deleted without properly cleaning up
its entity graph, the child objects (frames, slots, edges, documents)
become orphans.  This tool can scan for, inspect, and delete such orphans.

Usage:
    # Scan for orphan graphs in a space:
    python -m apps.entity_graph_repair.repair_orphan_graphs scan --space my_space

    # Inspect a specific entity graph:
    python -m apps.entity_graph_repair.repair_orphan_graphs inspect \\
        --space my_space --entity-uri urn:my_entity

    # Delete an orphan graph (dry run by default):
    python -m apps.entity_graph_repair.repair_orphan_graphs delete \\
        --space my_space --entity-uri urn:my_entity

    # Delete for real:
    python -m apps.entity_graph_repair.repair_orphan_graphs delete \\
        --space my_space --entity-uri urn:my_entity --no-dry-run

    # Delete ALL orphan graphs in a space (dry run):
    python -m apps.entity_graph_repair.repair_orphan_graphs delete-all-orphans \\
        --space my_space
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

from .orphan_scanner import (
    inspect_entity_graph,
    print_inspect_result,
    scan_orphan_graphs,
)
from .orphan_deleter import (
    delete_orphan_graph,
    print_delete_result,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

async def cmd_scan(args: argparse.Namespace) -> None:
    """Scan for orphaned entity graphs."""
    client = VitalGraphClient()
    try:
        await client.open()
        print(f"Connected to VitalGraph")
        print(f"Scanning space: {args.space}\n")

        orphans = await scan_orphan_graphs(client, args.space)

        if not orphans:
            print("No orphaned entity graphs found.")
            return

        for orphan in orphans:
            print(f"  {orphan}")

        total_objects = sum(o.object_count for o in orphans)
        print(f"\nFound {len(orphans)} orphan entity graphs "
              f"({total_objects} total orphaned objects)")

    finally:
        await client.close()


async def cmd_inspect(args: argparse.Namespace) -> None:
    """Inspect a specific entity graph."""
    client = VitalGraphClient()
    try:
        await client.open()
        print(f"Connected to VitalGraph\n")

        result = await inspect_entity_graph(client, args.space, args.entity_uri)
        print_inspect_result(result)

    finally:
        await client.close()


async def cmd_delete(args: argparse.Namespace) -> None:
    """Delete an orphaned entity graph."""
    client = VitalGraphClient()
    try:
        await client.open()
        print(f"Connected to VitalGraph")
        print(f"Space: {args.space}")
        print(f"Entity URI: {args.entity_uri}")
        print(f"Dry run: {args.dry_run}\n")

        result = await delete_orphan_graph(
            client,
            args.space,
            args.entity_uri,
            graph_id=args.graph_id,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        print_delete_result(result)

    finally:
        await client.close()


async def cmd_delete_all_orphans(args: argparse.Namespace) -> None:
    """Scan and delete all orphaned entity graphs."""
    client = VitalGraphClient()
    try:
        await client.open()
        print(f"Connected to VitalGraph")
        print(f"Scanning space: {args.space}\n")

        orphans = await scan_orphan_graphs(client, args.space)

        if not orphans:
            print("No orphaned entity graphs found.")
            return

        print(f"Found {len(orphans)} orphan entity graphs:\n")
        for orphan in orphans:
            print(f"  {orphan}")

        print()

        for i, orphan in enumerate(orphans, 1):
            print(f"\n--- [{i}/{len(orphans)}] {orphan.entity_uri} ---")
            result = await delete_orphan_graph(
                client,
                args.space,
                orphan.entity_uri,
                graph_id=args.graph_id,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            print_delete_result(result)

        print(f"\nProcessed {len(orphans)} orphan graphs.")

    finally:
        await client.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repair_orphan_graphs",
        description="Diagnose and repair orphaned KG entity graphs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- scan ---
    p_scan = subparsers.add_parser(
        "scan", help="Find orphaned entity graphs in a space"
    )
    p_scan.add_argument("--space", required=True, help="Space ID to scan")

    # --- inspect ---
    p_inspect = subparsers.add_parser(
        "inspect", help="Show details of a specific entity graph"
    )
    p_inspect.add_argument("--space", required=True, help="Space ID")
    p_inspect.add_argument(
        "--entity-uri", required=True, help="URI of the entity to inspect"
    )

    # --- delete ---
    p_delete = subparsers.add_parser(
        "delete", help="Delete an orphaned entity graph"
    )
    p_delete.add_argument("--space", required=True, help="Space ID")
    p_delete.add_argument(
        "--entity-uri", required=True, help="URI of the orphaned entity"
    )
    p_delete.add_argument(
        "--graph-id", default=None,
        help="Named graph URI (auto-detects if not specified)",
    )
    p_delete.add_argument(
        "--batch-size", type=int, default=50,
        help="URIs per batch delete (default: 50)",
    )
    p_delete.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="Actually delete (default is dry run)",
    )

    # --- delete-all-orphans ---
    p_all = subparsers.add_parser(
        "delete-all-orphans",
        help="Scan and delete all orphaned entity graphs in a space",
    )
    p_all.add_argument("--space", required=True, help="Space ID")
    p_all.add_argument(
        "--graph-id", default=None,
        help="Named graph URI (auto-detects if not specified)",
    )
    p_all.add_argument(
        "--batch-size", type=int, default=50,
        help="URIs per batch delete (default: 50)",
    )
    p_all.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="Actually delete (default is dry run)",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "scan": cmd_scan,
        "inspect": cmd_inspect,
        "delete": cmd_delete,
        "delete-all-orphans": cmd_delete_all_orphans,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
