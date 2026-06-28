# Entity Dedup: Extensions (Phonetic + Typo Matching)

## Status

| Phase | Status | Notes |
|-------|--------|-------|
| **5a** Plan | ✅ Done | This document |
| **5b** Phonetic LSH index | ✅ Done | Second MinHashLSH with phonetic code shingles |
| **5c** Phonetic scoring integration | ✅ Done | Phonetic bonus in `find_similar` |
| **5d** Typo candidate retrieval | ✅ Done | Edit-distance-1 variants → primary LSH batch query |
| **5e** Tests | ✅ Done | 96/96 in-memory + 22/22 Redis integration |
| **5f** Documentation | ✅ Done | This document updated |

---

## Problem

The base dedup pipeline (MinHash LSH → RapidFuzz) is effective for string-similar names but misses **phonetically similar** names and **single-character typos in short words**:

| Query | Should Match | Base Pipeline |
|-------|-------------|---------------|
| Schmidt | Schmitt, Schmid | ❌ Low string similarity |
| Schneider | Snyder | ❌ Different spelling |
| Johansson | Johanson, Johnson | ❌ Variant transliterations |
| Smtih | Smith | ❌ All trigrams destroyed by transposition |

---

## Architecture: Three-Layer Candidate Retrieval

All index data lives in structured LSH indexes backed by Redis/MemoryDB. **No in-memory dicts for index data.** The only in-memory dict is `_entity_cache` (for RapidFuzz scoring).

```
┌──────────────────────────────────────────────────────────────────┐
│                   Query: "Smtih & Associates"                     │
├──────────────────┬──────────────────┬────────────────────────────┤
│  Primary LSH     │  Phonetic LSH    │  Edit-Distance-1 Variants  │
│  (char trigrams) │  (metaphone +    │  → shingle → batch query   │
│                  │   soundex codes) │    primary LSH              │
│  candidates      │  candidates      │  candidates                │
├──────────────────┴──────────────────┴────────────────────────────┤
│                    Union of all candidates                        │
├──────────────────────────────────────────────────────────────────┤
│  RapidFuzz scoring + Phonetic bonus                               │
├──────────────────────────────────────────────────────────────────┤
│                       Sorted results                              │
└──────────────────────────────────────────────────────────────────┘
```

### Index Structure

| Index | Shingles | Storage | Purpose |
|-------|----------|---------|---------|
| `self.lsh` (primary) | Character trigrams (k=3) | In-memory or Redis/MemoryDB | Near-duplicate string matching |
| `self.phonetic_lsh` | Metaphone + Soundex codes | In-memory or Redis/MemoryDB | Sound-alike name matching |
| `self._entity_cache` | — | In-memory (rebuilt on startup) | RapidFuzz scoring metadata |

### What each layer catches

| Method | Catches | Misses |
|--------|---------|--------|
| Primary LSH | Substrings, reorderings, partial overlap, typos in long words | Short-name typos, phonetic variants |
| Phonetic LSH | Different spellings that sound alike | Typos that change pronunciation |
| Edit-distance-1 → primary LSH | Transpositions, insertions, deletions in short words (3–8 chars) | Phonetic variants, edit distance > 1 |

---

## Implementation Details

### Phonetic LSH (Phase 5b)

A second `MinHashLSH` instance using phonetic codes as shingles instead of character trigrams:

```python
# __init__:
self.lsh = self._create_lsh(self.threshold, self.storage_config)
self.phonetic_lsh = self._create_lsh(
    self.phonetic_threshold,
    self._phonetic_storage_config(),
)
```

- **Threshold**: `DEFAULT_PHONETIC_LSH_THRESHOLD = 0.15` (lower than primary's 0.3 because phonetic code sets are small — 2–6 codes per entity)
- **Shingles**: Per-word Metaphone (`M:` prefix) and Soundex (`S:` prefix) codes
- **Redis namespace**: `_phonetic_storage_config()` appends `_phonetic` to the basename so both LSH indexes coexist in the same Redis instance

```python
@staticmethod
def _phonetic_codes(name: str) -> List[str]:
    """Metaphone + Soundex codes for each word, prefixed for namespace."""
    codes = []
    for word in name.split():
        word = word.strip()
        if len(word) < 2:
            continue
        m = jellyfish.metaphone(word)
        if m:
            codes.append(f"M:{m}")
        s = jellyfish.soundex(word)
        if s:
            codes.append(f"S:{s}")
    return codes
```

One phonetic LSH entry per name variant (same pattern as primary LSH). Keys: `P::entity_id::variant_index`.

### Phonetic Scoring (Phase 5c)

During `find_similar`, after RapidFuzz scoring, a configurable bonus (default `+10.0`, capped at 100) is added when query and candidate share at least one phonetic code:

```python
if self._phonetic_match(query_names, cached):
    result['score'] = min(result['score'] + self.phonetic_bonus, 100.0)
    result['score_detail']['phonetic_match'] = True
```

### Typo Candidate Retrieval (Phase 5d)

At query time, for each word (length 3–8) in the query name:

1. Generate all edit-distance-1 variants (~180–440 per word)
2. Build variant full names (replacing the word with each variant)
3. Shingle each variant name
4. Build MinHash for each
5. **Batch query** the primary LSH using `_batch_query_lsh()`

```python
def _typo_candidates(self, query_names, entity):
    all_minhashes = []
    for name in query_names:
        for word_idx, word in enumerate(words):
            if len(word) < 3 or len(word) > 8:
                continue
            for variant in self._edit_distance_1(word):
                variant_name = name_with_word_replaced(variant)
                shingles = self._name_shingles(variant_name, entity)
                all_minhashes.append(self._build_minhash(shingles))

    raw_keys = self._batch_query_lsh(self.lsh, all_minhashes)
    return {self._entity_id_from_lsh_key(k) for k in raw_keys}
```

**Word length cap (3–8)**: Words shorter than 3 produce too many false matches. Words longer than 8 don't need edit-1 because the primary LSH already catches single typos via sufficient trigram overlap.

### Batch Query for Redis Scalability (Phase 5d)

Without batching, N variants × B bands = thousands of Redis round-trips. The `_batch_query_lsh()` method batches all variant band hashes into one `getmany()` call per band:

```python
def _batch_query_lsh(self, lsh, minhashes):
    """O(B) Redis round-trips regardless of N variants."""
    candidates = set()
    for (start, end), hashtable in zip(lsh.hashranges, lsh.hashtables):
        band_hashes = [lsh._H(mh.hashvalues[start:end]) for mh in minhashes]
        results = hashtable.getmany(*band_hashes)  # single Redis pipeline per band
        for result_set in results:
            for key in result_set:
                candidates.add(key)
    return candidates
```

Datasketch's `RedisListStorage.getmany()` uses `redis.pipeline()` internally, so each `getmany()` call is **one Redis round-trip** containing all keys for that band.

| Metric | Without batching | With batching |
|--------|-----------------|---------------|
| Redis round-trips (286 variants, 37 bands) | **10,582** | **37** |
| Typical query time (100 entities, local Redis) | N/A | 200–600ms |

---

## Redis Key Pattern

Keys are namespaced by environment via `VITALGRAPH_ENVIRONMENT`:

```
{env}_dedup_bucket_{band_index}                      # primary LSH band registry (hash)
{env}_dedup_bucket_{band_index}{band_hash}           # primary LSH band bucket (set)
{env}_dedup_phonetic_bucket_{band_index}             # phonetic LSH band registry (hash)
{env}_dedup_phonetic_bucket_{band_index}{band_hash}  # phonetic LSH band bucket (set)
```

Examples with `VITALGRAPH_ENVIRONMENT=prod`:
- `prod_dedup_bucket_\x00\x00` — primary LSH, band 0 registry
- `prod_dedup_phonetic_bucket_\x00\x05` — phonetic LSH, band 5 registry

For 100 entities: ~7,500 Redis keys (3,579 primary + 3,923 phonetic).

---

## Configuration

### Environment Variables

```bash
# Backend selection
ENTITY_DEDUP_BACKEND=redis           # 'memory' (default) or 'redis'

# Redis connection
ENTITY_DEDUP_REDIS_HOST=localhost
ENTITY_DEDUP_REDIS_PORT=6379
ENTITY_DEDUP_REDIS_USERNAME=         # optional (MemoryDB ACL)
ENTITY_DEDUP_REDIS_PASSWORD=         # optional (MemoryDB AUTH)
ENTITY_DEDUP_REDIS_SSL=false         # 'true' for MemoryDB

# Redis key namespace (uses existing project env var)
VITALGRAPH_ENVIRONMENT=prod          # keys prefixed as prod_dedup_*, prod_dedup_phonetic_*

# Tuning
ENTITY_DEDUP_NUM_PERM=128            # MinHash permutations
ENTITY_DEDUP_THRESHOLD=0.3           # Primary LSH Jaccard threshold
```

### Constructor Parameters

```python
EntityDedupIndex(
    num_perm=128,                     # MinHash permutations
    threshold=0.3,                    # Primary LSH threshold
    shingle_k=3,                      # Character shingle size
    storage_config=None,              # None=in-memory, dict=Redis
    phonetic_bonus=10.0,              # Score bonus for phonetic match
    phonetic_threshold=0.15,          # Phonetic LSH threshold
)
```

---

## Dependencies

```
jellyfish>=1.0.0    # Metaphone + Soundex
datasketch>=1.6.0   # MinHash LSH (with Redis storage)
rapidfuzz>=3.0.0    # String similarity scoring
redis>=4.0.0        # Redis client (only for Redis backend)
```

---

## Test Results

### In-Memory Tests

| Suite | Tests | Status |
|-------|-------|--------|
| `test_dedup_standalone.py` | 44/44 | ✅ All pass |
| `test_dedup_extensions.py` | 52/52 | ✅ All pass |

### Redis Integration Tests

| Suite | Tests | Status | Redis |
|-------|-------|--------|-------|
| `test_dedup_redis.py` | 22/22 | ✅ All pass | localhost:6381 |

### Diagnostic Script

| Suite | Cases | Status |
|-------|-------|--------|
| `test_dedup_typo_diagnostic.py` | 6/6 typo cases | ✅ All found |

Shows full pipeline detail: edit-1 variants, shingle comparisons, LSH hits, RapidFuzz scoring, phonetic bonus.

### Performance (100 entities, local Redis)

| Metric | Time |
|--------|------|
| Index build | ~6s |
| Exact name query | 245ms |
| Phonetic query | 24ms |
| Typo query (edit-distance-1 batch) | 200–600ms |
| `_batch_query_lsh` (50 MinHashes) | 26ms |

---

## Test Files

| File | Purpose |
|------|---------|
| `test_scripts/entity_registry/test_dedup_entities.py` | 100 test entities covering near-dupes, phonetic variants, typos, aliases |
| `test_scripts/entity_registry/test_dedup_standalone.py` | 44 original dedup unit tests (in-memory) |
| `test_scripts/entity_registry/test_dedup_extensions.py` | 52 phonetic + typo extension tests (in-memory) |
| `test_scripts/entity_registry/test_dedup_redis.py` | 22 Redis integration tests |
| `test_scripts/entity_registry/test_dedup_typo_diagnostic.py` | 6 detailed typo pipeline diagnostic cases |

---

## Scaling Notes (10M entities)

- **Primary LSH**: Standard datasketch Redis backend, ~37 Redis calls per query
- **Phonetic LSH**: Same structure, ~37 Redis calls per query
- **Edit-distance-1**: ~300 variants × 37 bands, but batched into **37 Redis pipeline calls**
- **Total per `find_similar`**: ~111 Redis round-trips (3 layers × 37 bands)
- **Entity cache**: In-memory, rebuilt from DB on startup via `initialize()`

All fits on a single MemoryDB node. No separate name index dict, no SymSpell, no pre-computed delete neighborhoods.
