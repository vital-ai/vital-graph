#!/usr/bin/env python3
"""Give an N-Triples dataset its frame groupings and form types, by the rule.

`issues/257`. Exported datasets carry no grouping URIs: the canonical wordnet
export (`kgframe-wordnet-0.0.1.vital` -> `-vt.nt`) has 285,348 frames and no
`hasFrameGraphURI`, `hasKGGraphURI` or `hasKGFormType` at all. A frame update
or upsert REPLACES the frame graph `hasFrameGraphURI` defines (`issues/256`),
so a space loaded from such an export cannot take frame writes safely. This is
the conversion step that fixes the DATA before it is loaded, rather than
repairing the space afterwards.

    1. scripts/convert_vital_to_ntriples.py   .vital -> .nt
    2. THIS SCRIPT                            .nt    -> .nt with groupings
    3. .nt -> CSV, then scripts/load_wordnet_csv.py

THE RULE (decided 2026-10-03), the one `kg_impl/frame_grouping.py` applies on
every write path and the generators emit:

    KGFrame            hasFrameGraphURI = ITSELF, and an explicit hasKGFormType
    Edge_hasKGSlot     hasFrameGraphURI = its source frame
    a slot             hasFrameGraphURI = the frame whose Edge_hasKGSlot links it
    Edge_hasKGFrame /
    Edge_hasEntityKGFrame   no hasFrameGraphURI
    an entity's graph  hasKGGraphURI = the entity on every frame it attaches
                       (Edge_hasEntityKGFrame), their descendants, their slots
                       and the edges among them, and on the entity itself

FORM TYPE, option 2. A frame the input leaves without `hasKGFormType` gets the
classification it has TODAY, made explicit: no grouping in the input ->
Assertion, grouped -> Aspect. For wordnet that is Assertion on every frame,
which is what the space has always read as.

Existing `hasFrameGraphURI` and `hasKGGraphURI` triples are DROPPED and
regenerated, so a wrong input grouping cannot survive. A slot linked from more
than one frame has no single owner; it gets no grouping and is reported.

Two streaming passes over the file: the first reads the structure (only the
URIs it needs are kept in memory), the second copies every other line and
appends the groupings.

    python scripts/add_frame_groupings.py \\
        test_data/kgframe-wordnet-0.0.1-vt.nt \\
        test_data/kgframe-wordnet-0.0.1-vt-grouped.nt
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
import time

KG = "http://vital.ai/ontology/haley-ai-kg#"
VC = "http://vital.ai/ontology/vital-core#"
VITALTYPE = f"{VC}vitaltype"
SRC, DST = f"{VC}hasEdgeSource", f"{VC}hasEdgeDestination"
FGU, KGG, FORM = f"{KG}hasFrameGraphURI", f"{KG}hasKGGraphURI", f"{KG}hasKGFormType"
ASSERTION, ASPECT = f"{KG}KGFormType_Assertion", f"{KG}KGFormType_Aspect"
EDGE_TYPES = {"Edge_hasKGSlot", "Edge_hasKGFrame", "Edge_hasEntityKGFrame"}

# Subject and predicate are always IRIs here; the object may be anything, so
# only a leading IRI object is captured.
LINE = re.compile(r"^<([^>]*)> <([^>]*)> (<([^>]*)>|.*) \.\s*$")


def _scan(path: str):
    """Pass 1: the structure the rule needs, and nothing else."""
    frames, slots = set(), set()
    edge_type, src, dst = {}, {}, {}
    has_form, had_group = set(), set()
    for line in open(path, encoding="utf-8"):
        m = LINE.match(line)
        if not m:
            continue
        s, p, o = m.group(1), m.group(2), m.group(4)
        if p == VITALTYPE and o:
            t = o.rsplit("#", 1)[-1]
            # Edges FIRST: `Edge_hasKGSlot` ends in "Slot" too.
            if t in EDGE_TYPES:
                edge_type[s] = t
            elif t == "KGFrame":
                frames.add(s)
            elif t.endswith("Slot"):
                slots.add(s)
        elif p == SRC and o:
            src[s] = o
        elif p == DST and o:
            dst[s] = o
        elif p == FORM:
            has_form.add(s)
        elif p == FGU:
            had_group.add(s)
    return frames, slots, edge_type, src, dst, has_form, had_group


def groupings(frames, slots, edge_type, src, dst, has_form, had_group):
    """The triples the rule requires, as (subject, predicate, object) IRIs."""
    out = []
    report = collections.Counter()

    # Slot ownership from Edge_hasKGSlot; a slot with two owners gets none.
    owners = collections.defaultdict(set)
    for e, t in edge_type.items():
        if t == "Edge_hasKGSlot" and e in src and e in dst:
            owners[dst[e]].add(src[e])
    shared = {s for s, fs in owners.items() if len(fs) > 1}
    report["slots linked from more than one frame (left ungrouped)"] = len(shared)

    for f in frames:
        out.append((f, FGU, f))
        if f not in has_form:
            out.append((f, FORM, ASPECT if f in had_group else ASSERTION))
            report["form type made explicit: " +
                   ("Aspect" if f in had_group else "Assertion")] += 1
    for e, t in edge_type.items():
        if t == "Edge_hasKGSlot" and e in src:
            out.append((e, FGU, src[e]))
    for s in slots:
        fs = owners.get(s)
        if fs and len(fs) == 1:
            out.append((s, FGU, next(iter(fs))))
        elif not fs:
            report["slots linked from no frame (left ungrouped)"] += 1

    # Entity graphs: frames an entity attaches, their descendants, their
    # slots and the edges among them.
    entity_of = {}
    for e, t in edge_type.items():
        if t == "Edge_hasEntityKGFrame" and e in src and e in dst:
            entity_of[dst[e]] = src[e]
            out.append((e, KGG, src[e]))
            out.append((src[e], KGG, src[e]))       # the entity's self-link (issues/091)
    children = collections.defaultdict(list)
    for e, t in edge_type.items():
        if t == "Edge_hasKGFrame" and e in src and e in dst:
            children[src[e]].append((e, dst[e]))
    stack = list(entity_of)
    while stack:
        f = stack.pop()
        for e, child in children.get(f, ()):
            if child not in entity_of:
                entity_of[child] = entity_of[f]
                stack.append(child)
            out.append((e, KGG, entity_of[f]))
    for f, ent in entity_of.items():
        out.append((f, KGG, ent))
    for e, t in edge_type.items():
        if t == "Edge_hasKGSlot" and src.get(e) in entity_of:
            ent = entity_of[src[e]]
            out.append((e, KGG, ent))
            if e in dst:
                out.append((dst[e], KGG, ent))
    report["frames in an entity graph"] = len(entity_of)
    return list(dict.fromkeys(out)), report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="input .nt")
    ap.add_argument("dst", help="output .nt")
    a = ap.parse_args()
    if a.src == a.dst:
        ap.error("write to a new file; the input is read twice")

    t0 = time.monotonic()
    structure = _scan(a.src)
    frames, slots, edge_type = structure[0], structure[1], structure[2]
    print(f"pass 1: {len(frames):,} frames, {len(slots):,} slots, "
          f"{len(edge_type):,} frame/slot/entity edges ({time.monotonic() - t0:.0f}s)",
          flush=True)
    triples, report = groupings(*structure)

    kept = dropped = 0
    with open(a.dst, "w", encoding="utf-8") as out:
        for line in open(a.src, encoding="utf-8"):
            m = LINE.match(line)
            if m and m.group(2) in (FGU, KGG):
                dropped += 1                 # regenerated below, never trusted
                continue
            out.write(line if line.endswith("\n") else line + "\n")
            kept += 1
        for s, p, o in triples:
            out.write(f"<{s}> <{p}> <{o}> .\n")
    print(f"pass 2: {kept:,} lines kept, {dropped:,} input grouping triples dropped, "
          f"{len(triples):,} grouping/form-type triples added "
          f"({time.monotonic() - t0:.0f}s)")
    for k, v in sorted(report.items()):
        print(f"  {v:>10,}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
