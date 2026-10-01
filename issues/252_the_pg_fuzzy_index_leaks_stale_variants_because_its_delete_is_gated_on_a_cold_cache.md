# 252 — The PG fuzzy index leaks stale variants because its delete is gated on a per-process cache

## Status: FIXED LOCALLY 2026-09-29, verified end to end.
## **PRODUCTION INDEXES BUILT 2026-09-29** — both valid, both owned by
## `vitalgraph_user`, 214 MB each, measured at 0.172 ms against the old shape's
## 8,041 ms on the same entity and the same 42 rows. The prerequisite is done, so
## the code is now safe to deploy; **the code itself is NOT deployed yet.**
## Production data is clean (audited below) — there was nothing to repair.
##
## Found 2026-09-29 by the `fuzzy check` rewritten in `issues/251`
## on its FIRST RUN, which is the argument for that rewrite. One drifted entity
## in local `sparql_sql_graph`, mechanism read straight out of the source.
## PRODUCTION AUDITED AND CLEAN (three-way exact agreement), and the delete path
## has NEVER RUN there — `n_tup_del` is 0 on both band tables, lifetime.
##
## SEVERITY REVISED DOWN, twice, and both revisions matter:
## a stale row CANNOT return a retracted name (scoring reloads names from the
## database), so this is index pollution with a narrow recall risk, not a wrong
## answer. The first draft claimed otherwise.
##
## AND A SECOND DEFECT FOUND MEASURING THE FIX: the delete path that does exist
## costs 2.5-6.3 seconds per call warm, 22 s cold, INSIDE the delete
## transaction. The first entity deletion on production will block for >10 s
## across both band tables. That is arguably more urgent than the leak.

**Related:** `issues/251` (the check that found it, and why the old one could
not), `issues/249` (a stale variant is a name that matches — the same confident-
wrong-answer surface)

## The shape

`EntityFuzzyIndexPG.add_entity` removes the entity's existing band rows only if
it happens to find the entity in its in-process scoring cache:

    # entity_fuzzy_pg.py:178
    # Remove existing entries if present (for updates)
    if entity_id in self._entity_cache:
        await self.remove_entity(entity_id)

`self._entity_cache` starts **empty in every process** and is populated lazily,
per query, by `_load_candidate_data`. It is a scoring cache, not an index of what
is stored. So the delete fires only for an entity this process has already
scored — which, for a server handling a write to an entity nobody searched for
since the last restart, is never.

`insert_bands` is `ON CONFLICT DO NOTHING`, so unchanged rows collapse
harmlessly. What survives is every band row the new write does *not* reproduce:
a variant index that no longer exists, or one whose name changed.

**There is a second, independent cache dependency in the same path.**
`remove_entity` derives the key list from the cache too, and defaults to one
variant on a miss:

    # entity_fuzzy_pg.py:246
    cached = self._entity_cache.get(entity_id)
    variant_count = (cached or {}).get('_variant_count', 1)
    primary_keys = [self._lsh_key(entity_id, i) for i in range(variant_count)]

So an explicit `remove_entity` on a cold cache deletes `entity_id::0` and leaves
`::1`, `::2`, … behind — every alias variant. The storage layer already has the
right tool for this and it is not called here:
`remove_entity_bands_by_prefix(table, entity_id)` (`entity_fuzzy_storage.py:249`,
`DELETE … WHERE entity_key LIKE $1`).

Net: on the `postgresql` backend an entity **update** can leak stale variants,
and an entity **delete** can leak all but the first. Both silently, both
`ON CONFLICT DO NOTHING`-clean, neither visible to any count of whole-table rows.

## The case found

`e_dd1kf9fu5g`, "Acme Corporation", in local `sparql_sql_graph`. Primary name
plus two active aliases is three variants; the band table holds four:

    entity_key
    -----------------
    e_dd1kf9fu5g::0
    e_dd1kf9fu5g::1
    e_dd1kf9fu5g::2
    e_dd1kf9fu5g::3     <-- no live variant produces this

The alias table explains it: two `active` aliases (`Acme Corp`, `ACME`) and
nineteen `retracted` rows all named `Acme Manufacturing`. A retraction dropped
the variant count from four to three, the re-add ran in a process whose cache did
not hold the entity, no delete fired, and `::3` outlived the name it was built
from.

**What a stale row does NOT do — the first draft of this issue got this wrong.**
`Acme Manufacturing` is in the band index, so a query resembling it produces a
band hit for this entity. It cannot come back as a match name, because
`_load_candidate_data` reloads names from the database on every query, with the
writer's predicates (`ea.status != RETRACTED`, `e.status != DELETED`). Scoring
therefore always runs against live names. `_extract_entity_ids` also collapses an
entity's variants to a single entity id taking its best band-hit count, so extra
variants do not inflate the candidate count either.

So the harm is real but indirect, and it is worth stating narrowly:

* **Candidate pollution.** The entity is pulled into the candidate set for
  queries it no longer resembles, scored against its live names, and dropped by
  `min_score`. Wasted work, no wrong answer.
* **A recall risk at two boundaries.** A stale row can only *raise* an entity's
  hit level. If a level would have yielded 19 candidates and the inflated entity
  makes it 20, `_extract_entity_ids` stops relaxing one level early and a genuine
  weaker match is never pulled in. Same at the `max_candidates` 5,000 cap, where
  ranking is by the inflated `id_best`. Both are narrow, and both are `issues/248`
  territory — that issue is where the early-stop behaviour is characterised.

Which is why this is filed as pollution with a recall risk, not as "the index
returns retracted names".

The per-entity query that locates it, worth keeping because no aggregate count
does:

```sql
with expected as (
  select e.entity_id, 1 + count(ea.alias_id) as variants
  from entity e
  left join entity_alias ea
    on ea.entity_id = e.entity_id and ea.status <> 'retracted'
  where e.status <> 'deleted'
  group by e.entity_id
), banded as (
  select split_part(entity_key,'::',1) as entity_id, count(*) as variants
  from entity_fuzzy_band where band_id = 0
  group by 1
)
select coalesce(e.entity_id, b.entity_id) as entity_id,
       e.variants as expected, b.variants as banded
from expected e
full outer join banded b on b.entity_id = e.entity_id
where coalesce(e.variants,0) <> coalesce(b.variants,0);
```

Band 0 rather than the whole table: every variant is written to every band, so
band 0 carries the full key set at 1/21 of the rows.

**The predicates are the writer's, not `= 'active'`.** `_do_initialize` selects
on `ea.status <> 'retracted'` and `e.status <> 'deleted'`, and a check that
invents its own definition of "should be indexed" reports phantom drift the
moment a third status value exists. This is not hypothetical — `251`'s first
draft of the check used `= 'active'` and the two happen to coincide in local
data only because no third value is present there.

## Why no whole-table count catches it

A leaked variant is an extra `entity_key`, and `entity_fuzzy_hash` is keyed by
`entity_id`, so the hash table stays exactly 1:1 with the entity table while the
band tables drift. Every total I measured for `251` on production — hashed
entities, banded entities, total live rows — is blind to this by construction.
Only the per-entity variant comparison above sees it.

## When it fires — it is intermittent, not absent

`_entity_cache` is populated by `_load_candidate_data`, i.e. by *querying*. So
the delete fires exactly when the entity being written was already scored by this
process. The normal dedup flow — search for duplicates, find the entity, update
it — warms the cache first, and the delete works.

It is the writes that skip the search that leak: a bulk import, a background job,
an API write served by a worker that did not run the search, the first write after
a restart. That is the worst shape for a defect like this, because the code is
correct on the path a developer exercises by hand.

**Production does NOT confirm this, and an earlier draft of this issue claimed it
did.** The reasoning was: 2,051 `add_entity` calls on already-hashed entities,
zero leaked rows, therefore the cache must have been warm. That inference is dead,
because `n_tup_del` is **0** on both band tables — the delete has never removed a
row there, so the warm path has never fired either.

The explanation that survives is that those 2,051 re-adds produced **identical
band rows**. `set_fuzzy_hash` is `ON CONFLICT DO UPDATE SET fuzzy_hash =
EXCLUDED.fuzzy_hash`, which counts as an update even when the value is unchanged,
so 2,051 hash updates do not imply 2,051 content changes. Identical bands hit
`ON CONFLICT DO NOTHING` and change nothing, and no delete is needed.

So "intermittent, works when warm" is a claim from reading the source. It is not
something production has demonstrated either way.

## Production: CLEAN, and latent — audited 2026-09-29

Three-way exact agreement, so there is nothing to repair:

    band_id=0 rows                 1,279,215
    band_id=0 distinct keys        1,279,215     no duplicate-hash leak
    entity + entity_alias          1,279,215     no variant-count leak

Equal rows and distinct keys rules out the name-change leak; agreement with
`entity + entity_alias` rules out the variant-count leak.

It is clean because neither trigger has occurred there:

* **No retracted aliases.** All 7,782 are `active`.
* **No deleted entities.** `entity` holds one status value, `active`, and
  `n_tup_del` on both band tables is **0** — nothing has ever been deleted from
  them.

So the first alias retraction or entity deletion on production leaks silently.
Note `delete_entity` is a **soft** delete (`status = DELETED`) that calls
`remove_entity`, so it goes straight into the `_variant_count` default of 1.

**Watch for it with `entity_admin.py fuzzy check`**, which compares against
entities and aliases separately and would have caught the local case.

## The delete path that exists is unusably slow — measured, not estimated

Found while pricing the fix, and it stands on its own. `EXPLAIN ANALYZE` on
production, 26.86M band rows, matching **zero** rows, in a rolled-back
transaction, 5 runs per shape:

| Shape | Plan | Planner cost | Cold | Warm min / med / max |
|---|---|---|---|---|
| `band_id=? AND band_hash=? AND entity_key=?` | Index Scan, PK | 2.79 | — | **0.085 / 0.092 / 0.095 ms** |
| `entity_key LIKE 'x::%'` | Seq Scan, 1,814 MB heap | 568,636 | 9,826 ms | 2,531 / 2,534 / 2,582 ms |
| `entity_key = ANY([2 keys])` — today's `remove_entity` | Index Scan, PK, non-leading cond | 434,080 | 22,441 ms | 6,260 / 6,266 / 6,600 ms |

**Planner cost inverts the real ordering, so do not rank these by cost.** The seq
scan is 2.5x *faster* than the index scan the planner prefers: a full btree walk in
index order is effectively random access and single-threaded, while the heap scan
is sequential. Every buffer was `shared hit`, so those warm figures are CPU-bound
on a fully cached table — the cold column is what a real cache miss costs.

`= ANY` also scales badly in the key count: one key measured 1,411 ms with 9,174
index searches (a skip scan over the leading columns), two keys 6,260 ms.

**Consequence.** `remove_entity` calls `remove_entity_bands` on *both* band
tables, so one entity removal is two of these — 5-13 seconds warm, ~45 s cold.
`delete_entity` runs it inside `async with conn.transaction()`. **The first entity
deletion on production will hold a write transaction open for over ten seconds**,
and prod's `statement_timeout` is 60 s, so a multi-variant entity on a cold cache
is not far off being killed outright. `n_tup_del = 0` is why nobody has met this.

This is independent of the leak: fixing the gating without fixing the shape turns
a never-executed multi-second scan into one on every write.

## Fix

Ranked by measured write cost, which is the only ranking that survived contact
with `EXPLAIN ANALYZE`:

1. **Index `entity_key` and ungate the delete.** Makes today's `= ANY` a
   leading-column lookup instead of a whole-index skip scan, so the delete goes
   from seconds to sub-millisecond with no change to the write path's shape. At
   **Measured, not estimated** (see below): ~214 MB per band table, and the
   delete drops from 216 ms to 0.105 ms at the scale tested.
   **It is a net space SAVING**: `idx_fuzzy_band_lookup` (1,647 MB) and
   `idx_fuzzy_phonetic_lookup` (1,794 MB) are redundant with their primary keys —
   same leading columns, with `entity_key` present as a key column rather than an
   INCLUDE payload. Verified by dropping one inside a rolled-back transaction: the
   PK serves the same query as an **Index Only Scan**. Production already prefers
   the PK 2,349,291 times to the covering index's 13,296, and on local the covering
   index is the *larger* of the two. Dropping both more than pays for indexing
   `entity_key` on both tables — 3,441 MB recovered against ~428 MB spent, so
   roughly **3 GB freed** while making the delete usable.
2. **Delete via the PK by recomputing the old band hashes** — 0.09 ms, the
   fastest shape, and needs no new index. But it needs the *old* names, and they
   are not recoverable at `add_entity` time: `update_entity` writes the entity row
   first and calls `add_entity` after, so the database already holds the new
   values. `entity_fuzzy_hash` stores only a 32-char digest, which is not
   reversible. So this means persisting the old names or their band hashes — which
   is what `_entity_cache` was for. The defect is that a per-process cache is the
   *only* record of them.
3. **`remove_entity` must stop defaulting `_variant_count` to 1** whatever else
   changes. That default is what makes a cold-cache delete leak silently instead
   of failing, and it is the entity-deletion half of the bug on its own.

**`remove_entity_bands_by_prefix` still should not be used**, but for a different
reason than the first draft gave: not because it is the slowest — it is 2.5x
faster than what `remove_entity` does today — but because it is a whole-table scan
either way, and the collation is `en_US.UTF-8` so `LIKE 'prefix%'` cannot use a
plain btree at all. Once `entity_key` is indexed, `= ANY` beats it outright. One
smaller note if it is ever used: `_` is a LIKE wildcard and every entity id starts
`e_`, so the pattern is marginally looser than a strict prefix match.

Repair for an already-drifted index is `migrate_fuzzy_redis_to_pg.py --rebuild`.

## Option 1 confirmed at scale — measured 2026-09-29

The local entity registry is 37k band rows against production's 26.86M, so this
was measured on a synthetic replica of the production table at exactly 10% scale:
2,686,362 rows, `entity_key` `avg_width` **16** — identical to production — with
the same `(band_id, band_hash, entity_key)` primary key. Heap and PK came out at
10.4x and 10.9x smaller than production's, so the replica is faithful. Dropped
afterwards; the local disk is at 99% capacity, which is why this was done at a
tenth rather than full size.

**Index size — five times smaller than the earlier estimate:**

    entity_key btree, 10% scale            21 MB
    extrapolated, one band table          214 MB
    extrapolated, both band tables        428 MB

The earlier ~1 GB/table guess ignored **btree deduplication**. Every
`entity_key` appears once per band — 21 times — and duplicate keys collapse into
posting lists, which is precisely the case deduplication exists for. So the index
is cheap for exactly the reason the schema looked expensive.

Against 3,441 MB recovered by dropping the two redundant covering indexes, this is
a **net ~3 GB saving**.

**Delete time, controlled, same table, 5 runs each, zero rows matched:**

| | cold | warm min / med / max |
|---|---|---|
| with `entity_key` index | 8.0 ms | **0.079 / 0.105 / 0.154 ms** |
| without | 3,268 ms | 212 / 216 / 221 ms |

~2,000x warm, and the plan changes from a skip scan to `Index Scan using _t252_ek`
with **1 index search** rather than production's 9,174. Production's unindexed
`= ANY` measures 6,260 ms, about 3x worse than a linear extrapolation of the 216 ms
here — consistent with the skip scan degrading as the index grows.

## The root cause, in one sentence

`remove_entity` inherited "read the variant count from `_entity_cache`" from
`EntityFuzzyIndex`, where `_do_initialize` populates that cache for **every**
entity, so it is a complete mirror of the index and the count is authoritative.
`EntityFuzzyIndexPG` changed what the cache *is* — `initialize(skip_if_populated=True)`
returns early without populating anything and `_load_candidate_data` fills it
lazily per query, with entries that do not even carry `_variant_count` — but kept
the contract that read from it. The memory and redis backends do not have this
bug for that reason, and their identical-looking code is correct.

## What was done

`vitalgraph/entity_registry/entity_fuzzy_storage.py`

* `ENTITY_ID_EXPR`, one source of truth for recovering an entity id from an
  entity key, **per table** — see the near-miss below.
* `remove_entity_bands_by_entity_id(table, entity_id)` replaces
  `remove_entity_bands_by_prefix`. Plain equality on the expression, so it is
  indexable under any collation. The old LIKE form is gone rather than left
  as a trap with zero callers.
* `get_indexed_counts` now reads the per-table expression. **I introduced this
  bug earlier in the same session** and it is the same one: it hardcoded field 1,
  so its entity count for the phonetic table was `COUNT(DISTINCT 'P')` = 1. It
  was invisible because `entity_admin` only consumed the variant count.

`vitalgraph/entity_registry/entity_registry_schema.py` — two expression indexes,
`idx_fuzzy_band_entity_id` and `idx_fuzzy_phonetic_entity_id`.

`vitalgraph/entity_registry/entity_fuzzy_pg.py`

* `add_entity` deletes existing band rows **unconditionally**; the
  `if entity_id in self._entity_cache` gate is gone.
* `remove_entity` deletes by entity id and no longer reconstructs a key list
  from a variant count, so there is no default-to-1 to be wrong.

`test_scripts/entity_registry/test_fuzzy_pg.py` — **this suite could not import
at HEAD** and therefore has never run: it imports `compute_entity_hash` from
`entity_fuzzy_pg`, where that name has never existed (it is `compute_fuzzy_hash`
there; `compute_entity_hash` lives in `entity_fuzzy.py`). Renamed. Pre-existing,
unrelated to this fix, but it is why the remove path had no coverage.

### The near-miss worth recording

The first design was a single expression index on `split_part(entity_key,'::',1)`
for both tables. **Primary keys are `entity_id::variant`; phonetic keys are
`P::entity_id::variant`.** Field 1 of a phonetic key is the literal `'P'`, so that
index would have held one distinct value for 26.8M rows and
`DELETE ... WHERE split_part(entity_key,'::',1) = 'P'` — which is what every
phonetic removal would have generated — **matches the entire table**. Caught by
reading `make_phonetic_lsh_key` before building it, not by a test. Hence
`ENTITY_ID_EXPR` as a map rather than an inlined expression.

## Verification, local

* **The drifted entity repairs itself from a COLD cache** — the exact condition
  that leaked. `e_dd1kf9fu5g` held 4 variants against 3 live, in both band
  tables; one `fuzzy sync --entity-id` in a fresh process left exactly 3 in each.
* **`fuzzy check` goes from disagreeing to agreeing**: 1,773 banded variants
  against 1,772 expected, then 1,772 = 1,772.
* **Cold-cache removal deletes every variant**
  (`test_scripts/entity_registry/test_fuzzy_cold_cache_delete.py`): 63 primary + 63 phonetic
  rows (3 variants x 21 bands) → 0 and 0, hash row gone, then restored to 63/63
  by a re-add. Under the old code this would have left 42 rows in each table.
* **Both indexes are used, each with its own field** — `EXPLAIN` shows
  `Index Scan using idx_fuzzy_band_entity_id` with `split_part(..., 1)` and
  `Index Scan using idx_fuzzy_phonetic_entity_id` with `split_part(..., 2)`.
* `test_scripts/entity_registry/test_fuzzy_pg.py` 5/5 once it could import.
* `pytest tests/unit -k "entity or fuzzy"` — 434 passed, 6 skipped, 0 failed.
* `search similar` unchanged.

## Production index build — 2026-09-29

Built as `vitalgraph_user`, not the RDS master. Two things had to be handled and
both would have bitten:

* **`postgres` could not have done it.** It is not a superuser on RDS and is not
  a member of `vitalgraph_user`, which owns the tables — and an index's owner
  follows its table's. Credentials came from the same Secrets Manager secret the
  task definition uses.
* **Prod's `statement_timeout` is 60 s and each build took 48 s.** It would have
  survived, but with twelve seconds to spare on a table that is still growing.
  Built with `SET statement_timeout = 0` for the session. `CREATE INDEX
  CONCURRENTLY`, so writes were never blocked.

        idx_fuzzy_band_entity_id       valid, vitalgraph_user, 214 MB, 48.4 s
        idx_fuzzy_phonetic_entity_id   valid, vitalgraph_user, 214 MB, 48.3 s

**214 MB each — exactly the figure extrapolated from the 10%-scale replica.**
Both carry the correct field, confirmed from `pg_indexes`: `split_part(..., 1)`
for primary and `split_part(..., 2)` for phonetic.

### Measured on production, after `ANALYZE`

Same entity (`e_003n8vjjha`), same 42 rows deleted, rolled back:

| Shape | Plan | Cold | Warm |
|---|---|---|---|
| `split_part(entity_key,'::',1) = $1` | `Index Scan using idx_fuzzy_band_entity_id` | 0.495 ms | **0.169 / 0.172 / 0.178 ms** |
| `entity_key = ANY([...])` (old) | `Index Scan using entity_fuzzy_band_pkey` | 24,593 ms | 8,041 / 8,069 ms |

**~47,000x warm.** The old shape's 24.6 s cold is the number that matters for the
severity claim above: `remove_entity` touches both band tables, so a single
entity deletion on a cold cache was within reach of the 60 s `statement_timeout`,
inside `delete_entity`'s transaction.

Zero-row deletes measure 0.099 / 0.102 / 0.105 ms on primary and
0.092 / 0.097 / 0.098 ms on phonetic, 5 runs each.

**No read-path regression.** The representative band lookup still plans as
`Index Only Scan using idx_fuzzy_band_lookup`, 0.263-0.282 ms warm.

**The visibility map is unchanged and still empty** on `entity_fuzzy_band` (0 of
232,204 pages) and `entity_fuzzy_hash` — `Heap Fetches: 152` for 152 rows. An
earlier read in this session looked faster only because it was cache-warm
(`shared hit` throughout versus `read=9`). Neither the index build nor `ANALYZE`
touches the VM; that is `issues/251`'s VACUUM item and it is still outstanding.

## The incremental re-index path had the SAME leak — found answering "is the cost acceptable"

`_do_initialize` only ever inserts. Its single delete is `truncate_all()`, which
fires only when `since is None`. So `initialize(since=...)` — the incremental
path, and the one `fuzzy sync --since-hours` was wired to and that this issue and
`IMPORT_FORMAT.md` both recommend as the post-import catch-up — **inserted new
band rows and left the old ones**, since `insert_bands` is
`ON CONFLICT DO NOTHING`. A renamed entity kept both sets. Same defect as the
cache-gated delete, by a different route, and the first fix here did not touch it.

Fixed by deleting each page's entity ids before its rows are buffered, batched via
`remove_entity_bands_by_entity_ids`. Safe because pages are ordered by
`entity_id` and advance with `> last_entity_id`, so page id-sets are disjoint and
a page's delete can never remove rows a later flush inserts for an earlier page.

Verified: 21 + 21 stale rows injected for `e_dd1kf9fu5g::9`, `fuzzy check`
reported the drift, `fuzzy sync --since-hours` cleared it, and both tables came
back to zero stale rows with the check clean. Before this change the incremental
path left them untouched.

**Noticed, not fixed** — `last_entity_id = rows[-1]['entity_id']` with
`entity_id > last_entity_id` on the next page means an entity straddling a page
boundary loses its remaining alias rows, so its trailing aliases go unindexed.
`PAGE_SIZE` is 50,000 and aliases are sparse, so it is rare, but it is a real
pre-existing under-indexing bug independent of this issue.

## Is the cost acceptable — measured

Yes. The headline ~47,000x is the wrong number to judge by: it compares against a
shape that **never actually ran on production** (`n_tup_del` = 0). What deploying
this actually costs is the delete that `add_entity` now performs unconditionally
where before it almost always skipped it.

**Per entity write: ~0.27 ms added** — 0.172 ms on the primary table plus
0.095 ms on phonetic, both measured on production.

Against the insert that already happens in the same call: **~100 ms** for 42 rows
on production (96.0 / 97.6 / 99.97 / 101.4 / 104.8 ms over 5 runs). So the added
delete is **~0.3% of the band-write step it accompanies**, before counting the
rest of an entity write — the entity UPDATE, the change log, alias and identifier
handling, `_pg_sync_entity`.

A caution on measuring that insert: three earlier runs read 113.7 / 1.6 / 6.7 ms,
and the fast ones are the misleading ones — they reused **identical** band hashes,
so they hit warm index pages. Real band hashes are MinHash output and effectively
random, which is why ~100 ms with distinct hashes is the representative figure.

**The third index costs nothing measurable on insert.** Isolated on the 10%-scale
replica, with warm-up discarded and the conditions interleaved
(with / without / with again):

| | shared hit | read | dirtied |
|---|---|---|---|
| with the index | 533-623 | 86-102 | 82-85 |
| without | 475-482 | 82-90 | 80-85 |
| with, again | 542-564 | 82-86 | 82-84 |

~60-140 extra buffer touches, all *cached*, with **no additional reads and no
additional dirtied pages** — the 21 rows of one entity share a single expression
value, so dedup puts them in one posting list on one page. Timing ranges overlap
completely and sit under the noise floor of a disk at 99% capacity.

An uncontrolled first attempt at this read 41-282 ms "with" against 5-9 ms
"without" and is recorded here because it is a trap: those runs came immediately
after `CREATE INDEX` + `ANALYZE`, and the cost was cache disruption, not index
maintenance. Warm-up and interleaving removed the effect entirely.

The incremental path is also cheap: deleting a 500-entity page (10,584 band rows)
measured 11.2 / 11.3 / 98.8 ms on production — about 0.022 ms per entity.

## What is NOT done

* **Deploying the code to production.** The indexes are in place, so the
  unconditional delete is now cheap there, but the application still runs the old
  image. Until it is deployed, production keeps leaking on any alias retraction
  or entity deletion — of which there have so far been none.
* **Dropping the two redundant covering indexes** (3,441 MB). Independent of
  this fix, and not required by it — the new indexes are ~214 MB each, so they
  pay for themselves without it.
* **The hash short-circuit.** `add_entity` computes the content hash and writes
  it but never compares it to the stored one; comparing first would make
  production's 2,051 no-op updates free. Left out deliberately: a short-circuit
  on an unchanged hash would also skip the repair for an entity whose bands had
  already drifted, and self-healing on write is worth more right now than the
  saved work.
* Local `sparql_sql_graph` no longer carries the drifted entity — it was the
  test case and repairing it was the test.
