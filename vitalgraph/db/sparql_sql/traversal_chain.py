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

    # A CONSTRAINED end is not the same as a pinned one. Pinned means "fixed to
    # one value", which is what `_pinned` above answers. Constrained means the
    # end carries a type predicate against a constant — `?slot hasKGSlotType
    # <CompanyName>` — which admits a SET, not a row.
    #
    # That distinction is the whole of issues/090's direction problem. A
    # constrained end can be the better side to drive from when its set is
    # smaller than the other end's, and the gate could not see it at all: only
    # a pinned end counted, so a query constrained at one end and open at the
    # other was declined as "neither end pinned".
    #
    # Stored as (predicate_uuid, object_uuid) so `decide` can price it against
    # rdf_stats. Detection here, pricing there, because the statistics are
    # loaded at a later stage than chain detection.
    head_constraint: Optional[tuple] = None
    tail_constraint: Optional[tuple] = None
    # WHICH table carries each end's constraint. The emitter has to hoist that
    # table out of the criteria fence to drive from it, and identifying it again
    # downstream is not reliable: by emit time the constants are still
    # `__CONST_c_N__` tokens — `substitute_constants` resolves them at the very
    # end — so matching the pair's uuids against the constraint SQL finds
    # nothing. Recorded here, where the alias is already in hand (issues/090).
    head_constraint_alias: Optional[str] = None
    tail_constraint_alias: Optional[str] = None

    def reversed(self) -> "TraversalChain":
        """The same chain walked from the other end.

        Only the ORDER matters to emission: `partition_hops` keys off
        `link.ref_id` and nothing downstream reads `source_col`/`dest_col`, and
        `_place` assigns each constraint to the highest hop it mentions — a rule
        that is already indifferent to which way the numbering runs. So driving
        from the tail is this list reversed, not a second emitter.

        The columns are swapped anyway so the object stays truthful about which
        end a hop arrives on; a later reader of `source_col` would otherwise get
        a chain that lies about its own direction.
        """
        return TraversalChain(
            links=[ChainLink(ref_id=l.ref_id, kind=l.kind,
                             source_col=l.dest_col, dest_col=l.source_col)
                   for l in reversed(self.links)],
            pinned_head=self.pinned_tail,
            pinned_tail=self.pinned_head,
            head_constraint=self.tail_constraint,
            tail_constraint=self.head_constraint,
            head_constraint_alias=self.tail_constraint_alias,
            tail_constraint_alias=self.head_constraint_alias)

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


def _as_uuid_pair(pred, obj):
    """(predicate, object) as TERM UUIDs, or None.

    `leaf_terms` records constants as `(term_text, term_type)`; `rdf_stats` —
    which prices a constrained end — is keyed by term UUID. Returning the raw
    text pair looks right and silently never matches a statistic, so the end
    prices as unknown and the direction is never chosen. Converted here, with
    the same deterministic UUIDv5 the writer uses, so the two agree by
    construction rather than by luck.
    """
    if not pred or not obj:
        return None
    try:
        from .emit_update import _generate_term_uuid
        p_text, p_type = pred[0], pred[1]
        o_text, o_type = obj[0], obj[1]
    except Exception:
        return None
    # A typed or language-tagged object hashes with those in the key, and
    # leaf_terms does not carry them here — so only plain URIs are priced.
    if p_type != "U" or o_type != "U":
        return None
    return (_generate_term_uuid(p_text, p_type),
            _generate_term_uuid(o_text, o_type))


def _pinned_vars(plan: PlanV2, out: set, depth: int = 0) -> set:
    """Variables an equality FILTER binds to a constant, anywhere in the plan.

    Read from the PARSED QUERY. `push_filters` runs during emit, so at detection
    time the BGP carries the chain's join conditions and not the pin; reading
    the filter expression also means detection does not depend on whether the
    push-down fired.
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
    """Every traversal chain reachable from `plan`, longest first."""
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
    """Link the hops in one BGP using the plan's STRUCTURE.

    Everything here reads `var_slots` and `leaf_terms` — the records collect()
    makes — and nothing parses emitted SQL. Two hops are consecutive when THE
    SAME VARIABLE sits at one's destination and the next one's source, which is
    what "the walk continues" means; a variable is what the SPARQL actually
    said, whereas the constraint string is one rendering of it.

    Matching constraint text was the first implementation and it is the mistake
    `reorder_joins` documents at length: its cardinality lookup regex-parsed
    constraint SQL, could not read the shape this pipeline emits, and left every
    selectivity decision running on infinity — two criteria in opposite order
    gave the same join order and differed 8x (`issues/061`). Text matching here
    would break on a spacing change, on the operands being emitted in the other
    order, or on a hop whose join is expressed through a third table.
    """
    links = _traversal_tables(bgp)
    if not links:
        return []

    # (ref_id, column) -> variable, from the structural record.
    col_var: Dict[Tuple[str, str], str] = {}
    for var, slot in (bgp.var_slots or {}).items():
        for ref_id, col in (getattr(slot, "positions", None) or []):
            col_var[(ref_id, col)] = var

    # A variable at hop A's destination and hop B's source means B follows A.
    # Built from the variable's own position list rather than by pairing tables.
    source_of: Dict[str, str] = {}      # var -> ref_id whose SOURCE it is
    dest_of: Dict[str, str] = {}        # var -> ref_id whose DEST it is
    for ref_id, link in links.items():
        v_src = col_var.get((ref_id, link.source_col))
        v_dst = col_var.get((ref_id, link.dest_col))
        if v_src is not None:
            source_of[v_src] = ref_id
        if v_dst is not None:
            dest_of[v_dst] = ref_id

    successor: Dict[str, str] = {}
    predecessor: Dict[str, str] = {}
    for var, a_ref in dest_of.items():
        b_ref = source_of.get(var)
        if b_ref is not None and b_ref != a_ref:
            successor[a_ref] = b_ref
            predecessor[b_ref] = a_ref

    leaf_terms = getattr(bgp, "leaf_terms", None) or {}

    def _pinned(ref_id: str, col: str) -> bool:
        """Is this end fixed to one value?

        Either a FILTER pins the variable sitting there, or collect() recorded a
        constant term at that column — a query written with the term inline
        rather than as a FILTER. `leaf_terms` is that record; reading it means
        no assumption about how the constant is rendered in SQL.
        """
        if col_var.get((ref_id, col)) in pinned_vars:
            return True
        return (ref_id, col) in leaf_terms

    def _constrained(ref_id: str, col: str):
        """A type-ish constraint on this end, as ((pred_uuid, obj_uuid), alias).

        The end's variable must also be the SUBJECT of some quad table whose
        predicate and object are both constants. `leaf_terms` records the
        constants collect() resolved, keyed by (alias, column) — so this asks
        for a table where subject is the chain end's variable and both other
        columns are known.

        Returns (None, None) when the end is open, or when the constraint
        cannot be priced (a variable predicate or object), because an
        unpriceable constraint is no basis for choosing a direction.
        """
        end_var = col_var.get((ref_id, col))
        if end_var is None:
            return None, None
        for (alias, c), term in leaf_terms.items():
            if c != "subject_uuid":
                continue
            if col_var.get((alias, "subject_uuid")) != end_var:
                continue
            pair = _as_uuid_pair(leaf_terms.get((alias, "predicate_uuid")),
                                 leaf_terms.get((alias, "object_uuid")))
            if pair:
                return pair, alias
        # The ordinary case: the end variable is the SUBJECT of a table whose
        # predicate and object are the constants.
        for (alias, c) in list(leaf_terms):
            if c != "predicate_uuid":
                continue
            if col_var.get((alias, "subject_uuid")) != end_var:
                continue
            pair = _as_uuid_pair(leaf_terms.get((alias, "predicate_uuid")),
                                 leaf_terms.get((alias, "object_uuid")))
            if pair:
                return pair, alias
        return None, None


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
            _head = _constrained(ordered[0].ref_id, ordered[0].source_col)
            _tail = _constrained(ordered[-1].ref_id, ordered[-1].dest_col)
            chains.append(TraversalChain(
                links=ordered,
                pinned_head=_pinned(ordered[0].ref_id, ordered[0].source_col),
                pinned_tail=_pinned(ordered[-1].ref_id, ordered[-1].dest_col),
                head_constraint=_head[0], head_constraint_alias=_head[1],
                tail_constraint=_tail[0], tail_constraint_alias=_tail[1]))

    # A cycle has no head, so the walk above never starts on it. Emit each
    # remaining link rather than dropping it silently.
    for ref_id, link in links.items():
        if ref_id not in seen:
            seen.add(ref_id)
            _head = _constrained(ref_id, link.source_col)
            _tail = _constrained(ref_id, link.dest_col)
            chains.append(TraversalChain(
                links=[link],
                pinned_head=_pinned(ref_id, link.source_col),
                pinned_tail=_pinned(ref_id, link.dest_col),
                head_constraint=_head[0], head_constraint_alias=_head[1],
                tail_constraint=_tail[0], tail_constraint_alias=_tail[1]))
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
