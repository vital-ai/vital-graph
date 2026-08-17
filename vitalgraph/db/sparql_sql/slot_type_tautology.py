"""Is a slot TYPE constraint able to exclude anything in this space?

`rewrite_frame_entity_table` absorbs `?slot a <T>` as a role-scoped semi-join back
through the edge, which is correct and costs three index probes per surviving
`frame_entity` row. With a criterion few rows survive and it is free; with none,
every row survives and it is the whole cost — 4.2x to 5.2x against the open walk
(`issues/048` Problem 4).

When no role slot in the space lacks `T`, the check cannot exclude anything and
can be dropped entirely. Measured worth: **7.4x**, 627,418 buffers to 84,573 on
identical rows.

WHY THIS IS A QUERY AND NOT AN ARGUMENT

`issues/048` twice proposed proving the redundancy by reasoning, and both were
wrong:

  * "a slot reached through `hasEntitySlotValue` from a `frame_entity` row IS a
    KGEntitySlot" — false. `sync_frame_entity_table` requires an edge, a
    source/dest role and `hasEntitySlotValue`, and never looks at the type.
  * comparing `rdf_stats` counts — necessary, not sufficient. On
    `sp_graph_skew_2k` the counts matched exactly while the conclusion was still
    unproven; two sets of equal size are not the same set.

So it is answered by an anti-join against the data, per space, and the counts are
used only as a free pre-filter.

STALENESS. A write can introduce the first differently-typed role slot at any
time, and then a dropped check returns rows that should have been excluded —
wrong answers, not slow ones. The cache is therefore keyed by the predicate's
`rdf_pred_stats` row count, so it is discarded the moment the slot-type predicate
changes size. That is the same freshness signal `sync_value_stats` uses, and it
is deliberately conservative: a write that leaves the count unchanged (an update
in place) will not invalidate it, so the cache is only sound for a space whose
slot types are append-mostly. Pass `enabled=False` to switch the whole
optimisation off if that is ever not true.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# (space_id, type_uri, roles) -> (predicate_rows_when_computed, excludes_nothing)
_CACHE: dict = {}

SLOT_TYPE_URI = "http://vital.ai/ontology/haley-ai-kg#hasKGSlotType"
VITALTYPE_URI = "http://vital.ai/ontology/vital-core#vitaltype"
RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def clear_cache() -> None:
    _CACHE.clear()


async def excludes_nothing(space_id: str, type_uri: str, roles: tuple,
                           type_predicate: str, conn) -> Optional[bool]:
    """True when NO role slot in this space lacks `type_uri`.

    None when it cannot be answered — no connection, a term missing, a failed
    query. None must be treated as "keep the check": the whole risk here is
    dropping a constraint that does exclude something.
    """
    if conn is None or not roles:
        return None
    key = (space_id, type_uri, tuple(sorted(roles)), type_predicate)

    try:
        pred_rows = await conn.fetchval(
            f"""SELECT s.row_count FROM {space_id}_rdf_pred_stats s
                JOIN {space_id}_term t ON t.term_uuid = s.predicate_uuid
                WHERE t.term_text = $1""", SLOT_TYPE_URI)
    except Exception as exc:
        logger.debug("slot-type tautology: pred stat lookup failed: %s", exc)
        return None

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == pred_rows:
        return cached[1]

    placeholders = ", ".join(f"${i + 3}" for i in range(len(roles)))
    try:
        row = await conn.fetchval(
            f"""SELECT count(*) FROM (
                  SELECT 1 FROM {space_id}_rdf_quad q
                  JOIN {space_id}_term p ON p.term_uuid = q.predicate_uuid
                   AND p.term_text = $1
                  JOIN {space_id}_term o ON o.term_uuid = q.object_uuid
                   AND o.term_text IN ({placeholders})
                  WHERE NOT EXISTS (
                    SELECT 1 FROM {space_id}_rdf_quad ty
                    JOIN {space_id}_term tp ON tp.term_uuid = ty.predicate_uuid
                     AND tp.term_text = $2
                    JOIN {space_id}_term t2 ON t2.term_uuid = ty.object_uuid
                     AND t2.term_text = ${len(roles) + 3}
                    WHERE ty.subject_uuid = q.subject_uuid)
                  LIMIT 1) x""",
            SLOT_TYPE_URI, type_predicate, *roles, type_uri)
    except Exception as exc:
        logger.debug("slot-type tautology: anti-join failed: %s", exc)
        return None

    verdict = (row == 0)
    _CACHE[key] = (pred_rows, verdict)
    logger.info("slot-type tautology: %s %s over %s -> %s (%d counterexample(s))",
                space_id, type_uri, sorted(roles),
                "excludes nothing" if verdict else "EXCLUDES", row or 0)
    return verdict
