"""
Objects CRUD Test Case — SPARQL-SQL Backend

Tests object lifecycle: create, list, get, update, delete via the Objects endpoint.
Uses VitalSigns KGEntity objects as test data.
"""

import logging
from typing import Dict, Any, List

from vital_ai_vitalsigns.vitalsigns import VitalSigns
from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)


def _make_entity(uri: str, name: str, entity_type: str = "http://vital.ai/ontology/haley-ai-kg#GenericEntity") -> KGEntity:
    """Create a KGEntity with the given URI and name."""
    e = KGEntity()
    e.URI = uri
    e.name = name
    e.kGEntityType = entity_type
    return e


NS = "http://example.org/sqlobj/"


class ObjectsCrudTester:
    """Client-based test for objects CRUD against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run objects CRUD tests.

        Expects the space and graph to already exist.

        Args:
            space_id: Space to operate in
            graph_id: Graph URI for object operations

        Returns:
            Standard test results dict
        """
        results = {
            "test_name": "Objects CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Objects CRUD")
        logger.info(f"{'=' * 80}")

        # Build test objects
        obj_alice = _make_entity(f"{NS}alice", "Alice")
        obj_bob = _make_entity(f"{NS}bob", "Bob")
        obj_charlie = _make_entity(f"{NS}charlie", "Charlie")

        # --- 1. Create objects ---
        results["tests_run"] += 1
        try:
            cr = await self.client.objects.create_objects(space_id, graph_id, [obj_alice, obj_bob, obj_charlie])
            if cr.is_success and cr.created_count == 3:
                logger.info(f"✅ PASS: Create 3 objects")
                results["tests_passed"] += 1
            else:
                raise Exception(f"created_count={getattr(cr, 'created_count', '?')}, msg={getattr(cr, 'error_message', cr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Create objects — {e}")
            results["errors"].append(f"Create objects: {e}")
            # Can't continue if create failed
            return results

        # --- 2. List objects ---
        results["tests_run"] += 1
        try:
            lr = await self.client.objects.list_objects(space_id, graph_id, page_size=50)
            if lr.is_success and lr.count >= 3:
                logger.info(f"✅ PASS: List objects — count={lr.count}")
                results["tests_passed"] += 1
            else:
                raise Exception(f"count={getattr(lr, 'count', '?')}, msg={getattr(lr, 'error_message', lr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: List objects — {e}")
            results["errors"].append(f"List objects: {e}")

        # --- 3. Get object by URI ---
        results["tests_run"] += 1
        try:
            gr = await self.client.objects.get_object(space_id, graph_id, f"{NS}alice")
            if gr.is_success and gr.object is not None:
                got_name = str(gr.object.name) if hasattr(gr.object, 'name') else None
                logger.info(f"✅ PASS: Get object — name={got_name}")
                results["tests_passed"] += 1
            else:
                raise Exception(f"msg={getattr(gr, 'error_message', gr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Get object — {e}")
            results["errors"].append(f"Get object: {e}")

        # --- 4. Update object ---
        results["tests_run"] += 1
        try:
            obj_alice_updated = _make_entity(f"{NS}alice", "Alice Updated")
            ur = await self.client.objects.update_objects(space_id, graph_id, [obj_alice_updated])
            if ur.is_success:
                logger.info(f"✅ PASS: Update object")
                results["tests_passed"] += 1
            else:
                raise Exception(f"msg={getattr(ur, 'error_message', ur)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Update object — {e}")
            results["errors"].append(f"Update object: {e}")

        # --- 5. Verify update ---
        results["tests_run"] += 1
        try:
            gr2 = await self.client.objects.get_object(space_id, graph_id, f"{NS}alice")
            if gr2.is_success and gr2.object is not None:
                got_name = str(gr2.object.name) if hasattr(gr2.object, 'name') else None
                if got_name == "Alice Updated":
                    logger.info(f"✅ PASS: Verify update — name={got_name}")
                    results["tests_passed"] += 1
                else:
                    raise Exception(f"expected 'Alice Updated', got '{got_name}'")
            else:
                raise Exception(f"msg={getattr(gr2, 'error_message', gr2)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify update — {e}")
            results["errors"].append(f"Verify update: {e}")

        # --- 6. Delete single object ---
        results["tests_run"] += 1
        try:
            dr = await self.client.objects.delete_object(space_id, graph_id, f"{NS}bob")
            if dr.is_success:
                logger.info(f"✅ PASS: Delete object (bob)")
                results["tests_passed"] += 1
            else:
                raise Exception(f"msg={getattr(dr, 'error_message', dr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Delete object — {e}")
            results["errors"].append(f"Delete object: {e}")

        # --- 7. Verify bob deleted ---
        results["tests_run"] += 1
        try:
            gr3 = await self.client.objects.get_object(space_id, graph_id, f"{NS}bob")
            if not gr3.is_success or gr3.object is None:
                logger.info(f"✅ PASS: Verify bob deleted")
                results["tests_passed"] += 1
            else:
                raise Exception("bob still exists after delete")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify bob deleted — {e}")
            results["errors"].append(f"Verify bob deleted: {e}")

        # --- 8. List remaining ---
        results["tests_run"] += 1
        try:
            lr2 = await self.client.objects.list_objects(space_id, graph_id, page_size=50)
            remaining = lr2.count if lr2.is_success else -1
            if remaining == 2:
                logger.info(f"✅ PASS: Remaining objects — {remaining}")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected 2, got {remaining}")
        except Exception as e:
            logger.error(f"❌ FAIL: Remaining objects — {e}")
            results["errors"].append(f"Remaining objects: {e}")

        # --- 9. Batch delete ---
        results["tests_run"] += 1
        try:
            dr2 = await self.client.objects.delete_objects_batch(
                space_id, graph_id,
                f"{NS}alice,{NS}charlie"
            )
            if dr2.is_success:
                logger.info(f"✅ PASS: Batch delete (alice, charlie)")
                results["tests_passed"] += 1
            else:
                raise Exception(f"msg={getattr(dr2, 'error_message', dr2)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Batch delete — {e}")
            results["errors"].append(f"Batch delete: {e}")

        # --- 10. Final verification ---
        results["tests_run"] += 1
        try:
            lr3 = await self.client.objects.list_objects(space_id, graph_id, page_size=50)
            remaining = lr3.count if lr3.is_success else -1
            if remaining == 0:
                logger.info(f"✅ PASS: Final verification — 0 objects remaining")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected 0, got {remaining}")
        except Exception as e:
            logger.error(f"❌ FAIL: Final verification — {e}")
            results["errors"].append(f"Final verification: {e}")

        return results
