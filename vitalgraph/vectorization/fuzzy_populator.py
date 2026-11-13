"""
Fuzzy search populator for RDF quads (Track A).

Reads literal property values from the quad/term tables,
computes MinHash LSH band hashes, and stores them in the
per-space fuzzy_band / fuzzy_phonetic_band tables.

The space has one fuzzy index, the union of its enabled mappings
(`fuzzy_mapping_manager.SpaceFuzzyIndex`). Population, per-subject sync and the
`vg:fuzzyMatch` resolver all read names through `fetch_scoped_names`, so the
three agree on what a subject's names are (`issues/338`, `issues/339`).

Usage:
    await populate_fuzzy_index(conn, space_id)
    await update_subject_fuzzy(conn, space_id, subject_uuid, context_uuid)
"""
from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from .fuzzy_core import (
    build_band_entries,
    build_minhash,
    compute_band_ranges,
    compute_phonetic_codes,
    compute_shingles,
    make_lsh_key,
    make_phonetic_lsh_key,
)
from .fuzzy_mapping_manager import (
    RDF_TYPE,
    SpaceFuzzyIndex,
    resolve_space_fuzzy_index,
)
from vitalgraph.db.sparql_sql.space_names import space_prefix

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def populate_fuzzy_index(
    conn,
    space_id: str,
    truncate_first: bool = True,
) -> int:
    """Rebuild the space's fuzzy index from RDF quads.

    1. Resolves the space's index (every enabled mapping)
    2. Fetches every subject's names through those mappings
    3. Computes MinHash bands for each name variant
    4. Stores in {space}_fuzzy_band / {space}_fuzzy_phonetic_band

    Returns:
        Number of subjects indexed.
    """
    index = await resolve_space_fuzzy_index(conn, space_id)
    if index is None:
        logger.warning("No enabled fuzzy mapping with properties in space='%s'", space_id)
        return 0

    band_table = f"{space_prefix(space_id)}_fuzzy_band"
    phonetic_table = f"{space_prefix(space_id)}_fuzzy_phonetic_band"

    if truncate_first:
        await conn.execute(f"TRUNCATE {band_table}")
        await conn.execute(f"TRUNCATE {phonetic_table}")

    primary_ranges = compute_band_ranges(index.num_perm, index.lsh_threshold)
    phonetic_ranges = compute_band_ranges(index.num_perm, 0.3)  # phonetic uses fixed threshold

    subjects = await fetch_scoped_names(conn, space_id, index)
    logger.info("Fuzzy populator: found %d subjects with mapped names (space=%s, %d mappings)",
                len(subjects), space_id, len(index.scopes))

    primary_buffer: List[Tuple[int, bytes, str]] = []
    phonetic_buffer: List[Tuple[int, bytes, str]] = []
    count = 0

    for subject_uuid, names in subjects.items():
        if not names:
            continue
        _band_names(index, str(subject_uuid), names, primary_ranges, phonetic_ranges,
                    primary_buffer, phonetic_buffer)
        count += 1

        if count % BATCH_SIZE == 0:
            await _flush_bands(conn, band_table, primary_buffer)
            await _flush_bands(conn, phonetic_table, phonetic_buffer)
            primary_buffer.clear()
            phonetic_buffer.clear()

    if primary_buffer:
        await _flush_bands(conn, band_table, primary_buffer)
    if phonetic_buffer:
        await _flush_bands(conn, phonetic_table, phonetic_buffer)

    logger.info("Fuzzy populator: indexed %d subjects in space='%s'", count, space_id)
    return count


async def update_subject_fuzzy(
    conn,
    space_id: str,
    subject_uuid: UUID,
    context_uuid: Optional[UUID] = None,
) -> bool:
    """Re-derive one subject's fuzzy bands. Called by auto_sync on a write.

    Removes the subject's rows, then indexes whatever names the space's
    mappings give it now. A subject no mapping covers (any longer) ends with no
    rows, so this also repairs rows an earlier, wider sync left behind.

    Returns:
        True if the space has a fuzzy index, False if not.
    """
    index = await resolve_space_fuzzy_index(conn, space_id)
    if index is None:
        return False

    band_table = f"{space_prefix(space_id)}_fuzzy_band"
    phonetic_table = f"{space_prefix(space_id)}_fuzzy_phonetic_band"
    subject_str = str(subject_uuid)

    # entity_key starts with '{subject_uuid}::'
    await conn.execute(
        f"DELETE FROM {band_table} WHERE entity_key LIKE $1", f"{subject_str}::%"
    )
    await conn.execute(
        f"DELETE FROM {phonetic_table} WHERE entity_key LIKE $1", f"P::{subject_str}::%"
    )

    names = (await fetch_scoped_names(conn, space_id, index, [subject_uuid])).get(subject_uuid)
    if not names:
        return True  # cleaned up, nothing to index

    primary_buffer: List[Tuple[int, bytes, str]] = []
    phonetic_buffer: List[Tuple[int, bytes, str]] = []
    _band_names(index, subject_str, names,
                compute_band_ranges(index.num_perm, index.lsh_threshold),
                compute_band_ranges(index.num_perm, 0.3),
                primary_buffer, phonetic_buffer)
    await _flush_bands(conn, band_table, primary_buffer)
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
    band_table = f"{space_prefix(space_id)}_fuzzy_band"
    phonetic_table = f"{space_prefix(space_id)}_fuzzy_phonetic_band"
    subject_str = str(subject_uuid)

    await conn.execute(
        f"DELETE FROM {band_table} WHERE entity_key LIKE $1",
        f"{subject_str}::%"
    )
    await conn.execute(
        f"DELETE FROM {phonetic_table} WHERE entity_key LIKE $1",
        f"P::{subject_str}::%"
    )


async def fetch_scoped_names(
    conn,
    space_id: str,
    index: SpaceFuzzyIndex,
    subject_uuids: Optional[Iterable[UUID]] = None,
) -> Dict[UUID, List[str]]:
    """Each subject's names under the space's fuzzy index.

    A name is a literal value of a property some enabled mapping lists, on a
    subject that mapping covers (its exact rdf:type, or any subject for a
    mapping type with no type filter). Names are stripped, empty ones dropped,
    and a name repeated across properties or mappings is kept once.

    `subject_uuids` limits the read to those subjects; None reads them all.
    Quads in every graph count, as they always have.
    """
    quad_table = f"{space_prefix(space_id)}_rdf_quad"
    term_table = f"{space_prefix(space_id)}_term"
    wanted = list(subject_uuids) if subject_uuids is not None else None

    subjects: Dict[UUID, List[str]] = {}
    for scope in index.scopes:
        params: list = [scope.property_uris]
        where = ["pred_t.term_text = ANY($1)"]
        if wanted is not None:
            params.append(wanted)
            where.append(f"q.subject_uuid = ANY(${len(params)}::uuid[])")
        if scope.rdf_type_uri:
            params.append(scope.rdf_type_uri)
            where.append(f"""q.subject_uuid IN (
                  SELECT q2.subject_uuid
                  FROM {quad_table} q2
                  JOIN {term_table} tp ON tp.term_uuid = q2.predicate_uuid
                  JOIN {term_table} to2 ON to2.term_uuid = q2.object_uuid
                  WHERE tp.term_text = '{RDF_TYPE}'
                    AND to2.term_text = ${len(params)})""")
        rows = await conn.fetch(f"""
            SELECT q.subject_uuid, obj_t.term_text
            FROM {quad_table} q
            JOIN {term_table} pred_t ON pred_t.term_uuid = q.predicate_uuid
            JOIN {term_table} obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L'
            WHERE {' AND '.join(where)}
            ORDER BY q.subject_uuid
        """, *params)
        for row in rows:
            text = (row["term_text"] or "").strip()
            if not text:
                continue
            names = subjects.setdefault(row["subject_uuid"], [])
            if text not in names:
                names.append(text)
    return subjects


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _band_names(index, subject_str, names, primary_ranges, phonetic_ranges,
                primary_buffer, phonetic_buffer) -> None:
    """Append one subject's primary and phonetic band rows, one set per name."""
    for variant_idx, name in enumerate(names):
        shingles = compute_shingles(name, index.shingle_k)
        if not shingles:
            continue
        mh = build_minhash(shingles, index.num_perm)
        primary_buffer.extend(build_band_entries(
            mh, primary_ranges, make_lsh_key(subject_str, variant_idx)))

        codes = compute_phonetic_codes(name)
        if codes:
            ph_mh = build_minhash(set(codes), index.num_perm)
            phonetic_buffer.extend(build_band_entries(
                ph_mh, phonetic_ranges, make_phonetic_lsh_key(subject_str, variant_idx)))


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
