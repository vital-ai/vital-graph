"""Remove FTS rows for subjects whose quads are being deleted.

WHY THIS IS AT THE SQL LAYER AND NOT IN `auto_sync`. An FTS row is keyed on the
SUBJECT, and the subjects of an entity graph are its FRAMES and SLOTS, not the
entity. The delete endpoint schedules `auto_sync(..., "delete")` with the ENTITY
uris, so the entity -- which has no FTS row -- is the only thing it cleans, and
every slot row survives its own data. `issues/217` fixed the single-entity path
and recorded the bulk path as still open; this closes it.

`delete_entity_graph_bulk` already computes the exact subject set it is about to
delete and already syncs `frame_slot`, `entity_slot_sort` and `edge` from it.
Doing FTS in the same place makes the cleanup transactional with the delete
rather than a fire-and-forget task that may not run: a background task that
fails leaves rows matching a search and resolving to an entity that is gone.

Measured before this existed: deleting 1,387 entities from `prod_kg_archive`
emptied the space (0 quads) and left 5,409 FTS rows, every one orphaned. The
only repair was dropping the index and recreating it -- which is not an option
on a live space whose index has 324,869 rows.
"""

from __future__ import annotations

import logging
from typing import List

from .sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)


async def sync_fts_before_delete(conn, space_id: str, subject_uuids: List,
                                 context_uuid) -> int:
    """Delete FTS rows for `subject_uuids` from EVERY index in the space.

    Every index, not the one the caller has in mind: a subject may be indexed by
    several mappings, and a caller that knows about one of them would leave the
    others behind. Returns the number of rows removed.

    Raises nothing for a missing table -- an index registered but never
    populated has no data table yet, and that is not an error at delete time.
    """
    if not subject_uuids:
        return 0

    rows = await conn.fetch(
        f"SELECT index_name FROM {space_id}_fts_index")
    removed = 0
    for row in rows:
        table = SparqlSQLSchema.fts_table_name(space_id, row["index_name"])
        try:
            result = await conn.execute(
                f"DELETE FROM {table} "
                f"WHERE subject_uuid = ANY($1) AND context_uuid = $2",
                subject_uuids, context_uuid)
            if result and result.rsplit(" ", 1)[-1].isdigit():
                removed += int(result.rsplit(" ", 1)[-1])
        except Exception as e:
            # A registered index whose data table does not exist yet is normal.
            # Anything else is worth knowing about, but must not abort a delete
            # that has already removed the quads.
            logger.warning("fts delete cleanup on %s failed: %s", table, e)

    if removed:
        logger.info("sync_fts_before_delete(%s): removed %d FTS row(s) for "
                    "%d subject(s)", space_id, removed, len(subject_uuids))
    return removed
