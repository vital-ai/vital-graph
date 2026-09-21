#!/usr/bin/env python3
"""`issues/225` — an object the frame writer does not handle must not vanish.

`categorize_frame_objects` sorted a payload into frames, slots and edges with
NO `else` branch, so anything else joined no list and ceased to exist. The
caller still got `success=True` and `status: "updated"`, because the frames it
DID recognise were written.

The live case is a `KGEntity`: passing it alongside its frames is the natural
way to change an entity property and a frame slot in one write. It survives
ownership validation (non-frames are passed through deliberately, since slots
and edges must be), has its grouping URI assigned, and is then dropped.

These tests pin the SILENCE, not the discarding. Writing the entity node is a
separate, larger change; `issues/225` fix 1 is only that a partly-discarded
payload stops reporting plain success.

    python3 tests/unit/test_frame_update_does_not_discard_a_payload_silently.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGEntity import KGEntity
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGTextSlot import KGTextSlot

from vitalgraph.kg_impl.kgentity_frame_create_impl import (
    KGEntityFrameCreateProcessor)


def _payload(with_entity: bool):
    """A frame, its edge and its slot — optionally with the entity node too."""
    frame = KGFrame()
    frame.URI = "urn:test:frame:1"
    slot = KGTextSlot()
    slot.URI = "urn:test:slot:1"
    slot.textSlotValue = "message_ready"
    edge = Edge_hasKGSlot()
    edge.URI = "urn:test:edge:1"
    edge.edgeSource = "urn:test:frame:1"
    edge.edgeDestination = "urn:test:slot:1"
    objs = [frame, edge, slot]
    if with_entity:
        entity = KGEntity()
        entity.URI = "urn:test:entity:1"
        objs.insert(0, entity)
    return objs


async def _categorize(objs):
    return await KGEntityFrameCreateProcessor().categorize_frame_objects(objs)


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    ok = True
    print(__doc__.strip().splitlines()[0])
    print()

    # 1. The entity node is REPORTED, where it used to be lost without trace.
    cats = asyncio.run(_categorize(_payload(with_entity=True)))
    names = sorted({type(o).__name__ for o in cats.unhandled})
    ok &= check("a KGEntity in the payload is reported as unhandled",
                names == ["KGEntity"], f"unhandled={names}")

    # It is still NOT written. Asserted so that implementing fix 2 has to come
    # here and change this line deliberately, rather than silently inverting
    # what this test claims.
    kept = list(cats.frame_objects) + list(cats.slot_objects) + list(cats.edge_objects)
    ok &= check("and is still not written (fix 1 is visibility, not support)",
                not any(isinstance(o, KGEntity) for o in kept))

    # 2. THE CONTROL. Without it, cell 1 would pass against an implementation
    #    that reports everything as unhandled — which would be noise on every
    #    ordinary write. This is the cell that makes the first one mean
    #    something, and it is the pairing `issues/210` needed for the same
    #    reason.
    cats_ok = asyncio.run(_categorize(_payload(with_entity=False)))
    ok &= check("an ordinary frame payload reports NOTHING unhandled",
                cats_ok.unhandled == [], f"unhandled={cats_ok.unhandled}")
    ok &= check("and still categorises all three objects",
                len(cats_ok.frame_objects) == 1 and len(cats_ok.slot_objects) == 1
                and len(cats_ok.edge_objects) == 1,
                f"{len(cats_ok.frame_objects)}f/{len(cats_ok.slot_objects)}s/"
                f"{len(cats_ok.edge_objects)}e")

    # 3. The message a caller actually reads must name it. A log line is not
    #    enough: `status: "updated"` is the only signal the caller gets.
    from vitalgraph.kg_impl.kgentity_frame_create_impl import CreateFrameResult
    r = CreateFrameResult(success=True, created_uris=[], message="x", frame_count=0,
                          unhandled_types=["KGEntity"])
    ok &= check("CreateFrameResult carries the unhandled type names",
                r.unhandled_types == ["KGEntity"])
    ok &= check("and defaults to empty rather than None",
                CreateFrameResult(success=True, created_uris=[], message="x",
                                  frame_count=0).unhandled_types == [])

    # 4. THE SECOND COPY. `kgframe_create_impl` defines its own
    #    FrameObjectCategories and its own categorize_frame_objects, with the
    #    same three branches and the same missing else, and it is reachable
    #    from /kgframes (kgframes_endpoint.py:2340). Fixing one copy and
    #    leaving the other is the asymmetry that keeps producing defects in
    #    this codebase -- resync_all.py was the same mistake the same day.
    from vitalgraph.kg_impl.kgframe_create_impl import (
        KGFrameCreateProcessor, CreateFrameResult as FrameCreateResult)
    cats2 = asyncio.run(
        KGFrameCreateProcessor().categorize_frame_objects(_payload(with_entity=True)))
    names2 = sorted({type(o).__name__ for o in cats2.unhandled})
    ok &= check("the /kgframes copy reports it too",
                names2 == ["KGEntity"], f"unhandled={names2}")
    cats2_ok = asyncio.run(
        KGFrameCreateProcessor().categorize_frame_objects(_payload(with_entity=False)))
    ok &= check("and its control reports nothing unhandled",
                cats2_ok.unhandled == [], f"unhandled={cats2_ok.unhandled}")
    ok &= check("and its result carries the type names",
                FrameCreateResult(success=True, created_uris=[], message="x",
                                  frame_count=0).unhandled_types == [])

    print()
    print("OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
