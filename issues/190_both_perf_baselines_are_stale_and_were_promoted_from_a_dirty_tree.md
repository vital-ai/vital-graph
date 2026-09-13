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

## THE SUITE NOW COMPLETES — state as of 2026-09-13

Both preconditions this issue names are met. `issues/188`'s visibility work and
`issues/189` are in, and the suite runs end to end:

    full run, commit bc6ff22a    3,564 s (59 min)    158 benches recorded
    stamp: vg-test-docker-persist, promotion_blocked: no, dirty: False

**That run is a valid promotion candidate**, which it could not have been
before: `189` fixed the class being taken from a flag, and the `dirty` flag was
counting 48 untracked scratch files, so every run was disqualified by this
issue's own rule.

### What stands between here and promoting

**21 known failures.** Promoting now bakes them in as the reference, which is
this issue's own argument against promoting early. They are:

| file | count | status |
|---|---:|---|
| `test_traversal_direction_gate` | 7 | `issues/197` — the gate correctly bypassed, outdated expectations |
| `test_traversal_bench` | 5 | `issues/197` — criterion not measured, same class |
| `test_graph_traversal_fixture` | 5 | pre-existing, uninvestigated |
| `test_kgquery_growth_curve` | 2 | pre-existing, verified not caused by `bc6ff22a` |
| `test_partition_pruning` | 1 | pre-existing, uninvestigated |
| `test_paging_fence_covers_every_shape` | 1 | pre-existing, uninvestigated |

Twelve of the 21 are understood and recorded in `issues/197`; nine are not.

**The run took 59 minutes**, up from 45 before — because eight tests that used to
error instantly on a dropped table now actually execute, and
`test_range_comparator_pays_for_every_candidate` alone takes 187 s. `188`'s
instruction is 3-4 samples on an unmodified tree, which is now 3-4 hours rather
than impossible.

### CORRECTION — "triage the failures first" was wrong

I first wrote that the 21 failures had to be triaged before promoting, because
"a baseline that records them makes them permanent". That is not how this
baseline works, and the tooling already says so.

`compare_bench` handles a non-ok baseline entry explicitly:

    baseline ok      -> now failing   FAIL   "REGRESSED — was measured in the baseline"
    baseline not ok  -> still failing WARN   "known hole"
    baseline not ok  -> now ok        INFO

So promoting an imperfect run records the failures AS FAILURES, not as targets
to match. A known hole stays visible as a warning and turns into an INFO the
day it starts passing. That is exactly "capture the current state and do better
next time", and it is built in.

Nor does promotion refuse a run with failures. Its only guards are `--partial`
(never promote a subset, it bakes missing benches in as holes) and a refusal to
promote a run with no PostgreSQL settings. A full run with failures is an
expected input.

**And this issue's own caution was narrower than I read it.** "Re-promote AFTER
`issues/188` and `issues/189`" is about the unruled metrics and the false runner
class — both now done. It never said "wait for a clean suite", and waiting for
one means no baseline at all, which is strictly worse than a baseline with
recorded holes: today there is no drift detection whatsoever.

### The real cost of promoting now, which is smaller and specific

Not 21 failures — **10 benches that are `ok` in the committed baseline and would
not be `ok` in the new one.** Those are the reference points actually lost,
because each currently produces a FAIL against the old baseline and would become
a "known hole" against the new one:

    query.kgquery.range_penalty[10k]                  now failed
    query.kgquery.range_penalty[100k]                 now failed
    query.kgquery.sorted_paging.page_shape[10k]       now skipped
    query.kgquery.sorted_paging.page_shape[100k]      now skipped
    query.partition.graph_scoped_pruning              now ABSENT
    traversal.skew2k.constrained_common_head.depth2   now failed
    traversal.skew2k.constrained_rare_head.depth2     now failed
    traversal.skew2k.constrained_rare_tail.depth2     now failed
    (and 2 more)

Three of those are the `skew2k` gate benches `issues/197` explains as outdated
expectations rather than regressions. The rest are not yet understood.

Against that, promoting gains drift detection on 101 benches plus 3 that the
committed baseline does not cover at all.

### The one open question, which is not about failures

The two committed baselines split into tiers — `query.json` is 108 benches
(api/query/traversal), `ingest.json` is 51 (query/write) — and the prefixes
OVERLAP, so the split rule cannot be recovered from the files. A single full run
covers both (158 benches). `run-perf-tests.sh --promote NAME` promotes whatever
run it has to that name, with no tier filter, so promoting a full run to `query`
would redefine what that baseline contains and leave `ingest.json` stale.

That is a decision about how baselines are organised, not about the failures.

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

## Resolution of the query tier, and what the two-baseline split actually is

`query.json` was promoted from a full run at `bc6ff22a` (`125d0c7b`): 158 benches,
101 ok / 48 unrecorded / 7 failed / 2 skipped, class `vg-test-docker-persist`,
`dirty` false. It compares clean against itself — 0 failing, 57 warning, 0
informational, 243 uncompared.

The promotion captured current state, errors included, which is the right shape
for a baseline: `compare_bench` records a non-ok entry as a "known hole" WARN and
only FAILs on a *regression*, so carrying the 7 failures forward costs nothing and
loses no signal. The earlier recommendation to triage before promoting was wrong.

Investigating how the two tiers should split for next time produced a plainer
answer than expected: **there is no split to maintain.**

* `query.json` (108 benches) and `ingest.json` (51) were fully disjoint.
* All 51 `ingest.json` ids are now inside the promoted `query.json`.
* `ingest.json`'s entire informational content is **3** ok benches —
  `query.growth.entity_page_buffers`, `write.ingest.bulk_vs_executemany`,
  `write.per_write_curve.incremental_probe` — and all three are ok in the
  promotion too. Its other 48 are 47 `unrecorded` + 1 `skipped`.
* So `ingest.json` is entirely subsumed. It is stale (`573c46f`, class
  `vg-test-docker-clean`) and carries nothing the promoted baseline lacks.

The 48 benches both files hold as `unrecorded` are not a tier that records
elsewhere. They are every parametrisation of
`query.kgquery.paging_fence_coverage`, and
`tests/performance/test_paging_fence_covers_every_shape.py` **never calls
`perf_record`** — it asserts buffer ratios inline. They wear a `bench` mark, so
`conftest` mints a bench id and then flags it "test passed without recording
metrics". They can never be ok in any baseline, in any pass.

The only genuine second pass is the API tier: `run-perf-tests.sh` runs `-k bench`
with the app up and writes `${RECORD_PATH%.json}-api.json`. That is a separate
file already, and is not what `ingest.json` holds.

### Actions

1. Retire `ingest.json` — subsumed, stale, and no invocation reproduces it.
   Keep one baseline per pass: the suite baseline, and `-api.json` for the API pass.
2. Stop minting bench ids for the 48 paging-fence assertions, or make them
   record. Carrying 48 permanent holes is what made the split look meaningful.

## A bench can vanish from the baseline instead of failing

`query.partition.graph_scoped_pruning` is in the old `query.json` and in the tree
at `tests/performance/test_partition_pruning.py:132`, but is **absent from the
promotion entirely** — not failed, not unrecorded, gone.

Its fixture raised rather than its test failing:

    assert ok, f"space manager failed to create {sid}"
    E  AssertionError: space manager failed to create p3test_a95bc974

On a fixture error the test never reaches the status machinery, so the bench id
is never stamped and the bench simply disappears from the record. The promotion
then bakes the absence in, and `compare_bench` cannot warn about a bench that is
in neither side.

Diffing the 47 `@pytest.mark.bench` ids declared in the tree against the run
found this is the only real instance (`query.fastpath.entity_page` also looked
missing but is a docstring example in `perf_record.py`). One is enough: the
failure mode is silent, so the count is only ever a lower bound.

Fix: have the runner diff declared bench ids against recorded ones and fail the
promotion on any that are declared-but-absent, so a fixture error costs a loud
error rather than a quietly smaller baseline. Separately, find out why
`create_space_with_tables(partition_quads=4)` now returns False.
