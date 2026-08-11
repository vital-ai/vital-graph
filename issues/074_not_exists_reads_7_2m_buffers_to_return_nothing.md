# `not_exists` Reads 7.2M Buffers to Return Zero Rows

## Status: OPEN — found 2026-08-10 by the sweep's new buffer metric

    not_exists/Double    7,236,177 buffers    191 ms warm / 236 ms cold    0 rows
    not_exists/Text      7,236,171 buffers    203 ms warm / 2,353 ms cold  0 rows

For comparison, on the same fixture and page size:

    not_has/Text            ~20k buffers       72 ms
    has_any/Text            ~30k buffers       80 ms

## Why this was invisible until now

Nothing was wrong with its wall time. At ~200 ms warm it sits comfortably below
every threshold, has never appeared in `issues/053`'s slow list, and would pass
any timing-based regression gate. It reads **360x** the buffers of a comparable
cell.

`scripts/perf_comparator_timing.py` reported only a single cold wall-clock
number until this was added. The first run with buffers surfaced this
immediately — which is the argument for the metric, made concrete:
`performance_regression_tracking_plan.md` R1 chose structural metrics as the
primary signal, and this is what that buys.

## Why it matters even though it is fast

7.2M buffer touches is ~55 GB of buffer traffic for a 25-row page that returns
nothing. It is fast *here* because the fixture fits in cache. The same query on
a space that does not fit, or under concurrency where those buffers evict other
queries' working sets, is a different story — this is exactly the shape that
degrades non-linearly with scale, and the wall clock on a warm single-user box
says nothing about it.

Also note `not_exists`/Text's cold/warm ratio: 2,353 ms against 203 ms, an 11.6x
gap and the widest of any cell. Consistent with reading far more data than it
needs.

## Not yet diagnosed

No `EXPLAIN ANALYZE` has been run. Two starting hypotheses, both cheap to test:

1. **Same shape as `is_empty`.** `not_exists` negates a VARIABLE-object pattern
   (`?slot p ?v`), unlike `not_has` which negates a constant-object one. The
   candidate-driven fold in `issues/057`/`059` needs the constant, so this may be
   falling back to a per-candidate probe that scans the whole predicate. That
   would also explain `is_empty`, whose NOT EXISTS rewrite failed for exactly
   this reason (`issues/072`).
2. **The probe is not early-terminating.** It returns 0 rows, so every candidate
   is tested and none survives; if each test scans rather than probes, the cost
   is entities x scan.

If 1 holds, `not_exists`, `is_empty` and the `not_has_any` family share one
underlying gap — negation over an unbound object — and fixing it once would
close the last genuinely slow cell in `issues/053`.

## Related

- `issues/053` — the sweep; `not_exists` has never been on its slow list
- `issues/072` — `is_empty`, the other variable-object negation
- `issues/057` / `059` — the negation fold, which handles the constant-object case
- `performance_regression_tracking_plan.md` R1/R1.1 — why buffers lead
