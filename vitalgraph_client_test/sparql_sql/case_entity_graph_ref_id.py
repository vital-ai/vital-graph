"""
Entity Graph Reference ID Regression Test — SPARQL-SQL Backend

Regression test for the include_entity_graph + reference_id duplication bug.

When an entity has hasKGGraphURI pointing to itself (the grouping pattern),
the UNION query that retrieves the full entity graph used to return the
entity's triples twice — once from each branch. This caused multi-valued
properties like hasReferenceIdentifier to be accumulated into a list
(e.g. "['EVENT-0005', 'EVENT-0005']") instead of the correct single value.

Tests:
  1. Create entity with reference ID, frame, and slots
  2. Get entity by reference_id (no entity graph) — verify clean ref ID
  3. Get entity by reference_id (with entity graph) — verify clean ref ID
  4. Get entity by URI (with entity graph) — verify clean ref ID
  5. Verify quad count is correct (no duplicates)
  6. Cleanup
"""

import logging
import uuid
from typing import Dict, Any, Optional

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

logger = logging.getLogger(__name__)

NS = "http://example.org/refid_test/"
REF_ID = "REFID-TEST-001"


def _uid() -> str:
    return str(uuid.uuid4())[:8]


def _make_entity_with_frame(ref_id: str):
    """Create an entity with a reference ID, one frame, and two slots."""
    entity_uri = f"{NS}entity_{_uid()}"
    frame_uri = f"{NS}frame_{_uid()}"
    slot1_uri = f"{NS}slot1_{_uid()}"
    slot2_uri = f"{NS}slot2_{_uid()}"

    entity = KGEntity()
    entity.URI = entity_uri
    entity.name = "RefID Test Entity"
    entity.referenceIdentifier = ref_id

    frame = KGFrame()
    frame.URI = frame_uri
    frame.name = "Test Frame"

    slot1 = KGTextSlot()
    slot1.URI = slot1_uri
    slot1.name = "Slot Alpha"
    slot1.textSlotValue = "alpha_value"

    slot2 = KGTextSlot()
    slot2.URI = slot2_uri
    slot2.name = "Slot Beta"
    slot2.textSlotValue = "beta_value"

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = f"{NS}edge_ef_{_uid()}"
    edge_ef.edgeSource = entity_uri
    edge_ef.edgeDestination = frame_uri

    edge_fs1 = Edge_hasKGSlot()
    edge_fs1.URI = f"{NS}edge_fs1_{_uid()}"
    edge_fs1.edgeSource = frame_uri
    edge_fs1.edgeDestination = slot1_uri

    edge_fs2 = Edge_hasKGSlot()
    edge_fs2.URI = f"{NS}edge_fs2_{_uid()}"
    edge_fs2.edgeSource = frame_uri
    edge_fs2.edgeDestination = slot2_uri

    return {
        "entity_uri": entity_uri,
        "objects": [entity, frame, slot1, slot2, edge_ef, edge_fs1, edge_fs2],
    }


def _extract_ref_id(objects) -> Optional[str]:
    """Extract referenceIdentifier from the KGEntity in a list of objects."""
    for obj in objects:
        if isinstance(obj, KGEntity) and hasattr(obj, 'referenceIdentifier'):
            val = obj.referenceIdentifier
            if val is not None:
                return str(val)
    return None


class EntityGraphRefIdTester:
    """Regression test for include_entity_graph reference ID duplication bug."""

    def __init__(self, client):
        self.client = client

    def _pass(self, results, label):
        logger.info(f"✅ PASS: {label}")
        results["tests_passed"] += 1

    def _fail(self, results, label, err):
        logger.error(f"❌ FAIL: {label} — {err}")
        results["errors"].append(f"{label}: {err}")
        results["tests_failed"] += 1

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        results = {
            "test_name": "Entity Graph Reference ID Regression",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info(f"\n{'=' * 80}")
        logger.info(f"  Entity Graph Reference ID Regression")
        logger.info(f"{'=' * 80}")

        data = _make_entity_with_frame(REF_ID)
        entity_uri = data["entity_uri"]

        # --- 1. Create entity with frame, slots, and reference ID ---
        results["tests_run"] += 1
        try:
            cr = await self.client.kgentities.create_kgentities(
                space_id=space_id, graph_id=graph_id,
                objects=data["objects"])
            if cr.is_success and cr.created_count >= 1:
                self._pass(results, f"Create entity with frame — created_count={cr.created_count}")
            else:
                raise Exception(f"created_count={getattr(cr, 'created_count', 0)}, msg={getattr(cr, 'error_message', cr)}")
        except Exception as e:
            self._fail(results, "Create entity with frame", e)
            return results  # can't continue

        # --- 2. Get by reference_id WITHOUT entity graph ---
        results["tests_run"] += 1
        try:
            resp = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                reference_id=REF_ID, include_entity_graph=False)
            if not resp.is_success or not resp.objects:
                raise Exception(f"Retrieval failed: {getattr(resp, 'error_message', resp)}")
            got_ref = _extract_ref_id(resp.objects)
            if got_ref == REF_ID:
                self._pass(results, f"Get by ref_id (no graph) — referenceIdentifier={got_ref!r}")
            else:
                raise Exception(f"expected {REF_ID!r}, got {got_ref!r}")
        except Exception as e:
            self._fail(results, "Get by ref_id (no graph)", e)

        # --- 3. Get by reference_id WITH entity graph (the bug path) ---
        results["tests_run"] += 1
        try:
            resp = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                reference_id=REF_ID, include_entity_graph=True)
            if not resp.is_success or not resp.objects:
                raise Exception(f"Retrieval failed: {getattr(resp, 'error_message', resp)}")
            eg = resp.objects  # EntityGraph container
            obj_list = eg.objects if hasattr(eg, 'objects') else []
            got_ref = _extract_ref_id(obj_list)
            obj_count = len(obj_list)
            logger.info(f"     include_entity_graph=True returned {obj_count} objects")
            if got_ref == REF_ID:
                self._pass(results, f"Get by ref_id (with graph) — referenceIdentifier={got_ref!r}")
            else:
                raise Exception(
                    f"DUPLICATION BUG: expected {REF_ID!r}, got {got_ref!r} "
                    f"(object count: {obj_count})")
        except Exception as e:
            self._fail(results, "Get by ref_id (with graph)", e)

        # --- 4. Get by URI WITH entity graph ---
        results["tests_run"] += 1
        try:
            resp = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri, include_entity_graph=True)
            if not resp.is_success or not resp.objects:
                raise Exception(f"Retrieval failed: {getattr(resp, 'error_message', resp)}")
            eg = resp.objects
            obj_list = eg.objects if hasattr(eg, 'objects') else []
            got_ref = _extract_ref_id(obj_list)
            obj_count = len(obj_list)
            logger.info(f"     include_entity_graph=True (by URI) returned {obj_count} objects")
            if got_ref == REF_ID:
                self._pass(results, f"Get by URI (with graph) — referenceIdentifier={got_ref!r}")
            else:
                raise Exception(
                    f"DUPLICATION BUG: expected {REF_ID!r}, got {got_ref!r} "
                    f"(object count: {obj_count})")
        except Exception as e:
            self._fail(results, "Get by URI (with graph)", e)

        # --- 5. Verify entity graph object count (entity + frame + 2 slots + 3 edges = 7) ---
        results["tests_run"] += 1
        try:
            resp = await self.client.kgentities.get_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri, include_entity_graph=True)
            if not resp.is_success or not resp.objects:
                raise Exception(f"Retrieval failed: {getattr(resp, 'error_message', resp)}")
            eg = resp.objects
            obj_list = eg.objects if hasattr(eg, 'objects') else []
            obj_count = len(obj_list)
            # Expect 7 objects: entity + frame + 2 slots + 3 edges
            if obj_count == 7:
                self._pass(results, f"Entity graph object count — {obj_count}")
            else:
                raise Exception(f"expected 7 objects, got {obj_count}")
        except Exception as e:
            self._fail(results, "Entity graph object count", e)

        # --- 6. Cleanup: delete entity ---
        results["tests_run"] += 1
        try:
            dr = await self.client.kgentities.delete_kgentity(
                space_id=space_id, graph_id=graph_id,
                uri=entity_uri)
            if dr.is_success:
                self._pass(results, "Delete entity")
            else:
                raise Exception(f"msg={getattr(dr, 'error_message', dr)}")
        except Exception as e:
            self._fail(results, "Delete entity", e)

        results["tests_failed"] = results["tests_run"] - results["tests_passed"]
        return results
