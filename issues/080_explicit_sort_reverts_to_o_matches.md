# An Explicit Sort Reverts Paging to O(matches) — 46ms Becomes 18.6s

## Status: OPEN — measured 2026-08-11 on `sp_lead_synth_100k`

`eq/KGTextSlot`, 25-row page, warm, same criteria throughout:

    no sort                                      46 ms
    sort by entity property (hasName)        18,579 ms      404x
    sort by frame slot                       INVALID SQL — see below

## Why: the sort defeats two-phase paging by construction

    Gather ... rows=9220 (actual time=5.213..26.250)     match set: 26 ms
    ->  Sort  Sort Key: t_v8.term_text, t_v2.term_text
              (actual time=19060.673..19060.898)          19 s
    Limit ... rows=25

The match set is found in 26 ms. The remaining 19 seconds resolves TERM TEXT for
all 9,220 matches so they can be ordered, after which 25 rows are kept.

That is exactly the cost `issues/040` removed for the unsorted case. Two-phase
pages 25 uuids and resolves text for 25; a sort on a text property cannot,
because the order is not known until every candidate's text is resolved. The
fast paths decline here deliberately and correctly — `emit_slice` says so at the
guard: "An explicit sort was requested, so the order key is a sort variable.
Paging on the entity uuid would ignore it."

So this is not a bug in the sort path. It is the sorted path having no
equivalent of the optimisation the unsorted path received, and nothing measuring
the difference.

## Why it was never seen

**No performance test uses `sort_criteria` or an `ORDER BY`.** Verified across
`tests/performance/`. Decision D1's uuid ordering applies only when no sort is
requested, so every benchmark in this repo exercises the unsorted path. The
sorted path — which the UI's query builder offers as a first-class control — has
never been executed by a benchmark.

Same shape as `issues/078` (every test at `offset=0`) and `issues/070` (one
fixed needle per cell): a parameter held constant across every measurement.

## The fix, DESIGN VALIDATED 2026-08-11 — and my first diagnosis was wrong

I first called this structural: "ordering by a value requires knowing the
value". That is true and it is not where the 18.6 s goes.

The full plan is a tower of EIGHT nested loops above the match set, each
estimated `rows=1` against `rows=9220` actual, accumulating 19 ms -> 23,176 ms.
They are resolving TERM TEXT FOR EVERY PROJECTED COLUMN of every match — roughly
74,000 random lookups into a 10.4M-row term table. The sort does not cost that;
it EXPOSES it, because without a sort two-phase pages 25 uuids and only 25 rows
ever reach those joins.

Two measurements settle the direction:

    enable_nestloop=off, +enable_material=off   17,589 ms -> 10,425 ms   1.7x
    resolving ONE column (the sort key) for the
      9,220-row match set, ORDER BY, LIMIT 25                    33 ms

So the misestimate is real but secondary — fixing the join method alone leaves
10 s, because the work itself is 74,000 lookups. The answer is to stop doing
them: resolve the SORT KEY for the match set, take 25, and resolve everything
else for those 25.

That is exactly the two-phase pattern this codebase already uses, extended to
the sorted case:

    phase 1   (entity_uuid, sort_key_text) for all matches
              ORDER BY sort_key LIMIT 25          measured ~33 ms
    phase 2   full projection for those 25 uuids  the existing phase 2

**Where it declines — CORRECTED, having implemented against the wrong answer.**
It is NOT `emit_slice.py:125` / `len(buried) != 1`; that was inferred from the
ORDER BY and never instrumented. Instrumented, `_emit_two_phase` returns at
lines 118-121: for a sorted plan the SEMI-JOIN IS NOT MARKED and there is no
foldable EXISTS join, so it never looks at the ordering. An implementation
built on the ORDER BY theory was written, never reached, and reverted.

The open question is therefore why `mark_semijoins` does not mark a plan
carrying `sort_criteria` when the same plan without one is marked.

What DOES hold about the ordering, verified: the builder emits two keys:

    unsorted   ORDER BY ?entity
    sorted     ORDER BY ASC(?sort_val_0) ?entity

The tie-breaker is `?entity`, the SAME uuid the page already orders by, so a
sorted page ordering on `(sort_key, uuid)` reproduces the SPARQL semantics
exactly. There are no ties to break differently and D1 does not need reopening.

The full step-by-step sequence — decline point, anchor variable, sort column,
page shape, the `needs_ordered_scan` trap, and the gates — is in
`planning/planning_performance/two_phase_kgquery_paging_plan.md` section 8a.

### The concrete shape, traced 2026-08-11

Today's page is (`emit_slice.py`, end of `_emit_two_phase`):

    SELECT DISTINCT ON (col_ref) col_ref AS {sn}__uuid
    FROM {from_sql} WHERE {conds} AND EXISTS ({probe})
    ORDER BY col_ref
    LIMIT {limit}

The sorted variant cannot simply swap the ORDER BY: `DISTINCT ON (col_ref)`
REQUIRES `ORDER BY` to lead with `col_ref`. So the dedup and the ordering have to
be separated —

    SELECT * FROM (
        SELECT DISTINCT ON (col_ref) col_ref AS {sn}__uuid,
               {t_sk}.term_text AS __sort_key
        FROM {from_sql}
        JOIN {term} AS {t_sk} ON {t_sk}.term_uuid = {sort_col}
        WHERE {conds} AND EXISTS ({probe})
        ORDER BY col_ref                      -- required by DISTINCT ON
    ) d
    ORDER BY d.__sort_key {direction}
    LIMIT {limit}

then phase 2 joins the term table for the full projection of those `limit` rows,
exactly as it does today.

`{sort_col}` is the quad column binding the sort variable. The open question — and
the first thing to check when picking this up — is whether that column is already
in `from_sql`: the SPARQL binds `?entity vital:hasName ?sortVar`, so `collect`
should place that quad in the ANCHOR bgp, in which case the join above is the only
addition. If it lands elsewhere, phase 1 needs that leaf pulled in first.

Note what this gives up deliberately: phase 1 now MATERIALISES the match set and
sorts it (9,220 rows, measured 33 ms) instead of early-terminating. That is the
trade — `ctx.needs_ordered_scan` and the `issues/047` fence exist for the
unsorted path and should NOT be asserted here, because there is no ordered scan
to protect.

**Gate before believing any of it:** `tests/performance/test_kgquery_sorted_paging.py`
records 3x at 10k and 203x at 100k. The 100k ratio is the number that has to move,
and the 10k one must not regress. Then `scripts/perf_sweep_diff.py`, 39 cells.

**Not implemented here, deliberately.** It is a change to the paging core —
the code with two prior reverts behind it, gated on the 39-cell sweep — and
landing it half-measured would be worse than leaving it. What is de-risked is
the design and its size: ~33 ms against 17,589 ms is the target, and the fence
alternative (1.7x) is not worth shipping.

## Other options considered, and why they lose

Unlike `078`, there is no obviously correct fix — ordering by a value genuinely
requires knowing the value:

* **An index-backed sort key.** If the sort property has its own index and the
  criteria can be probed against it, the ordered scan could drive the page the
  way the entity uuid does today. That is a schema question as much as a
  planner one.
* **Sort on a column already carried by the anchor.** `hasName` is resolved
  through the term table; if the anchor exposed a sortable projection, the top-N
  could be taken before the join.
* **Accept it and bound it.** 18.6 s is inside the 120 s request deadline, so it
  degrades rather than fails. Deciding this is acceptable is a legitimate
  answer — but it should be a decision, and right now it is an accident.

Measure before choosing: the numbers above are one shape at one scale.

## Secondary: a frame-slot sort generates invalid SQL

    sort_type="entity_frame_slot", slot_type=..., slot_class_uri=...,
    frame_path=[parent, child]
    -> asyncpg.exceptions.UndefinedColumnError: column s0.v14 does not exist

NOT CONFIRMED as a product defect: the frontend only ever sends
`sort_type`/`property_uri`/`direction` (`KGQueryBuilder.tsx:211`) and filters on
`property_uri`, so it never constructs this shape, and the criteria above may
simply be malformed. Two things are worth separating before acting:

1. whether that criteria construction is valid — if it is, generation is broken
   for a documented `sort_type`;
2. whether invalid input should produce invalid SQL at all, rather than a
   rejected request. It currently reaches PostgreSQL and fails there.

## Related

- `issues/040` — paging is O(matches) not O(page). Fixed for the unsorted path.
- `issues/078` — paging past page 1. The other half of the paging surface that
  no benchmark covered.
- `issues/047` — the paging plan flipping to a blocking sort above 51 rows.
