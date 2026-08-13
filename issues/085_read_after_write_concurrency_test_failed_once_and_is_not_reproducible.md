# Read-After-Write Concurrency Test Failed Once, Not Reproducible

## Status: OPEN — observed 2026-08-13, unattributed

`tests/integration/test_read_after_write_concurrency.py::test_concurrent_insert_data_shared_terms_read_after_write`
failed once during a full integration run, and has not failed since.

    full suite run, first     1 failed, 195 passed
    full suite, 3 more runs   196 passed, 196 passed, 196 passed
    that test alone, 12x      0 failures
    that test alone, 2x       0 failures

So: **1 failure in 4 full-suite runs, 0 in 14 isolated runs.**

## Why this is filed rather than shrugged off

The test is regression coverage for a connection-poisoning bug that produced a
real, user-visible flake (`issues/003`, `019`): concurrent `INSERT DATA` sharing
a term both emitted the same deterministic `term_uuid`, hit a duplicate-key
violation, poisoned the pooled connection, and made UNRELATED reads hang or come
back empty. The fix was `ON CONFLICT (term_uuid) DO NOTHING`.

A test guarding that failing intermittently is exactly the signal that gets
dismissed as flakiness until it is not. Two readings, and nothing here
distinguishes them:

1. **Test-level flakiness under suite load** — it only failed when the whole
   suite ran, never alone, which points at pool contention or timing rather than
   the logic under test.
2. **A residual race** that the `ON CONFLICT` fix narrowed but did not close,
   surfacing only under the concurrency the full suite happens to produce.

## What was NOT the cause

It appeared in the run for the query-pipeline warm-up commit
(`860cc20`). That change adds a background task to APP startup; integration
tests do not start the app, and the three subsequent clean full runs were on the
same code. It is not attributable to that change.

## How to make progress

* Capture the failure output next time — this one was seen only as a summary
  line, so the assertion that failed is unknown. That is the single most useful
  thing to add.
* Run the full suite in a loop overnight and count. 1-in-4 should reproduce in
  tens of runs if it is load-dependent.
* If it recurs, check whether the pool is exhausted at that point rather than
  assuming the term race: the failure mode of the ORIGINAL bug was unrelated
  reads hanging, which a pool census at failure time would show directly.
