"""
Vector population pipeline.

Reads subjects from the RDF quad/term tables, builds search_text,
vectorizes via the configured provider, and upserts into the
per-index vector data table ``{space}_vec_{index_name}``.

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

from vitalgraph.vectorization.base import VectorizationProvider
from vitalgraph.vectorization.registry import get_provider
from vitalgraph.vectorization.search_text_builder import (
    MappingRule,
    build_search_text,
    fetch_literal_properties,
    fetch_literal_properties_batch,
    resolve_mapping,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 100


@dataclass
class PopulationStats:
    """Statistics for a population run."""
    subjects_processed: int = 0
    subjects_skipped: int = 0
    embeddings_stored: int = 0
    elapsed_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------
# Core upsert SQL
# -----------------------------------------------------------------------

UPSERT_VECTOR_SQL = """
INSERT INTO {vec_table} (subject_uuid, context_uuid, embedding, search_text, updated_time)
VALUES ($1, $2, $3::vector, $4, CURRENT_TIMESTAMP)
ON CONFLICT (subject_uuid, context_uuid)
DO UPDATE SET embedding = EXCLUDED.embedding,
              search_text = EXCLUDED.search_text,
              updated_time = EXCLUDED.updated_time
"""

DELETE_VECTOR_SQL = """
DELETE FROM {vec_table}
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


async def populate_index(
    conn,
    space_id: str,
    index_name: str,
    context_uuid,
    *,
    type_uri: Optional[str] = None,
    mapping_rule: Optional[MappingRule] = None,
    mapping_type: Optional[str] = None,
    provider: Optional[VectorizationProvider] = None,
    provider_name: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    subject_uuids: Optional[List] = None,
) -> PopulationStats:
    """Populate (or re-populate) a vector index for a graph.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        index_name: Name of the vector index (must exist in vector_index table).
        context_uuid: Graph context UUID.
        type_uri: Optional RDF type URI to filter subjects (e.g., KGEntity type).
        mapping_rule: Pre-resolved mapping rule. If None, resolved from DB.
        mapping_type: Mapping type for DB resolution (e.g., 'kgentity').
        provider: Pre-instantiated vectorization provider.
        provider_name: Provider name to look up (used if provider is None).
        provider_config: Provider config dict (used if provider is None).
        batch_size: Number of subjects to process per batch.
        subject_uuids: Optional explicit list of subjects to index
            (for incremental updates). If None, indexes all subjects.

    Returns:
        PopulationStats with counts and timing.
    """
    stats = PopulationStats()
    t0 = time.monotonic()

    # Resolve provider
    if provider is None:
        if provider_name is None:
            # Look up from vector_index table
            row = await conn.fetchrow(
                f"SELECT provider, provider_config, dimensions FROM {space_id}_vector_index "
                f"WHERE index_name = $1",
                index_name,
            )
            if row is None:
                stats.errors.append(f"Vector index '{index_name}' not found in {space_id}_vector_index")
                return stats
            provider_name = str(row["provider"])
            provider_config = row["provider_config"] or {}

        assert provider_name is not None
        provider = get_provider(provider_name, provider_config, cache_key=f"{space_id}:{index_name}")

    # Resolve mapping rule from normalized tables if not provided
    if mapping_rule is None and mapping_type is not None:
        mapping_rule = await resolve_mapping(
            conn, space_id, index_name, mapping_type, type_uri,
        )

    # No mapping found → class is not vectorized (opt-in model)
    if mapping_rule is None:
        logger.info("populate_index: %s/%s — no mapping found for %s/%s, skipping",
                     space_id, index_name, mapping_type, type_uri)
        return stats

    # Check enabled flag — mapping exists but is disabled
    if not mapping_rule.enabled:
        logger.info("populate_index: %s/%s — mapping disabled for %s/%s, skipping",
                     space_id, index_name, mapping_type, type_uri)
        return stats

    vec_table = f"{space_id}_vec_{index_name}"

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
        "populate_index: %s/%s — %d subjects, provider=%s",
        space_id, index_name, len(subject_uuids), provider.provider_name,
    )

    # Process in batches
    for i in range(0, len(subject_uuids), batch_size):
        batch_uuids = subject_uuids[i : i + batch_size]

        try:
            await _process_batch(
                conn, space_id, vec_table, context_uuid,
                batch_uuids, provider, mapping_rule, stats,
            )
        except Exception as e:
            msg = f"Batch {i // batch_size} failed: {e}"
            logger.error("populate_index: %s", msg)
            stats.errors.append(msg)

    stats.elapsed_seconds = time.monotonic() - t0
    logger.info(
        "populate_index: %s/%s done — %d stored, %d skipped, %.1fs",
        space_id, index_name, stats.embeddings_stored,
        stats.subjects_skipped, stats.elapsed_seconds,
    )
    return stats


async def _process_batch(
    conn,
    space_id: str,
    vec_table: str,
    context_uuid,
    subject_uuids: List,
    provider: VectorizationProvider,
    mapping_rule: Optional[MappingRule],
    stats: PopulationStats,
) -> None:
    """Process a batch of subjects: fetch props → build text → vectorize → upsert."""
    # 1. Fetch literal properties for all subjects in batch
    props_map = await fetch_literal_properties_batch(
        conn, space_id, subject_uuids, context_uuid,
    )

    # 2. Build search_text for each subject
    texts: List[str] = []
    valid_uuids: List = []
    for subj_uuid in subject_uuids:
        stats.subjects_processed += 1
        props = props_map.get(subj_uuid, [])
        if not props:
            stats.subjects_skipped += 1
            continue
        text = build_search_text(props, mapping_rule)
        if not text.strip():
            stats.subjects_skipped += 1
            continue
        texts.append(text)
        valid_uuids.append(subj_uuid)

    if not texts:
        return

    # 3. Vectorize batch
    embeddings = await provider.vectorize_texts(texts)

    # 4. Upsert into vector data table
    upsert_sql = UPSERT_VECTOR_SQL.format(vec_table=vec_table)
    for subj_uuid, embedding, text in zip(valid_uuids, embeddings, texts):
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        await conn.execute(upsert_sql, subj_uuid, context_uuid, vec_str, text)
        stats.embeddings_stored += 1


async def delete_subject_vectors(
    conn,
    space_id: str,
    index_name: str,
    subject_uuid,
    context_uuid,
) -> bool:
    """Remove a subject's vector from a specific index."""
    vec_table = f"{space_id}_vec_{index_name}"
    sql = DELETE_VECTOR_SQL.format(vec_table=vec_table)
    try:
        await conn.execute(sql, subject_uuid, context_uuid)
        return True
    except Exception as e:
        logger.error("delete_subject_vectors(%s/%s) failed: %s", space_id, index_name, e)
        return False


async def update_subject_vector(
    conn,
    space_id: str,
    index_name: str,
    subject_uuid,
    context_uuid,
    *,
    mapping_rule: Optional[MappingRule] = None,
    provider: Optional[VectorizationProvider] = None,
) -> bool:
    """Re-vectorize and upsert a single subject (for auto-sync on update).

    If provider is None, it will be looked up from the vector_index table.
    If mapping_rule is None, uses default (hasKGraphDescription) behavior.
    """
    try:
        # Resolve provider if needed
        if provider is None:
            row = await conn.fetchrow(
                f"SELECT provider, provider_config FROM {space_id}_vector_index "
                f"WHERE index_name = $1",
                index_name,
            )
            if row is None:
                return False
            provider = get_provider(
                row["provider"], row["provider_config"] or {},
                cache_key=f"{space_id}:{index_name}",
            )

        # Fetch properties
        props = await fetch_literal_properties(conn, space_id, subject_uuid, context_uuid)
        if not props:
            # No properties → remove from index
            await delete_subject_vectors(conn, space_id, index_name, subject_uuid, context_uuid)
            return True

        text = build_search_text(props, mapping_rule)
        if not text.strip():
            await delete_subject_vectors(conn, space_id, index_name, subject_uuid, context_uuid)
            return True

        # Vectorize
        embedding = await provider.vectorize_text(text)

        # Upsert
        vec_table = f"{space_id}_vec_{index_name}"
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        await conn.execute(
            UPSERT_VECTOR_SQL.format(vec_table=vec_table),
            subject_uuid, context_uuid, vec_str, text,
        )
        return True

    except Exception as e:
        logger.error("update_subject_vector(%s/%s) failed: %s", space_id, index_name, e)
        return False
