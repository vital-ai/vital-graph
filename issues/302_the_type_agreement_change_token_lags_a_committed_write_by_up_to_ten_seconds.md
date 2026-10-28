# 302 — The type-agreement change token lags a committed write by up to ten seconds

## Status: FIXED 2026-10-28 on the default path (option 1, the write log). Open until the vg test stack runs the full suite on the rebuilt image; live per space once `scripts/install_write_log.py` has run there.

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

## Fix (2026-10-28) — option 1

`edge_type_agreement`, on the default path (and the planner's, which reads the same verdict):

- **The token.** Where the space has the write log, `change_token` and the reader's in-query token
  carry the log's write count and the quad table's oid (`<churn>:<relfilenode>|w<writes>:<oid>`),
  read in the same statement as the verdict. A reader sees a committed quad write's log row
  exactly when it sees its rows, so the verdict is declined at once. A log whose trigger is
  missing or disabled gives `|wnone`, which no stored token matches. The refresh's before / after
  tokens carry it too, so a quad write during the scan marks the verdict born stale.
- **The planning gap.** A TRUE verdict accepted under the log hands `(space, writes, oid)` to the
  generation result as `verdict_guard` (`ACCEPTED_GUARD`, per task). The executor's existing hook
  (`pattern_verdict.guard_holds`) re-checks it in the REPEATABLE READ snapshot the query runs in,
  and re-plans without stored verdicts (`planner_verdicts=False`, now honoured by
  `frame_type_absorbable` / `edge_type_absorbable` as `use_stored`) when a write landed between
  planning and running.
- **Without the log**, the reader runs today's query unchanged: the window stays there until the
  log is installed. Not "no log, no verdict": that would turn absorption off on every space at
  deploy.

Residual: the derived table's own churn (`frame_slot` / `edge`) is still the statistics token; a
write to it alone (a resync, with no quad write) lags as before. Every write path that changes
which frames carry which types writes quads in the same transaction.

**Deploy step**: `python scripts/install_write_log.py --all`, then refresh the type-agreement
verdicts (the maintenance job, or an explicit refresh): a verdict stored before the log has no
write-log part and is declined once the log is present.

## Test

`tests/integration/test_type_agreement_verdict_sees_a_write_at_once.py`: a stored TRUE verdict,
then a write that makes `rdf:type` disagree with `vitaltype`, read at once from another
connection: declined. On the code before the fix it is still TRUE (`assert True is None`). And
the guard handed to the executor moves with a later write (`guard_holds` false).
