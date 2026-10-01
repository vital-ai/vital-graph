# 249 — A third of the business entities are indexed under a placeholder name, and every one of them is a match for every other one

## Status: OPEN, measured 2026-09-29, NOT BUILT. **Decided: these strings must
## not enter the index at all.** Found as a data observation while measuring
## `248` and split out because it is a different defect with a different fix.
## The scores and the phonetic collapse below are EXACT — computed by calling
## the shipped functions, not estimated. The band-collision counts are from a
## synthetic 20k population and are labelled as such where they appear.

**Related:** `issues/248` (the geo shingles, same subsystem, same measurement
session — read it first, it establishes the configuration and the 8/8 recall
result this must not regress), `issues/252` (the band delete path, **read before
implementing** — it removed the variant-count reconstruction this issue's first
draft warned about, and its `fuzzy check` invariant is the trap that replaces
it), `issues/251` (the `fuzzy check` tool itself, and a sync that reported
success while writing nothing), `issues/227` (nothing resolves an entity by
identifier, so concurrent callers mint duplicates — placeholder names are
exactly the records that cannot be resolved by name), `issues/219` and
`issues/245` (the vectorization precedent for deliberate SKIPPING, and what goes
wrong when a skip is silent)

**Tree state when measured:** `252`'s fix was present but uncommitted. Nothing in
it touches shingling, banding or scoring, so every number below is unaffected by
it — but the *implementation notes* were rewritten after reading it, and the
first draft's headline trap was stale. See "Two traps".

## The data

209,580 of 643,791 active business entities — **32.6%** — have a `primary_name`
of the form `company-<digits>`. It is a placeholder minted by the Salesforce
backfill, not a business name.

Nothing in this repo generates them; the format is upstream. Whether the backfill
should be producing them at all is a separate question and is **not** what this
issue proposes to change. The names stay in `entity.primary_name` — they are the
source value and the UI needs something to render. What changes is whether they
reach the fuzzy index.

## 1. This is not noise, it is a 209,580-member false-positive clique

The tempting reading is "fuzzy matching over placeholders is meaningless, so the
results are garbage in a corner nobody reads". That understates it. Every
placeholder pair scores **above the default `min_score=50.0`**, so every one of
these entities is a returned match for every other one. Exact, via `score_pair`:

    company-4471000  vs  company-4471008     93.3   high
    company-4471000  vs  company-4471900     93.3   high
    company-447100   vs  company-4471000     96.6   high
    company-4471000  vs  company-1234567     66.7   possible

Two entirely unrelated businesses are a **`high`** match on the shared `company-`
prefix alone. The digits are 7 of 15 characters and RapidFuzz over the whole
string cannot outvote the prefix. The *worst* case — maximally different digits —
is still `possible`, which clears the floor.

So `find_similar` on any placeholder returns `limit` confident duplicates, all
wrong, every time. This matters wherever the output is consumed rather than
eyeballed: `entity_registry_endpoint.py:1051`, `entity_admin.py:764`, and
`find_duplicates_for_entity`. `227` wants an identifier-based resolve path partly
because name-based resolution mints duplicates; for a third of the business
entities, name-based resolution is not merely unreliable, it is uniformly wrong
in the confident direction.

## 2. The phonetic index collapses all 209,580 into one cell

`compute_phonetic_codes` drops digits. Every placeholder, regardless of its
digits or their count, produces the identical code pair:

    'company-4471000'  ->  ['S:C515', 'M:KMPN']
    'company-1234567'  ->  ['S:C515', 'M:KMPN']
    'company-99'       ->  ['S:C515', 'M:KMPN']

Identical code set → identical MinHash → identical band hash in **all 21
phonetic bands** (21 bands × 3 rows at `num_perm=64`, `threshold=0.3`). This is
deterministic, not probabilistic: the phonetic table holds 21 cells of 209,580
`entity_key`s each.

`query_bands` (`entity_fuzzy_storage.py:141`) has **no `LIMIT`** — `max_candidates`
is applied afterwards, in `_extract_entity_ids`, in Python. So a single band hit
on one of those cells pulls 209,580 rows into a `Counter`, and
`query_bands_progressive` queries 3 bands per batch.

**And real names reach that cell.** Measured, by counting shared phonetic bands
against the placeholder signature:

    'Company'                  21/21 bands
    'Compana'                  21/21 bands
    'Campana Inc'               4/21 bands
    'Campania LLC'              3/21 bands
    'The Company'               1/21 bands
    'Companion Care'            0/21
    'Acme Industrial Supply'    0/21

A real business named `Campana Inc` shares 4 of 21 phonetic bands with the
entire placeholder population. The phonetic step only runs when primary LSH
returns fewer than `min_candidates=20` — an uncommon name, which is exactly the
case where recall matters most — so this fires rarely and expensively, and the
rarity is why it has not been noticed.

## 3. What this does NOT do — real-name queries are clean in the primary index

Stated so nobody over-claims the above. A mixed index was built (20k synthetic
real names + 20k `company-<7 digits>`) and probed over the first two progressive
batches:

    real-name query      mean 1,029 rows/query   worst 3,814   placeholder share   0.0%
    placeholder query    mean 1,535 rows/query   worst 6,342   placeholder share 100.0%

The two populations are **disjoint in primary band space**. Placeholders are not
crowding real candidates out of ordinary lookups, and the 8/8 production recall
result in `248` is not threatened by them. This is a waste-and-correctness
problem, not a live recall regression — which is why it is `248`'s sibling and
not its cause.

Caveat on that number, because it is the weakest measurement here: the "real"
names came from a 12×10×6 word vocabulary, which is far less diverse than actual
business names. It establishes that the *prefix* does not bridge the two
populations. It does not establish a 0% floor for real data.

## 4. The waste

At 21 primary bands and 21 phonetic bands, 209,580 placeholder names cost
**~8.8M band rows** — 4,401,180 in each of `entity_fuzzy_band` and
`entity_fuzzy_phonetic_band` — plus their share of every full rebuild.

The larger cost is the sweep: a dedup pass over the registry issues 209,580
queries that each do real band work and return uniformly wrong results. That is
a third of the sweep's runtime spent producing output that must then be
discarded.

Hot cells in the *primary* index, synthetic at 20k (so read the shape, not the
magnitude): the largest single band cell held 9,325 of 20,000 names. The
placeholders collide heavily with each other because they share 8 of ~13
trigrams.

## What to do

**Skip them at index time. Store the fact as a column; do not re-derive it in
the indexer.**

The reason to prefer a column over a regex evaluated during indexing: there are
**two** index implementations that must agree exactly — `_compute_entity_bands`
(bulk rebuild) and `add_entity` (incremental). A heuristic evaluated in both is a
drift source, and `compute_fuzzy_hash` would not notice a policy change, so
tuning the rule would silently take effect only on a full rebuild. A column is
also auditable: "how many did we exclude, and which" becomes SQL.

1. **Name-level, not entity-level.** `entity.is_placeholder_name` and
   `entity_alias.is_placeholder_name`, both `NOT NULL DEFAULT FALSE`. An entity
   can have a placeholder `primary_name` and a real alias; the band key is
   already `entity_id::variant_idx`, so per-name skipping falls out. Fits the
   idempotent `MIGRATIONS` list (`entity_registry_schema.py:410`) — add the
   column, then one backfill `UPDATE`.
2. **Writer supplies it; a policy fills the gap.** `create_entity(...,
   is_placeholder_name=None)` and the alias equivalent, through the API and CLI.
   When `None`, resolve against a short list of *known upstream placeholder
   formats* — not a general "is this string useful" heuristic, which would
   silently suppress real dedup. Persist the resolved boolean.
3. **Skip on both sides.** Index side: `continue` in the name loops in
   `_compute_entity_bands` and `add_entity`. Query side: drop them in
   `_get_name_variants`, so a sweep skips a third of its queries outright
   instead of doing the expensive thing and discarding the answer.

Do NOT fix this by filtering at result time. It is the cheapest edit and it keeps
all 8.8M rows, the rebuild cost, and the whole per-query cost — it only hides the
output.

## Two traps

Both are in the *bookkeeping* around the index, not in the skip itself. Neither
is caught by a test that only checks "does the placeholder stop matching".

### 1. `fuzzy check` will alarm forever, and its advice will not help

This is the one to handle first, because it silently converts a working health
monitor into a broken one. `entity_admin.py:575` asserts two equalities:

    expected_variants = pg_count + alias_count      # active entities + active aliases
    banded_entities   == pg_count
    banded_variants   == expected_variants

Skipping 209,580 names breaks **both**. `banded_variants` drops by the number of
skipped names; `banded_entities` drops by the number of entities left with no
indexable name at all (placeholder primary *and* no real alias — likely most of
the 209,580). `fuzzy check` would then report a ~209,580 deficit and print

    Rebuild with: python apps/fuzzy_index/migrate_fuzzy_redis_to_pg.py --rebuild

which cannot fix it, because the deficit is now intentional. That check is the
tool `251` rewrote and `252` used to find a real leak on its first run, and it
currently reports prod **clean** (1,279,215 = 1,279,215). Breaking it costs more
than this issue saves.

**So the expected-count arithmetic has to subtract non-indexable names in the
same commit** — `pg_count` and `alias_count` become counts of *indexable* names,
and the report should print what it excluded rather than silently netting it out.
An operator needs to be able to tell "209,580 deliberately skipped" from
"209,580 missing".

### 2. Add the flag to `compute_fuzzy_hash`'s inputs

It currently hashes type/name/location/aliases. Flipping the flag on an unchanged
name would not move the hash, so a manual "this one really is a real name, index
it" correction would never reach the sync path.

### Retracted from the first draft

The first draft led with "do not compact the variant indices, because
`remove_entity` reconstructs keys as `range(_variant_count)`". **That is no longer
true of the PG backend** — `252` replaced the reconstruction with a delete by
entity id through an expression index (`entity_fuzzy_pg.py:260`), and the comment
there explains why the count is not knowable from a per-process cache. Numbering
is now irrelevant to removal on that path.

It is still true of `entity_fuzzy.py` — lines 889 and 975 still read
`_variant_count` — which `252` argues is correct there, since that backend's
`_do_initialize` populates the cache for every entity. So the guidance survives
in narrowed form: **keep `_variant_count` at `len(all_names)` and `continue` on
skipped names rather than renumbering**, which costs nothing and keeps the memory
backend's removal a superset. Do not rely on the PG backend's immunity if you
touch the shared shape.

## Verify after fixing

- `248`'s 8 production clusters stay **8/8**, both members. Unrelated mechanism,
  but it is the result that must not regress and it is cheap to re-run.
- `find_similar('company-4471000')` returns **0** candidates, not 10 confident
  wrong ones.
- The 21 phonetic cells of 209,580 are gone: no `band_hash` in
  `entity_fuzzy_phonetic_band` has more than a few thousand `entity_key`s.
- A real name sharing the placeholder phonetic code — `Campana Inc` is the
  measured case — still finds its own genuine matches.
- Band-row count drops by roughly 8.8M after a full rebuild, and the rebuild
  gets measurably faster. Take the before number first.
- An entity with a placeholder `primary_name` and a REAL alias is still findable
  by that alias. This is the case that a naive entity-level flag breaks.
- **`fuzzy check` still reports ✅**, against both prod and the test stack, and
  its output states the excluded count explicitly. If it reports a deficit, trap
  1 was not handled and the monitor is now useless.
- Delete an entity whose name was skipped and confirm no orphan bands survive, on
  **both** backends — the PG path deletes by entity id and should be immune, the
  memory path reconstructs from `_variant_count` and is not.

## Not established

  * **Whether the backfill should mint these names at all.** Upstream question,
    deliberately out of scope. If it stops, this fix is still needed for the
    209,580 already stored.
  * **Whether `company-<digits>` is the only placeholder format in the registry.**
    Only the one reported was measured. The backfill may have others, and a
    second format would not be caught by a rule written for this one. Worth a
    `GROUP BY` over name shapes before choosing the policy's pattern list.
  * **The primary-index hot-cell magnitudes** are synthetic at 20k, not measured
    against production. The phonetic collapse and the scores are exact; these are
    not.
  * **The real-name contamination floor.** 0.0% was measured against a synthetic
    vocabulary (see section 3). Re-run against real names before relying on it.
  * **Whether the vector path should skip them too.** `build_entity_search_text`
    puts `primary_name` first, so a third of the corpus is currently spending an
    embedding call on `company-4471000`. The same flag would serve it. Not
    proposed here — different subsystem, different reindex, and `245` shows how
    a skip rule that is slightly wrong deletes rows it should have kept.
  * **No timing was taken.** The costs above are row counts and query counts, not
    measured latency.

## Reproducing these numbers

`test_scripts/entity_registry/test_fuzzy_prod_check.py` re-measures them. READ-ONLY — every query is a SELECT or
a `find_similar` call, so it is safe against production.

    python test_scripts/entity_registry/test_fuzzy_prod_check.py              # all checks
    python test_scripts/entity_registry/test_fuzzy_prod_check.py --offline    # the arithmetic only, no database

A known-open defect reports **KNOWN**, not a failure: both of these issues are
open and unbuilt, and a checker that exits non-zero forever is one people learn
to ignore. It exits non-zero only for a REGRESSION, and reports **FIXED** when a
documented defect stops reproducing — which means the issue's numbers no longer
describe the system and should be re-measured before they are trusted.

The duplicate-name clusters are DISCOVERED, not hardcoded: this file names three
of its eight and says "five more", so a fixed list could not reproduce the 8/8.
Discovery also keeps customer names out of the checker.

Verified on 2026-10-01 to reproduce the jaccard values (0.000 and 0.333), both
head-to-head scores (83.3 and 90.0) and both omission-variant shingle counts
(1 and 5) exactly as recorded above.
