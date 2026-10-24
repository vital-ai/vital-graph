# 302 — The type-agreement change token lags a committed write by up to ten seconds

## Status: OPEN (reproduced 2026-10-24 on the planner stack, PostgreSQL 18.4)

**Related:** `issues/182` and `issues/183` (what the absorption is worth),
`edge_type_agreement.py` (`_stored_verdict`, `refresh_type_agreement`),
`write_log.py` (a signal built to avoid this).

## Found

While choosing an invalidation signal for stored pattern verdicts (planning for
the planner extension). `_stored_verdict` accepts the maintenance job's verdict
that `rdf:type` agrees with `frame_slot.frame_type_uuid` / `edge.edge_type_uuid`
while this token is unchanged:

    pg_stat_get_tuples_inserted(oid) + pg_stat_get_tuples_updated(oid)
      + pg_stat_get_tuples_deleted(oid) || ':' || relfilenode

Those are cumulative statistics. A backend keeps its counts locally and flushes
them to shared memory asynchronously: at transaction end only if a second has
passed since its last flush, otherwise later (after about 10 s when it goes idle,
up to a minute while it stays busy). Until then, other sessions see the old
token, although the write's rows are already visible to them.

## Reproduced

`test_scripts/debug/_type_agreement_token_lag.py`, fixture table, two writes in
quick succession on one connection, the token read from another:

```
trial 0: token before 1:21584  right after commit 2:21584  (rows visible 3)  moved again after 10.01 s
trial 1: token before 3:21584  right after commit 5:21584  (rows visible 6)  moved again after 10.02 s
...  (5 of 5 trials)
```

The second write is visible as a row and absent from the token for ten seconds.

## Why it matters

The verdict decides whether `?f rdf:type T` is answered from the derived type
column instead of the type quads. A write that makes the two DISAGREE (an
`rdf:type` that differs from the `vitaltype` the column is derived from) leaves
the old token in place for 10-60 s, and a query in that window absorbs on a
verdict that is no longer true. Absorbing when they disagree is a wrong answer in
both directions (the module's own docstring): rows dropped or added.

Likelihood is low: writes that set `rdf:type` and `vitaltype` differently are
rare, and the window is seconds. But it is a result-correctness window, not a
performance one, and it is invisible: nothing logs that a stale token was
accepted.

The other direction is safe. A token captured BEFORE the scan can only be
behind, so a reader later sees a higher count and declines.

## Fix options

1. **Use a transactional signal.** `write_log.py` (built 2026-10-24, script-installed
   per space) counts writing transactions in a table, so a reader sees a write's
   log row exactly when it sees its rows; the verdict records the count read in the
   same snapshot as its check. It counts `rdf_quad` writes; the type columns are
   derived from quads, so a quad write is the earlier and broader signal. Needs the
   log installed on every space that relies on a verdict, and a reader that treats
   "no log" as "no verdict".
2. **Read the pending counters too.** `pg_stat_get_xact_*` covers only the
   reader's own transaction, not other backends': no help.
3. **`pg_stat_force_next_flush()`** is per backend, so every writer would have to
   call it. Not a fix.

(1) is the one that closes the window.
