"""Frame-Entity table rewrite for v2 IR — replaces slot+edge patterns with a
pre-computed table mapping frames to source/destination entities.

The pattern detected (post edge table rewrite):

    edge:        frame → slot  (source_node_uuid, dest_node_uuid)
    slot_type:   slot hasSlotType <hasSourceEntity|hasDestEntity>
    slot_value:  slot hasSlotValue ?entity

When a source group and dest group share the same frame variable, all 6
tables (2 edge + 2 slot_type + 2 slot_value) are replaced by one
frame_entity table:

    {space}_frame_entity(frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid)

This eliminates 5 JOINs per hop.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from .declines import Rule
from .ir import PlanV2, TableRef, AliasGenerator, KIND_BGP, KIND_PROJECT

logger = logging.getLogger(__name__)

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
SLOT_VALUE_URI = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
# NOTE: the slot ROLE values (`urn:hasSourceEntity` and friends) are
# deliberately NOT named in this module. They are `hasKGSlotType` OBJECT
# values — data, supplied by the query — and compiling two of them in is
# what `issues/183` records. `slot_role_constants` reads them from the plan.
# The frame's own type. `frame_entity.frame_type_uuid` carries it, so a hop
# constrained by it needs no join back to rdf_quad — the trade `edge_type_uuid`
# makes (issues/060). VITALTYPE rather than rdf:type: single-valued by design so
# the column is well-defined, matches the edge column, and is what the product
# queries with (`kgframes_endpoint` emits vital-core:vitaltype).
VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"

_PRED_RE = re.compile(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(c_\d+)__")
_OBJ_RE = re.compile(r"(\w+)\.object_uuid\s*=\s*__CONST_(c_\d+)__")
_COREF_RE = re.compile(r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)")

# Reads the EDGE rewrite's output, not just the collected plan: this pass
# matches on `kind == "edge"` tables, so without stage 2a.1 having run there is
# nothing here to collapse. Declaring the dependency is how "no edge table
# bindings" stops being a message someone has to interpret.
FE = Rule("frame_entity_rewrite", stage="frame_entity_rewrite",
          reads=("collect", "materialize_constants", "edge_rewrite"))


class _SlotGroup(NamedTuple):
    """A matched slot group: edge table + slot_type quad + slot_value quad."""
    edge_alias: str
    type_quad: str
    value_quad: str
    role: str           # "source" or "dest"
    slot_var: str       # SPARQL variable for the slot node
    entity_var: str     # SPARQL variable for the entity
    frame_var: str      # SPARQL variable for the frame


def _type_quads_for(plan, frame_var, quad_predicate, quad_obj_const,
                    table_by_alias, aliases=None):
    """Quad tables holding `<frame_var> vitaltype <constant>`.

    A VARIABLE object is skipped rather than absorbed. `?f vitaltype ?t` binds
    the type to something the query may read elsewhere, and the column could
    supply it — but whether that survives is decided by the position rewrite
    below, and requiring a constant keeps this to the case with no such
    question.
    """
    slot = (plan.var_slots or {}).get(frame_var)
    if not slot:
        return []
    out = []
    for ref_id, col in (slot.positions or []):
        if col != "subject_uuid":
            continue
        tbl = table_by_alias.get(ref_id)
        if not tbl or tbl.kind != "quad":
            continue
        # VITALTYPE is what `frame_type_uuid` holds, so it is always
        # equivalent. `rdf:type` is equivalent only where the two agree in this
        # space, which `frame_type_absorbable` answers against the data and
        # `generator` prefetches onto `aliases`. Absent or None keeps the join.
        #
        # This gate used to accept VITALTYPE only, and `issues/183` measured the
        # cost on a query that writes `?frame a KGFrame`: 5,120,000 of the
        # 6,032,427 buffers, the entire remaining gap against the table this
        # collapse replaced.
        _pred = quad_predicate.get(ref_id)
        if _pred != VITALTYPE_URI:
            if not (getattr(aliases, "frame_type_absorbable", None) or {}).get(_pred):
                continue
        if not quad_obj_const.get(ref_id):
            continue
        out.append(ref_id)
    return out


SLOT_TYPE_PREDICATES = (VITALTYPE_URI,
                        "http://www.w3.org/1999/02/22-rdf-syntax-ns#type")


def _slot_type_quads_for(plan, slot_var, quad_predicate, quad_obj_const,
                         table_by_alias):
    """Quad tables holding `<slot_var> a|vitaltype <constant>`.

    BOTH spellings, unlike `_type_quads_for`, which matches vitaltype only.
    Measured on `sp_graph_skew_2k`: `a KGEntitySlot` and `vitaltype KGEntitySlot`
    reach the identical decline at 542,012 buffers, so absorbing one and not the
    other would fix half the cases and leave the other half looking unfixed for
    no visible reason.

    A VARIABLE object is skipped for the same reason it is on frames: it binds
    something the query may read, and nothing here can supply it.
    """
    slot = (plan.var_slots or {}).get(slot_var)
    if not slot:
        return []
    out = []
    for ref_id, col in (slot.positions or []):
        if col != "subject_uuid":
            continue
        tbl = table_by_alias.get(ref_id)
        if not tbl or tbl.kind != "quad":
            continue
        if quad_predicate.get(ref_id) not in SLOT_TYPE_PREDICATES:
            continue
        if not quad_obj_const.get(ref_id):
            continue
        out.append(ref_id)
    return out


def slot_role_constants(plan: PlanV2, aliases: AliasGenerator) -> tuple:
    """Every `hasKGSlotType` OBJECT constant this plan names, as a tuple.

    The roles are whatever the QUERY says they are. Reading them from the plan
    is what lets the slot-type tautology be asked about the roles actually in
    play instead of two names compiled into the source (`issues/183`).
    """
    const_to_uri = {c: text for (text, ttype, _lg, _dt), c in aliases.constants.items()
                    if ttype == "U"}
    pred_of, obj_of = {}, {}
    for _owner, sql in (plan.tagged_constraints or []):
        m = _PRED_RE.search(sql)
        if m:
            pred_of[m.group(1)] = const_to_uri.get(m.group(2), "")
        m = _OBJ_RE.search(sql)
        if m:
            obj_of[m.group(1)] = const_to_uri.get(m.group(2), "")
    out = {obj_of[a] for a in pred_of
           if pred_of[a] == SLOT_TYPE_URI and obj_of.get(a)}
    for child in (plan.children or []):
        out.update(slot_role_constants(child, aliases))
    return tuple(sorted(out))


def slot_type_constants(plan: PlanV2, aliases: AliasGenerator):
    """(type_predicate_uri, type_object_uri) for every slot type constraint here.

    The generator needs these BEFORE the rewrite runs, to price each one against
    the data while it still has a connection. Duplicating the scan is deliberate:
    the alternative is making the rewrite async, and it is called from three
    places that are not.
    """
    const_to_uri = {c: text for (text, ttype, _lg, _dt), c in aliases.constants.items()
                    if ttype == "U"}
    pred_of, obj_of = {}, {}
    for _owner, sql in (plan.tagged_constraints or []):
        m = _PRED_RE.search(sql)
        if m:
            pred_of[m.group(1)] = const_to_uri.get(m.group(2), "")
        m = _OBJ_RE.search(sql)
        if m:
            obj_of[m.group(1)] = const_to_uri.get(m.group(2), "")
    out = {(pred_of[a], obj_of[a]) for a in pred_of
           if pred_of[a] in SLOT_TYPE_PREDICATES and obj_of.get(a)}
    for child in (plan.children or []):
        out.update(slot_type_constants(child, aliases))
    return sorted(out)


_NEEDED_UNSET = object()


def _needed_vars(root: PlanV2) -> Optional[Set[str]]:
    """Variables the query still reads after this BGP — or None for "all".

    `frame_entity` has no slot column, so collapsing a group DISCARDS the slot
    variables (issues/178). That is free when nothing reads them and silently
    wrong when something does: the CONSTRUCT template in
    `sql_reference/happy_frame_query.sparql` projected `?sourceSlot` and
    `?destinationSlot`, got a literal NULL for each, and emitted 30 of its 60
    triples with HTTP 200.

    None means "could not enumerate, assume everything is read", which makes the
    caller decline. That is the safe direction and it costs nothing that was
    working: a query this declines on is one whose slot variables the rewrite
    would have emptied, i.e. one that is returning wrong output today.
    """
    needed: Set[str] = set()

    def walk(p: PlanV2) -> bool:
        ok = True
        if p.kind == KIND_PROJECT:
            if p.project_vars is None:
                return False          # SELECT * — every variable is read
            needed.update(p.project_vars)
        # Any variable named in an expression is read too, wherever it sits.
        for attr in ("filter_expr", "extend_expr", "order_by", "group_vars",
                     "aggregates", "having"):
            # `getattr(p, "child")` is NOT safe here: `child` is a property that
            # asserts a single child and raises on a BGP, and a default does not
            # suppress an exception raised inside a property. Only plain fields
            # are read, and the walk below uses `children` directly — which is
            # what `child` returns anyway.
            val = getattr(p, attr, None)
            if val is not None:
                needed.update(_expr_vars(val))
        ev = getattr(p, "extend_var", None)
        if isinstance(ev, str):
            needed.add(ev)
        for child in (p.children or []):
            if child is not None and not walk(child):
                ok = False
        return ok

    return needed if walk(root) else None


def _expr_vars(val) -> Set[str]:
    """Every variable named anywhere inside an expression-ish value.

    Deliberately structure-agnostic — it walks dataclasses, lists and dicts
    generically rather than switching on node type, so a node kind this file
    does not know about cannot silently hide a variable reference.
    """
    from ..jena_sparql.jena_types import ExprVar, VarNode
    out: Set[str] = set()
    seen: Set[int] = set()

    def rec(v):
        if v is None or id(v) in seen:
            return
        seen.add(id(v))
        if isinstance(v, (ExprVar, VarNode)):
            name = getattr(v, "var", None) or getattr(v, "name", None)
            if isinstance(name, str):
                out.add(name)
            return
        if isinstance(v, str):
            return
        if isinstance(v, dict):
            for k, x in v.items():
                if isinstance(k, str):
                    out.add(k)
                rec(x)
            return
        if isinstance(v, (list, tuple, set, frozenset)):
            for x in v:
                rec(x)
            return
        for f in getattr(v, "__dataclass_fields__", {}):
            rec(getattr(v, f, None))

    rec(val)
    return out


def rewrite_frame_entity_table(plan: PlanV2, aliases: AliasGenerator,
                                space_id: str, needed_vars=_NEEDED_UNSET) -> PlanV2:
    """Rewrite a v2 plan to use the frame_entity table where possible.

    Detects groups of 6 tables (2 edge + 2 slot_type + 2 slot_value)
    that form a frame traversal pattern and replaces each group with a
    single frame_entity table lookup.

    `needed_vars` is computed once from the root and threaded down; callers do
    not pass it. See `_needed_vars` for why the collapse must consult it.
    """
    if needed_vars is _NEEDED_UNSET:
        needed_vars = _needed_vars(plan)

    # Kept so a decline can return the plan untouched rather than a
    # half-rewritten one.
    original_plan = copy.deepcopy(plan)

    if plan.kind != KIND_BGP or not plan.tables:
        for i, child in enumerate(plan.children):
            plan.children[i] = rewrite_frame_entity_table(child, aliases, space_id,
                                                          needed_vars)
        return plan

    fe_table_name = f"{space_id}_frame_entity"
    fs_table_name = f"{space_id}_frame_slot"
    edge_table_name = f"{space_id}_edge"
    quad_table_name = f"{space_id}_rdf_quad"

    # --- Step 1: Build constant reverse map ---
    const_to_uri: Dict[str, str] = {}
    for (text, ttype, _lg, _dt), col_alias in aliases.constants.items():
        if ttype == "U":
            const_to_uri[col_alias] = text

    # --- Step 2: Classify quad tables by predicate and object URIs ---
    quad_predicate: Dict[str, str] = {}
    quad_obj_const: Dict[str, str] = {}
    quad_obj_token: Dict[str, str] = {}
    quad_pred_token: Dict[str, str] = {}

    for _owner, sql in plan.tagged_constraints:
        m = _PRED_RE.search(sql)
        if m:
            quad_predicate[m.group(1)] = const_to_uri.get(m.group(2), "")
            quad_pred_token[m.group(1)] = f"__CONST_{m.group(2)}__"
        m = _OBJ_RE.search(sql)
        if m:
            quad_obj_const[m.group(1)] = const_to_uri.get(m.group(2), "")
            quad_obj_token[m.group(1)] = f"__CONST_{m.group(2)}__"

    # --- Step 3: Build edge table variable bindings ---
    table_by_alias: Dict[str, TableRef] = {t.alias: t for t in plan.tables}

    # edge_alias → {"frame_var": ..., "slot_var": ...}
    edge_bindings: Dict[str, Dict[str, str]] = {}

    for var_name, slot in plan.var_slots.items():
        for ref_id, col in slot.positions:
            t = table_by_alias.get(ref_id)
            if t and t.kind == "edge":
                entry = edge_bindings.setdefault(ref_id, {})
                if col == "source_node_uuid":
                    entry["frame_var"] = var_name
                elif col == "dest_node_uuid":
                    entry["slot_var"] = var_name

    if not edge_bindings:
        # Silent declines are how a materialised table ends up maintained and
        # unused with nobody able to say why. Every exit says which precondition
        # failed (issues/048).
        FE.decline(
            "no edge table bindings — the frame->slot hops were not rewritten "
            "to the edge table first",
            table_kinds=sorted({t.kind for t in plan.tables}))
        return plan

    # --- Step 4: Find slot_type and slot_value quads ---
    slot_type_quads: Dict[str, str] = {}   # quad_alias → role
    slot_value_quads: Set[str] = set()

    for q_alias, pred_uri in quad_predicate.items():
        if pred_uri == SLOT_TYPE_URI:
            # ANY constant role. `urn:hasSourceEntity` and
            # `urn:hasDestinationEntity` are VALUES of `hasKGSlotType`, as
            # arbitrary as any other object — matching on them by name is what
            # `issues/183` records, and it silently excluded every frame schema
            # using different ones.
            obj_uri = quad_obj_const.get(q_alias, "")
            if obj_uri:
                slot_type_quads[q_alias] = obj_uri
        elif pred_uri == SLOT_VALUE_URI:
            slot_value_quads.add(q_alias)

    if not slot_type_quads or not slot_value_quads:
        FE.decline(
            "no slot arms — a frame_slot row needs a typed slot and its "
            "entity value",
            slot_type_quads=len(slot_type_quads),
            slot_value_quads=len(slot_value_quads))
        return plan

    # --- Step 5: Build subject/object variable maps for quads ---
    quad_subject_var: Dict[str, str] = {}
    quad_object_var: Dict[str, str] = {}

    for var_name, slot in plan.var_slots.items():
        for ref_id, col in slot.positions:
            t = table_by_alias.get(ref_id)
            if not t or t.kind != "quad":
                continue
            if col == "subject_uuid":
                quad_subject_var[ref_id] = var_name
            elif col == "object_uuid" and ref_id in slot_value_quads:
                quad_object_var[ref_id] = var_name

    # --- Step 6: Match slot quads to edge tables via shared slot variable ---
    groups: List[_SlotGroup] = []

    for st_alias, role in slot_type_quads.items():
        slot_var = quad_subject_var.get(st_alias)
        if not slot_var:
            continue

        # Find the edge table that has this slot_var at dest_node_uuid
        matched_edge = None
        for edge_alias, bindings in edge_bindings.items():
            if bindings.get("slot_var") == slot_var:
                matched_edge = edge_alias
                break
        if not matched_edge:
            continue

        frame_var = edge_bindings[matched_edge].get("frame_var")
        if not frame_var:
            continue

        # Find the slot_value quad with the same slot_var as subject
        matched_sv = None
        for sv_alias in slot_value_quads:
            if quad_subject_var.get(sv_alias) == slot_var:
                matched_sv = sv_alias
                break
        if not matched_sv:
            continue

        entity_var = quad_object_var.get(matched_sv)
        if not entity_var:
            continue

        groups.append(_SlotGroup(
            edge_alias=matched_edge,
            type_quad=st_alias,
            value_quad=matched_sv,
            role=role,
            slot_var=slot_var,
            entity_var=entity_var,
            frame_var=frame_var,
        ))

    # --- Step 7: Group arms by frame variable ---
    #
    # An ARM is one (edge, slot-type quad, slot-value quad) reaching one slot of
    # one frame. Previously this required exactly a "source" arm and a "dest"
    # arm, because `frame_entity` has one column for each. `frame_slot` holds
    # the role as data, so any number of arms with any role values collapse —
    # two is merely the common case (`issues/183`).
    frame_groups: Dict[str, List[_SlotGroup]] = {}
    for g in groups:
        frame_groups.setdefault(g.frame_var, []).append(g)

    # Two arms on one frame is the shape worth collapsing: a single arm is one
    # slot lookup, which the quad tables already do without a join saved.
    frame_arms: List[List[_SlotGroup]] = [
        arms for arms in frame_groups.values() if len(arms) >= 2]

    if not frame_arms:
        FE.decline(
            "no frame variable carries two or more slot arms, which is what a "
            "frame_slot collapse joins",
            frame_vars={v: sorted(g.role for g in a)
                        for v, a in frame_groups.items()})
        return plan

    logger.debug("Frame-slot rewrite: %d frame pattern(s), arms per frame %s",
                 len(frame_arms), [len(a) for a in frame_arms])

    # --- Step 8: Replace each pair with a frame_entity table ---
    removed_aliases: Set[str] = set()
    # Aliases whose OWN constraints are replaced wholesale by an absorbed type
    # predicate, rather than remapped conjunct by conjunct.
    type_quad_owned: Set[str] = set()
    absorbed_type: List[Tuple[str, str]] = []
    new_fe_tables: List[TableRef] = []
    alias_map: Dict[str, Tuple[str, Dict[str, Optional[str]]]] = {}
    # The frame_entity aliases this pass CREATES. Needed by the issues/051
    # check below, which asks whether a variable is still bound by a
    # SURVIVING table — and `alias_map` is keyed by the OLD aliases, so a
    # position on the new table looks like a survivor unless excluded.
    fe_aliases: Set[str] = set()

    for arms in frame_arms:
        # One frame_slot join per arm. They join to each other on `frame_uuid`
        # automatically: the frame variable has a position on every arm's alias,
        # so the emitter produces the equality itself.
        arm_alias: Dict[int, str] = {}
        for _g in arms:
            _a = aliases.next("fsmv")
            fe_aliases.add(_a)
            arm_alias[id(_g)] = _a
            new_fe_tables.append(TableRef(
                ref_id=_a, kind="frame_slot",
                table_name=fs_table_name, alias=_a,
            ))
        # The frame ANCHOR. Everything below that is a property of the FRAME
        # rather than of one slot — the frame type absorption, the edge-type and
        # slot-type semi-joins — hangs off this one alias, and every arm carries
        # the same `frame_uuid`, so any arm would do. Kept under the old name so
        # those blocks are untouched by this change.
        fe_alias = arm_alias[id(arms[0])]


        for _g in arms:
            for alias in (_g.edge_alias, _g.type_quad, _g.value_quad):
                removed_aliases.add(alias)

        for _g in arms:
            a = arm_alias[id(_g)]
            # edge: frame -> slot
            alias_map[_g.edge_alias] = (a, {
                "source_node_uuid": "frame_uuid",
                "dest_node_uuid": "slot_uuid",
                "edge_uuid": None,
                "context_uuid": "context_uuid",
            })
            # slot TYPE quad. `object_uuid -> role_uuid` is what makes the role
            # constraint survive: the query's own
            # `qN.object_uuid = __CONST_role__` is remapped to
            # `fsN.role_uuid = __CONST_role__`, whatever that constant is. No
            # role value is named here.
            alias_map[_g.type_quad] = (a, {
                "subject_uuid": "slot_uuid",
                "predicate_uuid": None,
                "object_uuid": "role_uuid",
                "context_uuid": "context_uuid",
            })
            # slot VALUE quad
            alias_map[_g.value_quad] = (a, {
                "subject_uuid": "slot_uuid",
                "predicate_uuid": None,
                "object_uuid": "entity_uuid",
                "context_uuid": "context_uuid",
            })

        # A `<frame> vitaltype <Type>` triple collapses in too: the column holds
        # exactly that, so the quad table is redundant. Measured on
        # wordnet_frames at depth 3 this probe was 79% of ALL buffers
        # (2,006,247 of 2,543,685), run once per output row.
        #
        # Handled explicitly rather than through `alias_map` alone. The generic
        # remap leaves a column mapped to None UNTOUCHED in the constraint text,
        # so `q0.predicate_uuid` survived, the leftover check saw a removed
        # alias still referenced, and the whole rewrite declined — silently
        # correct and no faster. The predicate conjunct is what IDENTIFIES the
        # triple as a vitaltype, and the column already encodes that, so it is
        # dropped rather than remapped.
        for tq in _type_quads_for(plan, arms[0].frame_var, quad_predicate,
                                  quad_obj_const, table_by_alias, aliases):
            removed_aliases.add(tq)
            type_quad_owned.add(tq)
            alias_map[tq] = (fe_alias, {
                "subject_uuid": "frame_uuid",
                "predicate_uuid": None,
                "object_uuid": "frame_type_uuid",
                "context_uuid": "context_uuid",
            })
            tok = quad_obj_token.get(tq)
            if tok:
                absorbed_type.append(
                    (fe_alias, f"{fe_alias}.frame_type_uuid = {tok}"))

        # A type constraint on a SLOT node becomes a role-scoped semi-join back
        # through the edge (issues/048 Problem 1).
        #
        # `frame_entity` has no slot column, so this constraint used to leave the
        # slot variable bound by a surviving table with its tie to the frame gone
        # — the `issues/051` cross-product shape — and the whole rewrite declined.
        # Measured cost of that decline: 542,012 buffers where the unconstrained
        # walk reads 10,626.
        #
        # THE ROLE JOIN IS THE CORRECTNESS. Without `st_x` this reads "the frame
        # has SOME slot of type T" rather than "the ROLE-scoped slot is of type
        # T". Those agreed on every fixture until `--attribute-slot-fraction`
        # existed, because every slot was a KGEntitySlot; on the regenerated
        # `sp_graph_skew_2k` they are 0 and 2,317.
        # The edge VARIABLE, for the slot-EDGE form below. `?slotEdge` binds at
        # the edge table's `edge_uuid`, which the collapse maps to None.
        edge_var_of = {}
        for _v, _s in (plan.var_slots or {}).items():
            for _ref, _col in (_s.positions or []):
                if _col == "edge_uuid":
                    edge_var_of[_ref] = _v

        for g in arms:
            role_pred = quad_pred_token.get(g.type_quad)
            role_obj = quad_obj_token.get(g.type_quad)
            if not (role_pred and role_obj):
                continue

            # `?slotEdge vitaltype Edge_hasKGSlot` — the form `kgframes_endpoint`
            # emits, and the more expensive of the two when it declines (691K
            # buffers). CHEAPER to absorb than the slot-node form: `{space}_edge`
            # carries `edge_type_uuid`, so this is a column test on the row the
            # semi-join already visits, with no second quad join.
            #
            # The role join stays. Without it this reads "the frame has SOME edge
            # of this type", which is true of every connection frame.
            e_var = edge_var_of.get(g.edge_alias)
            if e_var:
                for etq in _slot_type_quads_for(plan, e_var, quad_predicate,
                                                quad_obj_const, table_by_alias):
                    e_tok = quad_obj_token.get(etq)
                    if not e_tok:
                        continue

                    ex = aliases.next("edgechk")
                    removed_aliases.add(etq)
                    type_quad_owned.add(etq)
                    alias_map[etq] = (fe_alias, {
                        "subject_uuid": None, "predicate_uuid": None,
                        "object_uuid": None, "context_uuid": "context_uuid",
                    })
                    absorbed_type.append((fe_alias, (
                        f"EXISTS (SELECT 1 FROM {edge_table_name} AS e_{ex}"
                        f" JOIN {quad_table_name} AS st_{ex}"
                        f" ON st_{ex}.subject_uuid = e_{ex}.dest_node_uuid"
                        f" AND st_{ex}.predicate_uuid = {role_pred}"
                        f" AND st_{ex}.object_uuid = {role_obj}"
                        f" WHERE e_{ex}.source_node_uuid = {fe_alias}.frame_uuid"
                        f" AND e_{ex}.context_uuid = {fe_alias}.context_uuid"
                        f" AND e_{ex}.edge_type_uuid = {e_tok})")))
            for stq in _slot_type_quads_for(plan, g.slot_var, quad_predicate,
                                            quad_obj_const, table_by_alias):
                ty_pred = quad_pred_token.get(stq)
                ty_obj = quad_obj_token.get(stq)
                if not (ty_pred and ty_obj):
                    continue

                # If the data says this type excludes no role slot in this
                # space, the check cannot change the answer and the semi-join is
                # pure cost — 7.4x of it on an unfiltered walk (issues/048
                # Problem 4). Drop the quad and emit nothing.
                #
                # `True` only. None means unanswered — no connection, a missing
                # term, a failed query — and unanswered must keep the check: the
                # risk is one-sided, since dropping a constraint that DOES
                # exclude something returns rows that should not be there.
                verdict = (getattr(aliases, "slot_type_tautology", None) or {}).get(
                    (quad_predicate.get(stq), quad_obj_const.get(stq)))
                if verdict is True:
                    removed_aliases.add(stq)
                    type_quad_owned.add(stq)
                    alias_map[stq] = (fe_alias, {
                        "subject_uuid": None, "predicate_uuid": None,
                        "object_uuid": None, "context_uuid": "context_uuid",
                    })
                    logger.info(
                        "frame_entity: slot type %s excludes nothing in %s — "
                        "dropped rather than checked per row (issues/048)",
                        quad_obj_const.get(stq), space_id)
                    continue

                ex = aliases.next("slotchk")
                removed_aliases.add(stq)
                type_quad_owned.add(stq)
                alias_map[stq] = (fe_alias, {
                    "subject_uuid": None, "predicate_uuid": None,
                    "object_uuid": None, "context_uuid": "context_uuid",
                })
                absorbed_type.append((fe_alias, (
                    f"EXISTS (SELECT 1 FROM {edge_table_name} AS e_{ex}"
                    f" JOIN {quad_table_name} AS st_{ex}"
                    f" ON st_{ex}.subject_uuid = e_{ex}.dest_node_uuid"
                    f" AND st_{ex}.predicate_uuid = {role_pred}"
                    f" AND st_{ex}.object_uuid = {role_obj}"
                    f" JOIN {quad_table_name} AS ty_{ex}"
                    f" ON ty_{ex}.subject_uuid = e_{ex}.dest_node_uuid"
                    f" AND ty_{ex}.predicate_uuid = {ty_pred}"
                    f" AND ty_{ex}.object_uuid = {ty_obj}"
                    f" WHERE e_{ex}.source_node_uuid = {fe_alias}.frame_uuid"
                    f" AND e_{ex}.context_uuid = {fe_alias}.context_uuid)")))

    # --- Rewrite tables ---
    new_tables: List[TableRef] = []
    for t in plan.tables:
        if t.alias in removed_aliases:
            continue
        if t.kind == "term" and t.join_col:
            parts = t.join_col.split(".")
            if len(parts) == 2 and parts[0] in alias_map:
                new_fe, col_map = alias_map[parts[0]]
                new_col = col_map.get(parts[1])
                if new_col:
                    t.join_col = f"{new_fe}.{new_col}"
                else:
                    continue  # term table for eliminated slot — skip
        new_tables.append(t)
    plan.tables = new_fe_tables + new_tables

    # --- Rewrite variable positions ---
    seen_positions: Set[Tuple[str, str]] = set()
    # A variable that loses a position here because frame_entity has no column
    # for it, but is STILL bound by a surviving table, has quietly lost its tie
    # to the frame — and an unconstrained quad table is a cross product.
    #
    # That is issues/051: `?sourceEdge a Edge_hasKGSlot` binds the edge variable
    # both at mv0.edge_uuid (collapsed away) and at the type quad's subject
    # (surviving). Dropping the first leaves the type quad scanning every
    # Edge_hasKGSlot in the space. Measured on wordnet: 285,348 rows correct,
    # over a million produced, and an unbounded count that would not finish.
    broken: List[str] = []
    had_positions = {k for k, v in plan.var_slots.items() if v.positions}
    for _var_name, slot in plan.var_slots.items():
        new_positions = []
        lost_to_fe = False
        for ref_id, col_name in slot.positions:
            if ref_id in alias_map:
                new_fe, col_map = alias_map[ref_id]
                new_col = col_map.get(col_name)
                if new_col is None:
                    lost_to_fe = True
                    continue
                pos_key = (new_fe, new_col)
                if pos_key not in seen_positions:
                    new_positions.append(pos_key)
                    seen_positions.add(pos_key)
            else:
                new_positions.append((ref_id, col_name))
        # `ref not in alias_map` means "bound by a table the collapse did not
        # absorb" — the cross-product hazard of issues/051. A position on the
        # frame_entity table this pass just CREATED is not that: it IS the
        # collapse, and since issues/182 gave the table `source_slot_uuid` /
        # `dest_slot_uuid` the slot variables land there instead of being
        # emptied. Without this exclusion the guard fires on its own output and
        # declines every frame pattern that names a slot.
        if lost_to_fe and any(ref not in alias_map and ref not in fe_aliases
                              for ref, _ in new_positions):
            broken.append(_var_name)
        slot.positions = new_positions
    if broken:
        FE.decline(
            "a variable would lose the binding that ties it to the frame "
            "while still being bound by a surviving table, which reads as a "
            "cross product (issues/051)",
            broken=sorted(broken))
        return original_plan
    # A variable whose every position mapped into `frame_entity` at a column
    # that does not exist has been emptied above, and the line below would drop
    # it from the plan entirely. `compute_scope` then reports it out of scope,
    # `null_companions` pads it with a literal NULL, and the query returns a
    # column of NULLs where it asked for slots — silently, with HTTP 200
    # (issues/178).
    #
    # The `broken` check above does not cover this: it fires only when the
    # variable is ALSO bound by a surviving table, which reads as a cross
    # product (issues/051). That guards wrong ROWS. This one guards a missing
    # OUTPUT, which the A/B in issues/178 measured as the whole of the defect —
    # 425 rows either way, identical, with the two slot columns NULL.
    emptied = sorted(had_positions - {k for k, v in plan.var_slots.items()
                                      if v.positions})
    if emptied and (needed_vars is None
                    or any(v in needed_vars for v in emptied)):
        FE.decline(
            "the collapse would empty a variable the query still reads, and "
            "`frame_entity` has no column to rebind it from (issues/178)",
            emptied=emptied,
            needed=("<all: SELECT *>" if needed_vars is None
                    else sorted(v for v in emptied if v in needed_vars)))
        return original_plan
    plan.var_slots = {k: v for k, v in plan.var_slots.items() if v.positions}

    # --- Rewrite constraints ---
    new_constraints: List[str] = []
    new_tagged: List[Tuple[str, str]] = []
    seen_ctx: Set[str] = set()

    for owner, sql in plan.tagged_constraints:
        if owner in type_quad_owned:
            # Its subject tie and its type value are both now columns of the
            # frame_entity row, and its predicate identified a triple that no
            # longer exists as a table. Nothing here survives remapping.
            continue
        if owner in removed_aliases:
            # Preserve context constraints — remap to fe table (deduplicated)
            if ".context_uuid" in sql:
                new_fe = alias_map[owner][0]
                new_sql = sql.replace(f"{owner}.", f"{new_fe}.")
                ctx_key = f"{new_fe}:ctx"
                if ctx_key not in seen_ctx:
                    seen_ctx.add(ctx_key)
                    new_tagged.append((new_fe, new_sql))
                    new_constraints.append(new_sql)
                continue

            # A constraint on a column the collapse KEEPS must be REMAPPED,
            # not dropped. `frame_slot` holds the role in `role_uuid`, so the
            # arm's own `qN.object_uuid = __CONST_role__` becomes
            # `fsN.role_uuid = __CONST_role__`.
            #
            # Dropping it was correct while the role lived in the COLUMN NAME
            # (`source_entity_uuid` vs `dest_entity_uuid`) — the constraint was
            # genuinely redundant. With the role as data it is load-bearing:
            # without it every arm matches every role, which measured as a 4x
            # cross product (1,700 rows where the answer is 425).
            _m_const = re.search(r"(\w+)\.(\w+)\s*=\s*(__CONST_c_\d+__)", sql)
            if _m_const and _m_const.group(1) == owner:
                _fe_a, _cm = alias_map[owner]
                _new_col = _cm.get(_m_const.group(2))
                if _new_col:
                    new_sql = f"{_fe_a}.{_new_col} = {_m_const.group(3)}"
                    new_tagged.append((_fe_a, new_sql))
                    new_constraints.append(new_sql)
                    continue

            # Check co-references linking removed ↔ non-removed tables
            m = _COREF_RE.search(sql)
            if m:
                a_al, a_col, b_al, b_col = (
                    m.group(1), m.group(2), m.group(3), m.group(4)
                )
                if a_al in removed_aliases and b_al in removed_aliases:
                    new_a_fe, a_cm = alias_map[a_al]
                    new_b_fe, b_cm = alias_map[b_al]
                    new_a_col = a_cm.get(a_col)
                    new_b_col = b_cm.get(b_col)
                    if (new_a_col and new_b_col
                            and (new_a_fe, new_a_col) != (new_b_fe, new_b_col)):
                        new_sql = f"{new_a_fe}.{new_a_col} = {new_b_fe}.{new_b_col}"
                        dup_key = f"{new_a_fe}.{new_a_col}={new_b_fe}.{new_b_col}"
                        if dup_key not in seen_ctx:
                            seen_ctx.add(dup_key)
                            new_tagged.append((new_a_fe, new_sql))
                            new_constraints.append(new_sql)
                elif a_al in removed_aliases and b_al not in removed_aliases:
                    new_fe, col_map = alias_map[a_al]
                    new_col = col_map.get(a_col)
                    if new_col:
                        new_sql = f"{new_fe}.{new_col} = {b_al}.{b_col}"
                        dup_key = f"{new_fe}.{new_col}={b_al}.{b_col}"
                        if dup_key not in seen_ctx:
                            seen_ctx.add(dup_key)
                            new_tagged.append((new_fe, new_sql))
                            new_constraints.append(new_sql)
                elif b_al in removed_aliases and a_al not in removed_aliases:
                    new_fe, col_map = alias_map[b_al]
                    new_col = col_map.get(b_col)
                    if new_col:
                        new_sql = f"{a_al}.{a_col} = {new_fe}.{new_col}"
                        dup_key = f"{new_fe}.{new_col}={a_al}.{a_col}"
                        if dup_key not in seen_ctx:
                            seen_ctx.add(dup_key)
                            new_tagged.append((a_al, new_sql))
                            new_constraints.append(new_sql)
            continue

        # Non-removed owner: remap any references to removed tables
        new_sql = _remap_constraint_sql(sql, alias_map)
        new_owner = owner

        if ".context_uuid" in new_sql:
            ctx_key = f"{new_owner}:{new_sql}"
            if ctx_key in seen_ctx:
                continue
            seen_ctx.add(ctx_key)

        new_tagged.append((new_owner, new_sql))
        new_constraints.append(new_sql)

    # Every reference to a collapsed table must have been remapped. Some cannot
    # be: frame_entity holds (frame, source_entity, dest_entity), so a
    # constraint on the SLOT node — `?sourceSlot a KGEntitySlot` in the
    # canonical query — has no column to remap onto. Emitting anyway produced
    # SQL PostgreSQL rejects outright:
    #
    #     missing FROM-clause entry for table "mv0"
    #
    # on the very query this rewrite exists to serve. Declining is the correct
    # outcome — the query then runs unrewritten, slower but valid — and it is
    # what the equivalent check in semijoin does when its BGP split cannot be
    # completed. See issues/048.
    # Alias boundaries matter: the frame_entity alias is "fe" + the edge alias
    # it replaced, so a substring test for "mv0." also matches "femv0." and
    # declines on the very constraint the rewrite just created correctly.
    def _refs(sql: str, alias: str) -> bool:
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(alias)}\.", sql) is not None

    for owner, sql in absorbed_type:
        if sql not in new_constraints:
            new_tagged.append((owner, sql))
            new_constraints.append(sql)

    leftover = sorted(
        a for a in removed_aliases
        if any(_refs(sql, a) for sql in new_constraints))
    if leftover:
        offenders = [c for c in new_constraints
                     if any(_refs(c, a) for a in leftover)]
        # The facts here are the ones that matter most in this module. This
        # exact decline fired silently for the vitaltype absorption — a conjunct
        # the remap left untouched still named a collapsed alias, so the whole
        # rewrite reverted, giving right answers at the old speed with no
        # symptom. `offenders` is the constraint text to read; without it the
        # message says a rewrite declined and nothing about which conjunct.
        FE.decline(
            "constraints still reference collapsed table(s) with no "
            "frame_entity column to remap onto (issues/048)",
            leftover=leftover, offenders=offenders[:3])
        return original_plan

    plan.tagged_constraints = new_tagged
    plan.constraints = new_constraints

    return plan


def _remap_constraint_sql(sql: str, alias_map: Dict) -> str:
    """Remap alias.column references in a constraint SQL string."""
    result = sql
    for old_alias, (new_alias, col_map) in alias_map.items():
        for old_col, new_col in col_map.items():
            if new_col is None:
                continue
            result = result.replace(f"{old_alias}.{old_col}", f"{new_alias}.{new_col}")
    return result
