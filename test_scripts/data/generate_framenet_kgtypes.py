#!/usr/bin/env python3
"""
FrameNet KG Types Generator — .vital Block File Output
=======================================================

Generates KG Type objects (types only, no prototypes) from FrameNet 1.7
using proper VitalSigns GraphObject classes.  Output is a .vital block
file that can be loaded directly into a space's KG types graph.

Object types generated:
  - KGFrameType   (~1,221)  — one per FrameNet frame
  - KGSlotType    (~1,285)  — fuzzylicated frame elements
  - Edge_hasSubKGFrameType (~781)  — frame inheritance hierarchy

FrameNet defines frame semantics at the type level — frame definitions,
typed slots (frame elements), and inheritance relationships.  This maps
cleanly to the KG type tier.  Prototypes (structural templates) are not
generated here since FrameNet does not define compositional requirements
beyond the frame element definitions; prototype test data would need to
be synthetic.

Prerequisites:
    pip install nltk
    python -c "import nltk; nltk.download('framenet_v17')"

Usage:
    # Generate full dataset
    python generate_framenet_kgtypes.py -o framenet_kgtypes.vital

    # Quick subset for development
    python generate_framenet_kgtypes.py --limit 50 -o framenet_kgtypes_50.vital

    # Preview a single frame
    python generate_framenet_kgtypes.py --preview Commerce_buy

    # Stats only
    python generate_framenet_kgtypes.py --stats
"""

import argparse
import sys
import uuid
from typing import Optional, List, Dict

from vital_ai_vitalsigns.model.GraphObject import GraphObject
from vital_ai_vitalsigns.block.vital_block import VitalBlock
from vital_ai_vitalsigns.block.vital_block_file import VitalBlockFile
from vital_ai_vitalsigns.block.vital_block_writer import VitalBlockWriter

from ai_haley_kg_domain.model.KGFrameType import KGFrameType
from ai_haley_kg_domain.model.KGSlotType import KGSlotType
from ai_haley_kg_domain.model.Edge_hasSubKGFrameType import Edge_hasSubKGFrameType


# ---------------------------------------------------------------------------
# FrameNet access via NLTK
# ---------------------------------------------------------------------------

def ensure_framenet():
    """Download FrameNet data if not already present."""
    import nltk
    try:
        from nltk.corpus import framenet as fn
        _ = fn.frames()
        return fn
    except LookupError:
        print("Downloading FrameNet 1.7 data...")
        nltk.download('framenet_v17')
        from nltk.corpus import framenet as fn
        return fn


# ---------------------------------------------------------------------------
# URI generation
# ---------------------------------------------------------------------------

_BASE_URI = "urn:vitalgraph:framenet"

# PostgreSQL btree index limit is ~2704 bytes; truncate descriptions to
# stay safely under this (UTF-8 chars can be multi-byte).
_MAX_DESC_LEN = 2500


def _type_uri(prefix: str, name: str) -> str:
    """Generate a deterministic URI from prefix and name."""
    return f"{_BASE_URI}:{prefix}:{name}"


def _edge_uri() -> str:
    """Generate a unique edge URI."""
    return f"{_BASE_URI}:edge:{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# First pass: collect slot type usage across all frames
# ---------------------------------------------------------------------------

def _collect_slot_type_usage(frames) -> Dict[str, dict]:
    """Collect which frames use each FE name and the first definition seen."""
    slot_info: Dict[str, dict] = {}
    for frame in frames:
        for fe in frame.FE.values():
            if fe.name not in slot_info:
                slot_info[fe.name] = {
                    "definition": fe.definition,
                    "frames": [],
                }
            slot_info[fe.name]["frames"].append(frame.name)
    return slot_info


# ---------------------------------------------------------------------------
# GraphObject builders
# ---------------------------------------------------------------------------

def make_frame_type(frame) -> KGFrameType:
    """Create a KGFrameType from a FrameNet frame.

    Enriches the description with core frame element names for better
    keyword and vector search.
    """
    core_fes = [fe.name for fe in frame.FE.values()
                if getattr(fe, 'coreType', '') == 'Core']
    description = frame.definition
    if core_fes:
        description += f" Core participants: {', '.join(core_fes)}."

    ft = KGFrameType()
    ft.URI = _type_uri("frame-type", frame.name)
    ft.name = frame.name
    ft.kGraphDescription = description[:_MAX_DESC_LEN]
    ft.kGFrameTypeExternIdentifier = str(frame.ID)
    return ft


def make_slot_type(fe_name: str, fe_definition: str,
                   used_in_frames: Optional[List[str]] = None) -> KGSlotType:
    """Create a KGSlotType from a FrameNet frame element.

    Enriches the description with cross-frame usage context for better
    vector search recall.
    """
    description = fe_definition
    if used_in_frames:
        frames_str = ', '.join(used_in_frames[:10])
        suffix = (f" (and {len(used_in_frames) - 10} more)"
                  if len(used_in_frames) > 10 else "")
        description += f" Used in frames: {frames_str}{suffix}."

    st = KGSlotType()
    st.URI = _type_uri("slot-type", fe_name)
    st.name = fe_name
    st.kGraphDescription = description[:_MAX_DESC_LEN]
    st.kGSlotTypeName = fe_name
    st.kGSlotTypeLabel = fe_name
    st.kGSlotTypeExternIdentifier = fe_name
    return st


def make_hierarchy_edge(parent_name: str, child_name: str) -> Edge_hasSubKGFrameType:
    """Create an Edge_hasSubKGFrameType for frame inheritance."""
    edge = Edge_hasSubKGFrameType()
    edge.URI = _edge_uri()
    edge.edgeSource = _type_uri("frame-type", parent_name)
    edge.edgeDestination = _type_uri("frame-type", child_name)
    return edge


# ---------------------------------------------------------------------------
# Full generation
# ---------------------------------------------------------------------------

def generate_kgtypes(fn, limit: Optional[int] = None):
    """Generate all KG Type GraphObjects from FrameNet.

    Returns (objects, stats) where objects is a list of GraphObject
    instances and stats is a summary dict.
    """
    frames = fn.frames()
    if limit:
        frames = frames[:limit]

    slot_info = _collect_slot_type_usage(frames)
    seen_slot_types: set = set()
    objects: List[GraphObject] = []

    stats = {
        "frame_types": 0,
        "slot_types": 0,
        "hierarchy_edges": 0,
    }

    for frame in frames:
        # KGFrameType
        objects.append(make_frame_type(frame))
        stats["frame_types"] += 1

        # KGSlotType (fuzzylicated, enriched)
        for fe in frame.FE.values():
            if fe.name not in seen_slot_types:
                info = slot_info[fe.name]
                objects.append(make_slot_type(
                    fe.name, info["definition"],
                    used_in_frames=info["frames"],
                ))
                seen_slot_types.add(fe.name)
                stats["slot_types"] += 1

        # Frame hierarchy edges (Inheritance only)
        for relation in frame.frameRelations:
            if (relation.type.name == "Inheritance"
                    and relation.superFrame.name == frame.name):
                objects.append(make_hierarchy_edge(
                    relation.superFrame.name, relation.subFrame.name,
                ))
                stats["hierarchy_edges"] += 1

    stats["total_objects"] = len(objects)
    return objects, stats


# ---------------------------------------------------------------------------
# Block file writing
# ---------------------------------------------------------------------------

BLOCK_SIZE = 50  # objects per block


def write_vital_block_file(objects: List[GraphObject], output_path: str):
    """Write GraphObjects to a .vital block file."""
    bf = VitalBlockFile(output_path)
    writer = VitalBlockWriter(bf)
    writer.write_header()

    # Write in batches
    for i in range(0, len(objects), BLOCK_SIZE):
        chunk = objects[i:i + BLOCK_SIZE]
        block = VitalBlock(chunk)
        writer.write_block(block)

    writer.close()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def preview_frame(fn, frame_name: str):
    """Print a detailed preview of objects generated for one frame."""
    frame = fn.frame(frame_name)
    print(f"\n{'=' * 70}")
    print(f"Frame: {frame.name} (ID: {frame.ID})")
    print(f"Definition: {frame.definition[:120]}...")
    print(f"{'=' * 70}")

    print(f"\nFrame Elements ({len(frame.FE)}):")
    for fe in frame.FE.values():
        core = getattr(fe, 'coreType', '?')
        print(f"  [{core:>10}] {fe.name}: {fe.definition[:80]}...")

    print(f"\nFrame Relations ({len(frame.frameRelations)}):")
    for rel in frame.frameRelations:
        print(f"  {rel.type.name}: {rel.superFrame.name} -> {rel.subFrame.name}")

    print(f"\n{'-' * 70}")
    print("Generated GraphObjects:")
    print(f"{'-' * 70}")

    ft = make_frame_type(frame)
    print(f"\n  KGFrameType: {ft.URI}")
    print(f"    name = {ft.name}")
    print(f"    kGFrameTypeExternIdentifier = {ft.kGFrameTypeExternIdentifier}")

    for fe in frame.FE.values():
        st = make_slot_type(fe.name, fe.definition)
        print(f"\n  KGSlotType: {st.URI}")
        print(f"    name = {st.name}")

    for rel in frame.frameRelations:
        if rel.type.name == "Inheritance" and rel.superFrame.name == frame.name:
            edge = make_hierarchy_edge(rel.superFrame.name, rel.subFrame.name)
            print(f"\n  Edge_hasSubKGFrameType: {edge.URI}")
            print(f"    {edge.edgeSource} -> {edge.edgeDestination}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate FrameNet KG Type objects as a .vital block file"
    )
    parser.add_argument("--output", "-o", type=str,
                        help="Output .vital block file path")
    parser.add_argument("--preview", "-p", type=str,
                        help="Preview objects for a single frame")
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

    objects, stats = generate_kgtypes(fn, limit=args.limit)

    print("\nFrameNet -> KG Types Statistics:")
    print(f"  Frame types:           {stats['frame_types']}")
    print(f"  Slot types:            {stats['slot_types']}")
    print(f"  Hierarchy edges:       {stats['hierarchy_edges']}")
    print(f"  {'─' * 30}")
    print(f"  Total objects:         {stats['total_objects']}")

    if args.stats:
        return

    if args.output:
        write_vital_block_file(objects, args.output)
        print(f"\nWrote {len(objects)} objects to {args.output}")
    else:
        print("\nNo --output specified. Use -o <path.vital> to write a block file.")
        sys.exit(1)


if __name__ == "__main__":
    main()
