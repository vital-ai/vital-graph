"""Emit "slot S of graph ?d" as one MATERIALIZED CTE driven from the slot type.

`issues/293`. In a flat BGP

    ?d hasKGEntityType <T> .
    ?s hasKGGraphURI ?d ; hasKGSlotType <S> ; hasTextSlotValue ?v .

PostgreSQL drives from ?d and probes `(context, hasKGGraphURI, object = ?d)` per
entity, which returns its whole graph (~1,000 members on production UW
decisions) estimated at ~10 rows. Measured: 1,159 decisions became 1,261,467
rows before the slot type kept 9,318.

Restricting that leaf alone was tried three ways and reverted (see the issue):
each fixed one query and broke others, because PostgreSQL ALSO underestimates
a mid-frequency `(predicate, object)` pair (3 rows for 1,159 slots, with the
`quad_po` statistics at target 1000), and put whatever was restricted inside a
nested loop that re-ran its index lookups once per outer row.

This takes the order out of the planner's hands for the part it gets wrong.
The SLOT GROUP, meaning every leaf whose subject is the slot variable with a
constant predicate (the graph link, the pin, the value), is emitted as one CTE:

    WITH sg_q1_cte AS MATERIALIZED (
        SELECT q2.subject_uuid AS q2__subject_uuid, ..., q1.object_uuid AS q1__object_uuid, ...
        FROM quad q2                                   -- the pin: slot type S
        JOIN quad q1 ON q1.subject_uuid = q2.subject_uuid AND q1.predicate = hasKGGraphURI
        JOIN quad q4 ON q4.subject_uuid = q2.subject_uuid AND q4.predicate = <value>
        WHERE q2.predicate = hasKGSlotType AND q2.object = <S>)
    SELECT ... FROM quad q0 JOIN sg_q1_cte ON sg_q1_cte.q1__object_uuid = q0.subject_uuid ...

Inside, the plan is the pin plus primary-key lookups by subject: the cost is
the pin's size, whatever the estimates. Outside, the group is a set computed
ONCE. If PostgreSQL still nests it inside a loop, a re-run is a scan of a
materialised set, not a repeat of the lookups that made the fence slow. It
only underestimates SMALL pairs, and a small set is cheap to rescan. A large
pair is in the MCV list and is estimated well enough to be hashed.

WHEN IT FIRES. Only when the pinned set is clearly smaller than the expansion
it replaces, from statistics already loaded:

    pinned     = rows of the (predicate, object) pair pinning the slot subject
    expansion  = min(anchor rows x mean graph size, all hasKGGraphURI rows)

`anchor` is the cheapest constant leaf binding ?d in this BGP; with none (an
OPTIONAL group whose ?d comes from outside) the bound is the whole predicate.
Mean graph size is the mean `row_count` of the predicate's pairs in `rdf_stats`,
biased high if the table is truncated, which errs towards the CTE. The CTE
holds at most `pinned` rows per group.

Rows are unchanged: the CTE is a sub-join of the same leaves and constraints,
and every constraint linking the group to the rest of the BGP is applied
outside it, on the CTE's columns.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

#: Predicates whose object is a GROUPING URI: one object, many subjects.
GRAPH_FANOUT_PREDICATES = frozenset({
    "http://vital.ai/ontology/haley-ai-kg#hasKGGraphURI",
})

#: The pinned set must be this many times smaller than the expansion.
MARGIN = 2.0

NAME = "slot_group_cte"
_COLS = ("subject_uuid", "predicate_uuid", "object_uuid", "context_uuid")

_fanout_cache: Dict[Tuple[int, str], Optional[float]] = {}


def mean_fanout(quad_stats: dict, pred_uuid: str) -> Optional[float]:
    """Mean subjects per object of `pred_uuid`, from its `rdf_stats` pairs."""
    key = (id(quad_stats), pred_uuid)
    if key in _fanout_cache:
        return _fanout_cache[key]
    n = total = 0
    for (p, _o), rows in quad_stats.items():
        if p == pred_uuid:
            n += 1
            total += rows
    out = (total / n) if n else None
    if len(_fanout_cache) > 256:
        _fanout_cache.clear()
    _fanout_cache[key] = out
    return out


def values_bound_vars(plan) -> Dict[str, int]:
    """var -> fewest rows of any VALUES table that binds it, anywhere in the plan.

    A VALUES is a join node ABOVE the BGP, so the BGP's own leaves do not show
    the restriction; PostgreSQL still pushes it into the leaf's lookup.
    """
    out: Dict[str, int] = {}

    def walk(node):
        if node is None:
            return
        if node.kind == "table" and node.values_vars:
            rows = node.values_rows or []
            for v in node.values_vars:
                n = sum(1 for r in rows if r.get(v) is not None)
                if n:
                    out[v] = min(out.get(v, n), n)
        for c in node.children or []:
            walk(c)

    walk(plan)
    return out


def _reaches_without(start: Set[str], targets: Set[str], var_aliases: Dict[str, Set[str]],
                     alias_vars: Dict[str, Set[str]], avoid_var: str) -> bool:
    """Whether any `start` alias reaches a `targets` alias through shared
    variables, never crossing `avoid_var`."""
    seen, frontier = set(start), list(start)
    while frontier:
        a = frontier.pop()
        if a in targets:
            return True
        for v in alias_vars.get(a, ()):
            if v == avoid_var:
                continue
            for b in var_aliases.get(v, ()):
                if b not in seen:
                    seen.add(b)
                    frontier.append(b)
    return False


@dataclass
class SlotGroup:
    name: str
    aliases: Set[str]
    pin: str
    pinned: float
    detail: dict = field(default_factory=dict)


def _refs(sql: str, aliases) -> Set[str]:
    return {a for a in aliases if re.search(rf"\b{re.escape(a)}\.", sql)}


def find_groups(plan, ctx, quad_tables, leaf_card: Dict[str, float],
                uuid_of) -> List[SlotGroup]:
    """The slot groups worth emitting as CTEs, gated on the statistics."""
    leaf_terms = getattr(plan, "leaf_terms", None) or {}
    tagged = getattr(plan, "tagged_constraints", None) or []
    by_alias = {t.alias: t for t in quad_tables}
    if not leaf_terms or not tagged or any(t.kind != "quad" for t in quad_tables):
        return []

    var_at: Dict[Tuple[str, str], str] = {}
    positions: Dict[str, List[Tuple[str, str]]] = {}
    var_aliases: Dict[str, Set[str]] = {}
    alias_vars: Dict[str, Set[str]] = {}
    for var, slot in plan.var_slots.items():
        positions[var] = list(slot.positions)
        for pos in slot.positions:
            var_at[pos] = var
            var_aliases.setdefault(var, set()).add(pos[0])
            alias_vars.setdefault(pos[0], set()).add(var)

    aliases_obj = ctx.aliases
    values_rows = getattr(aliases_obj, "values_bound_vars", None) or {}
    quad_stats = getattr(aliases_obj, "quad_stats", None) or {}
    pred_stats = getattr(aliases_obj, "pred_stats", None) or {}
    from .plan_decisions import recorder_for
    rec = recorder_for(aliases_obj)

    groups: List[SlotGroup] = []
    taken: Set[str] = set()
    for a in sorted(by_alias):
        p_term = leaf_terms.get((a, "predicate_uuid"))
        if not p_term or p_term[0] not in GRAPH_FANOUT_PREDICATES or a in taken:
            continue
        if (a, "object_uuid") in leaf_terms or (a, "subject_uuid") in leaf_terms:
            continue                       # a constant end: already selective
        s_var = var_at.get((a, "subject_uuid"))
        d_var = var_at.get((a, "object_uuid"))
        if not s_var or not d_var:
            continue

        # Members: every leaf on the slot subject with a constant predicate and
        # a constant context (no GRAPH ?g, whose binding would cross the CTE).
        members = {b for (b, col) in positions.get(s_var, [])
                   if col == "subject_uuid" and b in by_alias and b not in taken
                   and (b, "predicate_uuid") in leaf_terms
                   and (b, "context_uuid") not in var_at}
        if a not in members:
            continue
        # The pin is the member with the fewest rows by ANY count the IR
        # carries: a constant (predicate, object) pair, an FTS match count, a
        # measured range. KGQuery's text search pins the slot by FTS; sizing
        # the group by every slot of that TYPE would misjudge the gate.
        pins = [(leaf_card[b], b) for b in members if b != a and b in leaf_card]
        if not pins:
            rec.declined(NAME, "no counted leaf on the slot subject to drive from",
                         alias=a)
            continue
        pinned, pin = min(pins)

        p_uuid = uuid_of(p_term)
        whole = pred_stats.get(p_uuid) if p_uuid else None
        fanout = mean_fanout(quad_stats, p_uuid) if p_uuid else None
        # An anchor is a leaf with a CONSTANT object binding ?d (the entity
        # type). Another group's graph link also binds ?d, but is priced at its
        # whole predicate and anchors nothing.
        anchors = [leaf_card[c] for (c, _col) in positions.get(d_var, [])
                   if c not in members and c in leaf_card
                   and (c, "object_uuid") in leaf_terms]
        anchor = min(anchors) if anchors else None
        if anchor is not None and fanout is not None:
            expansion = anchor * fanout
            if whole is not None:
                expansion = min(expansion, whole)
        elif whole is not None:
            expansion = whole
        else:
            rec.declined(NAME, "no statistics for the grouping predicate", alias=a)
            continue
        detail = dict(alias=a, pin=pin, members=sorted(members), pinned=pinned,
                      expansion=round(expansion), anchor=anchor,
                      fanout=fanout and round(fanout, 1))
        if pinned * MARGIN >= expansion:
            rec.declined(NAME, "the pinned set is not clearly smaller than the expansion",
                         **detail)
            continue

        # A SMALLER DRIVER THAT NEVER CROSSES ?d. If something more selective
        # than the pin reaches the slot through other variables (a reason
        # code restricted by VALUES, through the reason frame to the kind
        # slot), PostgreSQL drives from it with primary-key lookups and never
        # expands a graph, so there is nothing for the CTE to fix and
        # materialising the pin's whole set is pure cost. Measured: all_of,
        # 380 ms -> 1,220 ms before this rule. The VALUES restriction is a join
        # node above the BGP, so its rows come from `values_bound_vars`.
        drivers = {c for v, n in values_rows.items() if n * MARGIN < pinned
                   for c in var_aliases.get(v, ())}
        drivers |= {c for c in by_alias
                    if c not in members and c in leaf_card
                    and leaf_card[c] * MARGIN < pinned
                    and (c, "object_uuid") in leaf_terms
                    and d_var not in alias_vars.get(c, ())}
        # A driver that IS a member (VALUES on the slot's own value) reaches
        # it trivially: PostgreSQL looks the value up and walks to the slot.
        if drivers and _reaches_without(drivers, members, var_aliases,
                                        alias_vars, d_var):
            rec.declined(NAME, "a smaller driver reaches the slot without the graph link",
                         **detail)
            continue
        # Ends in `_cte`, never in an alias: `reorder_joins` finds references
        # by substring (`"q1." in sql`), so `sg_q1.` would read as one to `q1`.
        name = f"sg_{a}_cte"
        groups.append(SlotGroup(name, members, pin, pinned, detail))
        taken |= members
        rec.fired(NAME, "", **detail)
    return groups


def apply_groups(groups: List[SlotGroup], quad_tables, tagged, inner_cols: List[str],
                 leaf_card: Dict[str, float], reorder):
    """Replace each group's aliases with its CTE.

    Returns (tables, tagged, inner_cols, leaf_card, cte_sql). `reorder` is
    `reorder_joins`, used to order the leaves INSIDE each CTE from its pin.
    """
    from .ir import TableRef

    all_aliases = {t.alias for t in quad_tables}
    owner_group = {a: g for g in groups for a in g.aliases}

    def rename(sql: str) -> str:
        for a, g in owner_group.items():
            sql = re.sub(rf"\b{re.escape(a)}\.(\w+)", rf"{g.name}.{a}__\1", sql)
        return sql

    ctes = []
    for g in groups:
        tables = [t for t in quad_tables if t.alias in g.aliases]
        internal = [(o, s) for o, s in tagged
                    if o in g.aliases and _refs(s, all_aliases) <= g.aliases]
        card = {a: (0 if a == g.pin else leaf_card.get(a, float("inf"))) for a in g.aliases}
        ordered, on_map, first_conds = reorder(tables, internal, leaf_cardinality=card)
        cols = ", ".join(f"{a}.{c} AS {a}__{c}" for a in sorted(g.aliases) for c in _COLS)
        body = [f"SELECT {cols}", f"FROM {ordered[0].table_name} AS {ordered[0].alias}"]
        for t in ordered[1:]:
            conds = on_map.get(t.alias)
            body.append(f"JOIN {t.table_name} AS {t.alias} ON "
                        + (" AND ".join(conds) if conds else "TRUE"))
        if first_conds:
            body.append("WHERE " + " AND ".join(first_conds))
        ctes.append(f"{g.name} AS MATERIALIZED (\n" + "\n".join(body) + "\n)")

    new_tables = [t for t in quad_tables if t.alias not in owner_group]
    new_tables += [TableRef(ref_id=g.name, kind="quad", table_name=g.name, alias=g.name)
                   for g in groups]
    new_tagged = []
    for o, s in tagged:
        g = owner_group.get(o)
        if g is not None and _refs(s, all_aliases) <= g.aliases:
            continue                                 # inside the CTE
        new_tagged.append((g.name if g is not None else o, rename(s)))
    new_card = {a: n for a, n in leaf_card.items() if a not in owner_group}
    for g in groups:
        new_card[g.name] = g.pinned
    return (new_tables, new_tagged, [rename(c) for c in inner_cols], new_card,
            "WITH " + ",\n".join(ctes) + "\n")
