"""The one place a frame grouping (`hasFrameGraphURI`) is decided.

`hasFrameGraphURI` IS the definition of a frame graph, and every frame is
grouped with ITSELF (`issues/256`, `issues/257`, decided 2026-10-03):

- a `KGFrame`'s grouping is its own URI;
- a slot's is the frame that links it by `Edge_hasKGSlot`;
- an `Edge_hasKGSlot`'s is its source frame;
- an `Edge_hasKGFrame` (parent -> child) has NONE (decided 2026-10-03), like
  `Edge_hasEntityKGFrame`: a structural link between frames belongs to no
  frame's graph, so a shallow `update` of either frame leaves it alone and only
  a subtree operation (`replace`, recursive delete) removes it, explicitly.

Nothing a frame does not own carries its grouping. That keeps `update` shallow
and leaves `replace` as the only subtree operation.

THE SERVER DECIDES, ALWAYS. Every grouping a client sent is discarded before
anything is assigned. Grouping URIs are server-enforced
(`frame_hierarchy_consistency_plan.md` §5), and before this module there were
eight places that assigned them, each with its own gaps: a slot with no edge in
a multi-frame payload, an edge whose source frame was not in the payload, and
any slot outside a six-class list all kept whatever the client sent. A
production copy holds 925 slots and their child frames grouped under the ROOT
frame (`issues/257`), which is the shape those gaps let through.

A slot whose owning frame cannot be determined is REFUSED, not written
ungrouped: an ungrouped slot is invisible to its frame's graph and survives
that frame's replace.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from ai_haley_kg_domain.model.Edge_hasEntityKGFrame import Edge_hasEntityKGFrame
from ai_haley_kg_domain.model.Edge_hasKGFrame import Edge_hasKGFrame
from ai_haley_kg_domain.model.Edge_hasKGSlot import Edge_hasKGSlot
from ai_haley_kg_domain.model.KGFrame import KGFrame
from ai_haley_kg_domain.model.KGSlot import KGSlot
from vital_ai_vitalsigns.model.VITAL_Edge import VITAL_Edge

from .refusals import RequestRefused


class UngroupableSlot(RequestRefused):
    """A slot's owning frame cannot be determined, so nothing was written.

    A caller error, answered INVALID_REQUEST in a 200: the request must carry
    the slot's `Edge_hasKGSlot`, or name exactly one frame.
    """

    def __init__(self, slot_uris: List[str]):
        self.slot_uris = slot_uris
        shown = ", ".join(slot_uris[:5]) + (" ..." if len(slot_uris) > 5 else "")
        super().__init__(
            f"cannot determine the owning frame of {len(slot_uris)} slot(s): "
            f"{shown}. Send each slot's Edge_hasKGSlot in the request, or send "
            f"exactly one frame (issues/257)")


def _uri(value) -> Optional[str]:
    return str(value) if value else None


def assign_frame_groupings(objects: Iterable,
                           owning_frame_uri: Optional[str] = None) -> None:
    """Set `hasFrameGraphURI` on every object, discarding what the client sent.

    `owning_frame_uri` is the frame a route already knows its slots belong to
    (the slot route's `frame_uri`). It is used for a slot no `Edge_hasKGSlot`
    in the payload claims, before the single-frame fallback.

    Raises `UngroupableSlot` if any slot's owning frame cannot be determined.
    In that case the groupings already assigned are not a partial write:
    nothing has been stored yet.
    """
    objects = list(objects)
    frame_uris = {str(o.URI) for o in objects if isinstance(o, KGFrame)}
    single_frame = next(iter(frame_uris)) if len(frame_uris) == 1 else None

    # Ownership comes from the edge, wherever its source frame is: an
    # Edge_hasKGSlot names its owner whether or not that frame is in this
    # request.
    slot_owner = {}
    for o in objects:
        if isinstance(o, Edge_hasKGSlot):
            src, dst = _uri(o.edgeSource), _uri(o.edgeDestination)
            if src and dst:
                slot_owner[dst] = src

    ungroupable: List[str] = []
    for o in objects:
        if not hasattr(o, "frameGraphURI"):
            continue
        o.frameGraphURI = None                 # the client's value never survives

        if isinstance(o, KGFrame):
            o.frameGraphURI = str(o.URI)
        elif isinstance(o, KGSlot):
            owner = (slot_owner.get(str(o.URI)) or owning_frame_uri or single_frame)
            if owner:
                o.frameGraphURI = owner
            else:
                ungroupable.append(str(o.URI))
        elif isinstance(o, Edge_hasKGSlot):
            src = _uri(o.edgeSource)
            if src:
                o.frameGraphURI = src
        elif isinstance(o, (Edge_hasEntityKGFrame, Edge_hasKGFrame)):
            # Structural links between an entity and a frame, or a parent frame
            # and a child: in NO frame's graph (decided 2026-10-03). This was
            # inconsistent: `/kgframes` grouped a parent -> child edge with the
            # child, the entity route gave it none, and the dead hierarchical
            # processor gave it the parent.
            pass
        elif isinstance(o, VITAL_Edge):
            # Any other edge: with its source frame if that frame is in the
            # request, else with the request's only frame, as before.
            src = _uri(o.edgeSource)
            if src in frame_uris:
                o.frameGraphURI = src
            elif single_frame:
                o.frameGraphURI = single_frame
        # Anything else (a KGEntity in an entity payload, ...) is in no frame's
        # graph, so its grouping stays cleared.

    if ungroupable:
        raise UngroupableSlot(ungroupable)
