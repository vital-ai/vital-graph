"""
Frame-Entity MV optimization pass — replaces slot+edge patterns with a
pre-computed materialized view mapping frames to source/destination entities.

The pattern detected (post edge-MV rewrite):

    edge_mv:     frame → slot  (source_node_uuid, dest_node_uuid)
    slot_type:   slot hasSlotType <hasSourceEntity|hasDestEntity>
    slot_value:  slot hasSlotValue ?entity

When a source group and dest group share the same frame variable, all 6 tables
(2 edge_mv + 2 slot_type + 2 slot_value) are replaced by one frame_entity_mv:

    {space}_frame_entity_mv(frame_uuid, source_entity_uuid, dest_entity_uuid, context_uuid)

This eliminates 5 JOINs per hop.  For a 4-hop query: 38 → ~18 tables.

Architecture:
    - ensure_frame_entity_mv():  DDL — create/refresh the MV if missing
    - rewrite_frame_entity_mv(): Plan rewrite — detect patterns, replace in IR
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, NamedTuple, Optional, Set, Tuple

from .jena_sql_ir import AliasGenerator, TableRef, VarSlot, RelationPlan

logger = logging.getLogger(__name__)

# Predicates for slot structure
SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
SLOT_VALUE_URI = "http://vital.ai/ontology/haley-ai-kg#hasEntitySlotValue"
SOURCE_ENTITY_URI = "urn:hasSourceEntity"
DEST_ENTITY_URI = "urn:hasDestinationEntity"


class _SlotGroup(NamedTuple):
    """A matched slot group: edge_mv + slot_type quad + slot_value quad."""
    mv_alias: str
    type_quad: str
    value_quad: str
    role: str           # "source" or "dest"
    slot_var: str       # SPARQL variable for the slot node
    entity_var: str     # SPARQL variable for the entity
    frame_var: str      # SPARQL variable for the frame


# ===========================================================================
# DDL: ensure the frame-entity MV exists
# ===========================================================================

def ensure_frame_entity_mv(space_id: str, conn=None, conn_params=None) -> bool:
    """Create the frame-entity MV if it doesn't exist.  Returns True if usable."""
    from . import db

    mv_name = f"{space_id}_frame_entity_mv"
    edge_mv_name = f"{space_id}_edge_mv"
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    # Check if MV already exists
    try:
        rows = db.execute_query(
            "SELECT 1 FROM pg_matviews WHERE matviewname = %s",
            params=(mv_name,), conn=conn, conn_params=conn_params,
        )
        if rows:
            logger.debug("Frame-entity MV %s already exists", mv_name)
            return True
    except Exception as e:
        logger.debug("Error checking frame-entity MV: %s", e)
        return False

    # Check edge MV exists (prerequisite)
    try:
        rows = db.execute_query(
            "SELECT 1 FROM pg_matviews WHERE matviewname = %s",
            params=(edge_mv_name,), conn=conn, conn_params=conn_params,
        )
        if not rows:
            logger.debug("Edge MV %s not found, skipping frame-entity MV", edge_mv_name)
            return False
    except Exception:
        return False

    # Look up predicate/type UUIDs from term table
    uuid_map: Dict[str, str] = {}
    for uri in [SLOT_TYPE_URI, SLOT_VALUE_URI, SOURCE_ENTITY_URI, DEST_ENTITY_URI]:
        rows = db.execute_query(
            f"SELECT term_uuid FROM {term_table} WHERE term_text = %s LIMIT 1",
            params=(uri,), conn=conn, conn_params=conn_params,
        )
        if not rows:
            logger.debug("Term %s not found in %s, skipping frame-entity MV", uri, term_table)
            return False
        uuid_map[uri] = str(rows[0]["term_uuid"])

    st_uuid = uuid_map[SLOT_TYPE_URI]
    sv_uuid = uuid_map[SLOT_VALUE_URI]
    src_uuid = uuid_map[SOURCE_ENTITY_URI]
    dst_uuid = uuid_map[DEST_ENTITY_URI]

    logger.info("Creating frame-entity MV %s ...", mv_name)
    ddl = f"""
    CREATE MATERIALIZED VIEW {mv_name} AS
    SELECT
        emv.source_node_uuid  AS frame_uuid,
        (array_agg(sv.object_uuid) FILTER (
            WHERE st.object_uuid = '{src_uuid}'::uuid
        ))[1] AS source_entity_uuid,
        (array_agg(sv.object_uuid) FILTER (
            WHERE st.object_uuid = '{dst_uuid}'::uuid
        ))[1] AS dest_entity_uuid,
        emv.context_uuid      AS context_uuid
    FROM {edge_mv_name} emv
    JOIN {quad_table} st
        ON st.subject_uuid = emv.dest_node_uuid
        AND st.predicate_uuid = '{st_uuid}'::uuid
    JOIN {quad_table} sv
        ON sv.subject_uuid = emv.dest_node_uuid
        AND sv.predicate_uuid = '{sv_uuid}'::uuid
    WHERE st.object_uuid IN ('{src_uuid}'::uuid, '{dst_uuid}'::uuid)
    GROUP BY emv.source_node_uuid, emv.context_uuid
    HAVING (array_agg(sv.object_uuid) FILTER (
        WHERE st.object_uuid = '{src_uuid}'::uuid
    ))[1] IS NOT NULL
    AND (array_agg(sv.object_uuid) FILTER (
        WHERE st.object_uuid = '{dst_uuid}'::uuid
    ))[1] IS NOT NULL
    """

    idx_prefix = f"idx_{space_id}_frame_entity_mv"
    indexes = [
        # Given source entity, find frames (forward hop: entity → frame)
        f"CREATE INDEX {idx_prefix}_src_frame "
        f"ON {mv_name} (source_entity_uuid, frame_uuid)",
        # Given dest entity, find frames (reverse hop)
        f"CREATE INDEX {idx_prefix}_dst_frame "
        f"ON {mv_name} (dest_entity_uuid, frame_uuid)",
        # Given frame, find both entities
        f"CREATE INDEX {idx_prefix}_frame "
        f"ON {mv_name} (frame_uuid)",
    ]

    try:
        with db.get_connection(params=conn_params) as c:
            with c.cursor() as cur:
                cur.execute(ddl)
                for idx_sql in indexes:
                    cur.execute(idx_sql)
            c.commit()

        rows = db.execute_query(
            f"SELECT COUNT(*) as cnt FROM {mv_name}",
            conn=conn, conn_params=conn_params,
        )
        cnt = rows[0]["cnt"] if rows else 0
        logger.info("Frame-entity MV %s created with %d rows and 3 indexes", mv_name, cnt)
        return True

    except Exception as e:
        logger.warning("Failed to create frame-entity MV %s: %s", mv_name, e)
        return False


# ===========================================================================
# Plan rewrite: detect slot+edge patterns and replace with MV references
# ===========================================================================

def rewrite_frame_entity_mv(plan: RelationPlan, aliases: AliasGenerator,
                             space_id: str) -> RelationPlan:
    """Rewrite a plan to use the frame_entity MV where possible.

    Detects groups of 6 tables (2 edge_mv + 2 slot_type + 2 slot_value)
    that form a frame traversal pattern and replaces each group with a
    single frame_entity_mv lookup.
    """
    if plan.kind != "bgp" or not plan.tables:
        for i, child in enumerate(plan.children):
            plan.children[i] = rewrite_frame_entity_mv(child, aliases, space_id)
        return plan

    mv_name = f"{space_id}_frame_entity_mv"

    # --- Step 1: Build constant reverse map ---
    const_to_uri: Dict[str, str] = {}
    for (text, ttype), col_alias in aliases.constants.items():
        if ttype == "U":
            const_to_uri[col_alias] = text

    # --- Step 2: Classify quad tables by predicate and object URIs ---
    pred_re = re.compile(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(c_\d+)__")
    obj_re = re.compile(r"(\w+)\.object_uuid\s*=\s*__CONST_(c_\d+)__")

    quad_predicate: Dict[str, str] = {}   # quad_alias → predicate URI
    quad_obj_const: Dict[str, str] = {}   # quad_alias → object URI

    for _owner, sql in plan.tagged_constraints:
        m = pred_re.search(sql)
        if m:
            quad_predicate[m.group(1)] = const_to_uri.get(m.group(2), "")
        m = obj_re.search(sql)
        if m:
            quad_obj_const[m.group(1)] = const_to_uri.get(m.group(2), "")

    # --- Step 3: Build edge_mv variable bindings ---
    table_by_alias: Dict[str, TableRef] = {t.alias: t for t in plan.tables}

    # mv_alias → {"frame_var": ..., "slot_var": ...}
    mv_bindings: Dict[str, Dict[str, str]] = {}

    for var_name, slot in plan.var_slots.items():
        for ref_id, col in slot.positions:
            t = table_by_alias.get(ref_id)
            if t and t.kind == "edge_mv":
                entry = mv_bindings.setdefault(ref_id, {})
                if col == "source_node_uuid":
                    entry["frame_var"] = var_name
                elif col == "dest_node_uuid":
                    entry["slot_var"] = var_name

    if not mv_bindings:
        return plan

    # --- Step 4: Find slot_type and slot_value quads ---
    slot_type_quads: Dict[str, str] = {}   # quad_alias → role ("source"/"dest")
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
    # quad_alias → subject variable name
    quad_subject_var: Dict[str, str] = {}
    # quad_alias → object variable name (for slot_value quads)
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

    # --- Step 6: Match slot quads to edge_mvs via shared slot variable ---
    groups: List[_SlotGroup] = []

    for st_alias, role in slot_type_quads.items():
        slot_var = quad_subject_var.get(st_alias)
        if not slot_var:
            continue

        # Find the edge_mv that has this slot_var at dest_node_uuid
        matched_mv = None
        for mv_alias, bindings in mv_bindings.items():
            if bindings.get("slot_var") == slot_var:
                matched_mv = mv_alias
                break
        if not matched_mv:
            continue

        frame_var = mv_bindings[matched_mv].get("frame_var")
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
            mv_alias=matched_mv,
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

    logger.debug("Frame-entity MV rewrite: found %d frame pattern(s)", len(pairs))

    # --- Step 8: Replace each pair with a frame_entity_mv table ---
    removed_aliases: Set[str] = set()
    new_mv_tables: List[TableRef] = []
    alias_map: Dict[str, Tuple[str, Dict[str, Optional[str]]]] = {}

    for src_g, dst_g in pairs:
        femv_alias = aliases.next("femv")
        new_mv_tables.append(TableRef(
            ref_id=femv_alias, kind="frame_entity_mv",
            table_name=mv_name, alias=femv_alias,
        ))

        for alias in [src_g.mv_alias, dst_g.mv_alias,
                      src_g.type_quad, dst_g.type_quad,
                      src_g.value_quad, dst_g.value_quad]:
            removed_aliases.add(alias)

        # Source edge_mv: frame → srcSlot
        alias_map[src_g.mv_alias] = (femv_alias, {
            "source_node_uuid": "frame_uuid",
            "dest_node_uuid": None,      # slot eliminated
            "edge_uuid": None,           # edge eliminated
            "context_uuid": "context_uuid",
        })
        # Dest edge_mv: frame → dstSlot
        alias_map[dst_g.mv_alias] = (femv_alias, {
            "source_node_uuid": "frame_uuid",
            "dest_node_uuid": None,
            "edge_uuid": None,
            "context_uuid": "context_uuid",
        })
        # Slot type quads: eliminated entirely
        for st_q in [src_g.type_quad, dst_g.type_quad]:
            alias_map[st_q] = (femv_alias, {
                "subject_uuid": None,
                "predicate_uuid": None,
                "object_uuid": None,
                "context_uuid": "context_uuid",
            })
        # Slot value quads: object_uuid → entity column
        alias_map[src_g.value_quad] = (femv_alias, {
            "subject_uuid": None,
            "predicate_uuid": None,
            "object_uuid": "source_entity_uuid",
            "context_uuid": "context_uuid",
        })
        alias_map[dst_g.value_quad] = (femv_alias, {
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
                new_mv, col_map = alias_map[parts[0]]
                new_col = col_map.get(parts[1])
                if new_col:
                    t.join_col = f"{new_mv}.{new_col}"
                else:
                    # Term table for an eliminated slot variable — skip it
                    continue
        new_tables.append(t)
    plan.tables = new_mv_tables + new_tables

    # --- Rewrite variable positions ---
    seen_positions: Set[Tuple[str, str]] = set()
    for _var_name, slot in plan.var_slots.items():
        new_positions = []
        for ref_id, col_name in slot.positions:
            if ref_id in alias_map:
                new_mv, col_map = alias_map[ref_id]
                new_col = col_map.get(col_name)
                if new_col is None:
                    continue
                pos_key = (new_mv, new_col)
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
    coref_re = re.compile(r"(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)")

    for owner, sql in plan.tagged_constraints:
        if owner in removed_aliases:
            # Preserve context constraints — remap to femv (deduplicated)
            if ".context_uuid" in sql:
                new_mv = alias_map[owner][0]
                new_sql = sql.replace(f"{owner}.", f"{new_mv}.")
                ctx_key = f"{new_mv}:ctx"
                if ctx_key not in seen_ctx:
                    seen_ctx.add(ctx_key)
                    new_tagged.append((new_mv, new_sql))
                    new_constraints.append(new_sql)
                continue

            # Check co-references linking removed ↔ non-removed tables
            m = coref_re.search(sql)
            if m:
                a_al, a_col, b_al, b_col = (
                    m.group(1), m.group(2), m.group(3), m.group(4)
                )
                if a_al in removed_aliases and b_al in removed_aliases:
                    # Both sides removed — emit if they remap to
                    # DIFFERENT targets (cross-hop connections like
                    # femv1.source_entity_uuid = femv0.dest_entity_uuid)
                    new_a_mv, a_cm = alias_map[a_al]
                    new_b_mv, b_cm = alias_map[b_al]
                    new_a_col = a_cm.get(a_col)
                    new_b_col = b_cm.get(b_col)
                    if (new_a_col and new_b_col
                            and (new_a_mv, new_a_col) != (new_b_mv, new_b_col)):
                        new_sql = f"{new_a_mv}.{new_a_col} = {new_b_mv}.{new_b_col}"
                        dup_key = f"{new_a_mv}.{new_a_col}={new_b_mv}.{new_b_col}"
                        if dup_key not in seen_ctx:
                            seen_ctx.add(dup_key)
                            new_tagged.append((new_a_mv, new_sql))
                            new_constraints.append(new_sql)
                elif a_al in removed_aliases and b_al not in removed_aliases:
                    new_mv, col_map = alias_map[a_al]
                    new_col = col_map.get(a_col)
                    if new_col:
                        new_sql = f"{new_mv}.{new_col} = {b_al}.{b_col}"
                        dup_key = f"{new_mv}.{new_col}={b_al}.{b_col}"
                        if dup_key not in seen_ctx:
                            seen_ctx.add(dup_key)
                            new_tagged.append((new_mv, new_sql))
                            new_constraints.append(new_sql)
                elif b_al in removed_aliases and a_al not in removed_aliases:
                    new_mv, col_map = alias_map[b_al]
                    new_col = col_map.get(b_col)
                    if new_col:
                        new_sql = f"{a_al}.{a_col} = {new_mv}.{new_col}"
                        dup_key = f"{new_mv}.{new_col}={a_al}.{a_col}"
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
