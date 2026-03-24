#!/usr/bin/env python3
"""
Quick client test: list spaces and graphs against prod VitalGraph.

Requires VITALGRAPH_CLIENT_ENVIRONMENT=prod in .env.

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/prod_db/test_client_list_spaces.py
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Suppress chatty loggers
for name in ('httpx', 'httpcore', 'vitalgraph.client'):
    logging.getLogger(name).setLevel(logging.WARNING)

from vitalgraph.client.vitalgraph_client import VitalGraphClient


async def main():
    print("\n" + "=" * 70)
    print("  VitalGraph Client — List Spaces & Graphs (PROD)")
    print("=" * 70)

    client = VitalGraphClient()
    print(f"  Server: {client.config.get_server_url()}")
    print(f"  Auth:   {client.config.get_credentials()[0]}")
    print()

    await client.open()
    if not client.is_connected():
        logger.error("❌ Failed to connect")
        return False
    print("✅ Connected to prod VitalGraph\n")

    try:
        # List spaces
        print("-" * 70)
        print("  SPACES")
        print("-" * 70)
        resp = await client.spaces.list_spaces()
        if resp.is_success:
            spaces = resp.spaces or []
            print(f"\n  Found {len(spaces)} space(s):\n")
            for s in spaces:
                name = getattr(s, 'space_name', '') or ''
                desc = getattr(s, 'space_description', '') or ''
                print(f"    • {s.space}")
                if name:
                    print(f"      name: {name}")
                if desc:
                    print(f"      desc: {desc[:80]}")
        else:
            print(f"  ❌ Failed to list spaces: {resp.error_message}")
            return False

        # List graphs per space
        print()
        print("-" * 70)
        print("  GRAPHS")
        print("-" * 70)
        for s in spaces:
            print(f"\n  Space: {s.space}")
            try:
                gresp = await client.graphs.list_graphs(s.space)
                if gresp.is_success:
                    graphs = gresp.graphs or []
                    if graphs:
                        for g in graphs:
                            print(f"    • {g}")
                    else:
                        print(f"    (no graphs)")
                else:
                    print(f"    ❌ {gresp.error_message}")
            except Exception as e:
                print(f"    ❌ Error: {e}")

        print()
        print("=" * 70)
        print("  ✅ Done")
        print("=" * 70)
        return True

    finally:
        await client.close()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
