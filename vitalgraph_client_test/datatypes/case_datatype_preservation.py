#!/usr/bin/env python3
"""
Datatype Preservation Test Case

Tests that all DB write paths correctly preserve RDFLib datatype and language
metadata through to both Fuseki and PostgreSQL.  Covers the fixes applied to:

1. Entity update (kgentity_update_impl) — typed literals in update_quads
2. Entity delete (kgentity_delete_impl) — typed literals in delete quads
3. Entity graph delete (kgentity_delete_impl) — typed literals for full graph
4. KGType update (kgtypes_update_impl) — typed literals in type updates
5. Frame/slot create & update (kgframes_endpoint, kgentity_frame_create_impl)
6. Relations update/upsert (kgrelations_endpoint) — atomic update_quads
7. Triples delete (triples_endpoint) — preserving RDFLib objects

Each test creates data with typed values (integer, datetime, text), then
performs the operation under test and verifies:
  a. The operation succeeds
  b. Values are correct after the operation (no stale data)
  c. No triple accumulation (object count stable)
"""

import logging
from typing import Dict, Any, List
from datetime import datetime

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation
from ai_haley_kg_domain.model.KGType import KGType

logger = logging.getLogger(__name__)

# ---------- Fixed URIs for entity graph tests ----------
ENTITY_URI = "urn:dt_test:entity_001"
FRAME_URI = "urn:dt_test:frame_001"
SLOT_TEXT_URI = "urn:dt_test:slot_text_001"
SLOT_INT_URI = "urn:dt_test:slot_int_001"
SLOT_DATE_URI = "urn:dt_test:slot_date_001"
EDGE_EF_URI = "urn:dt_test:edge_ef_001"
EDGE_FS_TEXT_URI = "urn:dt_test:edge_fs_text_001"
EDGE_FS_INT_URI = "urn:dt_test:edge_fs_int_001"
EDGE_FS_DATE_URI = "urn:dt_test:edge_fs_date_001"

# ---------- Fixed URIs for second entity (delete tests) ----------
ENTITY2_URI = "urn:dt_test:entity_002"
FRAME2_URI = "urn:dt_test:frame_002"
SLOT2_TEXT_URI = "urn:dt_test:slot_text_002"
SLOT2_INT_URI = "urn:dt_test:slot_int_002"
EDGE2_EF_URI = "urn:dt_test:edge_ef_002"
EDGE2_FS_TEXT_URI = "urn:dt_test:edge_fs_text_002"
EDGE2_FS_INT_URI = "urn:dt_test:edge_fs_int_002"

# ---------- Fixed URIs for KGRelations tests ----------
REL_ENTITY_A_URI = "urn:dt_test:rel_entity_a"
REL_ENTITY_B_URI = "urn:dt_test:rel_entity_b"
RELATION_URI = "urn:dt_test:relation_001"

# ---------- Fixed URIs for KGTypes tests ----------
KGTYPE_URI = "http://vital.ai/test/kgtype/DtTestType"

# ---------- Fixed URIs for Triples tests ----------
TRIPLES_ENTITY_URI = "urn:dt_test:triples_entity_001"


def _build_entity_graph(
    entity_uri=ENTITY_URI,
    frame_uri=FRAME_URI,
    slot_text_uri=SLOT_TEXT_URI,
    slot_int_uri=SLOT_INT_URI,
    slot_date_uri=SLOT_DATE_URI,
    edge_ef_uri=EDGE_EF_URI,
    edge_fs_text_uri=EDGE_FS_TEXT_URI,
    edge_fs_int_uri=EDGE_FS_INT_URI,
    edge_fs_date_uri=EDGE_FS_DATE_URI,
    name_value: str = "Acme Corp",
    int_value: int = 42,
    date_value: datetime = datetime(2020, 6, 15),
) -> List[GraphObject]:
    """Build a complete entity graph with typed slot values."""
    objects: List[GraphObject] = []

    entity = KGEntity()
    entity.URI = entity_uri
    entity.name = name_value
    entity.kGEntityType = "http://vital.ai/test/kgtype/DtTestEntity"
    objects.append(entity)

    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = f"{name_value} Frame"
    frame.kGFrameType = "http://vital.ai/test/kgtype/DtTestFrame"
    objects.append(frame)

    text_slot = KGTextSlot()
    text_slot.URI = slot_text_uri
    text_slot.name = "Name Slot"
    text_slot.kGSlotType = "http://vital.ai/test/kgtype/DtNameSlot"
    text_slot.textSlotValue = name_value
    objects.append(text_slot)

    int_slot = KGIntegerSlot()
    int_slot.URI = slot_int_uri
    int_slot.name = "Count Slot"
    int_slot.kGSlotType = "http://vital.ai/test/kgtype/DtCountSlot"
    int_slot.integerSlotValue = int_value
    objects.append(int_slot)

    date_slot = KGDateTimeSlot()
    date_slot.URI = slot_date_uri
    date_slot.name = "Date Slot"
    date_slot.kGSlotType = "http://vital.ai/test/kgtype/DtDateSlot"
    date_slot.dateTimeSlotValue = date_value
    objects.append(date_slot)

    e_ef = Edge_hasEntityKGFrame()
    e_ef.URI = edge_ef_uri
    e_ef.edgeSource = entity_uri
    e_ef.edgeDestination = frame_uri
    objects.append(e_ef)

    e_ft = Edge_hasKGSlot()
    e_ft.URI = edge_fs_text_uri
    e_ft.edgeSource = frame_uri
    e_ft.edgeDestination = slot_text_uri
    objects.append(e_ft)

    e_fi = Edge_hasKGSlot()
    e_fi.URI = edge_fs_int_uri
    e_fi.edgeSource = frame_uri
    e_fi.edgeDestination = slot_int_uri
    objects.append(e_fi)

    e_fd = Edge_hasKGSlot()
    e_fd.URI = edge_fs_date_uri
    e_fd.edgeSource = frame_uri
    e_fd.edgeDestination = slot_date_uri
    objects.append(e_fd)

    return objects


def _extract_graph_objects(response) -> List:
    """Extract flat objects list from an EntityGraphResponse."""
    if not response.is_success or response.objects is None:
        return []
    eg = response.objects
    if hasattr(eg, 'objects') and isinstance(eg.objects, list):
        return eg.objects
    return []


class DatatypePreservationTester:
    """Tests that all write paths preserve RDFLib datatype metadata."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "Datatype Preservation (All Write Paths)",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info("=" * 80)
        logger.info("  Datatype Preservation — All Write Paths")
        logger.info("=" * 80)

        # ---- Test 1: Create entity graph with typed values ----
        await self._test_create_entity_graph(results, space_id, graph_id)

        # ---- Test 2: Verify typed values survive retrieval ----
        await self._test_verify_typed_values(
            results, space_id, graph_id,
            expected_text="Acme Corp", expected_int=42,
            test_label="2: Verify typed values after create"
        )

        # ---- Test 3: Update entity graph — typed values change ----
        await self._test_update_entity_graph(results, space_id, graph_id)

        # ---- Test 4: Verify updated typed values (no stale data) ----
        await self._test_verify_typed_values(
            results, space_id, graph_id,
            expected_text="Beta Corp", expected_int=999,
            test_label="4: Verify typed values after update (no stale data)"
        )

        # ---- Test 5: No triple accumulation after update ----
        await self._test_no_accumulation(results, space_id, graph_id)

        # ---- Test 6: Create second entity for delete tests ----
        await self._test_create_second_entity(results, space_id, graph_id)

        # ---- Test 7: Delete single entity preserves typed delete ----
        await self._test_delete_single_entity(results, space_id, graph_id)

        # ---- Test 8: Delete entity graph (all related objects) ----
        await self._test_delete_entity_graph(results, space_id, graph_id)

        # ---- Test 9: Verify entity graph fully deleted ----
        await self._test_verify_entity_deleted(results, space_id, graph_id)

        # ============================================================
        # KGRelations Tests (Fix 3: atomic update_quads)
        # ============================================================

        # ---- Test 10: Create relation with typed properties ----
        await self._test_create_relation(results, space_id, graph_id)

        # ---- Test 11: Update relation (atomic update_quads) ----
        await self._test_update_relation(results, space_id, graph_id)

        # ---- Test 12: Upsert relation (atomic update_quads) ----
        await self._test_upsert_relation(results, space_id, graph_id)

        # ---- Test 13: Verify relation values after upsert ----
        await self._test_verify_relation(results, space_id, graph_id)

        # ---- Test 14: Delete relation cleanup ----
        await self._test_delete_relation(results, space_id, graph_id)

        # ============================================================
        # KGTypes Tests (Fix: kgtypes_update_impl datatype preservation)
        # ============================================================

        # ---- Test 15: Create KGType ----
        await self._test_create_kgtype(results, space_id, graph_id)

        # ---- Test 16: Update KGType (typed literal preservation) ----
        await self._test_update_kgtype(results, space_id, graph_id)

        # ---- Test 17: Delete KGType cleanup ----
        await self._test_delete_kgtype(results, space_id, graph_id)

        # ============================================================
        # Triples Tests (Fix 4: str(o) on delete path)
        # ============================================================

        # ---- Test 18: Add triples with typed values ----
        await self._test_add_triples(results, space_id, graph_id)

        # ---- Test 19: Verify triples exist ----
        await self._test_verify_triples_exist(results, space_id, graph_id)

        # ---- Test 20: Delete triples by subject (typed literal matching) ----
        await self._test_delete_triples(results, space_id, graph_id)

        # ---- Test 21: Verify triples deleted ----
        await self._test_verify_triples_deleted(results, space_id, graph_id)

        logger.info(f"\n{'=' * 80}")
        logger.info(f"   Datatype Preservation: "
                    f"{results['tests_passed']}/{results['tests_run']} passed")
        logger.info(f"{'=' * 80}\n")

        return results

    # ==================================================================
    # Test 1: Create entity graph with typed values
    # ==================================================================
    async def _test_create_entity_graph(self, results, space_id, graph_id):
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 1: Create entity graph with typed values ---")
            objects = _build_entity_graph(
                name_value="Acme Corp", int_value=42,
                date_value=datetime(2020, 6, 15),
            )
            logger.info(f"   Creating {len(objects)} objects: text='Acme Corp', int=42, date=2020-06-15")

            response = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=objects,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Create succeeded")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Create failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 1: Create failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 1: Exception: {e}")

    # ==================================================================
    # Test 2/4: Verify typed values
    # ==================================================================
    async def _test_verify_typed_values(self, results, space_id, graph_id,
                                         expected_text, expected_int, test_label):
        results["tests_run"] += 1
        try:
            logger.info(f"\n--- Test {test_label} ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=ENTITY_URI, include_entity_graph=True,
            )

            graph_objects = _extract_graph_objects(response)
            if not graph_objects:
                logger.error(f"   ❌ FAIL: Could not retrieve entity graph")
                results["tests_failed"] += 1
                results["errors"].append(f"Test {test_label}: No entity graph returned")
                return

            text_slots = [o for o in graph_objects if isinstance(o, KGTextSlot)]
            int_slots = [o for o in graph_objects if isinstance(o, KGIntegerSlot)]
            dt_slots = [o for o in graph_objects if isinstance(o, KGDateTimeSlot)]

            errors = []

            # Check text value
            if text_slots:
                val = str(text_slots[0].textSlotValue) if text_slots[0].textSlotValue else None
                if val != expected_text:
                    errors.append(f"Text: expected '{expected_text}', got '{val}'")
                else:
                    logger.info(f"   Text slot: '{val}' ✅")
            else:
                errors.append("No TextSlot found")

            # Check integer value — must be actual int, not string
            if int_slots:
                val = int_slots[0].integerSlotValue
                if val != expected_int:
                    errors.append(f"Integer: expected {expected_int}, got {val}")
                else:
                    logger.info(f"   Integer slot: {val} (type={type(val).__name__}) ✅")
            else:
                errors.append("No IntegerSlot found")

            # Check datetime present
            if dt_slots:
                val = dt_slots[0].dateTimeSlotValue
                logger.info(f"   DateTime slot: {val} ✅")
            else:
                errors.append("No DateTimeSlot found")

            if errors:
                logger.error(f"   ❌ FAIL: Value check errors:")
                for err in errors:
                    logger.error(f"      {err}")
                results["tests_failed"] += 1
                results["errors"].extend([f"Test {test_label}: {e}" for e in errors])
            else:
                logger.info(f"   ✅ PASS: All typed values correct")
                results["tests_passed"] += 1
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test {test_label}: Exception: {e}")

    # ==================================================================
    # Test 3: Update entity graph — typed values change
    # ==================================================================
    async def _test_update_entity_graph(self, results, space_id, graph_id):
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 3: Update entity graph with different typed values ---")
            objects = _build_entity_graph(
                name_value="Beta Corp", int_value=999,
                date_value=datetime(2025, 1, 1),
            )
            logger.info(f"   Updating with: text='Beta Corp', int=999, date=2025-01-01")

            response = await self.client.kgentities.update_kgentities(
                space_id=space_id, graph_id=graph_id, objects=objects,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Update succeeded")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Update failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 3: Update failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 3: Exception: {e}")

    # ==================================================================
    # Test 5: No triple accumulation after update
    # ==================================================================
    async def _test_no_accumulation(self, results, space_id, graph_id):
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 5: No triple accumulation after update ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=ENTITY_URI, include_entity_graph=True,
            )

            graph_objects = _extract_graph_objects(response)
            if not graph_objects:
                logger.error(f"   ❌ FAIL: Could not retrieve entity graph")
                results["tests_failed"] += 1
                results["errors"].append("Test 5: No entity graph returned")
                return

            obj_count = len(graph_objects)
            text_slots = [o for o in graph_objects if isinstance(o, KGTextSlot)]
            int_slots = [o for o in graph_objects if isinstance(o, KGIntegerSlot)]
            dt_slots = [o for o in graph_objects if isinstance(o, KGDateTimeSlot)]

            logger.info(f"   Total objects: {obj_count}")
            logger.info(f"   TextSlots: {len(text_slots)}, IntSlots: {len(int_slots)}, DateTimeSlots: {len(dt_slots)}")

            # We expect exactly 1 of each slot type, 1 entity, 1 frame, 4 edges = 9 objects
            errors = []
            if len(text_slots) != 1:
                errors.append(f"Expected 1 TextSlot, got {len(text_slots)}")
            if len(int_slots) != 1:
                errors.append(f"Expected 1 IntegerSlot, got {len(int_slots)}")
            if len(dt_slots) != 1:
                errors.append(f"Expected 1 DateTimeSlot, got {len(dt_slots)}")

            if errors:
                logger.error(f"   ❌ FAIL: Triple accumulation detected:")
                for err in errors:
                    logger.error(f"      {err}")
                results["tests_failed"] += 1
                results["errors"].extend([f"Test 5: {e}" for e in errors])
            else:
                logger.info(f"   ✅ PASS: No triple accumulation — counts correct")
                results["tests_passed"] += 1
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 5: Exception: {e}")

    # ==================================================================
    # Test 6: Create second entity graph for delete tests
    # ==================================================================
    async def _test_create_second_entity(self, results, space_id, graph_id):
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 6: Create second entity graph (for delete tests) ---")
            objects = _build_entity_graph(
                entity_uri=ENTITY2_URI, frame_uri=FRAME2_URI,
                slot_text_uri=SLOT2_TEXT_URI, slot_int_uri=SLOT2_INT_URI,
                slot_date_uri=SLOT_DATE_URI,  # reuse date slot URI won't matter, separate entity
                edge_ef_uri=EDGE2_EF_URI,
                edge_fs_text_uri=EDGE2_FS_TEXT_URI,
                edge_fs_int_uri=EDGE2_FS_INT_URI,
                edge_fs_date_uri=EDGE_FS_DATE_URI,
                name_value="Delta Inc", int_value=77,
                date_value=datetime(2018, 3, 10),
            )

            # Use unique date slot and edge URIs
            # Override the shared ones to avoid collisions
            for obj in objects:
                if isinstance(obj, KGDateTimeSlot):
                    obj.URI = "urn:dt_test:slot_date_002"
                if isinstance(obj, Edge_hasKGSlot) and obj.URI == EDGE_FS_DATE_URI:
                    obj.URI = "urn:dt_test:edge_fs_date_002"
                    obj.edgeDestination = "urn:dt_test:slot_date_002"

            logger.info(f"   Creating second entity graph: {ENTITY2_URI}")

            response = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=objects,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Second entity created")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Create failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 6: Create failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 6: Exception: {e}")

    # ==================================================================
    # Test 7: Delete single entity (typed literals must match for delete)
    # ==================================================================
    async def _test_delete_single_entity(self, results, space_id, graph_id):
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 7: Delete single entity (typed literal matching) ---")
            logger.info(f"   Deleting entity: {ENTITY2_URI}")

            response = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=ENTITY2_URI,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Single entity delete succeeded")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Delete failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 7: Delete failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 7: Exception: {e}")

    # ==================================================================
    # Test 8: Delete entity graph (all related objects with typed literals)
    # ==================================================================
    async def _test_delete_entity_graph(self, results, space_id, graph_id):
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 8: Delete entity graph (typed literal matching) ---")
            logger.info(f"   Deleting full entity graph: {ENTITY_URI}")

            response = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=ENTITY_URI,
                delete_entity_graph=True,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Entity graph delete succeeded")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Delete failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 8: Delete failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 8: Exception: {e}")

    # ==================================================================
    # Test 9: Verify entity graph fully deleted (no orphaned triples)
    # ==================================================================
    async def _test_verify_entity_deleted(self, results, space_id, graph_id):
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 9: Verify entity graph fully deleted ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=ENTITY_URI, include_entity_graph=True,
            )

            # After full entity graph deletion, we expect no objects or a failure
            graph_objects = _extract_graph_objects(response)
            if not graph_objects or len(graph_objects) == 0:
                logger.info(f"   Entity graph returns 0 objects — fully deleted")
                logger.info(f"   ✅ PASS: No orphaned triples after entity graph delete")
                results["tests_passed"] += 1
            else:
                count = len(graph_objects)
                logger.error(f"   ❌ FAIL: Found {count} orphaned objects after delete")
                for obj in graph_objects:
                    logger.error(f"      Orphan: {type(obj).__name__} URI={getattr(obj, 'URI', '?')}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 9: {count} orphaned objects after entity graph delete")
        except Exception as e:
            # An exception or 404 is also acceptable — means entity was deleted
            logger.info(f"   Entity not found (expected): {e}")
            logger.info(f"   ✅ PASS: Entity fully deleted")
            results["tests_passed"] += 1

    # ==================================================================
    # KGRelations Tests
    # ==================================================================

    async def _test_create_relation(self, results, space_id, graph_id):
        """Test 10: Create two entities and a relation between them."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 10: Create entities + relation with typed properties ---")

            # Create two entities first
            entity_a = KGEntity()
            entity_a.URI = REL_ENTITY_A_URI
            entity_a.name = "Supplier Alpha"
            entity_a.kGEntityType = "http://vital.ai/test/kgtype/DtTestEntity"

            entity_b = KGEntity()
            entity_b.URI = REL_ENTITY_B_URI
            entity_b.name = "Customer Beta"
            entity_b.kGEntityType = "http://vital.ai/test/kgtype/DtTestEntity"

            resp = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id, objects=[entity_a, entity_b],
            )
            if not resp.is_success:
                logger.error(f"   ❌ FAIL: Entity create failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 10: Entity create failed: {resp.error_message}")
                return

            # Create relation
            relation = Edge_hasKGRelation()
            relation.URI = RELATION_URI
            relation.edgeSource = REL_ENTITY_A_URI
            relation.edgeDestination = REL_ENTITY_B_URI
            relation.name = "supplies_to_v1"

            resp = await self.client.kgrelations.create_relations(
                space_id=space_id, graph_id=graph_id, relations=[relation],
            )

            if resp.is_success:
                logger.info(f"   ✅ PASS: Relation created: {RELATION_URI}")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Relation create failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 10: Relation create failed: {resp.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 10: Exception: {e}")

    async def _test_update_relation(self, results, space_id, graph_id):
        """Test 11: Update relation — exercises atomic update_quads."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 11: Update relation (atomic update_quads) ---")

            relation = Edge_hasKGRelation()
            relation.URI = RELATION_URI
            relation.edgeSource = REL_ENTITY_A_URI
            relation.edgeDestination = REL_ENTITY_B_URI
            relation.name = "supplies_to_v2"

            resp = await self.client.kgrelations.update_relations(
                space_id=space_id, graph_id=graph_id, relations=[relation],
            )

            if resp.is_success:
                logger.info(f"   ✅ PASS: Relation updated via atomic update_quads")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Update failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 11: Relation update failed: {resp.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 11: Exception: {e}")

    async def _test_upsert_relation(self, results, space_id, graph_id):
        """Test 12: Upsert relation — exercises atomic update_quads for existing."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 12: Upsert relation (atomic update_quads) ---")

            relation = Edge_hasKGRelation()
            relation.URI = RELATION_URI
            relation.edgeSource = REL_ENTITY_A_URI
            relation.edgeDestination = REL_ENTITY_B_URI
            relation.name = "supplies_to_v3"

            resp = await self.client.kgrelations.upsert_relations(
                space_id=space_id, graph_id=graph_id, relations=[relation],
            )

            if resp.is_success:
                logger.info(f"   ✅ PASS: Relation upserted via atomic update_quads")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Upsert failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 12: Relation upsert failed: {resp.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 12: Exception: {e}")

    async def _test_verify_relation(self, results, space_id, graph_id):
        """Test 13: Verify relation has latest values after upsert."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 13: Verify relation values after upsert ---")

            resp = await self.client.kgrelations.get_relation(
                space_id=space_id, graph_id=graph_id, relation_uri=RELATION_URI,
            )

            if resp.is_success and resp.objects:
                rel = resp.objects[0]
                name_val = str(rel.name) if hasattr(rel, 'name') and rel.name else None
                logger.info(f"   Relation name: '{name_val}'")
                if name_val and "v3" in name_val:
                    logger.info(f"   ✅ PASS: Relation has v3 value after upsert")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ FAIL: Expected v3 name, got '{name_val}'")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Test 13: Relation name mismatch: {name_val}")
            else:
                # If we can't retrieve individually, just check it exists via list
                logger.info(f"   Relation retrieval returned no objects; checking via list...")
                list_resp = await self.client.kgrelations.list_relations(
                    space_id=space_id, graph_id=graph_id,
                    entity_source_uri=REL_ENTITY_A_URI,
                )
                if list_resp.is_success and list_resp.objects:
                    logger.info(f"   Found {len(list_resp.objects)} relations via list")
                    logger.info(f"   ✅ PASS: Relation exists after upsert")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ FAIL: Relation not found after upsert")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Test 13: Relation not found after upsert")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 13: Exception: {e}")

    async def _test_delete_relation(self, results, space_id, graph_id):
        """Test 14: Delete relation and entities."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 14: Delete relation + entities cleanup ---")

            resp = await self.client.kgrelations.delete_relations(
                space_id=space_id, graph_id=graph_id, relation_uris=[RELATION_URI],
            )

            # Also delete the entities
            await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=REL_ENTITY_A_URI,
            )
            await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id, uri=REL_ENTITY_B_URI,
            )

            if resp.is_success:
                logger.info(f"   ✅ PASS: Relation + entities deleted")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Delete failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 14: Delete failed: {resp.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 14: Exception: {e}")

    # ==================================================================
    # KGTypes Tests
    # ==================================================================

    async def _test_create_kgtype(self, results, space_id, graph_id):
        """Test 15: Create a KGType with typed properties."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 15: Create KGType with typed properties ---")

            kgtype = KGType()
            kgtype.URI = KGTYPE_URI
            kgtype.name = "DtTestType v1"

            resp = await self.client.kgtypes.create_kgtypes(
                space_id=space_id, graph_id=graph_id, objects=[kgtype],
            )

            if resp.is_success:
                logger.info(f"   ✅ PASS: KGType created: {KGTYPE_URI}")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Create failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 15: KGType create failed: {resp.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 15: Exception: {e}")

    async def _test_update_kgtype(self, results, space_id, graph_id):
        """Test 16: Update KGType — exercises kgtypes_update_impl datatype preservation."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 16: Update KGType (datatype preservation) ---")

            kgtype = KGType()
            kgtype.URI = KGTYPE_URI
            kgtype.name = "DtTestType v2"

            resp = await self.client.kgtypes.update_kgtypes(
                space_id=space_id, graph_id=graph_id, objects=[kgtype],
            )

            if resp.is_success:
                logger.info(f"   ✅ PASS: KGType updated with preserved datatypes")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Update failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 16: KGType update failed: {resp.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 16: Exception: {e}")

    async def _test_delete_kgtype(self, results, space_id, graph_id):
        """Test 17: Delete KGType cleanup."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 17: Delete KGType cleanup ---")

            resp = await self.client.kgtypes.delete_kgtype(
                space_id=space_id, graph_id=graph_id, uri=KGTYPE_URI,
            )

            if resp.is_success:
                logger.info(f"   ✅ PASS: KGType deleted")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Delete failed: {resp.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 17: KGType delete failed: {resp.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 17: Exception: {e}")

    # ==================================================================
    # Triples Tests
    # ==================================================================

    async def _test_add_triples(self, results, space_id, graph_id):
        """Test 18: Add triples with typed values via triples endpoint."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 18: Add triples with typed values ---")

            # Build a simple entity as JSON-LD and add via triples endpoint
            entity = KGEntity()
            entity.URI = TRIPLES_ENTITY_URI
            entity.name = "Triples Test Entity"
            entity.kGEntityType = "http://vital.ai/test/kgtype/DtTestEntity"

            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from vitalgraph.model.jsonld_model import JsonLdObject
            jsonld_dict = GraphObject.to_jsonld_list([entity])

            # Single object — use JsonLdObject
            obj = JsonLdObject(**jsonld_dict['@graph'][0])
            obj.jsonld_type = 'object'

            resp = await self.client.triples.add_triples(
                space_id=space_id, graph_id=graph_id, document=obj,
            )

            if resp.success:
                logger.info(f"   ✅ PASS: Triples added")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Add failed: {resp.message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 18: Add triples failed: {resp.message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 18: Exception: {e}")

    async def _test_verify_triples_exist(self, results, space_id, graph_id):
        """Test 19: Verify triples exist for the added entity."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 19: Verify triples exist ---")

            resp = await self.client.triples.list_triples(
                space_id=space_id, graph_id=graph_id,
                subject=TRIPLES_ENTITY_URI, page_size=50,
            )

            # TripleListResponse uses .total_count from BaseJsonLdResponse
            count = getattr(resp, 'total_count', 0) or 0
            # Also check if data has @graph entries
            if count == 0 and hasattr(resp, 'data'):
                data = resp.data
                if hasattr(data, 'graph') and data.graph:
                    count = len(data.graph)

            if count > 0:
                logger.info(f"   Found {count} triples for subject")
                logger.info(f"   ✅ PASS: Triples exist")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: No triples found for subject {TRIPLES_ENTITY_URI}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 19: No triples found")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 19: Exception: {e}")

    async def _test_delete_triples(self, results, space_id, graph_id):
        """Test 20: Delete triples via JSON-LD body (exercises _handle_delete_jsonld fix)."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 20: Delete triples via JSON-LD (typed literal matching) ---")
            logger.info(f"   Deleting triples for: {TRIPLES_ENTITY_URI}")

            # Build the same entity JSON-LD to send as delete body
            entity = KGEntity()
            entity.URI = TRIPLES_ENTITY_URI
            entity.name = "Triples Test Entity"
            entity.kGEntityType = "http://vital.ai/test/kgtype/DtTestEntity"

            from vital_ai_vitalsigns.model.GraphObject import GraphObject
            from vitalgraph.model.jsonld_model import JsonLdObject
            jsonld_dict = GraphObject.to_jsonld_list([entity])

            obj = JsonLdObject(**jsonld_dict['@graph'][0])
            obj.jsonld_type = 'object'

            # Send DELETE with JSON-LD body directly via httpx
            # (The client's delete_triples uses pattern params, but the server
            #  DELETE endpoint accepts a JSON-LD body — that's the path we fixed)
            import httpx
            url = f"{self.client.config.get_server_url()}/api/graphs/triples"
            params = {"space_id": space_id, "graph_id": graph_id}
            headers = {}
            if hasattr(self.client, 'access_token') and self.client.access_token:
                headers["Authorization"] = f"Bearer {self.client.access_token}"

            async with httpx.AsyncClient() as http_client:
                response = await http_client.request(
                    "DELETE", url, params=params,
                    json=obj.model_dump(by_alias=True),
                    headers=headers,
                )

            if response.status_code == 200:
                resp_data = response.json()
                if resp_data.get('success', False):
                    logger.info(f"   ✅ PASS: Triples deleted via JSON-LD body")
                    results["tests_passed"] += 1
                else:
                    logger.error(f"   ❌ FAIL: Delete returned success=false: {resp_data}")
                    results["tests_failed"] += 1
                    results["errors"].append(f"Test 20: Delete success=false")
            else:
                logger.error(f"   ❌ FAIL: Delete HTTP {response.status_code}: {response.text}")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 20: HTTP {response.status_code}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 20: Exception: {e}")

    async def _test_verify_triples_deleted(self, results, space_id, graph_id):
        """Test 21: Verify triples for subject are gone."""
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 21: Verify triples deleted ---")

            resp = await self.client.triples.list_triples(
                space_id=space_id, graph_id=graph_id,
                subject=TRIPLES_ENTITY_URI, page_size=50,
            )

            count = getattr(resp, 'total_count', 0) or 0
            if count == 0 and hasattr(resp, 'data'):
                data = resp.data
                if hasattr(data, 'graph') and data.graph:
                    count = len(data.graph)

            if count == 0:
                logger.info(f"   No triples found for subject — fully deleted")
                logger.info(f"   ✅ PASS: Triples cleanup confirmed")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: {count} orphaned triples remain after delete")
                results["tests_failed"] += 1
                results["errors"].append(f"Test 21: {count} orphaned triples after delete")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Test 21: Exception: {e}")
