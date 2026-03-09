"""Incremental and full sync for the {space}_rdf_pred_stats and {space}_rdf_stats tables.

These tables drive the join reorder heuristic in the v2 SPARQL-to-SQL
generator.  They must stay fresh as data changes through the REST API.

Incremental functions accept an asyncpg connection already inside a
transaction.  The resync function can be called standalone.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


async def sync_stats_after_insert(
    conn,
    space_id: str,
    quad_rows: List[Tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]],
) -> int:
    """After quads are inserted, increment predicate and pred+object stats.

    quad_rows: list of (subject_uuid, predicate_uuid, object_uuid, context_uuid).
    Returns total stats rows upserted.
    """
    if not quad_rows:
        return 0

    t_pred = f"{space_id}_rdf_pred_stats"
    t_stats = f"{space_id}_rdf_stats"

    # Count occurrences per predicate and per (predicate, object)
    pred_counts: Counter = Counter()
    po_counts: Counter = Counter()
    for _s, p, o, _g in quad_rows:
        pred_counts[p] += 1
        po_counts[(p, o)] += 1

    # Upsert predicate stats
    upserted = 0
    await conn.executemany(
        f"INSERT INTO {t_pred} (predicate_uuid, row_count) "
        f"VALUES ($1, $2) "
        f"ON CONFLICT (predicate_uuid) "
        f"DO UPDATE SET row_count = {t_pred}.row_count + EXCLUDED.row_count",
        [(p, cnt) for p, cnt in pred_counts.items()],
    )
    upserted += len(pred_counts)

    # Upsert predicate+object stats
    await conn.executemany(
        f"INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count) "
        f"VALUES ($1, $2, $3) "
        f"ON CONFLICT (predicate_uuid, object_uuid) "
        f"DO UPDATE SET row_count = {t_stats}.row_count + EXCLUDED.row_count",
        [(p, o, cnt) for (p, o), cnt in po_counts.items()],
    )
    upserted += len(po_counts)

    logger.debug("sync_stats_after_insert(%s): %d pred + %d po upserts",
                 space_id, len(pred_counts), len(po_counts))
    return upserted


async def sync_stats_after_delete(
    conn,
    space_id: str,
    quad_rows: List[Tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]],
) -> int:
    """After quads are deleted, decrement predicate and pred+object stats.

    quad_rows: list of (subject_uuid, predicate_uuid, object_uuid, context_uuid).
    Decrements counts, flooring at 0.  Returns total rows updated.
    """
    if not quad_rows:
        return 0

    t_pred = f"{space_id}_rdf_pred_stats"
    t_stats = f"{space_id}_rdf_stats"

    pred_counts: Counter = Counter()
    po_counts: Counter = Counter()
    for _s, p, o, _g in quad_rows:
        pred_counts[p] += 1
        po_counts[(p, o)] += 1

    updated = 0
    await conn.executemany(
        f"UPDATE {t_pred} "
        f"SET row_count = GREATEST(0, row_count - $2) "
        f"WHERE predicate_uuid = $1",
        [(p, cnt) for p, cnt in pred_counts.items()],
    )
    updated += len(pred_counts)

    await conn.executemany(
        f"UPDATE {t_stats} "
        f"SET row_count = GREATEST(0, row_count - $3) "
        f"WHERE predicate_uuid = $1 AND object_uuid = $2",
        [(p, o, cnt) for (p, o), cnt in po_counts.items()],
    )
    updated += len(po_counts)

    logger.debug("sync_stats_after_delete(%s): %d pred + %d po decrements",
                 space_id, len(pred_counts), len(po_counts))
    return updated


async def sync_stats_for_deleted_subjects(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: uuid.UUID = None,
) -> int:
    """Before quads for subjects are deleted, fetch their pred+object pairs
    and decrement stats.  Used by delete_entity_graph_bulk.

    Returns total stats rows updated.
    """
    if not subject_uuids:
        return 0

    t_quad = f"{space_id}_rdf_quad"

    # Fetch the quads that are about to be deleted
    if context_uuid:
        rows = await conn.fetch(
            f"SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid "
            f"FROM {t_quad} WHERE subject_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid,
        )
    else:
        rows = await conn.fetch(
            f"SELECT subject_uuid, predicate_uuid, object_uuid, context_uuid "
            f"FROM {t_quad} WHERE subject_uuid = ANY($1)",
            subject_uuids,
        )

    if not rows:
        return 0

    quad_rows = [(r['subject_uuid'], r['predicate_uuid'],
                  r['object_uuid'], r['context_uuid']) for r in rows]
    return await sync_stats_after_delete(conn, space_id, quad_rows)


async def resync_stats_tables(conn, space_id: str) -> Dict[str, int]:
    """Rebuild both stats tables from scratch by scanning rdf_quad.

    Truncates and repopulates both tables.  Runs ANALYZE afterwards.
    Returns {'pred_stats': N, 'quad_stats': M}.
    """
    t_quad = f"{space_id}_rdf_quad"
    t_pred = f"{space_id}_rdf_pred_stats"
    t_stats = f"{space_id}_rdf_stats"

    # Predicate cardinality
    await conn.execute(f"TRUNCATE {t_pred}")
    result = await conn.execute(f"""
        INSERT INTO {t_pred} (predicate_uuid, row_count)
        SELECT predicate_uuid, COUNT(*)
        FROM {t_quad}
        GROUP BY predicate_uuid
    """)
    pred_count = int(result.split()[-1]) if result else 0

    # Predicate+object co-occurrence (cap at 200k to exclude extremely common pairs)
    await conn.execute(f"TRUNCATE {t_stats}")
    result = await conn.execute(f"""
        INSERT INTO {t_stats} (predicate_uuid, object_uuid, row_count)
        SELECT predicate_uuid, object_uuid, COUNT(*)
        FROM {t_quad}
        GROUP BY predicate_uuid, object_uuid
        HAVING COUNT(*) <= 200000
    """)
    stats_count = int(result.split()[-1]) if result else 0

    await conn.execute(f"ANALYZE {t_pred}")
    await conn.execute(f"ANALYZE {t_stats}")

    logger.info("resync_stats_tables(%s): %d pred_stats, %d quad_stats",
                space_id, pred_count, stats_count)
    return {'pred_stats': pred_count, 'quad_stats': stats_count}
