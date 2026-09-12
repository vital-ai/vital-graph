# An Unfiltered Depth-2 Traversal Plans At 19 Trillion And Hangs The Perf Suite

## Status: OPEN, found 2026-09-12 while trying to sample the perf suite for
## `issues/188`. It is why the suite cannot be run to completion, and therefore
## why `188`'s thresholds cannot be measured and `190`'s baselines cannot be
## re-promoted.

**Related:** `issues/188` (blocked by this), `issues/190` (blocked by this),
`issues/096` / `issues/181` (the traversal gate and what it can see),
`issues/151` (hop-wise vs flat emission)

## The defect

`tests/performance/test_graph_traversal_fixture.py::test_open_frame_traversal_matches_the_manifest[2]`
does not finish. Observed twice: cancelled after **24m41s** the first time and
still running the second. It is an `entity -> frame -> entity` walk at depth 2
with NO criterion, over four sample starts, on `sp_graph_synth_10k` — the
fixture named `SMALL`, ten thousand entities.

The plan is the whole story. Same query, same fixture, depth 1 against depth 2:

| depth | estimated cost | plan lines | nested loops |
|---|---:|---:|---:|
| 1 | 741,337 | 42 | 7 |
| 2 | **19,282,929,239,712** | 77 | 12 |

**Twenty-six million times the cost for one more hop.** That is not a slow
query, it is an unrunnable plan that the suite waits on indefinitely.

The generated SQL grows modestly — 9,103 to 12,075 characters, 8 to 15 joins —
so this is a PLANNING collapse, not a code-generation explosion.

## The proximate cause: the chain detector does not see the second hop

`traversal_decision` reports the SAME decision for both depths:

    depth 1   Decision(hop-wise: depth 1, driving from tail, criterion admits 0%, drive from tail)
    depth 2   Decision(hop-wise: depth 1, driving from tail, criterion admits 0%, drive from tail)

It says **depth 1 for the depth-2 query.** So the chain it found is one hop
long, the decision it made applies to one hop, and the second hop is emitted by
the general path — which at depth 2 is where the trillions come from.

`criterion admits 0%` is the other half. These walks have no criterion at all,
and `traversal_decision`'s own docstring records what that costs: "Without a
criterion the walk fans out unchecked ... an unfiltered depth-3 walk on
`wordnet_frames` measured 865 ms flat against 2,044 ms hop-wise." That
measurement said flat was the better arm for an unfiltered walk. **On this
fixture at this depth, flat is not 865 ms — it is unrunnable**, so the
conclusion drawn from `wordnet_frames` does not generalise to
`sp_graph_synth_10k`.

`emit_dedup_chain` is documented as handling the unfiltered case "far better
than either arm" and as deliberately ungated. It evidently does not take this
shape; establishing why is the next step.

## Why it matters beyond the suite

1. **It blocks the perf work.** `188` requires 3-4 samples on an unmodified
   tree; the first sample reached 23% in 25 minutes and stopped here. `190`
   requires a promotable run. Neither is possible while this hangs.
2. **It is a correctness test, in the performance suite.** The assertion is
   `got == expected` against a manifest. It is not measuring speed, so the
   pathology it exposes has no threshold to breach — it just never returns.
3. **A 10k fixture is not a scale excuse.** Whatever this is, it is not "the
   fixture is too big".

## An operational hazard found alongside it

**Killing pytest does not cancel the query.** After the first run was killed,
the backend kept executing for a further 24 minutes and was still running when
the next run started — so the second run competed with the first, on the same
box, measuring nothing useful. Cancel explicitly:

```sql
SELECT pg_cancel_backend(pid) FROM pg_stat_activity
 WHERE state = 'active' AND query LIKE 'SELECT DISTINCT%';
```

Worth remembering for any perf work: an abandoned benchmark can go on consuming
the machine that the next measurement is taken on.

## What to do next

1. **Find out why `traversal_chain` reports depth 1 for a depth-2 query.** That
   is the specific, testable defect. Everything else here is a consequence.
2. **Ask why `emit_dedup_chain` declines this shape**, since it is the arm
   documented as handling unfiltered walks.
3. **Do not "fix" this by giving the bench a criterion.** The unfiltered walk is
   the shape under test, and a criterion would make the bench pass while leaving
   the plan collapse in place for any caller who writes the same query.
4. Until then the suite needs a way to run without it — a timeout per bench, or
   a marker — or every perf run costs a day. That is `issues/192`/`193`
   territory and should not be solved by deleting the test.
