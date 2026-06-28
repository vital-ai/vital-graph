"""
KGTypes CRUD Test Case — SPARQL-SQL Backend

Tests KGType lifecycle: create, list, get, update, delete via the KGTypes endpoint.
Uses KGType and its subclasses (KGEntityType, KGFrameType) as test data.
"""

import logging
from typing import Dict, Any, List

from ai_haley_kg_domain.model.KGType import KGType
from ai_haley_kg_domain.model.KGEntityType import KGEntityType
from ai_haley_kg_domain.model.KGFrameType import KGFrameType

logger = logging.getLogger(__name__)

NS = "http://example.org/sqlkgtype/"


def _make_kgtype(uri: str, name: str, description: str,
                 version: str = "1.0", cls=KGType):
    """Create a KGType (or subclass) with the given properties."""
    t = cls()
    t.URI = uri
    t.name = name
    t.kGraphDescription = description
    t.kGTypeVersion = version
    t.kGModelVersion = "2024.1"
    return t


class KGTypesCrudTester:
    """Client-based test for KGTypes CRUD against sparql_sql backend."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "KGTypes CRUD",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  KGTypes CRUD")
        logger.info(f"{'=' * 80}")

        # Build test types
        type_person = _make_kgtype(f"{NS}Person", "Person",
                                   "Represents a person entity")
        type_org = _make_kgtype(f"{NS}Organization", "Organization",
                                "Represents an organization",
                                cls=KGEntityType)
        type_addr = _make_kgtype(f"{NS}AddressFrame", "AddressFrame",
                                 "Frame type for addresses",
                                 cls=KGFrameType)

        # --- 1. Create KGTypes ---
        results["tests_run"] += 1
        try:
            cr = await self.client.kgtypes.create_kgtypes(
                space_id, graph_id, [type_person, type_org, type_addr])
            if cr.is_success and cr.created_count == 3:
                logger.info("✅ PASS: Create 3 KGTypes")
                results["tests_passed"] += 1
            else:
                raise Exception(
                    f"created_count={getattr(cr, 'created_count', '?')}, "
                    f"msg={getattr(cr, 'error_message', cr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Create KGTypes — {e}")
            results["errors"].append(f"Create KGTypes: {e}")
            return results  # can't continue

        # --- 2. List KGTypes ---
        results["tests_run"] += 1
        try:
            lr = await self.client.kgtypes.list_kgtypes(
                space_id, graph_id, page_size=50)
            if lr.is_success and lr.count >= 3:
                logger.info(f"✅ PASS: List KGTypes — count={lr.count}")
                results["tests_passed"] += 1
            else:
                raise Exception(
                    f"count={getattr(lr, 'count', '?')}, "
                    f"msg={getattr(lr, 'error_message', lr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: List KGTypes — {e}")
            results["errors"].append(f"List KGTypes: {e}")

        # --- 3. Get KGType by URI ---
        results["tests_run"] += 1
        try:
            gr = await self.client.kgtypes.get_kgtype(
                space_id, graph_id, f"{NS}Person")
            if gr.is_success and gr.type is not None:
                got_name = str(gr.type.name) if hasattr(gr.type, 'name') else None
                logger.info(f"✅ PASS: Get KGType — name={got_name}")
                results["tests_passed"] += 1
            else:
                raise Exception(
                    f"msg={getattr(gr, 'error_message', gr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Get KGType — {e}")
            results["errors"].append(f"Get KGType: {e}")

        # --- 4. Update KGType ---
        results["tests_run"] += 1
        try:
            type_person_updated = _make_kgtype(
                f"{NS}Person", "Person Updated",
                "Updated person type", version="2.0")
            ur = await self.client.kgtypes.update_kgtypes(
                space_id, graph_id, [type_person_updated])
            if ur.is_success:
                logger.info("✅ PASS: Update KGType")
                results["tests_passed"] += 1
            else:
                raise Exception(
                    f"msg={getattr(ur, 'error_message', ur)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Update KGType — {e}")
            results["errors"].append(f"Update KGType: {e}")

        # --- 5. Verify update ---
        results["tests_run"] += 1
        try:
            gr2 = await self.client.kgtypes.get_kgtype(
                space_id, graph_id, f"{NS}Person")
            if gr2.is_success and gr2.type is not None:
                got_name = str(gr2.type.name) if hasattr(gr2.type, 'name') else None
                if got_name == "Person Updated":
                    logger.info(f"✅ PASS: Verify update — name={got_name}")
                    results["tests_passed"] += 1
                else:
                    raise Exception(
                        f"expected 'Person Updated', got '{got_name}'")
            else:
                raise Exception(
                    f"msg={getattr(gr2, 'error_message', gr2)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify update — {e}")
            results["errors"].append(f"Verify update: {e}")

        # --- 6. Delete single KGType ---
        results["tests_run"] += 1
        try:
            dr = await self.client.kgtypes.delete_kgtype(
                space_id, graph_id, f"{NS}Organization")
            if dr.is_success:
                logger.info("✅ PASS: Delete KGType (Organization)")
                results["tests_passed"] += 1
            else:
                raise Exception(
                    f"msg={getattr(dr, 'error_message', dr)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Delete KGType — {e}")
            results["errors"].append(f"Delete KGType: {e}")

        # --- 7. Verify Organization deleted ---
        results["tests_run"] += 1
        try:
            gr3 = await self.client.kgtypes.get_kgtype(
                space_id, graph_id, f"{NS}Organization")
            if not gr3.is_success or gr3.type is None:
                logger.info("✅ PASS: Verify Organization deleted")
                results["tests_passed"] += 1
            else:
                raise Exception("Organization still exists after delete")
        except Exception as e:
            logger.error(f"❌ FAIL: Verify Organization deleted — {e}")
            results["errors"].append(f"Verify Organization deleted: {e}")

        # --- 8. List remaining ---
        results["tests_run"] += 1
        try:
            lr2 = await self.client.kgtypes.list_kgtypes(
                space_id, graph_id, page_size=50)
            remaining = lr2.count if lr2.is_success else -1
            if remaining == 2:
                logger.info(f"✅ PASS: Remaining KGTypes — {remaining}")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected 2, got {remaining}")
        except Exception as e:
            logger.error(f"❌ FAIL: Remaining KGTypes — {e}")
            results["errors"].append(f"Remaining KGTypes: {e}")

        # --- 9. Batch delete ---
        results["tests_run"] += 1
        try:
            dr2 = await self.client.kgtypes.delete_kgtypes_batch(
                space_id, graph_id,
                f"{NS}Person,{NS}AddressFrame")
            if dr2.is_success:
                logger.info("✅ PASS: Batch delete (Person, AddressFrame)")
                results["tests_passed"] += 1
            else:
                raise Exception(
                    f"msg={getattr(dr2, 'error_message', dr2)}")
        except Exception as e:
            logger.error(f"❌ FAIL: Batch delete — {e}")
            results["errors"].append(f"Batch delete: {e}")

        # --- 10. Final verification ---
        results["tests_run"] += 1
        try:
            lr3 = await self.client.kgtypes.list_kgtypes(
                space_id, graph_id, page_size=50)
            remaining = lr3.count if lr3.is_success else -1
            if remaining == 0:
                logger.info("✅ PASS: Final verification — 0 KGTypes remaining")
                results["tests_passed"] += 1
            else:
                raise Exception(f"expected 0, got {remaining}")
        except Exception as e:
            logger.error(f"❌ FAIL: Final verification — {e}")
            results["errors"].append(f"Final verification: {e}")

        return results
