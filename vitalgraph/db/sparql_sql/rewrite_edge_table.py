"""Edge table rewrite for v2 IR — replaces hasEdgeSource + hasEdgeDestination
quad pairs with a single edge table lookup.

The edge table collapses the two-quad pattern:
    ?edge <hasEdgeSource>      ?sourceNode .
    ?edge <hasEdgeDestination> ?destNode .

into a single table:
    {space}_edge(edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)

This eliminates 1 quad JOIN per edge pair (2 quads → 1 edge row).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from .ir import PlanV2, TableRef, AliasGenerator, KIND_BGP

logger = logging.getLogger(__name__)

EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST_URI = "http://vital.ai/ontology/vital-core#hasEdgeDestination"

_PRED_RE = re.compile(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(c_\d+)__")
_COREF_RE = re.compile(r"(\w+)\.subject_uuid\s*=\s*(\w+)\.subject_uuid")


def rewrite_edge_table(plan: PlanV2, aliases: AliasGenerator,
                       space_id: str) -> PlanV2:
    """Rewrite a v2 plan to use the edge table where possible.

    Detects pairs of quad tables where one has predicate = hasEdgeSource
    and the other has predicate = hasEdgeDestination, sharing the same
    subject variable. Replaces each pair with a single edge TableRef.
    """
    if plan.kind != KIND_BGP or not plan.tables:
        for i, child in enumerate(plan.children):
            plan.children[i] = rewrite_edge_table(child, aliases, space_id)
        return plan

    edge_table_name = f"{space_id}_edge"

    # Build reverse constant map: const_alias → URI text
    const_to_uri: Dict[str, str] = {}
    for (text, ttype), col_alias in aliases.constants.items():
        if ttype == "U":
            const_to_uri[col_alias] = text

    # Find quad tables with hasEdgeSource or hasEdgeDestination predicates
    src_quads: Dict[str, str] = {}  # quad_alias → constant_alias
    dst_quads: Dict[str, str] = {}

    for owner, sql in plan.tagged_constraints:
        m = _PRED_RE.search(sql)
        if not m:
            continue
        quad_alias = m.group(1)
        const_alias = m.group(2)
        uri = const_to_uri.get(const_alias, "")
        if uri == EDGE_SOURCE_URI:
            src_quads[quad_alias] = const_alias
        elif uri == EDGE_DEST_URI:
            dst_quads[quad_alias] = const_alias

    if not src_quads or not dst_quads:
        logger.info("rewrite_edge_table: no edge pairs found in BGP. "
                    "src_quads=%s, dst_quads=%s, const_to_uri has %d URIs, "
                    "tagged_constraints=%d",
                    src_quads, dst_quads, len(const_to_uri),
                    len(plan.tagged_constraints))
        if not const_to_uri:
            logger.info("rewrite_edge_table: constant map is empty — constants: %s",
                        dict(list(aliases.constants.items())[:10]))
        return plan

    # Find co-reference pairs: src and dst sharing same subject_uuid
    pairs: List[Tuple[str, str]] = []  # (src_alias, dst_alias)
    used_src: Set[str] = set()
    used_dst: Set[str] = set()

    # Method 1: Explicit constraints (qA.subject_uuid = qB.subject_uuid)
    for owner, sql in plan.tagged_constraints:
        m = _COREF_RE.search(sql)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        if a in dst_quads and b in src_quads and a not in used_dst and b not in used_src:
            pairs.append((b, a))
            used_src.add(b)
            used_dst.add(a)
        elif a in src_quads and b in dst_quads and a not in used_src and b not in used_dst:
            pairs.append((a, b))
            used_src.add(a)
            used_dst.add(b)

    # Method 2: var_slots transitive co-reference detection.
    # When a vitaltype triple precedes the edge pair, the co-reference
    # constraints chain through the vitaltype quad (e.g. q2→q1, q3→q1)
    # rather than directly between src and dst (q3→q2).  var_slots
    # records ALL positions of a shared variable, so we can find the
    # src/dst pair regardless of which quad introduced the variable first.
    remaining_src = set(src_quads) - used_src
    remaining_dst = set(dst_quads) - used_dst
    if remaining_src and remaining_dst and plan.var_slots:
        for var_name, slot in plan.var_slots.items():
            src_hit = None
            dst_hit = None
            for ref_id, col_name in slot.positions:
                if col_name == "subject_uuid":
                    if ref_id in src_quads and ref_id not in used_src:
                        src_hit = ref_id
                    elif ref_id in dst_quads and ref_id not in used_dst:
                        dst_hit = ref_id
            if src_hit and dst_hit:
                pairs.append((src_hit, dst_hit))
                used_src.add(src_hit)
                used_dst.add(dst_hit)
                logger.info("rewrite_edge_table: var_slots co-ref ?%s: "
                            "%s(src) + %s(dst)", var_name, src_hit, dst_hit)

    if not pairs:
        logger.info("rewrite_edge_table: found src/dst quads but no co-reference pairs. "
                    "src=%s, dst=%s", src_quads, dst_quads)
        return plan

    logger.info("Edge table rewrite: found %d edge pair(s) to replace", len(pairs))

    # Build alias_map: old_quad_alias → (edge_alias, {old_col → new_col})
    alias_map: Dict[str, Tuple[str, Dict[str, Optional[str]]]] = {}
    new_edge_tables: List[TableRef] = []
    removed_aliases: Set[str] = set()

    for src_alias, dst_alias in pairs:
        edge_alias = aliases.next("mv")
        new_edge_tables.append(TableRef(
            ref_id=edge_alias, kind="edge",
            table_name=edge_table_name, alias=edge_alias,
        ))

        alias_map[src_alias] = (edge_alias, {
            "subject_uuid": "edge_uuid",
            "object_uuid": "source_node_uuid",
            "predicate_uuid": None,
            "context_uuid": "context_uuid",
        })
        alias_map[dst_alias] = (edge_alias, {
            "subject_uuid": "edge_uuid",
            "object_uuid": "dest_node_uuid",
            "predicate_uuid": None,
            "context_uuid": "context_uuid",
        })
        removed_aliases.add(src_alias)
        removed_aliases.add(dst_alias)

    # --- Rewrite tables ---
    new_tables = []
    for t in plan.tables:
        if t.alias in removed_aliases:
            continue
        if t.kind == "term" and t.join_col:
            t.join_col = _remap_col_ref(t.join_col, alias_map)
        new_tables.append(t)
    plan.tables = new_edge_tables + new_tables

    # --- Rewrite variable positions ---
    seen_edge_positions: Set[Tuple[str, str]] = set()
    for var_name, slot in plan.var_slots.items():
        new_positions = []
        for ref_id, col_name in slot.positions:
            if ref_id in alias_map:
                edge_alias, col_map = alias_map[ref_id]
                new_col = col_map.get(col_name)
                if new_col is None:
                    continue
                pos_key = (edge_alias, new_col)
                if pos_key not in seen_edge_positions:
                    new_positions.append(pos_key)
                    seen_edge_positions.add(pos_key)
            else:
                new_positions.append((ref_id, col_name))
        slot.positions = new_positions
    plan.var_slots = {k: v for k, v in plan.var_slots.items() if v.positions}

    # --- Rewrite constraints ---
    new_constraints = []
    new_tagged = []
    seen_ctx: Set[str] = set()
    seen_sql: Set[str] = set()  # general dedup for remapped constraints

    for owner, sql in plan.tagged_constraints:
        # Remove predicate constraints for removed quads
        if owner in removed_aliases and ".predicate_uuid" in sql:
            continue
        # Remove co-reference constraints between paired quads
        m = _COREF_RE.search(sql)
        if m:
            a, b = m.group(1), m.group(2)
            if a in removed_aliases and b in removed_aliases:
                continue

        # Remap column references
        new_sql = _remap_constraint_sql(sql, alias_map)
        new_owner = owner
        if owner in alias_map:
            new_owner = alias_map[owner][0]

        # Deduplicate context_uuid constraints on the same edge table
        if ".context_uuid" in new_sql:
            ctx_key = f"{new_owner}:{new_sql}"
            if ctx_key in seen_ctx:
                continue
            seen_ctx.add(ctx_key)

        # General dedup: after remapping, multiple removed quads can
        # produce identical constraints (e.g. both src and dst co-ref
        # to the same vitaltype quad → same edge.edge_uuid = qN.subject_uuid)
        if new_sql in seen_sql:
            continue
        seen_sql.add(new_sql)

        new_tagged.append((new_owner, new_sql))
        new_constraints.append(new_sql)

    plan.tagged_constraints = new_tagged
    plan.constraints = new_constraints

    return plan


def _remap_col_ref(col_ref: str, alias_map: Dict) -> str:
    """Remap a column reference like 'q5.object_uuid' using alias_map."""
    parts = col_ref.split(".")
    if len(parts) != 2:
        return col_ref
    alias, col = parts
    if alias not in alias_map:
        return col_ref
    edge_alias, col_map = alias_map[alias]
    new_col = col_map.get(col, col)
    if new_col is None:
        return col_ref
    return f"{edge_alias}.{new_col}"


def _remap_constraint_sql(sql: str, alias_map: Dict) -> str:
    """Remap all alias.column references in a constraint SQL string."""
    result = sql
    for old_alias, (edge_alias, col_map) in alias_map.items():
        for old_col, new_col in col_map.items():
            if new_col is None:
                continue
            result = result.replace(f"{old_alias}.{old_col}", f"{edge_alias}.{new_col}")
    return result
