"""
Unit tests for vitalgraph.vectorization.fuzzy_core module.

Pure algorithm tests — no database or I/O required.
Run: /opt/homebrew/anaconda3/envs/vital-graph/bin/python -m pytest test_scripts/test_fuzzy_core_unit.py -v
"""
import pytest
from vitalgraph.vectorization.fuzzy_core import (
    FuzzyConfig,
    build_band_entries,
    build_band_queries,
    build_minhash,
    build_typo_variants,
    compute_band_hash,
    compute_band_ranges,
    compute_phonetic_codes,
    compute_shingles,
    entity_id_from_lsh_key,
    extract_entity_ids,
    make_lsh_key,
    make_phonetic_lsh_key,
    match_level,
    phonetic_match,
    score_pair,
    score_with_phonetic,
)


# ---------------------------------------------------------------------------
# Shingle tests
# ---------------------------------------------------------------------------

class TestComputeShingles:
    def test_basic_shingles_k3(self):
        result = compute_shingles("hello", shingle_k=3)
        assert result == {"hel", "ell", "llo"}

    def test_short_string_below_k(self):
        result = compute_shingles("hi", shingle_k=3)
        assert result == {"hi"}

    def test_empty_string(self):
        result = compute_shingles("")
        assert result == set()

    def test_whitespace_only(self):
        result = compute_shingles("   ")
        assert result == set()

    def test_case_normalization(self):
        result = compute_shingles("Hello", shingle_k=3)
        assert "hel" in result
        assert "Hel" not in result

    def test_context_tokens(self):
        result = compute_shingles("test", shingle_k=3, context_tokens={"country": "US"})
        assert "country:us" in result
        assert "tes" in result

    def test_context_tokens_empty_value(self):
        result = compute_shingles("test", shingle_k=3, context_tokens={"country": ""})
        assert "country:" not in result


# ---------------------------------------------------------------------------
# MinHash tests
# ---------------------------------------------------------------------------

class TestBuildMinhash:
    def test_deterministic(self):
        shingles = {"hel", "ell", "llo"}
        mh1 = build_minhash(shingles, num_perm=64)
        mh2 = build_minhash(shingles, num_perm=64)
        assert (mh1.hashvalues == mh2.hashvalues).all()

    def test_similar_strings_high_similarity(self):
        sh1 = compute_shingles("Microsoft Corporation", shingle_k=3)
        sh2 = compute_shingles("Microsoft Corp", shingle_k=3)
        mh1 = build_minhash(sh1, num_perm=128)
        mh2 = build_minhash(sh2, num_perm=128)
        jaccard = mh1.jaccard(mh2)
        assert jaccard > 0.3  # Similar strings should have non-trivial overlap

    def test_dissimilar_strings_low_similarity(self):
        sh1 = compute_shingles("Microsoft Corporation", shingle_k=3)
        sh2 = compute_shingles("Toyota Motor Company", shingle_k=3)
        mh1 = build_minhash(sh1, num_perm=128)
        mh2 = build_minhash(sh2, num_perm=128)
        jaccard = mh1.jaccard(mh2)
        assert jaccard < 0.3  # Dissimilar strings should have low overlap


# ---------------------------------------------------------------------------
# Band hash tests
# ---------------------------------------------------------------------------

class TestBandHash:
    def test_compute_band_hash_deterministic(self):
        shingles = {"hel", "ell", "llo"}
        mh = build_minhash(shingles, num_perm=64)
        h1 = compute_band_hash(mh.hashvalues, 0, 8)
        h2 = compute_band_hash(mh.hashvalues, 0, 8)
        assert h1 == h2

    def test_different_bands_different_hashes(self):
        shingles = {"hel", "ell", "llo"}
        mh = build_minhash(shingles, num_perm=64)
        h1 = compute_band_hash(mh.hashvalues, 0, 8)
        h2 = compute_band_hash(mh.hashvalues, 8, 16)
        assert h1 != h2

    def test_band_hash_is_20_bytes(self):
        shingles = {"hel", "ell", "llo"}
        mh = build_minhash(shingles, num_perm=64)
        h = compute_band_hash(mh.hashvalues, 0, 8)
        assert len(h) == 20  # SHA1 = 20 bytes


# ---------------------------------------------------------------------------
# Band range tests
# ---------------------------------------------------------------------------

class TestBandRanges:
    def test_ranges_cover_all_perms(self):
        ranges = compute_band_ranges(num_perm=64, threshold=0.3)
        assert len(ranges) > 0
        # All ranges should tile most of [0, 64)
        covered = set()
        for start, end in ranges:
            for i in range(start, end):
                covered.add(i)
        # datasketch may leave <=1 perm uncovered due to integer division
        assert len(covered) >= 62

    def test_ranges_no_overlap(self):
        ranges = compute_band_ranges(num_perm=64, threshold=0.3)
        seen = set()
        for start, end in ranges:
            for i in range(start, end):
                assert i not in seen
                seen.add(i)


# ---------------------------------------------------------------------------
# Band entries tests
# ---------------------------------------------------------------------------

class TestBuildBandEntries:
    def test_builds_correct_count(self):
        shingles = {"hel", "ell", "llo"}
        mh = build_minhash(shingles, num_perm=64)
        ranges = compute_band_ranges(64, 0.3)
        entries = build_band_entries(mh, ranges, "entity1::0")
        assert len(entries) == len(ranges)
        for band_id, bh, key in entries:
            assert isinstance(band_id, int)
            assert isinstance(bh, bytes)
            assert key == "entity1::0"


# ---------------------------------------------------------------------------
# Phonetic tests
# ---------------------------------------------------------------------------

class TestPhoneticCodes:
    def test_basic_codes(self):
        codes = compute_phonetic_codes("Microsoft")
        assert any(c.startswith("M:") for c in codes)
        assert any(c.startswith("S:") for c in codes)

    def test_empty_input(self):
        codes = compute_phonetic_codes("")
        assert codes == []

    def test_short_words_skipped(self):
        codes = compute_phonetic_codes("a b c")
        assert codes == []  # All words < 2 chars


class TestPhoneticMatch:
    def test_match_similar_sounding(self):
        # Smith and Smyth should share phonetic codes
        assert phonetic_match(["Smith"], ["Smyth"])

    def test_no_match_different(self):
        assert not phonetic_match(["Microsoft"], ["Toyota"])


# ---------------------------------------------------------------------------
# RapidFuzz scoring tests
# ---------------------------------------------------------------------------

class TestScorePair:
    def test_exact_match(self):
        result = score_pair(["Microsoft"], ["Microsoft"])
        assert result.score == 100.0
        assert result.match_level == "high"

    def test_similar_match(self):
        result = score_pair(["Microsoft Corp"], ["Microsoft Corporation"])
        assert result.score > 70.0
        assert result.match_level in ("high", "likely")

    def test_no_match(self):
        result = score_pair(["Apple Inc"], ["Toyota Motor"])
        assert result.score < 50.0

    def test_detail_populated(self):
        result = score_pair(["test"], ["test"])
        assert "ratio" in result.detail
        assert "token_sort_ratio" in result.detail


class TestScoreWithPhonetic:
    def test_phonetic_bonus_applied(self):
        # "Googel" vs "Google" — similar sounding
        no_bonus = score_pair(["Googel"], ["Google"])
        with_bonus = score_with_phonetic(["Googel"], ["Google"], phonetic_bonus=10.0)
        assert with_bonus.score >= no_bonus.score

    def test_phonetic_bonus_capped_at_100(self):
        result = score_with_phonetic(["Microsoft"], ["Microsoft"], phonetic_bonus=50.0)
        assert result.score <= 100.0


# ---------------------------------------------------------------------------
# Match level tests
# ---------------------------------------------------------------------------

class TestMatchLevel:
    def test_high(self):
        assert match_level(95.0) == "high"

    def test_likely(self):
        assert match_level(75.0) == "likely"

    def test_possible(self):
        assert match_level(50.0) == "possible"


# ---------------------------------------------------------------------------
# Entity ID extraction tests
# ---------------------------------------------------------------------------

class TestExtractEntityIds:
    def test_basic_extraction(self):
        hits = {
            "uuid1::0": 3,
            "uuid1::1": 2,
            "uuid2::0": 3,
        }
        result = extract_entity_ids(hits, min_candidates=1, max_candidates=100)
        assert "uuid1" in result
        assert "uuid2" in result

    def test_adaptive_threshold(self):
        hits = {
            "uuid1::0": 5,
            "uuid2::0": 1,
        }
        # With high min_candidates, should include both
        result = extract_entity_ids(hits, min_candidates=2, max_candidates=100)
        assert len(result) == 2

    def test_max_candidates_cap(self):
        hits = {f"uuid{i}::0": 1 for i in range(100)}
        result = extract_entity_ids(hits, min_candidates=1, max_candidates=10)
        assert len(result) <= 10

    def test_empty_hits(self):
        assert extract_entity_ids({}) == set()

    def test_phonetic_keys(self):
        hits = {
            "P::uuid1::0": 2,
            "P::uuid2::0": 1,
        }
        result = extract_entity_ids(hits, phonetic_keys=True, min_candidates=1)
        assert "uuid1" in result


# ---------------------------------------------------------------------------
# LSH key tests
# ---------------------------------------------------------------------------

class TestLshKeys:
    def test_make_lsh_key(self):
        assert make_lsh_key("abc-123", 0) == "abc-123::0"
        assert make_lsh_key("abc-123", 2) == "abc-123::2"

    def test_make_phonetic_lsh_key(self):
        assert make_phonetic_lsh_key("abc-123", 0) == "P::abc-123::0"

    def test_entity_id_from_lsh_key(self):
        assert entity_id_from_lsh_key("abc-123::0") == "abc-123"
        assert entity_id_from_lsh_key("abc-123::2") == "abc-123"


# ---------------------------------------------------------------------------
# Typo variant tests
# ---------------------------------------------------------------------------

class TestTypoVariants:
    def test_generates_variants(self):
        # Word must be 3-8 chars for typo variant generation
        variants = build_typo_variants(["Goolge"], shingle_k=3, num_perm=64)
        assert len(variants) > 0

    def test_max_variants_cap(self):
        variants = build_typo_variants(
            ["Microsoft Corporation"], shingle_k=3, num_perm=64, max_variants=5
        )
        assert len(variants) <= 5

    def test_short_words_skipped(self):
        variants = build_typo_variants(["ab"], shingle_k=3, num_perm=64)
        assert len(variants) == 0


# ---------------------------------------------------------------------------
# Band queries tests
# ---------------------------------------------------------------------------

class TestBuildBandQueries:
    def test_builds_queries(self):
        shingles = compute_shingles("test", shingle_k=3)
        mh = build_minhash(shingles, num_perm=64)
        ranges = compute_band_ranges(64, 0.3)
        queries = build_band_queries([mh], ranges)
        assert len(queries) == len(ranges)
        for band_id, hashes in queries:
            assert isinstance(band_id, int)
            assert len(hashes) == 1  # One MinHash → one hash per band


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
