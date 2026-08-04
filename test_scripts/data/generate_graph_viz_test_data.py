#!/usr/bin/env python3
"""
Graph Visualization Test Data Generator
========================================

Generates small, hand-crafted graph datasets for testing the graph
visualization and session architecture.  Each dataset targets a specific
visualization pattern (binary frames, N-ary hubs, subframes, direct
relations, unary frames, top-level frames).

Output: One .vital block file per dataset, suitable for import via
``vitalgraphimport`` into the ``graph_viz_test`` space.

Datasets:
  A — People & Employment   (binary frames + relations)
  B — Research Project       (N-ary frame)
  C — Supply Chain           (mixed arity + subframes)
  D — Social Network         (pure Edge_hasKGRelation)
  E — Unary Frame            (annotation/tag pattern)
  F — Top-Level Frames       (Assertions, no owning entity)

Usage:
    python generate_graph_viz_test_data.py                     # all datasets
    python generate_graph_viz_test_data.py --dataset A         # one dataset
    python generate_graph_viz_test_data.py --output-dir /tmp   # custom dir

See: planning/planning_visualization/graph_session_architecture_plan.md §9
"""

import argparse
import os
import random
import sys
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.block.vital_block import VitalBlock
from vital_ai_vitalsigns.block.vital_block_file import VitalBlockFile
from vital_ai_vitalsigns.block.vital_block_writer import VitalBlockWriter

from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot
from ai_haley_kg_domain.model.KGIntegerSlot import KGIntegerSlot
from ai_haley_kg_domain.model.KGDoubleSlot import KGDoubleSlot
from ai_haley_kg_domain.model.KGDateTimeSlot import KGDateTimeSlot
from ai_haley_kg_domain.model.KGEntitySlot import KGEntitySlot
from ai_haley_kg_domain.model.KGDocument import KGDocument
from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.Edge_hasKGRelation import Edge_hasKGRelation


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------

_BASE = "urn:vitalgraph:graphviz"

def _uri(kind: str, name: str) -> str:
    return f"{_BASE}:{kind}:{name}"

def _edge_uri() -> str:
    return f"{_BASE}:edge:{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Object builders
# ---------------------------------------------------------------------------

def _entity(name: str, entity_type: str = "Person") -> KGEntity:
    ent = KGEntity()
    ent.URI = _uri("entity", name.replace(" ", "_"))
    ent.name = name
    ent.kGEntityType = f"urn:vitalgraph:type:{entity_type}"
    ent.kGEntityTypeDescription = entity_type
    return ent


def _document(name: str, description: str = "") -> KGDocument:
    doc = KGDocument()
    doc.URI = _uri("document", name.replace(" ", "_"))
    doc.name = name
    if description:
        doc.kGraphDescription = description
    return doc


def _frame(name: str, frame_type: str = "GenericFrame",
           owner_entity: Optional[KGEntity] = None) -> Tuple[KGFrame, List[GraphObject]]:
    """Create a KGFrame and optionally the Edge_hasEntityKGFrame.

    Returns (frame, [edge_or_empty_list]) so callers can extend a flat list.
    """
    fr = KGFrame()
    fr.URI = _uri("frame", name.replace(" ", "_"))
    fr.name = name
    fr.kGFrameType = f"urn:vitalgraph:frametype:{frame_type}"
    fr.kGFrameTypeDescription = frame_type
    fr.frameGraphURI = str(fr.URI)

    edges = []
    if owner_entity:
        # Entity-enclosed frame (Aspect)
        fr.kGFormType = "http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect"
        fr.kGGraphURI = str(owner_entity.URI)

        e = Edge_hasEntityKGFrame()
        e.URI = _edge_uri()
        e.edgeSource = str(owner_entity.URI)
        e.edgeDestination = str(fr.URI)
        e.kGGraphURI = str(owner_entity.URI)
        edges.append(e)
    else:
        # Top-level frame (Assertion)
        fr.kGFormType = "http://vital.ai/ontology/haley-ai-kg#KGFormType_Assertion"

    return fr, edges


def _entity_slot(frame: KGFrame, slot_type_uri: str,
                 target_entity: KGEntity, owner_entity: Optional[KGEntity] = None) -> List[GraphObject]:
    """Create a KGEntitySlot + Edge_hasKGSlot."""
    slot = KGEntitySlot()
    slot.URI = _edge_uri()  # unique
    slot.name = slot_type_uri.split(":")[-1]
    slot.kGSlotType = slot_type_uri
    slot.entitySlotValue = str(target_entity.URI)
    slot.frameGraphURI = str(frame.URI)
    if owner_entity:
        slot.kGGraphURI = str(owner_entity.URI)

    edge = Edge_hasKGSlot()
    edge.URI = _edge_uri()
    edge.edgeSource = str(frame.URI)
    edge.edgeDestination = str(slot.URI)
    edge.frameGraphURI = str(frame.URI)
    if owner_entity:
        edge.kGGraphURI = str(owner_entity.URI)

    return [slot, edge]


def _text_slot(frame: KGFrame, slot_type_uri: str, value: str,
               owner_entity: Optional[KGEntity] = None) -> List[GraphObject]:
    slot = KGTextSlot()
    slot.URI = _edge_uri()
    slot.name = slot_type_uri.split(":")[-1]
    slot.kGSlotType = slot_type_uri
    slot.textSlotValue = value
    slot.frameGraphURI = str(frame.URI)
    if owner_entity:
        slot.kGGraphURI = str(owner_entity.URI)

    edge = Edge_hasKGSlot()
    edge.URI = _edge_uri()
    edge.edgeSource = str(frame.URI)
    edge.edgeDestination = str(slot.URI)
    edge.frameGraphURI = str(frame.URI)
    if owner_entity:
        edge.kGGraphURI = str(owner_entity.URI)

    return [slot, edge]


def _integer_slot(frame: KGFrame, slot_type_uri: str, value: int,
                  owner_entity: Optional[KGEntity] = None) -> List[GraphObject]:
    slot = KGIntegerSlot()
    slot.URI = _edge_uri()
    slot.name = slot_type_uri.split(":")[-1]
    slot.kGSlotType = slot_type_uri
    slot.integerSlotValue = value
    slot.frameGraphURI = str(frame.URI)
    if owner_entity:
        slot.kGGraphURI = str(owner_entity.URI)

    edge = Edge_hasKGSlot()
    edge.URI = _edge_uri()
    edge.edgeSource = str(frame.URI)
    edge.edgeDestination = str(slot.URI)
    edge.frameGraphURI = str(frame.URI)
    if owner_entity:
        edge.kGGraphURI = str(owner_entity.URI)

    return [slot, edge]


def _datetime_slot(frame: KGFrame, slot_type_uri: str, value: str,
                   owner_entity: Optional[KGEntity] = None) -> List[GraphObject]:
    slot = KGDateTimeSlot()
    slot.URI = _edge_uri()
    slot.name = slot_type_uri.split(":")[-1]
    slot.kGSlotType = slot_type_uri
    slot.dateTimeSlotValue = value
    slot.frameGraphURI = str(frame.URI)
    if owner_entity:
        slot.kGGraphURI = str(owner_entity.URI)

    edge = Edge_hasKGSlot()
    edge.URI = _edge_uri()
    edge.edgeSource = str(frame.URI)
    edge.edgeDestination = str(slot.URI)
    edge.frameGraphURI = str(frame.URI)
    if owner_entity:
        edge.kGGraphURI = str(owner_entity.URI)

    return [slot, edge]


def _relation(source: KGEntity, target: KGEntity,
              relation_type: str) -> Edge_hasKGRelation:
    rel = Edge_hasKGRelation()
    rel.URI = _edge_uri()
    rel.edgeSource = str(source.URI)
    rel.edgeDestination = str(target.URI)
    rel.kGRelationType = f"urn:vitalgraph:reltype:{relation_type}"
    rel.kGRelationTypeDescription = relation_type
    return rel


def _subframe_edge(parent: KGFrame, child: KGFrame,
                   owner_entity: Optional[KGEntity] = None) -> Edge_hasKGFrame:
    edge = Edge_hasKGFrame()
    edge.URI = _edge_uri()
    edge.edgeSource = str(parent.URI)
    edge.edgeDestination = str(child.URI)
    if owner_entity:
        edge.kGGraphURI = str(owner_entity.URI)
    return edge


# ---------------------------------------------------------------------------
# Dataset generators
# ---------------------------------------------------------------------------

_FIRST_NAMES = [
    "Alice", "Bob", "Carol", "David", "Elena", "Frank", "Grace", "Henry",
    "Iris", "Jack", "Karen", "Leo", "Maria", "Nathan", "Olivia", "Paul",
    "Quinn", "Rachel", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xavier",
]
_LAST_NAMES = [
    "Chen", "Martinez", "Kim", "Park", "Johnson", "Rivera", "Lee", "Smith",
    "Garcia", "Brown", "Davis", "Wilson", "Taylor", "Thomas", "Moore", "White",
]
_COMPANY_NAMES = [
    "Acme Corp", "Globex Inc", "Initech", "Umbrella Co", "Stark Industries",
    "Wayne Enterprises", "Soylent Corp", "Hooli", "Pied Piper", "Dunder Mifflin",
    "Cyberdyne", "Oscorp", "LexCorp", "Tyrell Corp", "Weyland-Yutani",
]


def generate_dataset_a() -> List[GraphObject]:
    """Dataset A — People & Employment (binary frames). ~350 objects."""
    rng = random.Random(42)
    objects: List[GraphObject] = []

    # 30 people, 12 companies
    people = []
    for i in range(30):
        first = _FIRST_NAMES[i % len(_FIRST_NAMES)]
        last = _LAST_NAMES[i % len(_LAST_NAMES)]
        name = f"{first} {last}" if i < len(_FIRST_NAMES) else f"{first} {last} {i}"
        people.append(_entity(f"A_{name.replace(' ', '_')}", "Person"))
    companies = [_entity(f"A_{c.replace(' ', '_')}", "Organization")
                 for c in _COMPANY_NAMES[:12]]
    objects.extend(people)
    objects.extend(companies)

    # Each person employed at 1-2 companies (binary frames)
    for i, person in enumerate(people):
        employer = companies[i % len(companies)]
        fr, edges = _frame(f"A_Employment_{i}", "EmploymentFrame", owner_entity=person)
        objects.extend([fr] + edges)
        objects.extend(_entity_slot(fr, "urn:hasEmployee", person, owner_entity=person))
        objects.extend(_entity_slot(fr, "urn:hasEmployer", employer, owner_entity=person))
        objects.extend(_text_slot(fr, "urn:hasRole", rng.choice(["Engineer", "Manager", "Director", "Analyst", "VP"]), owner_entity=person))

        # ~40% have a previous job
        if rng.random() < 0.4:
            prev = companies[(i + 3) % len(companies)]
            fr2, edges2 = _frame(f"A_PrevJob_{i}", "EmploymentFrame", owner_entity=person)
            objects.extend([fr2] + edges2)
            objects.extend(_entity_slot(fr2, "urn:hasEmployee", person, owner_entity=person))
            objects.extend(_entity_slot(fr2, "urn:hasEmployer", prev, owner_entity=person))

    # 40 knows relations (random pairs)
    pairs = set()
    while len(pairs) < 40:
        a, b = rng.sample(range(len(people)), 2)
        if (a, b) not in pairs:
            pairs.add((a, b))
            objects.append(_relation(people[a], people[b], "knows"))

    # 8 partner_of relations between companies
    for i in range(8):
        objects.append(_relation(companies[i], companies[(i + 1) % len(companies)], "partner_of"))

    return objects


_TOPICS = [
    "Neural Networks", "Reinforcement Learning", "NLP", "Computer Vision",
    "Robotics", "Quantum Computing", "Bioinformatics", "Cryptography",
    "Graph Theory", "Optimization", "Signal Processing", "Control Systems",
]
_INSTITUTIONS = [
    "MIT Lab", "Stanford AI", "CMU Robotics", "Oxford NLP", "ETH Zurich",
    "Berkeley AI", "DeepMind", "FAIR Lab",
]


def generate_dataset_b() -> List[GraphObject]:
    """Dataset B — Research Project (N-ary frames). ~400 objects."""
    rng = random.Random(43)
    objects: List[GraphObject] = []

    # 25 researchers, 8 institutions, 12 topics, 10 papers
    researchers = [_entity(f"B_Dr_{_FIRST_NAMES[i % len(_FIRST_NAMES)]}_{_LAST_NAMES[i % len(_LAST_NAMES)]}_{i}", "Person")
                   for i in range(25)]
    institutions = [_entity(f"B_{name.replace(' ', '_')}", "Organization")
                    for name in _INSTITUTIONS]
    topics = [_entity(f"B_{t.replace(' ', '_')}", "Topic") for t in _TOPICS]
    papers = [_document(f"B_Paper_{i}: {rng.choice(['A Study of', 'Advances in', 'Survey of', 'On the'])} {_TOPICS[i % len(_TOPICS)]}")
             for i in range(10)]
    objects.extend(researchers + institutions + topics + papers)

    # 12 N-ary research collaboration frames (3-5 researchers + institution + topic)
    for i in range(12):
        lead = researchers[i]
        fr, edges = _frame(f"B_Research_{i}", "ResearchCollaboration", owner_entity=lead)
        objects.extend([fr] + edges)

        # 3-5 researchers per project
        team_size = rng.randint(3, 5)
        team = [lead] + rng.sample([r for r in researchers if r != lead], team_size - 1)
        for member in team:
            objects.extend(_entity_slot(fr, "urn:hasResearcher", member, owner_entity=lead))

        objects.extend(_entity_slot(fr, "urn:hasInstitution", institutions[i % len(institutions)], owner_entity=lead))
        objects.extend(_entity_slot(fr, "urn:hasTopic", topics[i % len(topics)], owner_entity=lead))
        objects.extend(_text_slot(fr, "urn:hasFunding", f"Grant #{rng.randint(10000, 99999)}", owner_entity=lead))

    # Relations: advises, affiliated_with, co_authored
    for i in range(15):
        objects.append(_relation(researchers[i], researchers[(i + 1) % len(researchers)], "advises"))
    for i, r in enumerate(researchers):
        objects.append(_relation(r, institutions[i % len(institutions)], "affiliated_with"))

    return objects


def generate_dataset_c() -> List[GraphObject]:
    """Dataset C — Supply Chain (mixed arity + subframes). ~450 objects."""
    rng = random.Random(44)
    objects: List[GraphObject] = []

    # 8 buyers, 8 sellers, 5 carriers, 6 warehouses
    buyers = [_entity(f"C_Buyer_{i}", "Organization") for i in range(8)]
    sellers = [_entity(f"C_Seller_{i}", "Organization") for i in range(8)]
    carriers = [_entity(f"C_Carrier_{i}", "Organization") for i in range(5)]
    warehouses = [_entity(f"C_Warehouse_{chr(65 + i)}", "Location") for i in range(6)]
    objects.extend(buyers + sellers + carriers + warehouses)

    # 20 purchase orders, each with a shipping subframe
    for i in range(20):
        buyer = buyers[i % len(buyers)]
        seller = sellers[i % len(sellers)]

        po, po_edges = _frame(f"C_PO_{i:03d}", "PurchaseOrderFrame", owner_entity=buyer)
        objects.extend([po] + po_edges)
        objects.extend(_entity_slot(po, "urn:hasBuyer", buyer, owner_entity=buyer))
        objects.extend(_entity_slot(po, "urn:hasSeller", seller, owner_entity=buyer))
        objects.extend(_text_slot(po, "urn:hasOrderNumber", f"PO-2026-{i:03d}", owner_entity=buyer))
        objects.extend(_integer_slot(po, "urn:hasQuantity", rng.randint(100, 5000), owner_entity=buyer))

        # Shipping subframe
        ship, _ = _frame(f"C_Shipping_{i:03d}", "ShippingFrame", owner_entity=buyer)
        ship.kGFormType = "http://vital.ai/ontology/haley-ai-kg#KGFormType_Aspect"
        ship.kGGraphURI = str(buyer.URI)
        ship.parentFrameURI = str(po.URI)
        objects.append(ship)
        objects.append(_subframe_edge(po, ship, owner_entity=buyer))
        objects.extend(_entity_slot(ship, "urn:hasCarrier", carriers[i % len(carriers)], owner_entity=buyer))
        objects.extend(_entity_slot(ship, "urn:hasDestination", warehouses[i % len(warehouses)], owner_entity=buyer))
        objects.extend(_datetime_slot(ship, "urn:hasDeliveryDate", f"2026-{rng.randint(7,12):02d}-{rng.randint(1,28):02d}T00:00:00Z", owner_entity=buyer))

    # Relations
    for i in range(len(buyers)):
        objects.append(_relation(buyers[i], sellers[i % len(sellers)], "customer_of"))
    for i in range(len(carriers)):
        objects.append(_relation(carriers[i], warehouses[i % len(warehouses)], "operates_at"))

    return objects


_REL_TYPES = ["knows", "follows", "mentors", "collaborates_with", "reports_to"]


def generate_dataset_d() -> List[GraphObject]:
    """Dataset D — Social Network (many binary relations, no frames). ~250 objects."""
    rng = random.Random(45)
    objects: List[GraphObject] = []

    # 50 people, 8 organizations
    people = []
    for i in range(50):
        first = _FIRST_NAMES[i % len(_FIRST_NAMES)]
        last = _LAST_NAMES[i % len(_LAST_NAMES)]
        people.append(_entity(f"D_{first}_{last}_{i}", "Person"))
    orgs = [_entity(f"D_Org_{i}", "Organization") for i in range(8)]
    objects.extend(people + orgs)

    # ~150 relations between people
    pairs = set()
    while len(pairs) < 150:
        a, b = rng.sample(range(len(people)), 2)
        if (a, b) not in pairs:
            pairs.add((a, b))
            objects.append(_relation(people[a], people[b], rng.choice(_REL_TYPES)))

    # 40 person→org relations
    for i in range(40):
        person = people[i % len(people)]
        org = orgs[i % len(orgs)]
        rel = rng.choice(["works_at", "founded", "invested_in", "advises"])
        objects.append(_relation(person, org, rel))

    return objects


_CATEGORIES = ["Computer Science", "Mathematics", "Physics", "Biology", "Chemistry",
               "Engineering", "Medicine", "Economics", "Psychology", "Linguistics"]
_SUBFIELDS = ["AI", "ML", "Theory", "Applied", "Experimental", "Computational",
              "Statistical", "Clinical", "Behavioral", "Structural"]


def generate_dataset_e() -> List[GraphObject]:
    """Dataset E — Unary Frame (annotation/tag pattern). ~300 objects."""
    rng = random.Random(46)
    objects: List[GraphObject] = []

    # 35 topics
    topic_names = _TOPICS + [
        "Machine Learning", "Deep Learning", "Data Mining", "Information Retrieval",
        "Distributed Systems", "Operating Systems", "Compilers", "Databases",
        "Software Engineering", "Human-Computer Interaction", "Security",
        "Cloud Computing", "Edge Computing", "Formal Methods", "Type Theory",
        "Category Theory", "Linear Algebra", "Probability", "Statistics",
        "Numerical Methods", "Parallel Computing", "Embedded Systems", "IoT",
    ]
    topics = [_entity(f"E_{t.replace(' ', '_')}", "Topic") for t in topic_names]
    objects.extend(topics)

    # Each topic gets a unary classification frame (data-value slots only)
    for i, topic in enumerate(topics):
        fr, edges = _frame(f"E_Classification_{i}", "ClassificationFrame", owner_entity=topic)
        objects.extend([fr] + edges)
        objects.extend(_text_slot(fr, "urn:hasCategory", _CATEGORIES[i % len(_CATEGORIES)], owner_entity=topic))
        objects.extend(_text_slot(fr, "urn:hasSubfield", _SUBFIELDS[i % len(_SUBFIELDS)], owner_entity=topic))
        objects.extend(_integer_slot(fr, "urn:hasPopularityRank", rng.randint(1, 100), owner_entity=topic))

    # 25 parent_topic relations (tree-ish structure)
    for i in range(25):
        parent = topics[i]
        child = topics[(i + rng.randint(3, 8)) % len(topics)]
        if parent != child:
            objects.append(_relation(parent, child, "parent_topic"))

    return objects


def generate_dataset_f() -> List[GraphObject]:
    """Dataset F — Top-Level Frames (Assertions, no owning entity). ~400 objects."""
    rng = random.Random(47)
    objects: List[GraphObject] = []

    # 20 people, 8 locations, 6 documents
    people = [_entity(f"F_{_FIRST_NAMES[i]}_{_LAST_NAMES[i % len(_LAST_NAMES)]}", "Person")
              for i in range(20)]
    locations = [_entity(f"F_Location_{i}", "Location") for i in range(8)]
    docs = [_document(f"F_Minutes_2026_{i:02d}", f"Meeting minutes document {i}")
            for i in range(6)]
    objects.extend(people + locations + docs)

    # 12 N-ary top-level meeting frames (Assertion, no owning entity)
    for i in range(12):
        meeting, _ = _frame(f"F_Meeting_{i}", "MeetingFrame")
        objects.append(meeting)

        chair = people[i % len(people)]
        objects.extend(_entity_slot(meeting, "urn:hasChair", chair))

        # 3-5 attendees
        attendees = rng.sample([p for p in people if p != chair], rng.randint(3, 5))
        for att in attendees:
            objects.extend(_entity_slot(meeting, "urn:hasAttendee", att))

        objects.extend(_entity_slot(meeting, "urn:hasVenue", locations[i % len(locations)]))
        objects.extend(_datetime_slot(meeting, "urn:hasDate", f"2026-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}T14:00:00Z"))
        objects.extend(_text_slot(meeting, "urn:hasAgenda", f"Agenda item {i}: budget and planning"))

    # 10 binary top-level decision frames (Assertion, no owning entity)
    for i in range(10):
        decision, _ = _frame(f"F_Decision_{i}", "DecisionFrame")
        objects.append(decision)
        objects.extend(_entity_slot(decision, "urn:hasApprover", people[i % len(people)]))
        objects.extend(_entity_slot(decision, "urn:hasAffectedArea", locations[i % len(locations)]))

    # Track which people are connected (referenced by entity slots or relation edges)
    people_uris = {str(p.URI) for p in people}
    connected = set()
    for obj in objects:
        # Entity slots reference entities via entitySlotValue
        val = str(getattr(obj, 'entitySlotValue', '') or '')
        if val in people_uris:
            connected.add(val)
        # Relation edges reference entities via edgeSource/edgeDestination
        src = str(getattr(obj, 'edgeSource', '') or '')
        dst = str(getattr(obj, 'edgeDestination', '') or '')
        if src in people_uris:
            connected.add(src)
        if dst in people_uris:
            connected.add(dst)

    # Ensure every person is in at least one meeting as attendee
    for p in people:
        if str(p.URI) not in connected:
            meeting_idx = rng.randint(0, 11)
            meeting_uri = _uri("frame", f"F_Meeting_{meeting_idx}")
            meeting_obj = next((o for o in objects if isinstance(o, KGFrame) and str(o.URI) == meeting_uri), None)
            if meeting_obj:
                objects.extend(_entity_slot(meeting_obj, "urn:hasAttendee", p))

    # 20 relations
    for i in range(10):
        objects.append(_relation(people[i], locations[i % len(locations)], "governs"))
        objects.append(_relation(locations[i % len(locations)], locations[(i + 1) % len(locations)], "adjacent_to"))

    return objects


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

BLOCK_SIZE = 100

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

DATASETS = {
    "A": ("graph_viz_test_A_people.vital",       generate_dataset_a, "People & Employment (binary frames)"),
    "B": ("graph_viz_test_B_research.vital",      generate_dataset_b, "Research Project (N-ary frame)"),
    "C": ("graph_viz_test_C_supply.vital",        generate_dataset_c, "Supply Chain (subframes)"),
    "D": ("graph_viz_test_D_social.vital",        generate_dataset_d, "Social Network (relations only)"),
    "E": ("graph_viz_test_E_unary.vital",         generate_dataset_e, "Unary Frame (annotation)"),
    "F": ("graph_viz_test_F_toplevel.vital",      generate_dataset_f, "Top-Level Frames (Assertions)"),
}


def main():
    parser = argparse.ArgumentParser(
        description="Generate graph visualization test datasets as .vital block files"
    )
    parser.add_argument("--dataset", "-d", type=str, default=None,
                        help="Generate only this dataset (A-F). Default: all.")
    parser.add_argument("--output-dir", "-o", type=str, default=None,
                        help="Output directory (default: generated_instances/)")
    parser.add_argument("--stats", "-s", action="store_true",
                        help="Print statistics only, don't write files")
    args = parser.parse_args()

    # Resolve output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        out_dir = Path(__file__).parent.parent.parent / "generated_instances"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Select datasets
    if args.dataset:
        key = args.dataset.upper()
        if key not in DATASETS:
            print(f"Unknown dataset '{key}'. Choose from: {', '.join(DATASETS.keys())}")
            sys.exit(1)
        selected = {key: DATASETS[key]}
    else:
        selected = DATASETS

    total_objects = 0
    for key, (filename, generator, description) in sorted(selected.items()):
        objects = generator()
        count = len(objects)
        total_objects += count

        # Count by type
        entities = sum(1 for o in objects if isinstance(o, KGEntity))
        frames = sum(1 for o in objects if isinstance(o, KGFrame))
        docs = sum(1 for o in objects if isinstance(o, KGDocument))
        slots = sum(1 for o in objects if isinstance(o, (KGEntitySlot, KGTextSlot,
                                                          KGIntegerSlot, KGDoubleSlot,
                                                          KGDateTimeSlot)))
        edges = count - entities - frames - docs - slots

        print(f"  [{key}] {description}")
        print(f"      {entities} entities, {frames} frames, {docs} docs, "
              f"{slots} slots, {edges} edges = {count} total")

        if not args.stats:
            path = out_dir / filename
            write_vital_block_file(objects, str(path))
            print(f"      → {path}")

    print(f"\n  Total: {total_objects} objects across {len(selected)} dataset(s)")


if __name__ == "__main__":
    main()
