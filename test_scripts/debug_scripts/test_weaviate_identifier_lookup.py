"""Test identifier lookup against production Weaviate directly."""
import asyncio
import os
import sys
import logging

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('VITALGRAPH_ENVIRONMENT', 'prod')
os.environ.setdefault('ENTITY_WEAVIATE_ENABLED', 'true')

logging.basicConfig(level=logging.INFO, format='%(message)s')


async def main():
    from vitalgraph.entity_registry.entity_weaviate import EntityWeaviateIndex

    weaviate_index = await EntityWeaviateIndex.from_env()
    if not weaviate_index:
        print("Failed to connect to Weaviate")
        return

    test_cases = [
        ("EIN", "32-0518589", "dashed EIN"),
        ("EIN", "320518589", "undashed EIN"),
        ("PHONE", "17858454543", "phone number"),
    ]

    for namespace, value, label in test_cases:
        print(f"\n{'='*60}")
        print(f"Test: {label} — namespace={namespace}, value={value}")
        print(f"{'='*60}")

        results = await weaviate_index.search_by_identifier(
            identifier_value=value,
            identifier_namespace=namespace,
            limit=5,
        )

        if results:
            for r in results:
                print(f"  ✓ {r['entity_id']}: {r['primary_name']} ({r['type_key']})")
                print(f"    {r.get('locality', '')}, {r.get('region', '')} {r.get('country', '')}")
        else:
            print(f"  ✗ No results")

    # Also test value-only (no namespace)
    print(f"\n{'='*60}")
    print(f"Test: value-only search — value=32-0518589 (no namespace)")
    print(f"{'='*60}")

    results = await weaviate_index.search_by_identifier(
        identifier_value="32-0518589",
        limit=5,
    )
    if results:
        for r in results:
            print(f"  ✓ {r['entity_id']}: {r['primary_name']}")
    else:
        print(f"  ✗ No results")

    await weaviate_index.close()
    print("\nDone.")


asyncio.run(main())
