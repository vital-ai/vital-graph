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

`_emit_two_phase` declines the moment the order key is a sort variable. Making
it instead carry ONE extra term join into the ordered phase is the change.

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
