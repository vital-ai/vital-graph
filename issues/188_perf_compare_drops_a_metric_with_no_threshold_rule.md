# `perf_compare` Drops A Metric With No Threshold Rule, In Silence

## Status: PARTLY FIXED 2026-09-12 — the absence is VISIBLE, and the one metric
## that needed no sampling is now GATED (`1834b857`). The 91 NUMERIC rules are
## still unwritten, and BLOCKED ON A SUITE THAT CANNOT BE SAMPLED — see
## "Why the numbers could not be measured".

**Related:** `issues/081` (a gate disabled by absence, same shape),
`issues/112` (the one metric where this was noticed and fixed),
`planning/planning_performance/perf_coverage_gaps_plan.md` §1

## The defect

`rule_for()` returns None when `thresholds.toml` has no entry for a metric, and
the comparison loop did:

    rule = rule_for(thresholds, bench_id, metric)
    if rule is None:
        continue

No FAIL, no WARN, no INFO. "Nobody wrote a rule" and "the rule passed" printed
identically: nothing. Measured 2026-09-12 against the committed baselines:

| | |
|---|---|
| distinct metric names recorded | 121 |
| with any rule | 15 |
| that actually gate (rest are `report_only`) | 10 |
| **unruled, never compared** | **106** |
| query cells with no gating metric AND no plan shape | **37 / 108** |

The unruled names are not telemetry — they are the claim each bench exists to
make: `underestimate_factor`, `range_vs_equality`, `growth_ratio`, `sort_ratio`,
`sorted_depth_ratio`, `deep_ratio`, `spill_ratio`, `advantage_ratio`,
`flatness`, `flips_within_range`, `partitions_scanned`, `buffers_per_match`,
`deep_offset_ratio`. Whole families have no gating cell: aggregates,
`range_penalty`, `page_size_cliff`, both sorted-paging benches, the deep-paging
curve, relation traversal, the values clause, partition pruning.

`flips_within_range` is the sharpest case. It records `false`, and the bench
exists to notice it becoming `true` — the page-size cliff appearing. That flip
was dropped on the floor.

## Not "unguarded" — undetected DRIFT

Two things still held and should not be overstated away:

* every one of these benches carries an inline absolute floor that fails on its
  own (`assert ratio < 20`, `test_frame_slot_paging_bench.py:149`);
* non-numeric metrics are compared without a rule, so `node_types`,
  `with_index_node`, `growth_class` still WARN on change.

What was missing is the second layer. `tests/performance/README.md` states the
baseline's purpose exactly — the drift detector that catches "a 40% degradation
that still clears the floor". For 37 of 108 cells that sentence was false.

## Why nothing noticed

The same shape as `issues/081`: an absent value could not disagree with
anything, so the gate was not failing — it was disabled, and a disabled gate
reports the same "no problems" as a satisfied one.

`thresholds.toml` already carries `[metrics.min_ratio]`, added when someone
noticed `deep_paging.monotonic` was gating a coin-flip buffer count while its
own claim had no rule. Right diagnosis, applied to one metric, never
generalised.

## Fixed so far (2026-09-12)

`perf_compare` gained an `UNRULED` bookkeeping level, a `benches_with_no_gate()`
helper and a `--strict-rules` flag. A comparison now ends:

      ✅ 108/108 benches within tolerance
      ⚠️  261 metric comparisons skipped for want of a rule (92 distinct names)
          37/108 benches have no gating metric and no plan shape

Reported as ONE aggregate line, deliberately: `ok_benches` counts a bench as
within tolerance only if nothing WARNs against it, so a warning per unruled
metric would have taken the headline from 108/108 to ~30/108 and buried every
real warning under 106 lines of bookkeeping. Exit code is unchanged — only FAIL
sets it — so this gates nothing new.

Pinned by `tests/unit/test_unruled_metrics_are_visible.py`, which also pins that
`report_only` counts as RULED: "classified, and here is why it does not gate
yet" must stay distinguishable from "nobody looked".

## The one that needed no sampling — DONE (`1834b857`)

Classified the 95 unruled metrics in `query.json` by type:

    numeric      91     need a measured noise band
    boolean       1     flips_within_range
    string        3     node_types, with_index_node, without_index_node

The three strings already WARN on change without a rule, so they are gated in
practice. **`flips_within_range` is the only cell that could be fixed without
sampling anything** — there is no spread for a boolean, any change is the event
— and it is the sharpest case in this issue. Gated at `warn_pct = 0`,
`fail_pct = 0`; `pct_change` returns `inf` from a `false` baseline, so the flip
fails without a mechanism of its own.

## Why the numbers could not be measured

The instruction below — sample 3-4 times on an unmodified tree — was attempted
on 2026-09-12 against the live seeded stack (105 GB, 16 GB `shared_buffers`,
all gated fixtures excluded from maintenance, so the statistics could not move
under the run).

**It did not get past the first sample.** After 25 minutes the suite was at 23%
and one query had been running for 15 of those minutes continuously. Four full
samples is not hours, it is most of a day, and nothing in this issue is worth
that much wall-clock.

That is a finding about the suite rather than about these thresholds: **a
benchmark suite that cannot be run four times cannot have measured thresholds**,
and every numeric rule here depends on exactly that. It belongs with
`issues/192` / `issues/193`, which are about the suite's shape.

Two ways forward, and the choice is not obvious:

1. **Sample a fast SUBSET.** Pick the benches that complete in seconds, measure
   their claim metrics properly, gate those, and leave the slow benches
   unruled with a comment. Honest and partial.
2. **Find out why one bench runs for 15 minutes first.** It may be a real
   pathology worth its own issue, in which case sampling around it is measuring
   the wrong thing. The query was a `SELECT DISTINCT` over a projected
   sub-select; the fixture was not identified before the run was stopped.

(2) first, on the grounds that a 15-minute bench is either a bug or a fixture
that should not be in a suite anyone is expected to re-run.

## What remains

Classify the 106 into **claim** (gate), **context** (`report_only`) and
**timing** (`report_only`), per the convention in the plan §8: floor in the
test, drift in the baseline, both, always.

**Do not invent the numbers.** `thresholds.toml`'s `copy_speedup` comment is the
standard — four samples on unchanged code spread 8.81 to 11.11, and the warn
band had been sitting inside that noise. Sample 3-4 times on an unmodified tree
first; a claim metric whose spread is unknown ships `report_only` with a comment
saying so.

Booleans need a rule, not a mechanism: `pct_change` returns `inf` from a zero
baseline, so `false → true` and `1 → 0` both fail correctly once a
`warn_pct = 0, fail_pct = 0` rule exists.

Closing this requires a re-promotion (`issues/190`), which must come after, not
before.
