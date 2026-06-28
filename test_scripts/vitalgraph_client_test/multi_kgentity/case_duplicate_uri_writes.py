#!/usr/bin/env python3
"""
Duplicate URI Writes Test Case

Tests that writing entity graphs with the same URIs multiple times does NOT
cause triple accumulation.  This reproduces the bug where a second CREATE
for the same slot URI added triples without removing the old ones, leading
to corrupted data (e.g. a KGTextSlot with both text and integer properties).

Test strategy:
1. Create an entity graph with a frame and slots (text, integer, datetime)
2. Read back the entity graph and verify correct triple counts
3. Create the SAME entity graph again with the same URIs but DIFFERENT values
4. Read back and verify:
   a. Only one set of triples per subject (no accumulation)
   b. Values match the SECOND write (old values replaced)
5. Create a DIFFERENT slot type on the same slot URI (e.g. KGIntegerSlot
   reusing a URI that was previously KGTextSlot) and verify the type changed
6. Verify via include_entity_graph that retrieval still works correctly
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

logger = logging.getLogger(__name__)

# Fixed URIs — deliberately reused across writes to test idempotency
ENTITY_URI = "urn:test:duplicate_uri:entity_001"
FRAME_URI = "urn:test:duplicate_uri:frame_info_001"
SLOT_NAME_URI = "urn:test:duplicate_uri:slot_name_001"
SLOT_COUNT_URI = "urn:test:duplicate_uri:slot_count_001"
SLOT_DATE_URI = "urn:test:duplicate_uri:slot_date_001"
EDGE_ENTITY_FRAME_URI = "urn:test:duplicate_uri:edge_entity_frame_001"
EDGE_FRAME_NAME_URI = "urn:test:duplicate_uri:edge_frame_name_001"
EDGE_FRAME_COUNT_URI = "urn:test:duplicate_uri:edge_frame_count_001"
EDGE_FRAME_DATE_URI = "urn:test:duplicate_uri:edge_frame_date_001"


def _build_entity_graph(
    name_value: str = "Alpha Corp",
    count_value: int = 100,
    date_value: datetime = datetime(2020, 1, 1),
) -> List[GraphObject]:
    """Build a complete entity graph using the fixed URIs."""
    objects: List[GraphObject] = []

    # Entity
    entity = KGEntity()
    entity.URI = ENTITY_URI
    entity.name = name_value
    entity.kGEntityType = "http://vital.ai/test/kgtype/TestOrganizationEntity"
    objects.append(entity)

    # Frame
    frame = KGFrame()
    frame.URI = FRAME_URI
    frame.name = f"{name_value} Info"
    frame.kGFrameType = "http://vital.ai/test/kgtype/CompanyInfoFrame"
    objects.append(frame)

    # Text slot — company name
    name_slot = KGTextSlot()
    name_slot.URI = SLOT_NAME_URI
    name_slot.name = "Company Name"
    name_slot.kGSlotType = "http://vital.ai/test/kgtype/CompanyNameSlot"
    name_slot.textSlotValue = name_value
    objects.append(name_slot)

    # Integer slot — employee count
    count_slot = KGIntegerSlot()
    count_slot.URI = SLOT_COUNT_URI
    count_slot.name = "Employee Count"
    count_slot.kGSlotType = "http://vital.ai/test/kgtype/EmployeeCountSlot"
    count_slot.integerSlotValue = count_value
    objects.append(count_slot)

    # DateTime slot — founded date
    date_slot = KGDateTimeSlot()
    date_slot.URI = SLOT_DATE_URI
    date_slot.name = "Founded Date"
    date_slot.kGSlotType = "http://vital.ai/test/kgtype/FoundedDateSlot"
    date_slot.dateTimeSlotValue = date_value
    objects.append(date_slot)

    # Edge: entity -> frame
    e_ef = Edge_hasEntityKGFrame()
    e_ef.URI = EDGE_ENTITY_FRAME_URI
    e_ef.edgeSource = ENTITY_URI
    e_ef.edgeDestination = FRAME_URI
    objects.append(e_ef)

    # Edge: frame -> name slot
    e_fn = Edge_hasKGSlot()
    e_fn.URI = EDGE_FRAME_NAME_URI
    e_fn.edgeSource = FRAME_URI
    e_fn.edgeDestination = SLOT_NAME_URI
    objects.append(e_fn)

    # Edge: frame -> count slot
    e_fc = Edge_hasKGSlot()
    e_fc.URI = EDGE_FRAME_COUNT_URI
    e_fc.edgeSource = FRAME_URI
    e_fc.edgeDestination = SLOT_COUNT_URI
    objects.append(e_fc)

    # Edge: frame -> date slot
    e_fd = Edge_hasKGSlot()
    e_fd.URI = EDGE_FRAME_DATE_URI
    e_fd.edgeSource = FRAME_URI
    e_fd.edgeDestination = SLOT_DATE_URI
    objects.append(e_fd)

    return objects


def _build_frame_objects(
    name_value: str = "Alpha Corp",
    count_value: int = 100,
    date_value: datetime = datetime(2020, 1, 1),
) -> List[GraphObject]:
    """Build frame + slot + edge objects (NO entity) for update_entity_frames."""
    objects: List[GraphObject] = []

    # Frame
    frame = KGFrame()
    frame.URI = FRAME_URI
    frame.name = f"{name_value} Info"
    frame.kGFrameType = "http://vital.ai/test/kgtype/CompanyInfoFrame"
    objects.append(frame)

    # Text slot
    name_slot = KGTextSlot()
    name_slot.URI = SLOT_NAME_URI
    name_slot.name = "Company Name"
    name_slot.kGSlotType = "http://vital.ai/test/kgtype/CompanyNameSlot"
    name_slot.textSlotValue = name_value
    objects.append(name_slot)

    # Integer slot
    count_slot = KGIntegerSlot()
    count_slot.URI = SLOT_COUNT_URI
    count_slot.name = "Employee Count"
    count_slot.kGSlotType = "http://vital.ai/test/kgtype/EmployeeCountSlot"
    count_slot.integerSlotValue = count_value
    objects.append(count_slot)

    # DateTime slot
    date_slot = KGDateTimeSlot()
    date_slot.URI = SLOT_DATE_URI
    date_slot.name = "Founded Date"
    date_slot.kGSlotType = "http://vital.ai/test/kgtype/FoundedDateSlot"
    date_slot.dateTimeSlotValue = date_value
    objects.append(date_slot)

    # Edge: frame -> name slot
    e_fn = Edge_hasKGSlot()
    e_fn.URI = EDGE_FRAME_NAME_URI
    e_fn.edgeSource = FRAME_URI
    e_fn.edgeDestination = SLOT_NAME_URI
    objects.append(e_fn)

    # Edge: frame -> count slot
    e_fc = Edge_hasKGSlot()
    e_fc.URI = EDGE_FRAME_COUNT_URI
    e_fc.edgeSource = FRAME_URI
    e_fc.edgeDestination = SLOT_COUNT_URI
    objects.append(e_fc)

    # Edge: frame -> date slot
    e_fd = Edge_hasKGSlot()
    e_fd.URI = EDGE_FRAME_DATE_URI
    e_fd.edgeSource = FRAME_URI
    e_fd.edgeDestination = SLOT_DATE_URI
    objects.append(e_fd)

    return objects


def _extract_graph_objects(response) -> List:
    """Extract the flat objects list from an EntityGraphResponse.
    
    When include_entity_graph=True, response.objects is an EntityGraph
    container whose .objects attribute holds the actual GraphObject list.
    """
    if not response.is_success or response.objects is None:
        return []
    eg = response.objects  # EntityGraph
    if hasattr(eg, 'objects') and isinstance(eg.objects, list):
        return eg.objects
    return []


class DuplicateUriWritesTester:
    """Test case for verifying atomic writes prevent triple accumulation."""

    def __init__(self, client):
        self.client = client

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """
        Run duplicate-URI write tests.

        Returns:
            Dict with test_name, tests_run, tests_passed, tests_failed, errors
        """
        results = {
            "test_name": "Duplicate URI Writes (Atomic Update)",
            "tests_run": 0,
            "tests_passed": 0,
            "tests_failed": 0,
            "errors": [],
        }

        logger.info("=" * 80)
        logger.info("  Duplicate URI Writes — Atomic Update Tests")
        logger.info("=" * 80)

        # ==================================================================
        # Test 1: Initial CREATE — entity graph with first set of values
        # ==================================================================
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 1: Initial CREATE ---")
            objects_v1 = _build_entity_graph(
                name_value="Alpha Corp",
                count_value=100,
                date_value=datetime(2020, 1, 1),
            )
            logger.info(f"   Creating entity graph with {len(objects_v1)} objects")
            logger.info(f"   Entity URI: {ENTITY_URI}")
            logger.info(f"   Values: name='Alpha Corp', count=100, date=2020-01-01")

            response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=objects_v1,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Initial create succeeded (count={response.count})")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Initial create failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Initial create failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception in initial create: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception in initial create: {e}")

        # ==================================================================
        # Test 2: Verify initial data via include_entity_graph
        # ==================================================================
        results["tests_run"] += 1
        initial_object_count = 0
        try:
            logger.info("\n--- Test 2: Verify initial data via entity graph retrieval ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=ENTITY_URI,
                include_entity_graph=True,
            )

            graph_objects = _extract_graph_objects(response)
            if graph_objects:
                initial_object_count = len(graph_objects)
                logger.info(f"   Retrieved {initial_object_count} objects in entity graph")

                # Check for expected object types
                entities = [o for o in graph_objects if isinstance(o, KGEntity)]
                frames = [o for o in graph_objects if isinstance(o, KGFrame)]
                text_slots = [o for o in graph_objects if isinstance(o, KGTextSlot)]
                int_slots = [o for o in graph_objects if isinstance(o, KGIntegerSlot)]
                dt_slots = [o for o in graph_objects if isinstance(o, KGDateTimeSlot)]

                logger.info(f"   Entities: {len(entities)}, Frames: {len(frames)}, "
                          f"TextSlots: {len(text_slots)}, IntSlots: {len(int_slots)}, "
                          f"DateTimeSlots: {len(dt_slots)}")

                # Verify text slot value
                if text_slots:
                    val = str(text_slots[0].textSlotValue) if text_slots[0].textSlotValue else None
                    logger.info(f"   Text slot value: {val}")
                    if val != "Alpha Corp":
                        logger.error(f"   ❌ FAIL: Expected 'Alpha Corp', got '{val}'")
                        results["tests_failed"] += 1
                        results["errors"].append(f"Initial text slot value mismatch: {val}")
                    else:
                        logger.info(f"   ✅ PASS: Initial entity graph verified")
                        results["tests_passed"] += 1
                else:
                    logger.info(f"   ✅ PASS: Initial entity graph retrieved ({initial_object_count} objects)")
                    results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Could not retrieve entity graph")
                results["tests_failed"] += 1
                results["errors"].append("Could not retrieve initial entity graph")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception retrieving initial data: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception retrieving initial data: {e}")

        # ==================================================================
        # Test 3: SECOND CREATE — same URIs, different values
        # ==================================================================
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 3: UPDATE with SAME URIs, DIFFERENT values ---")
            objects_v2 = _build_entity_graph(
                name_value="Beta Industries",
                count_value=500,
                date_value=datetime(2015, 6, 15),
            )
            logger.info(f"   Updating entity graph with {len(objects_v2)} objects (same URIs)")
            logger.info(f"   Values: name='Beta Industries', count=500, date=2015-06-15")

            response = await self.client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=objects_v2,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Update succeeded")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Update failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Update failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception in update: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception in update: {e}")

        # ==================================================================
        # Test 4: Verify NO triple accumulation — object count unchanged
        # ==================================================================
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 4: Verify NO triple accumulation after second write ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=ENTITY_URI,
                include_entity_graph=True,
            )

            graph_objects = _extract_graph_objects(response)
            if graph_objects:
                second_count = len(graph_objects)
                logger.info(f"   Object count after second write: {second_count}")
                logger.info(f"   Object count after first write:  {initial_object_count}")

                if second_count == initial_object_count:
                    logger.info(f"   ✅ PASS: No triple accumulation — count unchanged at {second_count}")
                    results["tests_passed"] += 1
                elif second_count > initial_object_count:
                    logger.error(f"   ❌ FAIL: TRIPLE ACCUMULATION DETECTED!")
                    logger.error(f"   Objects grew from {initial_object_count} to {second_count}")
                    results["tests_failed"] += 1
                    results["errors"].append(
                        f"Triple accumulation: {initial_object_count} -> {second_count} objects"
                    )
                else:
                    logger.warning(f"   ⚠️  Object count decreased: {initial_object_count} -> {second_count}")
                    results["tests_failed"] += 1
                    results["errors"].append(
                        f"Object count decreased: {initial_object_count} -> {second_count}"
                    )
            else:
                logger.error(f"   ❌ FAIL: Could not retrieve entity graph after second write")
                results["tests_failed"] += 1
                results["errors"].append("Could not retrieve entity graph after second write")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception verifying second write: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception verifying second write: {e}")

        # ==================================================================
        # Test 5: Verify values match SECOND write (old values replaced)
        # ==================================================================
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 5: Verify values match second write ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=ENTITY_URI,
                include_entity_graph=True,
            )

            graph_objects = _extract_graph_objects(response)
            if graph_objects:
                text_slots = [o for o in graph_objects if isinstance(o, KGTextSlot)]
                int_slots = [o for o in graph_objects if isinstance(o, KGIntegerSlot)]
                
                value_errors = []

                # Check text slot has v2 value
                for slot in text_slots:
                    val = str(slot.textSlotValue) if slot.textSlotValue else None
                    if val and "Alpha" in val:
                        value_errors.append(f"Text slot still has v1 value: '{val}'")
                    if val == "Beta Industries":
                        logger.info(f"   Text slot: '{val}' ✅")

                # Check integer slot has v2 value
                for slot in int_slots:
                    val = slot.integerSlotValue
                    if val == 100:
                        value_errors.append(f"Integer slot still has v1 value: {val}")
                    if val == 500:
                        logger.info(f"   Integer slot: {val} ✅")

                if value_errors:
                    logger.error(f"   ❌ FAIL: Stale values found:")
                    for err in value_errors:
                        logger.error(f"      {err}")
                    results["tests_failed"] += 1
                    results["errors"].extend(value_errors)
                else:
                    logger.info(f"   ✅ PASS: All values match second write")
                    results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Could not retrieve entity graph for value check")
                results["tests_failed"] += 1
                results["errors"].append("Could not retrieve entity graph for value check")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception verifying values: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception verifying values: {e}")

        # ==================================================================
        # Test 6: THIRD CREATE — change slot type on same URI
        # Reuse SLOT_NAME_URI (was KGTextSlot) as KGIntegerSlot
        # ==================================================================
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 6: UPDATE — change slot type on same URI ---")
            logger.info(f"   Changing {SLOT_NAME_URI} from KGTextSlot to KGIntegerSlot")

            objects_v3: List[GraphObject] = []

            # Same entity
            entity = KGEntity()
            entity.URI = ENTITY_URI
            entity.name = "Gamma LLC"
            entity.kGEntityType = "http://vital.ai/test/kgtype/TestOrganizationEntity"
            objects_v3.append(entity)

            # Same frame
            frame = KGFrame()
            frame.URI = FRAME_URI
            frame.name = "Gamma LLC Info"
            frame.kGFrameType = "http://vital.ai/test/kgtype/CompanyInfoFrame"
            objects_v3.append(frame)

            # SLOT_NAME_URI now as KGIntegerSlot (was KGTextSlot)
            type_changed_slot = KGIntegerSlot()
            type_changed_slot.URI = SLOT_NAME_URI
            type_changed_slot.name = "Converted Slot"
            type_changed_slot.kGSlotType = "http://vital.ai/test/kgtype/ConvertedSlot"
            type_changed_slot.integerSlotValue = 999
            objects_v3.append(type_changed_slot)

            # Keep count slot as integer
            count_slot = KGIntegerSlot()
            count_slot.URI = SLOT_COUNT_URI
            count_slot.name = "Employee Count"
            count_slot.kGSlotType = "http://vital.ai/test/kgtype/EmployeeCountSlot"
            count_slot.integerSlotValue = 750
            objects_v3.append(count_slot)

            # Keep date slot
            date_slot = KGDateTimeSlot()
            date_slot.URI = SLOT_DATE_URI
            date_slot.name = "Founded Date"
            date_slot.kGSlotType = "http://vital.ai/test/kgtype/FoundedDateSlot"
            date_slot.dateTimeSlotValue = datetime(2010, 3, 20)
            objects_v3.append(date_slot)

            # Edges (same URIs)
            e_ef = Edge_hasEntityKGFrame()
            e_ef.URI = EDGE_ENTITY_FRAME_URI
            e_ef.edgeSource = ENTITY_URI
            e_ef.edgeDestination = FRAME_URI
            objects_v3.append(e_ef)

            e_fn = Edge_hasKGSlot()
            e_fn.URI = EDGE_FRAME_NAME_URI
            e_fn.edgeSource = FRAME_URI
            e_fn.edgeDestination = SLOT_NAME_URI
            objects_v3.append(e_fn)

            e_fc = Edge_hasKGSlot()
            e_fc.URI = EDGE_FRAME_COUNT_URI
            e_fc.edgeSource = FRAME_URI
            e_fc.edgeDestination = SLOT_COUNT_URI
            objects_v3.append(e_fc)

            e_fd = Edge_hasKGSlot()
            e_fd.URI = EDGE_FRAME_DATE_URI
            e_fd.edgeSource = FRAME_URI
            e_fd.edgeDestination = SLOT_DATE_URI
            objects_v3.append(e_fd)

            response = await self.client.kgentities.update_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=objects_v3,
            )

            if response.is_success:
                logger.info(f"   ✅ PASS: Type-change update succeeded")
                results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Type-change update failed: {response.error_message}")
                results["tests_failed"] += 1
                results["errors"].append(f"Type-change update failed: {response.error_message}")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception in type-change update: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception in type-change update: {e}")

        # ==================================================================
        # Test 7: Verify type change — no leftover text properties
        # ==================================================================
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 7: Verify type change — no leftover text properties ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=ENTITY_URI,
                include_entity_graph=True,
            )

            graph_objects = _extract_graph_objects(response)
            if graph_objects:
                obj_count = len(graph_objects)
                text_slots = [o for o in graph_objects if isinstance(o, KGTextSlot)]
                int_slots = [o for o in graph_objects if isinstance(o, KGIntegerSlot)]

                logger.info(f"   Total objects: {obj_count}")
                logger.info(f"   TextSlots: {len(text_slots)}")
                logger.info(f"   IntegerSlots: {len(int_slots)}")

                # We should have 0 text slots (the one that was text is now integer)
                # We should have 2 integer slots (converted + count)
                type_errors = []
                if text_slots:
                    type_errors.append(
                        f"Found {len(text_slots)} TextSlot(s) — old type not cleaned up"
                    )
                    for ts in text_slots:
                        logger.error(f"      Leftover TextSlot URI: {ts.URI}, "
                                   f"value: {ts.textSlotValue}")

                if len(int_slots) != 2:
                    type_errors.append(
                        f"Expected 2 IntegerSlots, found {len(int_slots)}"
                    )

                if type_errors:
                    logger.error(f"   ❌ FAIL: Type change verification failed:")
                    for err in type_errors:
                        logger.error(f"      {err}")
                    results["tests_failed"] += 1
                    results["errors"].extend(type_errors)
                else:
                    logger.info(f"   ✅ PASS: Type change clean — 0 TextSlots, 2 IntegerSlots")
                    results["tests_passed"] += 1
            else:
                logger.error(f"   ❌ FAIL: Could not retrieve entity graph after type change")
                results["tests_failed"] += 1
                results["errors"].append("Could not retrieve entity graph after type change")
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception verifying type change: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception verifying type change: {e}")

        # ==================================================================
        # Test 8: Verify entity graph retrieval still returns non-zero
        # (the original bug caused include_entity_graph to return 0 objects)
        # ==================================================================
        results["tests_run"] += 1
        try:
            logger.info("\n--- Test 8: Entity graph retrieval returns objects (regression check) ---")

            response = await self.client.kgentities.get_kgentity(
                space_id=space_id,
                graph_id=graph_id,
                uri=ENTITY_URI,
                include_entity_graph=True,
            )

            graph_objects = _extract_graph_objects(response)
            if graph_objects and len(graph_objects) > 0:
                logger.info(f"   Entity graph contains {len(graph_objects)} objects")
                logger.info(f"   ✅ PASS: Entity graph retrieval works after multiple writes")
                results["tests_passed"] += 1
            else:
                count = len(graph_objects)
                logger.error(f"   ❌ FAIL: Entity graph returned {count} objects (expected > 0)")
                logger.error(f"   This is the original bug — triple accumulation breaks retrieval")
                results["tests_failed"] += 1
                results["errors"].append(
                    f"Entity graph returned {count} objects after multiple writes"
                )
        except Exception as e:
            logger.error(f"   ❌ FAIL: Exception in regression check: {e}")
            results["tests_failed"] += 1
            results["errors"].append(f"Exception in regression check: {e}")

        # ==================================================================
        # Summary
        # ==================================================================
        logger.info(f"\n{'=' * 80}")
        logger.info(f"   Duplicate URI Writes: "
                    f"{results['tests_passed']}/{results['tests_run']} passed")
        logger.info(f"{'=' * 80}\n")

        return results
