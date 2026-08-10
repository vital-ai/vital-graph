# `num_val` Is Too Sparse for ANALYZE to Sample, So Range Estimation Collapses at 100k

## Status: FIXED 2026-08-10 — statistics target raised in the schema; TIMEOUT -> 7-20 ms

**Title and framing corrected.** This was filed as "`idx_*_term_num` inverts sign
with scale" on evidence that dropping the index made four cells 100x faster.
That evidence was real but the conclusion was wrong: the index is not the
problem. Bad statistics were, and they made the planner *misuse* the index.
See "How the first diagnosis went wrong" below — the error is worth keeping
because the measurement method that produced it looks sound.

## Is the index worth keeping? Yes — verified at both scales

Measured with arms alternated, repeated, first run discarded, and confirmed
order-independent:

| | planner uses it? | its estimate | with | without |
|---|---|---|---|---|
| 10k | **yes** — `Index Cond: (num_val <= 65.0)` | `rows=808`, correct | **1.5 ms** | 5.5 ms |
| 100k | **no** — `term_pkey` + `Filter` | `rows=1` | ~7 ms | ~7 ms |

At 10k it is a genuine 3.5-4.5x win and the planner chooses it. At 100k the
planner declines it and reaches the term by traversal instead, so it costs
nothing and earns nothing. Nothing is measurably worse for having it.

The two fixtures hold nearly the same number of numeric terms — 1,289 and 1,290
— but 1.05M and 10.5M total rows, so density differs 10x (0.12% vs 0.012%).
That is the whole reason the planner's choice flips, and why the same index is
load-bearing at one scale and inert at the other.

## The defect

Terms are deduplicated, so 100,000 entities sharing ~1,000 distinct one-decimal
rating values produce **1,290 non-NULL `num_val` in a 10,467,626-row term
table** — `null_frac` 0.99993.

The default statistics target samples ~30,000 rows, which at that null fraction
captures about **two** non-NULL values:

| | `null_frac` | histogram buckets |
|---|---|---|
| 100k | 0.99993 | **2** |
| 10k | 0.99847 | 46 |

Two buckets is not a histogram. `num_val <= 65.0` therefore estimates `rows=1`
against **809 actual**, and the planner — believing the leaf yields one row —
drives a nested loop from `idx_*_term_num` and enumerates 809 candidate terms
*per probe*, 31 probes deep into a paged scan. A 25-row page times out at 60 s.

At 10k the identical column is dense enough for 46 buckets, estimates correctly,
and nothing goes wrong. That is why this survived: the index and the push-down
were validated at the only scale where the statistics happen to work.

## Fix

    ALTER TABLE {space}_term
      ALTER COLUMN num_val SET STATISTICS 10000,
      ALTER COLUMN dt_val  SET STATISTICS 10000

In `sparql_sql_schema.create_space_indexes_sql`, beside the existing per-column
targets on the skewed uuid columns. 2 buckets -> 356, and ANALYZE on 10.4M rows
costs 8.3 s — cheap *because* the column is sparse.

Steady-state, warm, after the fix — and with the index present, which no longer
matters:

| cell | before | after |
|---|---|---|
| `lte`/Double | TIMED OUT (>60s) | **~7 ms** |
| `lt`/Integer | TIMED OUT (>60s) | **~12 ms** |
| `gt`/Double | 697 ms | **~19 ms** |
| `gte`/Double | ~19 ms | ~19 ms |

With good statistics the planner stops choosing `idx_*_term_num` for these
queries entirely: both plans use `term_pkey` with `Filter: (num_val <= 65.0)`,
reaching the term by traversal and checking the value, rather than enumerating
values and checking membership. For a *correlated probe* that is obviously the
right direction — the entity is already known — and it is what the bad estimate
was suppressing.

## How the first diagnosis went wrong

The bisect was: drop the index inside a transaction, re-measure, roll back.

    BEGIN; DROP INDEX idx_..._term_num; EXPLAIN (ANALYZE) <query>; ROLLBACK;

That isolates the index cleanly and is why the *pre-fix* numbers were valid — a
60 s timeout cannot be a caching artifact. But after the statistics fix the two
arms became genuinely identical, and the remaining difference was **cold
cache**: the
"without" arm always ran second, on buffers the first arm had warmed.

Alternating the order and repeating exposes it immediately:

    run  without   with
     1   593.975   18.880      <- first execution, cold
     2    20.956   19.335
     3    20.289   18.841

Only run 1 differs, and it differs whichever arm goes first. A single
measurement per arm would have reported a 30x effect that does not exist — and
did: this issue originally recorded "229 ms with / 38 ms without" as a residual
pessimization. Both figures were first-runs; the steady state is ~7 ms for both.

**Rule this produces:** a with/without comparison needs the arms alternated and
repeated, and the first run of each discarded. Confirming this took three
repetitions and about a minute.

## Related

- `issues/040` — the range push-down, certified at 10k; this is why the
  certification did not transfer
- `issues/053` — four of its cells were this
- `issues/055` — the missing indexes that preceded this investigation
- `scaling_test_strategy.md` — principle 9, an optimization can invert sign with
  scale, so "validated" must name a scale
