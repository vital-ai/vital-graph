#!/usr/bin/env python3
"""
Standalone unit tests for EntityDedupIndex (MinHash LSH + RapidFuzz).

No database, no server, no network — tests the dedup logic purely in-memory.

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/entity_registry/test_dedup_standalone.py
"""

import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex, build_shingles

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)


class StandaloneDedupTests:
    """Pure in-memory tests for EntityDedupIndex."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.index = None

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            logger.info(f"  ✅ {name}{' - ' + detail if detail else ''}")
        else:
            self.failed += 1
            logger.error(f"  ❌ {name}{' - ' + detail if detail else ''}")

    def _fresh_index(self) -> EntityDedupIndex:
        """Create a fresh in-memory dedup index."""
        return EntityDedupIndex(num_perm=128, threshold=0.3)

    def _seed_index(self, index: EntityDedupIndex):
        """Populate index with a standard set of test entities."""
        entities = [
            ('e_001', {
                'primary_name': 'Acme Corporation',
                'type_key': 'business',
                'country': 'US',
                'region': 'California',
                'aliases': [{'alias_name': 'ACME'}, {'alias_name': 'Acme Corp'}],
            }),
            ('e_002', {
                'primary_name': 'International Business Machines',
                'type_key': 'business',
                'country': 'US',
                'aliases': [{'alias_name': 'IBM'}, {'alias_name': 'Big Blue'}],
            }),
            ('e_003', {
                'primary_name': 'Smith & Associates',
                'type_key': 'business',
                'country': 'US',
                'region': 'New York',
            }),
            ('e_004', {
                'primary_name': 'Smith & Associates',
                'type_key': 'business',
                'country': 'UK',
                'region': 'London',
            }),
            ('e_005', {
                'primary_name': 'Global Solutions Inc',
                'type_key': 'business',
                'country': 'US',
            }),
            ('e_006', {
                'primary_name': 'Bob Martinez',
                'type_key': 'person',
                'country': 'US',
            }),
            ('e_007', {
                'primary_name': 'National Bank of Commerce',
                'type_key': 'business',
                'country': 'US',
                'aliases': [{'alias_name': 'NBC'}],
            }),
            ('e_008', {
                'primary_name': 'National Bank of Commerce Inc',
                'type_key': 'business',
                'country': 'US',
            }),
        ]
        for eid, data in entities:
            index.add_entity(eid, data)
        return entities

    # ------------------------------------------------------------------
    # build_shingles (module-level function)
    # ------------------------------------------------------------------

    def test_build_shingles(self):
        logger.info("\n--- build_shingles ---")

        entity = {'primary_name': 'Acme', 'country': 'US'}
        shingles = build_shingles(entity, k=3)
        self.check("Shingles non-empty", len(shingles) > 0, f"count={len(shingles)}")
        self.check("Contains 'acm' shingle", 'acm' in shingles)
        self.check("Contains 'cme' shingle", 'cme' in shingles)
        self.check("Contains country token", 'country:us' in shingles)

        entity_with_alias = {
            'primary_name': 'Acme',
            'aliases': [{'alias_name': 'ACME Corp'}],
        }
        shingles2 = build_shingles(entity_with_alias, k=3)
        self.check("Alias shingles included", 'acm' in shingles2 and 'cor' in shingles2)

        empty = build_shingles({}, k=3)
        self.check("Empty entity produces empty shingles", len(empty) == 0)

        short = build_shingles({'primary_name': 'AB'}, k=3)
        self.check("Short name (< k) included as-is", 'ab' in short)

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def test_add_and_count(self):
        logger.info("\n--- Add Entity & Count ---")
        idx = self._fresh_index()
        self.check("Empty index has 0 entities", idx.entity_count == 0)

        idx.add_entity('e_001', {'primary_name': 'Acme Corporation', 'country': 'US'})
        self.check("Count is 1 after add", idx.entity_count == 1)

        idx.add_entity('e_002', {'primary_name': 'Widget Corp'})
        self.check("Count is 2 after second add", idx.entity_count == 2)

        # Re-add same entity (update) should not increase count
        idx.add_entity('e_001', {'primary_name': 'Acme Corporation Updated', 'country': 'US'})
        self.check("Re-add same ID keeps count at 2", idx.entity_count == 2)

    def test_remove_entity(self):
        logger.info("\n--- Remove Entity ---")
        idx = self._fresh_index()
        idx.add_entity('e_001', {'primary_name': 'Acme Corporation'})
        idx.add_entity('e_002', {'primary_name': 'Widget Corp'})
        self.check("Count is 2 before remove", idx.entity_count == 2)

        idx.remove_entity('e_001')
        self.check("Count is 1 after remove", idx.entity_count == 1)

        # Removing non-existent entity should not error
        idx.remove_entity('e_nonexistent')
        self.check("Remove non-existent does not error", idx.entity_count == 1)

    def test_clear_index(self):
        logger.info("\n--- Clear Index ---")
        idx = self._fresh_index()
        idx.add_entity('e_001', {'primary_name': 'Acme'})
        idx.add_entity('e_002', {'primary_name': 'Widget'})
        idx._initialized = True

        idx.clear_index()
        self.check("Count is 0 after clear", idx.entity_count == 0)
        self.check("Initialized is False after clear", idx._initialized is False)

    # ------------------------------------------------------------------
    # find_similar / find_similar_by_name
    # ------------------------------------------------------------------

    def test_exact_name_match(self):
        logger.info("\n--- Exact Name Match ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        results = idx.find_similar_by_name("Acme Corporation")
        found_ids = [r['entity_id'] for r in results]
        self.check("Exact name finds entity", 'e_001' in found_ids, f"results={len(results)}")

        if results:
            acme = next(r for r in results if r['entity_id'] == 'e_001')
            self.check("Score >= 95 for exact match", acme['score'] >= 95.0,
                        f"score={acme['score']}")
            self.check("Match level is 'high'", acme['match_level'] == 'high')
            self.check("Has score_detail with ratio", 'ratio' in acme['score_detail'])

    def test_similar_name(self):
        logger.info("\n--- Similar Name ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        results = idx.find_similar_by_name("Acme Corp")
        found_ids = [r['entity_id'] for r in results]
        self.check("Similar name 'Acme Corp' finds Acme Corporation",
                    'e_001' in found_ids, f"results={len(results)}")

        if 'e_001' in found_ids:
            acme = next(r for r in results if r['entity_id'] == 'e_001')
            self.check("Score >= 70 for similar name", acme['score'] >= 70.0,
                        f"score={acme['score']}")

    def test_alias_matching(self):
        logger.info("\n--- Alias Matching ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        # Short acronym
        results = idx.find_similar_by_name("IBM")
        found_ids = [r['entity_id'] for r in results]
        self.check("'IBM' finds International Business Machines",
                    'e_002' in found_ids, f"results={len(results)}")

        # Longer alias
        results2 = idx.find_similar_by_name("Big Blue")
        found_ids2 = [r['entity_id'] for r in results2]
        self.check("'Big Blue' finds IBM entity",
                    'e_002' in found_ids2, f"results={len(results2)}")

    def test_unrelated_name(self):
        logger.info("\n--- Unrelated Name ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        results = idx.find_similar_by_name("Xyloquest Barvonian Plc", min_score=70.0)
        self.check("Unrelated name returns no high matches",
                    len(results) == 0, f"results={len(results)}")

    def test_near_duplicate(self):
        logger.info("\n--- Near Duplicate ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        # e_007 = "National Bank of Commerce", e_008 = "National Bank of Commerce Inc"
        results = idx.find_similar(
            {'primary_name': 'National Bank of Commerce'},
            exclude_ids={'e_007'},
        )
        found_ids = [r['entity_id'] for r in results]
        self.check("Near-dup 'National Bank of Commerce Inc' found",
                    'e_008' in found_ids, f"results={len(results)}")

    def test_empty_query(self):
        logger.info("\n--- Empty Query ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        results = idx.find_similar_by_name("")
        self.check("Empty name returns no results", len(results) == 0)

        results2 = idx.find_similar({'primary_name': ''})
        self.check("Empty entity returns no results", len(results2) == 0)

    def test_min_score_filter(self):
        logger.info("\n--- Min Score Filter ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        results_low = idx.find_similar_by_name("Global Solutions", min_score=30.0)
        results_high = idx.find_similar_by_name("Global Solutions", min_score=90.0)
        self.check("Lower threshold >= higher threshold results",
                    len(results_low) >= len(results_high),
                    f"low={len(results_low)}, high={len(results_high)}")

    def test_type_key_filter(self):
        logger.info("\n--- Type Key Filter ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        # "Bob Martinez" is type_key='person'
        results_all = idx.find_similar_by_name("Bob Martinez", min_score=50.0)
        results_person = idx.find_similar_by_name("Bob Martinez", min_score=50.0, type_key='person')
        results_biz = idx.find_similar_by_name("Bob Martinez", min_score=50.0, type_key='business')

        self.check("Unfiltered finds Bob", any(r['entity_id'] == 'e_006' for r in results_all))
        self.check("type_key='person' finds Bob", any(r['entity_id'] == 'e_006' for r in results_person))
        self.check("type_key='business' excludes Bob",
                    not any(r['entity_id'] == 'e_006' for r in results_biz))

    def test_exclude_ids(self):
        logger.info("\n--- Exclude IDs ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        results = idx.find_similar(
            {'primary_name': 'Acme Corporation'},
            exclude_ids={'e_001'},
        )
        found_ids = [r['entity_id'] for r in results]
        self.check("Self excluded from results", 'e_001' not in found_ids)

    def test_location_differentiation(self):
        logger.info("\n--- Location Differentiation ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        # Both e_003 (US/NY) and e_004 (UK/London) are "Smith & Associates"
        results_us = idx.find_similar_by_name("Smith & Associates", country='US')
        results_uk = idx.find_similar_by_name("Smith & Associates", country='UK')

        us_ids = [r['entity_id'] for r in results_us]
        uk_ids = [r['entity_id'] for r in results_uk]
        self.check("US query finds Smith entities", 'e_003' in us_ids or 'e_004' in us_ids,
                    f"ids={us_ids}")
        self.check("UK query finds Smith entities", 'e_003' in uk_ids or 'e_004' in uk_ids,
                    f"ids={uk_ids}")

        # With country set, the same-country entity should score higher
        if len(results_us) >= 2:
            us_scores = {r['entity_id']: r['score'] for r in results_us}
            if 'e_003' in us_scores and 'e_004' in us_scores:
                self.check("US Smith scores >= UK Smith when querying with country=US",
                            us_scores['e_003'] >= us_scores['e_004'],
                            f"US={us_scores['e_003']}, UK={us_scores['e_004']}")

    def test_find_similar_with_aliases(self):
        logger.info("\n--- find_similar with Query Aliases ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        # Query entity with aliases
        results = idx.find_similar({
            'primary_name': 'International Business Machines Corp',
            'aliases': [{'alias_name': 'IBM'}],
        })
        found_ids = [r['entity_id'] for r in results]
        self.check("Query with aliases finds IBM entity",
                    'e_002' in found_ids, f"results={len(results)}")

    def test_score_detail_structure(self):
        logger.info("\n--- Score Detail Structure ---")
        idx = self._fresh_index()
        self._seed_index(idx)

        results = idx.find_similar_by_name("Acme Corporation")
        if results:
            detail = results[0]['score_detail']
            self.check("score_detail has 'ratio'", 'ratio' in detail)
            self.check("score_detail has 'partial_ratio'", 'partial_ratio' in detail)
            self.check("score_detail has 'token_sort_ratio'", 'token_sort_ratio' in detail)
            self.check("score_detail has 'token_set_ratio'", 'token_set_ratio' in detail)
            self.check("All scores are 0-100",
                        all(0 <= detail[k] <= 100 for k in detail),
                        f"detail={detail}")
        else:
            self.check("Results returned for score detail test", False)

    def test_limit(self):
        logger.info("\n--- Limit ---")
        idx = self._fresh_index()
        # Add many similar entities
        for i in range(20):
            idx.add_entity(f'e_{i:03d}', {'primary_name': f'National Bank Branch {i}'})

        results = idx.find_similar_by_name("National Bank", min_score=30.0, limit=5)
        self.check("Limit caps results at 5", len(results) <= 5,
                    f"count={len(results)}")

    def test_results_sorted_by_score(self):
        logger.info("\n--- Results Sorted by Score ---")
        idx = self._fresh_index()
        # Seed entities with varying similarity to "National Bank"
        idx.add_entity('e_s1', {'primary_name': 'National Bank of Commerce'})
        idx.add_entity('e_s2', {'primary_name': 'National Bank Corp'})
        idx.add_entity('e_s3', {'primary_name': 'National Banking Group'})
        idx.add_entity('e_s4', {'primary_name': 'National Bank of Commerce Inc'})

        results = idx.find_similar_by_name("National Bank of Commerce", min_score=30.0)
        if len(results) >= 2:
            scores = [r['score'] for r in results]
            self.check("Results sorted descending by score",
                        all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1)),
                        f"scores={scores}")
        else:
            self.check("Multiple results for sort test", len(results) >= 2,
                        f"count={len(results)}")

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run_all(self) -> bool:
        logger.info("=" * 60)
        logger.info("EntityDedupIndex Standalone Unit Tests")
        logger.info("(no database, no server, pure in-memory)")
        logger.info("=" * 60)

        self.test_build_shingles()
        self.test_add_and_count()
        self.test_remove_entity()
        self.test_clear_index()
        self.test_exact_name_match()
        self.test_similar_name()
        self.test_alias_matching()
        self.test_unrelated_name()
        self.test_near_duplicate()
        self.test_empty_query()
        self.test_min_score_filter()
        self.test_type_key_filter()
        self.test_exclude_ids()
        self.test_location_differentiation()
        self.test_find_similar_with_aliases()
        self.test_score_detail_structure()
        self.test_limit()
        self.test_results_sorted_by_score()

        total = self.passed + self.failed
        logger.info("=" * 60)
        logger.info(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        logger.info("=" * 60)
        return self.failed == 0


if __name__ == '__main__':
    runner = StandaloneDedupTests()
    success = runner.run_all()
    sys.exit(0 if success else 1)
