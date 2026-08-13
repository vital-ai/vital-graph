# Covering Index Puts `object_uuid` in INCLUDE, Not a Key — 1,850x Buffer Blowup

## Status: FIXED 2026-08-07 (schema + migration)

Applied in `1eaf71e` as part of the range push-down work:
`sparql_sql_schema.py:830` now declares
`(context_uuid, predicate_uuid, object_uuid) INCLUDE (subject_uuid)`.
Because the DDL is `IF NOT EXISTS`, **spaces created before that commit keep the
old two-key index and will never pick the new one up** —
`scripts/migrate_quad_ctx_pred_index.py` exists to rebuild them, and has to be
run per space.

Two of the four pre-apply checks below are not recorded as having been done:
index size on a realistic space, and whether `idx_{space}_quad_po`
(`sparql_sql_schema.py:800`) is now dead weight for graph-scoped queries. Both
are follow-ups, not blockers.

`idx_{space}_quad_ctx_pred` is declared

```sql
CREATE INDEX idx_{space}_quad_ctx_pred ON {space}_rdf_quad
  (context_uuid, predicate_uuid) INCLUDE (subject_uuid, object_uuid)
```
<sup>`vitalgraph/db/sparql_sql/sparql_sql_schema.py:728`</sup>

`object_uuid` is in the INCLUDE payload, so it can **only ever be a filter, never
an index condition**. Any query binding graph + predicate + object — the shape
every typed-entity listing produces — scans the whole (context, predicate) range
and discards almost all of it.

## Measured

Query: 25 KGEntity subjects from `wordnet_frames` (8.58M quads), i.e.
`?s vitaltype KGEntity` in a graph, `LIMIT 25`.

| Plan | Buffers | Time |
|---|---|---|
| **Chosen today** — `quad_ctx_pred`, object as *filter* | **14,876** | 592ms |
| `quad_po` (forced) — object as index cond | 8 | 0.24ms |
| Seq scan (forced) | 110,143 | 1,261ms |
| **`(context, predicate, object)` INCLUDE (subject)** | **5** | **0.21ms** |

**~1,850x more buffers than necessary** for a 25-row page.

```
Index Only Scan using idx_wordnet_frames_quad_ctx_pred
  Index Cond: (context_uuid = ... AND predicate_uuid = vitaltype)
  Filter:     (object_uuid = KGEntity)
  Rows Removed by Filter: 1,426,740
  Heap Fetches: 0
  Buffers: shared hit=4 read=14866
```

It walks 1.4M index entries — 93% of every `vitaltype` quad in the graph — to
return 25 rows.

## Why the planner picks it

Not a cardinality error. The estimate is accurate: `rows=111113` against 109,745
actual. The problem is the **LIMIT cost model**: with ~111k rows expected to
match, it assumes they are spread uniformly through the index range, so 25
should appear in the first ~0.02% of the scan. It costs that at `0.56..23.01`.

They are not uniform — KGEntity quads cluster at the end of that index's scan
order, so it reads essentially the whole range first. Estimated cost 23, actual
14,876 buffers.

## What does not fix it

**Extended statistics on `(predicate_uuid, object_uuid)`.** Tried:
`stat_wordnet_frames_quad_po` already existed, was raised to
`SET STATISTICS 1000` and re-analyzed — the plan did not change, and the row
estimate was already correct before and after.

This was my first hypothesis and it was wrong, for a reason worth recording:
extended stats correct *how many* rows match, not *where they sit* in a scan
order. There is no statistic for "position of matching rows within an index
range", so no amount of ANALYZE will talk the planner out of this. It is the
same family as the nurture slot-value blowup but **not** the same fix.

## The fix

Promote `object_uuid` from INCLUDE to a key column:

```sql
CREATE INDEX idx_{space}_quad_ctx_pred ON {space}_rdf_quad
  (context_uuid, predicate_uuid, object_uuid) INCLUDE (subject_uuid)
```

Verified on `wordnet_frames`: all three columns become index conditions, zero
rows filtered, still `Heap Fetches: 0`, **5 buffers**.

```
Index Only Scan using idx_wf_quad_ctx_pred_obj
  Index Cond: (context_uuid = ... AND predicate_uuid = ... AND object_uuid = ...)
  Heap Fetches: 0
  Buffers: shared hit=1 read=4
```

The existing covering use case is preserved — `test_covering_indexes.py` asserts
an Index-Only Scan with 0 heap fetches on a graph-scoped predicate scan, which
still holds because `object_uuid` remains in the index, just as a key rather
than payload. `subject_uuid` stays in INCLUDE, so the index still covers.

Before applying, check on a realistic space:

1. **Index size.** Moving a uuid from payload to key changes the b-tree
   structure; measure `pg_relation_size` before/after.
2. **Write cost.** `test_per_write_curve` should stay flat.
3. **`test_covering_indexes` / `test_covering_benchmark`** still pass.
4. Whether `idx_{space}_quad_po` becomes redundant — it may now be dead weight
   for graph-scoped queries, though it still serves cross-graph ones.

## How it was missed

The suite had 20 plan-shape assertions and every one of them ran against
**hand-written** SQL mirroring the fast paths. Nothing asserted on the SQL the
SPARQL generator emits, so this shape was never planned under test. The
hand-written KGEntity fast page costs 481 buffers for the same logical result
because it constrains `object_uuid = ANY(...)` in a way that reaches a workable
index — so the tested path and the API path diverged by orders of magnitude and
only the tested one was watched.

Found by `tests/performance/test_generated_sql_plans.py`, added to close exactly
that gap. That bench moves 14,970 → 105 buffers with the fixed index.

## Reproduce

```bash
./scripts/run-perf-tests.sh --seed-data --no-down     # needs wordnet_frames
pytest tests/performance/test_generated_sql_plans.py -m performance -q
```

Then compare `query.generated_sql.plan[typed_listing]` against
`query.fastpath.typed_subject_page` in the same run: same logical query, ~140x
the buffers.
