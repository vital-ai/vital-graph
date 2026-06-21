"""
Resolve VectorRequests and FuzzyRequests by performing deferred
computation and substituting placeholder tokens in the generated SQL.

Called between SQL generation and SQL execution by both orchestration paths:
  - SparqlOrchestrator.execute()              (dev / test)
  - SparqlSQLSpaceImpl.execute_sparql_query()  (production)

Flow (vector):
  1. generate_sql() returns GenerateResult with vector_requests list.
  2. resolve_vector_requests() vectorizes search text, replaces placeholders
     with actual embedding literals.

Flow (fuzzy):
  1. generate_sql() returns GenerateResult with fuzzy_requests list.
  2. resolve_fuzzy_requests() performs MinHash band lookup + RapidFuzz
     scoring, replaces placeholders with CASE score expressions and
     UUID IN filters.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .vg_functions import FuzzyRequest, VectorRequest

logger = logging.getLogger(__name__)


async def resolve_vector_requests(
    sql: str,
    vector_requests: List[VectorRequest],
    space_id: str,
    conn,
) -> str:
    """Replace placeholder tokens in SQL with actual embedding vectors.

    Args:
        sql: Generated SQL string containing ``__VG_EMBED_*__`` placeholders.
        vector_requests: List of VectorRequest objects from GenerateResult.
        space_id: Space ID for vector index table lookups.
        conn: asyncpg connection (already acquired).

    Returns:
        SQL string with all placeholders replaced by embedding literals.
    """
    if not vector_requests:
        return sql

    from vitalgraph.vectorization.registry import get_provider

    for vr in vector_requests:
        # Look up vector index to get provider info
        row = await conn.fetchrow(
            f"SELECT provider, provider_config, dimensions "
            f"FROM {space_id}_vector_index "
            f"WHERE index_name = $1",
            vr.index_name,
        )

        if row is None:
            logger.error(
                "Vector index '%s' not found in %s_vector_index — "
                "cannot vectorize search text for placeholder %s",
                vr.index_name, space_id, vr.placeholder,
            )
            # Replace placeholder with a zero vector so the query doesn't
            # crash with a syntax error (will return 0 similarity)
            sql = sql.replace(f"'{vr.placeholder}'::vector", "'[]'::vector")
            continue

        provider_name = str(row["provider"])
        provider_config = row["provider_config"] or {}

        try:
            provider = get_provider(
                provider_name,
                provider_config,
                cache_key=f"{space_id}:{vr.index_name}",
            )

            embedding = await provider.vectorize_text(vr.search_text)

            # Format as pgvector literal: '[0.1,0.2,...]'
            vec_literal = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
            sql = sql.replace(
                f"'{vr.placeholder}'::vector",
                f"'{vec_literal}'::vector",
            )

            logger.debug(
                "Vectorized '%s' via %s/%s → %d dims for placeholder %s",
                vr.search_text[:50], provider_name, provider.model_name,
                len(embedding), vr.placeholder,
            )

        except Exception as e:
            logger.error(
                "Vectorization failed for placeholder %s (index=%s, text='%s'): %s",
                vr.placeholder, vr.index_name, vr.search_text[:50], e,
            )
            # Replace with zero vector so query doesn't crash
            sql = sql.replace(f"'{vr.placeholder}'::vector", "'[]'::vector")

    return sql


# ---------------------------------------------------------------------------
# Fuzzy request resolution
# ---------------------------------------------------------------------------

async def resolve_fuzzy_requests(
    sql: str,
    fuzzy_requests: List[FuzzyRequest],
    space_id: str,
    conn,
) -> str:
    """Replace fuzzy placeholder tokens in SQL with resolved score expressions.

    For each FuzzyRequest:
      1. Check if a fuzzy mapping exists for the space.
      2. If yes: MinHash band lookup → fetch candidate names → RapidFuzz score.
      3. If no: fall back to pg_trgm similarity() via existing GIN index.
      4. Replace score_placeholder with CASE expression.
      5. Inject filter_placeholder (if present in SQL) with UUID IN clause.

    Args:
        sql: Generated SQL string containing fuzzy placeholder tokens.
        fuzzy_requests: List of FuzzyRequest objects from GenerateResult.
        space_id: Space ID for table lookups.
        conn: asyncpg connection (already acquired).

    Returns:
        SQL string with all fuzzy placeholders replaced.
    """
    if not fuzzy_requests:
        return sql

    for fr in fuzzy_requests:
        try:
            scored = await _resolve_single_fuzzy(conn, space_id, fr)

            if scored:
                # Build CASE expression for scores
                case_parts = [
                    f"WHEN {fr.uuid_col} = '{uuid}'::uuid THEN {score}"
                    for uuid, score in scored
                ]
                case_expr = f"(CASE {' '.join(case_parts)} END)"

                # Build UUID IN filter
                uuid_list = ", ".join(f"'{uuid}'::uuid" for uuid, _ in scored)
                filter_expr = f"{fr.uuid_col} IN ({uuid_list})"
            else:
                # No results — NULL so FILTER(BOUND(?score)) removes all rows
                case_expr = "NULL"
                filter_expr = "FALSE"

            # Replace placeholders in SQL
            sql = sql.replace(fr.score_placeholder, case_expr)
            if fr.filter_placeholder in sql:
                sql = sql.replace(fr.filter_placeholder, filter_expr)

            logger.debug(
                "Fuzzy resolved '%s' → %d candidates (space=%s)",
                fr.search_text[:50], len(scored), space_id,
            )

        except Exception as e:
            logger.error(
                "Fuzzy resolution failed for '%s' (space=%s): %s",
                fr.search_text[:50], space_id, e,
            )
            # Replace with 0 score so query doesn't crash
            sql = sql.replace(fr.score_placeholder, "0")
            if fr.filter_placeholder in sql:
                sql = sql.replace(fr.filter_placeholder, "TRUE")

    return sql


async def _resolve_single_fuzzy(
    conn,
    space_id: str,
    fr: 'FuzzyRequest',
) -> List[Tuple[str, float]]:
    """Resolve a single fuzzy request → list of (uuid_str, score) pairs.

    Attempts MinHash LSH path first; falls back to pg_trgm if no mapping.
    """
    from vitalgraph.vectorization.fuzzy_mapping_manager import resolve_any_fuzzy_mapping

    rule = await resolve_any_fuzzy_mapping(conn, space_id)

    if rule is not None:
        scored = await _fuzzy_via_minhash(conn, space_id, fr, rule)
        if scored:
            return scored
        # MinHash LSH found no candidates — fall back to pg_trgm
        logger.debug(
            "MinHash LSH returned 0 candidates for '%s'; falling back to pg_trgm",
            fr.search_text[:50],
        )
    return await _fuzzy_via_trgm(conn, space_id, fr)


async def _fuzzy_via_minhash(
    conn,
    space_id: str,
    fr: 'FuzzyRequest',
    rule,
) -> List[Tuple[str, float]]:
    """MinHash LSH band lookup + RapidFuzz scoring.

    Uses the same 3-step candidate retrieval as the entity registry:
      Step 1: Primary LSH band lookup
      Step 2: Phonetic LSH band lookup
      Step 3: Typo variants (edit-distance-1) band lookup
    """
    from vitalgraph.vectorization.fuzzy_core import (
        build_band_queries,
        build_minhash,
        build_typo_variants,
        compute_band_ranges,
        compute_phonetic_codes,
        compute_shingles,
        extract_entity_ids,
        score_with_phonetic,
    )

    # Build MinHash from query string
    shingles = compute_shingles(fr.search_text, rule.shingle_k)
    if not shingles:
        return []

    mh = build_minhash(shingles, rule.num_perm)
    primary_ranges = compute_band_ranges(rule.num_perm, rule.lsh_threshold)

    # Step 1: Primary LSH band lookup
    band_queries = build_band_queries([mh], primary_ranges)
    band_table = f"{space_id}_fuzzy_band"

    hits: Dict[str, int] = {}
    for band_id, hashes in band_queries:
        rows = await conn.fetch(
            f"SELECT entity_key FROM {band_table} "
            f"WHERE band_id = $1 AND band_hash = ANY($2)",
            band_id, hashes,
        )
        for row in rows:
            key = row["entity_key"]
            hits[key] = hits.get(key, 0) + 1

    # Step 2: Phonetic LSH band lookup
    phonetic_codes = compute_phonetic_codes(fr.search_text)
    if phonetic_codes:
        ph_mh = build_minhash(set(phonetic_codes), rule.num_perm)
        ph_ranges = compute_band_ranges(rule.num_perm, 0.3)
        ph_queries = build_band_queries([ph_mh], ph_ranges)
        phonetic_table = f"{space_id}_fuzzy_phonetic_band"

        for band_id, hashes in ph_queries:
            rows = await conn.fetch(
                f"SELECT entity_key FROM {phonetic_table} "
                f"WHERE band_id = $1 AND band_hash = ANY($2)",
                band_id, hashes,
            )
            for row in rows:
                key = row["entity_key"]
                # Strip "P::" prefix so keys are in same format as primary
                if key.startswith("P::"):
                    key = key[3:]
                hits[key] = hits.get(key, 0) + 1

    # Step 3: Typo variants (edit-distance-1) band lookup
    typo_minhashes = build_typo_variants(
        [fr.search_text],
        shingle_k=rule.shingle_k,
        num_perm=rule.num_perm,
        max_variants=50,
    )
    if typo_minhashes:
        typo_queries = build_band_queries(typo_minhashes, primary_ranges)
        for band_id, hashes in typo_queries:
            rows = await conn.fetch(
                f"SELECT entity_key FROM {band_table} "
                f"WHERE band_id = $1 AND band_hash = ANY($2)",
                band_id, hashes,
            )
            for row in rows:
                key = row["entity_key"]
                hits[key] = hits.get(key, 0) + 1

    # Extract candidate entity UUIDs
    candidate_ids = extract_entity_ids(hits)
    if not candidate_ids:
        return []

    # Fetch candidate names from term table
    all_property_uris = rule.primary_uris + rule.alias_uris + rule.include_uris
    if not all_property_uris:
        # Default: hasName
        all_property_uris = ["http://vital.ai/ontology/vital-core#hasName"]

    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"

    # Candidate UUIDs are strings; convert for query
    import uuid as _uuid
    candidate_uuid_objs = []
    for cid in candidate_ids:
        try:
            candidate_uuid_objs.append(_uuid.UUID(cid))
        except ValueError:
            continue

    if not candidate_uuid_objs:
        return []

    # Fetch names for candidates
    rows = await conn.fetch(
        f"SELECT q.subject_uuid, obj_t.term_text "
        f"FROM {quad_table} q "
        f"JOIN {term_table} pred_t ON pred_t.term_uuid = q.predicate_uuid "
        f"JOIN {term_table} obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L' "
        f"WHERE q.subject_uuid = ANY($1) AND pred_t.term_text = ANY($2)",
        candidate_uuid_objs, all_property_uris,
    )

    # Group names by subject
    subject_names: Dict[str, List[str]] = {}
    for row in rows:
        uuid_str = str(row["subject_uuid"])
        text = row["term_text"]
        if text and text.strip():
            subject_names.setdefault(uuid_str, []).append(text.strip())

    # Score each candidate
    query_names = [fr.search_text]
    scored: List[Tuple[str, float]] = []

    for uuid_str, names in subject_names.items():
        result = score_with_phonetic(query_names, names, rule.phonetic_bonus)
        if result.score >= fr.min_score:
            scored.append((uuid_str, round(result.score, 1)))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


async def _fuzzy_via_trgm(
    conn,
    space_id: str,
    fr: 'FuzzyRequest',
) -> List[Tuple[str, float]]:
    """Fallback: pg_trgm similarity() via existing GIN trigram index.

    Used when no fuzzy mapping is configured. Searches hasName values
    for entities similar to the query string.
    """
    quad_table = f"{space_id}_rdf_quad"
    term_table = f"{space_id}_term"
    safe_name = fr.search_text.replace("'", "''")
    threshold = fr.min_score / 100.0

    sql = f"""
        SELECT q.subject_uuid, similarity(obj_t.term_text, '{safe_name}') * 100 AS score
        FROM {quad_table} q
        JOIN {term_table} obj_t ON obj_t.term_uuid = q.object_uuid AND obj_t.term_type = 'L'
        JOIN {term_table} pred_t ON pred_t.term_uuid = q.predicate_uuid
        WHERE pred_t.term_text = 'http://vital.ai/ontology/vital-core#hasName'
          AND similarity(obj_t.term_text, '{safe_name}') >= {threshold:.4f}
        ORDER BY score DESC
        LIMIT 100
    """

    rows = await conn.fetch(sql)
    scored: List[Tuple[str, float]] = []
    seen: Set[str] = set()
    for row in rows:
        uuid_str = str(row["subject_uuid"])
        if uuid_str not in seen:
            seen.add(uuid_str)
            scored.append((uuid_str, round(float(row["score"]), 1)))

    return scored
