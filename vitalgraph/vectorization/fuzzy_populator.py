"""
Fuzzy search populator for RDF quads (Track A).

Reads literal property values from the quad/term tables,
computes MinHash LSH band hashes, and stores them in the
per-space fuzzy_band / fuzzy_phonetic_band tables.

Usage:
    await populate_fuzzy_index(conn, space_id, index_name)
    await update_subject_fuzzy(conn, space_id, subject_uuid, context_uuid)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from .fuzzy_core import (
    FuzzyConfig,
    build_band_entries,
    build_minhash,
    compute_band_ranges,
    compute_phonetic_codes,
    compute_shingles,
    make_lsh_key,
    make_phonetic_lsh_key,
)
from .fuzzy_mapping_manager import (
    FuzzyMappingRule,
    resolve_fuzzy_mapping,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 500

# Mapping from logical mapping_type to RDF type URI(s)
_MAPPING_TYPE_RDF_TYPES = {
    "kgentity": "http://vital.ai/ontology/haley-ai-kg#KGEntity",
    "kgdocument": "http://vital.ai/ontology/haley-ai-kg#KGDocument",
    "kgdocument_segment": "http://vital.ai/ontology/haley-ai-kg#KGDocument",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def populate_fuzzy_index(
    conn,
    space_id: str,
    index_name: str,
    mapping_type: str = "kgentity",
    type_uri: Optional[str] = None,
    truncate_first: bool = True,
) -> int:
    """Full population of a fuzzy index from RDF quads.

    1. Resolves fuzzy mapping (which properties to index)
    2. Fetches all subjects with those properties
    3. Computes MinHash bands for each name variant
    4. Stores in {space}_fuzzy_band / {space}_fuzzy_phonetic_band

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        index_name: Logical fuzzy index name.
        mapping_type: KG mapping type (default 'kgentity').
        type_uri: Optional specific KG type URI.
        truncate_first: If True, truncate band tables before populating.

    Returns:
        Number of subjects indexed.
    """
    rule = await resolve_fuzzy_mapping(conn, space_id, index_name, mapping_type, type_uri)
    if rule is None:
        logger.warning("No fuzzy mapping found for index='%s', type='%s/%s' in space='%s'",
                        index_name, mapping_type, type_uri, space_id)
        return 0

    if not rule.enabled:
        logger.info("Fuzzy mapping %s is disabled, skipping", rule.mapping_id)
        return 0

    all_property_uris = rule.primary_uris + rule.alias_uris + rule.include_uris
    if not all_property_uris:
        logger.warning("Fuzzy mapping %s has no properties configured", rule.mapping_id)
        return 0

    band_table = f"{space_id}_fuzzy_band"
    phonetic_table = f"{space_id}_fuzzy_phonetic_band"

    if truncate_first:
        await conn.execute(f"TRUNCATE {band_table}")
        await conn.execute(f"TRUNCATE {phonetic_table}")

    # Pre-compute band ranges
    primary_ranges = compute_band_ranges(rule.num_perm, rule.lsh_threshold)
    phonetic_ranges = compute_band_ranges(rule.num_perm, 0.3)  # phonetic uses fixed threshold

    # Determine RDF type filter from mapping_type
    rdf_type_uri = _MAPPING_TYPE_RDF_TYPES.get(mapping_type)

    # Fetch subjects and their literal property values (filtered by type)
    subjects = await _fetch_subject_names(conn, space_id, all_property_uris, rdf_type_uri=rdf_type_uri)
    logger.info("Fuzzy populator: found %d subjects with mapped properties (type_filter=%s)", len(subjects), rdf_type_uri)

    primary_buffer: List[Tuple[int, bytes, str]] = []
    phonetic_buffer: List[Tuple[int, bytes, str]] = []
    count = 0

    for subject_uuid, names in subjects.items():
        if not names:
            continue

        for variant_idx, name in enumerate(names):
            # Primary shingles → MinHash → bands
            shingles = compute_shingles(name, rule.shingle_k)
            if not shingles:
                continue
            mh = build_minhash(shingles, rule.num_perm)
            entity_key = make_lsh_key(str(subject_uuid), variant_idx)
            entries = build_band_entries(mh, primary_ranges, entity_key)
            primary_buffer.extend(entries)

            # Phonetic shingles → MinHash → bands
            codes = compute_phonetic_codes(name)
            if codes:
                ph_mh = build_minhash(set(codes), rule.num_perm)
                ph_key = make_phonetic_lsh_key(str(subject_uuid), variant_idx)
                ph_entries = build_band_entries(ph_mh, phonetic_ranges, ph_key)
                phonetic_buffer.extend(ph_entries)

        count += 1

        # Flush in batches
        if count % BATCH_SIZE == 0:
            await _flush_bands(conn, band_table, primary_buffer)
            await _flush_bands(conn, phonetic_table, phonetic_buffer)
            primary_buffer.clear()
            phonetic_buffer.clear()

    # Final flush
    if primary_buffer:
        await _flush_bands(conn, band_table, primary_buffer)
    if phonetic_buffer:
        await _flush_bands(conn, phonetic_table, phonetic_buffer)

    logger.info("Fuzzy populator: indexed %d subjects for index='%s' in space='%s'",
                 count, index_name, space_id)
    return count


async def update_subject_fuzzy(
    conn,
    space_id: str,
    subject_uuid: UUID,
    context_uuid: Optional[UUID] = None,
) -> bool:
    """Incrementally update fuzzy bands for a single subject.

    Called by auto_sync when an entity is created/updated.

    Args:
        conn: asyncpg connection.
        space_id: Space identifier.
        subject_uuid: The entity UUID to re-index.
        context_uuid: Optional context (unused currently).

    Returns:
        True if bands were updated, False if no mapping found.
    """
    from .fuzzy_mapping_manager import resolve_any_fuzzy_mapping

    rule = await resolve_any_fuzzy_mapping(conn, space_id)
    if rule is None:
        return False

    all_property_uris = rule.primary_uris + rule.alias_uris + rule.include_uris
    if not all_property_uris:
        return False

    # Check if subject matches the expected RDF type for this mapping
    rdf_type_uri = _MAPPING_TYPE_RDF_TYPES.get(rule.mapping_type) if rule.mapping_type else None
    if rdf_type_uri:
        quad_table = f"{space_id}_rdf_quad"
        term_table = f"{space_id}_term"
        type_check = await conn.fetchval(f"""
            SELECT 1 FROM {quad_table} q
            JOIN {term_table} tp ON tp.term_uuid = q.predicate_uuid
            JOIN {term_table} to2 ON to2.term_uuid = q.object_uuid
            WHERE q.subject_uuid = $1
              AND tp.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
              AND to2.term_text = $2
            LIMIT 1
        """, subject_uuid, rdf_type_uri)
        if not type_check:
            return False  # subject doesn't match the mapping type

    band_table = f"{space_id}_fuzzy_band"
    phonetic_table = f"{space_id}_fuzzy_phonetic_band"
    subject_str = str(subject_uuid)

    # Remove existing bands for this subject
    # entity_key starts with '{subject_uuid}::'
    entity_prefix = f"{subject_str}::%"
    await conn.execute(
        f"DELETE FROM {band_table} WHERE entity_key LIKE $1", entity_prefix
    )
    await conn.execute(
        f"DELETE FROM {phonetic_table} WHERE entity_key LIKE $1",
        f"P::{subject_str}::%"
    )

    # Fetch current names for this subject
    names = await _fetch_single_subject_names(conn, space_id, subject_uuid, all_property_uris)
    if not names:
        return True  # cleaned up, nothing to index

    primary_ranges = compute_band_ranges(rule.num_perm, rule.lsh_threshold)
    phonetic_ranges = compute_band_ranges(rule.num_perm, 0.3)

    primary_buffer: List[Tuple[int, bytes, str]] = []
    phonetic_buffer: List[Tuple[int, bytes, str]] = []

    for variant_idx, name in enumerate(names):
        shingles = compute_shingles(name, rule.shingle_k)
        if not shingles:
            continue
        mh = build_minhash(shingles, rule.num_perm)
        entity_key = make_lsh_key(subject_str, variant_idx)
        primary_buffer.extend(build_band_entries(mh, primary_ranges, entity_key))

        codes = compute_phonetic_codes(name)
        if codes:
            ph_mh = build_minhash(set(codes), rule.num_perm)
            ph_key = make_phonetic_lsh_key(subject_str, variant_idx)
            phonetic_buffer.extend(build_band_entries(ph_mh, phonetic_ranges, ph_key))

    if primary_buffer:
        await _flush_bands(conn, band_table, primary_buffer)
    if phonetic_buffer:
        await _flush_bands(conn, phonetic_table, phonetic_buffer)

    return True


async def remove_subject_fuzzy(
    conn,
    space_id: str,
    subject_uuid: UUID,
) -> None:
    """Remove all fuzzy bands for a single subject.

    Called by auto_sync when an entity is deleted.
    """
    band_table = f"{space_id}_fuzzy_band"
    phonetic_table = f"{space_id}_fuzzy_phonetic_band"
    subject_str = str(subject_uuid)

    await conn.execute(
        f"DELETE FROM {band_table} WHERE entity_key LIKE $1",
        f"{subject_str}::%"
    )
    await conn.execute(
        f"DELETE FROM {phonetic_table} WHERE entity_key LIKE $1",
        f"P::{subject_str}::%"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _fetch_subject_names(
    conn,
    space_id: str,
    property_uris: List[str],
    rdf_type_uri: Optional[str] = None,
) -> Dict[UUID, List[str]]:
    """Fetch all subjects and their literal values for given predicate URIs.

    If rdf_type_uri is provided, only subjects with that rdf:type are included.

    Returns dict of subject_uuid → list of name strings.
    """
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    if rdf_type_uri:
        # Only fetch subjects that have the specified rdf:type
        sql = f"""
            SELECT q.subject_uuid, obj_t.term_text
            FROM {quad_table} q
            JOIN {term_table} pred_t ON pred_t.term_uuid = q.predicate_uuid
            JOIN {term_table} obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L'
            WHERE pred_t.term_text = ANY($1)
              AND q.subject_uuid IN (
                  SELECT q2.subject_uuid
                  FROM {quad_table} q2
                  JOIN {term_table} tp ON tp.term_uuid = q2.predicate_uuid
                  JOIN {term_table} to2 ON to2.term_uuid = q2.object_uuid
                  WHERE tp.term_text = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
                    AND to2.term_text = $2
              )
            ORDER BY q.subject_uuid
        """
        rows = await conn.fetch(sql, property_uris, rdf_type_uri)
    else:
        # No type filter — fetch all subjects with mapped properties
        sql = f"""
            SELECT q.subject_uuid, obj_t.term_text
            FROM {quad_table} q
            JOIN {term_table} pred_t ON pred_t.term_uuid = q.predicate_uuid
            JOIN {term_table} obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L'
            WHERE pred_t.term_text = ANY($1)
            ORDER BY q.subject_uuid
        """
        rows = await conn.fetch(sql, property_uris)

    subjects: Dict[UUID, List[str]] = {}
    for row in rows:
        uuid = row["subject_uuid"]
        text = row["term_text"]
        if text and text.strip():
            subjects.setdefault(uuid, []).append(text.strip())
    return subjects


async def _fetch_single_subject_names(
    conn,
    space_id: str,
    subject_uuid: UUID,
    property_uris: List[str],
) -> List[str]:
    """Fetch literal values for a single subject's mapped properties."""
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    sql = f"""
        SELECT obj_t.term_text
        FROM {quad_table} q
        JOIN {term_table} pred_t ON pred_t.term_uuid = q.predicate_uuid
        JOIN {term_table} obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L'
        WHERE q.subject_uuid = $1
          AND pred_t.term_text = ANY($2)
    """
    rows = await conn.fetch(sql, subject_uuid, property_uris)
    return [r["term_text"].strip() for r in rows if r["term_text"] and r["term_text"].strip()]


async def _flush_bands(
    conn,
    table: str,
    entries: List[Tuple[int, bytes, str]],
) -> None:
    """Insert band entries into PostgreSQL."""
    if not entries:
        return
    await conn.executemany(
        f"INSERT INTO {table} (band_id, band_hash, entity_key) VALUES ($1, $2, $3)",
        entries,
    )
