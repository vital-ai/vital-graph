"""Find multi-hop traversal chains in a plan, and which end is pinned.

The pipeline detects each HOP and never the CHAIN.
`rewrite_frame_entity_table` collapses a hop's six tables into one
`frame_entity` row, correctly and per hop, so a depth-3 walk becomes three
references. What links them exists only as ordinary join conditions:

    femv0.source_entity_uuid = '<pinned entity>'::uuid
    femv1.source_entity_uuid = femv0.dest_entity_uuid
    femv2.source_entity_uuid = femv1.dest_entity_uuid

Everything needed is there and nothing reads it as a chain, so no pass can order
the joins to drive from the pinned end or evaluate hop by hop, and PostgreSQL is
left inferring the shape from thirty-odd tables with row estimates of 1. The
cost, measured on graph_synth_10k at depth 3 with the same answer throughout:

    hand-written hop-wise CTEs        0.9 ms
    generated SQL, joins forced      45.1 ms
    generated SQL, planner's choice  58.9 ms

TWO SHAPES

    frame traversal   entity -> frame -> slot -> entity, collapsed to
                      {space}_frame_entity(frame, source_entity, dest_entity)
    relation          entity -> entity over Edge_hasKGRelation, collapsed to
                      {space}_edge(edge, source_node, dest_node)

They differ in the table and the column names and in nothing else that matters,
so this is written against a (source column, destination column) descriptor per
table kind. Writing it for frames alone is how the slot-listing endpoint came to
implement one linkage of two and report "no slots found" for the other.

DELIBERATELY INERT

This detects and records. It changes no SQL. A pass that finds the right thing
and does nothing can be checked against real queries before any plan changes
shape — worth more than speed here, given how many plausible fixes in this area
have measured worse (`issues/090` records three).

LINKS, NOT ENTITY VARIABLES

A chain is an ordered list of LINKS each with its own source and destination.
That looks like over-modelling for a line of entity hops, and it is not: nested
frames are coming, where a slot holds another FRAME rather than an entity —

    frame1 -> frame2 -> slot1 -> entity1
              frame2 -> slot2 -> entity2

so the far end of a hop is not always an entity, and a chain can fan out
mid-path into a tree. A line is the degenerate tree; modelling links keeps that
extension open instead of baking entity-to-entity into the representation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ir import PlanV2, KIND_BGP

logger = logging.getLogger(__name__)

# Per table kind: the column a hop ARRIVES on, and the column it LEAVES by.
# Adding a traversal shape means adding a line here, not a branch below.
_TRAVERSAL_KINDS: Dict[str, Tuple[str, str]] = {
    "frame_entity": ("source_entity_uuid", "dest_entity_uuid"),
    "edge": ("source_node_uuid", "dest_node_uuid"),
}

_CONST_RE = re.compile(r"__CONST_(\w+)__|'([0-9a-fA-F-]{36})'::uuid")


@dataclass
class ChainLink:
    """One hop: the table that carries it and the columns it joins on."""
    ref_id: str
    kind: str
    source_col: str
    dest_col: str


@dataclass
class TraversalChain:
    """An ordered run of links, plus which end (if either) is pinned.

    `pinned_head` means the FIRST link's source is constrained to a constant, so
    the chain can be driven forwards from a single row. `pinned_tail` is the
    mirror. Both can be true — a query pinned at both ends is a reachability
    question, and the shorter side is the one to drive from, which is why the
    length is kept rather than just a boolean.
    """
    links: List[ChainLink] = field(default_factory=list)
    pinned_head: bool = False
    pinned_tail: bool = False

    @property
    def depth(self) -> int:
        return len(self.links)

    @property
    def kind(self) -> str:
        return self.links[0].kind if self.links else ""

    def __repr__(self):
        ends = ("head" if self.pinned_head else "") + \
               ("+tail" if self.pinned_tail else "")
        return (f"TraversalChain({self.kind} depth={self.depth} "
                f"pinned={ends or 'none'} {[l.ref_id for l in self.links]})")


def _traversal_tables(bgp: PlanV2) -> Dict[str, ChainLink]:
    out: Dict[str, ChainLink] = {}
    for tbl in (bgp.tables or []):
        cols = _TRAVERSAL_KINDS.get(tbl.kind)
        if cols:
            out[tbl.ref_id] = ChainLink(ref_id=tbl.ref_id, kind=tbl.kind,
                                        source_col=cols[0], dest_col=cols[1])
    return out


def _constraints(bgp: PlanV2) -> List[str]:
    return list(bgp.constraints or []) + [sql for _tag, sql in
                                          (bgp.tagged_constraints or [])]


def _pinned_vars(plan: PlanV2, out: set, depth: int = 0) -> set:
    """Variables an equality FILTER binds to a constant, anywhere in the plan.

    Read from the PARSED QUERY rather than from constraint text, because the
    text does not have it yet: `push_filters` runs during emit, so at detection
    time the BGP carries the chain's join conditions and not the pin. Reading
    `FILTER(?e0 = <uri>)` directly also means detection does not depend on
    whether the push-down fired — which is the sort of coupling that makes a
    pass work until an unrelated optimisation declines.
    """
    from vitalgraph.db.jena_sparql.jena_types import (
        ExprFunction, ExprValue, ExprVar)
    if plan is None or depth > 24:
        return out
    for expr in (plan.filter_exprs or []):
        if not isinstance(expr, ExprFunction) or (expr.name or "").lower() != "eq":
            continue
        args = list(expr.args or [])
        if len(args) != 2:
            continue
        for a, b in ((args[0], args[1]), (args[1], args[0])):
            if isinstance(a, ExprVar) and isinstance(b, ExprValue):
                out.add(a.var)
    for child in (plan.children or []):
        _pinned_vars(child, out, depth + 1)
    return out


def find_chains(plan: PlanV2, depth: int = 0,
                pinned: Optional[set] = None) -> List[TraversalChain]:
    """Every traversal chain reachable from `plan`, longest first.

    Links are followed through the JOIN CONDITION, never through adjacency in
    the table list: two `frame_entity` references that share no variable are not
    a hop sequence, and pairing them by position would invent a chain the query
    does not contain.
    """
    if plan is None or depth > 24:
        return []
    if pinned is None:
        pinned = _pinned_vars(plan, set())

    chains: List[TraversalChain] = []
    if plan.kind == KIND_BGP and plan.tables:
        chains.extend(_chains_in_bgp(plan, pinned))
    for child in (plan.children or []):
        chains.extend(find_chains(child, depth + 1, pinned))

    chains.sort(key=lambda c: c.depth, reverse=True)
    return chains


def _chains_in_bgp(bgp: PlanV2, pinned_vars: set) -> List[TraversalChain]:
    links = _traversal_tables(bgp)
    if len(links) < 1:
        return []

    conds = _constraints(bgp)

    # successor[a] = b  when  b.source == a.dest, i.e. hop b follows hop a.
    successor: Dict[str, str] = {}
    predecessor: Dict[str, str] = {}
    for a in links.values():
        for b in links.values():
            if a.ref_id == b.ref_id:
                continue
            wanted = (f"{b.ref_id}.{b.source_col} = {a.ref_id}.{a.dest_col}",
                      f"{a.ref_id}.{a.dest_col} = {b.ref_id}.{b.source_col}")
            if any(w in c for c in conds for w in wanted):
                successor[a.ref_id] = b.ref_id
                predecessor[b.ref_id] = a.ref_id

    # (ref_id, column) -> variable, so a chain end can be matched against the
    # variables the query pins. The rewrite records both positions of a shared
    # variable, e.g. e1 -> [(femv0, dest), (femv1, source)], which is also what
    # makes the successor links findable.
    col_var: Dict[Tuple[str, str], str] = {}
    for var, slot in (bgp.var_slots or {}).items():
        for ref_id, col in (getattr(slot, "positions", None) or []):
            col_var[(ref_id, col)] = var

    def _pinned(ref_id: str, col: str) -> bool:
        """Is this end of the chain fixed to one value?

        Either because a FILTER pins the variable sitting there, or because the
        constant is already in the constraint — a query written with the term
        inline rather than as a FILTER. Both mean the chain can be driven from a
        single row instead of the whole relation.
        """
        if col_var.get((ref_id, col)) in pinned_vars:
            return True
        needle = f"{ref_id}.{col} = "
        for c in conds:
            i = c.find(needle)
            if i >= 0 and _CONST_RE.search(c[i + len(needle):i + len(needle) + 60]):
                return True
        return False

    chains: List[TraversalChain] = []
    seen: set = set()
    for ref_id in links:
        if ref_id in predecessor or ref_id in seen:
            continue                      # not a head, or already walked
        ordered: List[ChainLink] = []
        cur: Optional[str] = ref_id
        while cur is not None and cur not in seen:
            seen.add(cur)
            ordered.append(links[cur])
            cur = successor.get(cur)
        if ordered:
            chains.append(TraversalChain(
                links=ordered,
                pinned_head=_pinned(ordered[0].ref_id, ordered[0].source_col),
                pinned_tail=_pinned(ordered[-1].ref_id, ordered[-1].dest_col)))

    # A cycle has no head, so nothing above reaches it. Emit each remaining
    # link as its own single-hop chain rather than dropping it silently.
    for ref_id, link in links.items():
        if ref_id not in seen:
            seen.add(ref_id)
            chains.append(TraversalChain(
                links=[link],
                pinned_head=_pinned(ref_id, link.source_col),
                pinned_tail=_pinned(ref_id, link.dest_col)))
    return chains


def describe_chains(plan: PlanV2) -> List[TraversalChain]:
    """Find chains and LOG them.

    Observability is the point of this step. Every wrong turn in this area has
    been a pass that quietly declined — correct, slower, and invisible — so a
    detector that finds nothing must say so where it can be seen.
    """
    chains = find_chains(plan)
    multi = [c for c in chains if c.depth > 1]
    if multi:
        logger.info("traversal: %d chain(s), deepest %d hops (%s), pinned=%s",
                    len(multi), multi[0].depth, multi[0].kind,
                    "head" if multi[0].pinned_head else
                    ("tail" if multi[0].pinned_tail else "neither"))
    else:
        logger.debug("traversal: no multi-hop chain found (%d single hop(s))",
                     len(chains))
    return chains
