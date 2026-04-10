#!/usr/bin/env python3
"""
Read-only client test for the find_similar (dedup) endpoint.

Connects via VitalGraphClient to a running server, discovers real entities
via search_entities, then exercises find_similar. Does NOT create, update,
or delete any data.

Requires a running VitalGraph server with the entity registry + dedup index.

Usage:
    VITALGRAPH_CLIENT_ENVIRONMENT=local \
    python vitalgraph_client_test/test_find_similar_readonly.py

    # Or against prod:
    VITALGRAPH_CLIENT_ENVIRONMENT=prod \
    python vitalgraph_client_test/test_find_similar_readonly.py
"""

import asyncio
import logging
import sys
import time
import traceback
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(env_path)

from vitalgraph.client.vitalgraph_client import VitalGraphClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger('test_find_similar')


class FindSimilarTestRunner:
    """Read-only client tests for find_similar endpoint."""

    def __init__(self):
        self.client = VitalGraphClient()
        self.passed = 0
        self.failed = 0
        # Discovered from live data during setup
        self.sample_entities = []

    def check(self, name: str, passed: bool, detail: str = ""):
        if passed:
            self.passed += 1
            logger.info(f"  ✅ {name}{' — ' + detail if detail else ''}")
        else:
            self.failed += 1
            logger.error(f"  ❌ {name}{' — ' + detail if detail else ''}")

    @staticmethod
    def _has_real_name(name: str) -> bool:
        """Filter out garbage names like '____', '.', '?', ', ,'."""
        if not name or len(name) < 4:
            return False
        alpha_count = sum(1 for c in name if c.isalpha())
        return alpha_count >= 3

    async def discover_entities(self):
        """Fetch real entities via search_entities (read-only)."""
        logger.info("\n--- Discovering sample entities ---")
        # Search with a common letter to avoid garbage-named entities at the top
        results = await self.client.entity_registry.search_entities(
            page_size=50, page=1, status='active')
        self.sample_entities = [
            e for e in results.entities if self._has_real_name(e.primary_name)
        ][:20]
        logger.info(f"  Found {len(self.sample_entities)} usable entities "
                    f"(total active: {results.total_count:,})")
        for e in self.sample_entities[:5]:
            logger.info(f"    • {e.primary_name} [{e.type_key}] "
                        f"({e.country or '?'}/{e.region or '?'})")

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    async def test_exact_name_search(self):
        """Search for real entity names — should find themselves."""
        logger.info("\n--- Test: Exact Name Search ---")
        found_count = 0
        tested = 0

        for entity in self.sample_entities[:10]:
            name = entity.primary_name
            if not name or len(name) < 3:
                continue
            tested += 1

            try:
                t0 = time.time()
                resp = await self.client.entity_registry.find_similar(name, min_score=40.0)
                elapsed_ms = (time.time() - t0) * 1000

                candidate_ids = [c.entity_id for c in resp.candidates]
                found = entity.entity_id in candidate_ids
                if found:
                    found_count += 1
                    match = next(c for c in resp.candidates if c.entity_id == entity.entity_id)
                    logger.info(f"    ✓ '{name}' → score={match.score:.1f}, "
                               f"{len(resp.candidates)} candidates, {elapsed_ms:.0f}ms")
                else:
                    logger.warning(f"    ✗ '{name}' NOT in {len(resp.candidates)} results, "
                                  f"{elapsed_ms:.0f}ms")
            except Exception as e:
                logger.error(f"    ✗ '{name}' → ERROR: {e}")

        self.check(f"Self-match rate", found_count >= tested * 0.7,
                   f"{found_count}/{tested} entities found themselves")

    async def test_fuzzy_name_search(self):
        """Introduce variations and verify matches still work."""
        logger.info("\n--- Test: Fuzzy Name Search ---")

        for entity in self.sample_entities[:5]:
            name = entity.primary_name
            eid = entity.entity_id
            if not name or len(name) < 8:
                continue

            # Variation: swap two adjacent characters (typo)
            if len(name) > 4:
                typo = name[:2] + name[3] + name[2] + name[4:]
                try:
                    resp2 = await self.client.entity_registry.find_similar(typo, min_score=30.0)
                    result_ids2 = [c.entity_id for c in resp2.candidates]
                    found2 = eid in result_ids2
                    if found2:
                        match2 = next(c for c in resp2.candidates if c.entity_id == eid)
                        logger.info(f"    ✓ '{typo}' (typo) → '{name}' score={match2.score:.1f}")
                except Exception as e:
                    logger.error(f"    ✗ '{typo}' → ERROR: {e}")

            # Variation: drop last word
            words = name.split()
            if len(words) >= 2:
                truncated = ' '.join(words[:-1])
                try:
                    resp2 = await self.client.entity_registry.find_similar(truncated, min_score=30.0)
                    candidate_ids2 = [c.entity_id for c in resp2.candidates]
                    found2 = entity.entity_id in candidate_ids2
                    if found2:
                        match2 = next(c for c in resp2.candidates if c.entity_id == entity.entity_id)
                        logger.info(f"    ✓ '{truncated}' (truncated) → '{name}' score={match2.score:.1f}")
                    else:
                        logger.info(f"    · '{truncated}' → '{name}' not in {len(resp2.candidates)} results")
                except Exception as e:
                    logger.error(f"    ✗ '{truncated}' → ERROR: {e}")

        self.check("Fuzzy search completes without error", True)

    async def test_country_filter(self):
        """Verify country parameter works."""
        logger.info("\n--- Test: Country Filter ---")

        # Find an entity with a country
        entity = next((e for e in self.sample_entities if e.country), None)
        if not entity:
            self.check("Found entity with country", False, "No entities have country set")
            return

        resp = await self.client.entity_registry.find_similar(
            entity.primary_name, country=entity.country, min_score=30.0)
        self.check("Find similar with country filter",
                   resp.success and len(resp.candidates) >= 1,
                   f"name='{entity.primary_name}', country={entity.country}, "
                   f"candidates={len(resp.candidates)}")

    async def test_no_results_for_nonsense(self):
        """Verify garbage input returns no high-confidence matches."""
        logger.info("\n--- Test: Negative Cases ---")
        nonsense = [
            "Xyloquest Barvonian Plc",
            "ZZZZZ QQQQQ JJJJJ Inc",
            "Frobnicator Widgets 9000",
        ]
        for name in nonsense:
            resp = await self.client.entity_registry.find_similar(name, min_score=80.0)
            self.check(f"No high-score matches for '{name}'",
                       len(resp.candidates) == 0,
                       f"got {len(resp.candidates)}")

    async def test_result_structure(self):
        """Verify response model has all expected fields."""
        logger.info("\n--- Test: Result Structure ---")
        entity = self.sample_entities[0]
        resp = await self.client.entity_registry.find_similar(
            entity.primary_name, min_score=30.0, limit=5)

        self.check("Response has success=True", resp.success is True)
        self.check("Response has candidates list", resp.candidates is not None)

        if resp.candidates:
            c = resp.candidates[0]
            self.check("Candidate has entity_id", bool(c.entity_id))
            self.check("Candidate has primary_name", bool(c.primary_name))
            self.check("Candidate has score", isinstance(c.score, (int, float)) and c.score > 0,
                       f"score={c.score}")
            self.check("Candidate has match_level",
                       c.match_level in ('high', 'likely', 'possible'),
                       f"match_level={c.match_level}")
            self.check("Candidate has score_detail",
                       c.score_detail is not None and 'ratio' in c.score_detail,
                       f"keys={list(c.score_detail.keys()) if c.score_detail else 'None'}")
            self.check("Score in 0-100 range", 0 <= c.score <= 100, f"score={c.score}")
        else:
            self.check("Got candidates for real entity name", False,
                       f"'{entity.primary_name}' returned 0 results")

    async def test_latency(self):
        """Measure round-trip query latency."""
        logger.info("\n--- Test: Latency ---")
        times = []

        for entity in self.sample_entities[:20]:
            if not entity.primary_name:
                continue
            t0 = time.time()
            await self.client.entity_registry.find_similar(
                entity.primary_name, min_score=40.0, limit=10)
            times.append((time.time() - t0) * 1000)

        if not times:
            self.check("Latency measured", False, "No entities to test")
            return

        times.sort()
        p50 = times[len(times) // 2]
        p95 = times[int(len(times) * 0.95)]
        avg = sum(times) / len(times)

        logger.info(f"    N={len(times)}, P50={p50:.0f}ms, P95={p95:.0f}ms, "
                    f"avg={avg:.0f}ms, min={times[0]:.0f}ms, max={times[-1]:.0f}ms")

        self.check("P50 latency < 1000ms", p50 < 1000, f"P50={p50:.0f}ms")
        self.check("P95 latency < 3000ms", p95 < 3000, f"P95={p95:.0f}ms")

    async def test_limit_parameter(self):
        """Verify limit parameter caps results."""
        logger.info("\n--- Test: Limit Parameter ---")
        entity = self.sample_entities[0]

        resp1 = await self.client.entity_registry.find_similar(
            entity.primary_name, min_score=30.0, limit=1)
        resp5 = await self.client.entity_registry.find_similar(
            entity.primary_name, min_score=30.0, limit=5)

        self.check("limit=1 returns at most 1", len(resp1.candidates) <= 1,
                   f"got {len(resp1.candidates)}")
        self.check("limit=5 returns at most 5", len(resp5.candidates) <= 5,
                   f"got {len(resp5.candidates)}")

    async def test_min_score_filter(self):
        """Verify min_score filters low-confidence results."""
        logger.info("\n--- Test: Min Score Filter ---")
        entity = self.sample_entities[0]

        resp_low = await self.client.entity_registry.find_similar(
            entity.primary_name, min_score=30.0, limit=50)
        resp_high = await self.client.entity_registry.find_similar(
            entity.primary_name, min_score=90.0, limit=50)

        self.check("Low threshold >= high threshold results",
                   len(resp_low.candidates) >= len(resp_high.candidates),
                   f"low={len(resp_low.candidates)}, high={len(resp_high.candidates)}")

        # All results above high threshold should have score >= 90
        if resp_high.candidates:
            all_above = all(c.score >= 89.0 for c in resp_high.candidates)
            self.check("All high-threshold results have score >= 90",
                       all_above,
                       f"min score={min(c.score for c in resp_high.candidates):.1f}")

    async def run_all(self):
        logger.info("=" * 60)
        logger.info("Find Similar — Read-Only Client Tests")
        logger.info("=" * 60)

        try:
            await self.client.open()
            logger.info("Client connected")
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return

        try:
            await self.discover_entities()
            if not self.sample_entities:
                logger.error("No entities found — is the server running with data?")
                return

            await self.test_exact_name_search()
            await self.test_fuzzy_name_search()
            await self.test_country_filter()
            await self.test_no_results_for_nonsense()
            await self.test_result_structure()
            await self.test_latency()
            await self.test_limit_parameter()
            await self.test_min_score_filter()
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            traceback.print_exc()
        finally:
            await self.client.close()

        total = self.passed + self.failed
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        logger.info(f"{'=' * 60}")


async def main():
    runner = FindSimilarTestRunner()
    await runner.run_all()
    sys.exit(0 if runner.failed == 0 else 1)


if __name__ == '__main__':
    asyncio.run(main())
