"""Intersect independent criteria on the projected variable instead of nesting.

`issues/161`. A KGQuery with several frame criteria produces a BGP whose only
shared variable is the projected one. Removing `?entity` from the production
Nurture shape splits it into exactly two connected components with nothing in
common:

    component 0:  frame_0, frame_edge_0, slot_0_0, slot_edge_0_0    campaign
    component 1:  frame_1, frame_edge_1, slot_1_0, slot_edge_1_0    SFLeadId

The planner correlates them anyway — it re-runs the second chain once per
candidate of the first:

    Nested Loop  (cost ... 957,186,606, rows=46,079)
      ->  Hash Join   (rows=46,079)                    the campaign chain
      ->  Nested Loop (cost=1015.83..20,769.37)        the ABSENT chain, PER ROW

46,079 x 20,769 ~= 957,000,000, and the query times out returning 0 rows.

TWO DIFFERENT "NESTINGS", and only one is inherent. `frame -> frame -> slot`
inside a criterion is a containment path along shared variables and must be
walked. Correlating two INDEPENDENT criteria is a choice. Conflating them is why
direction, anchor size, statistics and the empty-constant sentinel all failed on
this shape: every one of those optimises WITHIN a component.

WHAT THIS ADDS. For each component that is a collapsible entity->frame->slot
walk, one UNCORRELATED constraint on the entity:

    <entity>.<col> IN (SELECT entity_uuid FROM {space}_entity_slot_sort
                       WHERE context_uuid = <ctx> AND entity_type_uuid = <E>
                         AND frame_type_path = ARRAY[...]::uuid[]
                         AND slot_type_uuid = <T> AND value_text = '<V>')

Uncorrelated is the whole point: PostgreSQL evaluates each subquery ONCE and
hash-semi-joins, so N criteria cost N lookups rather than multiplying. That is
what `fast_slot_filter` does with INTERSECT to answer the same query in 96 ms.

WHY IT IS SOUND. Each constraint restricts `?entity` to entities the surrounding
chain ALREADY requires: the component says "this entity has a frame of this type
carrying a slot of this type with this value", and that is exactly one
`entity_slot_sort` row. Nothing is removed and no variable is re-homed, so it
cannot change an answer — only the set PostgreSQL drives from.

The full index prefix is emitted deliberately. Probing `slot_type_uuid` +
`value_text` alone measured 5.36 s against 271 ms with `context_uuid`,
`entity_type_uuid` and `frame_type_path` supplied (`issues/161`).

COVERAGE GATES IT. `entity_slot_sort` is derived, and a short table would make
these constraints REMOVE rows — a confident subset with no error. Production
measured 1.05% for one entity type while its own drift probe reported converged
(`issues/149`). The caller must establish completeness; this module only builds
the constraint.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Default OFF. This changes plan shape on every multi-criterion entity query,
# and the two previous attempts in this area shipped as dead code and as a
# wrong-answer bug respectively. It earns the default by measurement.
ENABLED = os.getenv("VG_COMPONENT_INTERSECT", "0") == "1"

_PRED_RE = re.compile(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(c_\d+)__")
_OBJ_RE = re.compile(r"(\w+)\.object_uuid\s*=\s*__CONST_(c_\d+)__")


def _components(bgp, projected: str) -> List[Set[str]]:
    """Connected components of the BGP's variables once `projected` is removed.

    Union-find over each table's variables. Two variables are connected when
    some table binds both; dropping the projected variable is what separates
    criteria that meet only at the entity.
    """
    parent: Dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_alias: Dict[str, List[str]] = {}
    for var, vslot in (bgp.var_slots or {}).items():
        if var == projected:
            continue
        find(var)
        for alias, _col in (vslot.positions or []):
            by_alias.setdefault(alias, []).append(var)
    for vs in by_alias.values():
        for a, b in zip(vs, vs[1:]):
            union(a, b)

    comps: Dict[str, Set[str]] = {}
    for v in list(parent):
        comps.setdefault(find(v), set()).add(v)
    return list(comps.values())


def component_intersect_constraints(bgp, aliases, space_id: str,
                                    projected: str) -> list:
    """`[(alias, sql)]`, one uncorrelated entity constraint per collapsible
    component. Empty when the shape is anything else — declining costs speed,
    never an answer."""
    if not ENABLED:
        return []
    comps = _components(bgp, projected)
    if len(comps) < 2:
        # One component is an ordinary single-criterion query; there is nothing
        # to stop multiplying, and the existing paths handle it.
        return []
    from .slot_sort_range import EQUALITY_LANE, _const_uris, _const_terms

    HALEY = "http://vital.ai/ontology/haley-ai-kg#"
    SLOT_TYPE = f"{HALEY}hasKGSlotType"
    FRAME_TYPE = f"{HALEY}hasKGFrameType"
    ENTITY_TYPE = f"{HALEY}hasKGEntityType"

    const = _const_uris(aliases)     # predicates are URIs
    terms = _const_terms(aliases)    # values may be literals — see issues/162
    if not const:
        return []

    pred_of, obj_uri, obj_text, obj_token = {}, {}, {}, {}
    for _owner, sql in (bgp.tagged_constraints or []):
        m = _PRED_RE.search(sql)
        if m and const.get(m.group(2)):
            pred_of[m.group(1)] = const[m.group(2)]
        m = _OBJ_RE.search(sql)
        if m:
            obj_uri[m.group(1)] = const.get(m.group(2), "")
            if m.group(2) in terms:
                obj_text[m.group(1)] = terms[m.group(2)]
            obj_token[m.group(1)] = f"__CONST_{m.group(2)}__"

    # variable -> the aliases it binds as SUBJECT
    subj_aliases: Dict[str, List[str]] = {}
    for var, vslot in (bgp.var_slots or {}).items():
        for alias, col in (vslot.positions or []):
            if col == "subject_uuid":
                subj_aliases.setdefault(var, []).append(alias)

    # The entity type quad hangs off the PROJECTED variable, so it is outside
    # every component and shared by all of them.
    entity_type_token = None
    for a in subj_aliases.get(projected, []):
        if pred_of.get(a) == ENTITY_TYPE:
            entity_type_token = obj_token.get(a)
            break
    pslot = (bgp.var_slots or {}).get(projected)
    anchor = next(((a, c) for a, c in (pslot.positions if pslot else [])
                   if c == "subject_uuid"), None)
    if anchor is None or entity_type_token is None:
        return []

    ess = f"{space_id}_entity_slot_sort"
    out = []
    for comp in comps:
        value_alias = slot_var = None
        for var in comp:
            for a in subj_aliases.get(var, []):
                if EQUALITY_LANE.get(pred_of.get(a, "")) == "value_text" \
                        and a in obj_text:
                    value_alias, slot_var = a, var
                    break
            if value_alias:
                break
        if not value_alias:
            continue

        type_token = None
        for a in subj_aliases.get(slot_var, []):
            if pred_of.get(a) == SLOT_TYPE:
                type_token = obj_token.get(a)
                break
        if not type_token:
            continue

        # Frame types belonging to THIS component only — that is what keeps two
        # criteria from borrowing each other's path.
        frame_tokens = [obj_token[a]
                        for var in comp
                        for a in subj_aliases.get(var, [])
                        if pred_of.get(a) == FRAME_TYPE and a in obj_token]
        if not frame_tokens:
            continue

        value = str(obj_text[value_alias])
        if not value:
            continue   # an unresolved constant would match nothing — issues/162
        path = ", ".join(f"{t}::uuid" for t in dict.fromkeys(frame_tokens))
        sql = (f"{anchor[0]}.{anchor[1]} IN (SELECT entity_uuid FROM {ess} "
               f"WHERE entity_type_uuid = {entity_type_token} "
               f"AND frame_type_path = ARRAY[{path}] "
               f"AND slot_type_uuid = {type_token} "
               f"AND value_text = \'{value.replace(chr(39), chr(39) * 2)}\')")
        entry = (anchor[0], sql)
        if entry not in out:
            out.append(entry)

    if out:
        logger.info("component-intersect: %d component(s) narrowed to an "
                    "uncorrelated entity lookup", len(out))
    return out
