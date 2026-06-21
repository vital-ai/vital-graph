"""
FTS index lifecycle helpers.

Provides setup, teardown, and language-update operations for named FTS indexes.
Each FTS index gets its own data table (``{space}_fts_{index_name}``) with a
trigger-based multi-language tsvector column.

FTS indexes reference shared search mappings (``{space}_search_mapping``) by
``index_name`` — the same mappings used by vector indexes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema

logger = logging.getLogger(__name__)


# =====================================================================
# Public API
# =====================================================================

async def ensure_fts_index(
    conn,
    space_id: str,
    index_name: str,
    languages: Optional[List[str]] = None,
) -> bool:
    """Ensure an FTS index exists (registry row + data table + trigger).

    *languages* defaults to ``['english']`` if not provided.

    Returns True if created or already exists, False on error.
    """
    if languages is None:
        languages = ["english"]

    fts_index_table = f"{space_id}_fts_index"
    try:
        row = await conn.fetchrow(
            f"SELECT index_name FROM {fts_index_table} WHERE index_name = $1",
            index_name,
        )
        if row:
            logger.debug("FTS index '%s' already exists for space %s", index_name, space_id)
            return True

        await conn.execute(
            f"""
            INSERT INTO {fts_index_table}
                (index_name, languages)
            VALUES ($1, $2)
            ON CONFLICT (index_name) DO NOTHING
            """,
            index_name,
            languages,
        )

        schema = SparqlSQLSchema()
        for stmt in schema.create_fts_data_table_sql(space_id, index_name, languages):
            await conn.execute(stmt)

        logger.info(
            "Created FTS index '%s' for space %s: languages=%s",
            index_name, space_id, languages,
        )
        return True

    except Exception as e:
        logger.error("Error creating FTS index '%s' for %s: %s", index_name, space_id, e)
        return False


async def teardown_fts_index(conn, space_id: str, index_name: str) -> bool:
    """Remove an FTS index: drop data table + trigger function, delete registry row.

    Returns True on success.
    """
    fts_index_table = f"{space_id}_fts_index"
    try:
        schema = SparqlSQLSchema()
        for stmt in schema.drop_fts_data_table_sql(space_id, index_name):
            await conn.execute(stmt)

        await conn.execute(
            f"DELETE FROM {fts_index_table} WHERE index_name = $1", index_name,
        )
        logger.info("Torn down FTS index '%s' for space %s", index_name, space_id)
        return True

    except Exception as e:
        logger.error("Error tearing down FTS index '%s' for %s: %s", index_name, space_id, e)
        return False


async def list_fts_indexes(conn, space_id: str) -> List[Dict[str, Any]]:
    """List all registered FTS indexes for a space.

    Returns a list of dicts with keys: index_id, index_name, languages, created_time.
    """
    fts_index_table = f"{space_id}_fts_index"
    try:
        rows = await conn.fetch(
            f"SELECT * FROM {fts_index_table} ORDER BY index_id"
        )
        return [
            {
                "index_id": r["index_id"],
                "index_name": r["index_name"],
                "languages": list(r["languages"]),
                "created_time": str(r["created_time"]) if r["created_time"] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("Error listing FTS indexes for %s: %s", space_id, e)
        return []


async def get_fts_index(conn, space_id: str, index_name: str) -> Optional[Dict[str, Any]]:
    """Get a single FTS index by name.

    Returns a dict or None if not found.
    """
    fts_index_table = f"{space_id}_fts_index"
    try:
        row = await conn.fetchrow(
            f"SELECT * FROM {fts_index_table} WHERE index_name = $1",
            index_name,
        )
        if row is None:
            return None
        return {
            "index_id": row["index_id"],
            "index_name": row["index_name"],
            "languages": list(row["languages"]),
            "created_time": str(row["created_time"]) if row["created_time"] else None,
        }
    except Exception as e:
        logger.error("Error getting FTS index '%s' for %s: %s", index_name, space_id, e)
        return None


async def update_fts_languages(
    conn,
    space_id: str,
    index_name: str,
    languages: List[str],
    *,
    refresh_tsv: bool = True,
) -> bool:
    """Update the languages for an FTS index.

    Recreates the trigger function with the new language list.
    If *refresh_tsv* is True, recomputes all tsvector values in the data table.

    Returns True on success.
    """
    fts_index_table = f"{space_id}_fts_index"
    try:
        # Update registry
        result = await conn.execute(
            f"UPDATE {fts_index_table} SET languages = $1 WHERE index_name = $2",
            languages, index_name,
        )
        if result == "UPDATE 0":
            logger.warning("FTS index '%s' not found in space %s", index_name, space_id)
            return False

        # Recreate trigger function with new languages
        schema = SparqlSQLSchema()
        trigger_fn = f"{space_id}_fts_{index_name}_tsv_trigger"
        table = schema.fts_table_name(space_id, index_name)
        tsv_expr = schema._build_tsv_concat_expr(languages)

        await conn.execute(f'''CREATE OR REPLACE FUNCTION {trigger_fn}() RETURNS trigger AS $$
BEGIN
    NEW.tsv := {tsv_expr};
    RETURN NEW;
END
$$ LANGUAGE plpgsql''')

        logger.info(
            "Updated FTS index '%s' languages to %s for space %s",
            index_name, languages, space_id,
        )

        # Refresh existing tsvector values
        if refresh_tsv:
            batch_expr = schema.build_tsv_batch_expr(languages)
            await conn.execute(
                f"UPDATE {table} SET tsv = {batch_expr}"
            )
            logger.info("Refreshed tsvector for FTS index '%s' in space %s", index_name, space_id)

        return True

    except Exception as e:
        logger.error(
            "Error updating languages for FTS index '%s' in %s: %s",
            index_name, space_id, e,
        )
        return False


async def get_fts_stats(conn, space_id: str, index_name: str) -> Dict[str, Any]:
    """Get statistics for an FTS data table.

    Returns dict with: row_count, distinct_entity_count, has_tsv_count.
    """
    table = SparqlSQLSchema.fts_table_name(space_id, index_name)
    try:
        row = await conn.fetchrow(f"""
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT subject_uuid) AS distinct_entity_count,
                COUNT(tsv) AS has_tsv_count
            FROM {table}
        """)
        return {
            "row_count": row["row_count"],
            "distinct_entity_count": row["distinct_entity_count"],
            "has_tsv_count": row["has_tsv_count"],
        }
    except Exception as e:
        logger.error("Error getting FTS stats for '%s' in %s: %s", index_name, space_id, e)
        return {"row_count": 0, "distinct_entity_count": 0, "has_tsv_count": 0}
