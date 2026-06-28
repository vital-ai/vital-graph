#!/usr/bin/env python3
"""
Multi-Value Property Filter & Slot Comparator Test Case

Tests multi-valued property filtering on hasKGActionTypeList (top-level entity
property) and multi-value slot comparators (has, has_any, has_all, not_has,
not_has_any) via the VitalGraph client against a live server.

Test Data Layout (5 entities):
  entity_a — hasKGActionTypeList: [TypeA, TypeB]
             AddressFrame → CitySlot: multi-valued ["Boston", "NYC"]
  entity_b — hasKGActionTypeList: [TypeB, TypeC]
             AddressFrame → CitySlot: single-valued ["Austin"]
  entity_c — hasKGActionTypeList: [TypeA]
             AddressFrame → CitySlot: multi-valued ["Boston", "Austin"]
  entity_d — hasKGActionTypeList: [] (none)
             AddressFrame → CitySlot: single-valued ["Denver"]
  entity_e — hasKGActionTypeList: [TypeA, TypeB, TypeC]
             (no AddressFrame)

Test Groups:
  Phase 5  — EntityPropertyFilter on hasKGActionTypeList (POST /kgqueries)
  Phase 5b — List endpoint action_type convenience param (GET /kgentities)
  Phase 5c — Sort by hasKGActionTypeList
  Phase 8  — SlotCriteria multi-value comparators on entity query
"""

import logging
import time
import uuid
from typing import Dict, Any, List, Set, Optional

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGMultiChoiceSlot import KGMultiChoiceSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ACTION_TYPE_PROP = "http://vital.ai/ontology/haley-ai-kg#hasKGActionTypeList"
TYPE_A = "urn:action:TypeA"
TYPE_B = "urn:action:TypeB"
TYPE_C = "urn:action:TypeC"

ADDRESS_FRAME_TYPE = "http://vital.ai/ontology/haley-ai-kg#AddressFrame"
TAGS_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#TagsSlot"
KG_MULTI_CHOICE_SLOT_CLASS = "http://vital.ai/ontology/haley-ai-kg#KGMultiChoiceSlot"


def _uri(kind: str, label: str) -> str:
    return f"http://vital.ai/test/multivalue/{kind}/{label}"


def _edge_uri() -> str:
    return f"urn:edge:{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# Entity builders
# ---------------------------------------------------------------------------

def _build_entity_a() -> List[GraphObject]:
    """Entity A: action types [TypeA, TypeB], TagsSlot (multi-choice) = [Boston, NYC]."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "a")
    entity.name = "Entity A"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"
    entity.kGActionTypeList = [TYPE_A, TYPE_B]
    objs.append(entity)

    frame = KGFrame()
    frame.URI = _uri("frame", "a_addr")
    frame.name = "A Address"
    frame.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(frame)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = frame.URI
    objs.append(edge_ef)

    # Single KGMultiChoiceSlot with multiple values
    tags = KGMultiChoiceSlot()
    tags.URI = _uri("slot", "a_tags")
    tags.kGSlotType = TAGS_SLOT_TYPE
    tags.multiChoiceSlotValues = ["Boston", "NYC"]
    objs.append(tags)
    edge_s = Edge_hasKGSlot()
    edge_s.URI = _edge_uri()
    edge_s.edgeSource = frame.URI
    edge_s.edgeDestination = tags.URI
    objs.append(edge_s)

    return objs


def _build_entity_b() -> List[GraphObject]:
    """Entity B: action types [TypeB, TypeC], TagsSlot (multi-choice) = [Austin]."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "b")
    entity.name = "Entity B"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"
    entity.kGActionTypeList = [TYPE_B, TYPE_C]
    objs.append(entity)

    frame = KGFrame()
    frame.URI = _uri("frame", "b_addr")
    frame.name = "B Address"
    frame.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(frame)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = frame.URI
    objs.append(edge_ef)

    tags = KGMultiChoiceSlot()
    tags.URI = _uri("slot", "b_tags")
    tags.kGSlotType = TAGS_SLOT_TYPE
    tags.multiChoiceSlotValues = ["Austin"]
    objs.append(tags)
    edge_s = Edge_hasKGSlot()
    edge_s.URI = _edge_uri()
    edge_s.edgeSource = frame.URI
    edge_s.edgeDestination = tags.URI
    objs.append(edge_s)

    return objs


def _build_entity_c() -> List[GraphObject]:
    """Entity C: action types [TypeA], TagsSlot (multi-choice) = [Boston, Austin]."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "c")
    entity.name = "Entity C"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"
    entity.kGActionTypeList = [TYPE_A]
    objs.append(entity)

    frame = KGFrame()
    frame.URI = _uri("frame", "c_addr")
    frame.name = "C Address"
    frame.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(frame)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = frame.URI
    objs.append(edge_ef)

    tags = KGMultiChoiceSlot()
    tags.URI = _uri("slot", "c_tags")
    tags.kGSlotType = TAGS_SLOT_TYPE
    tags.multiChoiceSlotValues = ["Boston", "Austin"]
    objs.append(tags)
    edge_s = Edge_hasKGSlot()
    edge_s.URI = _edge_uri()
    edge_s.edgeSource = frame.URI
    edge_s.edgeDestination = tags.URI
    objs.append(edge_s)

    return objs


def _build_entity_d() -> List[GraphObject]:
    """Entity D: action types [] (none), TagsSlot (multi-choice) = [Denver]."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "d")
    entity.name = "Entity D"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"
    # No kGActionTypeList set
    objs.append(entity)

    frame = KGFrame()
    frame.URI = _uri("frame", "d_addr")
    frame.name = "D Address"
    frame.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(frame)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = frame.URI
    objs.append(edge_ef)

    tags = KGMultiChoiceSlot()
    tags.URI = _uri("slot", "d_tags")
    tags.kGSlotType = TAGS_SLOT_TYPE
    tags.multiChoiceSlotValues = ["Denver"]
    objs.append(tags)
    edge_s = Edge_hasKGSlot()
    edge_s.URI = _edge_uri()
    edge_s.edgeSource = frame.URI
    edge_s.edgeDestination = tags.URI
    objs.append(edge_s)

    return objs


def _build_entity_e() -> List[GraphObject]:
    """Entity E: action types [TypeA, TypeB, TypeC], no AddressFrame."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "e")
    entity.name = "Entity E"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#KGEntityType_KGEntity"
    entity.kGActionTypeList = [TYPE_A, TYPE_B, TYPE_C]
    objs.append(entity)
    return objs


# ---------------------------------------------------------------------------
# URI constants
# ---------------------------------------------------------------------------
ENTITY_A = _uri("entity", "a")
ENTITY_B = _uri("entity", "b")
ENTITY_C = _uri("entity", "c")
ENTITY_D = _uri("entity", "d")
ENTITY_E = _uri("entity", "e")

ALL_ENTITY_BUILDERS = [
    ("Entity A", _build_entity_a),
    ("Entity B", _build_entity_b),
    ("Entity C", _build_entity_c),
    ("Entity D", _build_entity_d),
    ("Entity E", _build_entity_e),
]

ALL_ENTITY_URIS = [ENTITY_A, ENTITY_B, ENTITY_C, ENTITY_D, ENTITY_E]


def _short(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


# ---------------------------------------------------------------------------
# Tester class
# ---------------------------------------------------------------------------

class MultiValueFilterTester:
    """Integration tests for multi-value property filters and slot comparators."""

    def __init__(self, client, query_mode: str = "edge"):
        self.client = client
        self.query_mode = query_mode
        self.tests_run = 0
        self.tests_passed = 0
        self.errors: List[str] = []

    def _record(self, name: str, passed: bool, expected: Any = None,
                got: Any = None, error: str = ""):
        self.tests_run += 1
        if passed:
            self.tests_passed += 1
            print(f"  ✅ PASS: {name}")
        else:
            msg = error or f"expected {expected}, got {got}"
            self.errors.append(f"{name}: {msg}")
            print(f"  ❌ FAIL: {name} — {msg}")

    # ------------------------------------------------------------------
    # Data setup & teardown
    # ------------------------------------------------------------------

    async def setup_data(self, space_id: str, graph_id: str) -> bool:
        """Create all 5 test entities. Returns True on success."""
        # Clean up any orphaned data from previous runs
        print("  Pre-cleanup: removing any leftover test entities...")
        for uri in ALL_ENTITY_URIS:
            try:
                await self.client.kgentities.delete_kgentity(
                    space_id=space_id, graph_id=graph_id, uri=uri,
                    delete_entity_graph=True
                )
            except Exception:
                pass

        print("  Creating 5 test entities with controlled action types & slots...")

        for name, builder in ALL_ENTITY_BUILDERS:
            objs = builder()
            entity_uri = [str(o.URI) for o in objs if isinstance(o, KGEntity)][0]
            print(f"    Creating {name} ({_short(entity_uri)}) — {len(objs)} objects")

            response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=objs,
            )
            if not response.is_success:
                err = getattr(response, 'error_message', 'unknown error')
                print(f"    FAILED to create {name}: {err}")
                return False
            print(f"    OK — stored {response.count} objects")

        print("  All 5 entities created.\n")
        return True

    async def teardown_data(self, space_id: str, graph_id: str):
        """Delete all test entities and their graphs."""
        print("  Cleaning up test entities...")
        for uri in ALL_ENTITY_URIS:
            try:
                await self.client.kgentities.delete_kgentity(
                    space_id=space_id, graph_id=graph_id, uri=uri,
                    delete_entity_graph=True
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _query_entities_with_property_filter(
        self, space_id: str, graph_id: str, filters, page_size: int = 50
    ) -> Set[str]:
        """Run entity query with property filters, return set of entity URIs."""
        from vitalgraph.model.kgentities_model import EntityPropertyFilter

        response = await self.client.kgqueries.query_entities(
            space_id=space_id,
            graph_id=graph_id,
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            entity_property_filters=filters,
            query_mode=self.query_mode,
            page_size=page_size,
            offset=0,
        )
        return set(response.entity_uris or [])

    async def _query_entities_with_frame_criteria(
        self, space_id: str, graph_id: str, frame_criteria_list, page_size: int = 50
    ) -> Set[str]:
        """Run entity query with frame criteria, return set of entity URIs."""
        response = await self.client.kgqueries.query_entities(
            space_id=space_id,
            graph_id=graph_id,
            entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
            frame_criteria=frame_criteria_list,
            query_mode=self.query_mode,
            page_size=page_size,
            offset=0,
        )
        return set(response.entity_uris or [])

    # ==================================================================
    # Phase 5: EntityPropertyFilter on hasKGActionTypeList
    # ==================================================================

    async def _test_action_type_has(self, space_id: str, graph_id: str):
        """has TypeA → entities A, C, E."""
        print("\n  Test: EntityPropertyFilter has TypeA")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            got = await self._query_entities_with_property_filter(
                space_id, graph_id,
                [EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="has", value=TYPE_A)]
            )
            expected = {ENTITY_A, ENTITY_C, ENTITY_E}
            self._record("has TypeA", got == expected, expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("has TypeA", False, error=str(e))

    async def _test_action_type_has_any(self, space_id: str, graph_id: str):
        """has_any [TypeA, TypeC] → entities A, B, C, E (anyone with A or C)."""
        print("\n  Test: EntityPropertyFilter has_any [TypeA, TypeC]")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            got = await self._query_entities_with_property_filter(
                space_id, graph_id,
                [EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="has_any", value=[TYPE_A, TYPE_C])]
            )
            expected = {ENTITY_A, ENTITY_B, ENTITY_C, ENTITY_E}
            self._record("has_any [A,C]", got == expected, expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("has_any [A,C]", False, error=str(e))

    async def _test_action_type_has_all(self, space_id: str, graph_id: str):
        """has_all [TypeA, TypeB] → entities A, E (both have A and B)."""
        print("\n  Test: EntityPropertyFilter has_all [TypeA, TypeB]")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            got = await self._query_entities_with_property_filter(
                space_id, graph_id,
                [EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="has_all", value=[TYPE_A, TYPE_B])]
            )
            expected = {ENTITY_A, ENTITY_E}
            self._record("has_all [A,B]", got == expected, expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("has_all [A,B]", False, error=str(e))

    async def _test_action_type_not_has(self, space_id: str, graph_id: str):
        """not_has TypeA → entities B, D (D has none, B has B+C)."""
        print("\n  Test: EntityPropertyFilter not_has TypeA")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            got = await self._query_entities_with_property_filter(
                space_id, graph_id,
                [EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="not_has", value=TYPE_A)]
            )
            expected = {ENTITY_B, ENTITY_D}
            self._record("not_has TypeA", got == expected, expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("not_has TypeA", False, error=str(e))

    async def _test_action_type_not_has_any(self, space_id: str, graph_id: str):
        """not_has_any [TypeA, TypeC] → entity D only (D has none; B has C)."""
        print("\n  Test: EntityPropertyFilter not_has_any [TypeA, TypeC]")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            got = await self._query_entities_with_property_filter(
                space_id, graph_id,
                [EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="not_has_any", value=[TYPE_A, TYPE_C])]
            )
            expected = {ENTITY_D}
            self._record("not_has_any [A,C]", got == expected, expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("not_has_any [A,C]", False, error=str(e))

    async def _test_action_type_exists(self, space_id: str, graph_id: str):
        """exists → entities A, B, C, E (all that have at least one action type)."""
        print("\n  Test: EntityPropertyFilter exists")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            got = await self._query_entities_with_property_filter(
                space_id, graph_id,
                [EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="exists", value=None)]
            )
            expected = {ENTITY_A, ENTITY_B, ENTITY_C, ENTITY_E}
            self._record("exists", got == expected, expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("exists", False, error=str(e))

    async def _test_action_type_not_exists(self, space_id: str, graph_id: str):
        """not_exists → entity D only."""
        print("\n  Test: EntityPropertyFilter not_exists")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            got = await self._query_entities_with_property_filter(
                space_id, graph_id,
                [EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="not_exists", value=None)]
            )
            expected = {ENTITY_D}
            self._record("not_exists", got == expected, expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("not_exists", False, error=str(e))

    # ==================================================================
    # Phase 5b: List endpoint action_type convenience param
    # ==================================================================

    async def _test_list_action_type_param(self, space_id: str, graph_id: str):
        """GET /kgentities?action_type=TypeA → entities with TypeA in their list."""
        print("\n  Test: list_kgentities action_type convenience param")
        try:
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=50,
                action_type=TYPE_A,
            )
            if response.is_success and hasattr(response, 'objects'):
                got_uris = set()
                for obj in response.objects:
                    if isinstance(obj, KGEntity):
                        got_uris.add(str(obj.URI))
                expected = {ENTITY_A, ENTITY_C, ENTITY_E}
                self._record("list action_type=TypeA", got_uris == expected,
                             expected=set(map(_short, expected)), got=set(map(_short, got_uris)))
            else:
                self._record("list action_type=TypeA", False, error="unexpected response type")
        except Exception as e:
            self._record("list action_type=TypeA", False, error=str(e))

    # ==================================================================
    # Phase 5c: Sort by hasKGActionTypeList
    # ==================================================================

    async def _test_sort_by_action_type_asc(self, space_id: str, graph_id: str):
        """Sort by action type ASC. Entity D (no action type) should be excluded.
        Remaining entities should be in deterministic MIN order."""
        print("\n  Test: sort by hasKGActionTypeList ASC")
        try:
            response = await self.client.kgentities.list_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                page_size=50,
                sort_by=ACTION_TYPE_PROP,
                sort_order="asc",
            )
            if response.is_success and hasattr(response, 'objects'):
                got_uris = []
                for obj in response.objects:
                    if isinstance(obj, KGEntity):
                        got_uris.append(str(obj.URI))
                # Entity D should be excluded (no action type)
                excluded_d = ENTITY_D not in got_uris
                # At least the other 4 should appear
                has_others = len(got_uris) >= 4
                # Verify sort order: MIN=TypeA entities (A, C, E) before MIN=TypeB entity (B)
                if ENTITY_B in got_uris:
                    b_idx = got_uris.index(ENTITY_B)
                    type_a_entities = {ENTITY_A, ENTITY_C, ENTITY_E}
                    all_before_b = all(
                        got_uris.index(u) < b_idx
                        for u in type_a_entities if u in got_uris
                    )
                else:
                    all_before_b = False
                passed = excluded_d and has_others and all_before_b
                self._record("sort ASC excludes entity D",
                             passed,
                             expected="D excluded, A/C/E before B",
                             got=f"D_in={not excluded_d}, count={len(got_uris)}, order={[_short(u) for u in got_uris]}")
            else:
                self._record("sort ASC excludes entity D", False, error="unexpected response type")
        except Exception as e:
            self._record("sort ASC excludes entity D", False, error=str(e))

    # ==================================================================
    # Phase 8: SlotCriteria multi-value comparators (entity query)
    # ==================================================================

    async def _test_slot_has(self, space_id: str, graph_id: str):
        """Slot has Boston → entities A, C (both have Boston in their multi-choice slot)."""
        print("\n  Test: SlotCriteria has Boston")
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
        try:
            got = await self._query_entities_with_frame_criteria(
                space_id, graph_id,
                [FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[SlotCriteria(
                        slot_type=TAGS_SLOT_TYPE,
                        slot_class_uri=KG_MULTI_CHOICE_SLOT_CLASS,
                        value="Boston",
                        comparator="has",
                    )],
                    frame_criteria=None,
                )]
            )
            expected = {ENTITY_A, ENTITY_C}
            self._record("slot has Boston", got == expected,
                         expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("slot has Boston", False, error=str(e))

    async def _test_slot_has_any(self, space_id: str, graph_id: str):
        """Slot has_any [Boston, Denver] → entities A, C, D."""
        print("\n  Test: SlotCriteria has_any [Boston, Denver]")
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
        try:
            got = await self._query_entities_with_frame_criteria(
                space_id, graph_id,
                [FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[SlotCriteria(
                        slot_type=TAGS_SLOT_TYPE,
                        slot_class_uri=KG_MULTI_CHOICE_SLOT_CLASS,
                        value=["Boston", "Denver"],
                        comparator="has_any",
                    )],
                    frame_criteria=None,
                )]
            )
            expected = {ENTITY_A, ENTITY_C, ENTITY_D}
            self._record("slot has_any [Boston,Denver]", got == expected,
                         expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("slot has_any [Boston,Denver]", False, error=str(e))

    async def _test_slot_has_all(self, space_id: str, graph_id: str):
        """Slot has_all [Boston, Austin] → entity C only (its single slot has both values)."""
        print("\n  Test: SlotCriteria has_all [Boston, Austin]")
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
        try:
            got = await self._query_entities_with_frame_criteria(
                space_id, graph_id,
                [FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[SlotCriteria(
                        slot_type=TAGS_SLOT_TYPE,
                        slot_class_uri=KG_MULTI_CHOICE_SLOT_CLASS,
                        value=["Boston", "Austin"],
                        comparator="has_all",
                    )],
                    frame_criteria=None,
                )]
            )
            expected = {ENTITY_C}
            self._record("slot has_all [Boston,Austin]", got == expected,
                         expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("slot has_all [Boston,Austin]", False, error=str(e))

    async def _test_slot_not_has(self, space_id: str, graph_id: str):
        """Slot not_has Boston → entities with AddressFrame whose TagsSlot doesn't contain Boston → B, D."""
        print("\n  Test: SlotCriteria not_has Boston")
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
        try:
            got = await self._query_entities_with_frame_criteria(
                space_id, graph_id,
                [FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[SlotCriteria(
                        slot_type=TAGS_SLOT_TYPE,
                        slot_class_uri=KG_MULTI_CHOICE_SLOT_CLASS,
                        value="Boston",
                        comparator="not_has",
                    )],
                    frame_criteria=None,
                )]
            )
            expected = {ENTITY_B, ENTITY_D}
            self._record("slot not_has Boston", got == expected,
                         expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("slot not_has Boston", False, error=str(e))

    async def _test_slot_not_has_any(self, space_id: str, graph_id: str):
        """Slot not_has_any [Boston, NYC] → entities with AddressFrame whose TagsSlot has none of [Boston,NYC] → B, D."""
        print("\n  Test: SlotCriteria not_has_any [Boston, NYC]")
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
        try:
            got = await self._query_entities_with_frame_criteria(
                space_id, graph_id,
                [FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[SlotCriteria(
                        slot_type=TAGS_SLOT_TYPE,
                        slot_class_uri=KG_MULTI_CHOICE_SLOT_CLASS,
                        value=["Boston", "NYC"],
                        comparator="not_has_any",
                    )],
                    frame_criteria=None,
                )]
            )
            expected = {ENTITY_B, ENTITY_D}
            self._record("slot not_has_any [Boston,NYC]", got == expected,
                         expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("slot not_has_any [Boston,NYC]", False, error=str(e))

    async def _test_slot_combined_has_and_has(self, space_id: str, graph_id: str):
        """Combined: AddressFrame with has Boston + has Austin on same multi-choice slot.
        Only entity C has both Boston and Austin in its TagsSlot → entity C."""
        print("\n  Test: Combined slot has Boston + has Austin (same slot)")
        from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria
        try:
            got = await self._query_entities_with_frame_criteria(
                space_id, graph_id,
                [FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type=TAGS_SLOT_TYPE,
                            slot_class_uri=KG_MULTI_CHOICE_SLOT_CLASS,
                            value="Boston",
                            comparator="has",
                        ),
                        SlotCriteria(
                            slot_type=TAGS_SLOT_TYPE,
                            slot_class_uri=KG_MULTI_CHOICE_SLOT_CLASS,
                            value="Austin",
                            comparator="has",
                        ),
                    ],
                    frame_criteria=None,
                )]
            )
            expected = {ENTITY_C}
            self._record("combined has Boston + has Austin", got == expected,
                         expected=set(map(_short, expected)), got=set(map(_short, got)))
        except Exception as e:
            self._record("combined has Boston + has Austin", False, error=str(e))

    async def _test_count_with_action_type_filter(self, space_id: str, graph_id: str):
        """count_only with has TypeA filter — count should match full query."""
        print("\n  Test: count_only with has TypeA")
        from vitalgraph.model.kgentities_model import EntityPropertyFilter
        try:
            # Full query
            full = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                entity_property_filters=[
                    EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="has", value=TYPE_A)
                ],
                query_mode=self.query_mode,
                page_size=50,
            )
            full_count = full.total_count

            # Count-only query
            count_resp = await self.client.kgqueries.query_entities(
                space_id=space_id,
                graph_id=graph_id,
                entity_type="http://vital.ai/ontology/haley-ai-kg#KGEntity",
                entity_property_filters=[
                    EntityPropertyFilter(property_uri=ACTION_TYPE_PROP, operator="has", value=TYPE_A)
                ],
                query_mode=self.query_mode,
                page_size=1,
                count_only=True,
            )
            count_only_total = count_resp.total_count

            passed = full_count == count_only_total and full_count == 3
            self._record("count_only matches full query", passed,
                         expected=f"full={3}, count_only=same",
                         got=f"full={full_count}, count_only={count_only_total}")
        except Exception as e:
            self._record("count_only matches full query", False, error=str(e))

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Run all multi-value filter integration tests."""
        print("=" * 80)
        print("  Multi-Value Property Filter & Slot Comparator Tests")
        print("=" * 80)

        # Phase 5: EntityPropertyFilter on hasKGActionTypeList
        print("\n--- Phase 5: EntityPropertyFilter on hasKGActionTypeList ---")
        await self._test_action_type_has(space_id, graph_id)
        await self._test_action_type_has_any(space_id, graph_id)
        await self._test_action_type_has_all(space_id, graph_id)
        await self._test_action_type_not_has(space_id, graph_id)
        await self._test_action_type_not_has_any(space_id, graph_id)
        await self._test_action_type_exists(space_id, graph_id)
        await self._test_action_type_not_exists(space_id, graph_id)

        # Phase 5b: List endpoint convenience param
        print("\n--- Phase 5b: List endpoint action_type param ---")
        await self._test_list_action_type_param(space_id, graph_id)

        # Phase 5c: Sort by action type
        print("\n--- Phase 5c: Sort by hasKGActionTypeList ---")
        await self._test_sort_by_action_type_asc(space_id, graph_id)

        # Count consistency
        print("\n--- Count consistency ---")
        await self._test_count_with_action_type_filter(space_id, graph_id)

        # Phase 8: SlotCriteria multi-value comparators
        print("\n--- Phase 8: SlotCriteria multi-value comparators ---")
        await self._test_slot_has(space_id, graph_id)
        await self._test_slot_has_any(space_id, graph_id)
        await self._test_slot_has_all(space_id, graph_id)
        await self._test_slot_not_has(space_id, graph_id)
        await self._test_slot_not_has_any(space_id, graph_id)
        await self._test_slot_combined_has_and_has(space_id, graph_id)

        print(f"\n  Summary: {self.tests_passed}/{self.tests_run} passed")
        if self.errors:
            print(f"  Errors:")
            for e in self.errors:
                print(f"    - {e}")

        return {
            "test_name": "Multi-Value Filters & Slot Comparators",
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "errors": self.errors,
        }
