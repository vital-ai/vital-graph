# `not_exists` Reads 7.2M Buffers — WITHDRAWN, It Reads 402k

## Status: NOT A DEFECT — withdrawn 2026-08-10, same day it was filed

The 7,236,171 figure was a measurement bug in the tool that produced it. Correct
numbers, from the same sweep after the fix:

    is_empty/Text        3,302,262 buffers    337x the median   <- the real outlier
    not_exists/Text        402,187 buffers     41x
    not_exists/Double      402,186 buffers     41x
    median of 39 cells       9,805 buffers

`not_exists` examines 100,000 entities to establish that none qualify, so 402k
buffers is roughly 4 per entity. That is unremarkable, and there is nothing here
to fix. `is_empty` is the outlier, and it already has `issues/072`.

## The bug, because it is worth not repeating

`scripts/perf_comparator_timing.py` had just been changed to report buffers
precisely BECAUSE wall-clock had produced two false findings in this effort. Its
first version summed `shared hit/read` across every node of the plan.

`EXPLAIN` reports buffers **cumulatively**: a node's line already includes
everything its children touched. Summing therefore multiplies by roughly the
depth of the tree — 5.4x here — and the deeper the plan, the bigger the
inflation. So the metric introduced to be trustworthy manufactured a finding
within the hour, and it did so in a way that scales with plan complexity, i.e.
worst exactly where the attention should go.

Fixed to take the maximum, which is the root and is cumulative for the whole
plan. Documented caveat: a CTE evaluated as its own subtree can be reported
outside the root's count, so the figure is a lower bound for plans with CTEs —
which the candidate-driven negation path produces.

### A second, independent error on the same number

Diagnosing this, a hand-written `EXPLAIN` gave 1,336,741 — also wrong, and
wrong differently. It applied `SET LOCAL enable_sort = off`, which the executor
applies only when the plan declares `needs_ordered_scan`. `not_exists` declares
False, so that measured a plan production never runs.

Three figures for one cell (7,236,171 / 1,336,741 / 402,187), two of them from
my own tooling and hand-checking, before the right one. Both mistakes are
prevented by going through the shared helper — `perf_ab.py` and the sweep's own
`_run` both apply the fence conditionally, from the plan's flag, rather than
unconditionally.

## What survives

Nothing about `not_exists`. What survives is the case for the metric, which the
corrected numbers make BETTER rather than worse: `is_empty` reads 337x the
median, identically cold or warm, and that ratio is visible without any timing
discipline at all. The instrument was right; this reading of it was not.

## Related

- `issues/072` — `is_empty`, the genuine outlier
- `performance_regression_tracking_plan.md` R1/R1.1 — why buffers lead
