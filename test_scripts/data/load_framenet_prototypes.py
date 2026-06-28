#!/usr/bin/env python3
"""
FrameNet KG Types & Prototypes Loader
======================================

Loads FrameNet frame data into KG Type and KG Prototype objects for testing
the KG types and prototypes implementation.

FrameNet (~1,224 frames) provides a rich dataset of semantic frame definitions
with typed slots (frame elements), frame relations (inheritance, subframe),
and annotated examples — mapping cleanly onto the three-tier KG architecture:

  Tier 1 (Types):      KGFrameType, KGSlotType, KGEntityType
  Tier 2 (Prototypes): KGFrameProtoType, KGSlotProtoType + edges
  Tier 3 (Instances):  KGFrame, KGSlot subclasses (not generated here)

Search testing:
  Each KGFrameType and KGSlotType includes a rich natural-language description
  (from FrameNet definitions). These descriptions are suitable for:
    - Full-text / keyword search testing
    - Vector embedding and semantic similarity search
    - Testing prototype lookup via type description search (searching type
      descriptions but surfacing related prototypes via graph traversal)

Prerequisites:
    pip install nltk
    python -c "import nltk; nltk.download('framenet_v17')"

Usage:
    # Generate all objects as JSON-L
    python load_framenet_prototypes.py --output framenet_kg_objects.jsonl

    # Preview a single frame
    python load_framenet_prototypes.py --preview Commerce_buy

    # Generate with frame limit (for quick testing)
    python load_framenet_prototypes.py --limit 50 --output framenet_kg_objects_50.jsonl

    # Print statistics only
    python load_framenet_prototypes.py --stats
"""

import argparse
import json
import sys
import uuid
from typing import Optional


# ---------------------------------------------------------------------------
# FrameNet access via NLTK
# ---------------------------------------------------------------------------

def ensure_framenet():
    """Download FrameNet data if not already present."""
    import nltk
    try:
        from nltk.corpus import framenet as fn
        # Trigger a load to verify data is present
        _ = fn.frames()
        return fn
    except LookupError:
        print("Downloading FrameNet 1.7 data...")
        nltk.download('framenet_v17')
        from nltk.corpus import framenet as fn
        return fn


def list_all_frames(fn):
    """List all FrameNet frames with ID, name, and definition."""
    frames = []
    for frame in fn.frames():
        frames.append({
            "id": frame.ID,
            "name": frame.name,
            "definition": frame.definition,
            "fe_count": len(frame.FE),
            "lu_count": len(frame.lexUnit),
        })
    return frames


def get_frame_elements(fn, frame_name: str):
    """Get all frame elements (semantic roles) for a frame."""
    frame = fn.frame(frame_name)
    elements = []
    for fe in frame.FE.values():
        elements.append({
            "name": fe.name,
            "definition": fe.definition,
            "coreType": getattr(fe, 'coreType', 'Unknown'),
            "semType": str(fe.semType) if hasattr(fe, 'semType') and fe.semType else None,
        })
    return elements


def get_frame_relations(fn, frame_name: str):
    """Get frame relations (inheritance, subframe, using, etc.)."""
    frame = fn.frame(frame_name)
    relations = []
    for relation in frame.frameRelations:
        relations.append({
            "type": relation.type.name,
            "superFrame": relation.superFrame.name,
            "subFrame": relation.subFrame.name,
        })
    return relations


def get_lexical_units(fn, frame_name: str):
    """Get lexical units (word senses) that evoke a frame."""
    frame = fn.frame(frame_name)
    lus = []
    for lu in frame.lexUnit.values():
        lus.append({
            "name": lu.name,
            "definition": lu.definition,
        })
    return lus


# ---------------------------------------------------------------------------
# URI generation
# ---------------------------------------------------------------------------

_BASE_URI = "urn:vitalgraph:framenet"


def _generate_uri(prefix: str, name: str) -> str:
    """Generate a deterministic URI from prefix and name."""
    return f"{_BASE_URI}:{prefix}:{name}"


def _generate_edge_uri() -> str:
    """Generate a unique edge URI."""
    return f"{_BASE_URI}:edge:{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# KG object generation — Tier 1 (Types)
# ---------------------------------------------------------------------------

_KG_NS = "http://vital.ai/ontology/haley-ai-kg#"
_VITAL_NS = "http://vital.ai/ontology/vital-core#"


def make_frame_type(frame) -> dict:
    """Create a KGFrameType object from a FrameNet frame.

    Includes a rich description combining the frame definition with its
    core frame elements, suitable for vector embedding and search.
    """
    # Build enriched description: definition + core FEs for better embeddings
    core_fes = [fe.name for fe in frame.FE.values()
                if getattr(fe, 'coreType', '') == 'Core']
    description = frame.definition
    if core_fes:
        description += f" Core participants: {', '.join(core_fes)}."

    return {
        "URI": _generate_uri("frame-type", frame.name),
        "type": f"{_KG_NS}KGFrameType",
        f"{_KG_NS}hasName": frame.name,
        f"{_KG_NS}kGraphDescription": description,
        f"{_KG_NS}hasKGFrameTypeExternIdentifier": str(frame.ID),
    }


def make_slot_type(fe_name: str, fe_definition: str,
                   used_in_frames: Optional[list] = None) -> dict:
    """Create a KGSlotType object from a FrameNet frame element.

    Includes an enriched description noting which frames use this slot type,
    suitable for vector embedding and search.
    """
    description = fe_definition
    if used_in_frames:
        frames_str = ', '.join(used_in_frames[:10])
        suffix = f" (and {len(used_in_frames) - 10} more)" if len(used_in_frames) > 10 else ""
        description += f" Used in frames: {frames_str}{suffix}."

    return {
        "URI": _generate_uri("slot-type", fe_name),
        "type": f"{_KG_NS}KGSlotType",
        f"{_KG_NS}hasName": fe_name,
        f"{_KG_NS}kGraphDescription": description,
        f"{_KG_NS}hasKGSlotTypeName": fe_name,
        f"{_KG_NS}hasKGSlotTypeLabel": fe_name,
        f"{_KG_NS}hasKGSlotTypeExternIdentifier": fe_name,
    }


def make_frame_type_hierarchy_edge(parent_frame_name: str, child_frame_name: str) -> dict:
    """Create an Edge_hasSubKGFrameType for frame inheritance."""
    return {
        "URI": _generate_edge_uri(),
        "type": f"{_KG_NS}Edge_hasSubKGFrameType",
        f"{_VITAL_NS}hasEdgeSource": _generate_uri("frame-type", parent_frame_name),
        f"{_VITAL_NS}hasEdgeDestination": _generate_uri("frame-type", child_frame_name),
    }


# ---------------------------------------------------------------------------
# KG object generation — Tier 2 (Prototypes)
# ---------------------------------------------------------------------------

def make_frame_prototype(frame) -> dict:
    """Create a KGFrameProtoType from a FrameNet frame."""
    return {
        "URI": _generate_uri("frame-proto", frame.name),
        "type": f"{_KG_NS}KGFrameProtoType",
        f"{_KG_NS}hasName": f"{frame.name}_Prototype",
        f"{_KG_NS}hasKGFrameType": _generate_uri("frame-type", frame.name),
        f"{_KG_NS}hasKGFrameTypeExternIdentifier": str(frame.ID),
    }


def make_slot_prototype(frame_name: str, fe_name: str) -> dict:
    """Create a KGSlotProtoType for a frame element within a frame."""
    return {
        "URI": _generate_uri("slot-proto", f"{frame_name}_{fe_name}"),
        "type": f"{_KG_NS}KGSlotProtoType",
        f"{_KG_NS}hasName": f"{frame_name}_{fe_name}_SlotPrototype",
        f"{_KG_NS}hasKGSlotType": _generate_uri("slot-type", fe_name),
        f"{_KG_NS}hasKGSlotTypeExternIdentifier": fe_name,
    }


def make_edge_has_slot_prototype(frame_name: str, fe_name: str,
                                  sequence: int, core_type: str) -> dict:
    """Create an Edge_hasKGSlotProtoType linking frame proto to slot proto."""
    role_type = "Core" if core_type == "Core" else "Non-Core"
    return {
        "URI": _generate_edge_uri(),
        "type": f"{_KG_NS}Edge_hasKGSlotProtoType",
        f"{_VITAL_NS}hasEdgeSource": _generate_uri("frame-proto", frame_name),
        f"{_VITAL_NS}hasEdgeDestination": _generate_uri("slot-proto", f"{frame_name}_{fe_name}"),
        f"{_KG_NS}hasKGSlotRoleSequence": sequence,
        f"{_KG_NS}hasKGSlotRoleType": role_type,
        f"{_KG_NS}hasKGSlotTypeExternIdentifier": fe_name,
    }


def make_edge_has_slot_type(frame_name: str, fe_name: str) -> dict:
    """Create an Edge_hasKGSlotType linking slot proto to slot type."""
    return {
        "URI": _generate_edge_uri(),
        "type": f"{_KG_NS}Edge_hasKGSlotType",
        f"{_VITAL_NS}hasEdgeSource": _generate_uri("slot-proto", f"{frame_name}_{fe_name}"),
        f"{_VITAL_NS}hasEdgeDestination": _generate_uri("slot-type", fe_name),
        f"{_KG_NS}hasKGSlotTypeExternIdentifier": fe_name,
    }


def make_edge_has_frame_prototype(frame_name: str) -> dict:
    """Create an Edge_hasKGFrameProtoType linking frame type to frame proto."""
    return {
        "URI": _generate_edge_uri(),
        "type": f"{_KG_NS}Edge_hasKGFrameProtoType",
        f"{_VITAL_NS}hasEdgeSource": _generate_uri("frame-type", frame_name),
        f"{_VITAL_NS}hasEdgeDestination": _generate_uri("frame-proto", frame_name),
    }


# ---------------------------------------------------------------------------
# Full generation pipeline
# ---------------------------------------------------------------------------

def _collect_slot_type_usage(frames) -> dict:
    """
    First pass: collect which frames use each FE name and the first definition
    seen. This allows enriching slot type descriptions with usage context.
    """
    slot_info = {}  # fe_name -> {"definition": str, "frames": [str]}
    for frame in frames:
        for fe in frame.FE.values():
            if fe.name not in slot_info:
                slot_info[fe.name] = {
                    "definition": fe.definition,
                    "frames": [],
                }
            slot_info[fe.name]["frames"].append(frame.name)
    return slot_info


def generate_all_objects(fn, limit: Optional[int] = None):
    """
    Generate all KG Type and Prototype objects from FrameNet.

    Yields dicts representing graph objects (types, prototypes, edges).
    Fuzzylicates slot types since the same FE name (e.g. "Place", "Time")
    appears in many frames. Enriches descriptions with cross-frame usage
    for better vector search / semantic similarity.
    """
    frames = fn.frames()
    if limit:
        frames = frames[:limit]

    # First pass: collect slot type usage across all frames
    slot_info = _collect_slot_type_usage(frames)

    seen_slot_types = set()
    stats = {
        "frame_types": 0,
        "slot_types": 0,
        "frame_prototypes": 0,
        "slot_prototypes": 0,
        "edges_has_frame_proto": 0,
        "edges_has_slot_proto": 0,
        "edges_has_slot_type": 0,
        "edges_frame_hierarchy": 0,
    }

    for frame in frames:
        # Tier 1: KGFrameType
        yield make_frame_type(frame)
        stats["frame_types"] += 1

        # Tier 1: KGSlotType (fuzzylicated by FE name, enriched with usage)
        for fe in frame.FE.values():
            if fe.name not in seen_slot_types:
                info = slot_info[fe.name]
                yield make_slot_type(
                    fe.name, info["definition"],
                    used_in_frames=info["frames"]
                )
                seen_slot_types.add(fe.name)
                stats["slot_types"] += 1

        # Tier 1: Frame hierarchy edges (Inheritance relations only)
        for relation in frame.frameRelations:
            if relation.type.name == "Inheritance" and relation.superFrame.name == frame.name:
                yield make_frame_type_hierarchy_edge(
                    relation.superFrame.name, relation.subFrame.name
                )
                stats["edges_frame_hierarchy"] += 1

        # Tier 2: KGFrameProtoType
        yield make_frame_prototype(frame)
        stats["frame_prototypes"] += 1

        # Tier 2: Edge linking KGFrameType → KGFrameProtoType
        yield make_edge_has_frame_prototype(frame.name)
        stats["edges_has_frame_proto"] += 1

        # Tier 2: KGSlotProtoType per FE + edges
        sequence = 0
        for fe in frame.FE.values():
            sequence += 1
            core_type = getattr(fe, 'coreType', 'Unknown')

            yield make_slot_prototype(frame.name, fe.name)
            stats["slot_prototypes"] += 1

            yield make_edge_has_slot_prototype(
                frame.name, fe.name, sequence, core_type
            )
            stats["edges_has_slot_proto"] += 1

            yield make_edge_has_slot_type(frame.name, fe.name)
            stats["edges_has_slot_type"] += 1

    return stats


def generate_with_stats(fn, limit: Optional[int] = None):
    """Generate all objects and collect stats.

    Two-pass: first collects slot type usage across frames for enriched
    descriptions, then generates all objects.
    """
    objects = []
    seen_slot_types = set()
    frames = fn.frames()
    if limit:
        frames = frames[:limit]

    # First pass: collect slot type usage for enriched descriptions
    slot_info = _collect_slot_type_usage(frames)

    stats = {
        "frame_types": 0,
        "slot_types": 0,
        "frame_prototypes": 0,
        "slot_prototypes": 0,
        "edges_has_frame_proto": 0,
        "edges_has_slot_proto": 0,
        "edges_has_slot_type": 0,
        "edges_frame_hierarchy": 0,
        "total_objects": 0,
    }

    for frame in frames:
        # Tier 1: KGFrameType (enriched with core FE names)
        objects.append(make_frame_type(frame))
        stats["frame_types"] += 1

        # Tier 1: KGSlotType (fuzzylicated, enriched with frame usage)
        for fe in frame.FE.values():
            if fe.name not in seen_slot_types:
                info = slot_info[fe.name]
                objects.append(make_slot_type(
                    fe.name, info["definition"],
                    used_in_frames=info["frames"]
                ))
                seen_slot_types.add(fe.name)
                stats["slot_types"] += 1

        # Tier 1: Frame hierarchy edges
        for relation in frame.frameRelations:
            if relation.type.name == "Inheritance" and relation.superFrame.name == frame.name:
                objects.append(make_frame_type_hierarchy_edge(
                    relation.superFrame.name, relation.subFrame.name
                ))
                stats["edges_frame_hierarchy"] += 1

        # Tier 2: KGFrameProtoType
        objects.append(make_frame_prototype(frame))
        stats["frame_prototypes"] += 1

        # Tier 2: Edge KGFrameType → KGFrameProtoType
        objects.append(make_edge_has_frame_prototype(frame.name))
        stats["edges_has_frame_proto"] += 1

        # Tier 2: KGSlotProtoType per FE + edges
        sequence = 0
        for fe in frame.FE.values():
            sequence += 1
            core_type = getattr(fe, 'coreType', 'Unknown')

            objects.append(make_slot_prototype(frame.name, fe.name))
            stats["slot_prototypes"] += 1

            objects.append(make_edge_has_slot_prototype(
                frame.name, fe.name, sequence, core_type
            ))
            stats["edges_has_slot_proto"] += 1

            objects.append(make_edge_has_slot_type(frame.name, fe.name))
            stats["edges_has_slot_type"] += 1

    stats["total_objects"] = len(objects)
    return objects, stats


# ---------------------------------------------------------------------------
# Preview helpers
# ---------------------------------------------------------------------------

def preview_frame(fn, frame_name: str):
    """Print a detailed preview of objects generated for one frame."""
    frame = fn.frame(frame_name)
    print(f"\n{'='*70}")
    print(f"Frame: {frame.name} (ID: {frame.ID})")
    print(f"Definition: {frame.definition[:120]}...")
    print(f"{'='*70}")

    # Frame elements
    print(f"\nFrame Elements ({len(frame.FE)}):")
    for fe in frame.FE.values():
        core = getattr(fe, 'coreType', '?')
        print(f"  [{core:>10}] {fe.name}: {fe.definition[:80]}...")

    # Relations
    print(f"\nFrame Relations ({len(frame.frameRelations)}):")
    for rel in frame.frameRelations:
        print(f"  {rel.type.name}: {rel.superFrame.name} → {rel.subFrame.name}")

    # Lexical units (first 10)
    lus = list(frame.lexUnit.values())
    print(f"\nLexical Units ({len(lus)}, showing first 10):")
    for lu in lus[:10]:
        print(f"  {lu.name}: {lu.definition[:80]}...")

    # Generated objects
    print(f"\n{'─'*70}")
    print("Generated KG Objects:")
    print(f"{'─'*70}")

    ft = make_frame_type(frame)
    print(f"\n  KGFrameType: {ft['URI']}")

    fp = make_frame_prototype(frame)
    print(f"  KGFrameProtoType: {fp['URI']}")

    efp = make_edge_has_frame_prototype(frame.name)
    print(f"  Edge_hasKGFrameProtoType: {efp[f'{_VITAL_NS}hasEdgeSource']} → {efp[f'{_VITAL_NS}hasEdgeDestination']}")

    seq = 0
    for fe in frame.FE.values():
        seq += 1
        core = getattr(fe, 'coreType', '?')
        sp = make_slot_prototype(frame.name, fe.name)
        print(f"\n  KGSlotProtoType [seq={seq}, role={core}]: {sp['URI']}")
        print(f"    → KGSlotType: {_generate_uri('slot-type', fe.name)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Load FrameNet data as KG Type and Prototype objects"
    )
    parser.add_argument("--output", "-o", type=str,
                        help="Output file path (JSON-L format)")
    parser.add_argument("--preview", "-p", type=str,
                        help="Preview objects for a single frame (e.g. Commerce_buy)")
    parser.add_argument("--limit", "-l", type=int, default=None,
                        help="Limit number of frames to process")
    parser.add_argument("--stats", "-s", action="store_true",
                        help="Print statistics only")
    parser.add_argument("--list-frames", action="store_true",
                        help="List all frame names")

    args = parser.parse_args()
    fn = ensure_framenet()

    if args.list_frames:
        for frame in fn.frames():
            print(f"{frame.ID:>5}  {frame.name}")
        print(f"\nTotal: {len(fn.frames())} frames")
        return

    if args.preview:
        preview_frame(fn, args.preview)
        return

    # Generate objects
    objects, stats = generate_with_stats(fn, limit=args.limit)

    # Print stats
    print("\nFrameNet → KG Objects Statistics:")
    print(f"  Frames processed:        {stats['frame_types']}")
    print(f"  Unique slot types:       {stats['slot_types']}")
    print(f"  Frame prototypes:        {stats['frame_prototypes']}")
    print(f"  Slot prototypes:         {stats['slot_prototypes']}")
    print(f"  Frame hierarchy edges:   {stats['edges_frame_hierarchy']}")
    print(f"  Frame→Proto edges:       {stats['edges_has_frame_proto']}")
    print(f"  Proto→SlotProto edges:   {stats['edges_has_slot_proto']}")
    print(f"  SlotProto→Type edges:    {stats['edges_has_slot_type']}")
    print(f"  ─────────────────────────────")
    print(f"  Total objects:           {stats['total_objects']}")

    if args.stats:
        return

    if args.output:
        with open(args.output, 'w') as f:
            for obj in objects:
                f.write(json.dumps(obj) + "\n")
        print(f"\nWrote {len(objects)} objects to {args.output}")
    else:
        # Write to stdout
        for obj in objects:
            print(json.dumps(obj))


if __name__ == "__main__":
    main()
