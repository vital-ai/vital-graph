"""
KGEntities CRUD Test Case — SPARQL-SQL Backend

Tests KGEntity lifecycle: create, list, get, update, delete, batch delete.
Uses programmatically created KGEntity objects (no lead data dependency).
"""

import logging
from typing import Dict, Any

from ai_haley_kg_domain.model.KGEntity import KGEntity

logger = logging.getLogger(__name__)

NS = "http://example.org/sqlentity/"


def _make_entity(uri: str, name: str) -> KGEntity:
    """Create a KGEntity with the given URI and name."""
    e = KGEntity()
    e.URI = uri
    e.name = name
    return e


class KGEntitiesCrudTester:
    """Client-based test for KGEntities CRUD against sparql_sql backend."""

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

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "KGEntities CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  KGEntities CRUD")
        logger.info(f"{'=' * 80}")

        e1 = _make_entity(f"{NS}entity_alpha", "Alpha Entity")
        e2 = _make_entity(f"{NS}entity_beta", "Beta Entity")
        e3 = _make_entity(f"{NS}entity_gamma", "Gamma Entity")

        # --- 1. Create KGEntities (individually to avoid batch kGGraphURI grouping) ---
        results["tests_run"] += 1
        try:
            total_created = 0
            for ent in [e1, e2, e3]:
                cr = await self.client.kgentities.create_kgentities(
                    space_id=space_id, graph_id=graph_id,
                    objects=[ent])
                total_created += cr.created_count if cr.is_success else 0
            if total_created == 3:
                self._pass(results, f"Create 3 KGEntities — created_count={total_created}")
            else:
                raise Exception(f"created_count={total_created}")
        except Exception as e:
            self._fail(results, "Create KGEntities", e)
            return results  # can't continue

        # --- 2. List KGEntities ---
        results["tests_run"] += 1
        try:
            lr = await self.client.kgentities.list_kgentities(
                space_id=space_id, graph_id=graph_id, page_size=50)
            if lr.is_success and len(lr.objects) >= 3:
                self._pass(results, f"List KGEntities — count={len(lr.objects)}")
            else:
                obj_count = len(lr.objects) if lr.is_success and lr.objects else 0
                raise Exception(
                    f"count={obj_count}, msg={getattr(lr, 'error_message', lr)}")
        except Exception as e:
            self._fail(results, "List KGEntities", e)

        # --- 3. Get KGEntity by URI ---
        results["tests_run"] += 1
        try:
            gr = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}entity_alpha")
            if gr.is_success and gr.objects:
                got_name = None
                for obj in gr.objects:
                    if hasattr(obj, 'name') and obj.name:
                        got_name = str(obj.name)
                        break
                self._pass(results, f"Get KGEntity — name={got_name}")
            else:
                raise Exception(f"msg={getattr(gr, 'error_message', gr)}")
        except Exception as e:
            self._fail(results, "Get KGEntity", e)

        # --- 4. Update KGEntity ---
        results["tests_run"] += 1
        try:
            e1_updated = _make_entity(f"{NS}entity_alpha", "Alpha Entity Updated")
            ur = await self.client.kgentities.update_kgentities(
                space_id=space_id, graph_id=graph_id,
                objects=[e1_updated])
            # Log all fields from client response
            for attr in ['is_success', 'message', 'updated_uri', 'error_message',
                         'error_code', 'status_code']:
                logger.info(f"  Update resp.{attr} = {getattr(ur, attr, 'N/A')}")
            # Also dump any extra fields
            if hasattr(ur, 'model_dump'):
                logger.info(f"  Update full response: {ur.model_dump()}")
            if ur.is_success:
                self._pass(results, "Update KGEntity")
            else:
                raise Exception(f"msg={getattr(ur, 'error_message', ur)}")
        except Exception as e:
            self._fail(results, "Update KGEntity", e)

        # --- 5. Verify update ---
        results["tests_run"] += 1
        try:
            gr2 = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}entity_alpha")
            if gr2.is_success and gr2.objects:
                got_name = None
                for obj in gr2.objects:
                    if hasattr(obj, 'name') and obj.name:
                        got_name = str(obj.name)
                        break
                if got_name == "Alpha Entity Updated":
                    self._pass(results, f"Verify update — name={got_name}")
                else:
                    raise Exception(f"expected 'Alpha Entity Updated', got '{got_name}'")
            else:
                raise Exception(f"msg={getattr(gr2, 'error_message', gr2)}")
        except Exception as e:
            self._fail(results, "Verify update", e)

        # --- 6. Delete single KGEntity ---
        results["tests_run"] += 1
        try:
            dr = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}entity_beta")
            if dr.is_success:
                self._pass(results, "Delete KGEntity (entity_beta)")
            else:
                raise Exception(f"msg={getattr(dr, 'error_message', dr)}")
        except Exception as e:
            self._fail(results, "Delete KGEntity", e)

        # --- 7. Verify entity_beta deleted ---
        results["tests_run"] += 1
        try:
            gr3 = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=f"{NS}entity_beta")
            if not gr3.is_success or not gr3.objects or len(gr3.objects) == 0:
                self._pass(results, "Verify entity_beta deleted")
            else:
                raise Exception("entity_beta still exists after delete")
        except Exception as e:
            # A client error (404) also means it's deleted
            err_str = str(e)
            if "404" in err_str or "not found" in err_str.lower():
                self._pass(results, "Verify entity_beta deleted (404)")
            else:
                self._fail(results, "Verify entity_beta deleted", e)

        # --- 8. List remaining ---
        results["tests_run"] += 1
        try:
            lr2 = await self.client.kgentities.list_kgentities(
                space_id=space_id, graph_id=graph_id, page_size=50)
            remaining = len(lr2.objects) if lr2.is_success and lr2.objects else 0
            if remaining == 2:
                self._pass(results, f"Remaining KGEntities — {remaining}")
            else:
                raise Exception(f"expected 2, got {remaining}")
        except Exception as e:
            self._fail(results, "Remaining KGEntities", e)

        # --- 9. Batch delete ---
        results["tests_run"] += 1
        try:
            dr2 = await self.client.kgentities.delete_kgentities_batch(
                space_id=space_id, graph_id=graph_id,
                uri_list=[f"{NS}entity_alpha", f"{NS}entity_gamma"])
            if dr2.is_success:
                self._pass(results, f"Batch delete — deleted_count={getattr(dr2, 'deleted_count', '?')}")
            else:
                raise Exception(f"msg={getattr(dr2, 'error_message', dr2)}")
        except Exception as e:
            self._fail(results, "Batch delete", e)

        # --- 10. Final verification ---
        results["tests_run"] += 1
        try:
            lr3 = await self.client.kgentities.list_kgentities(
                space_id=space_id, graph_id=graph_id, page_size=50)
            remaining = len(lr3.objects) if lr3.is_success and lr3.objects else 0
            if remaining == 0:
                self._pass(results, "Final verification — 0 KGEntities remaining")
            else:
                raise Exception(f"expected 0, got {remaining}")
        except Exception as e:
            self._fail(results, "Final verification", e)

        results["tests_failed"] = results["tests_run"] - results["tests_passed"]
        return results
