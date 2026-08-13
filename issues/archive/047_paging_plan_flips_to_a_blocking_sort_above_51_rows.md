# The O(page) Paging Plan Flips to a Blocking Sort Above ~51 Rows

## Status: FIXED 2026-08-08 (page and capped count)

> **MEASURED ON A 1 GB BUFFER POOL — see `issues/081`.** At risk: the 19/52/174 thresholds, which come from cost estimates effective_cache_size feeds. `shared_buffers` was 1 GB on a 64 GB machine against queries touching 400,000+ buffers; raising it to 16 GB moved a comparable query 16,411 ms -> 616 ms with no code change. Plan shapes, row counts and buffer counts are unaffected.

The two-phase page now fences its own statement. `emit_slice._emit_two_phase`
sets `ctx.needs_ordered_scan`, which reaches the executor via
`GenerateResult`, and `execute_sparql_query` runs that statement inside a
transaction with `SET LOCAL enable_sort = off`.

Measured on the 22.4M-quad production copy, warm.

**These numbers were re-measured 2026-08-08 after discovering the first set was
contaminated.** Three backends from a `timeout`-killed psql had been scanning
`rdf_quad` continuously for 18 hours on the same cluster — an accidental live
instance of `issues/044` — and the copy has since gained the 4-key index it
previously lacked entirely. The original figures (48,034 ms at page 100) carried
both that contention and a missing covering index, so they overstated the fence's
effect by roughly 40x. On a quiet cluster with schema-matching indexes:

| page_size | unfenced | fenced |
|---|---|---|
| 100 | 1,196 ms | **3 ms** |
| 250 | 1,179 ms | **8 ms** |

~400x, not the ~12,000x first reported. Plan-shape and threshold findings are
unaffected — those come from plain EXPLAIN, which does not depend on concurrent
load.

Cost is now proportional to the page (4 → 8 → 36 ms for 100 → 250 → 1000),
which is the property `issues/040` claimed and only ever delivered below the
cliff. Result set unchanged: 34,423 rows, 0 duplicates, deduplicated md5
`dd0b028c…` identical to the set-based path.

**Why a GUC rather than `pg_hint_plan`.** Verified against the production RDS
instance: `pg_hint_plan` 1.8.0 *is* available on RDS PostgreSQL 18.4 and is on
the allowed `shared_preload_libraries` list. But the hint that would fix the
cause — `Rows()`, correcting the estimate — does not apply to this shape: the
EXISTS runs as a SubPlan filter, so there is no join relation to correct
(`Rows hint requires at least two relations`). Every other applicable hint is
plan-banning, which `SET LOCAL` already does at the same cost and with no
extension, no static parameter change and no reboot.

`enable_sort` is a discouragement, not a prohibition — if a sort is the only
way to plan a query, the planner still uses one — so the fence cannot make a
statement unplannable.

**The capped count, via the same mechanism.**
`build_entity_count_query_sparql` produced `COUNT(*)` over a `DISTINCT`
subquery with no ORDER BY, so it never reached `_emit_two_phase` — which
requires exactly one buried ORDER BY — and was never fenced. Its bound is
`cap + 1`, so it was past the threshold every time.

Adding `ORDER BY ?entity` to the subquery **when capped** puts it on the
two-phase path. A capped count asks "how many, up to cap", so which entities
come back and in what order is immaterial to the answer — the ORDER BY buys a
plan shape, not a semantic. Uncapped there is no LIMIT to terminate early, so
ordering would be pure cost, and it is omitted.

Re-measured on a quiet cluster with schema-matching indexes (see the note
above — the 51,368–130,751 ms figures were contaminated):

| `include_total_count` | unfenced | fenced | value |
|---|---|---|---|
| `yes` (capped at 1,000) | 1,283 ms | **39 ms** | 1001 ✓ |
| `exact` | 1,445 ms (not fenced) | — | 34,423 ✓ |

Both values verified against ground truth: 1001 is the "more than 1,000"
sentinel, 34,423 is the true distinct-entity count. `exact` is not fenced
(`needs_ordered_scan` is False, correctly — with no LIMIT there is nothing to
terminate early) and remains inherently O(matches); its improvement is from the
4-key index, not from this change.

## Original diagnosis — one root cause behind two symptoms

`issues/040` made KGQuery paging O(page) by getting PostgreSQL to drive an
ordered index scan and stop at the page. That plan survives only while the
`LIMIT` is small. Above a threshold — **52 rows** on the query and data measured
here — the planner flips to `Sort → Bitmap Heap Scan`, which is blocking, and
evaluates the EXISTS probe for **every** candidate.

Two things that look unrelated are the same defect:

| symptom | measured |
|---|---|
| `page_size` 25 / 50 | **1–2 ms** |
| `page_size` 100 | **48,034 ms** |
| `total_count` capped at 1,000 (`LIMIT 1001`) | **51,368–130,751 ms** |
| `total_count` exact (no cap) | 61,288 ms |

The capped count is *always* past the cliff, because its bound is `cap + 1`.
Note the cap currently buys nothing: capped 51–130 s against uncapped 61 s.

## The flip, exactly

Same query, `LIMIT` varied, 22.4M-quad restored production copy:

```
LIMIT 50 -> ordered index scan     LIMIT 51 -> ordered index scan
LIMIT 52 -> BLOCKING sort          LIMIT 55 -> BLOCKING sort
```

Below the threshold:

```
Limit  (cost=0.56..3577.88 rows=50)
  ->  Unique  (cost=0.56..1209348.51 rows=16903)
        ->  Index Scan using idx_*_quad_ps        <- ordered, stops early
```

At and above it:

```
Limit  (cost=3621.45..3622.45 rows=200)
  ->  Unique
        ->  Sort  (Sort Key: q0.subject_uuid)     <- blocking
              ->  Bitmap Heap Scan  (actual rows=34,659)   <- every candidate
```

The arithmetic is exact. The ordered scan is costed at 1,209,306 total for
16,903 rows — **71.5 per row** — and the planner prorates that by the LIMIT,
assuming matching rows are spread uniformly through the index. The sort path
costs 3,621. So the ordered path wins while `0.56 + LIMIT × 71.5 < 3621`, i.e.
`LIMIT < 50.6`. Observed flip: 52.

The assumption is wrong here in the most extreme way available: this criterion
matches **96%** of candidates, so the first 1,001 distinct subjects appear
almost immediately rather than 6% of the way through. The estimate is off by
roughly the whole scan.

There is also an asymmetry that makes it worse. In the ordered plan the EXISTS
subplan cost is charged per row (65–71 each). In the bitmap plan the same filter
sits on a Bitmap Heap Scan costed at 2,390 for the same 16,457 rows — the
subplan is effectively not charged at all. So the blocking plan is
systematically under-costed against the one that terminates early.

This is the same family as `issues/039`: the LIMIT cost model assumes uniform
distribution and there is no statistic for *where* matching rows sit in a scan
order, so no amount of ANALYZE reaches it.

## What is NOT the cause

The generated count SQL has two obvious inefficiencies, and neither explains it:

1. **The term join runs before the LIMIT.** `JOIN {space}_term ON ...` resolves
   text for every candidate — exactly the barrier `emit_slice._emit_two_phase`
   removes for the page. The count never gets that treatment because
   `_emit_two_phase` requires exactly one buried ORDER BY (`len(buried) != 1`
   returns None) and a count query has none.
2. **`SELECT DISTINCT *`** deduplicates over eight resolved columns including
   text, rather than over the uuid.

Both are real waste. Hand-writing the count without either — `DISTINCT ON` the
uuid, no term join, `LIMIT 1001` — still takes **44,270 ms**. The plan flip is
the whole story; these are worth fixing on their own merits.

## Confirming it is plan choice, not inherent cost

Forcing the early-terminating plan at `LIMIT 1001`
(`enable_sort=off, enable_bitmapscan=off, enable_hashagg=off`):

| | chosen plan | forced ordered plan |
|---|---|---|
| cold | 44,270–130,751 ms | **2,413 ms** |
| warm | 48,619–86,465 ms | **89–209 ms** |

**300–600x.** The work is not required; the planner is choosing not to avoid it.

## The index change: necessary, not sufficient — corrected 2026-08-08

Promoting `subject_uuid` from INCLUDE to a trailing key —
`(context_uuid, predicate_uuid, object_uuid, subject_uuid)` — is now in the
schema and the migration. **It does not fix the cliff.** An earlier revision of
this issue said it did, on the strength of the production-copy numbers below;
testing it on a fixture that already had the INCLUDE form showed otherwise.

What it does do is make the ordered path *possible*. With `subject_uuid` in
INCLUDE it is not a sort key, so this index can never supply `ORDER BY
subject_uuid` — the early-terminating plan has to come from some other index or
not at all. As a key column it can. Cost: **+0.1%** (4,163 MB → 4,167 MB on a
50.6M-quad space; byte-identical at 5.06M).

The production-copy numbers that suggested more:

| | before | after |
|---|---|---|
| capped count, `LIMIT 1001` | 44,270–130,751 ms | 1,450–4,000 ms |
| page_size 100 | 48,034 ms | 1,289 ms |
| page_size 250 | timed out | 1,459 ms |

Those are real but **not attributable to key-vs-INCLUDE**: that copy predates the
current schema and had *no* `_quad_ctx_pred` index at all, so the measurement
was mostly "an index that was missing was added". On the 100k fixture, which
already had the INCLUDE form, migrating to the 4-key form left `page_size` 250
timing out exactly as before.

### It is the split-BGP anchor that flips, and the threshold is data-dependent

Measured by binary search over plain EXPLAIN (instant — never ANALYZE, since past
the flip the query takes minutes):

| fixture | generic `KGEntity` anchor | specific entity type |
|---|---|---|
| 10k lead | never flips up to 2,000 | **19** |
| 100k lead | never flips up to 2,000 | **174** |
| production copy | — | **52** |

**The generic anchor never flips; only the specific-entity-type path does.** That
is the path `issues/045` made reachable by splitting a single BGP into
`JOIN(anchor, rest)` — so the anchor there is one quad table rather than the
pruned-UNION BGP the generic form produces, and it is costed differently.

Note what the 10k row means: **19 is below the default page size of 25.** On that
fixture a default page of specific-type entities is already served by the
blocking plan. It does not hurt there because the match set is only 908 rows, so
"probe everything" is cheap — which is precisely why this went unnoticed, and
why the buffer-ratio assertion added for `issues/045` passes at that scale.

So no fixed page-size bound is safe across datasets: 19, 52 and 174 on three
datasets of the same shape. Any constant picked from one is wrong for the others.

## Fix, in order of appeal

1. **Chunk above the cliff.** Both symptoms are "ask for more rows than the
   planner will serve from an ordered scan". Requesting them in runs of ≤50 and
   looping stays on the good side *by construction*, with no reliance on the
   planner: a 1,000-row cap becomes ~20 chunks at ~2 ms, roughly 40 ms against
   51–130 s today. Applies equally to a large `page_size`.
2. **The 4-key index** — done, in `sparql_sql_schema.py` and
   `migrate_quad_ctx_pred_index.py` (which now treats the issues/039 INCLUDE
   form as stale too). Necessary groundwork, since without it this index cannot
   supply the scan order at all, but on its own it only moves the threshold.
   Existing spaces need the migration run; it is `CONCURRENTLY` throughout.
3. **Give the count the two-phase treatment** — drop the term join and dedup on
   the uuid. Does not fix the flip, but it is pure waste today and it makes (1)
   simpler to implement, since the count and page would share one shape.
4. **Bound `page_size` and `TOTAL_COUNT_CAP`** below the threshold. Now known to
   be unsafe as a strategy rather than merely inelegant: the threshold measures
   19, 52 and 174 on three datasets of the same shape, and the lowest is under
   the default page size. Worth knowing regardless that a caller can
   currently trigger a 48 s query by asking for 100 results.

## Reproduce

```bash
# page: fast at 50, 48s at 100
PROBE_PAGE_SIZE=50  ./scripts/probe_semijoin_entity_query.sh
PROBE_PAGE_SIZE=100 ./scripts/probe_semijoin_entity_query.sh

# count: always past the cliff
PROBE_COUNT=cap   ./scripts/probe_semijoin_entity_query.sh
PROBE_COUNT=exact ./scripts/probe_semijoin_entity_query.sh
```

To find the threshold on other data, EXPLAIN the page SQL with the LIMIT varied
and look for `Sort` appearing above the scan.

**Note on the measurement environment:** the restored production copy now
carries `idx_probe_ctx_pred_obj_subj`, built for the index test above, and
otherwise predates the current schema (no `idx_*_quad_ctx_pred`) — so the
"before" numbers are not reproducible on it without dropping that index. The
100k fixture has been migrated to the 4-key form. `sp_lead_synth_10k` carried a
hand-made `idx_*_quad_ctx_pred_subj` that no other space had and the schema
never created, which means growth-curve comparisons between 10k and 100k were
run against different indexes.

## Added to the suite

`test_page_size_before_plan_flip` binary-searches the largest page still served
by an ordered scan and asserts it clears `MIN_SAFE_PAGE_SIZE` (100). It uses
plain EXPLAIN, so finding a threshold costs milliseconds even where the query
would take minutes.

Parametrised over entity type, because with only the generic anchor it finds no
flip at all and certifies nothing — the same vacuity trap as `issues/046`. The
specific-type case is `xfail(strict=False)`: it XFAILs on 10k (threshold 19) and
XPASSes on 100k (174), and will XPASS everywhere once this issue is fixed.

## Related

- `issues/040` — the paging fix this bounds; its O(page) claim holds only below
  the threshold
- `issues/045` — the other precondition on that rewrite (entity type)
- `issues/039` — same cost-model family, and the index change this extends
- `issues/044` — the abandoned-query problem this is the largest contributor to;
  fixing this removes most of its urgency
