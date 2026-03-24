#!/usr/bin/env python3
"""
Standalone tests for EntityDedupIndex phonetic + typo extensions.

Tests phonetic matching (Metaphone + Soundex via jellyfish),
phonetic scoring bonus, and edit-distance-1 typo candidate retrieval.

Uses the 100 test entities from test_dedup_entities.py.

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/entity_registry/test_dedup_extensions.py
"""

import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex
from test_scripts.entity_registry.test_dedup_entities import TEST_ENTITIES

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


class DedupExtensionTests:
    """Tests for phonetic + typo matching extensions."""

    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            logger.info(f"  ✅ {name}{' - ' + detail if detail else ''}")
        else:
            self.failed += 1
            logger.error(f"  ❌ {name}{' - ' + detail if detail else ''}")

    def _build_index(self) -> EntityDedupIndex:
        """Build index from all 100 test entities."""
        idx = EntityDedupIndex(num_perm=128, threshold=0.3, phonetic_bonus=10.0)
        for eid, data in TEST_ENTITIES:
            idx.add_entity(eid, data)
        return idx

    # ------------------------------------------------------------------
    # _phonetic_codes unit tests
    # ------------------------------------------------------------------

    def test_phonetic_codes_basic(self):
        logger.info("\n--- _phonetic_codes: basic ---")
        codes = EntityDedupIndex._phonetic_codes("Schneider")
        self.check("Schneider has codes", len(codes) > 0, f"codes={codes}")

        codes2 = EntityDedupIndex._phonetic_codes("Snyder")
        self.check("Snyder has codes", len(codes2) > 0, f"codes={codes2}")

        # Soundex should match: both S536
        soundex_codes1 = {c for c in codes if c.startswith("S:")}
        soundex_codes2 = {c for c in codes2 if c.startswith("S:")}
        shared_soundex = soundex_codes1 & soundex_codes2
        self.check("Schneider/Snyder share soundex code", len(shared_soundex) > 0,
                    f"shared={shared_soundex}")

    def test_phonetic_codes_multi_word(self):
        logger.info("\n--- _phonetic_codes: multi-word ---")
        codes = EntityDedupIndex._phonetic_codes("Johnson Partners")
        self.check("Multi-word produces multiple codes", len(codes) >= 2,
                    f"count={len(codes)}")

    def test_phonetic_codes_short_word(self):
        logger.info("\n--- _phonetic_codes: short words ---")
        codes = EntityDedupIndex._phonetic_codes("A B")
        self.check("Single-char words produce no codes", len(codes) == 0)

        codes2 = EntityDedupIndex._phonetic_codes("AB")
        self.check("Two-char word produces codes", len(codes2) > 0)

    # ------------------------------------------------------------------
    # _edit_distance_1 unit tests
    # ------------------------------------------------------------------

    def test_edit_distance_1_basic(self):
        logger.info("\n--- _edit_distance_1: basic ---")
        variants = EntityDedupIndex._edit_distance_1("cat")
        self.check("Variants non-empty", len(variants) > 0, f"count={len(variants)}")
        self.check("Deletion 'at' in variants", "at" in variants)
        self.check("Deletion 'ct' in variants", "ct" in variants)
        self.check("Deletion 'ca' in variants", "ca" in variants)
        self.check("Transposition 'act' in variants", "act" in variants)
        self.check("Replacement 'bat' in variants", "bat" in variants)
        self.check("Insertion 'acat' in variants", "acat" in variants)
        self.check("Original 'cat' in variants (replace c->c)", "cat" in variants)

    def test_edit_distance_1_count(self):
        logger.info("\n--- _edit_distance_1: count ---")
        # For a word of length n: deletions=n, transpositions=n-1,
        # replacements=26*n, insertions=26*(n+1)
        # cat (n=3): 3 + 2 + 78 + 104 = 187 but some overlap
        variants = EntityDedupIndex._edit_distance_1("cat")
        self.check("Variant count in expected range", 100 < len(variants) < 200,
                    f"count={len(variants)}")

    # ------------------------------------------------------------------
    # Phonetic index lifecycle
    # ------------------------------------------------------------------

    def test_phonetic_lsh_populated(self):
        logger.info("\n--- Phonetic LSH populated ---")
        idx = self._build_index()
        # Verify phonetic LSH returns candidates for a known phonetic code
        codes = EntityDedupIndex._phonetic_codes("Schneider")
        mh = idx._build_minhash(set(codes))
        results = idx.phonetic_lsh.query(mh)
        self.check("Phonetic LSH returns candidates for Schneider",
                    len(results) > 0, f"count={len(results)}")

    def test_remove_cleans_phonetic_lsh(self):
        logger.info("\n--- Remove cleans phonetic LSH ---")
        idx = EntityDedupIndex(num_perm=128, threshold=0.3)
        idx.add_entity('x1', {'primary_name': 'Uniquephonetic'})
        codes = EntityDedupIndex._phonetic_codes("Uniquephonetic")
        mh = idx._build_minhash(set(codes))
        results_before = idx.phonetic_lsh.query(mh)
        self.check("Entity in phonetic LSH after add", len(results_before) > 0)

        idx.remove_entity('x1')
        results_after = idx.phonetic_lsh.query(mh)
        self.check("Entity removed from phonetic LSH", len(results_after) == 0)

    def test_clear_clears_all_indexes(self):
        logger.info("\n--- Clear clears all indexes ---")
        idx = self._build_index()
        idx.clear_index()
        # Verify phonetic LSH is empty by querying a known code
        codes = EntityDedupIndex._phonetic_codes("Schneider")
        mh = idx._build_minhash(set(codes))
        results = idx.phonetic_lsh.query(mh)
        self.check("Phonetic LSH empty after clear", len(results) == 0)
        self.check("Entity cache empty after clear", idx.entity_count == 0)

    # ------------------------------------------------------------------
    # Phonetic candidate retrieval
    # ------------------------------------------------------------------

    def test_phonetic_schneider_snyder(self):
        """Cluster 4: Schneider/Snyder/Snider share soundex S536."""
        logger.info("\n--- Phonetic: Schneider/Snyder/Snider ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Schneider Industries", min_score=30.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Schneider finds Snyder (e_015) via phonetic",
                    'e_015' in found_ids, f"found={found_ids}")
        self.check("Schneider finds Snider (e_016) via phonetic",
                    'e_016' in found_ids, f"found={found_ids}")

    def test_phonetic_schmidt_schmitt(self):
        """Cluster 5: Schmidt/Schmitt share phonetic codes."""
        logger.info("\n--- Phonetic: Schmidt/Schmitt ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Schmidt Manufacturing", min_score=30.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Schmidt finds Schmitt (e_019)", 'e_019' in found_ids,
                    f"found={found_ids}")

    def test_phonetic_johnson_johansson(self):
        """Cluster 8: Johnson/Johansson/Johnsen share phonetic codes."""
        logger.info("\n--- Phonetic: Johnson/Johansson ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Johnson & Partners", min_score=30.0)
        found_ids = {r['entity_id'] for r in results}
        # Johnson (JHNSN metaphone) and Johansson (JHNSN metaphone) should share codes
        self.check("Johnson finds Johansson (e_031) or Johanson (e_032)",
                    'e_031' in found_ids or 'e_032' in found_ids,
                    f"found={found_ids}")

    def test_phonetic_thompson_thomson(self):
        """Cluster 17: Thompson/Thomson share phonetic codes."""
        logger.info("\n--- Phonetic: Thompson/Thomson ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Thompson Reuters", min_score=30.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Thompson finds Thomson (e_068)", 'e_068' in found_ids,
                    f"found={found_ids}")

    def test_phonetic_anderson_andersen(self):
        """Cluster 16: Anderson/Andersen share phonetic codes."""
        logger.info("\n--- Phonetic: Anderson/Andersen ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Anderson Consulting", min_score=30.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Anderson finds Andersen (e_064)", 'e_064' in found_ids,
                    f"found={found_ids}")

    # ------------------------------------------------------------------
    # Phonetic scoring bonus
    # ------------------------------------------------------------------

    def test_phonetic_bonus_applied(self):
        """Phonetic matches should get the bonus added to their score."""
        logger.info("\n--- Phonetic bonus applied ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Schneider Industries", min_score=30.0)
        for r in results:
            if r['entity_id'] == 'e_014':  # exact match
                self.check("Exact match has phonetic_match=True",
                            r['score_detail'].get('phonetic_match') is True)
            if r['entity_id'] in ('e_015', 'e_016'):  # phonetic variants
                self.check(f"{r['entity_id']} has phonetic_match in score_detail",
                            'phonetic_match' in r['score_detail'],
                            f"detail={r['score_detail']}")

    def test_phonetic_bonus_value(self):
        """Score with phonetic bonus should be higher than without."""
        logger.info("\n--- Phonetic bonus value ---")
        idx_with = EntityDedupIndex(num_perm=128, threshold=0.3, phonetic_bonus=10.0)
        idx_without = EntityDedupIndex(num_perm=128, threshold=0.3, phonetic_bonus=0.0)
        for eid, data in TEST_ENTITIES:
            idx_with.add_entity(eid, data)
            idx_without.add_entity(eid, data)

        # Query something with a phonetic match
        results_with = idx_with.find_similar_by_name("Schneider Industries", min_score=30.0)
        results_without = idx_without.find_similar_by_name("Schneider Industries", min_score=30.0)

        # Find a phonetic-only match (Snyder)
        score_with = None
        score_without = None
        for r in results_with:
            if r['entity_id'] == 'e_015':
                score_with = r['score']
        for r in results_without:
            if r['entity_id'] == 'e_015':
                score_without = r['score']

        if score_with is not None and score_without is not None:
            self.check("Phonetic bonus increases score",
                        score_with > score_without,
                        f"with={score_with}, without={score_without}")
        else:
            self.check("Snyder found in both indexes",
                        score_with is not None and score_without is not None,
                        f"with={score_with}, without={score_without}")

    def test_phonetic_match_flag(self):
        """score_detail should contain phonetic_match flag."""
        logger.info("\n--- Phonetic match flag ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Acme Corporation", min_score=50.0)
        if results:
            self.check("phonetic_match key in score_detail",
                        'phonetic_match' in results[0]['score_detail'])
        else:
            self.check("Results returned", False)

    # ------------------------------------------------------------------
    # Typo candidate retrieval
    # ------------------------------------------------------------------

    def test_typo_acme_corporaton(self):
        """Cluster 1: 'Acme Corporaton' (missing 'i') should match."""
        logger.info("\n--- Typo: Acme Corporaton ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Acme Corporation", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Acme Corporaton' (e_004)", 'e_004' in found_ids,
                    f"found={found_ids}")

    def test_typo_acme_corproation(self):
        """Cluster 1: 'Acme Corproation' (transposition) should match."""
        logger.info("\n--- Typo: Acme Corproation ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Acme Corporation", min_score=40.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Acme Corproation' (e_005)", 'e_005' in found_ids,
                    f"found={found_ids}")

    def test_typo_smtih(self):
        """Cluster 2: 'Smtih & Associates' (transposition) should match."""
        logger.info("\n--- Typo: Smtih & Associates ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Smith & Associates", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Smtih' (e_009)", 'e_009' in found_ids,
                    f"found={found_ids}")

    def test_typo_international_buisness(self):
        """Cluster 3: 'International Buisness Machines' (typo) should match."""
        logger.info("\n--- Typo: International Buisness ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("International Business Machines", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Buisness' (e_013)", 'e_013' in found_ids,
                    f"found={found_ids}")

    def test_typo_microsft(self):
        """Cluster 14: 'Microsft Corporation' (missing 'o') should match."""
        logger.info("\n--- Typo: Microsft ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Microsoft Corporation", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Microsft' (e_054)", 'e_054' in found_ids,
                    f"found={found_ids}")

    def test_typo_andreson(self):
        """Cluster 16: 'Andreson Consulting' (transposition) should match."""
        logger.info("\n--- Typo: Andreson ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Anderson Consulting", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Andreson' (e_066)", 'e_066' in found_ids,
                    f"found={found_ids}")

    def test_typo_deutche(self):
        """Cluster 18: 'Deutche Bank AG' (missing 's') should match."""
        logger.info("\n--- Typo: Deutche ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Deutsche Bank AG", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Deutche' (e_072)", 'e_072' in found_ids,
                    f"found={found_ids}")

    def test_typo_james_willams(self):
        """Cluster 20: 'James Willams' (missing 'i') should match."""
        logger.info("\n--- Typo: James Willams ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("James Williams", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds typo 'Willams' (e_079)", 'e_079' in found_ids,
                    f"found={found_ids}")

    # ------------------------------------------------------------------
    # Negative / noise tests
    # ------------------------------------------------------------------

    def test_unrelated_no_match(self):
        """Truly unrelated entities should NOT match each other at high thresholds."""
        logger.info("\n--- Unrelated entities ---")
        idx = self._build_index()
        # Use a high min_score to filter out low-quality candidates
        results = idx.find_similar_by_name("Sahara Desert Tours", min_score=70.0)
        found_ids = {r['entity_id'] for r in results}
        non_cluster = found_ids - {'e_085'}
        self.check("No spurious high-score matches for 'Sahara Desert Tours'",
                    len(non_cluster) == 0, f"found={found_ids}")

    def test_distinct_tech_companies(self):
        """Apple/Google/Amazon should NOT match Microsoft."""
        logger.info("\n--- Distinct tech companies ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("Microsoft Corporation", min_score=70.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Apple (e_055) not a high match", 'e_055' not in found_ids,
                    f"found={found_ids}")
        self.check("Google (e_056) not a high match", 'e_056' not in found_ids,
                    f"found={found_ids}")
        self.check("Amazon (e_057) not a high match", 'e_057' not in found_ids,
                    f"found={found_ids}")

    # ------------------------------------------------------------------
    # Combined retrieval
    # ------------------------------------------------------------------

    def test_combined_lsh_phonetic_typo(self):
        """A query should find matches from all three retrieval methods."""
        logger.info("\n--- Combined LSH + phonetic + typo ---")
        idx = self._build_index()
        # "Schneider Industries" should find:
        #   - e_014 (exact, LSH) - Schneider Industries
        #   - e_015 (phonetic)   - Snyder Industries
        #   - e_016 (phonetic)   - Snider Industries
        #   - e_017 (typo)       - Schnider Industries
        results = idx.find_similar_by_name("Schneider Industries", min_score=30.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds exact (e_014)", 'e_014' in found_ids)
        self.check("Finds phonetic Snyder (e_015)", 'e_015' in found_ids)
        self.check("Finds phonetic Snider (e_016)", 'e_016' in found_ids)
        self.check("Finds typo Schnider (e_017)", 'e_017' in found_ids)

    def test_combined_national_bank(self):
        """National Bank cluster should find near-dups and typos."""
        logger.info("\n--- Combined: National Bank ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("National Bank of Commerce", min_score=30.0)
        found_ids = {r['entity_id'] for r in results}
        self.check("Finds exact (e_025)", 'e_025' in found_ids)
        self.check("Finds near-dup Inc (e_026)", 'e_026' in found_ids)
        self.check("Finds typo Natonal (e_029)", 'e_029' in found_ids)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_short_name_matching(self):
        """Short names (3 chars) should still work via phonetic/name index."""
        logger.info("\n--- Short name matching ---")
        idx = self._build_index()
        results = idx.find_similar_by_name("IBM", min_score=50.0)
        found_ids = {r['entity_id'] for r in results}
        # e_011 has alias IBM, e_012 is "IBM"
        self.check("IBM finds e_011 or e_012",
                    'e_011' in found_ids or 'e_012' in found_ids,
                    f"found={found_ids}")

    def test_entity_count_correct(self):
        """Index should have exactly 100 entities."""
        logger.info("\n--- Entity count ---")
        idx = self._build_index()
        self.check("100 entities in index", idx.entity_count == 100,
                    f"count={idx.entity_count}")

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run_all(self) -> bool:
        logger.info("=" * 60)
        logger.info("EntityDedupIndex Extension Tests (Phonetic + Typo)")
        logger.info("(100 test entities, pure in-memory)")
        logger.info("=" * 60)

        # Unit tests
        self.test_phonetic_codes_basic()
        self.test_phonetic_codes_multi_word()
        self.test_phonetic_codes_short_word()
        self.test_edit_distance_1_basic()
        self.test_edit_distance_1_count()

        # Index lifecycle
        self.test_phonetic_lsh_populated()
        self.test_remove_cleans_phonetic_lsh()
        self.test_clear_clears_all_indexes()

        # Phonetic candidate retrieval
        self.test_phonetic_schneider_snyder()
        self.test_phonetic_schmidt_schmitt()
        self.test_phonetic_johnson_johansson()
        self.test_phonetic_thompson_thomson()
        self.test_phonetic_anderson_andersen()

        # Phonetic scoring
        self.test_phonetic_bonus_applied()
        self.test_phonetic_bonus_value()
        self.test_phonetic_match_flag()

        # Typo candidate retrieval
        self.test_typo_acme_corporaton()
        self.test_typo_acme_corproation()
        self.test_typo_smtih()
        self.test_typo_international_buisness()
        self.test_typo_microsft()
        self.test_typo_andreson()
        self.test_typo_deutche()
        self.test_typo_james_willams()

        # Negative tests
        self.test_unrelated_no_match()
        self.test_distinct_tech_companies()

        # Combined retrieval
        self.test_combined_lsh_phonetic_typo()
        self.test_combined_national_bank()

        # Edge cases
        self.test_short_name_matching()
        self.test_entity_count_correct()

        total = self.passed + self.failed
        logger.info("=" * 60)
        logger.info(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        logger.info("=" * 60)
        return self.failed == 0


if __name__ == '__main__':
    runner = DedupExtensionTests()
    success = runner.run_all()
    sys.exit(0 if success else 1)
