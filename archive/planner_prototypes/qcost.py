"""Scoring plans over the annotated query tree (planning_planner/09, part 2).

Cost is C_out, the sum of intermediate result rows, as `bgp_cardinality` uses,
computed only from the tree's numbers (`qtree`). No weighting of index probes,
hashes or sorts until a measured reason calls for one.

The plan shape scored here is the one the dashboard queries take: a HUB unit
(`?d`) with other units linked to it through their link leaf
(`?o hasKGGraphURI ?d`), inside the hub's BGP or in OPTIONAL blocks. Each
linked unit is reached one of two ways:

    anchor   evaluate the unit from its own anchor (rows r, one row per
             subject probe after it), then join it to the hub on the link
             variable. Cost: r * (1 + probes) + the join's output.
    probe    from each hub row, probe the link BY OBJECT (hub rows x fan-out),
             then check the unit's anchor and probes per candidate.
             Cost: hub rows x fan-out + output x (1 + other probes).

`choices()` lists both per unit; `score()` prices one assignment of modes to
units; `rank()` prices every assignment (small: 2^units) and sorts them. The
search proper (DP over units) replaces `rank()` when queries grow beyond what
enumeration affords.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from vitalgraph.db.sparql_sql.qtree import Block, Est, Unit

ANCHOR, PROBE = "anchor", "probe"


@dataclass
class Linked:
    """A unit (or a block rooted at one) attached to the hub by a link."""
    name: str                       # the unit's subject, e.g. "?o"
    unit: Unit
    optional: bool
    extra: Optional[Block] = None   # the rest of its block (e.g. NAICS' frame unit)


@dataclass
class Scored:
    modes: Dict[str, str]
    cost: float
    rows: float
    parts: List[Tuple[str, str, float]] = field(default_factory=list)  # (unit, mode, cost)


def _star(b: Block) -> Tuple[Optional[Unit], List[Linked]]:
    """Find the hub and every unit linked to it, through the left-join chain."""
    hub, linked = None, []

    def visit(blk: Block, optional: bool):
        nonlocal hub
        if blk.kind == "bgp":
            targets = {k.target_var for u in blk.units for k in u.links}
            for u in blk.units:
                if hub is None and u.subject.startswith("?") and u.subject[1:] in targets \
                        and not any(k.target_var != u.subject[1:] for k in u.links):
                    hub = u
            for u in blk.units:
                if hub is not None and u is hub:
                    continue
                to_hub = [k for k in u.links if hub is not None and k.target_var == hub.subject[1:]]
                if to_hub:
                    # Only units that hang off THIS unit (its other links, e.g.
                    # NAICS' frame), never its siblings on the same hub.
                    hang = {k.target_var for k in u.links if k.target_var != hub.subject[1:]}
                    rest = [x for x in blk.units if x.subject[1:] in hang]
                    linked.append(Linked(u.subject, u, optional,
                                         Block(kind="bgp", rows=blk.rows, units=rest) if rest else None))
            return
        for i, c in enumerate(blk.children):
            visit(c, optional or (blk.kind == "left_join" and i == 1))
    visit(b, False)
    return hub, linked


def _unit_anchor_cost(u: Unit) -> Tuple[float, float]:
    r = u.rows.rows or 0.0
    return r * (1 + len(u.probes)), r


def _link_to(u: Unit, hub: Unit):
    return next(k for k in u.links if k.target_var == hub.subject[1:])


def _extra_cost(extra: Optional[Block], u: Unit) -> Tuple[float, Optional[float]]:
    """Units that hang off a linked unit inside its own block (NAICS' frame):
    evaluated from their anchor and joined by containment."""
    if extra is None:
        return 0.0, None
    cost, cap = 0.0, None
    for x in extra.units:
        c, r = _unit_anchor_cost(x)
        cost += c
        cap = r if cap is None else min(cap, r)
    return cost, cap


def score(hub: Unit, linked: List[Linked], modes: Dict[str, str]) -> Scored:
    hub_cost, hub_rows = _unit_anchor_cost(hub)
    total, rows = hub_cost, hub_rows
    parts = [(hub.subject, "hub", hub_cost)]
    for L in linked:
        u, mode = L.unit, modes[L.name]
        ur = u.rows.rows or 0.0
        xc, cap = _extra_cost(L.extra, u)
        matched = min(rows, ur if cap is None else min(ur, cap))   # containment on the hub key
        if mode == ANCHOR:
            c, _ = _unit_anchor_cost(u)
            c += xc + matched                       # + the join's output
        else:
            link = _link_to(u, hub)
            fan = link.by_object.rows or 0.0
            candidates = rows * fan                 # probe the link by object
            c = candidates + matched * (1 + max(0, len(u.probes) - 1)) + xc
        # an inner join narrows the hub rows; a left join keeps them
        if not L.optional:
            rows = matched
        total += c
        parts.append((L.name, mode, c))
    return Scored(modes=dict(modes), cost=total, rows=rows, parts=parts)


def rank(tree: Block) -> Tuple[Optional[Unit], List[Linked], List[Scored]]:
    hub, linked = _star(tree)
    if hub is None:
        return None, [], []
    names = [L.name for L in linked]
    out = []
    for combo in itertools.product((ANCHOR, PROBE), repeat=len(names)):
        out.append(score(hub, linked, dict(zip(names, combo))))
    out.sort(key=lambda s: s.cost)
    return hub, linked, out
