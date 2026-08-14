"""Emit a traversal chain hop by hop, so the pinned end drives the walk.

Step 3 of `planning_performance/traversal_chain_plan.md`. `traversal_chain`
finds the chain and `traversal_decision` says whether to walk it hop-wise; this
is the part that changes the SQL.

WHAT IS WRONG WITH THE FLAT JOIN

A depth-3 filtered walk emits nine tables in one join. Every row estimate in it
is 1 (`issues/090`), so PostgreSQL picks a root essentially arbitrarily — and it
picks the criterion, not the pin. Measured on graph_synth_10k, `score >= 50`,
depth 3, one start entity:

    generated flat join     70,180 buffers   planning 26.5 ms   execution 56.6 ms
    nested CROSS JOIN LATERAL   194 buffers   planning 30.0 ms   execution  1.9 ms

Same answer. 362x fewer buffers and 29x less execution; planning is a flat ~28 ms
either way, which is the whole reason wall-clock shows 13x rather than 29x. The
flat plan drove from `q19` — hop 2's score criterion — and probed the pinned
entity last. The nested form drives from `femv0.source_entity_uuid = <pin>`,
which is 7 rows, and probes outward.

NESTED, NOT SEQUENTIAL

The measurement in the plan doc was for `CROSS JOIN LATERAL (... OFFSET 0)` per
hop and did not say how the laterals compose. It matters, and only one of the
two options works here.

Sequential laterals — `FROM a CROSS JOIN LATERAL (x) l1 CROSS JOIN LATERAL (y)
l2` — put each hop in its own scope. `l2` can see `a` and `l1`'s OUTPUT COLUMNS,
but not the aliases INSIDE `l1`. Hop 2's join condition references
`femv1.dest_entity_uuid`, and `femv1` lives inside `l1`, so every such condition
would have to be REWRITTEN to name a projected column instead. That is string
surgery on generated SQL, which is exactly what `reorder_joins` documents as
having cost 8x when its cardinality lookup tried to recover meaning from
constraint text (`issues/061`).

Nesting each hop inside the previous one keeps every enclosing alias in lexical
scope, at any depth, so constraints are emitted VERBATIM and nothing is
rewritten. Only the projection is renamed, and the projection is built here from
`var_slots` rather than parsed out of anything.

WHY THE ROWS ARE THE SAME

Each hop is a `CROSS JOIN LATERAL` over a subquery with no LIMIT and no ORDER
BY, so it drops an outer row exactly when an inner join would and duplicates it
exactly as often. `OFFSET 0` is an optimisation fence and does not change the
multiset. The result is the same bag of rows as the flat join, which is what
lets this be chosen per query with the flat form as fallback.

The fence is not cosmetic: unfenced, PostgreSQL flattens the lateral back into
the join and re-chooses the same bad order (16.1 ms against 0.2 ms at depth 3 in
the plan doc's measurements).

WHAT IT DECLINES

Every check below returns None and leaves the flat path untouched. The failure
mode in this area has always been a pass that quietly declines — correct,
slower, invisible — so each refusal is logged with its reason.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .ir import PlanV2, TableRef
from .traversal_chain import TraversalChain

logger = logging.getLogger(__name__)

# Depth 1 QUALIFIES, matching `traversal_decision.MIN_DEPTH`.
#
# It did not, briefly, and the reason it did not is worth keeping: when a hop
# emitted its link and criteria as one join, a depth-1 chain had no lateral to
# place and would have produced the SAME SQL it was asked to replace. Fencing
# each hop's criteria behind its link — forced by the boolean regression above —
# gave depth 1 a structure of its own, and it is the biggest win measured:
#
#     depth 1, hasActive = true, sparse start   158 ms -> 0.4 ms   417x
#     depth 1, score >= 50,      sparse start    31 ms -> 0.2 ms   153x
#     depth 1, hasActive = true, dense start     72 ms -> 3.0 ms    24x
#
# which is the same mechanism the whole module is for: one hop still has a
# pinned constant that ought to drive, and without the fence it does not.
MIN_EMIT_DEPTH = 1

# `identifier.` — a lexical scan for qualified column references, intersected
# with the aliases we actually emitted. Deliberately not the substring test
# `f"{a}." in sql` used elsewhere: that matches `q1.` inside `xq1.col` and would
# silently assign a constraint to the wrong hop.
_QUALIFIER_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*\.")


@dataclass
class HopGroup:
    """One hop's tables and the constraints that belong to it.

    `tables` is link-first, and the link is emitted ALONE in the hop's FROM with
    every other table of the hop inside a fenced lateral beneath it.

    Listing the link first is not enough, which cost a 55x regression to learn.
    Inside a hop PostgreSQL still reorders freely, and on a boolean criterion it
    did: it drove from `hasActive = true` (13,198 rows) and applied the pinned
    entity as a FILTER on the inner side, 3.4M buffers, the exact pathology this
    module exists to remove. The same query with `score >= 50` happened to pick
    the link — so the flat form was not wrong here, it was LUCKY, and the luck
    ran out on a different criterion.

    A lateral is what makes the dependency one-way. The link is the only table in
    the outer FROM, so nothing can be joined ahead of it.
    """
    index: int
    link_alias: str
    tables: List[TableRef] = field(default_factory=list)
    # alias -> conditions to hang on that table's JOIN ON
    on_map: Dict[str, List[str]] = field(default_factory=dict)
    # conditions belonging to the link itself — this hop's outer WHERE
    where: List[str] = field(default_factory=list)
    # conditions on the FIRST non-link table, which has no JOIN ON to hang on
    crit_where: List[str] = field(default_factory=list)


def _refs(sql: str, known: set) -> set:
    """Aliases this constraint mentions, restricted to ones we emitted."""
    return {m for m in _QUALIFIER_RE.findall(sql or "") if m in known}


def partition_hops(plan: PlanV2, chain: TraversalChain,
                   quad_tables: Sequence[TableRef]) -> Optional[List[HopGroup]]:
    """Split the BGP's tables into one group per hop, or decline.

    A table belongs to a hop when it is that hop's link, or when it reaches
    exactly one link through the constraint graph. `q9` (the score criterion) is
    two constraints away from `femv0` — through `q0`, the frame-type check — so
    reachability is a walk, not adjacency.

    Declines, rather than guessing, when:
      * a table reaches two different hops. It is a cross-hop correlation and
        putting it in either would change which rows survive.
      * a table reaches no hop at all. It is a disconnected island and the flat
        path's cartesian handling is better tested than anything invented here.
      * the plan carries no tagged constraints, so there is no graph to walk.
    """
    tagged = list(plan.tagged_constraints or [])
    if not tagged:
        logger.debug("hop-wise declined: no tagged constraints to partition on")
        return None

    by_alias = {t.alias: t for t in quad_tables}
    known = set(by_alias)

    link_aliases = [l.ref_id for l in chain.links]
    if not all(a in by_alias for a in link_aliases):
        logger.debug("hop-wise declined: chain link(s) %s are not BGP tables",
                     [a for a in link_aliases if a not in by_alias])
        return None
    hop_of = {a: i for i, a in enumerate(link_aliases)}

    # Adjacency between non-link tables, and each table's direct link contacts.
    adj: Dict[str, set] = {a: set() for a in known}
    for _owner, sql in tagged:
        rs = _refs(sql, known)
        for a in rs:
            adj[a] |= (rs - {a})

    # Label every non-link table by the hop it reaches, walking THROUGH other
    # non-link tables but never through a link (a link is where a hop ends).
    for alias in known:
        if alias in hop_of:
            continue
        seen, frontier, reached = {alias}, [alias], set()
        while frontier:
            cur = frontier.pop()
            for nxt in adj[cur]:
                if nxt in hop_of:
                    reached.add(hop_of[nxt])
                    continue
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        if len(reached) != 1:
            logger.debug("hop-wise declined: table %s reaches hops %s, "
                         "expected exactly one", alias, sorted(reached))
            return None
        hop_of[alias] = reached.pop()

    groups = [HopGroup(index=i, link_alias=a, tables=[by_alias[a]])
              for i, a in enumerate(link_aliases)]
    for alias, hop in hop_of.items():
        if alias not in link_aliases:
            groups[hop].tables.append(by_alias[alias])

    if not _place(groups, tagged, known, hop_of):
        return None
    return groups


def _place(groups: List[HopGroup], tagged, known: set,
           hop_of: Dict[str, int]) -> bool:
    """Order each hop's tables and assign every constraint to exactly one place.

    A constraint goes to the HIGHEST hop it mentions, because that is the only
    scope where all of its aliases exist — lower hops enclose it. Within the
    hop it hangs on the last-placed table it mentions, so every reference is
    already in scope, which is the same rule `reorder_joins` uses.

    Returns False if a table cannot be connected to what precedes it. That would
    emit `ON TRUE` — a cartesian product inside a lateral — and the flat path
    handles disconnected islands better than this does.
    """
    parsed = [(sql, _refs(sql, known) | {owner}) for owner, sql in tagged]

    for g in groups:
        mine = {t.alias for t in g.tables}
        # Link first, then repeatedly take a table joined to something already
        # placed. Outer hops are always in scope, so only in-hop refs constrain
        # the order.
        placed = [g.link_alias]
        remaining = [t for t in g.tables if t.alias != g.link_alias]
        while remaining:
            nxt = None
            for t in remaining:
                for sql, rs in parsed:
                    if t.alias not in rs:
                        continue
                    if (rs & mine) - {t.alias} <= set(placed):
                        nxt = t
                        break
                if nxt:
                    break
            if nxt is None:
                logger.debug("hop-wise declined: %s in hop %d joins nothing "
                             "already placed", remaining[0].alias, g.index)
                return False
            placed.append(nxt.alias)
            remaining.remove(nxt)
        order = {a: i for i, a in enumerate(placed)}
        g.tables.sort(key=lambda t: order[t.alias])

    # Every constraint lands exactly once. Losing one silently widens the
    # answer, which is the failure this whole area keeps producing.
    for sql, rs in parsed:
        hop = max(hop_of[a] for a in rs)
        g = groups[hop]
        order = [t.alias for t in g.tables]
        mine = [a for a in rs if hop_of[a] == hop]
        last = max(mine, key=order.index)
        if last == g.link_alias:
            g.where.append(sql)
        elif last == order[1]:
            # The first non-link table opens the criterion lateral's FROM, so it
            # has no JOIN ON to hang on. Its conditions become that lateral's
            # WHERE — including the one tying it back to the link, which is a
            # correlated reference and exactly what makes the lateral lateral.
            g.crit_where.append(sql)
        else:
            g.on_map.setdefault(last, []).append(sql)
    return True


def emit_hop_wise(plan: PlanV2, chain: TraversalChain,
                  quad_tables: Sequence[TableRef],
                  sql_names: Dict[str, str]) -> Optional[str]:
    """The inner BGP query as nested per-hop laterals, or None to decline.

    Replaces only the inner (uuid-level) query of `emit_bgp`. The outer term
    JOINs and companion columns are untouched, so the column contract the rest
    of the pipeline depends on is unchanged.
    """
    if chain is None or chain.depth < MIN_EMIT_DEPTH:
        logger.debug("hop-wise declined: depth %s < %d",
                     getattr(chain, "depth", None), MIN_EMIT_DEPTH)
        return None
    if not chain.pinned_head:
        # A tail pin is as good in principle and needs the chain walked in
        # reverse — a different emission, and one nothing has measured. The
        # decision reports tail pins as eligible; this declines them for now
        # rather than emitting a forward walk that drives from the wrong end.
        logger.debug("hop-wise declined: head is not pinned "
                     "(tail-pinned reverse walk is not implemented)")
        return None

    groups = partition_hops(plan, chain, quad_tables)
    if not groups:
        return None

    # Nothing to fence and nothing to sequence. A single hop carrying only its
    # link emits exactly the SQL it was asked to replace, so returning it would
    # cost a wasted rewrite and, worse, log "hop-wise" for a plan that is not.
    if len(groups) == 1 and len(groups[0].tables) == 1:
        logger.debug("hop-wise declined: one hop with no criterion tables, "
                     "the emitted SQL would be identical")
        return None

    hop_of = {t.alias: g.index for g in groups for t in g.tables}

    # Variables split by where they bind: on the hop's LINK, or on one of its
    # criterion tables. The two sit in different scopes once the criteria are
    # fenced, so the projection has to know which.
    link_binds: Dict[int, List[Tuple[str, str]]] = {g.index: [] for g in groups}
    crit_binds: Dict[int, List[Tuple[str, str]]] = {g.index: [] for g in groups}
    for var, slot in (plan.var_slots or {}).items():
        if not slot.positions:
            continue
        alias, col = slot.positions[0]
        hop = hop_of.get(alias)
        if hop is None:
            logger.debug("hop-wise declined: variable %s binds on %s, which is "
                         "in no hop", var, alias)
            return None
        target = link_binds if alias == groups[hop].link_alias else crit_binds
        target[hop].append((f"{sql_names[var]}__uuid", f"{alias}.{col}"))

    def _deeper(i: int) -> List[Tuple[str, str]]:
        """Everything bound at hop i's criteria or below — re-projected by name."""
        out = list(crit_binds[i])
        for j in range(i + 1, len(groups)):
            out += link_binds[j] + crit_binds[j]
        return out

    def _criteria(i: int) -> str:
        """Hop i's non-link tables, with hop i+1 nested inside them.

        Deeper hops nest HERE rather than beside the criteria so that a
        constraint belonging to a later hop can still reference hop i's
        criterion aliases — they stay in lexical scope all the way down.
        """
        g = groups[i]
        cols = [f"{expr} AS {name}" for name, expr in crit_binds[i]]
        for j in range(i + 1, len(groups)):
            cols += [f"hop{i + 1}.{n}" for n, _ in link_binds[j] + crit_binds[j]]
        parts = [f"SELECT {', '.join(cols) if cols else '1 AS _dummy'}",
                 f"FROM {g.tables[1].table_name} AS {g.tables[1].alias}"]
        for t in g.tables[2:]:
            conds = g.on_map.get(t.alias)
            parts.append(f"JOIN {t.table_name} AS {t.alias} ON "
                         + (" AND ".join(conds) if conds else "TRUE"))
        if i + 1 < len(groups):
            parts.append(f"CROSS JOIN LATERAL (\n{_body(i + 1)}\n) AS hop{i + 1}")
        if g.crit_where:
            parts.append("WHERE " + " AND ".join(g.crit_where))
        parts.append("OFFSET 0")
        return "\n".join(parts)

    def _body(i: int) -> str:
        """Hop `i`: the link alone, everything else fenced beneath it."""
        g = groups[i]
        cols = [f"{expr} AS {name}" for name, expr in link_binds[i]]
        has_crit = len(g.tables) > 1
        if has_crit:
            cols += [f"crit{i}.{n}" for n, _ in _deeper(i)]
        else:
            for j in range(i + 1, len(groups)):
                cols += [f"hop{i + 1}.{n}"
                         for n, _ in link_binds[j] + crit_binds[j]]

        parts = [f"SELECT {', '.join(cols) if cols else '1 AS _dummy'}",
                 f"FROM {g.tables[0].table_name} AS {g.tables[0].alias}"]
        if has_crit:
            parts.append(f"CROSS JOIN LATERAL (\n{_criteria(i)}\n) AS crit{i}")
        elif i + 1 < len(groups):
            parts.append(f"CROSS JOIN LATERAL (\n{_body(i + 1)}\n) AS hop{i + 1}")
        if g.where:
            parts.append("WHERE " + " AND ".join(g.where))
        if i > 0:
            # The fence. Without it PostgreSQL pulls the lateral back into the
            # surrounding join and re-picks the order this exists to override.
            parts.append("OFFSET 0")
        return "\n".join(parts)

    sql = _body(0)
    logger.info("traversal: emitting %d hops hop-wise (%s), tables per hop %s",
                len(groups), chain.kind, [len(g.tables) for g in groups])
    return sql
