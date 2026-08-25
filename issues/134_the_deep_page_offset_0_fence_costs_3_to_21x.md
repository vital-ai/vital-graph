# The Deep-Page `OFFSET 0` Fence Costs 3–21x On Every Shape Measured

## Status: OPEN — measured 2026-08-25, NOT changed. Needs a full sweep first.

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
