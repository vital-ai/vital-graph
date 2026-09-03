# The Stats Integrity Check Has Never Run On This Space, And Said So At DEBUG

## Status: CAUSE FOUND AND FIXED 2026-09-03. It was a CLIENT-side timeout.
>
> **SUPERSEDED IN PART.** This is a consequence of `rdf_stats` being an
> incrementally-maintained accumulator that cannot validate itself. A
> proposal to recompute the reader's 10,000-row window instead — measured
> at 41 s on production — would remove the mechanism this issue describes
> rather than repair it. See
> `planning/planning_performance/rdf_stats_recompute_not_accumulate_plan.md`
> before doing further work here.


The original write-up below could not explain why `column p.pruned does not
exist` appeared when the column demonstrably existed. **That message was a red
herring from an earlier build.** What the deployed code actually logs is:

    Stats integrity check SKIPPED for <space> (TimeoutError)

with an EMPTY message — the signature of asyncpg's `command_timeout=60` firing
in the DRIVER. `164d9de` wrapped this check in `maintenance_timeouts`, which
raises `statement_timeout` and `lock_timeout` with SET. Neither can touch a
client-side bound. Six queries in the check had no `timeout=` at all.

**The production consequence, measured 2026-09-03:** the audit that rebuilds
`rdf_stats` never completed, so the table decayed to **5 rows** (max_rc ~1,879).
The `(hasKGEntityType, NurtureAction)` anchor — 77,479 rows — was ABSENT, so the
semi-join gate fell back to a **10.4 s runtime bounded-count probe on every
query**:

    SELECT count(*) FROM (SELECT 1 FROM <space>_rdf_quad
      WHERE predicate_uuid=<hasKGEntityType> AND object_uuid=<NurtureAction>
      LIMIT 50000) s                                          -- 10.4 s

Combined with a 28 s entity scan and the client's 2-attempt / 60 s budget, that
is the 60 s ReadTimeout on the dedup query. It bites only the MISS path — a
brand-new lead with no action — which is exactly the ~58% slow population.

The loop was self-sustaining: audit times out -> no rebuild -> a partial rebuild
records low values -> the prune correctly keeps 5 rows of an all-singleton table
(`issues/147`) -> repeat every cycle.

**AND ONE LEVEL DOWN.** Fixing the audit only moved the failure. The audit's
response to a coverage gap is to call `resync_stats_tables`, whose own aggregate
measured **19.6-49.0 s on production** against the same 60 s `command_timeout` —
and its nine queries had no `timeout=` at all. The rebuild would have died in
the driver and rolled back, leaving the stats exactly as corrupt as before. That
is now threaded through too (`resync_stats_tables` -> `_resync_stats_locked`),
and the guard test was widened to check the HELPERS the loop calls, not only the
loop itself, because the first version of it read `maintenance_job` alone and
would have passed while this was broken.

**Fixed:** all seven maintenance queries now pass
`timeout=PROBE_CLIENT_TIMEOUT_S`, and a guard test walks the source for any
query inside a `maintenance_timeouts` block without one. Verified non-vacuous by
removing a timeout and confirming the test fails.

**This was the FOURTH recurrence of the same blind spot** — raise the server
fence, forget the client one. `issues/149` fixed it for the slot-sort probe,
then missed the backfill it gates; the audit after that checked for
`maintenance_timeouts` wrapping and never for `timeout=`, which is how these six
survived. The guard test exists because reading the code has now failed three
times.

## Original write-up (the `p.pruned` red herring) follows

## What happens

Every maintenance cycle, for every KG space:

    Stats integrity check skipped for <space>: column p.pruned does not exist

logged at DEBUG, on a service that runs at INFO. One `except` guards BOTH the
coverage audit (`issues/141`) and the oversized-pair repair (`issues/142`), so
neither has ever run on production. Confirmed rather than assumed: the repair's
`Stats oversized` line appears nowhere in any log window examined.

That matters because `141`'s audit is precisely the mechanism designed to notice
"recorded pair 259 vs 192,091 actual" and trigger a rebuild. It is the safety net
under `rdf_stats`, and it has been disconnected the whole time.

## Why the message cannot be taken at face value

`p.pruned` resolves. Verified on production 2026-09-03:

* `pruned` exists on ALL five `*_rdf_pred_stats` tables;
* in schema `public`, the only schema holding them;
* in database `vitalgraphdb`, the only database the deployed config points at
  (checked against the deploy repo's compose/env, not assumed);
* the running image contains the correct query, aliasing
  `{space}_rdf_pred_stats p` — read out of the deployed tree at the running sha,
  not out of `main`;
* and the same query, run by hand on that database, RETURNS A ROW — a real
  coverage gap (`pred_total 79,469` against `pairs_sum 571`).

So the server is told a column does not exist which demonstrably does, on a
connection to a database that has it, from code that spells it correctly.

## What has been ruled out

* **Wrong database.** Deployed config names `vitalgraph-pg18-prod`; that is the
  instance measured. The write activity observed there tracks the app's own log
  timestamps, so it is the same database.
* **Wrong schema.** One schema, `public`, one match per table name.
* **Stale code.** The running image's query is correct.
* **A different table aliased `p`.** Both `p.pruned` sites join
  `{space}_rdf_pred_stats`.
* **A missing table on one space.** The message names spaces whose table exists.
  (one space in the list has no `_rdf_pred_stats` at all, which would raise
  UndefinedTable, not UndefinedColumn — that one is a separate, benign case.)

## What is worth trying next

1. **Get the full traceback.** `c823f1f` raises this to WARNING with
   `exc_info=True`, so the next deploy will name the failing STATEMENT rather
   than just the message. That alone may settle it.
2. **Suspect the connection, not the query.** A pooled asyncpg connection
   carrying a cached prepared statement from before the column existed would
   explain "spelled right, exists, still fails". `migrate_install_version.py`
   and the schema migrations both ALTER these tables; a connection established
   before that and never recycled is the obvious candidate. Check
   `max_inactive_connection_lifetime` on the pool and whether the failure
   follows a specific PID.
3. **Correlate with a restart.** If the failure disappears after a task
   restart and returns after the next migration, (2) is confirmed.

## The pattern this belongs to

Fourth instance in one investigation of "handled correctly, reported at a level
nobody sees, stayed broken":

    issues/140   swallowed UnboundLocalError, silently disabled a plan optimisation
    issues/144   statement timeout read as "not a KG space", repair never ran
    issues/146   exception with no containment, one entity failed every request
    issues/148   this — the audit AND the repair, disabled together, at DEBUG

The common root is not the exception handling. It is that in each case nobody
decided, when writing the handler, what a failure should COST — and a handler
written to be safe defaulted to being silent.
