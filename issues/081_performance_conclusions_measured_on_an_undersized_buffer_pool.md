# Most Performance Conclusions Were Measured on a 1 GB Buffer Pool

## Status: the three actions are DONE; the safeguard is closed 2026-08-16

`shared_buffers` was **1 GB on a 64 GB machine**, and `effective_cache_size` was
at its 4 GB default and had never been tuned. A single query on
`sp_lead_synth_100k` touches **400,000+ buffers (>3 GB)**, so the working set
could not fit and every query paid eviction.

Raised to 16 GB / 48 GB. **No code changed.** Measured immediately after:

    sorted page (issues/080)            16,411 ms  ->     616 ms      27x
    deep paging (issues/078) offset 250 39,247 ms  ->   1,437 ms      27x
                             offset 1000  TIMEOUT  ->   2,958 ms
                             offset 5000  TIMEOUT  ->  16,271 ms

Buffer COUNTS were identical before and after (453,180 vs 416,261), which is the
whole point: the work never changed, only whether the pages were resident.

## SHARPENED CRITERION — measured 2026-08-11, and it NARROWS the list a lot

The comparator sweep was re-run on the corrected pool and compared cell by cell:

    total WARM      1,444 ms ->  1,745 ms     0.83x   (slightly WORSE — noise)
    total COLD     15,802 ms ->  7,757 ms     2.04x
    total BUFFERS   1,597,396 -> 1,597,348    1.00x   (identical)
    perf_sweep_diff: no regressions across 39 cells

**The sweep cells were never affected**, and the reason is arithmetic: a 1 GB
pool holds 131,072 pages, and the sweep's largest cell reads **82,724 buffers**.
Every comparator query fit in the pool. The sorted page reads **453,180**
buffers — 3.5x the entire pool — which is why that one was destroyed and these
were not.

    A measurement is at risk IF AND ONLY IF the query's buffer count
    approaches or exceeds the buffer pool.

    1 GB pool  = 131,072 buffers
    sweep cells = 4,350 .. 82,724 buffers    -> FIT, unaffected
    sorted page = 453,180 buffers            -> 3.5x the pool, destroyed
    deep paging = grows with offset          -> crosses the line as it deepens

That is checkable from data already recorded, because the sweep prints buffer
counts per cell. **The triage below was written before this was measured and is
too broad.** Corrections:

* **`053` and the comparator issues (`045`, `058`, `059`, `061`, `071`, `073`)
  are NOT at risk.** Their queries read tens of thousands of buffers, fit
  comfortably in the old pool, and the re-run confirms their warm timings are
  unchanged. The banners added to those issues overstate the risk.
* **`078` and `080` ARE at risk and were re-measured in full.** Both read far
  more than the pool.
* **`047`, `072`** remain worth re-checking, but for a different reason:
  `effective_cache_size` (4 GB, never tuned) feeds COST ESTIMATES regardless of
  how many buffers a query touches, so plan CHOICE could shift even for queries
  that fit.
* **The 8-63x cold/warm gap stands as a real phenomenon**, though it halved:
  15,802 ms -> 7,757 ms across the sweep. Cold is still cold; the pool made it
  cheaper, not absent.

The original criterion — "at risk if it rests on a timing" — was the right
instinct and the wrong threshold. Buffer count against pool size is the test.

## `072` CHECKED — not a configuration artifact, and not re-testable as written

    is_empty/KGTextSlot   warm 339 ms -> 320 ms    buffers 25,341 -> 25,341
    gte/KGDoubleSlot      warm  21 ms ->  21 ms    buffers 24,710 -> 24,710
    gte/KGIntegerSlot     warm  10 ms ->  11 ms    buffers 12,147 -> 12,147

Identical buffer counts mean identical plans, so raising `effective_cache_size`
from 4 GB to 48 GB **did not change plan choice** for these cells. The worry that
`072`'s misestimation might be a configuration effect is not supported.

And on the CURRENT code the estimates are accurate:

    Index Only Scan ... est=107,377  actual=100,000     1x off
    Gather Merge    ... est=103,500  actual=100,000     1x off

The `rows=1` against 100,000 that `072` documents belonged to the OLD plan
shape, which the fix (the candidate-driven negation path from `059`) replaced.
The query is now set-based, and set-based plans estimate well here. So `072`
cannot be re-tested as written without reverting its own fix, and there is
little to learn from doing so.

**What this settles:** the app-side planning work — the semi-join gate,
`reorder_joins`, `edge_fanout` — is not undermined by the configuration finding.
The misestimations it was built to work around were real, they were in plan
shapes the fixes eliminated, and a correctly configured planner still chooses
the same plans for the queries that fit.

**RESOLVED 2026-08-12 — the edge-traversal underestimates are not a
configuration artifact, and cannot be.** Row estimates come from statistics;
`shared_buffers` and `effective_cache_size` feed COST. Confirmed by holding the
query fixed and sweeping the setting across a 192x range:

    effective_cache_size    est rows      plan shape      top cost
    48GB                    identical     identical          4,151
    4GB                     identical     identical          4,876
    256MB                   identical     identical          4,953

Only cost moves. So no cache setting can change a cardinality estimate, and the
worry that `059`'s figures might be a configuration effect is unfounded by
construction as well as by measurement.

**The underestimates are still real, and much smaller than recorded.** Worst
join-node ratios on the current plans, 100k fixture:

    eq/KGTextSlot          est 194     actual 7,161     36.9x
    gte/KGIntegerSlot      est  46     actual 1,412     30.7x
    not_has/KGTextSlot     est  31     actual   273      8.8x
    not_exists/KGTextSlot  est 52,326  actual 100,000    1.9x

Up to ~37x, not 305x or 4,761x — and, exactly as with `072`, the recorded
magnitudes belonged to plan shapes the fixes replaced, so they cannot be
re-tested as written without reverting those fixes. The queries are now fast
DESPITE the underestimates, because `reorder_joins`, `edge_fanout` and the
semi-join gate make the join-order decision instead of the planner.

**A citation problem worth recording.** The figures "305x and 4,761x" are
attributed to `issues/059` in `issues/061` (twice) and propagated into two
planning documents. **`issues/059` contains neither number.** They have been
used to justify app-side planning work ever since. The conclusion they support
is sound and is now independently measured, but the specific figures have no
traceable source — treat them as unsourced rather than as evidence.

## Original triage criterion (superseded by the above)

A conclusion is at risk if it rests on a **wall-clock timing**. It is safe if it
rests on a **buffer count**, a **row count**, or a **plan shape** — none of which
the pool affects.

This is not hypothetical: `issues/080` opened with a 404x figure that is now
616 ms, and four implementation attempts were spent chasing a query-shape
explanation for a memory setting.

## At risk — conclusion rests on timings, with no buffer or plan backing

| issue | what is in question |
|---|---|
| `045` | semi-join rewrite, "24.5-32.3 s -> 2 ms". The FIX is structural (the rewrite fires or it does not), so the direction stands; the magnitude does not. |
| `058` | `ne` "times out on all five slot classes". Timeouts on a 1 GB pool are the same signature as `078`'s, which vanished. |
| `059` | negation evaluated backward as a set. Direction is plan-shape, magnitudes are timings. |
| `060` | "31x on a real query" for the edge type column. |
| `061` | criterion ordering — 40 timing claims, no buffer counts. The reverts it records (7 range cells 3-14 ms -> 30 s) were also timings. |
| `071` | `is_empty` at 52 s. |
| `073` | absent constant as worst case. |
| `048` | frame_entity rewrite "not a pessimization" — settled on timings. |

## Partly at risk — timings plus buffers or plan shape

| issue | safe part | at-risk part |
|---|---|---|
| `040` | buffer curve (45 buffers x rows joined) | the latency figures |
| `039` | covering-index buffer counts | latency |
| `047` | that the plan FLIPS to a blocking sort | the thresholds (19, 52, 174), which come from cost estimates that `effective_cache_size` feeds |
| `053` | "0 cells over the buffer threshold" | "0 cells slow warm", and the 4 "slow COLD only" cells — that is exactly what a too-small pool produces |
| `057` | which bodies bypass the pipeline | the timings |
| `070` | the trigram finding (10,467,626 index rows for a 2-char infix is structural to pg_trgm) | `contains` latencies |
| `072` | nested-loop misplanning is real | **and `effective_cache_size` at 4 GB biases the planner AWAY from index scans, so part of this may BE the configuration** |
| `078` | O(offset) shape | the absolute numbers |
| `080` | criteria 38 ms vs resolution 19 s (from plan node timings inside one execution) | everything else |

## Safe — no re-measurement needed

* `074` — withdrawn on a buffer count, and the tool bug it found is unaffected.
* `056` — rests on ANALYZE sampling behaviour and statistics targets.
* `044`, `079` — correctness and boundedness; `079`'s 181 s sweep is O(edge
  table) structurally, which the pool does not change.
* `062`, `064`, `068` — write-path correctness.
* Every plan shape recorded anywhere: cross products, inverted joins, `rows=1`
  against 9,220 actual, `EXISTS` probe structure.

## What to do

1. **Re-run the comparator sweep** on the corrected configuration and compare
   against `053`'s closing table. That single run re-baselines the largest block
   of at-risk claims at once.
2. **Re-measure `072` specifically**, because the misestimation it documents may
   be partly an `effective_cache_size` artifact rather than a statistics one —
   and a great deal of app-side planning has been built on the belief that
   PostgreSQL cannot get these right.
3. **Do not re-litigate the FIXES.** Almost all of them changed a plan shape,
   and plan shapes are unaffected. What changes is how large the wins were, and
   therefore which further work is worth doing.

## The safeguard existed and was half-wired — fixed 2026-08-11

The pytest harness ALREADY stamps the server configuration:
`perf_record.PG_SETTINGS` lists `shared_buffers`, `effective_cache_size`,
`work_mem`, `random_page_cost` and more, and `pg_stamp()` reads them. Verified
working today — it returns `shared_buffers=16GB, effective_cache_size=48GB`.

But the committed baseline (`tests/performance/baselines/main.json`, promoted
from a 2026-08-06 run) has an EMPTY `env.pg`. So the mechanism is there, the
data slot is there, and nothing populated it for the run that became the
baseline. A safeguard that exists and produces nothing is worse than an absent
one, because its presence implies the check was made.

`scripts/perf_comparator_timing.py` had NO such mechanism at all, and it is the
tool that produced the sweep numbers this issue is about. **It now prints its
configuration as the first line of every run:**

    server: effective_cache_size=48GB  max_parallel_workers_per_gather=2
            random_page_cost=1  shared_buffers=16GB  work_mem=64MB
    fixture: sp_lead_synth_100k

### Answered 2026-08-16 — and the interesting half is why it stayed invisible

**Why it was empty.** `pg_stamp`, the conftest wiring that populates
`env["pg"]`, and the promoted baseline all arrived in the SAME commit
(`63163ee`, 2026-08-06). The run that became the baseline did not carry the
stamp the commit introduced. That much is mundane.

**Why nothing noticed for six days is the real finding.** `compare_env` gated
on:

    if a is not None and b is not None and a != b

which reads as careful and means an ABSENT value can never disagree with
anything. So the empty baseline stamp did not FAIL the configuration gate — it
DISABLED it. A disabled gate reports exactly what a satisfied one reports, and
`perf_compare` printed no environment problems for every run compared against
it.

Measured on the committed baseline:

    compare_env(stamped_run, committed_baseline)  ->  []      (before)
    compare_env(stamped_run, committed_baseline)  ->  4 problems  (after)

**Fixed.** Absence is now reported rather than skipped, in both directions and
per-key, and `promote()` REFUSES a run with no stamp — promotion being the
moment a run becomes the thing everything is later compared against.
`--force-unstamped` exists and records `baseline.pg_stamped: false` in the
artifact, so an override leaves a trace instead of producing a baseline
indistinguishable from a good one.

**Re-promoted 2026-08-16.** The baseline now carries
`shared_buffers=16GB, effective_cache_size=48GB, server_version=18.4` and
`baseline.pg_stamped: true`, and a comparison against a differently-configured
run reports it:

    pg.shared_buffers: baseline='16GB' run='1GB'

Two caveats recorded rather than smoothed over, both visible in the artifact and
printed by `perf_compare`:

* **37 of its 105 benches are holes**, against 20 usable in the old one — so it
  gates more, not less, but not everything. 18 of those holes are `issues/099`,
  a fixture loaded from only part of its own data; the rest are skips and
  unrecorded metrics.
* **Recorded from a dirty working tree**, so the baseline commit will not
  reproduce it exactly. Flagged in `env.git.dirty` and shown as
  `[DIRTY WORKING TREE]` on every comparison.

Neither is a reason to keep an unstamped baseline instead — an unstamped one
cannot be shown comparable to anything, and that was the actual defect.

Every ad-hoc timing script written during this investigation also lacked a
stamp — including all of mine.

## The rule this earns

**Record the server configuration alongside any performance number.** Not one
measurement in this repository states the `shared_buffers` it was taken under,
which is exactly why nobody noticed they were all taken under a wrong one.
`scripts/perf_comparator_timing.py` and the perf harness should emit it in their
headers.

## Related

- `issues/080`, `078` — the two re-measured in full.
- `issues/075` — decision D1, reopened because its justification is a timing.
- `planning/planning_performance/two_phase_kgquery_paging_plan.md` — the fuller
  account and the reassessment section.
