# The More Selective a Range Criterion, the More It Costs

## Status: FIXED 2026-08-20 — and it was never a performance problem

**The tight threshold was not filtering.** `MQLRating >= 99` with a 60,000-row
page returned 60,000 rows where 1,017 match, and neither `num_val` nor `99`
appeared anywhere in the generated SQL. The buffer curve below is what an
unfiltered scan costs; "3,705 buffers per match" divided real work by a match
count the query never honoured.

    before   60,000 rows returned, 1,017 match, 3,769,467 buf, 1,944 ms
    after     1,017 rows returned, 1,017 match, 1,496,337 buf, 1,663 ms
    (t=90)     9,907 rows match,   page correct,    70,471 buf,    77 ms

**Correct, and 60% fewer buffers — but only 14% faster.** The commit message
says "60% cheaper", which is true of buffers and misleading about time. These are
cache hits in a 16 GB `shared_buffers`, so the buffer count overstates the
latency impact; warm, best of three, the page went 1,944 ms -> 1,663 ms.

The number that matters is the last row. A page returning 1,017 matches takes
**21x longer than one returning 9,907** (1,663 ms against 77 ms). The correctness
fix did not touch that, and it is the real remaining problem.

### The cause

`_try_selective_driven` (`emit_slice`) pages from a selective criterion instead
of the entity anchor, choosing it with `_leaf_rows`. `_leaf_rows` counts three
things: constant leaves the BGP binds, plus `range_stats` and `text_stats` —
measurements of FILTERs sitting ABOVE the join, keyed by predicate precisely
because filter and predicate live at different levels.

Counting all three is right for the SEMI-JOIN gate, which decides whether to
PROBE a subtree. It is wrong for deciding whether to DRIVE from one, because
`emit_bgp_anchor` emits the BGP's constant leaves and not the filter. Driving on
a filter-derived count reproduces the row count without the predicate that
produced it.

`driver_n` is now measured with `filter_derived=False`. The anchor side still
counts everything — it is probed, not driven, so filter-derived selectivity is
legitimate there.

### The guard existed and did not cover this

The unmeasured branch says it outright:

> A text criterion is a pushed FILTER, so driving from its BGP drops the ILIKE
> entirely — measured: `contains 'ZZQQXX'` returned 25 rows for a substring
> matching nothing. Fixing this means teaching the driver to carry pushed filter
> conditions; until then the guard stays.

That fires when the count is MISSING. A numeric range has the identical shape and
`range_stats` gives it a number, so it walked straight through the guard written
for it. `_emit_two_phase` had already learned the lesson — it pushes the filters
and refuses if any survive, with a comment naming this exact failure —
and `_try_selective_driven`, added afterwards for `issues/061` step 3, inherited
neither the push nor the check.

### THREE PROPOSED FIXES, ALL MEASURED, ALL FAIL

Recorded so nobody spends the day I spent. Warm, best of three/five, t=99 on
sp_lead_synth_100k, 25-row page:

    as generated                    1,877 ms   1,496,337 buf
    fenced (OFFSET 0)               7,763 ms  10,783,176 buf   4x WORSE
    materialised CTE                1,957 ms     606,072 buf   60% fewer buffers,
                                                               no faster
    push filters into the driver    2,753 ms                   consistently worse

The first two are `issues/archive/040`'s own suggestion — "emit a push-down whose
selectivity is visible (a materialised uuid list, or a fenced subquery)". The
third is what `_try_selective_driven`'s comment proposes — "teaching the driver
to carry pushed filter conditions" — implemented by pushing the FILTERs into the
driver BGP before measuring, the way `_emit_two_phase` does. It stays correct and
it is slower at both thresholds.

**Buffers are not time on this stack.** The CTE removes 60% of the buffer traffic
and gains nothing, because a 16 GB `shared_buffers` makes these cache hits. Every
proposal above, and the whole of `archive/040`, optimises buffers. That is the
wrong target here and it is why the proposals do not land.

### Where the time actually goes

`EXPLAIN (ANALYZE)` self-time, t=99, total 1,973 ms:

     self ms    %    loops       rows    buffers  node
         990  50%        3     33,333     67,429  Hash Join
         600  30%  100,000          1    500,000  Index Scan rdf_quad
         416  21%        3  1,659,000     66,360  Seq Scan {space}_edge
         400  20%  100,000       0.01    400,000  Index Scan term

Half the time is one Hash Join, and a fifth is a SEQUENTIAL SCAN of all 1.66M
edge rows. It is not the per-candidate probing the issue name describes — that is
the 30%/20% pair. This is the other half of the trap
`_try_selective_driven` documents:

> The semi-join gate declines ... and that call is CORRECT. But the set-based
> join it falls back to materialises the large criterion. Neither plan fits, so
> no threshold reaches one.

The correctness fix made the gate decline correctly, and this seq-scanning
set-based join is what it declines TO. Any real fix has to give this shape a
third plan, not tune either of the two that do not fit.

### THE THIRD PLAN EXISTS, AND THE DATA IS ALREADY THERE

`{space}_entity_slot_sort` holds one row per (entity, frame, slot) with the value
split into `value_text` / `value_num` / `value_dt`, and carries

    idx_{space}_ess_num  btree (context_uuid, entity_type_uuid, frame_type_path,
                                slot_type_uuid, value_num, entity_uuid)
                         WHERE value_num IS NOT NULL

which is exactly this query's shape: fix the context, entity type, frame path and
slot type, range-scan `value_num`, read `entity_uuid` straight out of the index.

Measured against the same criterion the edge walk takes 1,877 ms to answer:

    entity_slot_sort, MQLRating >= 99      1.56 ms      736 buffers
    the edge walk it replaces          1,877.00 ms  1,496,337 buffers

**~1,200x faster, ~2,000x fewer buffers**, and exact on every threshold:

        t   entity_slot_sort   manifest
     99.9              145        145
       99            1,017      1,017
       90            9,907      9,907
       65           34,790     34,790

#### The preconditions, checked

* **It is write-synced**, in five places on the write paths, and handles a
  CHANGED value: `sync_entity_slot_sort_after_edge_insert` deletes before
  re-deriving "so a CHANGED value replaces its row rather than losing to" the
  old one.
* **Drift is detected and repaired** — `maintenance_job._run_entity_slot_sort_integrity`.
* **It is not a new trust tier.** `rewrite_edge_table` already answers traversals
  from `{space}_edge`, a derived table with the same freshness story. Filtering
  from `entity_slot_sort` is the same bargain, not a worse one.
* `fast_slot_sort` declines on any criterion because it SORTS — "it does not know
  which entities a criterion admits, and applying the sort to an unfiltered set
  would page through the wrong population". Using the table to FILTER is the
  opposite direction and does not inherit that objection.

#### Built 2026-08-20 — `slot_sort_range.py`

    >= 99.9    145 matches   1,886 ms ->  16 ms   118x
    >= 99    1,017 matches   1,877 ms ->  61 ms    31x
    >= 90    9,907 matches      77 ms ->  81 ms   unchanged, the gate declines

Row counts exact against the manifest at all four thresholds.

**It anchors on the SLOT, not the entity, which removed the risky part.**
`entity_slot_sort` is keyed on `(slot_uuid, context_uuid)` and that row carries
the slot's type and value, so "slots of type T with value >= L" is exactly what
the chain already requires of `?slot`. Nothing is replaced and the answer cannot
change — the constraint only hands PostgreSQL a small indexed set to start from.
No `frame_type_path` matching is involved, so the near-miss that returns wrong
rows is not reachable.

**The gate is the whole thing, and it was wrong twice before it was right.**
Ungated, the loose threshold went from 77 ms to a TIMEOUT — a 9,907-row IN list
destroys a plan that already worked. Gated on `MIN_SELECTIVITY` it still timed
out, because the first denominator was `pred_stats[hasDoubleSlotValue]`, which
counts every double-valued slot in the space (3.9M) rather than MQLRating's
100,000: 9,907 read as 0.25% and sailed through. Against its own slot type it is
9.9% and declines. The denominator is now the `quad_stats` pair count for
(hasKGSlotType, T).

`MIN_SELECTIVITY = 0.05` is `semijoin`'s existing threshold, reused rather than
invented — its comment describes this same cliff ("a criterion matching 9% of
entities went to 0.77x the baseline while one matching 0.96% went to 889x"), and
1.0% and 9.9% here straddle it.

#### What was NOT built

The hook is clean: `rewrite_edge_table` and `rewrite_frame_entity_table` are both
`rewrite_*(plan, aliases, space_id)` applied in sequence in `generator.py`
(995-1029), and a `rewrite_entity_slot_sort` would sit alongside them. The work is
in the gating, not the plumbing:

1. recognise entity -> frame(path) -> slot(type) with a range FILTER on the value;
2. match `frame_type_path` EXACTLY — the index is keyed on the whole array, and a
   loose match returns entities reached by a different path;
3. resolve `entity_type_uuid` and `context_uuid`, declining when either is
   unpinned;
4. decline on every shape it cannot serve, the way `fast_slot_sort` enumerates
   its own declines.

Step 2 is where a mistake returns WRONG ROWS rather than slow ones, which is
what stopped this being written in the same session that measured it: the day
this was found had already produced two wrong-answer bugs from exactly that kind
of near-miss.

### What remains

1.66 seconds and 1,496,337 buffers for 1,017 rows — against 77 ms for the
threshold returning ten times more — is still the "pays for every candidate"
shape `issues/archive/040` documented. Those numbers are now honest, and they are
what the archive's fix family (make the selectivity visible to the planner)
would address. Only the correctness half is done.

**The bench cannot catch the correctness half.** `test_range_comparator_*` takes
its match counts from a manifest and never checks what the query returns, which
is how an unfiltered page was measured precisely for days. Any growth-curve bench
that reports buffers-per-match should assert the row count first, or it is
dividing real work by a number the query never honoured.

---

## Original filing, kept for the record

Filed 2026-08-20 from measurements, before finding the archive and before the
cause was known. Kept because how it stopped being visible is worth more than the
measurement — and because the framing below, "a performance problem", was wrong.

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
