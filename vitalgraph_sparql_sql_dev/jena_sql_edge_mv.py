"""
Edge MV optimization pass — replaces hasEdgeSource + hasEdgeDestination
quad pairs with a single lookup on a pre-computed materialized view.

The edge MV collapses the two-quad pattern:
    ?edge <hasEdgeSource>      ?sourceNode .
    ?edge <hasEdgeDestination> ?destNode .

into a single table:
    {space}_edge_mv(edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)

This eliminates 1 quad JOIN per edge pair (2 quads → 1 MV row).
For a 4-hop multi-hop query with 8 edge pairs, this saves 8 JOINs.

Architecture:
    - ensure_edge_mv():  DDL — create/refresh the MV if missing
    - rewrite_edge_mv(): Plan rewrite — detect edge pairs, replace in IR
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from .jena_sql_ir import AliasGenerator, TableRef, VarSlot, RelationPlan

logger = logging.getLogger(__name__)

# The two predicates that define edge structure
EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST_URI = "http://vital.ai/ontology/vital-core#hasEdgeDestination"

# Column mapping: quad column → MV column
_COL_MAP = {
    "subject_uuid": "edge_uuid",
    # object_uuid mapping depends on whether it's the source or dest quad
}


# ===========================================================================
# DDL: ensure the edge MV exists
# ===========================================================================

def ensure_edge_mv(space_id: str, conn=None, conn_params=None) -> bool:
    """Create the edge MV if it doesn't exist.  Returns True if MV is usable."""
    from . import db

    mv_name = f"{space_id}_edge_mv"
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    # Check if MV already exists
    try:
        rows = db.execute_query(
            "SELECT 1 FROM pg_matviews WHERE matviewname = %s",
            params=(mv_name,), conn=conn, conn_params=conn_params,
        )
        if rows:
            logger.debug("Edge MV %s already exists", mv_name)
            return True
    except Exception as e:
        logger.debug("Error checking edge MV: %s", e)
        return False

    # Create the MV
    logger.info("Creating edge MV %s ...", mv_name)
    ddl = f"""
    CREATE MATERIALIZED VIEW {mv_name} AS
    SELECT
        src.subject_uuid  AS edge_uuid,
        src.object_uuid   AS source_node_uuid,
        dst.object_uuid   AS dest_node_uuid,
        src.context_uuid  AS context_uuid
    FROM {quad_table} src
    JOIN {quad_table} dst
        ON dst.subject_uuid = src.subject_uuid
        AND dst.context_uuid = src.context_uuid
    WHERE src.predicate_uuid = (
        SELECT term_uuid FROM {term_table}
        WHERE term_text = '{EDGE_SOURCE_URI}' AND term_type = 'U' LIMIT 1
    )
    AND dst.predicate_uuid = (
        SELECT term_uuid FROM {term_table}
        WHERE term_text = '{EDGE_DEST_URI}' AND term_type = 'U' LIMIT 1
    )
    """

    idx_prefix = f"idx_{space_id}_edge_mv"
    indexes = [
        # Forward traversal: given source, find dest (frame → slot)
        f"CREATE INDEX {idx_prefix}_src_dst "
        f"ON {mv_name} (source_node_uuid, dest_node_uuid)",
        # Reverse traversal: given dest, find source (slot → frame)
        f"CREATE INDEX {idx_prefix}_dst_src "
        f"ON {mv_name} (dest_node_uuid, source_node_uuid)",
        # Edge-centric lookup: when other triples reference the edge entity
        f"CREATE INDEX {idx_prefix}_edge "
        f"ON {mv_name} (edge_uuid)",
    ]

    try:
        with db.get_connection(params=conn_params) as c:
            with c.cursor() as cur:
                cur.execute(ddl)
                for idx_sql in indexes:
                    cur.execute(idx_sql)
            c.commit()

        # Get stats
        rows = db.execute_query(
            f"SELECT COUNT(*) as cnt FROM {mv_name}",
            conn=conn, conn_params=conn_params,
        )
        cnt = rows[0]["cnt"] if rows else 0
        logger.info("Edge MV %s created with %d rows and 3 indexes", mv_name, cnt)
        return True

    except Exception as e:
        logger.warning("Failed to create edge MV %s: %s", mv_name, e)
        return False


# ===========================================================================
# Plan rewrite: detect edge pairs and replace with MV references
# ===========================================================================

def rewrite_edge_mv(plan: RelationPlan, aliases: AliasGenerator,
                    space_id: str) -> RelationPlan:
    """Rewrite a plan to use the edge MV where possible.

    Detects pairs of quad tables where:
      - One has predicate = hasEdgeSource
      - The other has predicate = hasEdgeDestination
      - They share the same subject variable (via co-reference constraint)

    Replaces each pair with a single edge_mv TableRef and remaps all
    variable positions and constraints accordingly.
    """
    if plan.kind != "bgp" or not plan.tables:
        # Recurse into children
        for i, child in enumerate(plan.children):
            plan.children[i] = rewrite_edge_mv(child, aliases, space_id)
        return plan

    mv_name = f"{space_id}_edge_mv"

    # Build reverse constant map: alias → URI text
    const_to_uri: Dict[str, str] = {}
    for (text, ttype), col_alias in aliases.constants.items():
        if ttype == "U":
            const_to_uri[col_alias] = text

    # Find quad tables with hasEdgeSource or hasEdgeDestination predicates
    # by scanning tagged_constraints for predicate_uuid = {{c_X}} patterns
    src_quads: Dict[str, str] = {}  # quad_alias → constant_alias
    dst_quads: Dict[str, str] = {}  # quad_alias → constant_alias

    pred_re = re.compile(r"(\w+)\.predicate_uuid\s*=\s*__CONST_(c_\d+)__")

    for owner, sql in plan.tagged_constraints:
        m = pred_re.search(sql)
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
        return plan

    # Find co-reference pairs: src_quad and dst_quad sharing the same subject
    # Co-reference constraint looks like: "qY.subject_uuid = qX.subject_uuid"
    coref_re = re.compile(r"(\w+)\.subject_uuid\s*=\s*(\w+)\.subject_uuid")

    pairs: List[Tuple[str, str]] = []  # (src_alias, dst_alias)
    used_src: Set[str] = set()
    used_dst: Set[str] = set()

    for owner, sql in plan.tagged_constraints:
        m = coref_re.search(sql)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        # Check both orderings: a=src,b=dst or a=dst,b=src
        if a in dst_quads and b in src_quads and a not in used_dst and b not in used_src:
            pairs.append((b, a))  # (src, dst)
            used_src.add(b)
            used_dst.add(a)
        elif a in src_quads and b in dst_quads and a not in used_src and b not in used_dst:
            pairs.append((a, b))  # (src, dst)
            used_src.add(a)
            used_dst.add(b)

    if not pairs:
        return plan

    logger.debug("Edge MV rewrite: found %d edge pair(s) to replace", len(pairs))

    # For each pair, create an MV table and remap
    alias_map: Dict[str, Tuple[str, Dict[str, str]]] = {}
    # alias_map: old_quad_alias → (mv_alias, {old_col → new_col})

    new_mv_tables: List[TableRef] = []
    removed_aliases: Set[str] = set()

    for src_alias, dst_alias in pairs:
        mv_alias = aliases.next("mv")
        new_mv_tables.append(TableRef(
            ref_id=mv_alias, kind="edge_mv",
            table_name=mv_name, alias=mv_alias,
        ))

        # Column remapping for the source quad (hasEdgeSource)
        alias_map[src_alias] = (mv_alias, {
            "subject_uuid": "edge_uuid",
            "object_uuid": "source_node_uuid",
            "predicate_uuid": None,  # remove — implicit in MV
            "context_uuid": "context_uuid",
        })
        # Column remapping for the destination quad (hasEdgeDestination)
        alias_map[dst_alias] = (mv_alias, {
            "subject_uuid": "edge_uuid",
            "object_uuid": "dest_node_uuid",
            "predicate_uuid": None,  # remove — implicit in MV
            "context_uuid": "context_uuid",
        })
        removed_aliases.add(src_alias)
        removed_aliases.add(dst_alias)

    # --- Rewrite tables ---
    new_tables = []
    for t in plan.tables:
        if t.alias in removed_aliases:
            continue
        # Update term table join_col if it references a removed quad
        if t.kind == "term" and t.join_col:
            t.join_col = _remap_col_ref(t.join_col, alias_map)
        new_tables.append(t)
    plan.tables = new_mv_tables + new_tables

    # --- Rewrite variable positions ---
    seen_mv_positions: Set[Tuple[str, str]] = set()
    for var_name, slot in plan.var_slots.items():
        new_positions = []
        for ref_id, col_name in slot.positions:
            if ref_id in alias_map:
                mv_alias, col_map = alias_map[ref_id]
                new_col = col_map.get(col_name)
                if new_col is None:
                    continue  # predicate_uuid — skip
                pos_key = (mv_alias, new_col)
                if pos_key not in seen_mv_positions:
                    new_positions.append(pos_key)
                    seen_mv_positions.add(pos_key)
            else:
                new_positions.append((ref_id, col_name))
        slot.positions = new_positions
    plan.var_slots = {k: v for k, v in plan.var_slots.items() if v.positions}

    # --- Rewrite constraints ---
    new_constraints = []
    new_tagged = []
    seen_ctx: Set[str] = set()  # track context constraints per MV to avoid duplicates

    for owner, sql in plan.tagged_constraints:
        # Remove predicate constraints for removed quads
        if owner in removed_aliases and ".predicate_uuid" in sql:
            continue
        # Remove co-reference constraints between paired quads
        m = coref_re.search(sql)
        if m:
            a, b = m.group(1), m.group(2)
            if a in removed_aliases and b in removed_aliases:
                continue

        # Remap column references in the SQL
        new_sql = _remap_constraint_sql(sql, alias_map)
        new_owner = owner
        if owner in alias_map:
            new_owner = alias_map[owner][0]

        # Deduplicate context_uuid constraints on the same MV
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


def _remap_col_ref(col_ref: str, alias_map: Dict) -> str:
    """Remap a column reference like 'q5.object_uuid' using alias_map."""
    parts = col_ref.split(".")
    if len(parts) != 2:
        return col_ref
    alias, col = parts
    if alias not in alias_map:
        return col_ref
    mv_alias, col_map = alias_map[alias]
    new_col = col_map.get(col, col)
    if new_col is None:
        return col_ref
    return f"{mv_alias}.{new_col}"


def _remap_constraint_sql(sql: str, alias_map: Dict) -> str:
    """Remap all alias.column references in a constraint SQL string."""
    result = sql
    for old_alias, (mv_alias, col_map) in alias_map.items():
        for old_col, new_col in col_map.items():
            if new_col is None:
                continue
            result = result.replace(f"{old_alias}.{old_col}", f"{mv_alias}.{new_col}")
    return result
