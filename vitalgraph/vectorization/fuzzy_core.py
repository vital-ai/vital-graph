"""
Shared fuzzy search core algorithms.

Provides MinHash LSH computation, band hashing, RapidFuzz scoring, and
phonetic matching. Used by both:
  - Track A: SPARQL fuzzy search (fuzzy_populator.py, vg_resolve.py)
  - Track B: Entity registry fuzzy search (entity_fuzzy_pg.py)

All functions are stateless and pure (no I/O).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import jellyfish
import numpy as np
from datasketch import MinHash, MinHashLSH
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default tuning parameters
# ---------------------------------------------------------------------------

DEFAULT_NUM_PERM = 64
DEFAULT_LSH_THRESHOLD = 0.3
DEFAULT_SHINGLE_K = 3
DEFAULT_MIN_SCORE = 50.0
DEFAULT_PHONETIC_BONUS = 10.0
DEFAULT_PHONETIC_LSH_THRESHOLD = 0.3
DEFAULT_MAX_CANDIDATES = 5000
DEFAULT_MIN_CANDIDATES = 20


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class FuzzyConfig:
    """Configuration for fuzzy search algorithms."""
    num_perm: int = DEFAULT_NUM_PERM
    lsh_threshold: float = DEFAULT_LSH_THRESHOLD
    shingle_k: int = DEFAULT_SHINGLE_K
    phonetic_bonus: float = DEFAULT_PHONETIC_BONUS
    phonetic_lsh_threshold: float = DEFAULT_PHONETIC_LSH_THRESHOLD
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    min_candidates: int = DEFAULT_MIN_CANDIDATES


# ---------------------------------------------------------------------------
# Band range computation
# ---------------------------------------------------------------------------

def compute_band_ranges(num_perm: int, threshold: float) -> List[Tuple[int, int]]:
    """Compute optimal band ranges for MinHash LSH.

    Uses datasketch's MinHashLSH to determine the optimal band parameters
    (number of bands b and rows per band r) for the given threshold and
    permutation count, then extracts the hashranges.

    Returns:
        List of (start, end) index pairs into the MinHash hashvalues array.
    """
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    return list(lsh.hashranges)


def compute_band_hash(hashvalues: np.ndarray, start: int, end: int) -> bytes:
    """Compute the band hash for a slice of MinHash hashvalues.

    Replicates datasketch's MinHashLSH._H() logic: SHA1 of the packed
    band values.

    Args:
        hashvalues: The MinHash.hashvalues array (uint32 or uint64).
        start: Start index of the band slice.
        end: End index of the band slice.

    Returns:
        SHA1 digest bytes (20 bytes).
    """
    return hashlib.sha1(hashvalues[start:end].tobytes()).digest()


# ---------------------------------------------------------------------------
# Shingling
# ---------------------------------------------------------------------------

def compute_shingles(
    name: str,
    shingle_k: int = DEFAULT_SHINGLE_K,
    context_tokens: Optional[Dict[str, str]] = None,
) -> Set[str]:
    """Build character k-shingles for a name string.

    Args:
        name: The name to shingle.
        shingle_k: Character n-gram size.
        context_tokens: Optional dict of field→value pairs to add as
            context shingles (e.g., {'country': 'US', 'region': 'CA'}).

    Returns:
        Set of shingle strings.
    """
    shingles: Set[str] = set()
    normalized = name.lower().strip()
    if not normalized:
        return shingles

    if len(normalized) < shingle_k:
        shingles.add(normalized)
    else:
        for i in range(len(normalized) - shingle_k + 1):
            shingles.add(normalized[i:i + shingle_k])

    if context_tokens:
        for field_name, val in context_tokens.items():
            if val:
                shingles.add(f"{field_name}:{val.lower().strip()}")

    return shingles


# ---------------------------------------------------------------------------
# MinHash construction
# ---------------------------------------------------------------------------

def build_minhash(shingles: Set[str], num_perm: int = DEFAULT_NUM_PERM) -> MinHash:
    """Build a MinHash signature from a shingle set.

    Args:
        shingles: Set of shingle strings.
        num_perm: Number of permutations.

    Returns:
        MinHash object with computed hashvalues.
    """
    mh = MinHash(num_perm=num_perm)
    for s in shingles:
        mh.update(s.encode('utf-8'))
    return mh


def build_band_entries(
    minhash: MinHash,
    band_ranges: List[Tuple[int, int]],
    entity_key: str,
) -> List[Tuple[int, bytes, str]]:
    """Compute band hash entries for a MinHash signature.

    Args:
        minhash: The MinHash signature.
        band_ranges: List of (start, end) from compute_band_ranges().
        entity_key: The key to associate with each band entry.

    Returns:
        List of (band_id, band_hash_bytes, entity_key) tuples.
    """
    entries: List[Tuple[int, bytes, str]] = []
    for band_id, (start, end) in enumerate(band_ranges):
        bh = compute_band_hash(minhash.hashvalues, start, end)
        entries.append((band_id, bh, entity_key))
    return entries


# ---------------------------------------------------------------------------
# Phonetic codes
# ---------------------------------------------------------------------------

def compute_phonetic_codes(name: str) -> List[str]:
    """Get phonetic codes for a name using Metaphone and Soundex.

    Splits name into words and computes codes for each word (≥2 chars).

    Args:
        name: The name string.

    Returns:
        List of phonetic code strings (e.g., 'M:MKRSFT', 'S:M262').
    """
    codes: Set[str] = set()
    for word in name.split():
        word = word.strip()
        if len(word) < 2:
            continue
        # Generate codes for the word and possessive-stripped variant
        # so "Joe's" produces codes for both "Joe's" and "Joe"
        variants = [word]
        for suffix in ("\u2019s", "'s"):
            if word.endswith(suffix):
                stem = word[: -len(suffix)]
                if len(stem) >= 2:
                    variants.append(stem)
                break
        for v in variants:
            try:
                mp = jellyfish.metaphone(v)
                if mp:
                    codes.add(f"M:{mp}")
                sx = jellyfish.soundex(v)
                if sx:
                    codes.add(f"S:{sx}")
            except Exception:
                pass
    return list(codes)


def phonetic_match(query_names: List[str], candidate_names: List[str]) -> bool:
    """Check if any query name shares a phonetic code with any candidate name.

    Args:
        query_names: List of query name strings.
        candidate_names: List of candidate name strings.

    Returns:
        True if at least one phonetic code is shared.
    """
    query_codes: Set[str] = set()
    for qn in query_names:
        query_codes.update(compute_phonetic_codes(qn))
    if not query_codes:
        return False

    for cn in candidate_names:
        if cn:
            for code in compute_phonetic_codes(cn):
                if code in query_codes:
                    return True
    return False


# ---------------------------------------------------------------------------
# RapidFuzz scoring
# ---------------------------------------------------------------------------

@dataclass
class ScoreResult:
    """Result of scoring a query against a candidate."""
    score: float = 0.0
    match_level: str = 'possible'
    detail: Dict[str, float] = field(default_factory=dict)


def score_pair(query_names: List[str], candidate_names: List[str]) -> ScoreResult:
    """Score query names against candidate names using RapidFuzz.

    Computes composite score as max(token_sort_ratio, token_set_ratio)
    across all name pairs.

    Args:
        query_names: List of query name strings.
        candidate_names: List of candidate name strings.

    Returns:
        ScoreResult with best composite score and detail breakdown.
    """
    best_score = 0.0
    best_detail = {
        'ratio': 0.0,
        'partial_ratio': 0.0,
        'token_sort_ratio': 0.0,
        'token_set_ratio': 0.0,
    }

    for qn in query_names:
        for cn in candidate_names:
            r = fuzz.ratio(qn, cn)
            pr = fuzz.partial_ratio(qn, cn)
            tsr = fuzz.token_sort_ratio(qn, cn)
            tsetr = fuzz.token_set_ratio(qn, cn)
            composite = max(tsr, tsetr)

            if composite > best_score:
                best_score = composite
                best_detail = {
                    'ratio': round(r, 1),
                    'partial_ratio': round(pr, 1),
                    'token_sort_ratio': round(tsr, 1),
                    'token_set_ratio': round(tsetr, 1),
                }

    return ScoreResult(
        score=round(best_score, 1),
        match_level=match_level(best_score),
        detail=best_detail,
    )


def score_with_phonetic(
    query_names: List[str],
    candidate_names: List[str],
    phonetic_bonus: float = DEFAULT_PHONETIC_BONUS,
) -> ScoreResult:
    """Score query vs candidate with optional phonetic bonus.

    Args:
        query_names: Query name strings.
        candidate_names: Candidate name strings.
        phonetic_bonus: Bonus added if phonetic codes match.

    Returns:
        ScoreResult with phonetic bonus applied if applicable.
    """
    result = score_pair(query_names, candidate_names)

    is_phonetic = phonetic_match(query_names, candidate_names)
    if is_phonetic and phonetic_bonus > 0:
        result.score = min(result.score + phonetic_bonus, 100.0)
        result.score = round(result.score, 1)
    result.detail['phonetic_match'] = 1.0 if is_phonetic else 0.0

    # Recompute match level after bonus
    result.match_level = match_level(result.score)
    return result


def match_level(score: float) -> str:
    """Determine match level from score."""
    if score >= 90:
        return 'high'
    elif score >= 70:
        return 'likely'
    return 'possible'


# ---------------------------------------------------------------------------
# Band query helpers
# ---------------------------------------------------------------------------

def build_band_queries(
    minhashes: List[MinHash],
    band_ranges: List[Tuple[int, int]],
) -> List[Tuple[int, List[bytes]]]:
    """Build band query parameters from MinHash signatures.

    For each band, computes the band hash for every MinHash and
    groups them into a single query.

    Args:
        minhashes: List of MinHash signatures to query with.
        band_ranges: Band ranges from compute_band_ranges().

    Returns:
        List of (band_id, [hash1, hash2, ...]) tuples.
    """
    queries: List[Tuple[int, List[bytes]]] = []
    for band_id, (start, end) in enumerate(band_ranges):
        hashes = []
        for mh in minhashes:
            bh = compute_band_hash(mh.hashvalues, start, end)
            hashes.append(bh)
        queries.append((band_id, hashes))
    return queries


def extract_entity_ids(
    hits: Dict[str, int],
    phonetic_keys: bool = False,
    min_candidates: int = DEFAULT_MIN_CANDIDATES,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> Set[str]:
    """Extract entity IDs from band hit counts with adaptive threshold.

    Applies adaptive filter: strict → relaxed until min_candidates reached.

    Args:
        hits: Dict of entity_key → hit_count from band query.
        phonetic_keys: If True, strip phonetic prefix from keys.
        min_candidates: Minimum number of candidates to return.
        max_candidates: Maximum number of candidates to return.

    Returns:
        Set of entity_id strings.
    """
    if not hits:
        return set()

    def _extract_eid(k: str) -> str:
        if phonetic_keys and '::' in k:
            # Strip "P::" prefix
            k = k.split('::', 1)[1]
        # entity_key is "entity_id::variant_idx"
        return k.rsplit('::', 1)[0]

    # Map entity_id → best hit count across all its variants
    id_best: Dict[str, int] = {}
    for k, cnt in hits.items():
        eid = _extract_eid(k)
        if cnt > id_best.get(eid, 0):
            id_best[eid] = cnt

    if not id_best:
        return set()

    # Adaptive filter: strict → relaxed
    max_level = max(id_best.values())
    entity_ids: Set[str] = set()

    for level in range(max_level, 0, -1):
        entity_ids = {eid for eid, cnt in id_best.items() if cnt >= level}
        if len(entity_ids) >= min_candidates:
            break

    # Cap at max
    if len(entity_ids) > max_candidates:
        ranked = sorted(entity_ids, key=lambda eid: id_best[eid], reverse=True)
        entity_ids = set(ranked[:max_candidates])

    return entity_ids


# ---------------------------------------------------------------------------
# Typo variant generation
# ---------------------------------------------------------------------------

def build_typo_variants(
    query_names: List[str],
    shingle_k: int = DEFAULT_SHINGLE_K,
    context_tokens: Optional[Dict[str, str]] = None,
    num_perm: int = DEFAULT_NUM_PERM,
    max_variants: int = 50,
) -> List[MinHash]:
    """Build MinHash signatures for edit-distance-1 typo variants.

    Generates deletion and transposition variants of each word in query names.

    Args:
        query_names: List of query name strings.
        shingle_k: Shingle size.
        context_tokens: Optional context tokens.
        num_perm: MinHash permutations.
        max_variants: Maximum number of variant MinHashes to return.

    Returns:
        List of MinHash objects for typo variants.
    """
    all_minhashes: List[MinHash] = []
    for name in query_names:
        words = name.split()
        for word_idx, word in enumerate(words):
            lower_word = word.lower().strip()
            if len(lower_word) < 3 or len(lower_word) > 8:
                continue
            splits = [(lower_word[:i], lower_word[i:])
                      for i in range(len(lower_word) + 1)]
            # Deletions and transpositions
            variants = (
                {L + R[1:] for L, R in splits if R}
                | {L + R[1] + R[0] + R[2:] for L, R in splits if len(R) > 1}
            )
            for variant in variants:
                variant_words = list(words)
                variant_words[word_idx] = variant
                variant_name = ' '.join(variant_words)
                shingles = compute_shingles(variant_name, shingle_k, context_tokens)
                if shingles:
                    all_minhashes.append(build_minhash(shingles, num_perm))
                if len(all_minhashes) >= max_variants:
                    return all_minhashes
    return all_minhashes


# ---------------------------------------------------------------------------
# LSH key utilities
# ---------------------------------------------------------------------------

def make_lsh_key(entity_id: str, variant_idx: int) -> str:
    """Build compound LSH key: entity_id::variant_index."""
    return f"{entity_id}::{variant_idx}"


def make_phonetic_lsh_key(entity_id: str, variant_idx: int) -> str:
    """Build compound phonetic LSH key: P::entity_id::variant_index."""
    return f"P::{entity_id}::{variant_idx}"


def entity_id_from_lsh_key(lsh_key: str) -> str:
    """Extract entity_id from a compound LSH key."""
    return lsh_key.rsplit('::', 1)[0]
