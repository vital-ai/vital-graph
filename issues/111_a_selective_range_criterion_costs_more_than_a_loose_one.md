# The More Selective a Range Criterion, the More It Costs

## Status: OPEN — and this is a REDISCOVERY. `issues/archive/040` documented it,
## then it was archived with the regression unfixed and the gate re-pointed away.

Filed 2026-08-20 from measurements, before finding the archive. Keeping it,
because how it stopped being visible is more useful than the measurement.

## What is measured today

`sp_lead_synth_100k`, a 25-row page under `MQLRating >= t`:

        t   matches    buffers   buf/match
       99     1,017  3,768,476     3705.5
       90     9,907     70,471        7.1
       65    34,790     24,798        0.7
       50    49,814     14,110        0.3
        0   100,000      5,477        0.1

1,017 rows cost 3.77M buffers — 688x the query returning 100x MORE rows. The 10k
fixture is the same shape (2,972 buf/match at t=99 against 0.3 at t=0), so it is
not a large-fixture artifact. `test_range_comparator_pays_for_every_candidate[100k]`
takes 72 seconds, four times the next slowest bench in the repo.

**Every node in the t=99 plan runs at `loops=100000`** — the entity set driven
through per-candidate probes, which is the archived issue's title verbatim:

    t=99   822,542 buf  loops=100000  Index Scan       idx_..._edge_dst_src
           422,543 buf  loops=100000  Index Only Scan  ..._rdf_quad_pkey
    t=90    70,374 buf  loops=1       Index Only Scan  ..._rdf_quad_pkey
            34,151 buf  loops=8482    Index Only Scan  ..._rdf_quad_pkey

## What `issues/archive/040` already said

Under "W2/W4 were declared fixed on a 10,000-entity fixture":

    |     | MQLRating >= 99.9        | matches | buffers  | vs equality |
    | 10k | uses idx_*_term_num      |      16 |    1,337 |        1.6x |
    | 100k| falls back to PK lookup  |     145 |  578,885 |       76.8x |

> 10x the data and 9x the matches, but **433x the buffers**.

with the cause named: PostgreSQL estimates the numeric expression as a fixed
fraction of the table, predicts ~3.5M rows from a range returning 145, and
concludes the index is not worth using. And with the fix family named — force the
shape rather than trust the planner, or extend statistics so the estimate tracks
the distribution.

**That document's status line is `BOTH HALVES FIXED (verified at two scales)`.**
The regression is recorded inside a document declared fixed, and the document was
archived.

## How it stopped being visible — three defensible steps

1. **The gate that caught it still exists and still asserts.**
   `RANGE_VS_EQUALITY_MAX = 8.0`, `test_kgquery_growth_curve.py:406`. The archive
   records it firing at 76.8x.

2. **It was re-pointed away from the case it caught.** The test now picks the
   judged threshold as the one whose match count is closest to the largest
   equality case:

       # Judge the range at a threshold whose selectivity is comparable to an
       # available equality case, rather than at the extreme.

   With `EQ_STATES` led by `CA`, that selects a LOOSE threshold. Today it reports
   `range is 1.2x` equality and passes, while t=99 sits at 3,705 buf/match. The
   reasoning is sound in itself — the gate sends low- and high-selectivity
   criteria to different plans, so comparing across that boundary compares two
   plans. The consequence is that the extreme is measured, recorded via
   `perf_record`, and gated by nothing.

3. **The issue was archived**, so the standing regression left the working set.

None of the three is wrong on its own. Together they retired a documented 433x
regression without anyone deciding to.

## Two things I got wrong before finding the archive

* I predicted the probe/set-join gate, from the test's own comment. The plans say
  otherwise: t=90 is an ordered scan stopping at the page, t=99 sorts 100,000
  candidates.
* I wrote that "both obvious explanations are wrong". The second one — planner
  estimate leading to the wrong access path — is the archive's diagnosis and is
  the right family. What is genuinely new is that the specific plan has changed
  since 2026-08-07: the archive saw `term_pkey` displacing `idx_*_term_num`;
  today neither term index appears and the cost sits in `rdf_quad_pkey` and
  `edge_dst_src` at 100,000 loops.

## The `enable_sort` fence is not the answer here

    t=99   needs_ordered_scan=False   unfenced 3,766,045   fenced 2,110,740
    t=90   needs_ordered_scan=True    unfenced    70,474   fenced    70,471

The flag is FALSE for the shape that most needs it, so production really does run
the unfenced plan — the benchmark is not measuring something that never executes,
which was the risk worth ruling out (`issues/081`). And fencing by hand recovers
only 44%. See `issues/047` for what the fence is for.

## What to do

1. **Decide whether the extreme should be gated at all**, and say so in the test
   either way. A number that is measured, recorded, and watched by nothing is the
   state that let this return.
2. Establish why `needs_ordered_scan` is False at t=99 and True at t=90.
   `emit_slice` sets it in two places and the tighter shape misses both. A flag
   that tracks selectivity rather than plan shape will keep being wrong.
3. Take the fix family the archive already identified — make the selectivity
   visible to the planner (materialised uuid list or fenced subquery), or extend
   statistics — now that `rdf_value_stats` and the criterion gate exist, which
   they did not on 2026-08-07.

## Related

- `issues/archive/040` — the original, with the 433x table and the cause
- `issues/047` — the `enable_sort` fence, and why a GUC rather than a hint
- `issues/045`, `issues/046` — the other two caveats 040 was archived carrying
- `issues/081` — a benchmark measured against an unrecorded configuration; the
  fenced-vs-unfenced split above is the same trap, avoided by measuring both
