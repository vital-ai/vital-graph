"""Incremental sync for the {space}_edge table.

Called after quad inserts and before/after quad deletes to keep the edge
table in sync with rdf_quad.  All functions accept an asyncpg connection
that is already inside a transaction.
"""

from __future__ import annotations

import logging
import uuid
from typing import List, Optional

logger = logging.getLogger(__name__)

EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST_URI = "http://vital.ai/ontology/vital-core#hasEdgeDestination"

# Deterministic UUID namespace (same as sparql_sql_space_impl)
_VITALGRAPH_NS = uuid.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')

# Pre-computed predicate UUIDs (deterministic, never change)
_EDGE_SRC_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{EDGE_SOURCE_URI}\x00U")
_EDGE_DST_UUID = uuid.uuid5(_VITALGRAPH_NS, f"{EDGE_DEST_URI}\x00U")

# Cap the subject-array size per aux-sync statement. A bulk load can touch
# hundreds of thousands of subjects at once; passing them all as one ANY($)
# array makes a huge parameter and an unbounded self-join. Chunking keeps each
# statement's work bounded (per-write cost stays flat vs load size).
SYNC_CHUNK = 10_000


def chunk_uuids(seq: List[uuid.UUID], n: int = SYNC_CHUNK):
    """Yield successive n-sized slices of a UUID list."""
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


async def sync_edge_table_after_insert(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
) -> int:
    """After quads are inserted, find new edge pairs and insert into edge table.

    Scans only the given subject_uuids for hasEdgeSource + hasEdgeDestination
    pairs.  Returns the number of edge rows inserted.
    """
    if not subject_uuids:
        return 0

    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    inserted = 0
    for chunk in chunk_uuids(subject_uuids):
        result = await conn.execute(f"""
            INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
            SELECT
                src.subject_uuid,
                src.object_uuid,
                dst.object_uuid,
                src.context_uuid
            FROM {t_quad} src
            JOIN {t_quad} dst
                ON dst.subject_uuid = src.subject_uuid
                AND dst.context_uuid = src.context_uuid
            WHERE src.predicate_uuid = $1
              AND dst.predicate_uuid = $2
              AND src.subject_uuid = ANY($3)
            ON CONFLICT DO NOTHING
        """, _EDGE_SRC_UUID, _EDGE_DST_UUID, chunk)
        inserted += int(result.split()[-1]) if result else 0

    if inserted:
        logger.debug("sync_edge_table_after_insert(%s): %d edge rows", space_id, inserted)
    return inserted


async def sync_edge_table_before_delete(
    conn,
    space_id: str,
    subject_uuids: List[uuid.UUID],
    context_uuid: Optional[uuid.UUID] = None,
) -> int:
    """Before quads are deleted, remove corresponding edge table rows.

    Deletes edge rows where edge_uuid is in subject_uuids.
    If context_uuid is provided, scopes the delete to that graph.
    Returns the number of edge rows deleted.
    """
    if not subject_uuids:
        return 0

    t_edge = f"{space_id}_edge"

    if context_uuid:
        result = await conn.execute(
            f"DELETE FROM {t_edge} WHERE edge_uuid = ANY($1) AND context_uuid = $2",
            subject_uuids, context_uuid,
        )
    else:
        result = await conn.execute(
            f"DELETE FROM {t_edge} WHERE edge_uuid = ANY($1)",
            subject_uuids,
        )

    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.debug("sync_edge_table_before_delete(%s): %d edge rows", space_id, deleted)
    return deleted


async def cleanup_orphan_edges_for_subjects(conn, space_id: str,
                                            subjects: List[uuid.UUID]) -> int:
    """Remove edge rows (among the given edge_uuids) whose defining quads are
    gone — the delete-side counterpart of sync_edge_table_after_insert.

    An edge row is valid only while BOTH its hasEdgeSource and hasEdgeDestination
    quads exist. After a delete that removed one of them, the row is orphaned.
    Scoped to `subjects` (the edge_uuids the caller touched) so it stays cheap,
    and it only removes rows that are genuinely broken (so it's safe to pass any
    touched subject, edge or not). Returns rows deleted.
    """
    if not subjects:
        return 0
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    result = await conn.execute(f"""
        DELETE FROM {t_edge} e
        WHERE e.edge_uuid = ANY($3)
          AND (
            NOT EXISTS (
                SELECT 1 FROM {t_quad} s
                WHERE s.subject_uuid = e.edge_uuid AND s.predicate_uuid = $1
                  AND s.object_uuid = e.source_node_uuid
                  AND s.context_uuid = e.context_uuid)
            OR NOT EXISTS (
                SELECT 1 FROM {t_quad} d
                WHERE d.subject_uuid = e.edge_uuid AND d.predicate_uuid = $2
                  AND d.object_uuid = e.dest_node_uuid
                  AND d.context_uuid = e.context_uuid)
          )
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID, subjects)
    deleted = int(result.split()[-1]) if result else 0
    if deleted:
        logger.debug("cleanup_orphan_edges_for_subjects(%s): %d rows", space_id, deleted)
    return deleted


async def resync_edge_table(conn, space_id: str) -> int:
    """Rebuild {space}_edge from scratch by scanning rdf_quad.

    Truncates the edge table and repopulates it from hasEdgeSource +
    hasEdgeDestination quad pairs.  Runs ANALYZE afterwards.
    Returns the number of rows inserted.

    A well-formed edge has exactly one hasEdgeSource and one hasEdgeDestination
    per (edge_uuid, context).  Malformed edges with more than one of either
    would make the src×dst product collide on the (edge_uuid, context_uuid)
    primary key, so we de-duplicate with DISTINCT ON (keeping one arbitrary
    pair per edge) and warn — otherwise the INSERT aborts and, because TRUNCATE
    already ran, leaves the edge table empty.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    malformed = await conn.fetchval(f"""
        SELECT count(*) FROM (
            SELECT subject_uuid, context_uuid FROM {t_quad}
            WHERE predicate_uuid = ANY($1)
            GROUP BY subject_uuid, context_uuid, predicate_uuid
            HAVING count(*) > 1
        ) x
    """, [_EDGE_SRC_UUID, _EDGE_DST_UUID])
    if malformed:
        logger.warning(
            "resync_edge_table(%s): %d edges have >1 hasEdgeSource/hasEdgeDestination "
            "(malformed) — keeping one arbitrary pair each", space_id, malformed)

    await conn.execute(f"TRUNCATE {t_edge}")

    result = await conn.execute(f"""
        INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
        SELECT DISTINCT ON (src.subject_uuid, src.context_uuid)
            src.subject_uuid,
            src.object_uuid,
            dst.object_uuid,
            src.context_uuid
        FROM {t_quad} src
        JOIN {t_quad} dst
            ON dst.subject_uuid = src.subject_uuid
            AND dst.context_uuid = src.context_uuid
        WHERE src.predicate_uuid = $1
          AND dst.predicate_uuid = $2
        ORDER BY src.subject_uuid, src.context_uuid
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID)

    inserted = int(result.split()[-1]) if result else 0
    await conn.execute(f"ANALYZE {t_edge}")
    logger.info("resync_edge_table(%s): %d rows inserted", space_id, inserted)
    return inserted


async def backfill_edge_table(conn, space_id: str) -> int:
    """Add only the MISSING edges to {space}_edge — no TRUNCATE, no rebuild.

    Unlike resync_edge_table (which TRUNCATEs and holds ACCESS EXCLUSIVE on the
    edge table for the whole rebuild, blocking edge-rewrite queries), this is a
    plain INSERT ... ON CONFLICT DO NOTHING: it takes only ROW EXCLUSIVE, which
    does NOT conflict with concurrent readers, so edge-table queries keep
    running while it backfills.  Deletes are kept in sync separately
    (sync_edge_table_before_delete), so the table has no orphans to remove —
    drift is always *missing* edges, which this adds.  Returns rows inserted.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"

    result = await conn.execute(f"""
        INSERT INTO {t_edge} (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
        SELECT DISTINCT ON (src.subject_uuid, src.context_uuid)
            src.subject_uuid,
            src.object_uuid,
            dst.object_uuid,
            src.context_uuid
        FROM {t_quad} src
        JOIN {t_quad} dst
            ON dst.subject_uuid = src.subject_uuid
            AND dst.context_uuid = src.context_uuid
        WHERE src.predicate_uuid = $1
          AND dst.predicate_uuid = $2
        ORDER BY src.subject_uuid, src.context_uuid
        ON CONFLICT DO NOTHING
    """, _EDGE_SRC_UUID, _EDGE_DST_UUID)

    inserted = int(result.split()[-1]) if result else 0
    if inserted:
        # ANALYZE takes SHARE UPDATE EXCLUSIVE — does not block readers/writers.
        await conn.execute(f"ANALYZE {t_edge}")
    logger.info("backfill_edge_table(%s): %d rows inserted", space_id, inserted)
    return inserted


async def edge_table_drift(conn, space_id: str) -> tuple[int, int]:
    """Return (edge_source_quads, edge_rows) — a cheap, fully-indexed drift signal.

    edge_source_quads = number of hasEdgeSource quads (≈ number of edges).
    edge_rows         = rows currently in {space}_edge.
    A large positive (edge_source_quads - edge_rows) means the edge table has
    drifted behind rdf_quad (edges inserted via a path that didn't sync it) and
    should be resynced.  Both counts are single-column index scans.
    """
    t_edge = f"{space_id}_edge"
    t_quad = f"{space_id}_rdf_quad"
    src_quads = await conn.fetchval(
        f"SELECT count(*) FROM {t_quad} WHERE predicate_uuid = $1", _EDGE_SRC_UUID)
    edge_rows = await conn.fetchval(f"SELECT count(*) FROM {t_edge}")
    return int(src_quads or 0), int(edge_rows or 0)
