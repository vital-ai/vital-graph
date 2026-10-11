# The Deep-Page `OFFSET 0` Fence Costs 3–21x On Every Shape Measured

## ARCHIVED 2026-10-11 — no longer reproduces: on current code the fence costs 0.9-1.1x on all eight cases this issue priced at 3-21x (identical SQL, 5 alternating runs, rows identical). Nothing to change. Evidence: the last section.
## Status: CLOSED 2026-10-11 — measured 2026-08-25; re-measured, the cost is gone.

`emit_slice.py:796` emits an unconditional optimisation fence on the deep-page
path:

```python
# OFFSET 0 fences the subquery: without it PostgreSQL pulls it up and may
# invert the join. A CTE is unavailable — this returns a fragment.
page = (f"SELECT DISTINCT {p_a}.{csn}__uuid AS {sn}__uuid\n"
        f"FROM (\n{match_set}\nOFFSET 0\n) AS {p_a}\n"
        f"ORDER BY {p_a}.{csn}__uuid\n"
        f"LIMIT {plan.limit} OFFSET {plan.offset}")
```

Removing it is faster on **every** shape measured, by 3x to 21x, with
byte-identical results.

## Measured

Each query run the way the EXECUTOR runs it — fenced with `enable_sort = off`
only where `needs_ordered_scan` is set, never otherwise.

| case | `nos` | with barrier | without | |
|---|---|---|---|---|
| 10k / eq CA | True | 631.3 ms | **34.5 ms** | 18x |
| 10k / eq IL | False | 146.7 ms | **17.0 ms** | 8.6x |
| 10k / eq VT | False | 97.6 ms | **4.7 ms** | 21x |
| 10k / range 0.8 | True | 19.1 ms | **3.5 ms** | 5.5x |
| 100k / eq CA | True | 593.6 ms | **66.1 ms** | 9x |
| 100k / eq IL | False | 618.8 ms | **186.1 ms** | 3.3x |
| 100k / eq VT | False | 757.6 ms | **49.4 ms** | 15x |
| 100k / range 0.8 | True | 22.9 ms | **7.1 ms** | 3.2x |

Correctness: all eight return the same 25 rows in the same order. Zero
differing cases.

Note the win holds for `needs_ordered_scan = True` as well as False, so this is
not simply "the fence is only needed under the fence".

## The trap this nearly fell into

First measurement said the opposite. Removing the barrier and forcing
`enable_sort = off` on a query whose `needs_ordered_scan` is **False** produced
**76,945 ms** and 436,677 rows scanned — apparently damning proof the fence was
load-bearing.

That combination never occurs. The executor fences only when the flag is set.
Measuring a fence the executor would not apply is the same mistake the
"don't fence benchmarks unconditionally" note already records, where a
sort-requiring shape read 273x slow for exactly this reason. Once each query
was fenced the way the executor actually fences it, the barrier lost every
time.

## Why this is filed rather than done

The comment records a real hazard — "PostgreSQL pulls it up and may invert the
join" — and the eight cases here are all lead-fixture criteria queries on one
code path. They do not cover traversal, aggregates, the frame/slot benches, or
any other fixture.

Two precedents, pulling opposite ways:

- **`issues/archive/040`** introduced deep-page fences deliberately, as one of
  five mechanisms that turned paging from O(matches) into O(page). Item 4 is
  this class of fence: *"Without it the correlated subquery is pulled up into a
  hash semi-join, which both computes the full match set and destroys the
  anchor's ordering."* So the hazard is documented and was once real.
  That same issue then REMOVED a different `OFFSET 0` — the push-down probe's —
  with the reasoning now being applied here: *"it existed only to work around
  the bad estimate, and a fence also blocks legitimate optimisations."*
  So a fence in this codebase outliving its cause has precedent.
- **`issues/070`** records a barrier change *"implemented, measured, and
  REVERTED"*: a MATERIALIZED CTE that was 41x worse, with no cell improved.
  So does changing one on a partial sweep.

The distinction that matters: 040's removal followed a fix to the underlying
estimate (the `num_val` generated column). Nothing has changed underneath THIS
fence — the measurement simply says PostgreSQL no longer needs it on these
shapes. That is weaker evidence, and is why it wants the full sweep.

## What to run before changing it

1. Full `tests/performance` with the barrier removed, compared against
   `baselines/query.json` — every bench, not the criteria ones.
2. Conformance, unit and integration, for correctness across shapes the perf
   fixtures do not exercise.
3. If nothing regresses, prefer **gating** it over deleting it, so the
   documented hazard keeps a guard where it could still apply. `issues/040`
   item 4 describes the shape to gate on: a correlated probe that would be
   pulled up into a hash semi-join.

## Relationship to `issues/119`

Found while investigating 119's 46x planner misestimate. That misestimate turns
out to be load-bearing in the good direction and should be left alone; this
fence is where the time actually goes. The two are independent — removing the
fence does not change the estimate or the plan shape, only what PostgreSQL is
allowed to do around it.

## Related

- `issues/119` — the investigation that surfaced this
- `issues/archive/040` — where deep-page fences came from, and one removal
- `issues/070` — a barrier change reverted after measurement

## Re-measured 2026-10-11: the cost no longer exists

The sweep this issue asked for, done in two parts on the test stack:

1. **Full query-tier perf suite**, fence gated to "only over a semi-join" vs as
   shipped, recorded and compared, then 3 alternating rounds of the
   paging/traversal/growth benches. Nothing attributable: `deep_paging.monotonic`
   read the same buffers both ways (333,764 vs 333,757), and every timing
   difference was inside the run-to-run spread of one variant (the growth-curve
   benches swing 3-6x within a variant and never reach the deep-page path at all,
   since they page at offset 0). The traversal plan-shape flips seen in the first
   comparison varied within a variant too, and the fixtures had been re-ANALYZEd
   mid-run by the test app's maintenance job.
2. **This issue's eight cases**, offset 1000, 25 rows, measured on IDENTICAL SQL
   with and without the fence (the current generator's page with the
   `OFFSET 0` re-inserted), 5 alternating runs, test app stopped
   (`test_scripts/perf/_issue134_deep_page_fence.py`):

| case | fenced med ms | unfenced med ms | ratio | rows |
|---|---|---|---|---|
| 10k eq CA | 26.5 | 27.9 | 0.9 | same (0, under 1,000 matches) |
| 10k eq IL | 9.8 | 9.6 | 1.0 | same (0) |
| 10k eq VT | 2.9 | 2.9 | 1.0 | same (0) |
| 10k range 0.8 | 193.2 | 196.1 | 1.0 | same (25) |
| 100k eq CA | 276.7 | 269.6 | 1.0 | same (25) |
| 100k eq IL | 166.3 | 157.1 | 1.1 | same (25) |
| 100k eq VT | 36.7 | 37.3 | 1.0 | same (0) |
| 100k range 0.8 | 255.4 | 238.6 | 1.1 | same (25) |

**0.9-1.1x everywhere, where August measured 3-21x.** `needs_ordered_scan` is
now False on all eight, where three were True then, so the generator has changed
underneath the fence since. A gate was written and tested (kept the fence only
when `_has_semijoin(plan.child)`), and then REVERTED: a plan-shaping change with
no measured benefit is risk for nothing. The fence stays as it is.

If this ever needs reopening, rerun the script above. A ratio well above 1 on
identical SQL is the only evidence that would justify touching it.
