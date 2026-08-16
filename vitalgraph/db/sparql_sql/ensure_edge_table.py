"""Verify and populate the edge table for query rewrites. NO DDL.

The edge table is part of the space schema — `SparqlSQLSchema.create_space` —
and is maintained by app-level sync. This module used to CREATE it when
missing, from its own copy of the DDL, called from `generator` stage 2a.1.
Two things were wrong with that and one of them had already bitten:

  * Schema as a side effect of a READ. DDL ran inside a user's query.
  * Two sources for one schema, which diverged. The copy here never gained
    `edge_type_uuid` (issues/060), which `emit_backward` consumes as a column
    predicate and `compute_edge_fanout` requires — "without it every edge pools
    into one bucket and the result describes nothing". A space whose edge table
    was created here was missing the column, silently.

A missing table now disables the rewrite for that space and says which
migration to run. It cannot happen on a space created or migrated properly,
which is why it is reported rather than repaired.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# Predicate URIs used in edge table population
EDGE_SOURCE_URI = "http://vital.ai/ontology/vital-core#hasEdgeSource"
EDGE_DEST_URI = "http://vital.ai/ontology/vital-core#hasEdgeDestination"


# Module-level cache: space_id → bool
_edge_table_ready: dict = {}    # True once table verified populated this process


@asynccontextmanager
async def _acquire_conn(conn, conn_params):
    """Yield a usable connection for DDL/populate.

    CRITICAL (issue 019 pool-deadlock): when the caller already holds a pooled
    connection (``conn`` is not None), reuse it instead of acquiring a SECOND
    connection from the pool.  Acquiring a second connection while holding one
    deadlocks a small pool — with N concurrent callers each holding one and
    each blocking to acquire another, the pool bleeds out and unrelated reads
    stall.  Only acquire a fresh connection when the caller has none.
    """
    if conn is not None:
        yield conn
        return
    from . import db_provider as db
    async with db.get_connection(params=conn_params) as c:
        yield c


async def ensure_edge_table(space_id: str, conn=None, conn_params=None) -> bool:
    """Ensure the edge table exists and is populated.  Returns True if usable.

    On first access per process:
    - Creates the table if it doesn't exist
    - Populates the table from rdf_quad if empty
    """
    if _edge_table_ready.get(space_id):
        return True

    from . import db_provider as db

    table_name = f"{space_id}_edge"
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    try:
        # Check if edge table exists
        table_rows = await db.execute_query(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s",
            params=(table_name,), conn=conn, conn_params=conn_params,
        )

        if not table_rows:
            # The table is part of the space schema, so this cannot happen on a
            # space created or migrated properly. It is NOT created here.
            #
            # It used to be, and the DDL had drifted: the inline copy never
            # gained `edge_type_uuid`, which the schema added (issues/060) and
            # which `emit_backward` consumes as a column predicate and
            # `compute_edge_fanout` requires — "without it every edge pools into
            # one bucket and the result describes nothing". A space whose edge
            # table was created HERE was missing that column, and nothing said
            # so. Two sources for one schema is what produced that, and creating
            # schema from a read path is what hid it.
            logger.error(
                "ensure_edge_table(%s): %s does not exist. It is created with "
                "the space; a space predating it needs "
                "`python scripts/migrate_space_schema.py --space %s`. The edge "
                "rewrite is disabled for this space until then.",
                space_id, table_name, space_id)
            _edge_table_ready[space_id] = False
            return False

        # Check if table is empty and needs population
        count_rows = await db.execute_query(
            f"SELECT COUNT(*) AS cnt FROM {table_name}",
            conn=conn, conn_params=conn_params,
        )
        row_count = count_rows[0]["cnt"] if count_rows else 0

        if row_count == 0:
            # Populate from rdf_quad
            logger.info("ensure_edge_table(%s): populating edge table from rdf_quad", space_id)
            populate_sql = f"""
                INSERT INTO {table_name} (edge_uuid, source_node_uuid, dest_node_uuid, context_uuid)
                SELECT
                    src.subject_uuid,
                    src.object_uuid,
                    dst.object_uuid,
                    src.context_uuid
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
                ON CONFLICT DO NOTHING
            """
            async with _acquire_conn(conn, conn_params) as c:
                await c.execute(populate_sql)
                await c.execute(f"ANALYZE {table_name}")

            # Re-check count
            count_rows = await db.execute_query(
                f"SELECT COUNT(*) AS cnt FROM {table_name}",
                conn=conn, conn_params=conn_params,
            )
            row_count = count_rows[0]["cnt"] if count_rows else 0
            logger.info("ensure_edge_table(%s): populated %d edge rows", space_id, row_count)

        _edge_table_ready[space_id] = True
        return True

    except Exception as e:
        logger.warning("ensure_edge_table(%s): failed: %s", space_id, e)
        _edge_table_ready[space_id] = False
        return False
