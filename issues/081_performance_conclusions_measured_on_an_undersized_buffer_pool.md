# Most Performance Conclusions Were Measured on a 1 GB Buffer Pool

## Status: OPEN — triage below, 2026-08-11

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

## The triage criterion

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
