# 019 — Triples subject-filtered list intermittently returns 0 under full-suite load

## Status: 🟡 OPEN — read/write paths verified correct; root cause NOT reproduced

## Summary

Under the full Playwright E2E suite at high parallelism, `e2e/tests/triples-crud.spec.ts`
→ "triple appears in the list via filter" intermittently fails at its precondition:
`GET /api/graphs/triples?...&subject=<subj>` returns `results: []` for a triple that
test 1 already added and displayed. It passes in isolation and at CI concurrency
(2 workers). ~1 in 2–3 full runs at 5 local workers.

## Investigation — what was RULED OUT (do not re-chase these)

The original hypothesis was a SPARQL→SQL correctness bug (LIST returns 0 while
COUNT returns 1). **That was based on a misread log line** — `SPARQL pipeline …
(1 rows …)` for the COUNT query means the COUNT returned its single count-row; the
count *value* can still be 0. It is NOT evidence of divergence.

The read and write paths were then exercised directly against the test stack
(:5433 / :7071) and are provably correct and robust:

| Check | Method | Result |
|---|---|---|
| Generated LIST SQL is correct | capture exact 9929-char SQL via the endpoint's own `_build_sparql_query` + `generate_sql`, run it | returns 1 row ✅ |
| SQL is stats-independent here | generate with `_rdf_stats`/`_rdf_pred_stats` empty vs populated | identical SQL, 1 row (single-pattern query has 0 joins → no reorder) |
| SQL execution under concurrency | 24 workers × 150 iters, default / forced-parallel / parallel-disabled | **0 / 3600** zero-rows in every plan mode |
| SQL under concurrent DDL churn | 6 tasks create/drop spaces while 8 query | **0 / 85977** zero-rows |
| Full HTTP read path under load | 16 GET workers + 12 noise workers | **0 / 960** zero-rows |
| Write + immediate read-back under load | 30 create-space → add → readback cycles w/ 16 noise workers | **0 / 30** readback-zero |

So: SQL generation, SQL execution (incl. parallel plans + `LIMIT`), the HTTP read
path, and write-then-read-back all handle **more** concurrency than the 5-worker
E2E suite generates, without ever dropping the row. The generated SQL for a
subject-filtered list is a single quad-scan (`WHERE context_uuid = …`) INNER-JOINed
3× to `{space}_term` to resolve `?s/?p/?o`, filtered on the resolved subject text.
Term UUIDs are deterministic (`_generate_term_uuid` = hash of text/type/lang/dt), so
a quad can never reference a term UUID that mismatches an existing term row.

## Current best theory (unverified)

A rare read-after-write / space-lifecycle visibility race specific to the full
suite's timing — e.g. the just-added quad's row (or a `{space}_term` row) not being
visible on the connection that serves test 2's GET, in a window the isolated
reproductions didn't hit. The per-suite space isolation (`space-fixtures.ts`) makes
each run create a *fresh* space and reuse the id `e2e_triples_space` across runs,
which is a candidate interaction (stale space-manager / generator caches keyed by
space_id across drop→recreate) — but this was not reproduced despite trying
space-name reuse under load.

## Impact

- E2E flake only, at high local parallelism. **No reproduction of user-facing data
  loss**; every direct test of the read and write paths passed.
- CI (2 workers + 2 retries) is green.

## Next steps (for a future session with more signal)

- [ ] Add temporary server-side logging of the *count value* and `len(results)`
      together in `_list_triples`, plus a dump of `{space}_rdf_quad` / `{space}_term`
      row counts, then run the full suite until it fails to capture the real DB state
      at failure (the isolated space is dropped by `afterAll`, so add a "don't drop on
      failure" hook or log-before-drop).
- [ ] Check whether space-manager `get_space_or_load` / generator `_stats_cache` /
      `_compile_cache` retain stale entries across a same-id drop→recreate, which the
      isolation pattern now exercises every run.
- [ ] Consider whether the test should read-after-write with a bounded retry: now
      that the query path is *proven* correct, a retry here handles read-after-write
      visibility rather than masking a query defect — but only add it once the state
      at failure is captured, so we don't paper over a real (if elusive) write race.

## Test status

`triples-crud.spec.ts` keeps the plain single-shot precondition assertion (no
retry) with a NOTE pointing here, so the flake stays visible until root-caused.
