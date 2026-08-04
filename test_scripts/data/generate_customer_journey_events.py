#!/usr/bin/env python3
"""
Customer Journey Event Timeline — Test Dataset Generator
=========================================================

Generates a test dataset of event entities forming a customer journey
for visualizing with the Event Timeline (Cola L→R) layout.

Each event is a KGEntity with:
- kGEntityType: sub-type of EventEntity (ChannelArrivalEvent, PageViewEvent, etc.)
- kGProvenanceType: journey identifier
- kGActionTypeList: category tags (entry_point, exit_point, milestone, etc.)
- An EventDetailsFrame containing:
  - EventTimestampSlot (KGDateTimeSlot) — timeline ordering
  - EventChannelSlot (KGTextSlot) — channel info
  - EventActionSlot (KGTextSlot) — action description

Events are linked sequentially via Edge_hasKGRelation (type: FollowsEvent).

Output: One .vital block file suitable for import into a VitalGraph space/graph.

Usage:
    python generate_customer_journey_events.py                    # default journey
    python generate_customer_journey_events.py --include-branches # branching path
    python generate_customer_journey_events.py --dry-run          # stats only
    python generate_customer_journey_events.py --output-dir /tmp  # custom dir

See: planning/planning_ui/event_timeline_visualization_plan.md
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.block.vital_block import VitalBlock
from vital_ai_vitalsigns.block.vital_block_file import VitalBlockFile
from vital_ai_vitalsigns.block.vital_block_writer import VitalBlockWriter

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation


# ---------------------------------------------------------------------------
# Constants — KG Type URIs
# ---------------------------------------------------------------------------

# Base URI namespace
_BASE = "urn:vitalgraph:journey"

# Entity Types (EventEntity hierarchy)
ENTITY_TYPE_EVENT = "urn:entity_type:EventEntity"
ENTITY_TYPE_CHANNEL_ARRIVAL = "urn:entity_type:ChannelArrivalEvent"
ENTITY_TYPE_PAGE_VIEW = "urn:entity_type:PageViewEvent"
ENTITY_TYPE_APPLICATION = "urn:entity_type:ApplicationEvent"
ENTITY_TYPE_SUPPORT_INTERACTION = "urn:entity_type:SupportInteractionEvent"
ENTITY_TYPE_TRANSACTION = "urn:entity_type:TransactionEvent"
ENTITY_TYPE_CONFIRMATION = "urn:entity_type:ConfirmationEvent"

# Non-event entity types (connected to events via relations)
ENTITY_TYPE_PRODUCT = "urn:entity_type:Product"
ENTITY_TYPE_SUPPORT_REP = "urn:entity_type:SupportRep"
ENTITY_TYPE_AD_CAMPAIGN = "urn:entity_type:AdCampaign"
ENTITY_TYPE_PAYMENT_METHOD = "urn:entity_type:PaymentMethod"
ENTITY_TYPE_PAGE = "urn:entity_type:WebPage"

# Frame Types
FRAME_TYPE_EVENT_DETAILS = "urn:frame_type:EventDetailsFrame"

# Slot Types
SLOT_TYPE_TIMESTAMP = "urn:slot_type:EventTimestampSlot"
SLOT_TYPE_CHANNEL = "urn:slot_type:EventChannelSlot"
SLOT_TYPE_ACTION = "urn:slot_type:EventActionSlot"
SLOT_TYPE_PAGE = "urn:slot_type:EventPageSlot"
SLOT_TYPE_OUTCOME = "urn:slot_type:EventOutcomeSlot"

# Action Type Tags
ACTION_ENTRY_POINT = "urn:action:entry_point"
ACTION_EXIT_POINT = "urn:action:exit_point"
ACTION_MILESTONE = "urn:action:milestone"
ACTION_SUPPORT_INTERACTION = "urn:action:support_interaction"
ACTION_GOOGLE_ADS_CHANNEL = "urn:action:google_ads_channel"
ACTION_COMPLETED = "urn:action:completed"
ACTION_ABANDONED = "urn:action:abandoned"

# Relation Types
RELATION_TYPE_FOLLOWS = "urn:relation_type:FollowsEvent"
RELATION_TYPE_INVOLVES_PRODUCT = "urn:relation_type:InvolvesProduct"
RELATION_TYPE_ASSISTED_BY = "urn:relation_type:AssistedBy"
RELATION_TYPE_SOURCED_FROM = "urn:relation_type:SourcedFrom"
RELATION_TYPE_PAID_WITH = "urn:relation_type:PaidWith"
RELATION_TYPE_ON_PAGE = "urn:relation_type:OnPage"

# Provenance (Journey ID)
PROVENANCE_JOURNEY_DEMO = "urn:provenance:journey_onboarding_demo_001"

BLOCK_SIZE = 100


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------

def _uri(kind: str, name: str) -> str:
    return f"{_BASE}:{kind}:{name}"


def _edge_uri() -> str:
    return f"{_BASE}:edge:{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Object builders
# ---------------------------------------------------------------------------

def _event_entity(
    event_id: str,
    name: str,
    entity_type: str,
    entity_type_description: str,
    action_types: Optional[List[str]] = None,
    provenance: str = PROVENANCE_JOURNEY_DEMO,
) -> KGEntity:
    """Create an event KGEntity."""
    ent = KGEntity()
    ent.URI = _uri("event", event_id)
    ent.name = name
    ent.kGEntityType = entity_type
    ent.kGEntityTypeDescription = entity_type_description
    if action_types:
        ent.kGActionTypeList = action_types
    ent.kGProvenanceType = provenance
    return ent


def _event_details_frame(
    event: KGEntity,
    timestamp: str,
    channel: Optional[str] = None,
    action: Optional[str] = None,
    page: Optional[str] = None,
    outcome: Optional[str] = None,
) -> List[GraphObject]:
    """Create an EventDetailsFrame with slots and structural edges."""
    objects: List[GraphObject] = []

    # Frame
    frame = KGFrame()
    frame.URI = _uri("frame", f"{event.URI.split(':')[-1]}_details")
    frame.name = f"{event.name} Details"
    frame.kGFrameType = FRAME_TYPE_EVENT_DETAILS
    frame.kGFrameTypeDescription = "Event Details"
    frame.kGFormType = "http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect"
    frame.kGGraphURI = str(event.URI)
    frame.frameGraphURI = str(frame.URI)
    objects.append(frame)

    # Edge: entity → frame
    edge_ef = Edge_hasEntityKGFrame()
    edge_ef.URI = _edge_uri()
    edge_ef.edgeSource = str(event.URI)
    edge_ef.edgeDestination = str(frame.URI)
    edge_ef.kGGraphURI = str(event.URI)
    objects.append(edge_ef)

    # Timestamp slot (required)
    ts_slot = KGDateTimeSlot()
    ts_slot.URI = _uri("slot", f"{event.URI.split(':')[-1]}_timestamp")
    ts_slot.name = "EventTimestamp"
    ts_slot.kGSlotType = SLOT_TYPE_TIMESTAMP
    ts_slot.kGSlotTypeDescription = "Event Timestamp"
    ts_slot.dateTimeSlotValue = timestamp
    ts_slot.frameGraphURI = str(frame.URI)
    ts_slot.kGGraphURI = str(event.URI)
    objects.append(ts_slot)
    objects.append(_slot_edge(frame, ts_slot, event))

    # Channel slot (optional)
    if channel:
        ch_slot = KGTextSlot()
        ch_slot.URI = _uri("slot", f"{event.URI.split(':')[-1]}_channel")
        ch_slot.name = "EventChannel"
        ch_slot.kGSlotType = SLOT_TYPE_CHANNEL
        ch_slot.kGSlotTypeDescription = "Event Channel"
        ch_slot.textSlotValue = channel
        ch_slot.frameGraphURI = str(frame.URI)
        ch_slot.kGGraphURI = str(event.URI)
        objects.append(ch_slot)
        objects.append(_slot_edge(frame, ch_slot, event))

    # Action slot (optional)
    if action:
        act_slot = KGTextSlot()
        act_slot.URI = _uri("slot", f"{event.URI.split(':')[-1]}_action")
        act_slot.name = "EventAction"
        act_slot.kGSlotType = SLOT_TYPE_ACTION
        act_slot.kGSlotTypeDescription = "Event Action"
        act_slot.textSlotValue = action
        act_slot.frameGraphURI = str(frame.URI)
        act_slot.kGGraphURI = str(event.URI)
        objects.append(act_slot)
        objects.append(_slot_edge(frame, act_slot, event))

    # Page slot (optional)
    if page:
        pg_slot = KGTextSlot()
        pg_slot.URI = _uri("slot", f"{event.URI.split(':')[-1]}_page")
        pg_slot.name = "EventPage"
        pg_slot.kGSlotType = SLOT_TYPE_PAGE
        pg_slot.kGSlotTypeDescription = "Event Page"
        pg_slot.textSlotValue = page
        pg_slot.frameGraphURI = str(frame.URI)
        pg_slot.kGGraphURI = str(event.URI)
        objects.append(pg_slot)
        objects.append(_slot_edge(frame, pg_slot, event))

    # Outcome slot (optional)
    if outcome:
        out_slot = KGTextSlot()
        out_slot.URI = _uri("slot", f"{event.URI.split(':')[-1]}_outcome")
        out_slot.name = "EventOutcome"
        out_slot.kGSlotType = SLOT_TYPE_OUTCOME
        out_slot.kGSlotTypeDescription = "Event Outcome"
        out_slot.textSlotValue = outcome
        out_slot.frameGraphURI = str(frame.URI)
        out_slot.kGGraphURI = str(event.URI)
        objects.append(out_slot)
        objects.append(_slot_edge(frame, out_slot, event))

    return objects


def _slot_edge(frame: KGFrame, slot, owner_entity: KGEntity) -> Edge_hasKGSlot:
    """Create Edge_hasKGSlot connecting frame to slot."""
    edge = Edge_hasKGSlot()
    edge.URI = _edge_uri()
    edge.edgeSource = str(frame.URI)
    edge.edgeDestination = str(slot.URI)
    edge.frameGraphURI = str(frame.URI)
    edge.kGGraphURI = str(owner_entity.URI)
    return edge


def _follows_relation(source: KGEntity, target: KGEntity) -> Edge_hasKGRelation:
    """Create a sequential 'follows' relation between events."""
    rel = Edge_hasKGRelation()
    rel.URI = _edge_uri()
    rel.edgeSource = str(source.URI)
    rel.edgeDestination = str(target.URI)
    rel.kGRelationType = RELATION_TYPE_FOLLOWS
    rel.kGRelationTypeDescription = "Follows Event"
    return rel


def _plain_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    entity_type_description: str,
) -> KGEntity:
    """Create a non-event KGEntity (product, person, etc.)."""
    ent = KGEntity()
    ent.URI = _uri("ref", entity_id)
    ent.name = name
    ent.kGEntityType = entity_type
    ent.kGEntityTypeDescription = entity_type_description
    return ent


def _typed_relation(
    source: KGEntity,
    target: KGEntity,
    relation_type: str,
    relation_desc: str,
) -> Edge_hasKGRelation:
    """Create a typed relation between any two entities."""
    rel = Edge_hasKGRelation()
    rel.URI = _edge_uri()
    rel.edgeSource = str(source.URI)
    rel.edgeDestination = str(target.URI)
    rel.kGRelationType = relation_type
    rel.kGRelationTypeDescription = relation_desc
    return rel


# ---------------------------------------------------------------------------
# Journey dataset generators
# ---------------------------------------------------------------------------

def generate_onboarding_journey(include_branches: bool = False) -> List[GraphObject]:
    """
    Generate the 'New Customer Onboarding' journey.

    8 events in linear sequence, optionally with a branch at event 4.
    """
    objects: List[GraphObject] = []
    t0 = datetime(2026, 7, 10, 10, 0, 0)

    # --- Event definitions ---
    events_spec = [
        {
            "id": "01_ad_click",
            "name": "Ad Click",
            "type": ENTITY_TYPE_CHANNEL_ARRIVAL,
            "type_desc": "Channel Arrival Event",
            "tags": [ACTION_ENTRY_POINT, ACTION_GOOGLE_ADS_CHANNEL],
            "offset_sec": 0,
            "channel": "google_ads",
            "action": "click",
            "page": "/landing",
        },
        {
            "id": "02_landing_page",
            "name": "Landing Page View",
            "type": ENTITY_TYPE_PAGE_VIEW,
            "type_desc": "Page View Event",
            "tags": [],
            "offset_sec": 10,
            "action": "page_view",
            "page": "/products",
        },
        {
            "id": "03_product_browse",
            "name": "Product Browse",
            "type": ENTITY_TYPE_PAGE_VIEW,
            "type_desc": "Page View Event",
            "tags": [],
            "offset_sec": 45,
            "action": "browse",
            "page": "/products/premium-plan",
        },
        {
            "id": "04_start_application",
            "name": "Start Application",
            "type": ENTITY_TYPE_APPLICATION,
            "type_desc": "Application Event",
            "tags": [],
            "offset_sec": 120,
            "action": "form_start",
            "page": "/apply",
        },
        {
            "id": "05_chat_with_rep",
            "name": "Chat with Rep",
            "type": ENTITY_TYPE_SUPPORT_INTERACTION,
            "type_desc": "Support Interaction Event",
            "tags": [ACTION_SUPPORT_INTERACTION],
            "offset_sec": 180,
            "action": "chat_start",
            "channel": "live_chat",
        },
        {
            "id": "06_submit_form",
            "name": "Submit Application",
            "type": ENTITY_TYPE_APPLICATION,
            "type_desc": "Application Event",
            "tags": [ACTION_MILESTONE],
            "offset_sec": 300,
            "action": "form_submit",
            "page": "/apply",
            "outcome": "completed",
        },
        {
            "id": "07_payment",
            "name": "Payment",
            "type": ENTITY_TYPE_TRANSACTION,
            "type_desc": "Transaction Event",
            "tags": [ACTION_MILESTONE],
            "offset_sec": 360,
            "action": "payment",
            "page": "/checkout",
            "outcome": "completed",
        },
        {
            "id": "08_confirmation",
            "name": "Confirmation",
            "type": ENTITY_TYPE_CONFIRMATION,
            "type_desc": "Confirmation Event",
            "tags": [ACTION_EXIT_POINT, ACTION_COMPLETED],
            "offset_sec": 380,
            "action": "confirmation_view",
            "page": "/confirmation",
            "outcome": "completed",
        },
    ]

    # Build event entities and their frames/slots
    entities: List[KGEntity] = []
    for spec in events_spec:
        entity = _event_entity(
            event_id=spec["id"],
            name=spec["name"],
            entity_type=spec["type"],
            entity_type_description=spec["type_desc"],
            action_types=spec["tags"] if spec["tags"] else None,
        )
        entities.append(entity)
        objects.append(entity)

        timestamp = (t0 + timedelta(seconds=spec["offset_sec"])).strftime("%Y-%m-%dT%H:%M:%SZ")
        objects.extend(_event_details_frame(
            event=entity,
            timestamp=timestamp,
            channel=spec.get("channel"),
            action=spec.get("action"),
            page=spec.get("page"),
            outcome=spec.get("outcome"),
        ))

    # Sequential relations: 1→2→3→4→5→6→7→8
    for i in range(len(entities) - 1):
        objects.append(_follows_relation(entities[i], entities[i + 1]))

    # --- Non-event reference entities ---

    # Ad Campaign (connected to Ad Click)
    ad_campaign = _plain_entity("summer_promo", "Summer Promo 2026", ENTITY_TYPE_AD_CAMPAIGN, "Ad Campaign")
    objects.append(ad_campaign)
    objects.append(_typed_relation(entities[0], ad_campaign, RELATION_TYPE_SOURCED_FROM, "Sourced From"))

    # Product (connected to Product Browse, Start Application, Payment)
    product = _plain_entity("premium_plan", "Premium Plan", ENTITY_TYPE_PRODUCT, "Product")
    objects.append(product)
    objects.append(_typed_relation(entities[2], product, RELATION_TYPE_INVOLVES_PRODUCT, "Involves Product"))
    objects.append(_typed_relation(entities[3], product, RELATION_TYPE_INVOLVES_PRODUCT, "Involves Product"))
    objects.append(_typed_relation(entities[6], product, RELATION_TYPE_INVOLVES_PRODUCT, "Involves Product"))

    # Support Rep (connected to Chat with Rep)
    rep = _plain_entity("agent_maria", "Maria Garcia", ENTITY_TYPE_SUPPORT_REP, "Support Rep")
    objects.append(rep)
    objects.append(_typed_relation(entities[4], rep, RELATION_TYPE_ASSISTED_BY, "Assisted By"))

    # Payment Method (connected to Payment)
    payment_method = _plain_entity("visa_4242", "Visa ••4242", ENTITY_TYPE_PAYMENT_METHOD, "Payment Method")
    objects.append(payment_method)
    objects.append(_typed_relation(entities[6], payment_method, RELATION_TYPE_PAID_WITH, "Paid With"))

    # Web Pages (connected to Page View events)
    page_landing = _plain_entity("page_landing", "/landing", ENTITY_TYPE_PAGE, "Web Page")
    page_products = _plain_entity("page_products", "/products", ENTITY_TYPE_PAGE, "Web Page")
    page_apply = _plain_entity("page_apply", "/apply", ENTITY_TYPE_PAGE, "Web Page")
    page_checkout = _plain_entity("page_checkout", "/checkout", ENTITY_TYPE_PAGE, "Web Page")
    objects.extend([page_landing, page_products, page_apply, page_checkout])
    objects.append(_typed_relation(entities[0], page_landing, RELATION_TYPE_ON_PAGE, "On Page"))
    objects.append(_typed_relation(entities[1], page_products, RELATION_TYPE_ON_PAGE, "On Page"))
    objects.append(_typed_relation(entities[2], page_products, RELATION_TYPE_ON_PAGE, "On Page"))
    objects.append(_typed_relation(entities[3], page_apply, RELATION_TYPE_ON_PAGE, "On Page"))
    objects.append(_typed_relation(entities[5], page_apply, RELATION_TYPE_ON_PAGE, "On Page"))
    objects.append(_typed_relation(entities[6], page_checkout, RELATION_TYPE_ON_PAGE, "On Page"))

    # --- Optional branching variant ---
    if include_branches:
        # Alternate path from event 3 (Product Browse):
        # Main:   1→2→3→4→5→6→7→8
        # Branch: 3 → 4b_compare → 5b_support_call → 6b_return_to_app → (rejoins at 6: Submit)
        #
        # This tests: fork, parallel path, AND merge back into main flow.
        branch_events = [
            {
                "id": "04b_compare_plans",
                "name": "Compare Plans",
                "type": ENTITY_TYPE_PAGE_VIEW,
                "type_desc": "Page View Event",
                "tags": [],
                "offset_sec": 125,
                "action": "page_view",
                "page": "/compare",
            },
            {
                "id": "05b_support_call",
                "name": "Support Call",
                "type": ENTITY_TYPE_SUPPORT_INTERACTION,
                "type_desc": "Support Interaction Event",
                "tags": [ACTION_SUPPORT_INTERACTION],
                "offset_sec": 180,
                "action": "phone_call",
                "channel": "phone",
            },
            {
                "id": "06b_return_to_app",
                "name": "Return to Application",
                "type": ENTITY_TYPE_APPLICATION,
                "type_desc": "Application Event",
                "tags": [],
                "offset_sec": 280,
                "action": "form_resume",
                "page": "/apply",
            },
        ]

        branch_entities: List[KGEntity] = []
        for spec in branch_events:
            entity = _event_entity(
                event_id=spec["id"],
                name=spec["name"],
                entity_type=spec["type"],
                entity_type_description=spec["type_desc"],
                action_types=spec["tags"] if spec["tags"] else None,
            )
            branch_entities.append(entity)
            objects.append(entity)

            timestamp = (t0 + timedelta(seconds=spec["offset_sec"])).strftime("%Y-%m-%dT%H:%M:%SZ")
            objects.extend(_event_details_frame(
                event=entity,
                timestamp=timestamp,
                channel=spec.get("channel"),
                action=spec.get("action"),
                page=spec.get("page"),
                outcome=spec.get("outcome"),
            ))

        # Branch edges: fork from event 3, sequence through branch, rejoin at event 5 (Submit)
        objects.append(_follows_relation(entities[2], branch_entities[0]))  # Browse → Compare Plans
        objects.append(_follows_relation(branch_entities[0], branch_entities[1]))  # Compare → Support Call
        objects.append(_follows_relation(branch_entities[1], branch_entities[2]))  # Support Call → Return to App
        objects.append(_follows_relation(branch_entities[2], entities[5]))  # Return to App → Submit (rejoin)

        # Reference entities for branch
        page_compare = _plain_entity("page_compare", "/compare", ENTITY_TYPE_PAGE, "Web Page")
        objects.append(page_compare)
        objects.append(_typed_relation(branch_entities[0], page_compare, RELATION_TYPE_ON_PAGE, "On Page"))

        # Support rep also assists on branch call
        objects.append(_typed_relation(branch_entities[1], rep, RELATION_TYPE_ASSISTED_BY, "Assisted By"))

        # Branch also involves the product
        objects.append(_typed_relation(branch_entities[0], product, RELATION_TYPE_INVOLVES_PRODUCT, "Involves Product"))

    return objects


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------

def write_vital_block_file(objects: List[GraphObject], output_path: str):
    """Write GraphObjects to a .vital block file."""
    bf = VitalBlockFile(output_path)
    writer = VitalBlockWriter(bf)
    writer.write_header()

    for i in range(0, len(objects), BLOCK_SIZE):
        chunk = objects[i:i + BLOCK_SIZE]
        block = VitalBlock(chunk)
        writer.write_block(block)

    writer.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate customer journey event timeline test dataset"
    )
    parser.add_argument("--include-branches", action="store_true",
                        help="Include branching alternate path (abandon scenario)")
    parser.add_argument("--output-dir", "-o", type=str, default=None,
                        help="Output directory (default: generated_instances/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print statistics only, don't write file")
    args = parser.parse_args()

    # Resolve output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = Path(__file__).resolve().parent.parent.parent / "generated_instances"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate
    print("Generating Customer Journey Event Timeline dataset...")
    objects = generate_onboarding_journey(include_branches=args.include_branches)

    # Stats
    all_entities = [o for o in objects if isinstance(o, KGEntity)]
    event_entities = [e for e in all_entities if "Event" in str(e.kGEntityTypeDescription or "")]
    ref_entities = [e for e in all_entities if "Event" not in str(e.kGEntityTypeDescription or "")]
    frames = [o for o in objects if isinstance(o, KGFrame)]
    slots = [o for o in objects if isinstance(o, (KGTextSlot, KGDateTimeSlot, KGEntitySlot))]
    edges = [o for o in objects if isinstance(o, (Edge_hasEntityKGFrame, Edge_hasKGSlot, Edge_hasKGRelation))]

    print(f"  Event entities:    {len(event_entities)}")
    print(f"  Reference entities:{len(ref_entities)}")
    print(f"  Frames:            {len(frames)}")
    print(f"  Slots:             {len(slots)}")
    print(f"  Edges:             {len(edges)}")
    print(f"  Total objects:     {len(objects)}")
    if args.include_branches:
        print("  (includes branching alternate path)")

    if not args.dry_run:
        if args.include_branches:
            filename = "customer_journey_events_v3.vital"
        else:
            filename = "customer_journey_events_v2.vital"
        path = out_dir / filename
        write_vital_block_file(objects, str(path))
        print(f"\n  → {path}")
    else:
        print("\n  (dry run — no file written)")


if __name__ == "__main__":
    main()
