"""
FTS population pipeline.

Reads subjects from the RDF quad/term tables, builds search_text using the
shared search_mapping configuration, and upserts into the per-index FTS data
table ``{space}_fts_{index_name}``.

The tsvector column is computed in batch via SQL after bulk inserts (trigger
disabled during population for performance), matching the pattern used by
the fuzzy populator and Tier 3 loader.

Supports:
- Full re-index of all subjects in a graph (admin operation)
- Incremental update of specific subjects (auto-sync on CRUD)
- Batch processing with configurable batch size
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from vitalgraph.db.sparql_sql.sparql_sql_schema import SparqlSQLSchema
from vitalgraph.vectorization.search_text_builder import (
    MappingRule,
    build_search_text,
    fetch_literal_properties,
    fetch_literal_properties_batch,
    resolve_search_mapping,
)
from vitalgraph.vectorization.kgtype_description_lookup import (
    KGTypeDescriptionLookup,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500


@dataclass
class FTSPopulationStats:
    """Statistics for an FTS population run."""
    subjects_processed: int = 0
    subjects_skipped: int = 0
    rows_stored: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------
# Core upsert/delete SQL
# -----------------------------------------------------------------------

UPSERT_FTS_SQL = """
INSERT INTO {fts_table} (subject_uuid, context_uuid, search_text, updated_time)
VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
ON CONFLICT (subject_uuid, context_uuid)
DO UPDATE SET search_text = EXCLUDED.search_text,
              updated_time = EXCLUDED.updated_time
"""

DELETE_FTS_SQL = """
DELETE FROM {fts_table}
WHERE subject_uuid = $1 AND context_uuid = $2
"""

# -----------------------------------------------------------------------
# Fetch subjects to index
# -----------------------------------------------------------------------

ALL_SUBJECTS_SQL = """
SELECT DISTINCT q.subject_uuid
FROM {rdf_quad} q
WHERE q.context_uuid = $1
"""

TYPED_SUBJECTS_SQL = """
SELECT DISTINCT q.subject_uuid
FROM {rdf_quad} q
JOIN {term} t_pred ON q.predicate_uuid = t_pred.term_uuid
JOIN {term} t_obj  ON q.object_uuid    = t_obj.term_uuid
WHERE q.context_uuid = $1
  AND t_pred.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
  AND t_obj.term_text = $2
"""


async def populate_fts_index(
    conn,
    space_id: str,
    index_name: str,
    context_uuid,
    *,
    type_uri: Optional[str] = None,
    mapping_rule: Optional[MappingRule] = None,
    mapping_type: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    subject_uuids: Optional[List] = None,
) -> FTSPopulationStats:
    """Populate (or re-populate) an FTS index for a graph.

    Uses batch mode for full population: disable trigger → bulk INSERT →
    batch UPDATE tsv → re-enable trigger.

    For incremental updates (subject_uuids provided), uses the per-row
    trigger normally.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        index_name: Name of the FTS index (must exist in fts_index table).
        context_uuid: Graph context UUID.
        type_uri: Optional RDF type URI to filter subjects.
        mapping_rule: Pre-resolved mapping rule. If None, resolved from DB.
        mapping_type: Mapping type for DB resolution (e.g., 'kgentity').
        batch_size: Number of subjects to process per batch.
        subject_uuids: Optional explicit list of subjects to index
            (for incremental updates). If None, indexes all subjects.

    Returns:
        FTSPopulationStats with counts and timing.
    """
    stats = FTSPopulationStats()
    t0 = time.monotonic()

    # Resolve mapping rule from shared search_mapping tables
    if mapping_rule is None and mapping_type is not None:
        mapping_rule = await resolve_search_mapping(
            conn, space_id, index_name, mapping_type, type_uri,
        )

    if mapping_rule is None:
        logger.info("populate_fts_index: %s/%s — no mapping found for %s/%s, skipping",
                     space_id, index_name, mapping_type, type_uri)
        return stats

    if not mapping_rule.enabled:
        logger.info("populate_fts_index: %s/%s — mapping disabled for %s/%s, skipping",
                     space_id, index_name, mapping_type, type_uri)
        return stats

    # Look up languages for batch tsv computation
    fts_row = await conn.fetchrow(
        f"SELECT languages FROM {space_id}_fts_index WHERE index_name = $1",
        index_name,
    )
    if fts_row is None:
        stats.errors.append(f"FTS index '{index_name}' not found in {space_id}_fts_index")
        return stats

    languages = list(fts_row["languages"])
    fts_table = SparqlSQLSchema.fts_table_name(space_id, index_name)

    # Initialize type description lookup if needed
    type_lookup: Optional[KGTypeDescriptionLookup] = None
    if mapping_rule and mapping_rule.source_type in ("type_description", "properties_type"):
        type_lookup = KGTypeDescriptionLookup(mapping_type or "kgentity")

    # Determine if this is a full population or incremental
    is_full_population = subject_uuids is None

    # Get subjects to index
    if subject_uuids is None:
        if type_uri:
            sql = TYPED_SUBJECTS_SQL.format(
                rdf_quad=f"{space_id}_rdf_quad",
                term=f"{space_id}_term",
            )
            rows = await conn.fetch(sql, context_uuid, type_uri)
        else:
            sql = ALL_SUBJECTS_SQL.format(rdf_quad=f"{space_id}_rdf_quad")
            rows = await conn.fetch(sql, context_uuid)
        subject_uuids = [r["subject_uuid"] for r in rows]

    logger.info(
        "populate_fts_index: %s/%s — %d subjects, languages=%s, mode=%s",
        space_id, index_name, len(subject_uuids), languages,
        "full" if is_full_population else "incremental",
    )

    if not subject_uuids:
        stats.elapsed_seconds = time.monotonic() - t0
        return stats

    # For full population: disable trigger for batch performance
    trigger_name = f"trg_{space_id}_fts_{index_name}_tsv"
    if is_full_population:
        try:
            await conn.execute(
                f"ALTER TABLE {fts_table} DISABLE TRIGGER {trigger_name}"
            )
        except Exception as e:
            logger.warning("Could not disable trigger %s: %s", trigger_name, e)

    try:
        # Process in batches
        for i in range(0, len(subject_uuids), batch_size):
            batch_uuids = subject_uuids[i : i + batch_size]
            try:
                await _process_fts_batch(
                    conn, space_id, fts_table, context_uuid,
                    batch_uuids, mapping_rule, stats,
                    type_lookup=type_lookup,
                )
            except Exception as e:
                msg = f"Batch {i // batch_size} failed: {e}"
                logger.error("populate_fts_index: %s", msg)
                stats.errors.append(msg)

        # For full population: batch-compute tsvectors via SQL
        if is_full_population and stats.rows_stored > 0:
            tsv_expr = SparqlSQLSchema.build_tsv_batch_expr(languages)
            await conn.execute(
                f"UPDATE {fts_table} SET tsv = {tsv_expr} WHERE tsv IS NULL"
            )
            logger.info("Batch-computed tsvector for %d rows in %s",
                         stats.rows_stored, fts_table)

    finally:
        # Re-enable trigger
        if is_full_population:
            try:
                await conn.execute(
                    f"ALTER TABLE {fts_table} ENABLE TRIGGER {trigger_name}"
                )
            except Exception as e:
                logger.warning("Could not re-enable trigger %s: %s", trigger_name, e)

    stats.elapsed_seconds = time.monotonic() - t0
    logger.info(
        "populate_fts_index: %s/%s done — %d stored, %d skipped, %.1fs",
        space_id, index_name, stats.rows_stored,
        stats.subjects_skipped, stats.elapsed_seconds,
    )
    return stats


async def _process_fts_batch(
    conn,
    space_id: str,
    fts_table: str,
    context_uuid,
    subject_uuids: List,
    mapping_rule: Optional[MappingRule],
    stats: FTSPopulationStats,
    *,
    type_lookup: Optional[KGTypeDescriptionLookup] = None,
) -> None:
    """Process a batch of subjects: fetch props → build text → upsert."""
    # 1. Fetch literal properties for all subjects in batch
    props_map = await fetch_literal_properties_batch(
        conn, space_id, subject_uuids, context_uuid,
    )

    # 2. Batch-resolve type descriptions if needed
    desc_map: Dict = {}
    type_uri_map: Dict = {}
    if type_lookup:
        type_uri_map = await type_lookup.get_subject_type_uris_batch(
            conn, space_id, subject_uuids, context_uuid,
        )
        unique_type_uris = list(set(type_uri_map.values()))
        if unique_type_uris:
            desc_map = await type_lookup.get_descriptions_batch(conn, unique_type_uris)

    # 3. Build search_text and upsert
    upsert_sql = UPSERT_FTS_SQL.format(fts_table=fts_table)
    for subj_uuid in subject_uuids:
        stats.subjects_processed += 1
        props = props_map.get(subj_uuid, [])

        # Resolve type description for this subject
        type_desc: Optional[str] = None
        if type_lookup:
            subj_type_uri = type_uri_map.get(subj_uuid)
            if subj_type_uri:
                type_desc = desc_map.get(subj_type_uri)

        # For type_description mode, skip subjects without type desc
        if mapping_rule and mapping_rule.source_type == "type_description":
            if not type_desc:
                stats.subjects_skipped += 1
                continue
        elif not props:
            stats.subjects_skipped += 1
            continue

        text = build_search_text(props, mapping_rule, type_description=type_desc)
        if not text.strip():
            stats.subjects_skipped += 1
            continue
        await conn.execute(upsert_sql, subj_uuid, context_uuid, text)
        stats.rows_stored += 1


async def delete_subject_fts(
    conn,
    space_id: str,
    index_name: str,
    subject_uuid,
    context_uuid,
) -> bool:
    """Remove a subject's FTS entry from a specific index."""
    fts_table = SparqlSQLSchema.fts_table_name(space_id, index_name)
    sql = DELETE_FTS_SQL.format(fts_table=fts_table)
    try:
        await conn.execute(sql, subject_uuid, context_uuid)
        return True
    except Exception as e:
        logger.error("delete_subject_fts(%s/%s) failed: %s", space_id, index_name, e)
        return False


async def update_subject_fts(
    conn,
    space_id: str,
    index_name: str,
    subject_uuid,
    context_uuid,
    *,
    mapping_rule: Optional[MappingRule] = None,
    mapping_type: Optional[str] = None,
) -> bool:
    """Update a single subject's FTS entry (for auto-sync on update).

    Uses the trigger for tsvector computation (single-row, not batch mode).
    """
    try:
        # Fetch properties
        props = await fetch_literal_properties(conn, space_id, subject_uuid, context_uuid)
        fts_table = SparqlSQLSchema.fts_table_name(space_id, index_name)

        # Resolve type description if needed
        type_desc: Optional[str] = None
        if mapping_rule and mapping_rule.source_type in ("type_description", "properties_type"):
            lookup = KGTypeDescriptionLookup(mapping_type or "kgentity")
            type_uri = await lookup.get_subject_type_uri(
                conn, space_id, subject_uuid, context_uuid,
            )
            if type_uri:
                type_desc = await lookup.get_description(conn, type_uri)

        # For type_description mode, skip if no type desc
        if mapping_rule and mapping_rule.source_type == "type_description":
            if not type_desc:
                await delete_subject_fts(conn, space_id, index_name, subject_uuid, context_uuid)
                return True
        elif not props:
            # No properties → remove from index
            await delete_subject_fts(conn, space_id, index_name, subject_uuid, context_uuid)
            return True

        text = build_search_text(props, mapping_rule, type_description=type_desc)
        if not text.strip():
            await delete_subject_fts(conn, space_id, index_name, subject_uuid, context_uuid)
            return True

        # Upsert (trigger will handle tsvector)
        await conn.execute(
            UPSERT_FTS_SQL.format(fts_table=fts_table),
            subject_uuid, context_uuid, text,
        )
        return True

    except Exception as e:
        logger.error("update_subject_fts(%s/%s) failed: %s", space_id, index_name, e)
        return False
