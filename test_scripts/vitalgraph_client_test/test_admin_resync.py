#!/usr/bin/env python3
"""
Test script for Admin resync endpoint.

Tests the /api/admin/resync endpoint which rebuilds all auxiliary tables
(edge, frame_entity, stats) from rdf_quad for a given space.

Usage:
    python vitalgraph_client_test/test_admin_resync.py
    python vitalgraph_client_test/test_admin_resync.py --space-id wordnet_exp
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.client.vitalgraph_client import VitalGraphClient, VitalGraphClientError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

DEFAULT_SPACE_ID = "sp_sql_lead_dataset"


def print_section(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


async def main():
    """Run the admin resync endpoint test."""

    parser = argparse.ArgumentParser(description="Test admin resync endpoint")
    parser.add_argument(
        "--space-id", "-s",
        type=str,
        default=DEFAULT_SPACE_ID,
        help=f"Space ID to resync (default: {DEFAULT_SPACE_ID})"
    )
    args = parser.parse_args()
    space_id = args.space_id

    print_section(f"Admin Resync Endpoint Test — space={space_id}")

    # Initialize client
    logger.info("Initializing VitalGraph client...")
    client = VitalGraphClient()

    # Connect
    logger.info("Connecting to VitalGraph server...")
    await client.open()
    if not client.is_connected():
        logger.error("Connection failed!")
        return False
    logger.info("Connected successfully\n")

    success = False

    try:
        # Call the admin resync endpoint via typed client method
        logger.info(f"Calling client.admin.resync('{space_id}')...")

        t0 = time.monotonic()
        result = await client.admin.resync(space_id)
        wall_ms = (time.monotonic() - t0) * 1000

        print_section(f"Resync Results — {space_id}")
        logger.info(f"  {'Table':<20} {'Rows':>12}")
        logger.info(f"  {'─' * 34}")
        logger.info(f"  {'edge':<20} {result.edge_rows:>12,}")
        logger.info(f"  {'frame_entity':<20} {result.frame_entity_rows:>12,}")
        logger.info(f"  {'pred_stats':<20} {result.pred_stats_rows:>12,}")
        logger.info(f"  {'quad_stats':<20} {result.quad_stats_rows:>12,}")
        logger.info(f"  {'─' * 34}")
        logger.info(f"  {'Server elapsed':<20} {result.elapsed_ms:>11.1f}ms")
        logger.info(f"  {'Wall time':<20} {wall_ms:>11.0f}ms")
        logger.info("")

        # Basic validation
        if result.edge_rows >= 0 and result.pred_stats_rows >= 0:
            logger.info("PASS: Resync completed successfully")
            success = True
        else:
            logger.error("FAIL: Unexpected negative row counts")

    except VitalGraphClientError as e:
        logger.error(f"Client error: {e}")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("\nClosing client connection...")
        await client.close()
        logger.info("Client closed\n")

    return success


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
