# 346 — The prewarm fills its cap with the largest relations, not the hottest

## Status: FIXED 2026-11-16. Unit-tested and verified against a real PostgreSQL 18.4; NOT deployed.

## Found

`issues/271`'s prewarm job keeps one named space resident in `shared_buffers`. It orders
the relations "core (quad, term) indexes, then core heaps, then everything else, larger
first within each", and stops at `VG_PREWARM_MAX_BYTES`. That order assumed the space fits:
271 sized it at 234 k blocks (~1.8 GB).

Production, 2026-11-16 (read-only: catalog, `pg_stat_statements`, `pg_statio`, the job's own
log lines in CloudWatch, the task definition):

- The prewarmed space is now **23.1 GiB**; the cap is 12 GiB (task definition rev 97;
  the default is 3 GiB) and `shared_buffers` is 16 GiB. Every pass logs 52-102 relations
  "NOT warmed".
- The cap is filled by `rdf_quad_pkey` 3.7 GiB, `quad_ctx_pred` 3.3 GiB, `quad_ps` 2.1 GiB,
  `term_trgm` 0.9 GiB, …, and **every relation the write path's sync lookups read is left
  out**: the `edge` heap and its four indexes, and `entity_slot_sort` and three of its indexes
  (~1.9 GiB together).
- Those lookups (`sync_frame_slot_table._edge_owners`, the `entity_slot_sort` DELETE filter)
  are well planned: a BitmapOr over the right indexes, **0.2-0.8 ms warm** for a real
  one-entity write (EXPLAIN ANALYZE x5, `test_scripts/perf/_write_sync_lookup_explain.py`).
  On production they averaged **173 ms and 80 ms**, with ~346 blocks *read* per call, about
  their whole footprint.
- Block accesses over 30 minutes (`pg_statio` deltas, lookups and insert-time index
  maintenance, minus the job's own touches; `test_scripts/perf/_prewarm_access_density.py`):

  | relation | warmed | accesses per MiB |
  |---|---|---:|
  | `rdf_quad` heap (3.85 GiB) | no | 20,148, with 1.9 M cache misses |
  | `term_pkey` / `term` heap | no | 9,744 / 1,736 |
  | `edge` heap / `frame_slot` heap / `ess_entity` / `edge_edge` | no | 4,135 / 3,281 / 6,557 / 1,334 |
  | `quad_ps` (2.1 GiB) | yes | 583 |
  | `quad_ctx_pred` (3.35 GiB) | yes | 303 |
  | `term_trgm` (0.94 GiB) | yes | 128 |

  **The warm set covered 37.6 % of the space's block accesses; ranked by accesses per byte,
  the same 12 GiB covers 97.9 %.** (The warmed set itself drifted during the window, 54 → 25
  relations, as the 1 GiB `term` heap flipped across the cap boundary. That makes the
  subtraction approximate for a few small relations, not for the ranking above.)

## Fix

`vitalgraph/process/prewarm_job.py`: the job **measures access itself, every pass**, and fills
the cap by accesses per MiB, highest first.

- At the start of a pass it reads each relation's `heap|idx _blks_hit + _blks_read` from
  `pg_statio_user_{tables,indexes}`, one query. The accesses since the last pass are the
  delta **minus the blocks the job itself touched**, which `pg_prewarm` returns per relation,
  so the subtraction is exact.
- The rate is a decayed average (`VG_PREWARM_ACCESS_ALPHA`, default 0.1 per pass), so one
  maintenance burst does not reorder the set.
- A relation not measured yet (first pass, restart, a new index) keeps the old default
  order, after the measured ones. A counter that moved backwards (`pg_stat_reset`) or that
  cannot be read changes nothing.
- The pass log line gains `order: measured access | default`.

No index is dropped and nothing is per-space: every space keeps the full index set. Only
what this job keeps resident changes, and still only for the spaces named in
`VG_PREWARM_SPACES`.

## Tests

- `tests/unit/test_prewarm_job.py`, 7 new tests: the first pass uses the default order;
  measured access per byte decides the next pass; the job's own touches are not counted as
  use (the warmed relation does not look hot because it was warmed); a stats reset changes
  nothing; unreadable counters keep the default order; one burst does not displace a
  relation that has been hot for many passes; a new relation ranks after the measured ones.
  **5 of 7 fail on the unfixed code** (throwaway worktree at HEAD). The other two pin
  behaviour that is unchanged.
- Unit suite: 6,410 passed, 9 skipped.
- **Against a real PostgreSQL 18.4** (a throwaway container, not the shared vg stack, which
  was in use): the real `PrewarmJob` across 5 passes, with point lookups on a small edge
  index between passes and a cap that fits either the 16.9 MiB quad index or the edge
  relations. Pass 1 (unmeasured) warmed the quad index, as before. Passes 2-5 ranked by
  measured access and warmed the 3 edge relations; the quad index's rate was exactly 0,
  i.e. the job's own 2,164 touches were subtracted.

## Not done

- **After deploy**: `test_scripts/perf/_prewarm_log_summary.py` (CloudWatch only) for the
  pass lines' `order` and read share, and the pgss window for the two sync lookups, which
  should fall from 173 / 80 ms toward their warm 0.2-0.8 ms.
- The cap itself (12 GiB of 16 GiB `shared_buffers`) is a per-install operator choice, not
  changed here.
