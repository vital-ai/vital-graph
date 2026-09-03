# The Stats Integrity Check Has Never Run On This Space, And Said So At DEBUG

## Status: OPEN — the CAUSE is not understood. The silence is fixed (`c823f1f`).

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
