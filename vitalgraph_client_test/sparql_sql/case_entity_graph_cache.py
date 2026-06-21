"""
Entity Graph Cache Verification Test Case

Tests the in-memory entity graph cache lifecycle:
  1. Create entity
  2. GET with include_entity_graph=True (cache miss → populate)
  3. GET again (cache hit)
  4. Update entity (cache invalidated)
  5. GET again (cache miss → re-populate)
  6. Delete entity (cache invalidated)
  7. Check cache stats via /health/cache

Relies on the /health/cache endpoint for stats verification.
"""

import logging
from typing import Dict, Any

from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)

NS = "http://example.org/cache_test/"


def _make_entity(uri: str, name: str) -> KGEntity:
    e = KGEntity()
    e.URI = uri
    e.name = name
    return e


def _extract_name_from_response(resp) -> str:
    """Extract the entity name from a get_kgentity response.
    
    With include_entity_graph=True, resp.objects is an EntityGraph
    container whose .objects holds the actual GraphObject list.
    """
    if not resp.is_success or not resp.objects:
        return ""
    # EntityGraphResponse: resp.objects is EntityGraph with .objects list
    obj_list = getattr(resp.objects, 'objects', resp.objects)
    if not obj_list:
        return ""
    for obj in obj_list:
        if hasattr(obj, 'name') and obj.name:
            return str(obj.name)
    return ""


class EntityGraphCacheTester:
    """Verify entity graph cache hit/miss/invalidation via the running service."""

    def __init__(self, client):
        self.client = client

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _pass(self, results, label):
        logger.info(f"✅ PASS: {label}")
        results["tests_passed"] += 1

    def _fail(self, results, label, err):
        logger.error(f"❌ FAIL: {label} — {err}")
        results["errors"].append(f"{label}: {err}")
        results["tests_failed"] += 1

    async def _get_cache_stats(self) -> Dict[str, Any]:
        """Fetch cache stats via client.cache_stats()."""
        data = await self.client.cache_stats()
        return data.get("entity_graph_cache", {})

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------
    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "Entity Graph Cache",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Entity Graph Cache Tests")
        logger.info(f"{'=' * 80}")

        entity_uri = f"{NS}cache_entity_1"
        entity = _make_entity(entity_uri, "Cache Test Entity")

        # --- 0. Baseline cache stats ---
        try:
            baseline_stats = await self._get_cache_stats()
            logger.info(f"  Baseline cache stats: {baseline_stats}")
        except Exception as e:
            logger.warning(f"  ⚠️  Could not reach /health/cache: {e}")
            baseline_stats = {}

        # --- 1. Create entity ---
        results["tests_run"] += 1
        try:
            cr = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[entity])
            if cr.is_success:
                self._pass(results, "Create cache test entity")
            else:
                raise Exception(f"msg={getattr(cr, 'error_message', cr)}")
        except Exception as e:
            self._fail(results, "Create cache test entity", e)
            return results

        # --- 2. GET with include_entity_graph (should be cache miss → populate) ---
        results["tests_run"] += 1
        try:
            gr = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri, include_entity_graph=True)
            if gr.is_success and gr.objects:
                self._pass(results, "GET entity graph (cache miss → populate)")
            else:
                raise Exception(f"msg={getattr(gr, 'error_message', gr)}")
        except Exception as e:
            self._fail(results, "GET entity graph (miss)", e)

        # --- 3. GET again (should be cache hit) ---
        results["tests_run"] += 1
        try:
            stats_before = await self._get_cache_stats()
            hits_before = stats_before.get("hits", 0)

            gr2 = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri, include_entity_graph=True)

            stats_after = await self._get_cache_stats()
            hits_after = stats_after.get("hits", 0)

            if gr2.is_success and hits_after > hits_before:
                self._pass(results, f"GET entity graph (cache HIT — hits {hits_before}→{hits_after})")
            elif gr2.is_success:
                self._fail(results, "GET entity graph (expected cache hit)",
                           f"hits did not increase: {hits_before}→{hits_after}")
            else:
                raise Exception(f"msg={getattr(gr2, 'error_message', gr2)}")
        except Exception as e:
            self._fail(results, "GET entity graph (hit)", e)

        # --- 3b. KG entity query with include_entity_graph (should also cache hit) ---
        results["tests_run"] += 1
        try:
            stats_before = await self._get_cache_stats()
            hits_before = stats_before.get("hits", 0)
            misses_before = stats_before.get("misses", 0)

            from vitalgraph.model.kgentities_model import EntityQueryCriteria
            qr = await self.client.kgqueries.query_entities(
                space_id=space_id, graph_id=graph_id,
                entity_uris=[entity_uri],
                include_entity_graph=True,
                page_size=10, offset=0)

            stats_after = await self._get_cache_stats()
            hits_after = stats_after.get("hits", 0)
            misses_after = stats_after.get("misses", 0)

            has_graph = qr.entity_graphs and entity_uri in qr.entity_graphs
            hit_increased = hits_after > hits_before
            miss_same = misses_after == misses_before

            if has_graph and hit_increased and miss_same:
                self._pass(results, f"KG entity query include_entity_graph (cache HIT — hits {hits_before}→{hits_after})")
            elif has_graph and not hit_increased:
                self._fail(results, "KG entity query include_entity_graph",
                           f"entity_graphs present but hits did not increase: {hits_before}→{hits_after}, misses {misses_before}→{misses_after}")
            elif not has_graph:
                self._fail(results, "KG entity query include_entity_graph",
                           f"entity_graphs missing for {entity_uri}")
            else:
                self._fail(results, "KG entity query include_entity_graph",
                           f"hits {hits_before}→{hits_after}, misses {misses_before}→{misses_after}")
        except Exception as e:
            self._fail(results, "KG entity query include_entity_graph", e)

        # --- 4. Verify cached GET returns OLD name ---
        results["tests_run"] += 1
        try:
            stats_before = await self._get_cache_stats()
            hits_before = stats_before.get("hits", 0)

            gr_old = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri, include_entity_graph=True)

            stats_after = await self._get_cache_stats()
            hits_after = stats_after.get("hits", 0)

            # Extract name from response quads
            old_name = _extract_name_from_response(gr_old)
            if gr_old.is_success and hits_after > hits_before and old_name == "Cache Test Entity":
                self._pass(results, f"Cached GET returns old name='{old_name}' (cache HIT)")
            elif gr_old.is_success and old_name != "Cache Test Entity":
                self._fail(results, "Cached GET old name check",
                           f"expected 'Cache Test Entity', got '{old_name}'")
            else:
                self._fail(results, "Cached GET old name check",
                           f"hits {hits_before}→{hits_after}, name='{old_name}'")
        except Exception as e:
            self._fail(results, "Cached GET old name", e)

        # --- 5. Update entity (should invalidate cache) ---
        results["tests_run"] += 1
        try:
            updated_entity = _make_entity(entity_uri, "Cache Test Entity Updated")
            ur = await self.client.kgentities.update_kgentities(
                space_id=space_id, graph_id=graph_id,
                objects=[updated_entity])
            if ur.is_success:
                self._pass(results, "Update entity (cache invalidated)")
            else:
                raise Exception(f"msg={getattr(ur, 'error_message', ur)}")
        except Exception as e:
            self._fail(results, "Update entity", e)

        # --- 6. GET after update (should be cache miss with NEW name) ---
        results["tests_run"] += 1
        try:
            stats_before = await self._get_cache_stats()
            misses_before = stats_before.get("misses", 0)

            gr3 = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri, include_entity_graph=True)

            stats_after = await self._get_cache_stats()
            misses_after = stats_after.get("misses", 0)

            new_name = _extract_name_from_response(gr3)
            if gr3.is_success and misses_after > misses_before and new_name == "Cache Test Entity Updated":
                self._pass(results, f"GET after update returns new name='{new_name}' (cache MISS)")
            elif gr3.is_success and new_name != "Cache Test Entity Updated":
                self._fail(results, "GET after update name check",
                           f"expected 'Cache Test Entity Updated', got '{new_name}'")
            else:
                self._fail(results, "GET after update (expected cache miss)",
                           f"misses {misses_before}→{misses_after}, name='{new_name}'")
        except Exception as e:
            self._fail(results, "GET after update (miss)", e)

        # --- 7. Delete entity (should invalidate cache) ---
        results["tests_run"] += 1
        try:
            dr = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri)
            if dr.is_success:
                self._pass(results, "Delete entity (cache invalidated)")
            else:
                raise Exception(f"msg={getattr(dr, 'error_message', dr)}")
        except Exception as e:
            self._fail(results, "Delete entity", e)

        # --- 8. Final cache stats ---
        results["tests_run"] += 1
        try:
            final = await self._get_cache_stats()
            invalidations = final.get("invalidations", 0)
            baseline_inv = baseline_stats.get("invalidations", 0)
            new_invalidations = invalidations - baseline_inv
            if new_invalidations >= 2:
                self._pass(results, f"Cache invalidations: {new_invalidations} new (update + delete)")
            else:
                self._fail(results, "Cache invalidations",
                           f"expected ≥2 new invalidations, got {new_invalidations}")
            logger.info(f"  Final cache stats: {final}")
        except Exception as e:
            self._fail(results, "Final cache stats", e)

        results["tests_failed"] = results["tests_run"] - results["tests_passed"]
        return results
