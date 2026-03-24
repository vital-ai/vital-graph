#!/usr/bin/env python3
"""
Diagnostic script showing the full typo candidate retrieval pipeline in detail.

For each test case, shows:
  1. The query (with typo) and the expected target entity
  2. Edit-distance-1 variants generated for each query word
  3. Which variants produce shingles that match the primary LSH
  4. Shingle comparison: query shingles vs target entity shingles (overlap & Jaccard)
  5. RapidFuzz scoring breakdown
  6. Final result: found or missed, with score and match level

Usage:
    /opt/homebrew/anaconda3/envs/vital-graph/bin/python test_scripts/entity_registry/test_dedup_typo_diagnostic.py
"""

import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from rapidfuzz import fuzz
from vitalgraph.entity_registry.entity_dedup import EntityDedupIndex
from test_scripts.entity_registry.test_dedup_entities import TEST_ENTITIES

# ---------------------------------------------------------------
# Test cases: (query_with_typo, target_entity_id, description)
# ---------------------------------------------------------------
TYPO_CASES = [
    {
        'query': 'Smith & Associates',
        'typo_query': 'Smtih & Associates',
        'target_id': 'e_006',
        'description': 'Transposition: Smtih → Smith (5-char word, all trigrams change)',
    },
    {
        'query': 'Acme Corporation',
        'typo_query': 'Acme Corporaton',
        'target_id': 'e_001',
        'description': 'Deletion: Corporaton (missing i) → Corporation',
    },
    {
        'query': 'Microsoft Corporation',
        'typo_query': 'Microsft Corporation',
        'target_id': 'e_053',
        'description': 'Deletion: Microsft (missing o) → Microsoft',
    },
    {
        'query': 'Anderson Consulting',
        'typo_query': 'Andreson Consulting',
        'target_id': 'e_063',
        'description': 'Transposition: Andreson → Anderson',
    },
    {
        'query': 'Deutsche Bank AG',
        'typo_query': 'Deutche Bank AG',
        'target_id': 'e_070',
        'description': 'Deletion: Deutche (missing s) → Deutsche',
    },
    {
        'query': 'James Williams',
        'typo_query': 'James Willams',
        'target_id': 'e_076',
        'description': 'Deletion: Willams (missing i) → Williams',
    },
]


def fmt_set(s, max_items=20):
    """Format a set for display, truncating if large."""
    items = sorted(s)
    if len(items) > max_items:
        return '{' + ', '.join(items[:max_items]) + f', ... ({len(items)} total)' + '}'
    return '{' + ', '.join(items) + '}'


def run_diagnostic():
    print("=" * 80)
    print("TYPO CANDIDATE RETRIEVAL — DETAILED DIAGNOSTIC")
    print("=" * 80)

    # Build index
    t0 = time.time()
    idx = EntityDedupIndex(num_perm=128, threshold=0.3, phonetic_bonus=10.0)
    for eid, data in TEST_ENTITIES:
        idx.add_entity(eid, data)
    print(f"\nIndex built: {idx.entity_count} entities in {time.time() - t0:.2f}s\n")

    for case_num, case in enumerate(TYPO_CASES, 1):
        typo_query = case['typo_query']
        correct_query = case['query']
        target_id = case['target_id']

        target_data = None
        for eid, data in TEST_ENTITIES:
            if eid == target_id:
                target_data = data
                break

        print("=" * 80)
        print(f"CASE {case_num}: {case['description']}")
        print(f"  Correct spelling : {correct_query}")
        print(f"  User typed (typo): {typo_query}")
        print(f"  Target entity    : {target_id} → {target_data['primary_name']}")
        print("-" * 80)

        # ---------------------------------------------------------------
        # Step 1: Show shingle comparison (typo query vs target entity)
        # ---------------------------------------------------------------
        entity_dict = {'primary_name': typo_query, 'country': target_data.get('country')}
        query_shingles = idx._name_shingles(typo_query, entity_dict)
        target_shingles = idx._name_shingles(target_data['primary_name'], target_data)

        overlap = query_shingles & target_shingles
        union = query_shingles | target_shingles
        jaccard = len(overlap) / len(union) if union else 0

        print(f"\n  [1] SHINGLE COMPARISON (typo query vs target)")
        print(f"      Query shingles ({len(query_shingles)}): {fmt_set(query_shingles)}")
        print(f"      Target shingles ({len(target_shingles)}): {fmt_set(target_shingles)}")
        print(f"      Overlap ({len(overlap)}): {fmt_set(overlap)}")
        print(f"      Jaccard similarity: {jaccard:.3f}  (LSH threshold=0.3)")
        if jaccard >= 0.3:
            print(f"      → Primary LSH LIKELY catches this directly")
        else:
            print(f"      → Primary LSH may MISS this — edit-distance-1 variants needed")

        # ---------------------------------------------------------------
        # Step 2: Show edit-distance-1 variants for the typo word
        # ---------------------------------------------------------------
        print(f"\n  [2] EDIT-DISTANCE-1 VARIANTS")
        words = typo_query.split()
        for word_idx, word in enumerate(words):
            lower_word = word.lower().strip()
            if len(lower_word) < 3 or len(lower_word) > 8:
                print(f"      Word '{word}' (len={len(lower_word)}): SKIPPED (outside 3-8 range)")
                continue

            all_variants = idx._edit_distance_1(lower_word)
            print(f"      Word '{word}' (len={len(lower_word)}): {len(all_variants)} edit-1 variants generated")

            # Check which variants are the corrected spelling
            correct_words = correct_query.lower().split()
            correct_word = correct_words[word_idx] if word_idx < len(correct_words) else None
            if correct_word and correct_word in all_variants:
                print(f"      ✅ Correct spelling '{correct_word}' IS among the variants")
            elif correct_word:
                print(f"      ❌ Correct spelling '{correct_word}' NOT among variants (edit distance > 1?)")

        # ---------------------------------------------------------------
        # Step 3: Show which variant queries hit the primary LSH
        # ---------------------------------------------------------------
        print(f"\n  [3] VARIANT LSH QUERIES (variants that find the target)")
        hits_for_target = []
        total_lsh_queries = 0
        total_lsh_hits = 0

        for word_idx, word in enumerate(words):
            lower_word = word.lower().strip()
            if len(lower_word) < 3 or len(lower_word) > 8:
                continue

            for variant in idx._edit_distance_1(lower_word):
                variant_words = list(words)
                variant_words[word_idx] = variant
                variant_name = ' '.join(variant_words)

                shingles = idx._name_shingles(variant_name, entity_dict)
                if not shingles:
                    continue

                mh = idx._build_minhash(shingles)
                total_lsh_queries += 1
                try:
                    raw_keys = idx.lsh.query(mh)
                except ValueError:
                    continue

                if raw_keys:
                    total_lsh_hits += 1
                    matched_ids = {idx._entity_id_from_lsh_key(k) for k in raw_keys}
                    if target_id in matched_ids:
                        hits_for_target.append({
                            'variant_word': variant,
                            'variant_name': variant_name,
                            'matched_ids': matched_ids,
                        })

        print(f"      Total LSH queries: {total_lsh_queries}")
        print(f"      Queries with any hit: {total_lsh_hits}")
        print(f"      Queries that found target ({target_id}): {len(hits_for_target)}")
        if hits_for_target:
            # Show first few
            for i, hit in enumerate(hits_for_target[:5]):
                print(f"        [{i+1}] variant='{hit['variant_word']}' → name='{hit['variant_name']}'")
                print(f"            matched entities: {sorted(hit['matched_ids'])}")
            if len(hits_for_target) > 5:
                print(f"        ... and {len(hits_for_target) - 5} more")

        # ---------------------------------------------------------------
        # Step 4: Show the shingle detail for the best-matching variant
        # ---------------------------------------------------------------
        if hits_for_target:
            best = hits_for_target[0]
            best_shingles = idx._name_shingles(best['variant_name'], entity_dict)
            best_overlap = best_shingles & target_shingles
            best_union = best_shingles | target_shingles
            best_jaccard = len(best_overlap) / len(best_union) if best_union else 0

            print(f"\n  [4] BEST VARIANT SHINGLE DETAIL")
            print(f"      Variant name: '{best['variant_name']}'")
            print(f"      Variant shingles ({len(best_shingles)}): {fmt_set(best_shingles)}")
            print(f"      Overlap with target ({len(best_overlap)}): {fmt_set(best_overlap)}")
            print(f"      Jaccard: {best_jaccard:.3f}")

        # ---------------------------------------------------------------
        # Step 5: RapidFuzz scoring
        # ---------------------------------------------------------------
        print(f"\n  [5] RAPIDFUZZ SCORING (typo query vs target names)")
        target_names = [target_data['primary_name']]
        for alias in (target_data.get('aliases') or []):
            if alias.get('alias_name'):
                target_names.append(alias['alias_name'])

        for tn in target_names:
            r = fuzz.ratio(typo_query, tn)
            pr = fuzz.partial_ratio(typo_query, tn)
            tsr = fuzz.token_sort_ratio(typo_query, tn)
            tsetr = fuzz.token_set_ratio(typo_query, tn)
            composite = max(tsr, tsetr)
            print(f"      '{typo_query}' vs '{tn}':")
            print(f"        ratio={r:.1f}  partial={pr:.1f}  token_sort={tsr:.1f}  token_set={tsetr:.1f}  → composite={composite:.1f}")

        # Phonetic match check
        query_codes = set()
        for word in typo_query.split():
            query_codes.update(idx._phonetic_codes(word))
        target_codes = set()
        for tn in target_names:
            for word in tn.split():
                target_codes.update(idx._phonetic_codes(word))
        shared_codes = query_codes & target_codes
        is_phonetic = len(shared_codes) > 0
        print(f"      Phonetic codes (query): {sorted(query_codes)}")
        print(f"      Phonetic codes (target): {sorted(target_codes)}")
        print(f"      Shared phonetic codes: {sorted(shared_codes)}")
        print(f"      Phonetic match: {is_phonetic}  → bonus: +{10.0 if is_phonetic else 0.0}")

        # ---------------------------------------------------------------
        # Step 6: Final result from find_similar
        # ---------------------------------------------------------------
        print(f"\n  [6] FINAL RESULT (find_similar_by_name)")
        t1 = time.time()
        results = idx.find_similar_by_name(
            typo_query, country=target_data.get('country'), min_score=30.0,
        )
        elapsed_ms = (time.time() - t1) * 1000
        found_ids = {r['entity_id'] for r in results}

        if target_id in found_ids:
            match = next(r for r in results if r['entity_id'] == target_id)
            print(f"      ✅ FOUND target {target_id} (rank {results.index(match)+1}/{len(results)})")
            print(f"         score={match['score']}  level={match['match_level']}")
            print(f"         detail={match['score_detail']}")
        else:
            print(f"      ❌ MISSED target {target_id}")
            print(f"         Results returned: {len(results)}")
            if results:
                print(f"         Top match: {results[0]['entity_id']} ({results[0]['primary_name']}) score={results[0]['score']}")

        print(f"      Query time: {elapsed_ms:.0f}ms")
        print()

    print("=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    run_diagnostic()
