"""
Registry Search Verification Test Case

Tests the Entity Registry and Agent Registry search endpoints via REST API
to verify that loaded data is searchable after vector/FTS/geo population.

Tests:
  1. Entity semantic search (q only)
  2. Entity search with type filter
  3. Entity geo search (lat/lon/radius only)
  4. Entity combined semantic + geo search
  5. Entity identifier search
  6. Location geo search
  7. Location search with semantic query
  8. Location search with address keyword (BM25)
  9. Agent search (text query)
  10. Agent search with type filter
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class RegistrySearchVerifyTester:
    """Tests registry search endpoints against loaded data."""

    def __init__(self, client):
        self.client = client

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _pass(self, results: dict, label: str, detail: str = ""):
        msg = f"✅ PASS: {label}"
        if detail:
            msg += f" — {detail}"
        logger.info(msg)
        results["tests_passed"] += 1

    def _fail(self, results: dict, label: str, err: str):
        logger.error(f"❌ FAIL: {label} — {err}")
        results["errors"].append(f"{label}: {err}")
        results["tests_failed"] += 1

    def _check(self, results: dict, label: str, condition: bool, detail: str = "", err: str = ""):
        if condition:
            self._pass(results, label, detail)
        else:
            self._fail(results, label, err or detail or "condition failed")
        results["tests_run"] += 1

    # ------------------------------------------------------------------
    # main entry
    # ------------------------------------------------------------------
    async def run_tests(
        self,
        entity_ids: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run all registry search verification tests.

        Args:
            entity_ids: Optional dict mapping logical names to entity IDs
                        (from test_data_manifest.json). If None, tests are
                        generic (just check search returns results).
        """
        results: Dict[str, Any] = {
            "test_name": "Registry Search Verification",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        reg = self.client.entity_registry

        # ==================================================================
        # 1. Entity semantic search (q only)
        # ==================================================================
        logger.info("\n--- Entity Semantic Search ---")
        try:
            resp = await reg.search_entity(q="corporation business", min_certainty=0.3, limit=10)
            self._check(results, "Entity semantic search returns success",
                        resp.success is True, f"success={resp.success}")
            self._check(results, "Entity semantic search has results",
                        len(resp.results) > 0, f"count={len(resp.results)}")
            if resp.results:
                top = resp.results[0]
                self._check(results, "Top result has score > 0",
                            top.score > 0, f"score={top.score:.4f}")
                self._check(results, "Top result has entity_id",
                            bool(top.entity_id), f"entity_id={top.entity_id}")
                self._check(results, "Top result has primary_name",
                            bool(top.primary_name), f"name={top.primary_name}")
        except Exception as e:
            self._fail(results, "Entity semantic search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 2. Entity search with type filter
        # ==================================================================
        logger.info("\n--- Entity Search with Type Filter ---")
        try:
            resp = await reg.search_entity(q="consulting", type_key="person", min_certainty=0.3, limit=10)
            self._check(results, "Type filter search returns success",
                        resp.success is True)
            # All results should be persons (if any)
            if resp.results:
                all_match = all(r.type_key == "person" for r in resp.results)
                self._check(results, "All results match type_key filter",
                            all_match, f"count={len(resp.results)}")
            else:
                self._check(results, "Type filter may return 0 results (OK)",
                            True, "no matching persons")
        except Exception as e:
            self._fail(results, "Entity search type filter", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 3. Entity geo search (lat/lon/radius only)
        # ==================================================================
        logger.info("\n--- Entity Geo Search ---")
        try:
            # Near SF (37.79, -122.40) within 50 km
            resp = await reg.search_entity(
                latitude=37.79, longitude=-122.40, radius_km=50, limit=10)
            self._check(results, "Geo-only search returns success",
                        resp.success is True)
            self._check(results, "Geo-only search has results",
                        len(resp.results) > 0,
                        f"count={len(resp.results)}",
                        err="No entities found near SF (37.79, -122.40, 50km)")
            if resp.results:
                top = resp.results[0]
                has_locs = len(top.locations) > 0
                self._check(results, "Geo result has locations attached",
                            has_locs, f"locations={len(top.locations)}")
        except Exception as e:
            self._fail(results, "Entity geo search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 4. Entity combined semantic + geo search
        # ==================================================================
        logger.info("\n--- Entity Combined Semantic + Geo Search ---")
        try:
            resp = await reg.search_entity(
                q="corporation", latitude=37.79, longitude=-122.40,
                radius_km=50, min_certainty=0.3, limit=10)
            self._check(results, "Combined semantic+geo returns success",
                        resp.success is True)
            # May or may not have results depending on data distribution
            self._check(results, "Combined search does not error",
                        True, f"count={len(resp.results)}")
        except Exception as e:
            self._fail(results, "Entity combined search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 5. Entity identifier search
        # ==================================================================
        logger.info("\n--- Entity Identifier Search ---")
        try:
            # Search by a known identifier if we have entity_ids
            if entity_ids and 'acme_corp' in entity_ids:
                # Try to find by entity ID used as identifier
                resp = await reg.search_entity(
                    identifier_value=entity_ids['acme_corp'], limit=5)
                self._check(results, "Identifier search returns success",
                            resp.success is True)
                # The entity may or may not have an identifier registered
                self._check(results, "Identifier search does not error",
                            True, f"count={len(resp.results)}")
            else:
                # Generic: just verify the endpoint doesn't error
                resp = await reg.search_entity(
                    identifier_value="nonexistent-id-xyz", limit=5)
                self._check(results, "Identifier search for unknown returns success",
                            resp.success is True)
                self._check(results, "Identifier search for unknown returns 0 results",
                            len(resp.results) == 0, f"count={len(resp.results)}")
        except Exception as e:
            self._fail(results, "Entity identifier search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 6. Location geo search
        # ==================================================================
        logger.info("\n--- Location Geo Search ---")
        try:
            # Near SF
            resp = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=50, limit=10)
            self._check(results, "Location geo search returns success",
                        resp.success is True)
            self._check(results, "Location geo search has results",
                        len(resp.results) > 0,
                        f"count={len(resp.results)}",
                        err="No locations found near SF (37.79, -122.40, 50km)")
            if resp.results:
                top = resp.results[0]
                self._check(results, "Location result has location_id",
                            top.location_id is not None, f"location_id={top.location_id}")
                self._check(results, "Location result has entity_id",
                            bool(top.entity_id), f"entity_id={top.entity_id}")
        except Exception as e:
            self._fail(results, "Location geo search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 7. Location search with semantic query
        # ==================================================================
        logger.info("\n--- Location Semantic Search ---")
        try:
            resp = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=100,
                q="office headquarters", min_certainty=0.3, limit=10)
            self._check(results, "Location semantic search returns success",
                        resp.success is True)
            # May or may not have results
            self._check(results, "Location semantic search does not error",
                        True, f"count={len(resp.results)}")
        except Exception as e:
            self._fail(results, "Location semantic search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 8. Location search with address keyword (BM25)
        # ==================================================================
        logger.info("\n--- Location Address Keyword Search ---")
        try:
            resp = await reg.search_location(
                latitude=37.79, longitude=-122.40, radius_km=100,
                address="Market Street", limit=10)
            self._check(results, "Location address search returns success",
                        resp.success is True)
            self._check(results, "Location address search does not error",
                        True, f"count={len(resp.results)}")
        except Exception as e:
            self._fail(results, "Location address search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 9. Agent search (text query)
        # ==================================================================
        logger.info("\n--- Agent Search ---")
        try:
            resp = await self.client.agent_registry.search_agents(query="bot")
            self._check(results, "Agent search returns success",
                        resp.success is True)
            # Might be 0 if no agents loaded, but should not error
            self._check(results, "Agent search does not error",
                        True, f"count={resp.total_count}")
        except Exception as e:
            self._fail(results, "Agent search", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # 10. Agent search with type filter
        # ==================================================================
        logger.info("\n--- Agent Search with Type Filter ---")
        try:
            resp = await self.client.agent_registry.search_agents(
                query="", type_key="chatbot")
            self._check(results, "Agent search with type filter returns success",
                        resp.success is True)
            self._check(results, "Agent type filter search does not error",
                        True, f"count={resp.total_count}")
        except Exception as e:
            self._fail(results, "Agent search type filter", str(e))
            results["tests_run"] += 1

        # ==================================================================
        # Summary
        # ==================================================================
        logger.info(f"\n{'='*60}")
        logger.info(f"  Registry Search Verification: "
                    f"{results['tests_passed']}/{results['tests_run']} passed")
        logger.info(f"{'='*60}")

        return results
