# `perf_compare` Drops A Metric With No Threshold Rule, In Silence

## Status: PARTLY FIXED 2026-09-12 — the absence is now VISIBLE. The 106 rules
## are still unwritten, so 37 of 108 query cells still cannot turn red.

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
