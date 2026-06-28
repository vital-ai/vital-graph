#!/usr/bin/env python3
"""
Phase G: OpenAI Provider Validation for KG Type Search
=======================================================

Validates that the vector index provider swap mechanism works end-to-end:

1. Capture VitalSigns top-5 results for comparison queries
2. Swap index to OpenAI text-embedding-3-small (1536d)
3. Repopulate with OpenAI embeddings
4. Run FTS, vector, and hybrid tests
5. Log OpenAI vs VitalSigns top-5 comparison
6. Swap back to VitalSigns and repopulate

Prerequisites:
  - VitalGraph service running at localhost:8001
  - Space set up via: python test_scripts/sparql/setup_kgtype_search_framenet.py
  - OPENAI_API_KEY set in .env

Usage:
  python test_scripts/sparql/test_kgtype_search_openai.py
"""

import asyncio
import logging
import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
SPACE_ID = "framenet_kgtypes_test"
GRAPH_ID = "urn:vitalgraph:framenet_kgtypes_test:kg_types"
INDEX_NAME = "kgtype_default"

VITALSIGNS_CONFIG = {
    "dimensions": 384,
    "distance_metric": "cosine",
    "provider": "vitalsigns",
    "model_name": "paraphrase-multilingual-MiniLM-L12-v2",
    "description": "KGType embeddings — VitalSigns ONNX (384d, local)",
}

OPENAI_CONFIG = {
    "dimensions": 1536,
    "distance_metric": "cosine",
    "provider": "openai",
    "model_name": "text-embedding-3-small",
    "provider_config": {"api_key_env": "OPENAI_API_KEY"},
    "description": "KGType embeddings — OpenAI 3-small (1536d, API)",
}

# Queries used for both VitalSigns and OpenAI comparison
COMPARISON_QUERIES = [
    {"query": "hiring someone for a job", "mode": "vector", "type": "frame"},
    {"query": "physical movement from one place to another", "mode": "vector", "type": "frame"},
    {"query": "giving money to someone as payment", "mode": "vector", "type": "frame"},
    {"query": "cooking food preparation heat", "mode": "hybrid", "type": "frame"},
    {"query": "commercial transaction buying selling goods", "mode": "hybrid", "type": "frame"},
]

# Tests to run with OpenAI (FTS should work unchanged; vector/hybrid use new embeddings)
OPENAI_TESTS = [
    # FTS — validates search_text + tsvector GIN with new table
    {"name": "FTS: commercial transaction", "query": "commercial transaction buying",
     "mode": "fts", "type": "frame", "expected": ["Commercial_transaction"], "min": 1},
    {"name": "FTS: cooking food", "query": "cooking food heat",
     "mode": "fts", "type": "frame", "expected": ["Cooking_creation"], "min": 1},
    {"name": "FTS: motion frames", "query": "source goal path place",
     "mode": "fts", "type": "frame", "expected": ["Motion"], "min": 1},
    # Vector — validates OpenAI embed → HNSW query
    {"name": "Vector: hiring/employment", "query": "hiring someone for a job",
     "mode": "vector", "type": "frame", "expected": ["Hiring"], "min": 1},
    {"name": "Vector: physical movement", "query": "physical movement from one place to another",
     "mode": "vector", "type": "frame", "expected": ["Motion"], "min": 1},
    {"name": "Vector: giving money", "query": "giving money to someone as payment",
     "mode": "vector", "type": "frame", "expected": [], "min": 1},
    # Hybrid — validates FTS + vector JOIN with OpenAI embeddings
    {"name": "Hybrid: cooking", "query": "cooking food preparation heat",
     "mode": "hybrid", "type": "frame", "expected": ["Cooking_creation"], "min": 1},
    {"name": "Hybrid: commercial", "query": "commercial transaction buying selling goods",
     "mode": "hybrid", "type": "frame", "expected": ["Commercial_transaction"], "min": 1},
]


def _extract_names(response) -> List[str]:
    """Extract type names from search response."""
    names = []
    if hasattr(response, 'types') and response.types:
        for t in response.types:
            name = None
            if hasattr(t, 'name'):
                name = t.name
            elif isinstance(t, dict):
                name = t.get('name') or t.get('hasName')
            if name:
                names.append(str(name))
    return names


async def _create_mapping(client, type_uri, properties, label):
    """Create one search mapping with properties."""
    try:
        result = await client.search_mappings.create_mapping(
            space_id=SPACE_ID, index_name=INDEX_NAME,
            mapping_type="kgtype", type_uri=type_uri,
            source_type="properties", enabled=True,
            separator=". ", include_pred_name=False, include_type_desc=False,
        )
        mapping_id = result.mapping_id
        for prop_uri, ordinal in properties:
            await client.search_mappings.add_property(
                space_id=SPACE_ID, mapping_id=mapping_id,
                property_uri=prop_uri, ordinal=ordinal,
            )
        logger.info("    Created mapping: %s (%d properties)", label, len(properties))
    except Exception as e:
        if "already exists" in str(e).lower() or "409" in str(e):
            logger.info("    Mapping %s already exists", label)
        else:
            raise


async def _recreate_search_mappings(client):
    """Recreate all KGType search mappings (base + type-specific overrides)."""
    HAS_NAME = "http://vital.ai/ontology/vital-core#hasName"
    HAS_DESC = "http://vital.ai/ontology/haley-ai-kg#hasKGraphDescription"

    await _create_mapping(client, None, [
        (HAS_NAME, 1), (HAS_DESC, 2),
    ], "base (all KGTypes)")

    await _create_mapping(client,
        "http://vital.ai/ontology/haley-ai-kg#KGEntityType", [
            (HAS_NAME, 1), (HAS_DESC, 2),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGEntityTypeDescription", 3),
        ], "KGEntityType")

    await _create_mapping(client,
        "http://vital.ai/ontology/haley-ai-kg#KGFrameType", [
            (HAS_NAME, 1), (HAS_DESC, 2),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGFrameTypeDescription", 3),
        ], "KGFrameType")

    await _create_mapping(client,
        "http://vital.ai/ontology/haley-ai-kg#KGSlotType", [
            (HAS_NAME, 1),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeName", 2),
            ("http://vital.ai/ontology/haley-ai-kg#hasKGSlotTypeLabel", 3),
            (HAS_DESC, 4),
        ], "KGSlotType")


async def capture_top5(client: VitalGraphClient, label: str) -> Dict[str, List[str]]:
    """Capture top-5 results for comparison queries."""
    results = {}
    for q in COMPARISON_QUERIES:
        key = f"{q['mode']}:{q['query'][:40]}"
        try:
            resp = await client.kgtypes.search_types(
                SPACE_ID, GRAPH_ID,
                query=q["query"], search_mode=q["mode"], type=q["type"],
            )
            names = _extract_names(resp)[:5]
            results[key] = names
        except Exception as e:
            results[key] = [f"ERROR: {e}"]
    return results


async def swap_to_provider(client: VitalGraphClient, config: Dict[str, Any], label: str):
    """Delete existing indexes + recreate with new provider config."""
    print(f"\n{'='*70}")
    print(f"Swapping to {label}")
    print(f"{'='*70}")

    # Delete existing vector index (also drops data table)
    print(f"  Deleting vector index '{INDEX_NAME}'...")
    try:
        await client.vector_indexes.delete_index(SPACE_ID, INDEX_NAME)
        logger.info("  Deleted vector index")
    except Exception as e:
        logger.warning("  Delete vector index: %s (continuing)", e)

    # Delete existing FTS index
    print(f"  Deleting FTS index '{INDEX_NAME}'...")
    try:
        await client.fts_indexes.delete_index(SPACE_ID, INDEX_NAME)
        logger.info("  Deleted FTS index")
    except Exception as e:
        logger.warning("  Delete FTS index: %s (continuing)", e)

    await asyncio.sleep(1)  # Let server settle

    # Recreate vector index with new provider
    print(f"  Creating vector index: {config['provider']} ({config['dimensions']}d)...")
    provider_config = config.get("provider_config")
    await client.vector_indexes.create_index(
        space_id=SPACE_ID,
        index_name=INDEX_NAME,
        dimensions=config["dimensions"],
        distance_metric=config["distance_metric"],
        provider=config["provider"],
        model_name=config["model_name"],
        provider_config=provider_config,
        description=config.get("description", ""),
    )
    logger.info("  Created vector index")

    # Recreate FTS index
    print(f"  Creating FTS index...")
    await client.fts_indexes.create_index(
        space_id=SPACE_ID,
        index_name=INDEX_NAME,
        languages=["english"],
    )
    logger.info("  Created FTS index")

    # Recreate search mappings (deleted along with the index)
    print(f"  Recreating search mappings...")
    await _recreate_search_mappings(client)
    logger.info("  Recreated search mappings")


async def populate_and_wait(client: VitalGraphClient, timeout: int = 600):
    """Trigger async vector + FTS population and poll until ready."""
    print("  Triggering population...")

    # Vector reindex
    result = await client.vector_indexes.reindex(
        space_id=SPACE_ID, index_name=INDEX_NAME,
        graph_uri=GRAPH_ID, mapping_type="kgtype",
    )
    logger.info("  Vector reindex: %s", result.message)

    # FTS populate
    fts_result = await client.fts_indexes.populate(
        space_id=SPACE_ID, index_name=INDEX_NAME,
        graph_uri=GRAPH_ID, mapping_type="kgtype",
    )
    logger.info("  FTS populate: %s", fts_result.message)

    # Poll until stable — use longer intervals and higher threshold to avoid
    # premature "ready" when VitalSigns CPU embedding pauses between batches.
    t0 = time.time()
    poll_interval = 10
    prev_vec = -1
    prev_fts = -1
    stable_count = 0
    min_vec = 1000  # FrameNet has ~2500 types; require at least this many
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
        if vec_count >= min_vec and fts_count > 0:
            if vec_count == prev_vec and fts_count == prev_fts:
                stable_count += 1
            else:
                stable_count = 0
            if stable_count >= 3:
                logger.info("  Indexes ready: vec=%d, fts=%d (%.0fs)", vec_count, fts_count, elapsed)
                return
        prev_vec = vec_count
        prev_fts = fts_count
        logger.info("  Waiting... vec=%d, fts=%d (%.0fs)", vec_count, fts_count, elapsed)
        await asyncio.sleep(poll_interval)

    raise RuntimeError(f"Indexes not populated after {timeout}s")


async def run_openai_tests(client: VitalGraphClient) -> tuple:
    """Run FTS/vector/hybrid tests with OpenAI provider. Returns (passed, failed, errors)."""
    passed = 0
    failed = 0
    errors = []

    for test in OPENAI_TESTS:
        try:
            resp = await client.kgtypes.search_types(
                SPACE_ID, GRAPH_ID,
                query=test["query"], search_mode=test["mode"], type=test.get("type"),
            )
            names = _extract_names(resp)
            count = len(names)

            # Check min results
            if count < test["min"]:
                errors.append(f"{test['name']}: got {count} results, expected >= {test['min']}")
                failed += 1
                print(f"  ❌ {test['name']}: {count} results (expected >= {test['min']})")
                continue

            # Check expected names in results
            missing = [e for e in test["expected"] if not any(e in n for n in names)]
            if missing:
                errors.append(f"{test['name']}: missing {missing} in {names[:5]}")
                failed += 1
                print(f"  ❌ {test['name']}: missing {missing}")
            else:
                passed += 1
                top3 = names[:3]
                print(f"  ✓ {test['name']} ({count} results, top: {top3})")

        except Exception as e:
            errors.append(f"{test['name']}: {e}")
            failed += 1
            print(f"  ❌ {test['name']}: {e}")

    return passed, failed, errors


def print_comparison(vs_results: Dict, openai_results: Dict):
    """Print side-by-side top-5 comparison."""
    print(f"\n{'='*70}")
    print("VitalSigns vs OpenAI — Top-5 Comparison")
    print(f"{'='*70}")
    for key in vs_results:
        vs_names = vs_results[key]
        oa_names = openai_results.get(key, ["N/A"])
        print(f"\n  Query: {key}")
        print(f"    VitalSigns: {vs_names}")
        print(f"    OpenAI:     {oa_names}")
        # Overlap
        vs_set = set(vs_names) - {n for n in vs_names if n.startswith("ERROR")}
        oa_set = set(oa_names) - {n for n in oa_names if n.startswith("ERROR")}
        if vs_set and oa_set:
            overlap = vs_set & oa_set
            print(f"    Overlap:    {len(overlap)}/{max(len(vs_set), len(oa_set))} — {sorted(overlap) if overlap else 'none'}")


async def main():
    # Check OpenAI key
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "your-openai-api-key-here":
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)

    print("=" * 70)
    print("Phase G: OpenAI Provider Validation")
    print("=" * 70)
    print(f"  Space: {SPACE_ID}")
    print(f"  Index: {INDEX_NAME}")
    print(f"  OpenAI key: {api_key[:8]}...")
    print()

    client = VitalGraphClient(token_expiry_seconds=300)
    await client.open()

    passed_total = 0
    failed_total = 0

    try:
        # G6: Capture VitalSigns baseline
        print("Step 1: Capturing VitalSigns top-5 baseline...")
        vs_results = await capture_top5(client, "VitalSigns")
        logger.info("  Captured %d comparison queries", len(vs_results))

        # G1: Swap to OpenAI
        await swap_to_provider(client, OPENAI_CONFIG, "OpenAI text-embedding-3-small")

        # G2: Populate with OpenAI embeddings
        print("\nStep 2: Populating with OpenAI embeddings (~$0.003)...")
        t0 = time.time()
        await populate_and_wait(client, timeout=600)
        print(f"  Population completed in {time.time() - t0:.0f}s")

        # G3–G5: Run tests
        print(f"\n{'='*70}")
        print("OpenAI Search Tests")
        print(f"{'='*70}")
        passed, failed, errors = await run_openai_tests(client)
        passed_total += passed
        failed_total += failed

        # G6: Capture OpenAI results and compare
        print("\nStep 3: Capturing OpenAI top-5 for comparison...")
        openai_results = await capture_top5(client, "OpenAI")
        print_comparison(vs_results, openai_results)

        # G7: Swap back to VitalSigns
        await swap_to_provider(client, VITALSIGNS_CONFIG, "VitalSigns (restore)")

        print("\nStep 4: Repopulating with VitalSigns embeddings...")
        t0 = time.time()
        await populate_and_wait(client, timeout=300)
        print(f"  Restore completed in {time.time() - t0:.0f}s")

        # Quick sanity check with VitalSigns
        print("\nStep 5: VitalSigns restore sanity check...")
        try:
            resp = await client.kgtypes.search_types(
                SPACE_ID, GRAPH_ID,
                query="hiring someone for a job", search_mode="vector", type="frame",
            )
            names = _extract_names(resp)
            if any("Hiring" in n for n in names):
                print("  ✓ VitalSigns restored: 'Hiring' found in vector search")
                passed_total += 1
            else:
                print(f"  ❌ VitalSigns restored: 'Hiring' not found (got {names[:3]})")
                failed_total += 1
        except Exception as e:
            print(f"  ❌ VitalSigns sanity check failed: {e}")
            failed_total += 1

    finally:
        await client.close()

    # Summary
    print(f"\n{'='*70}")
    print(f"Results: {passed_total}/{passed_total + failed_total} passed, {failed_total} failed")
    if failed_total:
        print("Failures:")
        for err in errors:
            print(f"  - {err}")
    print(f"{'='*70}")

    sys.exit(1 if failed_total else 0)


if __name__ == "__main__":
    asyncio.run(main())
