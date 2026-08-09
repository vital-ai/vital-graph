# Twenty-One Comparator Shapes Time Out at 100k for a 25-Row Page

## Status: OPEN — measured 2026-08-09

Every comparator the API accepts, swept against `sp_lead_synth_100k`
(100,000 entities), page of 25, 60s budget per cell, executor fence applied:

| result | cells |
|---|---|
| under 1s | 14 |
| 1-3s | 4 |
| **timed out at 60s** | **21** |

A 25-row page. Not a count, not an export.

## What times out

| comparator | slot classes |
|---|---|
| `ne` | **all five** — text, double, boolean, integer, choice |
| `gt` | double, integer, datetime |
| `gte`, `lt`, `lte` | **datetime only** (numeric ones are 273-361ms) |
| `contains` | text |
| `not_exists` | text, double |
| `is_empty` | text |
| `has_any`, `not_has`, `not_has_any` | text, choice |

And what does not:

| | |
|---|---|
| `eq` | 1.9s text, 2.6s integer, faster elsewhere |
| `gt`/`lt`/`lte` on double, integer | 273-361 ms |
| `exists` | 140-161 ms |
| `has`, `has_all` | 252 ms - 1.2s |

## Three causes, not twenty-one

**1. No typed column for datetimes.** `num_val` is a STORED generated column on
the term table with its own index, added so numeric ranges could be indexed and
*estimated* — PostgreSQL does not collect statistics for indexed expressions.
There is no equivalent for datetimes, so a datetime range compares a CAST
expression. That is the whole difference between `lte/KGDoubleSlot` at 273ms and
`lte/KGDateTimeSlot` timing out. Term table columns today:

    term_uuid, term_text, term_type, lang, datatype_id, created_time,
    dataset, num_val

The fix is the one already taken for numerics, applied again.

**2. Negation and anti-joins.** `ne`, `not_exists`, `is_empty`, `not_has`,
`not_has_any` all time out. `is_empty` was improved from >120s to 1.5s at 10k by
`issues/052`, and still times out at 100k, so that fix helped without being
sufficient. The semi-join rewrite explicitly declines LEFT JOINs, so none of
this family gets the O(page) treatment `issues/040` built.

**3. `contains` and `has_any`.** Text matching and multi-value membership.
Neither has a leaf push-down path, so both evaluate above the join.

## Why this was not visible

`eq` and `gte` are the only comparators with any test coverage, on any slot
class — and they are two of the fast ones. The shape matrix
(`scripts/perf_shape_matrix.py`) classifies plans at 10k, where an O(matches)
plan over a small match set still returns quickly; classification alone reported
these as `set-based` rather than broken. Only timing at scale separates the two.

## Reproduce

Sweep with timing rather than plan classification:

    TSPACE=sp_lead_synth_100k TGRAPH=urn:lead_synth_100k \
      python scripts/perf_comparator_timing.py

## Suggested order

1. **Datetime typed column** — a direct mirror of `num_val`, fixes four cells,
   and the pattern is already proven in this codebase.
2. **The negation family** — five cells, one root cause, and the largest group.
3. **`contains` / `has_any`** — needs a push-down path that does not exist.

## Related

- `issues/052` — the OPTIONAL join fix; helped `is_empty` without closing it
- `issues/040` — the O(page) work, which covers only the shapes the semi-join
  rewrite accepts
