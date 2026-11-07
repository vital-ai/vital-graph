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

from vitalgraph.db.sparql_sql.fts_languages import (
    InvalidFtsLanguages, validate_fts_languages,
)
from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.db.sparql_sql.space_names import space_prefix

logger = logging.getLogger(__name__)


# =====================================================================
# Public API
# =====================================================================

async def ensure_fts_index(
    conn,
    space_id: str,
    index_name: str,
    languages: Optional[List[str]] = None,
    rank_normalization: int = 0,
) -> bool:
    """Ensure an FTS index exists (registry row + data table + trigger).

    *languages* defaults to ``['english']`` if not provided.

    *rank_normalization* is the ``ts_rank_cd`` normalization bitmask, default 0
    (PostgreSQL's own default, which IGNORES document length). Set 1 to divide
    by log(length) — on short text that is the difference between 3 and 101
    distinct scores over 118,702 matching documents. Stored on the index
    because it changes every score the index produces.

    Returns True if created or already exists, False on error.

    Raises `InvalidFtsLanguages` when the index does not exist and *languages*
    is not a valid list (`issues/333`), BEFORE anything is created — so a
    refused index leaves no registry row and no table. Unvalidated, an unknown
    name created cleanly and then failed every write into the index inside
    auto-sync, which only logs: the subject was silently never indexed.
    """
    if languages is None:
        languages = ["english"]

    fts_index_table = f"{space_prefix(space_id)}_fts_index"
    try:
        row = await conn.fetchrow(
            f"SELECT index_name FROM {fts_index_table} WHERE index_name = $1",
            index_name,
        )
    except Exception as e:
        logger.error("Error creating FTS index '%s' for %s: %s", index_name, space_id, e)
        return False
    if row:
        logger.debug("FTS index '%s' already exists for space %s", index_name, space_id)
        return True

    reason = await validate_fts_languages(conn, languages)
    if reason:
        raise InvalidFtsLanguages(reason)
    languages = list(languages)

    try:
        await conn.execute(
            f"""
            INSERT INTO {fts_index_table}
                (index_name, languages, rank_normalization)
            VALUES ($1, $2, $3)
            ON CONFLICT (index_name) DO NOTHING
            """,
            index_name,
            languages,
            int(rank_normalization),
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
    fts_index_table = f"{space_prefix(space_id)}_fts_index"
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


def _rank_normalization(row) -> int:
    """The row's `ts_rank_cd` bitmask, 0 when unset or the column predates it.

    Returned by `get_fts_index` / `list_fts_indexes` because `config_apply`
    compares it against the document. It used to be missing from both, so the
    comparison read None as 0 and an index whose document set a non-zero value
    was reported `updated`, and re-written, on every apply (`issues/333`).
    """
    try:
        return int(row.get("rank_normalization") or 0)
    except (TypeError, ValueError):
        return 0


async def list_fts_indexes(conn, space_id: str) -> List[Dict[str, Any]]:
    """List all registered FTS indexes for a space.

    Returns a list of dicts with keys: index_id, index_name, languages, created_time.
    """
    fts_index_table = f"{space_prefix(space_id)}_fts_index"
    try:
        rows = await conn.fetch(
            f"SELECT * FROM {fts_index_table} ORDER BY index_id"
        )
        return [
            {
                "index_id": r["index_id"],
                "index_name": r["index_name"],
                "languages": list(r["languages"]),
                "rank_normalization": _rank_normalization(r),
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
    fts_index_table = f"{space_prefix(space_id)}_fts_index"
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
            "rank_normalization": _rank_normalization(row),
            "created_time": str(row["created_time"]) if row["created_time"] else None,
        }
    except Exception as e:
        logger.error("Error getting FTS index '%s' for %s: %s", index_name, space_id, e)
        return None


class FtsRefreshIncomplete(RuntimeError):
    """The languages changed, but recomputing the stored tsvectors did not
    finish. Rows written since the change are indexed under the new list; older
    rows keep their old tsvector until `refresh_fts_tsv` (CLI: `refresh-fts`)
    completes, which is idempotent and safe to re-run."""


#: Rows recomputed per statement by `refresh_fts_tsv`. Each batch is its own
#: statement, so the refresh is bounded by `statement_timeout` per batch, not
#: per table: production RDS sets 60 s, and one `UPDATE` over a large message
#: table is exactly what it kills (`issues/136`). At ~38 µs per row for `cjk`
#: (`issues/333`) a batch is ~0.2 s of CPU plus the write.
REFRESH_BATCH_SIZE = 5000


async def update_fts_languages(
    conn,
    space_id: str,
    index_name: str,
    languages: List[str],
    *,
    refresh_tsv: bool = True,
    batch_size: int = REFRESH_BATCH_SIZE,
) -> bool:
    """Update the languages for an FTS index.

    The registry row and the trigger function change in ONE transaction, so a
    write can never be indexed under a list the registry does not record, nor
    the reverse. If *refresh_tsv* is True, every stored tsvector is then
    recomputed in batches (`refresh_fts_tsv`). While that runs a query sees a
    mix of old and new rows; adding a language only ADDS lexemes, so results
    grow monotonically to the final state and no wrong row is ever returned.

    For a large table, pass ``refresh_tsv=False`` and run the operator command
    `refresh-fts` instead: an HTTP caller's timeout is shorter than the
    refresh, though the server would finish it anyway.

    Returns True on success, False if the index does not exist.
    Raises `InvalidFtsLanguages` before changing anything when *languages* is
    not a valid list; `FtsRefreshIncomplete` when the change was made but the
    refresh did not finish; anything else (nothing changed) on a failure of the
    registry/trigger transaction.
    """
    reason = await validate_fts_languages(conn, languages)
    if reason:
        raise InvalidFtsLanguages(reason)
    languages = list(languages)

    fts_index_table = f"{space_prefix(space_id)}_fts_index"
    schema = SparqlSQLSchema()
    trigger_fn = f"{space_prefix(space_id)}_fts_{index_name}_tsv_trigger"
    tsv_expr = schema._build_tsv_concat_expr(languages)

    async with conn.transaction():
        result = await conn.execute(
            f"UPDATE {fts_index_table} SET languages = $1 WHERE index_name = $2",
            languages, index_name,
        )
        if result == "UPDATE 0":
            logger.warning("FTS index '%s' not found in space %s", index_name, space_id)
            return False
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

    if refresh_tsv:
        try:
            await refresh_fts_tsv(conn, space_id, index_name,
                                  languages=languages, batch_size=batch_size)
        except Exception as e:
            raise FtsRefreshIncomplete(
                f"FTS index '{index_name}' languages are now {languages}, but "
                f"recomputing the stored tsvectors failed: {e}. Re-run the "
                f"refresh (refresh-fts); it is idempotent.") from e
    return True


async def refresh_fts_tsv(
    conn,
    space_id: str,
    index_name: str,
    *,
    languages: Optional[List[str]] = None,
    batch_size: int = REFRESH_BATCH_SIZE,
    progress=None,
) -> int:
    """Recompute every stored tsvector of an FTS index; return rows refreshed.

    Keyset batches over the primary key, each its own statement (and its own
    transaction unless the caller holds one), so no single statement grows with
    the table. Idempotent: a batch recomputes from `search_text`, so an
    interrupted refresh is completed by running it again from the start.

    *languages* defaults to the index's registry row. *progress*, if given, is
    called with the running total after each batch.
    """
    if languages is None:
        info = await get_fts_index(conn, space_id, index_name)
        if info is None:
            raise ValueError(f"FTS index '{index_name}' not found in {space_id}")
        languages = info["languages"]
    batch_size = max(1, int(batch_size))
    table = SparqlSQLSchema.fts_table_name(space_id, index_name)
    expr = SparqlSQLSchema.build_tsv_batch_expr(languages, "t.search_text")
    first = (f"SELECT subject_uuid, context_uuid FROM {table} "
             f"ORDER BY subject_uuid, context_uuid LIMIT {batch_size}")
    after = (f"SELECT subject_uuid, context_uuid FROM {table} "
             f"WHERE (subject_uuid, context_uuid) > ($1, $2) "
             f"ORDER BY subject_uuid, context_uuid LIMIT {batch_size}")
    update = ("WITH b AS ({keys}) "
              f"UPDATE {table} t SET tsv = {expr} FROM b "
              "WHERE t.subject_uuid = b.subject_uuid "
              "AND t.context_uuid = b.context_uuid "
              "RETURNING t.subject_uuid, t.context_uuid")
    total, last = 0, None
    while True:
        if last is None:
            rows = await conn.fetch(update.format(keys=first))
        else:
            rows = await conn.fetch(update.format(keys=after), *last)
        if not rows:
            break
        total += len(rows)
        # uuid.UUID orders by its 128-bit value, which is PostgreSQL's uuid
        # order (bytewise), so the max is the batch's last key.
        last = max((r["subject_uuid"], r["context_uuid"]) for r in rows)
        if progress is not None:
            progress(total)
        if len(rows) < batch_size:
            break
    logger.info("Refreshed %d tsvector(s) for FTS index '%s' in space %s",
                total, index_name, space_id)
    return total


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


async def update_rank_normalization(conn, space_id: str, index_name: str,
                                    rank_normalization: int) -> bool:
    """Set an existing FTS index's `ts_rank_cd` normalization bitmask.

    ADDED FOR `issues/233` step 3 (apply config), which found there was no way to
    change this after creation: `ensure_fts_index` takes it only when creating,
    and `update_fts_languages` does not touch it. So a config document could
    describe a rank normalization that apply was unable to produce, and the
    mismatch would show up only as every score being computed the other way.

    Cheap and physical-object-free, unlike a language change: the bitmask is read
    at QUERY time by `ts_rank_cd`, so nothing is stored differently and no tsv
    needs recomputing. That is why this is a registry update and not a rebuild.

    Returns True when a row was updated.
    """
    try:
        result = await conn.execute(
            f"UPDATE {space_prefix(space_id)}_fts_index SET rank_normalization = $1 "
            f"WHERE index_name = $2", rank_normalization, index_name)
        updated = result.endswith(" 1")
        if updated:
            logger.info("FTS index %s/%s rank_normalization -> %s",
                        space_id, index_name, rank_normalization)
        else:
            logger.warning("FTS index %s/%s not found for rank_normalization "
                           "update", space_id, index_name)
        return updated
    except Exception as e:
        logger.error("Failed to update rank_normalization for %s/%s: %s",
                     space_id, index_name, e)
        return False
