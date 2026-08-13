# Read-After-Write Concurrency Test Failed Once, Not Reproducible

## Status: ATTRIBUTED AND FIXED 2026-08-13 — connection exhaustion, not a race

**It was never a race.** The segmentation worker opened a DEDICATED LISTEN
connection PER SPACE. On a database with 86 spaces that is 90 idle connections
holding `LISTEN "{space}_seg_jobs"`, against `max_connections = 100`:

    connections before   101   (over the limit)
    LISTEN connections    90
    after the fix         25   with 3 LISTEN connections, 85 channels

Everything else was starved. That is why the failures were intermittent and
concentrated in concurrency tests — they need several connections at once, and
whether they got them depended on what else was running.

The third occurrence is what made it findable: capturing the failure NAMES (as
this issue said to) showed `TestPoolBehavior::test_many_concurrent_queries` and
`test_read_after_write_concurrency` failing together with

    Failed to connect sparql_sql PostgreSQL: sorry, too many clients already

which is not a symptom any race would produce.

**The fix**: one LISTEN connection per DATABASE rather than per space. A single
PostgreSQL connection holds any number of LISTENs; nothing required one each.
Verified: 85 channels on one shared connection, and two consecutive full
integration runs at 201 passed.

**Why it hid for two days**: the first two occurrences were dismissed as
flakiness because the failing tests were not recorded, and the surviving
evidence — "1 failed, 195 passed" — is equally consistent with a race. The
lesson stands and is now proven: capture the names.

## Original: OPEN — observed TWICE on 2026-08-13, still unattributed

**Second occurrence, same day.** A full integration run reported `2 failed, 197
passed`; the three runs immediately after were `199 passed` each. **The failing
test names were not captured**, because the command filtered output to the
summary line — the same mistake this issue already recorded as the single most
useful thing to fix, repeated.

Running tally:

    run set 1   1 failed / 195 passed     then 3 clean full runs, 14 clean isolated
    run set 2   2 failed / 197 passed     then 3 clean full runs

So roughly 1 in 4 full-suite runs shows 1-2 failures that do not reproduce. That
is frequent enough to be worth catching properly and rare enough that it will
keep being dismissed.

**Always capture the names.** Use `--tb=short` and tee the output rather than
grepping for the summary:

    python -m pytest tests/integration --timeout=900 -p no:warnings \
        --tb=short 2>&1 | tee /tmp/integration.log | tail -5

The failure names live in the `FAILED ...` lines and the traceback; a
summary-only filter throws away the only evidence that matters.

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
