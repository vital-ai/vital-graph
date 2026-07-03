#!/usr/bin/env python3
"""Generate PlanV2 test fixtures from the Jena sidecar.

Sends each query in sparql_corpus.py to the sidecar's /v1/sparql/compile
endpoint and saves the raw JSON response. These fixtures are then used by
unit tests to reconstruct real PlanV2 trees without needing the sidecar.

Usage:
    python tests/fixtures/plan_trees/generate_fixtures.py

Requires:
    - Running Jena sidecar on localhost:7070 (or SPARQL_COMPILER_URL env var)
"""

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from vitalgraph.db.jena_sparql.jena_sidecar_client import SidecarClient
from sparql_corpus import QUERIES

FIXTURE_DIR = Path(__file__).parent / "json"


def main():
    FIXTURE_DIR.mkdir(exist_ok=True)

    client = SidecarClient()
    success = 0
    failed = 0

    for name, sparql in QUERIES:
        print(f"  {name}...", end=" ")
        try:
            result = client.compile(sparql.strip())
            if not result.get("ok"):
                print(f"PARSE ERROR: {result.get('error', {}).get('message', '?')}")
                failed += 1
                continue

            # Save with metadata
            fixture = {
                "name": name,
                "sparql": sparql.strip(),
                "sidecar_response": result,
            }
            outpath = FIXTURE_DIR / f"{name}.json"
            outpath.write_text(json.dumps(fixture, indent=2))
            print("OK")
            success += 1

        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    client.close()
    print(f"\nDone: {success} generated, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
