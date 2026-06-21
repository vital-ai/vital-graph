#!/usr/bin/env python3
"""
Count Cache Invalidation Test Case

Verifies that count endpoints return correct values after write operations
(create/delete), proving that the count cache is properly invalidated.

All tests are self-contained: they create temporary entities, verify counts,
then clean up — so they don't consume entities needed by later test steps.
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


class CountCacheInvalidationTester:
    """Test count cache invalidation around create and delete operations."""

    def __init__(self, client):
        self.client = client

    async def run_tests(
        self,
        space_id: str,
        graph_id: str,
        relation_type_uris: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Run count cache invalidation tests.

        Test 1: count → create entity → count (must increase by 1) → delete → count (back to original)
        Test 2: batch count → create entity → batch count (must increase) → delete
        Test 3: count_only KGQuery → create entity → count_only (must increase) → delete
        Test 4: filtered count invalidation after update (name change → search count changes)
        Test 5: filtered count (entity_type_uri) → create entity of that type → count increases
        Test 6: relation count_only → create relation → count increases → delete
        """
        results = {
            "test_name": "Count Cache Invalidation",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info("=" * 80)
        logger.info("  Count Cache Invalidation Tests")
        logger.info("=" * 80)

        # ------------------------------------------------------------------
        # Test 1: single count endpoint — create then delete
        # ------------------------------------------------------------------
        results["tests_run"] += 1
        test_name = "Count invalidation after create+delete"
        created_uri = None
        try:
            t0 = time.monotonic()

            # Baseline count
            count_baseline = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id,
            )
            # Warm cache — second call ensures value is cached
            count_cached = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id,
            )
            assert count_cached == count_baseline, (
                f"Cache warm-up mismatch: {count_cached} vs {count_baseline}"
            )
            logger.info(f"\n  Baseline count (cached): {count_baseline}")

            # Create a temporary entity (must have URI and type to be counted)
            temp = KGEntity()
            temp_uri = f"urn:cache-test:{uuid.uuid4().hex[:8]}"
            temp.URI = temp_uri
            temp.name = "CacheTest_Create"
            create_resp = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[temp],
            )
            if not create_resp.is_success:
                raise RuntimeError(f"Create failed: {create_resp.error_message}")
            created_uri = (create_resp.created_uris[0]
                          if create_resp.created_uris else temp_uri)
            logger.info(f"  Created entity: {created_uri}")

            count_after_create = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id,
            )
            logger.info(f"  After create: {count_after_create} (expected {count_baseline + 1})")

            if count_after_create != count_baseline + 1:
                msg = (f"Count after create: expected {count_baseline + 1}, "
                       f"got {count_after_create}")
                raise RuntimeError(msg)

            # Delete it — count should return to baseline
            del_resp = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=created_uri,
            )
            created_uri = None  # mark cleaned
            if not del_resp.is_success:
                raise RuntimeError(f"Delete failed: {del_resp.error_message}")

            count_after_delete = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id,
            )
            logger.info(f"  After delete: {count_after_delete} (expected {count_baseline})")

            elapsed = (time.monotonic() - t0) * 1000
            if count_after_delete == count_baseline:
                logger.info(f"✅ PASS: {test_name} ({elapsed:.0f}ms)")
                results["tests_passed"] += 1
            else:
                msg = (f"Count after delete: expected {count_baseline}, "
                       f"got {count_after_delete}")
                logger.error(f"❌ FAIL: {test_name} — {msg}")
                results["tests_failed"] += 1
                results["errors"].append(msg)

        except Exception as e:
            logger.error(f"❌ FAIL: {test_name} — {e}")
            results["tests_failed"] += 1
            results["errors"].append(str(e))
        finally:
            if created_uri:
                try:
                    await self.client.kgentities.delete_kgentity(
                        space_id=space_id, graph_id=graph_id, uri=created_uri,
                    )
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # Test 2: batch count endpoint — create then delete
        # ------------------------------------------------------------------
        results["tests_run"] += 1
        test_name = "Batch count invalidation after create+delete"
        created_uri = None
        try:
            t0 = time.monotonic()

            batch_before = await self.client.kgentities.batch_count_kgentities(
                space_id=space_id, graph_id=graph_id,
                count_requests=[{"label": "all"}],
            )
            all_before = batch_before[0]["count"] if batch_before else -1
            # Warm cache
            await self.client.kgentities.batch_count_kgentities(
                space_id=space_id, graph_id=graph_id,
                count_requests=[{"label": "all"}],
            )
            logger.info(f"\n  Batch baseline (cached): {all_before}")

            temp = KGEntity()
            temp_uri = f"urn:cache-test:{uuid.uuid4().hex[:8]}"
            temp.URI = temp_uri
            temp.name = "CacheTest_Batch"
            create_resp = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[temp],
            )
            if not create_resp.is_success:
                raise RuntimeError(f"Create failed: {create_resp.error_message}")
            created_uri = (create_resp.created_uris[0]
                          if create_resp.created_uris else temp_uri)

            batch_after = await self.client.kgentities.batch_count_kgentities(
                space_id=space_id, graph_id=graph_id,
                count_requests=[{"label": "all"}],
            )
            all_after = batch_after[0]["count"] if batch_after else -1
            logger.info(f"  After create: {all_after} (expected {all_before + 1})")

            # Delete
            del_resp = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=created_uri,
            )
            created_uri = None
            if not del_resp.is_success:
                raise RuntimeError(f"Delete failed: {del_resp.error_message}")

            batch_final = await self.client.kgentities.batch_count_kgentities(
                space_id=space_id, graph_id=graph_id,
                count_requests=[{"label": "all"}],
            )
            all_final = batch_final[0]["count"] if batch_final else -1
            logger.info(f"  After delete: {all_final} (expected {all_before})")

            elapsed = (time.monotonic() - t0) * 1000
            if all_after == all_before + 1 and all_final == all_before:
                logger.info(f"✅ PASS: {test_name} ({elapsed:.0f}ms)")
                results["tests_passed"] += 1
            else:
                msg = (f"Batch counts: before={all_before}, after_create={all_after}, "
                       f"after_delete={all_final}")
                logger.error(f"❌ FAIL: {test_name} — {msg}")
                results["tests_failed"] += 1
                results["errors"].append(msg)

        except Exception as e:
            logger.error(f"❌ FAIL: {test_name} — {e}")
            results["tests_failed"] += 1
            results["errors"].append(str(e))
        finally:
            if created_uri:
                try:
                    await self.client.kgentities.delete_kgentity(
                        space_id=space_id, graph_id=graph_id, uri=created_uri,
                    )
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # Test 3: count_only KGQuery — create then delete
        # ------------------------------------------------------------------
        results["tests_run"] += 1
        test_name = "KGQuery count_only invalidation after create+delete"
        created_uri = None
        try:
            t0 = time.monotonic()

            qr_before = await self.client.kgqueries.query_entities(
                space_id=space_id, graph_id=graph_id, count_only=True,
            )
            count_before = qr_before.total_count if qr_before else -1
            # Warm cache
            await self.client.kgqueries.query_entities(
                space_id=space_id, graph_id=graph_id, count_only=True,
            )
            logger.info(f"\n  KGQuery count_only baseline (cached): {count_before}")

            temp = KGEntity()
            temp_uri = f"urn:cache-test:{uuid.uuid4().hex[:8]}"
            temp.URI = temp_uri
            temp.name = "CacheTest_KGQuery"
            create_resp = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[temp],
            )
            if not create_resp.is_success:
                raise RuntimeError(f"Create failed: {create_resp.error_message}")
            created_uri = (create_resp.created_uris[0]
                          if create_resp.created_uris else temp_uri)

            qr_after = await self.client.kgqueries.query_entities(
                space_id=space_id, graph_id=graph_id, count_only=True,
            )
            count_after = qr_after.total_count if qr_after else -1
            logger.info(f"  After create: {count_after} (expected {count_before + 1})")

            # Delete
            del_resp = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=created_uri,
            )
            created_uri = None
            if not del_resp.is_success:
                raise RuntimeError(f"Delete failed: {del_resp.error_message}")

            qr_final = await self.client.kgqueries.query_entities(
                space_id=space_id, graph_id=graph_id, count_only=True,
            )
            count_final = qr_final.total_count if qr_final else -1
            logger.info(f"  After delete: {count_final} (expected {count_before})")

            elapsed = (time.monotonic() - t0) * 1000
            if count_after == count_before + 1 and count_final == count_before:
                logger.info(f"✅ PASS: {test_name} ({elapsed:.0f}ms)")
                results["tests_passed"] += 1
            else:
                msg = (f"KGQuery counts: before={count_before}, after_create={count_after}, "
                       f"after_delete={count_final}")
                logger.error(f"❌ FAIL: {test_name} — {msg}")
                results["tests_failed"] += 1
                results["errors"].append(msg)

        except Exception as e:
            logger.error(f"❌ FAIL: {test_name} — {e}")
            results["tests_failed"] += 1
            results["errors"].append(str(e))
        finally:
            if created_uri:
                try:
                    await self.client.kgentities.delete_kgentity(
                        space_id=space_id, graph_id=graph_id, uri=created_uri,
                    )
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # Test 4: filtered count invalidation after update (search filter)
        # ------------------------------------------------------------------
        results["tests_run"] += 1
        test_name = "Filtered count (search) invalidation after update"
        created_uri = None
        try:
            t0 = time.monotonic()

            unique_tag = f"CacheFilterTag{uuid.uuid4().hex[:6]}"

            # Create entity with a unique name
            temp = KGEntity()
            temp_uri = f"urn:cache-test:{uuid.uuid4().hex[:8]}"
            temp.URI = temp_uri
            temp.name = unique_tag
            create_resp = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[temp],
            )
            if not create_resp.is_success:
                raise RuntimeError(f"Create failed: {create_resp.error_message}")
            created_uri = (create_resp.created_uris[0]
                          if create_resp.created_uris else temp_uri)

            # Filtered count by search — should find exactly 1
            filtered_count = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id, search=unique_tag,
            )
            # Warm cache
            await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id, search=unique_tag,
            )
            logger.info(f"\n  Filtered count for '{unique_tag}': {filtered_count}")

            if filtered_count != 1:
                raise RuntimeError(f"Expected filtered count 1, got {filtered_count}")

            # Update entity name to something different
            temp.name = "UpdatedName_NoMatch"
            update_resp = await self.client.kgentities.update_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[temp],
            )
            if not update_resp.is_success:
                raise RuntimeError(f"Update failed: {update_resp.error_message}")

            # Filtered count should now be 0 for the old name
            filtered_after = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id, search=unique_tag,
            )
            logger.info(f"  After update (old name): {filtered_after} (expected 0)")

            elapsed = (time.monotonic() - t0) * 1000
            if filtered_after == 0:
                logger.info(f"\u2705 PASS: {test_name} ({elapsed:.0f}ms)")
                results["tests_passed"] += 1
            else:
                msg = f"Filtered count after update: expected 0, got {filtered_after}"
                logger.error(f"\u274c FAIL: {test_name} — {msg}")
                results["tests_failed"] += 1
                results["errors"].append(msg)

        except Exception as e:
            logger.error(f"\u274c FAIL: {test_name} — {e}")
            results["tests_failed"] += 1
            results["errors"].append(str(e))
        finally:
            if created_uri:
                try:
                    await self.client.kgentities.delete_kgentity(
                        space_id=space_id, graph_id=graph_id, uri=created_uri,
                    )
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # Test 5: filtered count (entity_type_uri) → create → count
        # ------------------------------------------------------------------
        results["tests_run"] += 1
        test_name = "Filtered count (entity_type_uri) invalidation after create+delete"
        created_uri = None
        try:
            t0 = time.monotonic()

            org_type = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"

            # Baseline filtered count
            filtered_before = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id, entity_type_uri=org_type,
            )
            # Warm cache
            await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id, entity_type_uri=org_type,
            )
            logger.info(f"\n  OrganizationEntity count (cached): {filtered_before}")

            # Create a new org-typed entity
            temp = KGEntity()
            temp_uri = f"urn:cache-test:{uuid.uuid4().hex[:8]}"
            temp.URI = temp_uri
            temp.name = "CacheTest_FilteredType"
            temp.kGEntityType = org_type
            create_resp = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[temp],
            )
            if not create_resp.is_success:
                raise RuntimeError(f"Create failed: {create_resp.error_message}")
            created_uri = (create_resp.created_uris[0]
                          if create_resp.created_uris else temp_uri)

            filtered_after = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id, entity_type_uri=org_type,
            )
            logger.info(f"  After create: {filtered_after} (expected {filtered_before + 1})")

            # Delete
            del_resp = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=created_uri,
            )
            created_uri = None
            if not del_resp.is_success:
                raise RuntimeError(f"Delete failed: {del_resp.error_message}")

            filtered_final = await self.client.kgentities.count_kgentities(
                space_id=space_id, graph_id=graph_id, entity_type_uri=org_type,
            )
            logger.info(f"  After delete: {filtered_final} (expected {filtered_before})")

            elapsed = (time.monotonic() - t0) * 1000
            if filtered_after == filtered_before + 1 and filtered_final == filtered_before:
                logger.info(f"\u2705 PASS: {test_name} ({elapsed:.0f}ms)")
                results["tests_passed"] += 1
            else:
                msg = (f"Filtered counts: before={filtered_before}, after_create={filtered_after}, "
                       f"after_delete={filtered_final}")
                logger.error(f"\u274c FAIL: {test_name} — {msg}")
                results["tests_failed"] += 1
                results["errors"].append(msg)

        except Exception as e:
            logger.error(f"\u274c FAIL: {test_name} — {e}")
            results["tests_failed"] += 1
            results["errors"].append(str(e))
        finally:
            if created_uri:
                try:
                    await self.client.kgentities.delete_kgentity(
                        space_id=space_id, graph_id=graph_id, uri=created_uri,
                    )
                except Exception:
                    pass

        # ------------------------------------------------------------------
        # Test 6: relation count_only → create relation → count → delete
        # ------------------------------------------------------------------
        if relation_type_uris and relation_type_uris.get('makes_product'):
            results["tests_run"] += 1
            test_name = "Relation count_only invalidation after create+delete"
            created_relation_uri = None
            try:
                from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation

                t0 = time.monotonic()
                makes_product_type = relation_type_uris['makes_product']

                # Baseline
                rq_before = await self.client.kgqueries.query_relation_connections(
                    space_id=space_id, graph_id=graph_id,
                    relation_type_uris=[makes_product_type],
                    count_only=True,
                )
                count_before = rq_before.total_count if rq_before else -1
                # Warm cache
                await self.client.kgqueries.query_relation_connections(
                    space_id=space_id, graph_id=graph_id,
                    relation_type_uris=[makes_product_type],
                    count_only=True,
                )
                logger.info(f"\n  Relation count_only baseline (cached): {count_before}")

                # Create a temp entity pair + relation
                src = KGEntity()
                src_uri = f"urn:cache-test:src-{uuid.uuid4().hex[:8]}"
                src.URI = src_uri
                src.name = "CacheTest_RelSrc"
                dst = KGEntity()
                dst_uri = f"urn:cache-test:dst-{uuid.uuid4().hex[:8]}"
                dst.URI = dst_uri
                dst.name = "CacheTest_RelDst"
                await self.client.kgentities.create_kgentities(
                    space_id=space_id, graph_id=graph_id, objects=[src, dst],
                )

                rel = Edge_hasKGRelation()
                rel_uri = f"urn:cache-test:rel-{uuid.uuid4().hex[:8]}"
                rel.URI = rel_uri
                rel.edgeSource = src_uri
                rel.edgeDestination = dst_uri
                rel.kGRelationType = makes_product_type
                rel_resp = await self.client.kgrelations.create_relations(
                    space_id, graph_id, [rel],
                )
                if rel_resp.is_success:
                    created_relation_uri = rel_resp.created_uris[0] if rel_resp.created_uris else rel_uri
                else:
                    raise RuntimeError(f"Relation create failed: {rel_resp.error_message}")

                rq_after = await self.client.kgqueries.query_relation_connections(
                    space_id=space_id, graph_id=graph_id,
                    relation_type_uris=[makes_product_type],
                    count_only=True,
                )
                count_after = rq_after.total_count if rq_after else -1
                logger.info(f"  After create: {count_after} (expected {count_before + 1})")

                # Delete relation + entities
                await self.client.kgrelations.delete_relations(
                    space_id, graph_id, [created_relation_uri],
                )
                created_relation_uri = None
                await self.client.kgentities.delete_kgentity(
                    space_id=space_id, graph_id=graph_id, uri=src_uri,
                )
                await self.client.kgentities.delete_kgentity(
                    space_id=space_id, graph_id=graph_id, uri=dst_uri,
                )

                rq_final = await self.client.kgqueries.query_relation_connections(
                    space_id=space_id, graph_id=graph_id,
                    relation_type_uris=[makes_product_type],
                    count_only=True,
                )
                count_final = rq_final.total_count if rq_final else -1
                logger.info(f"  After delete: {count_final} (expected {count_before})")

                elapsed = (time.monotonic() - t0) * 1000
                if count_after == count_before + 1 and count_final == count_before:
                    logger.info(f"\u2705 PASS: {test_name} ({elapsed:.0f}ms)")
                    results["tests_passed"] += 1
                else:
                    msg = (f"Relation counts: before={count_before}, after_create={count_after}, "
                           f"after_delete={count_final}")
                    logger.error(f"\u274c FAIL: {test_name} — {msg}")
                    results["tests_failed"] += 1
                    results["errors"].append(msg)

            except Exception as e:
                logger.error(f"\u274c FAIL: {test_name} — {e}")
                results["tests_failed"] += 1
                results["errors"].append(str(e))
                # Best-effort cleanup
                if created_relation_uri:
                    try:
                        await self.client.kgrelations.delete_relations(
                            space_id, graph_id, [created_relation_uri],
                        )
                    except Exception:
                        pass
                for uri in [src_uri, dst_uri]:
                    try:
                        await self.client.kgentities.delete_kgentity(
                            space_id=space_id, graph_id=graph_id, uri=uri,
                        )
                    except Exception:
                        pass
        else:
            logger.info("\n  Skipping relation count_only test (no relation data)")

        return results
