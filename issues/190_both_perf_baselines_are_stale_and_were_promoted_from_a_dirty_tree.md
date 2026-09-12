# Both Perf Baselines Are Stale, And Were Promoted From A Dirty Tree

## Status: OPEN. Promoted 2026-08-22 from a dirty `1e78609`; 126 commits have
## touched `vitalgraph/` since, including the paths the benches measure.

**Related:** `issues/188` (re-promoting before it lands bakes in the holes),
`issues/189` (re-promoting before it lands bakes in the false class),
`planning/planning_performance/perf_coverage_gaps_plan.md` §3

## The defect

`baselines/query.json` and `baselines/ingest.json` both carry
`git.dirty: true` at commit `1e78609`, promoted 2026-08-22. The drift detector
is comparing today's code against a three-week-old reference taken from a tree
that corresponds to no commit.

Perf-relevant work landed since:

    560dda08  perf(sort): serve multi-key sorted pages from entity_slot_sort
    562d111a  fix(analyze): entity_slot_sort was never analyzed
    35cf5616  perf(sparql-sql): distribute joins over unions, merge each arm's BGPs
    c7ebdff4  perf(kgquery): make property sorts use their indexes, both directions
    b94484a9  refactor(sparql-sql)!: retire frame_entity for a role-agnostic frame_slot

## Ordering — this is the part that matters

Re-promote AFTER `issues/188` and `issues/189`. Promoting first bakes the
current state in: the unruled metrics get written into a fresh baseline where
they go on not being compared, and the runner stamp goes on claiming clean.

Then:

* promote from a run driven by `run-perf-tests.sh`, so the stamp is produced the
  way the stamp assumes;
* record the deltas rather than smoothing them. Commit `76a9e1d8` is the model —
  it promoted a −10.6% `copy_speedup`, named the likely cause, and said it was a
  price rather than absorbing it.
* fold in `random_page_cost=1.1` (`issues/191`) in the SAME promotion, since it
  moves plan shapes.

## Worth adding while here

* Refuse promotion from a dirty tree without an explicit override. `promote()`
  already warns; the warning did not stop this.
* Warn when the baseline commit is more than N commits behind HEAD. Both are
  cheap, and either would have surfaced this without anyone going looking.
