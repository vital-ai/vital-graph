#!/usr/bin/env python3
"""Quick check of entity graph cache stats via /health/cache."""

import asyncio
import sys
from pathlib import Path

# `parent.parent` is test_scripts/, not the project root — `vitalgraph`
# lives one level further up, so this used to fail at `import vitalgraph`.
# test_scripts/ is appended (not inserted) so it cannot shadow packages in
# this directory: test_scripts/sparql/ vs vitalgraph_client_test/sparql/.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.append(str(Path(__file__).parent.parent))

from vitalgraph.client.vitalgraph_client import VitalGraphClient


async def main():
    client = VitalGraphClient()
    await client.open()
    try:
        data = await client.cache_stats()
        # Flatten if nested under a cache key
        if isinstance(data, dict) and len(data) == 1:
            stats = next(iter(data.values()))
            if not isinstance(stats, dict):
                stats = data
        else:
            stats = data

        print("Entity Graph Cache Stats")
        print("=" * 40)
        for k, v in stats.items():
            print(f"  {k:<25} {v}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
