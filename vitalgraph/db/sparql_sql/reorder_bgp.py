"""BGP join reordering — dependency graph + predicate cardinality stats.

Ported from v1's jena_sql_emit._reorder_joins() for the v2 pipeline.

SPARQL triple patterns may produce disconnected "islands" (e.g. slot
properties listed before the edge that connects them to the frame).
Without reordering, these become cartesian products via JOIN ... ON TRUE.

The algorithm:
1. Parse each tagged constraint to find which *other* aliases it references.
2. Pick the best chain root: prefer text-filter (ILIKE) tables as the
   most selective anchor.  Falls back to quad_tables[0].
3. Greedy placement (dependency graph traversal): repeatedly pick the
   remaining table with the most constraints connecting it to
   already-placed tables.  When connectivity scores are tied, use
   predicate cardinality stats as a tiebreaker (prefer lower cardinality).
4. Assign each constraint to the ON clause of the *last-placed* alias
   among all aliases it involves (so all references are already in scope).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from .ir import PlanV2, TableRef

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'::uuid")


def reorder_joins(
    quad_tables: List[TableRef],
    tagged_constraints: List[Tuple[str, str]],
    quad_stats: Optional[Dict[Tuple[str, str], int]] = None,
    pred_stats: Optional[Dict[str, int]] = None,
    leaf_cardinality: Optional[Dict[str, float]] = None,
) -> Tuple[List[TableRef], Dict[str, List[str]], List[str]]:
    """Reorder quad tables so every JOIN references an already-placed table.

    Returns (ordered_tables, on_map, first_conds):
        ordered_tables: list of TableRef in optimised order
        on_map: dict  alias -> [sql conditions] for JOIN ON clauses
        first_conds: list of sql conditions for the first table (WHERE)

    `leaf_cardinality` is alias -> row count, supplied by the caller from
    `plan.leaf_terms` — the STRUCTURAL record made at collect time. Prefer it.

    Without it this falls back to deriving cardinality by regex-parsing the
    constraint SQL, which cannot read the shape this pipeline emits: the object
    branch requires the constant to sit in a constraint referencing no other
    alias, and a KGQuery emits `q7.subject_uuid = mv0.dest_node_uuid AND
    q7.predicate_uuid = '...' AND q7.object_uuid = '...'` as ONE string. So
    `refs` is non-empty, the branch is skipped, and NO leaf gets a pair count —
    every selectivity decision below then runs on infinity, and the chain root
    falls through to whatever was listed first. Measured: the same two criteria
    in opposite order produced the same 20-table join order and differed 8x,
    purely by which end the scan started from (`issues/061`).

    Connectivity is still read from the SQL, and correctly — the join graph IS
    the constraint text. Only the cardinality was being recovered from a place
    that does not reliably hold it.
    """
    if not quad_tables:
        return quad_tables, {}, []
    if len(quad_tables) == 1:
        conds = [sql for _, sql in tagged_constraints]
        return quad_tables, {}, conds

    quad_stats = quad_stats or {}
    pred_stats = pred_stats or {}

    all_aliases = {t.alias for t in quad_tables}
    alias_to_table = {t.alias: t for t in quad_tables}

    # Parse each constraint: (owner_alias, sql, other_aliases_referenced)
    parsed = []
    for owner, sql in tagged_constraints:
        refs = {a for a in all_aliases if a != owner and f"{a}." in sql}
        parsed.append((owner, sql, refs))

    # --- Pre-compute per-table cardinality and fingerprint ---
    _INF = float('inf')
    cardinality: Dict[str, float] = {}
    fingerprint: Dict[str, str] = {}

    for alias in all_aliases:
        pred_uuid = obj_uuid = None
        coref_cols: List[str] = []
        self_parts: List[str] = []
        for owner, sql, refs in parsed:
            if owner != alias:
                continue
            if f"{alias}.predicate_uuid = " in sql:
                m = _UUID_RE.search(sql)
                if m:
                    pred_uuid = m.group(1)
                    self_parts.append(f"p={pred_uuid}")
            elif f"{alias}.object_uuid = " in sql and not refs:
                m = _UUID_RE.search(sql)
                if m:
                    obj_uuid = m.group(1)
                    self_parts.append(f"o={obj_uuid}")
            if refs:
                for col in ("subject_uuid", "object_uuid"):
                    if f"{alias}.{col}" in sql:
                        coref_cols.append(col)

        fingerprint[alias] = "|".join(sorted(self_parts) + sorted(coref_cols))

        if leaf_cardinality is not None and alias in leaf_cardinality:
            cardinality[alias] = leaf_cardinality[alias]
        elif quad_stats or pred_stats:
            if pred_uuid and obj_uuid:
                card = quad_stats.get((pred_uuid, obj_uuid))
                if card is not None:
                    cardinality[alias] = card
                    continue
            if pred_uuid:
                card = pred_stats.get(pred_uuid)
                if card is not None:
                    cardinality[alias] = card

    # --- Pick chain root ---
    first = quad_tables[0]
    ilike_alias = None
    for owner, sql, refs in parsed:
        if not refs and ("LIKE" in sql or "ILIKE" in sql
                         or "~*" in sql or "~ '" in sql):
            ilike_alias = owner
            break

    # A TEXT-FILTER ANCHOR WINS OUTRIGHT, ahead of any row count. That is the
    # original hardcoded rule and it stays: a LIKE / ILIKE / regex leaf is served
    # by the GIN trigram index, and its selectivity is not in `quad_stats` at all
    # because there is no constant object to key on. Ranking it by cardinality
    # would read it as UNKNOWN and place it last — exactly backwards for the one
    # leaf we know is cheap to enter. Cardinality is consulted only when no such
    # anchor exists.
    if ilike_alias and ilike_alias in alias_to_table:
        first = alias_to_table[ilike_alias]
        logger.debug("Chain root: %s (text-filter anchor)", ilike_alias)
    elif cardinality:
        # The root is where the scan STARTS, so it decides how much every later
        # join carries. This used to be list position — for a KGQuery, the order
        # the CALLER wrote the criteria in. Ties keep list order, so a plan whose
        # leaves have no known counts is byte-identical to before.
        cheapest, rows = min(cardinality.items(), key=lambda kv: (kv[1], kv[0]))
        if rows < _INF and cheapest in alias_to_table:
            first = alias_to_table[cheapest]
            logger.debug("Chain root: %s (%s rows, cheapest leaf)", cheapest, rows)

    placed_order = [first]
    placed_set = {first.alias}
    remaining = [t.alias for t in quad_tables if t.alias != first.alias]

    # --- Greedy placement (dependency graph traversal) ---
    while remaining:
        best_alias = None
        best_score = (-1, _INF, "")  # (connectivity, -cardinality, fingerprint)

        for alias in remaining:
            conn = 0
            for owner, sql, refs in parsed:
                involved = {owner} | refs
                if alias in involved:
                    others = involved - {alias}
                    if others and others <= placed_set:
                        conn += 1

            card = cardinality.get(alias, _INF)
            fp = fingerprint.get(alias, "")
            score = (conn, -card, fp)
            if score > best_score:
                best_score = score
                best_alias = alias

        if best_alias is None:
            best_alias = remaining[0]

        remaining.remove(best_alias)
        placed_order.append(alias_to_table[best_alias])
        placed_set.add(best_alias)

    # --- Assign constraints to ON clauses ---
    placement_rank = {t.alias: i for i, t in enumerate(placed_order)}
    on_map: Dict[str, List[str]] = {}

    for owner, sql, refs in parsed:
        involved = ({owner} | refs) & all_aliases
        latest = max(involved, key=lambda a: placement_rank[a])
        on_map.setdefault(latest, []).append(sql)

    first_alias = placed_order[0].alias
    first_conds = on_map.pop(first_alias, [])

    return placed_order, on_map, first_conds
