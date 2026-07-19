"""Streaming COPY export/import of a space's core data (backup / migration).

Exports the three core data tables — ``datatype``, ``term``, ``rdf_quad`` — via
binary ``COPY … TO`` (streamed to files, constant memory regardless of size).
``import_space`` restores them into a fresh space with ``COPY … FROM``, then
rebuilds everything derived from them (the datatype sequence, and the edge /
frame_entity / stats tables) so the restored space is immediately queryable.

Only the core tables are exported: the edge/frame_entity/geo/stats tables are
deterministic functions of the quads, so shipping them would just bloat the
backup — they are resynced on import instead.
"""

from __future__ import annotations

import logging
import os
from typing import Dict

from .sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)

# Core data tables, in a safe restore order (no FKs among them today, but keep
# datatype before term before rdf_quad for clarity).
_EXPORT_TABLES = ("datatype", "term", "rdf_quad")


def _bare(name: str) -> str:
    return name.split(".")[-1]


async def export_space(conn, space_id: str, dest_dir: str) -> Dict[str, str]:
    """Binary-COPY each core table to ``<dest_dir>/<table>.bin``.

    Returns a ``{logical_table: file_path}`` map. Streams row-by-row, so peak
    memory is independent of table size.
    """
    t = SparqlSQLSchema.get_table_names(space_id)
    os.makedirs(dest_dir, exist_ok=True)
    paths: Dict[str, str] = {}
    for key in _EXPORT_TABLES:
        table = _bare(t[key])
        path = os.path.join(dest_dir, f"{table}.bin")
        await conn.copy_from_table(table, output=path, format="binary")
        paths[key] = path
        logger.info("export_space(%s): %s -> %s", space_id, table, path)
    return paths


async def import_space(conn, space_id: str, paths: Dict[str, str],
                       resync: bool = True) -> Dict[str, int]:
    """Restore core tables from binary-COPY files into ``space_id``.

    TRUNCATEs the core tables first (a fresh space still has the seeded standard
    datatypes, which the import overwrites with the source's exact rows), COPYs
    each file in, resets the datatype id sequence, and — when ``resync`` — rebuilds
    the edge / frame_entity / stats tables.  Returns core-table row counts.
    Runs inside the caller's transaction.
    """
    t = SparqlSQLSchema.get_table_names(space_id)
    core = [_bare(t[k]) for k in _EXPORT_TABLES]
    await conn.execute(f"TRUNCATE {', '.join(core)}")

    for key in _EXPORT_TABLES:
        await conn.copy_to_table(_bare(t[key]), source=paths[key], format="binary")

    # COPY does not advance the datatype_id BIGSERIAL — realign it so later
    # datatype inserts don't collide with restored ids.
    dt = _bare(t["datatype"])
    await conn.execute(
        f"SELECT setval(pg_get_serial_sequence('{dt}', 'datatype_id'), "
        f"COALESCE((SELECT max(datatype_id) FROM {dt}), 1))")

    if resync:
        from .sync_edge_table import resync_edge_table
        from .sync_frame_entity_table import resync_frame_entity_table
        from .sync_stats_tables import resync_stats_tables
        await resync_edge_table(conn, space_id)
        await resync_frame_entity_table(conn, space_id)
        await resync_stats_tables(conn, space_id)

    counts = {}
    for key in _EXPORT_TABLES:
        counts[key] = await conn.fetchval(f"SELECT count(*) FROM {_bare(t[key])}")
    logger.info("import_space(%s): restored %s", space_id, counts)
    return counts
