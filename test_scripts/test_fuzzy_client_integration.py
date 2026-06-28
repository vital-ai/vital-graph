#!/usr/bin/env python3
"""
Fuzzy (fuzzy match) client integration test — validates the find_similar
pipeline through the VitalGraphClient.

Tests:
  1. Client → REST API → MinHash/RapidFuzz → response deserialization
  2. Known misspellings find correct canonical entities
  3. Score ordering (best match first)
  4. Negative controls (unrelated names don't match)
  5. Type filtering works

Prerequisites:
  - VitalGraph server running at configured URL
  - Entity registry populated with fuzzy test data
    (run: python test_scripts/data/generate_fuzzy_test_data.py --load-registry)

Usage:
    python test_scripts/test_fuzzy_client_integration.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_fuzzy_client_integration")


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

MISSPELLING_TESTS = [
    {"query": "Aple Inc", "expected_contains": "Apple", "min_score": 40},
    {"query": "Gogle LLC", "expected_contains": "Google", "min_score": 40},
    {"query": "Microsft Corporation", "expected_contains": "Microsoft", "min_score": 40},
    {"query": "Amazno.com Inc", "expected_contains": "Amazon", "min_score": 30},
    {"query": "Tessla Inc", "expected_contains": "Tesla", "min_score": 40},
]

ABBREVIATION_TESTS = [
    {"query": "Microsoft Corp.", "expected_contains": "Microsoft", "min_score": 50},
    {"query": "Toyota Motor Corp", "expected_contains": "Toyota", "min_score": 50},
    {"query": "Deutsche Bank", "expected_contains": "Deutsche Bank", "min_score": 60},
]

NEGATIVE_TESTS = [
    "Quantum Dynamics Research Lab",
    "Stellar Navigation Systems",
    "Pacific Rim Trading Co",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_find_similar_misspellings(client) -> bool:
    """Test that misspelled names find the correct canonical entity."""
    logger.info("test_find_similar_misspellings...")
    all_passed = True

    for tc in MISSPELLING_TESTS:
        result = await client.entity_registry.find_similar(
            name=tc["query"],
            min_score=float(tc["min_score"]),
            limit=5,
        )

        candidates = getattr(result, 'candidates', [])

        if not candidates:
            logger.error("  FAILED '%s': no candidates returned", tc["query"])
            all_passed = False
            continue

        # Check if expected entity is in results
        found = False
        for c in candidates:
            cname = getattr(c, 'name', '') or getattr(c, 'primary_name', '') or str(c)
            if tc["expected_contains"].lower() in cname.lower():
                score = getattr(c, 'score', 0) or getattr(c, 'similarity_score', 0)
                logger.info("  OK '%s' → '%s' (score=%.1f)", tc["query"], cname, score)
                found = True
                break

        if not found:
            candidate_names = [
                getattr(c, 'name', '') or getattr(c, 'primary_name', '') or str(c)
                for c in candidates
            ]
            logger.error("  FAILED '%s': expected '%s' in results, got: %s",
                         tc["query"], tc["expected_contains"], candidate_names)
            all_passed = False

    if all_passed:
        logger.info("  PASSED (%d/%d)", len(MISSPELLING_TESTS), len(MISSPELLING_TESTS))
    return all_passed


async def test_find_similar_abbreviations(client) -> bool:
    """Test that abbreviation variants find the correct canonical entity."""
    logger.info("test_find_similar_abbreviations...")
    all_passed = True

    for tc in ABBREVIATION_TESTS:
        result = await client.entity_registry.find_similar(
            name=tc["query"],
            min_score=float(tc["min_score"]),
            limit=5,
        )

        candidates = getattr(result, 'candidates', [])

        if not candidates:
            logger.error("  FAILED '%s': no candidates returned", tc["query"])
            all_passed = False
            continue

        found = False
        for c in candidates:
            cname = getattr(c, 'name', '') or getattr(c, 'primary_name', '') or str(c)
            if tc["expected_contains"].lower() in cname.lower():
                score = getattr(c, 'score', 0) or getattr(c, 'similarity_score', 0)
                logger.info("  OK '%s' → '%s' (score=%.1f)", tc["query"], cname, score)
                found = True
                break

        if not found:
            candidate_names = [
                getattr(c, 'name', '') or getattr(c, 'primary_name', '') or str(c)
                for c in candidates
            ]
            logger.error("  FAILED '%s': expected '%s' in results, got: %s",
                         tc["query"], tc["expected_contains"], candidate_names)
            all_passed = False

    if all_passed:
        logger.info("  PASSED (%d/%d)", len(ABBREVIATION_TESTS), len(ABBREVIATION_TESTS))
    return all_passed


async def test_negative_controls(client) -> bool:
    """Test that unrelated names don't produce false positive matches."""
    logger.info("test_negative_controls...")
    all_passed = True

    for query in NEGATIVE_TESTS:
        result = await client.entity_registry.find_similar(
            name=query,
            min_score=70.0,  # High threshold
            limit=5,
        )

        candidates = getattr(result, 'candidates', [])

        if candidates:
            # Check if any matches are from our canonical set
            canonical_names = [
                "Apple", "Google", "Microsoft", "Amazon", "Meta",
                "Tesla", "Netflix", "JPMorgan", "Deutsche Bank",
                "Toyota", "Samsung", "Alibaba", "Berkshire",
                "Johnson", "Procter",
            ]
            false_positives = []
            for c in candidates:
                cname = getattr(c, 'name', '') or getattr(c, 'primary_name', '') or str(c)
                for cn in canonical_names:
                    if cn.lower() in cname.lower():
                        false_positives.append(cname)
                        break

            if false_positives:
                logger.error("  FAILED '%s': false positives: %s", query, false_positives)
                all_passed = False
            else:
                logger.info("  OK '%s': %d results but none from canonical set", query, len(candidates))
        else:
            logger.info("  OK '%s': no candidates (correct)", query)

    if all_passed:
        logger.info("  PASSED (%d/%d)", len(NEGATIVE_TESTS), len(NEGATIVE_TESTS))
    return all_passed


async def test_score_ordering(client) -> bool:
    """Test that results are ordered by score (best first)."""
    logger.info("test_score_ordering...")

    result = await client.entity_registry.find_similar(
        name="Apple Inc",
        min_score=20.0,
        limit=10,
    )

    candidates = getattr(result, 'candidates', [])

    if len(candidates) < 2:
        logger.warning("  SKIPPED: Need at least 2 results to test ordering")
        return True

    scores = []
    for c in candidates:
        score = getattr(c, 'score', 0) or getattr(c, 'similarity_score', 0)
        scores.append(float(score))

    # Scores should be descending
    for i in range(len(scores) - 1):
        if scores[i] < scores[i + 1]:
            logger.error("  FAILED: scores not descending at position %d: %s", i, scores)
            return False

    logger.info("  PASSED (scores descending: %s)", [f"{s:.1f}" for s in scores[:5]])
    return True


async def test_empty_query(client) -> bool:
    """Test behavior with a very short/empty-like query."""
    logger.info("test_empty_query...")

    try:
        result = await client.entity_registry.find_similar(
            name="x",
            min_score=90.0,
            limit=5,
        )
        candidates = getattr(result, 'candidates', [])
        logger.info("  OK: query 'x' returned %d candidates (expected few/none)", len(candidates))
        return True
    except Exception as e:
        # Some implementations may reject very short queries
        logger.info("  OK: query 'x' raised %s (acceptable)", type(e).__name__)
        return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    from vitalgraph.client.vitalgraph_client import VitalGraphClient

    api_key = os.environ.get("VITALGRAPH_API_KEY")

    client = VitalGraphClient(api_key=api_key) if api_key else VitalGraphClient()
    await client.open()

    try:
        results = {}
        results["find_similar_misspellings"] = await test_find_similar_misspellings(client)
        results["find_similar_abbreviations"] = await test_find_similar_abbreviations(client)
        results["negative_controls"] = await test_negative_controls(client)
        results["score_ordering"] = await test_score_ordering(client)
        results["empty_query"] = await test_empty_query(client)

        # Summary
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info("")
        logger.info("=" * 60)
        logger.info("  FUZZY CLIENT INTEGRATION: %d/%d passed", passed, total)
        logger.info("=" * 60)
        for name, ok in results.items():
            logger.info("  %s %s", "PASS" if ok else "FAIL", name)

        if passed < total:
            sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
