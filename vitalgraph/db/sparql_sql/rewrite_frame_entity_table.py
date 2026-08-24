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
from .ir import PlanV2, TableRef, AliasGenerator, KIND_BGP

logger = logging.getLogger(__name__)

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
SLOT_VALUE_URI = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
SOURCE_ENTITY_URI = "urn:hasSourceEntity"
DEST_ENTITY_URI = "urn:hasDestinationEntity"
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
                    table_by_alias):
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
        if quad_predicate.get(ref_id) != VITALTYPE_URI:
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


def rewrite_frame_entity_table(plan: PlanV2, aliases: AliasGenerator,
                                space_id: str) -> PlanV2:
    """Rewrite a v2 plan to use the frame_entity table where possible.

    Detects groups of 6 tables (2 edge + 2 slot_type + 2 slot_value)
    that form a frame traversal pattern and replaces each group with a
    single frame_entity table lookup.
    """
    # Kept so a decline can return the plan untouched rather than a
    # half-rewritten one.
    original_plan = copy.deepcopy(plan)

    if plan.kind != KIND_BGP or not plan.tables:
        for i, child in enumerate(plan.children):
            plan.children[i] = rewrite_frame_entity_table(child, aliases, space_id)
        return plan

    fe_table_name = f"{space_id}_frame_entity"
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
            obj_uri = quad_obj_const.get(q_alias, "")
            if obj_uri == SOURCE_ENTITY_URI:
                slot_type_quads[q_alias] = "source"
            elif obj_uri == DEST_ENTITY_URI:
                slot_type_quads[q_alias] = "dest"
        elif pred_uri == SLOT_VALUE_URI:
            slot_value_quads.add(q_alias)

    if not slot_type_quads or not slot_value_quads:
        FE.decline(
            "no source/dest slot groups — a frame_entity row needs both a "
            "typed slot and its entity value",
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

    # --- Step 7: Group by frame_var, find source+dest pairs ---
    frame_groups: Dict[str, Dict[str, _SlotGroup]] = {}
    for g in groups:
        frame_groups.setdefault(g.frame_var, {})[g.role] = g

    pairs: List[Tuple[_SlotGroup, _SlotGroup]] = []
    for _fvar, roles in frame_groups.items():
        if "source" in roles and "dest" in roles:
            pairs.append((roles["source"], roles["dest"]))

    if not pairs:
        FE.decline(
            "no frame variable carries BOTH a source and a dest group, which "
            "is what one frame_entity row represents",
            frame_vars={v: sorted(r) for v, r in frame_groups.items()})
        return plan

    logger.debug("Frame-entity table rewrite: found %d frame pattern(s)", len(pairs))

    # --- Step 8: Replace each pair with a frame_entity table ---
    removed_aliases: Set[str] = set()
    # Aliases whose OWN constraints are replaced wholesale by an absorbed type
    # predicate, rather than remapped conjunct by conjunct.
    type_quad_owned: Set[str] = set()
    absorbed_type: List[Tuple[str, str]] = []
    new_fe_tables: List[TableRef] = []
    alias_map: Dict[str, Tuple[str, Dict[str, Optional[str]]]] = {}

    for src_g, dst_g in pairs:
        fe_alias = aliases.next("femv")
        new_fe_tables.append(TableRef(
            ref_id=fe_alias, kind="frame_entity",
            table_name=fe_table_name, alias=fe_alias,
        ))

        for alias in [src_g.edge_alias, dst_g.edge_alias,
                      src_g.type_quad, dst_g.type_quad,
                      src_g.value_quad, dst_g.value_quad]:
            removed_aliases.add(alias)

        # Source edge: frame → srcSlot
        alias_map[src_g.edge_alias] = (fe_alias, {
            "source_node_uuid": "frame_uuid",
            "dest_node_uuid": None,
            "edge_uuid": None,
            "context_uuid": "context_uuid",
        })
        # Dest edge: frame → dstSlot
        alias_map[dst_g.edge_alias] = (fe_alias, {
            "source_node_uuid": "frame_uuid",
            "dest_node_uuid": None,
            "edge_uuid": None,
            "context_uuid": "context_uuid",
        })
        # Slot type quads: eliminated entirely
        for st_q in [src_g.type_quad, dst_g.type_quad]:
            alias_map[st_q] = (fe_alias, {
                "subject_uuid": None,
                "predicate_uuid": None,
                "object_uuid": None,
                "context_uuid": "context_uuid",
            })
        # Slot value quads: object_uuid → entity column
        alias_map[src_g.value_quad] = (fe_alias, {
            "subject_uuid": None,
            "predicate_uuid": None,
            "object_uuid": "source_entity_uuid",
            "context_uuid": "context_uuid",
        })
        alias_map[dst_g.value_quad] = (fe_alias, {
            "subject_uuid": None,
            "predicate_uuid": None,
            "object_uuid": "dest_entity_uuid",
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
        for tq in _type_quads_for(plan, src_g.frame_var, quad_predicate,
                                  quad_obj_const, table_by_alias):
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

        for g in (src_g, dst_g):
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
        if lost_to_fe and any(ref not in alias_map for ref, _ in new_positions):
            broken.append(_var_name)
        slot.positions = new_positions
    if broken:
        FE.decline(
            "a variable would lose the binding that ties it to the frame "
            "while still being bound by a surviving table, which reads as a "
            "cross product (issues/051)",
            broken=sorted(broken))
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
