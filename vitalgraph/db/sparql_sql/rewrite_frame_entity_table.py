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

import logging
import re
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from .ir import PlanV2, TableRef, AliasGenerator, KIND_BGP

logger = logging.getLogger(__name__)

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
SLOT_VALUE_URI = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
SOURCE_ENTITY_URI = "urn:hasSourceEntity"
DEST_ENTITY_URI = "urn:hasDestinationEntity"

_PRED_RE = re.compile(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(c_\d+)__")
_OBJ_RE = re.compile(r"(\w+)\.object_uuid\s*=\s*__CONST_(c_\d+)__")
_COREF_RE = re.compile(r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)")


class _SlotGroup(NamedTuple):
    """A matched slot group: edge table + slot_type quad + slot_value quad."""
    edge_alias: str
    type_quad: str
    value_quad: str
    role: str           # "source" or "dest"
    slot_var: str       # SPARQL variable for the slot node
    entity_var: str     # SPARQL variable for the entity
    frame_var: str      # SPARQL variable for the frame


def rewrite_frame_entity_table(plan: PlanV2, aliases: AliasGenerator,
                                space_id: str) -> PlanV2:
    """Rewrite a v2 plan to use the frame_entity table where possible.

    Detects groups of 6 tables (2 edge + 2 slot_type + 2 slot_value)
    that form a frame traversal pattern and replaces each group with a
    single frame_entity table lookup.
    """
    if plan.kind != KIND_BGP or not plan.tables:
        for i, child in enumerate(plan.children):
            plan.children[i] = rewrite_frame_entity_table(child, aliases, space_id)
        return plan

    fe_table_name = f"{space_id}_frame_entity"

    # --- Step 1: Build constant reverse map ---
    const_to_uri: Dict[str, str] = {}
    for (text, ttype), col_alias in aliases.constants.items():
        if ttype == "U":
            const_to_uri[col_alias] = text

    # --- Step 2: Classify quad tables by predicate and object URIs ---
    quad_predicate: Dict[str, str] = {}
    quad_obj_const: Dict[str, str] = {}

    for _owner, sql in plan.tagged_constraints:
        m = _PRED_RE.search(sql)
        if m:
            quad_predicate[m.group(1)] = const_to_uri.get(m.group(2), "")
        m = _OBJ_RE.search(sql)
        if m:
            quad_obj_const[m.group(1)] = const_to_uri.get(m.group(2), "")

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
        return plan

    logger.debug("Frame-entity table rewrite: found %d frame pattern(s)", len(pairs))

    # --- Step 8: Replace each pair with a frame_entity table ---
    removed_aliases: Set[str] = set()
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
    for _var_name, slot in plan.var_slots.items():
        new_positions = []
        for ref_id, col_name in slot.positions:
            if ref_id in alias_map:
                new_fe, col_map = alias_map[ref_id]
                new_col = col_map.get(col_name)
                if new_col is None:
                    continue
                pos_key = (new_fe, new_col)
                if pos_key not in seen_positions:
                    new_positions.append(pos_key)
                    seen_positions.add(pos_key)
            else:
                new_positions.append((ref_id, col_name))
        slot.positions = new_positions
    plan.var_slots = {k: v for k, v in plan.var_slots.items() if v.positions}

    # --- Rewrite constraints ---
    new_constraints: List[str] = []
    new_tagged: List[Tuple[str, str]] = []
    seen_ctx: Set[str] = set()

    for owner, sql in plan.tagged_constraints:
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
