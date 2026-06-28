#!/usr/bin/env python3
"""
Slot Negation Integration Test Case

Tests KGQuery slot/frame negation via the VitalGraph client against a live server.
Creates 5 entities with carefully controlled frame/slot structures, then verifies
that frame negate, slot not_exists, and slot is_empty queries return correct results.

Test Data Layout:
  alpha_corp   — AddressFrame(ZipCode=94105, City=SF),      CompanyInfoFrame(Industry=Technology)
  beta_llc     — AddressFrame(ZipCode=10005, City=NY),      CompanyInfoFrame(Industry=Finance)
  gamma_inc    — AddressFrame(City=Boston, NO ZipCodeSlot),  CompanyInfoFrame(Industry=Healthcare)
  delta_co     — AddressFrame(ZipCode slot exists but empty, City=Austin), CompanyInfoFrame(Industry=Energy)
  epsilon_ltd  — NO AddressFrame,                            CompanyInfoFrame(Industry=Technology)
"""

import logging
import uuid
from typing import Dict, Any, List, Set

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot

logger = logging.getLogger(__name__)

# URN constants for frame/slot types used in this test
ADDRESS_FRAME_TYPE = "http://vital.ai/ontology/haley-ai-kg#AddressFrame"
COMPANY_INFO_FRAME_TYPE = "http://vital.ai/ontology/haley-ai-kg#CompanyInfoFrame"
ZIPCODE_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#ZipCodeSlot"
CITY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#CitySlot"
INDUSTRY_SLOT_TYPE = "http://vital.ai/ontology/haley-ai-kg#IndustrySlot"


def _uri(kind: str, label: str) -> str:
    """Generate a deterministic test URI."""
    return f"http://vital.ai/test/negation/{kind}/{label}"


def _edge_uri() -> str:
    return f"urn:edge:{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# Entity builders
# ---------------------------------------------------------------------------

def _build_alpha_corp() -> List[GraphObject]:
    """AddressFrame(ZipCode=94105, City=SF), CompanyInfoFrame(Industry=Technology)."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "alpha_corp")
    entity.name = "Alpha Corp"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
    objs.append(entity)

    # --- AddressFrame ---
    addr = KGFrame()
    addr.URI = _uri("frame", "alpha_address")
    addr.name = "Alpha Address"
    addr.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(addr)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = addr.URI
    objs.append(edge_ef)

    zip_slot = KGTextSlot()
    zip_slot.URI = _uri("slot", "alpha_zip")
    zip_slot.kGSlotType = ZIPCODE_SLOT_TYPE
    zip_slot.textSlotValue = "94105"
    objs.append(zip_slot)

    edge_zs = Edge_hasKGSlot()
    edge_zs.URI = _edge_uri()
    edge_zs.edgeSource = addr.URI
    edge_zs.edgeDestination = zip_slot.URI
    objs.append(edge_zs)

    city_slot = KGTextSlot()
    city_slot.URI = _uri("slot", "alpha_city")
    city_slot.kGSlotType = CITY_SLOT_TYPE
    city_slot.textSlotValue = "San Francisco"
    objs.append(city_slot)

    edge_cs = Edge_hasKGSlot()
    edge_cs.URI = _edge_uri()
    edge_cs.edgeSource = addr.URI
    edge_cs.edgeDestination = city_slot.URI
    objs.append(edge_cs)

    # --- CompanyInfoFrame ---
    comp = KGFrame()
    comp.URI = _uri("frame", "alpha_company")
    comp.name = "Alpha Company Info"
    comp.kGFrameType = COMPANY_INFO_FRAME_TYPE
    objs.append(comp)

    edge_ec = Edge_hasEntityKGFrame()
    edge_ec.URI = _edge_uri()
    edge_ec.edgeSource = entity.URI
    edge_ec.edgeDestination = comp.URI
    objs.append(edge_ec)

    ind_slot = KGTextSlot()
    ind_slot.URI = _uri("slot", "alpha_industry")
    ind_slot.kGSlotType = INDUSTRY_SLOT_TYPE
    ind_slot.textSlotValue = "Technology"
    objs.append(ind_slot)

    edge_is = Edge_hasKGSlot()
    edge_is.URI = _edge_uri()
    edge_is.edgeSource = comp.URI
    edge_is.edgeDestination = ind_slot.URI
    objs.append(edge_is)

    return objs


def _build_beta_llc() -> List[GraphObject]:
    """AddressFrame(ZipCode=10005, City=NY), CompanyInfoFrame(Industry=Finance)."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "beta_llc")
    entity.name = "Beta LLC"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
    objs.append(entity)

    # --- AddressFrame ---
    addr = KGFrame()
    addr.URI = _uri("frame", "beta_address")
    addr.name = "Beta Address"
    addr.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(addr)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = addr.URI
    objs.append(edge_ef)

    zip_slot = KGTextSlot()
    zip_slot.URI = _uri("slot", "beta_zip")
    zip_slot.kGSlotType = ZIPCODE_SLOT_TYPE
    zip_slot.textSlotValue = "10005"
    objs.append(zip_slot)

    edge_zs = Edge_hasKGSlot()
    edge_zs.URI = _edge_uri()
    edge_zs.edgeSource = addr.URI
    edge_zs.edgeDestination = zip_slot.URI
    objs.append(edge_zs)

    city_slot = KGTextSlot()
    city_slot.URI = _uri("slot", "beta_city")
    city_slot.kGSlotType = CITY_SLOT_TYPE
    city_slot.textSlotValue = "New York"
    objs.append(city_slot)

    edge_cs = Edge_hasKGSlot()
    edge_cs.URI = _edge_uri()
    edge_cs.edgeSource = addr.URI
    edge_cs.edgeDestination = city_slot.URI
    objs.append(edge_cs)

    # --- CompanyInfoFrame ---
    comp = KGFrame()
    comp.URI = _uri("frame", "beta_company")
    comp.name = "Beta Company Info"
    comp.kGFrameType = COMPANY_INFO_FRAME_TYPE
    objs.append(comp)

    edge_ec = Edge_hasEntityKGFrame()
    edge_ec.URI = _edge_uri()
    edge_ec.edgeSource = entity.URI
    edge_ec.edgeDestination = comp.URI
    objs.append(edge_ec)

    ind_slot = KGTextSlot()
    ind_slot.URI = _uri("slot", "beta_industry")
    ind_slot.kGSlotType = INDUSTRY_SLOT_TYPE
    ind_slot.textSlotValue = "Finance"
    objs.append(ind_slot)

    edge_is = Edge_hasKGSlot()
    edge_is.URI = _edge_uri()
    edge_is.edgeSource = comp.URI
    edge_is.edgeDestination = ind_slot.URI
    objs.append(edge_is)

    return objs


def _build_gamma_inc() -> List[GraphObject]:
    """AddressFrame(City=Boston, NO ZipCodeSlot), CompanyInfoFrame(Industry=Healthcare)."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "gamma_inc")
    entity.name = "Gamma Inc"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
    objs.append(entity)

    # --- AddressFrame (no ZipCodeSlot) ---
    addr = KGFrame()
    addr.URI = _uri("frame", "gamma_address")
    addr.name = "Gamma Address"
    addr.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(addr)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = addr.URI
    objs.append(edge_ef)

    city_slot = KGTextSlot()
    city_slot.URI = _uri("slot", "gamma_city")
    city_slot.kGSlotType = CITY_SLOT_TYPE
    city_slot.textSlotValue = "Boston"
    objs.append(city_slot)

    edge_cs = Edge_hasKGSlot()
    edge_cs.URI = _edge_uri()
    edge_cs.edgeSource = addr.URI
    edge_cs.edgeDestination = city_slot.URI
    objs.append(edge_cs)

    # --- CompanyInfoFrame ---
    comp = KGFrame()
    comp.URI = _uri("frame", "gamma_company")
    comp.name = "Gamma Company Info"
    comp.kGFrameType = COMPANY_INFO_FRAME_TYPE
    objs.append(comp)

    edge_ec = Edge_hasEntityKGFrame()
    edge_ec.URI = _edge_uri()
    edge_ec.edgeSource = entity.URI
    edge_ec.edgeDestination = comp.URI
    objs.append(edge_ec)

    ind_slot = KGTextSlot()
    ind_slot.URI = _uri("slot", "gamma_industry")
    ind_slot.kGSlotType = INDUSTRY_SLOT_TYPE
    ind_slot.textSlotValue = "Healthcare"
    objs.append(ind_slot)

    edge_is = Edge_hasKGSlot()
    edge_is.URI = _edge_uri()
    edge_is.edgeSource = comp.URI
    edge_is.edgeDestination = ind_slot.URI
    objs.append(edge_is)

    return objs


def _build_delta_co() -> List[GraphObject]:
    """AddressFrame(ZipCodeSlot exists but empty, City=Austin), CompanyInfoFrame(Industry=Energy)."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "delta_co")
    entity.name = "Delta Co"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
    objs.append(entity)

    # --- AddressFrame ---
    addr = KGFrame()
    addr.URI = _uri("frame", "delta_address")
    addr.name = "Delta Address"
    addr.kGFrameType = ADDRESS_FRAME_TYPE
    objs.append(addr)

    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = entity.URI
    edge_ef.edgeDestination = addr.URI
    objs.append(edge_ef)

    # ZipCodeSlot exists but textSlotValue is NOT set
    zip_slot = KGTextSlot()
    zip_slot.URI = _uri("slot", "delta_zip")
    zip_slot.kGSlotType = ZIPCODE_SLOT_TYPE
    # deliberately NOT setting zip_slot.textSlotValue
    objs.append(zip_slot)

    edge_zs = Edge_hasKGSlot()
    edge_zs.URI = _edge_uri()
    edge_zs.edgeSource = addr.URI
    edge_zs.edgeDestination = zip_slot.URI
    objs.append(edge_zs)

    city_slot = KGTextSlot()
    city_slot.URI = _uri("slot", "delta_city")
    city_slot.kGSlotType = CITY_SLOT_TYPE
    city_slot.textSlotValue = "Austin"
    objs.append(city_slot)

    edge_cs = Edge_hasKGSlot()
    edge_cs.URI = _edge_uri()
    edge_cs.edgeSource = addr.URI
    edge_cs.edgeDestination = city_slot.URI
    objs.append(edge_cs)

    # --- CompanyInfoFrame ---
    comp = KGFrame()
    comp.URI = _uri("frame", "delta_company")
    comp.name = "Delta Company Info"
    comp.kGFrameType = COMPANY_INFO_FRAME_TYPE
    objs.append(comp)

    edge_ec = Edge_hasEntityKGFrame()
    edge_ec.URI = _edge_uri()
    edge_ec.edgeSource = entity.URI
    edge_ec.edgeDestination = comp.URI
    objs.append(edge_ec)

    ind_slot = KGTextSlot()
    ind_slot.URI = _uri("slot", "delta_industry")
    ind_slot.kGSlotType = INDUSTRY_SLOT_TYPE
    ind_slot.textSlotValue = "Energy"
    objs.append(ind_slot)

    edge_is = Edge_hasKGSlot()
    edge_is.URI = _edge_uri()
    edge_is.edgeSource = comp.URI
    edge_is.edgeDestination = ind_slot.URI
    objs.append(edge_is)

    return objs


def _build_epsilon_ltd() -> List[GraphObject]:
    """NO AddressFrame. CompanyInfoFrame(Industry=Technology) only."""
    objs: List[GraphObject] = []
    entity = KGEntity()
    entity.URI = _uri("entity", "epsilon_ltd")
    entity.name = "Epsilon Ltd"
    entity.kGEntityType = "http://vital.ai/ontology/haley-ai-kg#OrganizationEntity"
    objs.append(entity)

    # --- CompanyInfoFrame only ---
    comp = KGFrame()
    comp.URI = _uri("frame", "epsilon_company")
    comp.name = "Epsilon Company Info"
    comp.kGFrameType = COMPANY_INFO_FRAME_TYPE
    objs.append(comp)

    edge_ec = Edge_hasEntityKGFrame()
    edge_ec.URI = _edge_uri()
    edge_ec.edgeSource = entity.URI
    edge_ec.edgeDestination = comp.URI
    objs.append(edge_ec)

    ind_slot = KGTextSlot()
    ind_slot.URI = _uri("slot", "epsilon_industry")
    ind_slot.kGSlotType = INDUSTRY_SLOT_TYPE
    ind_slot.textSlotValue = "Technology"
    objs.append(ind_slot)

    edge_is = Edge_hasKGSlot()
    edge_is.URI = _edge_uri()
    edge_is.edgeSource = comp.URI
    edge_is.edgeDestination = ind_slot.URI
    objs.append(edge_is)

    return objs


# ---------------------------------------------------------------------------
# Entity URIs (deterministic — must match _uri("entity", ...) above)
# ---------------------------------------------------------------------------
ALPHA_URI = _uri("entity", "alpha_corp")
BETA_URI = _uri("entity", "beta_llc")
GAMMA_URI = _uri("entity", "gamma_inc")
DELTA_URI = _uri("entity", "delta_co")
EPSILON_URI = _uri("entity", "epsilon_ltd")

ALL_ENTITY_BUILDERS = [
    ("Alpha Corp", _build_alpha_corp),
    ("Beta LLC", _build_beta_llc),
    ("Gamma Inc", _build_gamma_inc),
    ("Delta Co", _build_delta_co),
    ("Epsilon Ltd", _build_epsilon_ltd),
]


def _entity_uris_from_response(response) -> Set[str]:
    """Extract entity URIs from a KGQueryResponse."""
    uris: Set[str] = set()
    if response.frame_connections:
        for conn in response.frame_connections:
            if conn.source_entity_uri:
                uris.add(conn.source_entity_uri)
    return uris


def _short(uri: str) -> str:
    """Shorten a URI for logging."""
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


class SlotNegationTester:
    """Integration tests for frame/slot negation via the VitalGraph client."""

    def __init__(self, client, query_mode: str = "edge"):
        self.client = client
        self.query_mode = query_mode

    # ------------------------------------------------------------------
    # Data setup
    # ------------------------------------------------------------------

    async def setup_data(self, space_id: str, graph_id: str) -> bool:
        """Create all 5 test entities. Returns True on success."""
        logger.info("  Creating 5 test entities with controlled frame/slot structures...")

        for name, builder in ALL_ENTITY_BUILDERS:
            objs = builder()
            entity_uri = [str(o.URI) for o in objs if isinstance(o, KGEntity)][0]
            logger.info(f"    Creating {name} ({_short(entity_uri)}) — {len(objs)} objects")

            response = await self.client.kgentities.create_kgentities(
                space_id=space_id,
                graph_id=graph_id,
                objects=objs,
            )
            if not response.is_success:
                logger.error(f"    FAILED to create {name}: {response.error_message}")
                return False
            logger.info(f"    OK — stored {response.count} objects")

        logger.info("  All 5 entities created.\n")
        return True

    # ------------------------------------------------------------------
    # Query helper
    # ------------------------------------------------------------------

    async def _query(self, space_id, graph_id, frame_criteria_list, page_size=50):
        import json
        from vitalgraph.model.kgqueries_model import KGQueryCriteria, KGQueryRequest

        criteria = KGQueryCriteria(
            query_type="frame",
            query_mode=self.query_mode,
            source_entity_criteria=None,
            source_entity_uris=None,
            destination_entity_criteria=None,
            destination_entity_uris=None,
            relation_type_uris=None,
            direction="outgoing",
            source_frame_criteria=None,
            destination_frame_criteria=None,
            frame_criteria=frame_criteria_list,
            exclude_self_connections=True,
        )

        request = KGQueryRequest(criteria=criteria, page_size=page_size, offset=0)
        logger.info("    KGQuery request:\n%s", json.dumps(
            request.model_dump(exclude_none=True), indent=2))

        return await self.client.kgqueries.query_connections(
            space_id=space_id,
            graph_id=graph_id,
            criteria=criteria,
            page_size=page_size,
        )

    # ------------------------------------------------------------------
    # Individual tests
    # ------------------------------------------------------------------

    async def _test_frame_negate_no_address(self, space_id, graph_id) -> Dict[str, Any]:
        """Test 1: entities WITHOUT AddressFrame → expect [epsilon_ltd]."""
        logger.info("  Test 1: Frame negate — entities without AddressFrame")
        try:
            from vitalgraph.model.kgentities_model import FrameCriteria

            resp = await self._query(space_id, graph_id, [
                FrameCriteria(frame_type=ADDRESS_FRAME_TYPE, negate=True, slot_criteria=None, frame_criteria=None),
            ])
            got = _entity_uris_from_response(resp)
            expected = {EPSILON_URI}
            ok = got == expected
            logger.info(f"    Expected: {set(map(_short, expected))}")
            logger.info(f"    Got:      {set(map(_short, got))}")
            logger.info(f"    {'PASS' if ok else 'FAIL'}")
            return {"name": "Frame negate — no AddressFrame", "passed": ok,
                    "expected": expected, "got": got}
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            return {"name": "Frame negate — no AddressFrame", "passed": False, "error": str(e)}

    async def _test_slot_not_exists_zipcode(self, space_id, graph_id) -> Dict[str, Any]:
        """Test 2: AddressFrame present but ZipCodeSlot does NOT exist → expect [gamma_inc]."""
        logger.info("  Test 2: Slot not_exists — AddressFrame without ZipCodeSlot")
        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            resp = await self._query(space_id, graph_id, [
                FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[
                        SlotCriteria(slot_type=ZIPCODE_SLOT_TYPE, slot_class_uri=None, value=None, comparator="not_exists"),
                    ],
                    frame_criteria=None,
                ),
            ])
            got = _entity_uris_from_response(resp)
            expected = {GAMMA_URI}
            ok = got == expected
            logger.info(f"    Expected: {set(map(_short, expected))}")
            logger.info(f"    Got:      {set(map(_short, got))}")
            logger.info(f"    {'PASS' if ok else 'FAIL'}")
            return {"name": "Slot not_exists — no ZipCodeSlot", "passed": ok,
                    "expected": expected, "got": got}
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            return {"name": "Slot not_exists — no ZipCodeSlot", "passed": False, "error": str(e)}

    async def _test_slot_is_empty_zipcode(self, space_id, graph_id) -> Dict[str, Any]:
        """Test 3: ZipCodeSlot exists but has no value → expect [delta_co]."""
        logger.info("  Test 3: Slot is_empty — ZipCodeSlot present but no value")
        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            resp = await self._query(space_id, graph_id, [
                FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type=ZIPCODE_SLOT_TYPE,
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value=None,
                            comparator="is_empty",
                        ),
                    ],
                    frame_criteria=None,
                ),
            ])
            got = _entity_uris_from_response(resp)
            expected = {DELTA_URI}
            ok = got == expected
            logger.info(f"    Expected: {set(map(_short, expected))}")
            logger.info(f"    Got:      {set(map(_short, got))}")
            logger.info(f"    {'PASS' if ok else 'FAIL'}")
            return {"name": "Slot is_empty — ZipCodeSlot no value", "passed": ok,
                    "expected": expected, "got": got}
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            return {"name": "Slot is_empty — ZipCodeSlot no value", "passed": False, "error": str(e)}

    async def _test_frame_negate_with_slot_value(self, space_id, graph_id) -> Dict[str, Any]:
        """Test 4: NOT (AddressFrame with ZipCode=94105) → all except alpha_corp."""
        logger.info("  Test 4: Frame negate with slot value — NOT AddressFrame(ZipCode=94105)")
        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            resp = await self._query(space_id, graph_id, [
                FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=True,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type=ZIPCODE_SLOT_TYPE,
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="94105",
                            comparator="eq",
                        ),
                    ],
                    frame_criteria=None,
                ),
            ])
            got = _entity_uris_from_response(resp)
            expected = {BETA_URI, GAMMA_URI, DELTA_URI, EPSILON_URI}
            ok = got == expected
            logger.info(f"    Expected: {set(map(_short, expected))}")
            logger.info(f"    Got:      {set(map(_short, got))}")
            logger.info(f"    {'PASS' if ok else 'FAIL'}")
            return {"name": "Frame negate with slot value", "passed": ok,
                    "expected": expected, "got": got}
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            return {"name": "Frame negate with slot value", "passed": False, "error": str(e)}

    async def _test_mixed_positive_and_negated_frames(self, space_id, graph_id) -> Dict[str, Any]:
        """Test 5: CompanyInfoFrame(Industry=Technology) AND NOT AddressFrame → [epsilon_ltd]."""
        logger.info("  Test 5: Mixed — CompanyInfoFrame(Industry=Technology) AND NOT AddressFrame")
        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            resp = await self._query(space_id, graph_id, [
                FrameCriteria(
                    frame_type=COMPANY_INFO_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type=INDUSTRY_SLOT_TYPE,
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="Technology",
                            comparator="eq",
                        ),
                    ],
                    frame_criteria=None,
                ),
                FrameCriteria(frame_type=ADDRESS_FRAME_TYPE, negate=True, slot_criteria=None, frame_criteria=None),
            ])
            got = _entity_uris_from_response(resp)
            expected = {EPSILON_URI}
            ok = got == expected
            logger.info(f"    Expected: {set(map(_short, expected))}")
            logger.info(f"    Got:      {set(map(_short, got))}")
            logger.info(f"    {'PASS' if ok else 'FAIL'}")
            return {"name": "Mixed positive + negated frames", "passed": ok,
                    "expected": expected, "got": got}
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            return {"name": "Mixed positive + negated frames", "passed": False, "error": str(e)}

    async def _test_positive_control_city_boston(self, space_id, graph_id) -> Dict[str, Any]:
        """Test 6 (positive control): AddressFrame with City=Boston → [gamma_inc]."""
        logger.info("  Test 6: Positive control — AddressFrame with City=Boston")
        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            resp = await self._query(space_id, graph_id, [
                FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type=CITY_SLOT_TYPE,
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="Boston",
                            comparator="eq",
                        ),
                    ],
                    frame_criteria=None,
                ),
            ])
            got = _entity_uris_from_response(resp)
            expected = {GAMMA_URI}
            ok = got == expected
            logger.info(f"    Expected: {set(map(_short, expected))}")
            logger.info(f"    Got:      {set(map(_short, got))}")
            logger.info(f"    {'PASS' if ok else 'FAIL'}")
            return {"name": "Positive control — City=Boston", "passed": ok,
                    "expected": expected, "got": got}
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            return {"name": "Positive control — City=Boston", "passed": False, "error": str(e)}

    async def _test_mixed_eq_and_not_exists_same_frame(self, space_id, graph_id) -> Dict[str, Any]:
        """Test 7: AddressFrame with City=Boston AND ZipCodeSlot not_exists → [gamma_inc]."""
        logger.info("  Test 7: Mixed eq + not_exists in same frame — City=Boston AND no ZipCodeSlot")
        try:
            from vitalgraph.model.kgentities_model import FrameCriteria, SlotCriteria

            resp = await self._query(space_id, graph_id, [
                FrameCriteria(
                    frame_type=ADDRESS_FRAME_TYPE,
                    negate=False,
                    slot_criteria=[
                        SlotCriteria(
                            slot_type=CITY_SLOT_TYPE,
                            slot_class_uri="http://vital.ai/ontology/haley-ai-kg#KGTextSlot",
                            value="Boston",
                            comparator="eq",
                        ),
                        SlotCriteria(slot_type=ZIPCODE_SLOT_TYPE, slot_class_uri=None, value=None, comparator="not_exists"),
                    ],
                    frame_criteria=None,
                ),
            ])
            got = _entity_uris_from_response(resp)
            expected = {GAMMA_URI}
            ok = got == expected
            logger.info(f"    Expected: {set(map(_short, expected))}")
            logger.info(f"    Got:      {set(map(_short, got))}")
            logger.info(f"    {'PASS' if ok else 'FAIL'}")
            return {"name": "Mixed eq + not_exists same frame", "passed": ok,
                    "expected": expected, "got": got}
        except Exception as e:
            logger.error(f"    ERROR: {e}")
            return {"name": "Mixed eq + not_exists same frame", "passed": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    async def run_tests(self, space_id: str, graph_id: str) -> Dict[str, Any]:
        """Run all slot negation integration tests. Returns results dict."""
        logger.info("=" * 80)
        logger.info("  Slot Negation Integration Tests")
        logger.info("=" * 80 + "\n")

        results: List[Dict[str, Any]] = []
        errors: List[str] = []

        tests = [
            self._test_frame_negate_no_address,
            self._test_slot_not_exists_zipcode,
            self._test_slot_is_empty_zipcode,
            self._test_frame_negate_with_slot_value,
            self._test_mixed_positive_and_negated_frames,
            self._test_positive_control_city_boston,
            self._test_mixed_eq_and_not_exists_same_frame,
        ]

        for test_fn in tests:
            r = await test_fn(space_id, graph_id)
            results.append(r)
            if not r.get("passed"):
                errors.append(r.get("error") or f"{r['name']} — expected≠got")
            logger.info("")

        passed = sum(1 for r in results if r["passed"])
        logger.info(f"  Slot negation tests: {passed}/{len(results)} passed\n")

        return {
            "test_name": "Slot Negation Integration",
            "tests_run": len(results),
            "tests_passed": passed,
            "tests_failed": len(results) - passed,
            "errors": errors,
            "results": results,
        }
