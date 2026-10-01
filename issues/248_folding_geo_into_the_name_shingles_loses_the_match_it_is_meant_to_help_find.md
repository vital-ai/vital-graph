# 248 — Folding geo into the name shingles loses the match it is meant to help find

## Status: OPEN, measured 2026-09-29. The dedup question itself is ANSWERED AND
## GOOD: 8 of 8 real duplicate-name clusters pulled from production were fully
## recovered, both members every time. A new record for an existing business
## would be caught. Three misses were run down rather than left as noise, and
## they are three different things — one is this defect, one is arithmetically
## impossible to fix by tuning, and one is a marginal-probability miss that
## tuning WOULD recover. Do not read the 8/8 as "nothing to do" or the three
## misses as "recall is broken"; neither is true.

**Related:** `issues/227` (nothing resolves an entity by identifier, so
concurrent callers mint duplicates — the write-side of the same problem this
read-side recall protects against), `issues/217` (auto-sync ignoring the mapping
and the scope — the same `fuzzy_core` shingling, different consumer)

## What was verified first, because it is the question that matters

The question is not "can the matcher find typos", it is "when a new record
arrives for a business already in the registry, do we catch it". That was tested
directly: 8 actual duplicate-name clusters were pulled out of production and each
name searched — `'Tropical Smoothie Cafe'`, `'Beach Runners Landscaping, Inc.'`,
`'Rocking Rays Auto Detailing And Dent Removal LLC'` and five more.

**8/8 clusters fully recovered, both members returned every time.**

That is the load-bearing result and it should be stated before any of what
follows, because the three misses below are all typo variants — a harder task
than the one the system actually has to do.

## The configuration all of this is measured against

From `vitalgraph/vectorization/fuzzy_core.py` and
`vitalgraph/entity_registry/entity_fuzzy_pg.py`:

    shingle_k              3        character k-shingles over the lowercased name
    num_perm               64       MinHash permutations
    LSH threshold          0.3      Jaccard, sets the band layout
    min_candidates         20       the adaptive floor — see below, it is load-bearing
    max_candidates         5000     hard cap
    min_score              50.0     score floor for a returned match
    match_level            >=90 high, >=70 likely, else possible

## The defect: name alone finds it at rank 1, name plus geo loses it

`'Aur Trdaing Corp'` → `'Aur Trading Corp'`, the same query run two ways:

    name only                      120 candidates   target at RANK 1, score 100
    name + country/region/locality 1,071 candidates target ABSENT

Same index, same target, same typo. Adding geo turned a rank-1 exact-score hit
into a miss, and made the candidate set 8.9x larger while doing it.

This is not a test artefact: the test passes geo **because the server's path
does**. `_name_shingles` folds geo in at BOTH index and query time —
`entity_fuzzy_pg.py:900` and `entity_fuzzy.py:814`, both via
`compute_shingles(name, k, context_tokens=...)`:

```python
def _name_shingles(self, name: str, entity: Dict[str, Any]) -> set:
    """Build shingles for a single name variant, including location tokens."""
    context_tokens = {}
    for field in ('country', 'region', 'locality'):
        val = entity.get(field)
        if val:
            context_tokens[field] = val
    return compute_shingles(name, self.shingle_k, context_tokens=context_tokens)
```

## Why: geo is three fixed shingles, so it compresses every similarity toward 1

`compute_shingles` adds geo as up to three **whole-string** shingles
(`country:us`, `region:fl`, `locality:tampa`) alongside the ~L−k+1 character
shingles of the name. When two records agree on all three, that adds exactly +3
to the intersection and +3 to the union — `I/U` becomes `(I+3)/(U+3)`, for every
pair, regardless of how similar the names are.

Measured directly against the real shingler:

    pair                                             name only   name+geo    change
    'Aur Trdaing Corp' / 'Aur Trading Corp'          0.556       0.619       +0.063
    'Beach Runners Landscaping' / 'Zenith Dental'     0.049       0.114       +0.065

The absolute lift is the same — about +0.065 — but for the true pair that is
+11% and for two entirely unrelated businesses in the same locality it is
**+133%**. The transform is a fixed additive move toward 1.0, so it is nearly
free for a pair that already matches and enormous for a pair that does not. In
the Jaccard space the MinHash bands actually see, it compresses the gap between a
real duplicate and an unrelated same-city entity. 120 → 1,071 candidates is that
compression, counted.

So geo does not reinforce the name signal. It cannot: three tokens shared by
every business in the same city carry no discriminating information about
*which* business, and the only thing they can do to a similarity measure is
raise the floor under all of them at once.

## The adaptive threshold is what turns compression into an ABSENT target

Compression alone would only reorder candidates. What removes the target is
`_extract_entity_ids` (`entity_fuzzy_pg.py:848`):

```python
for level in range(max_level, min_level - 1, -1):
    entity_ids = {eid for eid, cnt in id_best.items() if cnt >= level}
    if len(entity_ids) >= min_candidates:
        break
```

It walks the band-hit count DOWN from the maximum and stops at the **first**
level that yields 20 candidates. With 1,071 same-geo entities crowding the higher
band-hit levels, that floor is satisfied early, the loop never relaxes to the
level where the target sits, and the target is cut.

**The 5,000 cap is NOT the cause** — 1,071 is well under it, and the cap below
that loop never ran. Anyone reading "1,071 candidates, target absent" will reach
for the cap first; it is the wrong place.

## It also penalises a true pair whose geo disagrees or is merely incomplete

The same measurement, run for geo that does not agree:

    'Aur Trdaing Corp' / 'Aur Trading Corp'   geo absent      0.556
                                              geo agrees      0.619
                                              geo DISAGREES   0.478   <- below baseline

    identical name, both records tagged                       1.000
    identical name, ONE record missing locality               0.870   <- no longer identical

When geo differs, the intersection gains nothing and the union gains up to six,
so a true pair scores **below** where it would have with no geo at all. And a
byte-identical business name stops looking identical the moment one of the two
records has patchy location metadata — which, on real registry data, is the
normal case rather than the edge case.

This is the more serious half of the defect. The rank-1-to-absent case is one
query; this is a systematic penalty on exactly the records dedup exists to catch.

## The two misses that are NOT this, and they are not the same as each other

`'Carbal'` → `'Cabral'` and `'Dice Durid'` → `'Dice Druid'`: the LSH never
proposed the target (45 and 1,401 candidates, target in neither). Scored
head-to-head they are 83.3 and 90.0 — `likely` and `high`, both far over the 50
floor. So the scorer was never the problem; candidate generation was.

But measuring the shingles shows these are two different failures:

    'Carbal'     / 'Cabral'       4 and 4 shingles, 0 shared,  jaccard 0.000
    'Dice Durid' / 'Dice Druid'   8 and 8 shingles, 4 shared,  jaccard 0.333

- **`Carbal`/`Cabral` is arithmetically unreachable.** A transposition destroys
  every k-shingle that spans it, and in a six-character token with k=3 that is
  all of them. Jaccard is exactly zero. No threshold, permutation count or band
  layout recovers a pair with no shared shingle — this one is the genuine
  MinHash-LSH recall ceiling, not a backend fault and not tunable.
- **`Dice Durid`/`Dice Druid` is marginal, not impossible.** Its 0.333 clears the
  0.3 LSH threshold, by 0.033. LSH banding is probabilistic, so a pair sitting
  that close to the threshold is found *some* of the time — this miss is a coin
  flip, and more permutations or a lower threshold would recover it. Filing it
  under the same "ceiling" as `Carbal` would be wrong.

The omission variant of both names hits, which is consistent: omission leaves the
surrounding shingles intact (`'Cabal'`/`'Cabral'` share 1, `'Dice Duid'`/
`'Dice Druid'` share 5) where transposition does not.

## What a fix has to decide

The shape of the fix is a choice about **where geo belongs**, and the codebase
already contains the answer to it. `entity_fuzzy_pg` maintains two independent
band families — `primary_band_ranges` and `phonetic_band_ranges`, in separate
tables, unioned into one candidate set. Phonetic codes were kept OUT of the name
MinHash for precisely the reason geo should be: a second signal that can only
ADD candidates cannot displace the ones the first signal found.

In preference order:

1. **Take geo out of `_name_shingles` and apply it at scoring time**, where it
   can break a tie between two similar names without deciding which names get
   considered. Disambiguation is a scoring job; candidate generation is a recall
   job, and the two have opposite failure costs. Requires a reindex.
2. **Give geo its own band family** alongside phonetic, so it can only widen the
   candidate set. More faithful to the current design, more moving parts.
3. Leave the shingles alone and make the adaptive loop stop cutting — but this
   treats the symptom, leaves the `geo disagrees → 0.478` penalty entirely
   unfixed, and (1) makes it unnecessary.

Do NOT "fix" this by raising `min_candidates` or the 5,000 cap. Neither is
involved, and both cost query time for no recall.

## Verify after fixing

- the 8 production clusters stay **8/8**, both members — this is the result that
  must not regress, and it is the whole reason the defect is only a defect
- `'Aur Trdaing Corp'` with geo passed finds `'Aur Trading Corp'` at rank 1,
  matching what name-only already does
- an identical name with one record missing `locality` scores 100, not 87
- a true pair whose geo DISAGREES scores no worse than the same pair with no geo
- `'Dice Durid'` → `'Dice Druid'` becomes reliable rather than a coin flip if
  the permutation count or threshold is touched
- `'Carbal'` → `'Cabral'` is expected to STAY missed; if a change appears to fix
  it, something else changed and the measurement is wrong

## Not established

- **The geo values on the `Aur Trading Corp` record were not captured**, so which
  half of the mechanism dominated that specific miss is unproven. The measurements
  support both paths — compression promoting 1,071 rivals, and a geo disagreement
  actively penalising the target to 0.478 — and the second would explain a rank-1
  pair losing outright more cleanly than the first. Read the two records'
  `country`/`region`/`locality` before assuming which.
- The 8/8 clusters were duplicate *names*; a duplicate business recorded under
  genuinely different names is untested here and is a different problem.
- No timing was taken. 1,071 candidates instead of 120 is 8.9x more scoring work
  per query, and whether that shows up in latency is unmeasured.
- Only `entity_fuzzy_pg` was read closely. `entity_fuzzy.py:814` has the same
  `_name_shingles` and is presumed to share the defect, unverified.
